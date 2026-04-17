"""Tests for AppleScript runner and ThingsApplescriptClient.

These tests avoid shelling out to osascript — they substitute a deterministic
fake runner and assert the script content and TSV parsing behaviour.
"""

import pytest

from things_bridge.errors import ThingsError, ThingsNotFoundError
from things_bridge.things import (
    NEWLINE_PLACEHOLDER,
    TAB_PLACEHOLDER,
    ThingsApplescriptClient,
    _TODO_FIELDS,
    _PROJECT_FIELDS,
    _AREA_FIELDS,
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

    client.list_todos(list_id="TMTodayListSource")
    assert 'to dos of list id "TMTodayListSource"' in runner.last_script

    client.list_todos(project_id="proj-123")
    assert 'to dos of project id "proj-123"' in runner.last_script

    client.list_todos(area_id="area-9")
    assert 'to dos of area id "area-9"' in runner.last_script

    client.list_todos(tag="Urgent")
    assert 'to dos of tag "Urgent"' in runner.last_script

    client.list_todos()
    # No filter → default source
    assert "repeat with t in (to dos)" in runner.last_script


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
    assert "repeat with p in (projects)" in runner.last_script


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
