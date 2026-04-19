"""CLI subprocess contract tests.

The bridge reasons about any ``things-client-cli-*`` purely through the
JSON-on-stdout + exit-code protocol defined in
:mod:`things_client_common.cli`. These tests run the fake CLI as a real
subprocess and assert the contract shape end-to-end so the protocol
cannot drift silently from the ``ThingsSubprocessClient`` unit tests
(which stub :func:`subprocess.run`).

The AppleScript CLI's command surface is exercised by the same
shared argparse setup and is covered on Darwin by
``test_things_client_applescript_things.py``.
"""

import json
import subprocess
import sys
import textwrap

import pytest

_FIXTURE = textwrap.dedent(
    """
    areas:
      - id: a1
        name: Personal
        tag_names: []
    projects:
      - id: p1
        name: Q2 Planning
        area_id: a1
        area_name: Personal
        status: open
        tag_names: [planning]
    todos:
      - id: t1
        name: Buy milk
        status: open
        tag_names: [Errand]
      - id: t2
        name: Write letter
        status: completed
        tag_names: []
    list_memberships:
      TMTodayListSource: [t1]
    """
).strip()


@pytest.fixture
def fixture_path(tmp_path):
    path = tmp_path / "things.yaml"
    path.write_text(_FIXTURE + "\n", encoding="utf-8")
    return path


def _run(*argv, fixtures=None):
    command = [sys.executable, "-m", "tests.things_client_fake"]
    if fixtures is not None:
        command.extend(["--fixtures", str(fixtures)])
    command.extend(argv)
    return subprocess.run(command, capture_output=True, text=True, timeout=15)


def _json(result: subprocess.CompletedProcess) -> dict:
    assert result.stdout.strip(), f"no JSON on stdout; stderr={result.stderr!r}"
    return json.loads(result.stdout)


def test_todos_list_emits_todos_envelope(fixture_path):
    result = _run("todos", "list", fixtures=fixture_path)
    assert result.returncode == 0
    payload = _json(result)
    assert set(payload.keys()) == {"todos"}
    assert [t["id"] for t in payload["todos"]] == ["t1", "t2"]


def test_todos_list_filters_forwarded(fixture_path):
    result = _run("todos", "list", "--status", "open", fixtures=fixture_path)
    assert result.returncode == 0
    assert [t["id"] for t in _json(result)["todos"]] == ["t1"]


def test_todos_list_by_list_id(fixture_path):
    result = _run("todos", "list", "--list", "TMTodayListSource", fixtures=fixture_path)
    assert result.returncode == 0
    assert [t["id"] for t in _json(result)["todos"]] == ["t1"]


def test_todos_show_emits_todo_envelope(fixture_path):
    result = _run("todos", "show", "t1", fixtures=fixture_path)
    assert result.returncode == 0
    payload = _json(result)
    assert set(payload.keys()) == {"todo"}
    assert payload["todo"]["id"] == "t1"


def test_not_found_exits_with_structured_error(fixture_path):
    result = _run("todos", "show", "does-not-exist", fixtures=fixture_path)
    # Exit code is non-zero; structured body on stdout carries the kind.
    assert result.returncode != 0
    payload = _json(result)
    assert payload["error"] == "not_found"
    assert "does-not-exist" in payload.get("detail", "")


def test_invalid_status_mapped_to_things_unavailable(fixture_path):
    # ``--status`` values outside the argparse ``choices`` are rejected by
    # argparse (exit 2, no JSON). The CLI therefore still relies on argparse
    # for input validation — verify that behaviour too.
    result = _run("todos", "list", "--status", "bogus", fixtures=fixture_path)
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_projects_list_envelope(fixture_path):
    result = _run("projects", "list", fixtures=fixture_path)
    assert result.returncode == 0
    assert [p["id"] for p in _json(result)["projects"]] == ["p1"]


def test_projects_show_not_found(fixture_path):
    result = _run("projects", "show", "p-missing", fixtures=fixture_path)
    assert result.returncode != 0
    assert _json(result)["error"] == "not_found"


def test_areas_list_envelope(fixture_path):
    result = _run("areas", "list", fixtures=fixture_path)
    assert result.returncode == 0
    assert [a["id"] for a in _json(result)["areas"]] == ["a1"]


def test_areas_show_envelope(fixture_path):
    result = _run("areas", "show", "a1", fixtures=fixture_path)
    assert result.returncode == 0
    assert _json(result)["area"]["id"] == "a1"


def test_no_fixtures_defaults_to_empty_store():
    result = _run("todos", "list")
    assert result.returncode == 0
    assert _json(result) == {"todos": []}


def test_missing_subcommand_emits_structured_error_payload():
    # Help on stderr for operators running the CLI directly, plus a
    # structured ``things_unavailable`` envelope on stdout so the bridge
    # can surface the condition through its normal error-mapping path
    # instead of falling back to a generic "no JSON output" protocol
    # violation.
    result = _run()  # no subcommand
    assert result.returncode != 0
    assert _json(result)["error"] == "things_unavailable"
    assert "usage:" in result.stderr.lower()


def test_yaml_load_error_mapped_to_things_unavailable(tmp_path):
    bad = tmp_path / "things.yaml"
    bad.write_text("todos:\n  - id: t1\n    status: done\n", encoding="utf-8")
    result = _run("todos", "list", fixtures=bad)
    assert result.returncode != 0
    payload = _json(result)
    assert payload["error"] == "things_unavailable"
    assert "status" in payload.get("detail", "").lower()
