# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: the gpg subprocess hangs past the configured timeout.

A gpg invocation that never returns (waiting on a frozen pinentry,
blocked on a full pipe, or a real gpg-agent deadlock) must surface
as a ``GpgError`` after the configured ``timeout_seconds`` AND the
child must be reaped — leaking a per-request subprocess on every
signing hang would exhaust the host's process table on a busy
bridge.
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from gpg_bridge.authz import AgentAuthClient
from gpg_bridge.config import Config
from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_bridge.metrics import build_registry
from gpg_bridge.server import GpgBridgeServer
from gpg_models.errors import GpgBackendUnavailableError, GpgError
from gpg_models.models import SignRequest


def _make_executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(0o755)
    return path


@pytest.mark.covers_function("Sign Payload")
def test_gpg_hang_raises_gpg_error_with_timeout_message(tmp_path: Path) -> None:
    """A gpg subprocess that never writes stdout times out as ``GpgError`` after the deadline.

    The error message must mention the configured timeout so an
    operator triaging from logs can correlate with the bridge's
    ``request_timeout_seconds`` config value rather than guessing
    where the deadline came from.
    """
    script = _make_executable(
        tmp_path / "gpg_hang.sh",
        "#!/usr/bin/env bash\nsleep 30\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=0.5)
    start = time.monotonic()
    with pytest.raises(GpgError, match="timed out after 0.5s"):
        client.sign(SignRequest(local_user="k", payload=b"x"))
    elapsed = time.monotonic() - start
    # Must give up close to the configured deadline, not the script's
    # 30-second sleep. A generous upper bound keeps this stable on
    # loaded CI runners.
    assert elapsed < 5.0, f"timeout took too long: {elapsed:.2f}s"


@pytest.mark.covers_function("Sign Payload")
def test_gpg_hang_partial_stdout_still_times_out(tmp_path: Path) -> None:
    """A gpg subprocess that flushes a partial stdout chunk then hangs still times out.

    Models the case where gpg starts writing the signature but blocks
    on something half-way through (e.g. a wedged gpg-agent prompt).
    Without a wall-clock deadline the bridge would wait forever.
    """
    script = _make_executable(
        tmp_path / "gpg_partial_hang.sh",
        "#!/usr/bin/env bash\nprintf 'partial signature bytes'\nsleep 30\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=0.5)
    with pytest.raises(GpgError, match="timed out"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Sign Payload")
def test_gpg_hang_ignores_sigterm_still_times_out(tmp_path: Path) -> None:
    """A gpg subprocess that traps SIGTERM still gets killed when the bridge times out.

    ``subprocess.run`` with ``timeout=`` raises ``TimeoutExpired`` and
    sends SIGKILL, which cannot be trapped — that's the contract that
    lets the bridge guarantee child reaping even when the gpg script
    tries to be cute about cleanup. Without this fault the bridge
    would have a path that leaks zombies on every misbehaving sign
    request.
    """
    script = _make_executable(
        tmp_path / "gpg_trap_term.sh",
        (
            "#!/usr/bin/env bash\n"
            "trap '' TERM\n"  # ignore SIGTERM
            "sleep 60\n"
        ),
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=0.5)
    start = time.monotonic()
    with pytest.raises(GpgError, match="timed out"):
        client.sign(SignRequest(local_user="k", payload=b"x"))
    elapsed = time.monotonic() - start
    assert elapsed < 5.0, f"SIGKILL fallback took too long: {elapsed:.2f}s"


@pytest.mark.covers_function("Sign Payload")
def test_gpg_hang_raises_backend_unavailable_error(tmp_path: Path) -> None:
    """A wedged gpg subprocess surfaces specifically as ``GpgBackendUnavailableError``.

    Distinguishes the wedge case from generic ``GpgError`` so the
    bridge can map it to ``signing_backend_unavailable`` (HTTP 503)
    rather than ``gpg_unavailable`` (HTTP 502). Without this assertion
    the bridge would lose the structured-error wire signal that
    ``gpg-cli`` uses to print the directed remediation message.
    """
    script = _make_executable(
        tmp_path / "gpg_hang_typed.sh",
        "#!/usr/bin/env bash\nsleep 30\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=0.5)
    with pytest.raises(GpgBackendUnavailableError, match="timed out"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


class _AlwaysAllowAuthz(AgentAuthClient):
    """Test stub that accepts every token / scope without contacting agent-auth."""

    def __init__(self) -> None:
        super().__init__("http://test-fake")

    def validate(self, token: str, required_scope: str, *, description: str | None = None) -> None:
        return None


@pytest.mark.covers_function("Serve GPG Bridge HTTP API")
def test_wedged_gpg_surfaces_signing_backend_unavailable(tmp_path: Path) -> None:
    """End-to-end: a gpg subprocess past the deadline drives 503 ``signing_backend_unavailable``.

    Reproduces the wedge from issue #331: a misconfigured host
    ``gpg-agent`` causes the host gpg subprocess to hang. The fake's
    ``sleep_seconds`` knob simulates that. The bridge's per-subprocess
    timeout fires, the bridge translates the
    ``GpgBackendUnavailableError`` into a 503 with the
    ``signing_backend_unavailable`` code and a remediation hint in
    the body, and the whole thing finishes well inside the
    devcontainer ``gpg-cli`` 30s ceiling so the user sees a
    structured error rather than ``bridge unreachable: timed out``.
    """
    fixture_path = tmp_path / "fixture.yaml"
    # 12s sleep guarantees the bridge's 5s per-subprocess timeout
    # below fires before the fake has a chance to return — without
    # making this test sit through the full 10s production budget.
    fixture_path.write_text(
        yaml.safe_dump(
            {
                "keys": [
                    {
                        "fingerprint": "D7A2B4C0E8F11234567890ABCDEF1234567890AB",
                        "user_ids": ["Test Key <test@example.invalid>"],
                        "aliases": ["test@example.invalid"],
                    }
                ],
                "behaviours": {"sleep_seconds": 12},
            }
        )
    )
    gpg_client = GpgSubprocessClient(
        command=[sys.executable, "-m", "gpg_backend_fake", "--fixtures", str(fixture_path)],
        timeout_seconds=5.0,
    )
    config = Config(port=0)
    registry, metrics = build_registry()
    server = GpgBridgeServer(config, gpg_client, _AlwaysAllowAuthz(), registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        body = json.dumps(
            {
                "local_user": "test@example.invalid",
                "payload_b64": base64.b64encode(b"x").decode("ascii"),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/gpg-bridge/v1/sign",
            data=body,
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
        elapsed = time.monotonic() - start

        # Total time must stay well below the 30s gpg-cli ceiling so
        # the directed error reaches the user before the client gives
        # up. The fault test's per-subprocess deadline is 5s, so a
        # 15s ceiling is comfortable while staying CI-stable.
        assert elapsed < 15.0, f"wedge handling took too long: {elapsed:.2f}s"
        assert status == 503, f"expected 503, got {status}"
        payload = json.loads(raw)
        assert payload["error"] == "signing_backend_unavailable"
        # The remediation hint is part of the wire contract — clients
        # forward it to the user. Asserting the substring keeps the
        # detail message stable enough that ``gpg-cli`` can pass it
        # through verbatim.
        assert "allow-loopback-pinentry" in payload["detail"]
        assert "gpg-bridge-host-setup.md" in payload["detail"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
