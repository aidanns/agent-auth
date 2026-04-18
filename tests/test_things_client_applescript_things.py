"""Tests for AppleScript runner and ThingsApplescriptClient.

Most tests avoid shelling out to osascript — they substitute a deterministic
fake runner and assert the script content and TSV parsing behaviour. A small
number of tests exercise the real AppleScriptRunner on macOS to guard against
regressions where the emitted script is rejected by osascript itself.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from things_client_applescript.things import (
    NEWLINE_PLACEHOLDER,
    TAB_PLACEHOLDER,
    AppleScriptRunner,
    ThingsApplescriptClient,
    _HELPERS,
    _TODO_FIELDS,
    _PROJECT_FIELDS,
    _AREA_FIELDS,
)
from things_models.errors import ThingsError, ThingsNotFoundError

_darwin_only = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("osascript") is None,
    reason="osascript is only available on macOS",
)


def _things3_installed() -> bool:
    for candidate in (
        "/Applications/Things3.app",
        os.path.expanduser("~/Applications/Things3.app"),
    ):
        if Path(candidate).is_dir():
            return True
    return False


_requires_things3 = pytest.mark.skipif(
    sys.platform != "darwin"
    or shutil.which("osascript") is None
    or not _things3_installed(),
    reason="requires macOS with Things 3 installed",
)


class FakeRunner:
    def __init__(self, output: str = ""):
        self.output = output
        self.last_script: str | None = None

    def run(self, script: str) -> str:
        self.last_script = script
        return self.output


def _todo_row(values: dict) -> str:
    # Fill defaults so the row always has len(_TODO_FIELDS) tab-separated columns.
    defaults = {k: "missing value" for k in _TODO_FIELDS}
    defaults.update(values)
    return "\t".join(defaults[k] for k in _TODO_FIELDS)


def _project_row(values: dict) -> str:
    defaults = {k: "missing value" for k in _PROJECT_FIELDS}
    defaults.update(values)
    return "\t".join(defaults[k] for k in _PROJECT_FIELDS)


def _area_row(values: dict) -> str:
    defaults = {k: "missing value" for k in _AREA_FIELDS}
    defaults.update(values)
    return "\t".join(defaults[k] for k in _AREA_FIELDS)


def test_list_todos_parses_tsv_rows():
    runner = FakeRunner(output=(
        _todo_row({"id": "t1", "name": "Buy milk", "status": "open", "tag_names": "Errand, P1"}) + "\n"
        + _todo_row({"id": "t2", "name": "Call dentist", "status": "completed",
                     "project_id": "p1", "project_name": "Health",
                     "due_date": "2026-05-01T00:00:00",
                     "completion_date": "2026-04-15T10:00:00"}) + "\n"
    ))
    client = ThingsApplescriptClient(runner)
    todos = client.list_todos()
    assert len(todos) == 2
    assert todos[0].id == "t1"
    assert todos[0].name == "Buy milk"
    assert todos[0].status == "open"
    assert todos[0].tag_names == ["Errand", "P1"]
    assert todos[0].project_id is None
    assert todos[1].status == "completed"
    assert todos[1].project_name == "Health"
    assert todos[1].due_date == "2026-05-01T00:00:00"


def test_list_todos_filter_builds_expected_source():
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)

    # Each filter must scope the batched "every to do of <scope>" reads to
    # the caller-requested collection. The fallback per-element loop that
    # walks project/area handlers must also share the scope so results stay
    # consistent across fields.
    client.list_todos(list_id="TMTodayListSource")
    assert 'every to do of list id "TMTodayListSource"' in runner.last_script
    assert 'to dos of list id "TMTodayListSource"' in runner.last_script

    client.list_todos(project_id="proj-123")
    assert 'every to do of project id "proj-123"' in runner.last_script
    assert 'to dos of project id "proj-123"' in runner.last_script

    client.list_todos(area_id="area-9")
    assert 'every to do of area id "area-9"' in runner.last_script
    assert 'to dos of area id "area-9"' in runner.last_script

    client.list_todos(tag="Urgent")
    assert 'every to do of tag "Urgent"' in runner.last_script
    assert 'to dos of tag "Urgent"' in runner.last_script

    client.list_todos()
    # No filter -> unscoped batched read.
    assert "id of every to do\n" in runner.last_script


def test_list_todos_status_filter_validates():
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    with pytest.raises(ThingsError):
        client.list_todos(status="archived")


def test_list_todos_status_filter_appears_in_script():
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    client.list_todos(status="open")
    assert '"open"' in runner.last_script


# -- Performance regression: batched AppleScript shape --
# An unfiltered `todos list` against a real Things 3 database (several
# hundred todos) must stay well under the AppleScriptRunner default
# timeout. The client therefore reads each property from the todo
# *collection* in one Apple Event, not per-todo. These tests assert the
# structural shape of the emitted AppleScript so a refactor can't silently
# reintroduce per-todo round-trips that timeout at 30s on large databases.


def test_list_todos_reads_properties_from_collection_in_one_apple_event():
    """Unfiltered listing must not issue a per-todo round-trip per property.

    Failure mode this guards: each property read inside a ``repeat with t
    in (to dos) … property of t`` body is its own Apple Event, so an
    N-todo database pays roughly ``properties * N`` round-trips and blows
    past the osascript timeout on real data. The batched form reads each
    property from the collection in a single Apple Event, making the cost
    of the unfiltered path roughly constant in the number of properties
    plus one pass for the optional project/area relationships.
    """
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    client.list_todos()
    script = runner.last_script
    assert script is not None

    # Every property that can be batched must be read via the collection
    # form. If any of these regress to per-element reads the timeout
    # symptom returns.
    for prop in (
        "id", "name", "notes", "status", "tag names",
        "due date", "activation date", "completion date",
        "cancellation date", "creation date", "modification date",
    ):
        assert f"{prop} of every to do" in script, (
            f"expected batched collection read for {prop!r} in emitted script"
        )

    # The unfiltered body must not contain a per-element property read of
    # the form ``id of t`` / ``name of t`` / ``notes of t``. The only
    # ``repeat`` that remains legitimately iterates todos to call the
    # try-wrapped project/area handlers — it does not touch ids, names,
    # notes, statuses, tag names, or dates.
    forbidden_per_element_reads = (
        "id of t)", "name of t)", "notes of t)", "status of t)",
        "tag names of t)", "due date of t)",
    )
    for bad in forbidden_per_element_reads:
        assert bad not in script, (
            f"unfiltered todos list reintroduced per-element read {bad!r}"
        )


def test_list_todos_empty_database_returns_no_todos():
    """Edge case that AppleScript's collection form handles differently
    from a ``repeat`` loop: an empty ``id of every to do`` returns ``{}``
    and the zip loop must short-circuit to an empty output without error.
    """
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    assert client.list_todos() == []


def test_list_todos_filtered_scope_uses_batched_reads():
    """Each filter variant must route the batched reads through the same
    caller-supplied scope. Otherwise a filtered query would silently read
    the entire database and then discard rows client-side.
    """
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)

    for kwargs, expected in [
        ({"list_id": "TMTodayListSource"}, 'every to do of list id "TMTodayListSource"'),
        ({"project_id": "p1"}, 'every to do of project id "p1"'),
        ({"area_id": "a1"}, 'every to do of area id "a1"'),
        ({"tag": "P1"}, 'every to do of tag "P1"'),
    ]:
        client.list_todos(**kwargs)
        script = runner.last_script
        assert script is not None
        assert f"id of {expected}" in script
        assert f"name of {expected}" in script
        assert f"due date of {expected}" in script


def test_list_projects_reads_properties_from_collection_in_one_apple_event():
    """Mirrors the todos regression for projects, so the same performance
    cliff cannot reappear on ``projects list`` as the project count grows.
    """
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    client.list_projects()
    script = runner.last_script
    assert script is not None
    for prop in ("id", "name", "notes", "status", "tag names", "due date"):
        assert f"{prop} of every project" in script, (
            f"expected batched collection read for {prop!r} in projects script"
        )


def test_list_areas_reads_properties_from_collection_in_one_apple_event():
    """Mirrors the todos regression for areas."""
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    client.list_areas()
    script = runner.last_script
    assert script is not None
    for prop in ("id", "name", "tag names"):
        assert f"{prop} of every area" in script, (
            f"expected batched collection read for {prop!r} in areas script"
        )


def test_unescape_handles_placeholders():
    # Verifies the framing round-trips tabs/newlines that would otherwise break TSV parsing.
    payload_notes = f"line1{NEWLINE_PLACEHOLDER}line2{TAB_PLACEHOLDER}tabbed"
    row = _todo_row({"id": "t", "name": "n", "notes": payload_notes, "status": "open"})
    runner = FakeRunner(output=row + "\n")
    client = ThingsApplescriptClient(runner)
    [todo] = client.list_todos()
    assert todo.notes == "line1\nline2\ttabbed"


def test_missing_value_becomes_none():
    row = _todo_row({"id": "t", "name": "n", "status": "open"})
    runner = FakeRunner(output=row + "\n")
    client = ThingsApplescriptClient(runner)
    [todo] = client.list_todos()
    assert todo.project_id is None
    assert todo.area_id is None
    assert todo.tag_names == []
    assert todo.due_date is None


def test_get_todo_raises_not_found_on_empty_output():
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    with pytest.raises(ThingsNotFoundError):
        client.get_todo("unknown-id")


def test_get_todo_parses_single_row():
    row = _todo_row({"id": "t1", "name": "Buy milk", "status": "open"})
    runner = FakeRunner(output=row + "\n")
    client = ThingsApplescriptClient(runner)
    todo = client.get_todo("t1")
    assert todo.id == "t1"
    assert '"t1"' in runner.last_script


def test_list_projects_filter_by_area():
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    client.list_projects(area_id="area-1")
    assert 'projects of area id "area-1"' in runner.last_script


def test_list_projects_default_source():
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    client.list_projects()
    # Batched read reads each property from the whole collection in a
    # single Apple Event.
    assert "id of every project\n" in runner.last_script


def test_list_projects_parses_rows():
    row = _project_row({"id": "p1", "name": "Q2", "status": "open", "area_id": "a1",
                        "area_name": "Work", "tag_names": "P1"})
    runner = FakeRunner(output=row + "\n")
    client = ThingsApplescriptClient(runner)
    [project] = client.list_projects()
    assert project.id == "p1"
    assert project.area_id == "a1"
    assert project.tag_names == ["P1"]


def test_list_areas_parses_rows():
    row = _area_row({"id": "a1", "name": "Personal", "tag_names": "home, routine"})
    runner = FakeRunner(output=row + "\n")
    client = ThingsApplescriptClient(runner)
    [area] = client.list_areas()
    assert area.id == "a1"
    assert area.name == "Personal"
    assert area.tag_names == ["home", "routine"]


def test_get_area_not_found():
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    with pytest.raises(ThingsNotFoundError):
        client.get_area("none")


def test_malformed_row_raises_things_error():
    runner = FakeRunner(output="only\ta\tfew\tcols\n")
    client = ThingsApplescriptClient(runner)
    with pytest.raises(ThingsError):
        client.list_todos()


# -- AppleScript injection guards --
# A list_id / project_id / area_id / tag containing a raw newline could break
# out of the AppleScript string literal; a raw U+241E / U+241F could smuggle
# a tab or newline through the TSV framing. These must be rejected before the
# script is built, not silently quoted.

@pytest.mark.parametrize("bad", [
    "foo\nbar",
    "foo\rbar",
    "foo\tbar",
    f"foo{TAB_PLACEHOLDER}bar",
    f"foo{NEWLINE_PLACEHOLDER}bar",
    "foo\x00bar",
    "foo\x1bbar",
    # DEL — path-segment ids were already rejected here by _safe_id, but
    # tag/project/area/list query params bypass _safe_id and reach _quote
    # directly, so _quote must also reject DEL to stay consistent.
    "foo\x7fbar",
])
def test_list_todos_rejects_injection_via_filter_ids(bad):
    """Control characters in caller-supplied ids must not reach AppleScript."""
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    with pytest.raises(ThingsError):
        client.list_todos(project_id=bad)
    assert runner.last_script is None


def test_get_todo_rejects_injection_in_id():
    runner = FakeRunner(output="")
    client = ThingsApplescriptClient(runner)
    with pytest.raises(ThingsError):
        client.get_todo("foo\nbar")
    assert runner.last_script is None


@_darwin_only
def test_helper_applescript_is_valid_syntax(tmp_path):
    """The AppleScript prelude shared by every bridge request must compile.

    If this script is invalid, every ``list`` and ``show`` endpoint fails
    with an opaque ``502 things_unavailable`` — clients can't tell the
    bridge is broken from the error taxonomy alone. FakeRunner-based tests
    don't catch this because they never hand the script to osascript.
    """
    # osacompile parses the script without executing any ``tell application``
    # block, so we can validate syntax without requiring Things 3 or
    # Automation permissions.
    out_path = tmp_path / "helpers.scpt"
    source_path = tmp_path / "helpers.applescript"
    # Append a no-op reference so the compiler accepts a helpers-only file.
    source_path.write_text(_HELPERS + "\nreturn\n")

    result = subprocess.run(
        ["osacompile", "-o", str(out_path), str(source_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"osacompile rejected _HELPERS: {result.stderr.strip()}"
    )


@pytest.mark.covers_function("Execute External System Interaction")
@_requires_things3
def test_list_projects_executes_against_things():
    """End-to-end smoke test against real Things 3.

    Guards the full osascript compile-and-execute path: if the emitted
    script is invalid or its handlers raise at runtime, clients see an
    opaque ``502 things_unavailable`` rather than useful data. FakeRunner
    short-circuits that path, so every other test in this file would pass
    while production breaks.

    Uses ``list_projects`` rather than ``list_todos`` because project counts
    are typically small enough to complete well under the 30s default
    timeout on any Mac. Requires Things 3 and Automation permissions.
    """
    client = ThingsApplescriptClient(AppleScriptRunner())
    client.list_projects()


@_darwin_only
def test_osascript_failure_writes_diagnostic_to_stderr(capfd):
    """Clients receive a deliberately-sparse ``502 things_unavailable`` on
    AppleScript failures so response bodies never leak host filesystem paths
    or script fragments. Operators need the same detail on the server's own
    stderr to diagnose why requests are failing.
    """
    runner = AppleScriptRunner()
    with pytest.raises(ThingsError):
        # Deliberately invalid AppleScript so osascript exits non-zero.
        runner.run('this is not valid applescript "')

    captured = capfd.readouterr()
    # Should name the subsystem so mixed stderr streams stay greppable,
    # and include enough of osascript's message to be useful.
    assert "things-client-cli-applescript" in captured.err
    assert "osascript" in captured.err.lower()


def test_osascript_timeout_writes_diagnostic_to_stderr(capfd, monkeypatch):
    """Clients receive the same sparse ``502 things_unavailable`` whether
    osascript failed synchronously or ran past its timeout. Without a
    stderr diagnostic operators cannot distinguish a stuck Things 3 from
    other AppleScript failures, which was painful during a live ``todos
    list`` debugging session.
    """
    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", _raise_timeout)

    runner = AppleScriptRunner(timeout_seconds=0.5)
    with pytest.raises(ThingsError):
        runner.run("tell application \"Things3\" to return \"\"")

    captured = capfd.readouterr()
    # Same greppability and subsystem-naming requirements as the
    # exit-code branch, plus the word "timed out" so operators can
    # distinguish the failure mode at a glance.
    assert "things-client-cli-applescript" in captured.err
    assert "timed out" in captured.err


def test_osascript_timeout_surfaces_partial_stderr(capfd, monkeypatch):
    """When osascript prints something before being killed (e.g. a pending
    permissions prompt that never resolved), operators need to see that hint
    on the bridge's stderr — otherwise they are left with only a bare timeout
    line and no way to tell the two failure shapes apart.
    """
    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=kwargs.get("timeout"),
            stderr="waiting on user to grant automation access\n",
        )

    monkeypatch.setattr(subprocess, "run", _raise_timeout)

    runner = AppleScriptRunner(timeout_seconds=0.5)
    with pytest.raises(ThingsError):
        runner.run("tell application \"Things3\" to return \"\"")

    captured = capfd.readouterr()
    assert "things-client-cli-applescript" in captured.err
    assert "timed out" in captured.err
    assert "waiting on user to grant automation access" in captured.err
