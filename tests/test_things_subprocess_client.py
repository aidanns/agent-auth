# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for :class:`things_bridge.things_client.ThingsSubprocessClient`.

Verifies the subprocess protocol the bridge speaks to any configured
Things client CLI: argv construction, stdout envelope parsing, exit-code
interpretation, stderr forwarding, timeout handling, bounded stderr
capture, and the mapping from error payloads to the typed
:class:`ThingsError` hierarchy. The live-subprocess path is exercised in
``test_things_bridge_e2e.py``.
"""

import io
import json
import subprocess
from typing import Any

import pytest

from things_bridge.things_client import STDERR_TAIL_MAX_CHARS, ThingsSubprocessClient
from things_bridge.types import ThingsClientCommand, make_things_client_command
from things_models.errors import (
    ThingsError,
    ThingsNotFoundError,
    ThingsPermissionError,
)


class _FakePopen:
    """Minimal ``subprocess.Popen`` double for unit tests.

    Emits ``stdout`` / ``stderr`` as text streams the client drains, and
    surfaces ``returncode`` from :meth:`wait`. Pass ``timeout=True`` to make
    the first :meth:`wait` raise :class:`subprocess.TimeoutExpired` so the
    timeout branch can be exercised.
    """

    def __init__(
        self,
        args: list[str],
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        timeout: bool = False,
    ):
        self.args = args
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self._returncode = returncode
        self._timeout = timeout
        self._wait_calls = 0
        self.returncode: int | None = None
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        self._wait_calls += 1
        if self._timeout and self._wait_calls == 1:
            raise subprocess.TimeoutExpired(cmd=self.args, timeout=timeout or 0.0)
        self.returncode = self._returncode
        return self._returncode

    def kill(self) -> None:
        self.killed = True


@pytest.fixture
def client() -> ThingsSubprocessClient:
    return ThingsSubprocessClient(
        command=make_things_client_command(["fake-client"]), timeout_seconds=1.0
    )


def _patch_popen(monkeypatch, **fake_kwargs) -> list[list[str]]:
    """Record each ``subprocess.Popen`` argv and return a ``_FakePopen``."""
    recorded: list[list[str]] = []

    def _popen(argv, **kwargs):
        recorded.append(argv)
        return _FakePopen(argv, **fake_kwargs)

    monkeypatch.setattr(subprocess, "Popen", _popen)
    return recorded


@pytest.mark.covers_function("Fetch Things Data")
def test_empty_command_rejected():
    # An empty tuple can still be cast to the NewType — the defensive
    # check inside ThingsSubprocessClient catches that belt-and-braces.
    with pytest.raises(ValueError):
        ThingsSubprocessClient(command=ThingsClientCommand(()), timeout_seconds=1.0)


@pytest.mark.covers_function("Fetch Things Data")
def test_make_things_client_command_rejects_empty():
    with pytest.raises(ValueError):
        make_things_client_command([])


@pytest.mark.covers_function("Fetch Things Data")
def test_make_things_client_command_rejects_non_string_element():
    with pytest.raises(TypeError):
        make_things_client_command(["things-client-cli-applescript", 42])


@pytest.mark.covers_function("Fetch Things Data")
def test_list_todos_sends_full_argv(monkeypatch, client):
    recorded = _patch_popen(monkeypatch, stdout='{"todos": []}\n')
    client.list_todos(
        list_id="TMTodayListSource",
        project_id="p1",
        area_id="a1",
        tag="Urgent",
        status="open",
    )
    assert recorded == [
        [
            "fake-client",
            "todos",
            "list",
            "--list",
            "TMTodayListSource",
            "--project",
            "p1",
            "--area",
            "a1",
            "--tag",
            "Urgent",
            "--status",
            "open",
        ]
    ]


def test_list_todos_omits_unset_flags(monkeypatch, client):
    recorded = _patch_popen(monkeypatch, stdout='{"todos": []}')
    client.list_todos()
    assert recorded == [["fake-client", "todos", "list"]]


def test_list_todos_parses_payload(monkeypatch, client):
    payload: dict[str, Any] = {
        "todos": [
            {
                "id": "t1",
                "name": "X",
                "notes": "",
                "status": "open",
                "project_id": None,
                "project_name": None,
                "area_id": None,
                "area_name": None,
                "tag_names": [],
                "due_date": None,
                "activation_date": None,
                "completion_date": None,
                "cancellation_date": None,
                "creation_date": None,
                "modification_date": None,
            }
        ]
    }
    _patch_popen(monkeypatch, stdout=json.dumps(payload))
    todos = client.list_todos()
    assert [t.id for t in todos] == ["t1"]


def test_get_todo_argv_and_envelope(monkeypatch, client):
    payload: dict[str, Any] = {
        "todo": {
            "id": "t2",
            "name": "Y",
            "notes": "",
            "status": "open",
            "project_id": None,
            "project_name": None,
            "area_id": None,
            "area_name": None,
            "tag_names": [],
            "due_date": None,
            "activation_date": None,
            "completion_date": None,
            "cancellation_date": None,
            "creation_date": None,
            "modification_date": None,
        }
    }
    recorded = _patch_popen(monkeypatch, stdout=json.dumps(payload))
    todo = client.get_todo("t2")
    assert recorded == [["fake-client", "todos", "show", "t2"]]
    assert todo.id == "t2"


def test_list_projects_area_filter(monkeypatch, client):
    recorded = _patch_popen(monkeypatch, stdout='{"projects": []}')
    client.list_projects(area_id="a1")
    assert recorded == [["fake-client", "projects", "list", "--area", "a1"]]


def test_areas_commands(monkeypatch, client):
    recorded = _patch_popen(monkeypatch, stdout='{"areas": []}')
    client.list_areas()
    assert recorded == [["fake-client", "areas", "list"]]

    recorded.clear()
    _patch_popen(
        monkeypatch,
        stdout='{"area": {"id": "a1", "name": "Personal", "tag_names": []}}',
    )
    area = client.get_area("a1")
    assert area.id == "a1"


@pytest.mark.covers_function("Fetch Things Data")
def test_not_found_error_mapped(monkeypatch, client):
    _patch_popen(
        monkeypatch,
        stdout='{"error": "not_found", "detail": "todo 123 missing"}',
        returncode=4,
    )
    with pytest.raises(ThingsNotFoundError, match="todo 123 missing"):
        client.get_todo("123")


def test_permission_denied_error_mapped(monkeypatch, client):
    _patch_popen(
        monkeypatch,
        stdout='{"error": "things_permission_denied", "detail": "grant access"}',
        returncode=5,
    )
    with pytest.raises(ThingsPermissionError, match="grant access"):
        client.list_todos()


def test_unknown_error_code_falls_back_to_things_error(monkeypatch, client):
    _patch_popen(
        monkeypatch,
        stdout='{"error": "something_else", "detail": "surprise"}',
        returncode=9,
    )
    with pytest.raises(ThingsError) as exc_info:
        client.list_todos()
    assert not isinstance(exc_info.value, ThingsNotFoundError)
    assert not isinstance(exc_info.value, ThingsPermissionError)
    # Unknown codes must carry the raw code so forward-compat failures are
    # debuggable rather than stripped to just the detail string.
    assert "something_else" in str(exc_info.value)


def test_error_body_with_zero_exit_still_raises(monkeypatch, client):
    # JSON body is authoritative. An ``error`` key on stdout must raise even
    # if the CLI mistakenly reports rc=0; otherwise a buggy client could
    # return a synthetic empty envelope to the bridge without failing.
    _patch_popen(
        monkeypatch,
        stdout='{"error": "not_found", "detail": "x"}',
        returncode=0,
    )
    with pytest.raises(ThingsNotFoundError):
        client.list_todos()


def test_non_zero_exit_without_error_body_raises_things_error(monkeypatch, client):
    _patch_popen(monkeypatch, stdout='{"todos": []}', returncode=1)
    with pytest.raises(ThingsError, match="exited 1"):
        client.list_todos()


def test_empty_stdout_raises_things_error(monkeypatch, client):
    _patch_popen(monkeypatch, stdout="", returncode=0)
    with pytest.raises(ThingsError, match="no JSON output"):
        client.list_todos()


def test_non_json_stdout_raises_things_error(monkeypatch, client):
    _patch_popen(monkeypatch, stdout="not json at all", returncode=0)
    with pytest.raises(ThingsError, match="non-JSON"):
        client.list_todos()


def test_non_object_json_stdout_raises_things_error(monkeypatch, client):
    # A bare list on stdout is a protocol violation — without this guard
    # the bridge would index into a list as though it were a dict.
    _patch_popen(monkeypatch, stdout='["oops"]', returncode=0)
    with pytest.raises(ThingsError, match="non-object JSON"):
        client.list_todos()


def test_missing_binary_raises_things_error(monkeypatch, client):
    def _missing(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "fake-client")

    monkeypatch.setattr(subprocess, "Popen", _missing)
    with pytest.raises(ThingsError, match="not found"):
        client.list_todos()


@pytest.mark.covers_function("Fetch Things Data")
def test_timeout_surfaces_as_things_error_and_logs_partial_stderr(monkeypatch, capfd, client):
    # Operators troubleshoot stuck subprocesses from the bridge's stderr;
    # the HTTP response stays generic. Both paths are exercised here.
    _patch_popen(
        monkeypatch,
        stderr="hung on automation prompt\n",
        timeout=True,
    )
    with pytest.raises(ThingsError, match="timed out"):
        client.list_todos()
    err = capfd.readouterr().err
    assert "timed out" in err
    assert "hung on automation prompt" in err


def test_subprocess_stderr_is_forwarded(monkeypatch, capfd, client):
    # The bridge must surface the client's stderr unchanged — otherwise
    # osascript permission prompts, YAML-load errors, etc. are invisible
    # to operators.
    _patch_popen(
        monkeypatch,
        stdout='{"todos": []}',
        stderr="things-client-cli-applescript: warning\n",
    )
    client.list_todos()
    assert "things-client-cli-applescript: warning" in capfd.readouterr().err


@pytest.mark.covers_function("Fetch Things Data")
def test_timeout_diagnostic_tail_is_bounded(monkeypatch, capfd, client):
    # A misbehaving client that streams multi-megabyte diagnostics must
    # not pin bridge memory. The bridge forwards stderr live and retains
    # only a small tail for the timeout-diagnostic line. This test
    # exercises the tail path by driving the client into the timeout
    # branch with a stderr payload many multiples of the cap; the
    # diagnostic excerpt must be ≤ STDERR_TAIL_MAX_CHARS.
    flood = "x" * (STDERR_TAIL_MAX_CHARS * 4)
    _patch_popen(monkeypatch, stderr=flood, timeout=True)
    with pytest.raises(ThingsError, match="timed out"):
        client.list_todos()
    err = capfd.readouterr().err
    diagnostic_lines = [line for line in err.splitlines() if "timed out" in line]
    assert diagnostic_lines, "expected a timeout diagnostic line"
    diagnostic = diagnostic_lines[-1]
    # The diagnostic format is "...timed out after Ns: <tail excerpt>";
    # split on ": " after the numeric timeout to isolate the excerpt.
    excerpt = diagnostic.rsplit(": ", 1)[-1]
    assert len(excerpt) <= STDERR_TAIL_MAX_CHARS
