# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for :class:`things_bridge.things_client.ThingsSubprocessClient`.

Verifies the subprocess protocol the bridge speaks to any configured
Things client CLI: argv construction, stdout envelope parsing, exit-code
interpretation, stderr forwarding, timeout handling, and the mapping
from error payloads to the typed :class:`ThingsError` hierarchy. The
live-subprocess path is exercised in ``test_things_bridge_e2e.py``.
"""

import json
import subprocess

import pytest

from things_bridge.things_client import ThingsSubprocessClient
from things_models.errors import (
    ThingsError,
    ThingsNotFoundError,
    ThingsPermissionError,
)


class _FakeCompleted:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def client() -> ThingsSubprocessClient:
    return ThingsSubprocessClient(command=["fake-client"], timeout_seconds=1.0)


def _patch_run(monkeypatch, completed: _FakeCompleted) -> list[list[str]]:
    """Record each subprocess.run argv and return ``completed`` unchanged."""
    recorded: list[list[str]] = []

    def _run(argv, **kwargs):
        recorded.append(argv)
        return completed

    monkeypatch.setattr(subprocess, "run", _run)
    return recorded


@pytest.mark.covers_function("Fetch Things Data")
def test_empty_command_rejected():
    with pytest.raises(ValueError):
        ThingsSubprocessClient(command=[], timeout_seconds=1.0)


@pytest.mark.covers_function("Fetch Things Data")
def test_list_todos_sends_full_argv(monkeypatch, client):
    recorded = _patch_run(monkeypatch, _FakeCompleted(stdout='{"todos": []}\n'))
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
    recorded = _patch_run(monkeypatch, _FakeCompleted(stdout='{"todos": []}'))
    client.list_todos()
    assert recorded == [["fake-client", "todos", "list"]]


def test_list_todos_parses_payload(monkeypatch, client):
    payload = {
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
    _patch_run(monkeypatch, _FakeCompleted(stdout=json.dumps(payload)))
    todos = client.list_todos()
    assert [t.id for t in todos] == ["t1"]


def test_get_todo_argv_and_envelope(monkeypatch, client):
    payload = {
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
    recorded = _patch_run(monkeypatch, _FakeCompleted(stdout=json.dumps(payload)))
    todo = client.get_todo("t2")
    assert recorded == [["fake-client", "todos", "show", "t2"]]
    assert todo.id == "t2"


def test_list_projects_area_filter(monkeypatch, client):
    recorded = _patch_run(monkeypatch, _FakeCompleted(stdout='{"projects": []}'))
    client.list_projects(area_id="a1")
    assert recorded == [["fake-client", "projects", "list", "--area", "a1"]]


def test_areas_commands(monkeypatch, client):
    recorded = _patch_run(monkeypatch, _FakeCompleted(stdout='{"areas": []}'))
    client.list_areas()
    assert recorded == [["fake-client", "areas", "list"]]

    recorded.clear()
    _patch_run(
        monkeypatch,
        _FakeCompleted(stdout='{"area": {"id": "a1", "name": "Personal", "tag_names": []}}'),
    )
    area = client.get_area("a1")
    assert area.id == "a1"


@pytest.mark.covers_function("Fetch Things Data")
def test_not_found_error_mapped(monkeypatch, client):
    _patch_run(
        monkeypatch,
        _FakeCompleted(stdout='{"error": "not_found", "detail": "todo 123 missing"}', returncode=4),
    )
    with pytest.raises(ThingsNotFoundError, match="todo 123 missing"):
        client.get_todo("123")


def test_permission_denied_error_mapped(monkeypatch, client):
    _patch_run(
        monkeypatch,
        _FakeCompleted(
            stdout='{"error": "things_permission_denied", "detail": "grant access"}',
            returncode=5,
        ),
    )
    with pytest.raises(ThingsPermissionError, match="grant access"):
        client.list_todos()


def test_unknown_error_code_falls_back_to_things_error(monkeypatch, client):
    _patch_run(
        monkeypatch,
        _FakeCompleted(stdout='{"error": "something_else", "detail": "surprise"}', returncode=9),
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
    _patch_run(
        monkeypatch,
        _FakeCompleted(stdout='{"error": "not_found", "detail": "x"}', returncode=0),
    )
    with pytest.raises(ThingsNotFoundError):
        client.list_todos()


def test_non_zero_exit_without_error_body_raises_things_error(monkeypatch, client):
    _patch_run(monkeypatch, _FakeCompleted(stdout='{"todos": []}', returncode=1))
    with pytest.raises(ThingsError, match="exited 1"):
        client.list_todos()


def test_empty_stdout_raises_things_error(monkeypatch, client):
    _patch_run(monkeypatch, _FakeCompleted(stdout="", returncode=0))
    with pytest.raises(ThingsError, match="no JSON output"):
        client.list_todos()


def test_non_json_stdout_raises_things_error(monkeypatch, client):
    _patch_run(monkeypatch, _FakeCompleted(stdout="not json at all", returncode=0))
    with pytest.raises(ThingsError, match="non-JSON"):
        client.list_todos()


def test_non_object_json_stdout_raises_things_error(monkeypatch, client):
    # A bare list on stdout is a protocol violation — without this guard
    # the bridge would index into a list as though it were a dict.
    _patch_run(monkeypatch, _FakeCompleted(stdout='["oops"]', returncode=0))
    with pytest.raises(ThingsError, match="non-object JSON"):
        client.list_todos()


def test_missing_binary_raises_things_error(monkeypatch, client):
    def _missing(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "fake-client")

    monkeypatch.setattr(subprocess, "run", _missing)
    with pytest.raises(ThingsError, match="not found"):
        client.list_todos()


@pytest.mark.covers_function("Fetch Things Data")
def test_timeout_surfaces_as_things_error_and_logs_partial_stderr(monkeypatch, capfd, client):
    # Operators troubleshoot stuck subprocesses from the bridge's stderr;
    # the HTTP response stays generic. Both paths are exercised here.
    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=kwargs.get("timeout"),
            stderr="hung on automation prompt\n",
        )

    monkeypatch.setattr(subprocess, "run", _timeout)
    with pytest.raises(ThingsError, match="timed out"):
        client.list_todos()
    err = capfd.readouterr().err
    assert "timed out" in err
    assert "hung on automation prompt" in err


def test_subprocess_stderr_is_forwarded(monkeypatch, capfd, client):
    # The bridge must surface the client's stderr unchanged — otherwise
    # osascript permission prompts, YAML-load errors, etc. are invisible
    # to operators.
    _patch_run(
        monkeypatch,
        _FakeCompleted(stdout='{"todos": []}', stderr="things-client-cli-applescript: warning\n"),
    )
    client.list_todos()
    assert "things-client-cli-applescript: warning" in capfd.readouterr().err
