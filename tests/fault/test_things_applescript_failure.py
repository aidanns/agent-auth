# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: Things client subprocess failures.

things-bridge's ``ThingsSubprocessClient`` is responsible for
translating every subprocess failure mode (missing binary, timeout,
non-zero exit, non-JSON stdout) into a ``ThingsError``. A subprocess
failure that escapes as a raw ``FileNotFoundError`` or
``subprocess.TimeoutExpired`` would crash the HTTP handler; these
tests assert the translation happens.
"""

import pytest

from things_bridge.errors import ThingsError
from things_bridge.things_client import ThingsSubprocessClient
from things_bridge.types import make_things_client_command


def test_missing_binary_raises_things_error() -> None:
    """A non-existent client command surfaces as ThingsError, not FileNotFoundError."""
    client = ThingsSubprocessClient(
        command=make_things_client_command(["/nonexistent/things-client"]), timeout_seconds=1.0
    )
    with pytest.raises(ThingsError, match="things client not found"):
        client.list_todos()


def test_subprocess_timeout_raises_things_error(tmp_path) -> None:
    """A client that never returns surfaces as ThingsError with a timeout message."""
    script = tmp_path / "hang.sh"
    script.write_text("#!/usr/bin/env bash\nsleep 30\n")
    script.chmod(0o755)
    client = ThingsSubprocessClient(
        command=make_things_client_command([str(script)]), timeout_seconds=0.3
    )
    with pytest.raises(ThingsError, match="timed out"):
        client.list_todos()


def test_subprocess_nonzero_exit_without_payload_raises_things_error(tmp_path) -> None:
    """Non-zero exit with no structured error body raises ThingsError."""
    script = tmp_path / "fail.sh"
    script.write_text('#!/usr/bin/env bash\necho "boom" >&2\nexit 2\n')
    script.chmod(0o755)
    client = ThingsSubprocessClient(
        command=make_things_client_command([str(script)]), timeout_seconds=2.0
    )
    with pytest.raises(ThingsError, match="rc=2"):
        client.list_todos()


def test_subprocess_non_json_stdout_raises_things_error(tmp_path) -> None:
    """A client that writes non-JSON to stdout surfaces as ThingsError."""
    script = tmp_path / "junk.sh"
    script.write_text('#!/usr/bin/env bash\necho "<html>not json</html>"\n')
    script.chmod(0o755)
    client = ThingsSubprocessClient(
        command=make_things_client_command([str(script)]), timeout_seconds=2.0
    )
    with pytest.raises(ThingsError, match="non-JSON"):
        client.list_todos()
