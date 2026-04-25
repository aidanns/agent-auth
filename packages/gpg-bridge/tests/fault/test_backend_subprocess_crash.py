# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: the gpg subprocess crashes.

``GpgSubprocessClient`` is the only place the bridge reasons about
how to drive the host ``gpg`` binary — every crash mode (non-zero
exit without a recognised stderr pattern, killed by signal,
segfault) must surface as ``GpgError``. A raw ``subprocess`` failure
escaping into the HTTP handler would crash the request thread and
leave the bridge exposing an unhelpful ``502`` with no diagnostic
tail.

These tests use ad-hoc shell scripts as the configured ``gpg_command``
— same approach as
``packages/things-bridge/tests/fault/test_things_applescript_failure.py``
— so the production fake stays free of error-injection knobs that
would never serve a real e2e test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_models.errors import GpgError, GpgNoSuchKeyError, GpgPermissionError
from gpg_models.models import SignRequest


def _make_executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(0o755)
    return path


@pytest.mark.covers_function("Sign Payload")
def test_gpg_nonzero_exit_without_recognised_stderr_raises_gpg_error(tmp_path: Path) -> None:
    """A gpg subprocess that exits non-zero with no recognised stderr pattern raises ``GpgError``.

    The bridge classifies known stderr patterns (``No secret key``,
    ``BAD signature``, ``No pinentry``, …) into typed
    :class:`gpg_models.errors.GpgError` subclasses. An unrecognised
    failure must still surface as a generic ``GpgError`` carrying the
    exit code so operators have something to grep for.
    """
    script = _make_executable(
        tmp_path / "gpg_nonzero.sh",
        "#!/usr/bin/env bash\necho 'something obscure broke' >&2\nexit 17\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="exited 17"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Sign Payload")
def test_gpg_killed_by_sigsegv_raises_gpg_error(tmp_path: Path) -> None:
    """A gpg subprocess that segfaults raises ``GpgError`` rather than escaping a signal.

    ``kill -SEGV $$`` from within the script causes the shell itself
    to terminate with a SIGSEGV — Python's ``subprocess.run`` reports
    a negative ``returncode`` (-11). The contract is the same as a
    plain non-zero exit: an unrecognised stderr pattern means a
    generic ``GpgError``.
    """
    script = _make_executable(
        tmp_path / "gpg_sigsegv.sh",
        "#!/usr/bin/env bash\nkill -SEGV $$\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="exited"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Sign Payload")
def test_gpg_killed_by_sigterm_raises_gpg_error(tmp_path: Path) -> None:
    """A gpg subprocess that gets SIGTERM before writing stdout raises ``GpgError``.

    Models the case where systemd / launchd reaps a slow gpg or a
    shared runner-host watchdog kills the process. The bridge must
    not treat the missing signature as success.
    """
    script = _make_executable(
        tmp_path / "gpg_sigterm.sh",
        "#!/usr/bin/env bash\nkill -TERM $$\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="exited"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Sign Payload")
def test_gpg_no_secret_key_stderr_pattern_raises_typed_error(tmp_path: Path) -> None:
    """``No secret key`` stderr surfaces as ``GpgNoSuchKeyError``.

    Mirrors the bridge's classification of host gpg's actual error
    output — the stderr pattern is the contract, not the exit code,
    so a non-zero rc with a recognised pattern still produces the
    typed subclass.
    """
    script = _make_executable(
        tmp_path / "gpg_no_key.sh",
        ("#!/usr/bin/env bash\n" "echo 'gpg: skipped: No secret key' >&2\n" "exit 2\n"),
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgNoSuchKeyError):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Sign Payload")
def test_gpg_pinentry_stderr_pattern_raises_typed_error(tmp_path: Path) -> None:
    """``No pinentry`` stderr surfaces as ``GpgPermissionError``.

    Same shape as the no-secret-key test — confirms the bridge's
    permission-pattern classification works end-to-end against an
    arbitrary script standing in for gpg.
    """
    script = _make_executable(
        tmp_path / "gpg_no_pinentry.sh",
        ("#!/usr/bin/env bash\n" "echo 'gpg: No pinentry' >&2\n" "exit 2\n"),
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgPermissionError):
        client.sign(SignRequest(local_user="k", payload=b"x"))
