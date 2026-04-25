# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: gpg backend subprocess hangs past the configured timeout.

A backend that never returns (waiting on a frozen pinentry, blocked
on a full pipe, or a real gpg-agent deadlock) must surface as a
``GpgError`` after the configured ``timeout_seconds`` AND the child
must be reaped — leaking a per-request subprocess on every signing
hang would exhaust the host's process table on a busy bridge.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_models.errors import GpgError
from gpg_models.models import SignRequest


def _make_executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(0o755)
    return path


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_hang_raises_gpg_error_with_timeout_message(tmp_path: Path) -> None:
    """A backend that never writes stdout times out as ``GpgError`` after the deadline.

    The error message must mention the configured timeout so an
    operator triaging from logs can correlate with the bridge's
    ``request_timeout_seconds`` config value rather than guessing
    where the deadline came from.
    """
    script = _make_executable(
        tmp_path / "backend_hang.sh",
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


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_hang_partial_stdout_still_times_out(tmp_path: Path) -> None:
    """A backend that flushes a partial stdout chunk then hangs still times out.

    Models the case where the backend opens its envelope (``{``) but
    blocks on something half-way through. The drain thread keeps
    reading bytes — without a wall-clock deadline the bridge would
    wait forever.
    """
    script = _make_executable(
        tmp_path / "backend_partial_hang.sh",
        '#!/usr/bin/env bash\nprintf \'{"signature_b64": "\'\nsleep 30\n',
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=0.5)
    with pytest.raises(GpgError, match="timed out"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_hang_ignores_sigterm_still_times_out(tmp_path: Path) -> None:
    """A backend that traps SIGTERM still gets killed when the bridge times out.

    ``Popen.kill`` sends SIGKILL which cannot be trapped — that's the
    contract that lets the bridge guarantee child reaping even when
    the backend script tries to be cute about cleanup. Without this
    fault the bridge would have a path that leaks zombies on every
    misbehaving sign request.
    """
    script = _make_executable(
        tmp_path / "backend_trap_term.sh",
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
