# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""End-to-end smoke test: gpg-cli process → gpg-bridge → real host gpg.

Spawns an in-process gpg-bridge that shells out to the real
``gpg-backend-cli-host`` script, which in turn drives a real host
``gpg`` binary against a throwaway ``GNUPGHOME``. The bridge's authz
client is stubbed because the path under test is the subprocess
contract — not agent-auth.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
import threading
from collections.abc import Generator
from pathlib import Path

import pytest

from gpg_bridge.authz import AgentAuthClient
from gpg_bridge.config import Config
from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_bridge.metrics import build_registry
from gpg_bridge.server import GpgBridgeServer

GPG_BIN = shutil.which("gpg")

pytestmark = pytest.mark.skipif(GPG_BIN is None, reason="gpg binary not available")


class _NoopAuthz(AgentAuthClient):
    def __init__(self) -> None:
        super().__init__("http://test-fake")

    def validate(self, token: str, required_scope: str, *, description: str | None = None) -> None:
        # Accept any bearer token.
        return None


def _generate_key(gnupg_home: Path) -> str:
    assert GPG_BIN is not None
    batch = textwrap.dedent(
        """
        %no-protection
        Key-Type: EDDSA
        Key-Curve: ed25519
        Subkey-Type: ECDH
        Subkey-Curve: cv25519
        Name-Real: AgentAuth E2E
        Name-Email: e2e@example.invalid
        Expire-Date: 0
        %commit
        """
    ).strip()
    subprocess.run(
        [GPG_BIN, "--batch", "--homedir", str(gnupg_home), "--gen-key"],
        input=batch,
        capture_output=True,
        check=True,
        text=True,
        timeout=60,
    )
    listing = subprocess.run(
        [
            GPG_BIN,
            "--batch",
            "--homedir",
            str(gnupg_home),
            "--list-secret-keys",
            "--with-colons",
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=15,
    ).stdout
    for line in listing.splitlines():
        if line.startswith("fpr:"):
            return line.split(":")[9]
    raise AssertionError("fingerprint not found in gpg --list-secret-keys output")


@pytest.fixture(scope="module")
def bridge_environment(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[tuple[str, str, Path], None, None]:
    gnupg_home = tmp_path_factory.mktemp("gnupg-e2e")
    gnupg_home.chmod(0o700)
    fingerprint = _generate_key(gnupg_home)

    backend_command = [
        sys.executable,
        "-c",
        (
            "import os, sys;"
            f"os.environ['GNUPGHOME']={str(gnupg_home)!r};"
            "from gpg_backend_cli_host.cli import main;"
            "sys.exit(main())"
        ),
    ]
    gpg = GpgSubprocessClient(command=backend_command, timeout_seconds=30.0)

    registry, metrics = build_registry()
    config = Config(port=0, gpg_backend_command=backend_command)
    server = GpgBridgeServer(config, gpg, _NoopAuthz(), registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", fingerprint, gnupg_home
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


class TestEndToEnd:
    def test_gpg_cli_sign_and_verify_via_bridge(
        self,
        bridge_environment: tuple[str, str, Path],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        bridge_url, fingerprint, _ = bridge_environment
        monkeypatch.setenv("AGENT_AUTH_GPG_BRIDGE_URL", bridge_url)
        monkeypatch.setenv("AGENT_AUTH_GPG_TOKEN", "e2e-token")

        # Run gpg-cli as a subprocess the way git would.
        payload = b"commit payload for e2e\n"
        signed = subprocess.run(
            [
                sys.executable,
                "-m",
                "gpg_cli.cli",
                "--status-fd",
                "2",
                "--keyid-format",
                "long",
                "-bsau",
                fingerprint,
            ],
            input=payload,
            capture_output=True,
            check=False,
            timeout=30,
            env={**__import__("os").environ},
        )
        assert signed.returncode == 0, signed.stderr.decode("utf-8", errors="replace")
        signature_bytes = signed.stdout
        assert signature_bytes.startswith(b"-----BEGIN PGP SIGNATURE-----")
        stderr_text = signed.stderr.decode("utf-8", errors="replace")
        assert "[GNUPG:] SIG_CREATED" in stderr_text

        sig_path = tmp_path / "sig.asc"
        sig_path.write_bytes(signature_bytes)
        data_path = tmp_path / "data.bin"
        data_path.write_bytes(payload)

        verified = subprocess.run(
            [
                sys.executable,
                "-m",
                "gpg_cli.cli",
                "--status-fd",
                "2",
                "--verify",
                str(sig_path),
                str(data_path),
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert verified.returncode == 0, verified.stderr.decode("utf-8", errors="replace")
        stderr_text = verified.stderr.decode("utf-8", errors="replace")
        assert "GOODSIG" in stderr_text or "VALIDSIG" in stderr_text
