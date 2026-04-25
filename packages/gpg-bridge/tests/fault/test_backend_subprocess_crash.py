# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: gpg backend subprocess crashes.

``GpgSubprocessClient`` is the only place the bridge reasons about the
backend CLI subprocess protocol — every crash mode (non-zero exit
without a structured error body, killed by signal, segfault) must
surface as ``GpgError``. A raw ``subprocess`` failure escaping into
the HTTP handler would crash the request thread and leave the bridge
exposing an unhelpful ``502`` with no diagnostic tail.

These tests use ad-hoc shell scripts as the configured backend
command — same approach as
``packages/things-bridge/tests/fault/test_things_applescript_failure.py``
— so the production fake stays free of error-injection knobs that
would never serve a real e2e test.
"""

from __future__ import annotations

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
def test_backend_nonzero_exit_without_payload_raises_gpg_error(tmp_path: Path) -> None:
    """A backend that exits non-zero with no JSON envelope raises ``GpgError``.

    The contract documented in
    :class:`gpg_bridge.gpg_client.GpgSubprocessClient._invoke` is that
    the JSON envelope on stdout is authoritative — if it is missing
    *and* the process exited non-zero we surface a ``GpgError`` with
    the exit code so operators have something to grep for.
    """
    script = _make_executable(
        tmp_path / "backend_nonzero.sh",
        "#!/usr/bin/env bash\necho 'something broke' >&2\nexit 17\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="emitted no JSON output"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_killed_by_sigsegv_raises_gpg_error(tmp_path: Path) -> None:
    """A backend that segfaults raises ``GpgError`` rather than escaping a signal.

    ``kill -SEGV $$`` from within the script causes the shell itself
    to terminate with a SIGSEGV — Python's ``Popen.wait`` reports a
    negative ``returncode`` (-11). The contract is the same as a
    plain non-zero exit: no JSON envelope means ``GpgError``.
    """
    script = _make_executable(
        tmp_path / "backend_sigsegv.sh",
        "#!/usr/bin/env bash\nkill -SEGV $$\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="emitted no JSON output"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_killed_by_sigterm_raises_gpg_error(tmp_path: Path) -> None:
    """A backend that gets SIGTERM before writing stdout raises ``GpgError``.

    Models the case where systemd / launchd reaps a slow backend or
    a shared runner-host watchdog kills the process. The bridge must
    not treat the missing payload as success.
    """
    script = _make_executable(
        tmp_path / "backend_sigterm.sh",
        "#!/usr/bin/env bash\nkill -TERM $$\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="emitted no JSON output"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_nonzero_exit_with_envelope_uses_envelope(tmp_path: Path) -> None:
    """A backend that emits a structured-error envelope wins over its exit code.

    The envelope is authoritative regardless of process exit code
    (see ``Emit Backend JSON Envelope`` in
    ``design/functional_decomposition.yaml``). A backend can crash
    *and* still write a clean ``{"error": "..."}`` envelope; the
    bridge must surface that envelope's typed error rather than a
    bare ``GpgError`` about the exit code.
    """
    script = _make_executable(
        tmp_path / "backend_envelope_with_exit.sh",
        '#!/usr/bin/env bash\nprintf \'{"error": "no_such_key", "detail": "no key x"}\'\nexit 9\n',
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    # ``GpgNoSuchKeyError`` is a ``GpgError`` subclass; matching on the
    # detail string is the strongest assertion that the envelope (not
    # the exit code) drove the response.
    with pytest.raises(GpgError, match="no key x"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_clean_zero_exit_without_payload_raises_gpg_error(tmp_path: Path) -> None:
    """A backend that returns 0 but emits no envelope still raises ``GpgError``.

    Without this guard the bridge would call ``SignResult.from_json``
    on ``{}`` and surface a ``ValueError`` from the model layer rather
    than a typed ``GpgError`` — making the failure look like a bridge
    bug instead of a backend protocol violation.
    """
    script = _make_executable(
        tmp_path / "backend_zero_no_payload.sh",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="emitted no JSON output"):
        client.sign(SignRequest(local_user="k", payload=b"x"))
