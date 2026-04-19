"""Docker contract tests for the things-client CLI protocol.

The bridge reasons about any ``things-client-cli-*`` purely through the
JSON-on-stdout + exit-code envelope defined in
:mod:`things_client_common.cli`. These tests run the fake CLI inside the
shared integration test image so the wire protocol is pinned by an
artefact built from the working tree, mirroring the Docker-per-test
pattern used by ``agent-auth`` and ``things-bridge``.

The AppleScript CLI itself is macOS-only and is exercised by the
existing Darwin-gated suite in
``tests/test_things_client_applescript_things.py``.
"""

from __future__ import annotations

import json
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
def seeded_runner(fake_cli_runner):
    fake_cli_runner.write_fixture(_FIXTURE + "\n")
    return fake_cli_runner


def _json(result) -> dict:
    assert result.stdout.strip(), f"no JSON on stdout; stderr={result.stderr!r}"
    return json.loads(result.stdout)


@pytest.mark.covers_function("Fetch Things Data")
def test_todos_list_emits_todos_envelope(seeded_runner):
    result = seeded_runner.run("todos", "list")
    assert result.returncode == 0
    payload = _json(result)
    assert set(payload.keys()) == {"todos"}
    assert [t["id"] for t in payload["todos"]] == ["t1", "t2"]


def test_todos_list_filters_forwarded(seeded_runner):
    result = seeded_runner.run("todos", "list", "--status", "open")
    assert result.returncode == 0
    assert [t["id"] for t in _json(result)["todos"]] == ["t1"]


def test_todos_show_emits_todo_envelope(seeded_runner):
    result = seeded_runner.run("todos", "show", "t1")
    assert result.returncode == 0
    payload = _json(result)
    assert set(payload.keys()) == {"todo"}
    assert payload["todo"]["id"] == "t1"


def test_not_found_exits_with_structured_error(seeded_runner):
    result = seeded_runner.run("todos", "show", "does-not-exist")
    assert result.returncode != 0
    payload = _json(result)
    assert payload["error"] == "not_found"


def test_projects_list_envelope(seeded_runner):
    result = seeded_runner.run("projects", "list")
    assert result.returncode == 0
    assert [p["id"] for p in _json(result)["projects"]] == ["p1"]


def test_areas_list_envelope(seeded_runner):
    result = seeded_runner.run("areas", "list")
    assert result.returncode == 0
    assert [a["id"] for a in _json(result)["areas"]] == ["a1"]


def test_areas_show_envelope(seeded_runner):
    result = seeded_runner.run("areas", "show", "a1")
    assert result.returncode == 0
    assert _json(result)["area"]["id"] == "a1"


def test_projects_show_not_found(seeded_runner):
    result = seeded_runner.run("projects", "show", "p-missing")
    assert result.returncode != 0
    assert _json(result)["error"] == "not_found"


def test_todos_list_by_list_id(seeded_runner):
    result = seeded_runner.run("todos", "list", "--list", "TMTodayListSource")
    assert result.returncode == 0
    assert [t["id"] for t in _json(result)["todos"]] == ["t1"]


def test_invalid_status_rejected_by_argparse(seeded_runner):
    # Argparse owns input validation for ``--status`` choices; the CLI
    # exits non-zero with no JSON envelope (exit 2). Pinning this so a
    # later refactor doesn't silently swap argparse for ad-hoc parsing
    # that would let bogus values reach the Things backend.
    result = seeded_runner.run("todos", "list", "--status", "bogus")
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_no_fixtures_defaults_to_empty_store(fake_cli_runner):
    # Default fixture written by the runner is ``todos: []``; verify the
    # CLI surfaces that as an empty envelope rather than an error.
    result = fake_cli_runner.run("todos", "list")
    assert result.returncode == 0
    assert _json(result) == {"todos": []}


@pytest.mark.covers_function("Fetch Things Data")
def test_yaml_load_error_mapped_to_things_unavailable(fake_cli_runner):
    # Structurally-valid YAML with an invalid Things value (status that
    # isn't in the enum) maps to ``things_unavailable`` so the bridge
    # surfaces backend faults through its normal error-mapping path.
    fake_cli_runner.write_fixture("todos:\n  - id: t1\n    status: done\n")
    result = fake_cli_runner.run("todos", "list")
    assert result.returncode != 0
    assert _json(result)["error"] == "things_unavailable"


def test_missing_subcommand_emits_structured_error_payload(fake_cli_runner):
    # Help on stderr for operators running the CLI directly, plus a
    # structured ``things_unavailable`` envelope on stdout so the bridge
    # can surface the condition through its normal error-mapping path.
    result = fake_cli_runner.run()  # no subcommand
    assert result.returncode != 0
    assert _json(result)["error"] == "things_unavailable"
    assert "usage:" in result.stderr.lower()
