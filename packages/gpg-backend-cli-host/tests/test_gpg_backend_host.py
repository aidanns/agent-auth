# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""End-to-end tests against the real host ``gpg`` binary.

Generates a throwaway keypair into an ephemeral ``GNUPGHOME``, signs a
payload through ``HostGpgBackend``, and verifies the signature. Skipped
automatically if ``gpg`` is not on ``PATH`` or refuses to run in batch
mode.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from gpg_backend_cli_host.gpg import HostGpgBackend
from gpg_models.errors import GpgBadSignatureError, GpgNoSuchKeyError
from gpg_models.models import SignRequest, VerifyRequest

GPG_BIN = shutil.which("gpg")

pytestmark = pytest.mark.skipif(GPG_BIN is None, reason="gpg binary not available")


def _generate_key(gnupg_home: Path) -> str:
    """Generate a throwaway keypair and return its fingerprint."""
    assert GPG_BIN is not None
    batch = textwrap.dedent(
        """
        %no-protection
        Key-Type: EDDSA
        Key-Curve: ed25519
        Subkey-Type: ECDH
        Subkey-Curve: cv25519
        Name-Real: AgentAuth Test
        Name-Email: agent-auth-test@example.invalid
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
            parts = line.split(":")
            return parts[9]
    raise AssertionError("fingerprint not found in gpg --list-secret-keys output")


@pytest.fixture(scope="module")
def host_fingerprint(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    gnupg_home = tmp_path_factory.mktemp("gnupg")
    gnupg_home.chmod(0o700)
    fingerprint = _generate_key(gnupg_home)
    return gnupg_home, fingerprint


@pytest.fixture
def backend(host_fingerprint: tuple[Path, str]) -> HostGpgBackend:
    gnupg_home, _ = host_fingerprint
    assert GPG_BIN is not None
    return HostGpgBackend(gpg_path=GPG_BIN, gnupg_home=str(gnupg_home))


class TestHostGpgBackend:
    def test_sign_round_trips_to_verify(
        self, backend: HostGpgBackend, host_fingerprint: tuple[Path, str]
    ) -> None:
        _, fingerprint = host_fingerprint
        payload = b"agent-auth commit test payload"
        sign_result = backend.sign(SignRequest(local_user=fingerprint, payload=payload, armor=True))
        assert sign_result.signature.startswith(b"-----BEGIN PGP SIGNATURE-----")
        assert "[GNUPG:] SIG_CREATED" in sign_result.status_text
        assert sign_result.resolved_key_fingerprint.endswith(fingerprint[-16:])

        verify_result = backend.verify(
            VerifyRequest(signature=sign_result.signature, payload=payload)
        )
        assert verify_result.exit_code == 0
        assert "[GNUPG:] GOODSIG" in verify_result.status_text
        assert "[GNUPG:] VALIDSIG" in verify_result.status_text

    def test_tampered_payload_fails_verify(
        self, backend: HostGpgBackend, host_fingerprint: tuple[Path, str]
    ) -> None:
        _, fingerprint = host_fingerprint
        payload = b"original"
        sign_result = backend.sign(SignRequest(local_user=fingerprint, payload=payload, armor=True))
        with pytest.raises(GpgBadSignatureError):
            backend.verify(VerifyRequest(signature=sign_result.signature, payload=b"tampered"))

    def test_unknown_key_raises_no_such_key(self, backend: HostGpgBackend) -> None:
        with pytest.raises(GpgNoSuchKeyError):
            backend.sign(
                SignRequest(
                    local_user="0000000000000000000000000000000000000000",
                    payload=b"x",
                    armor=True,
                )
            )
