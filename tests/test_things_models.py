"""Tests for the shared Things dataclass models."""

from things_models.models import Area, Project, Todo


def test_todo_to_json_round_trips_all_fields():
    todo = Todo(
        id="abc", name="Buy milk", notes="2L", status="open",
        project_id=None, project_name=None,
        area_id="area-1", area_name="Personal",
        tag_names=["Errand", "P1"],
        due_date="2026-05-01", activation_date=None,
        completion_date=None, cancellation_date=None,
        creation_date="2026-04-15T09:00:00", modification_date="2026-04-15T09:00:00",
    )
    payload = todo.to_json()
    assert payload["id"] == "abc"
    assert payload["status"] == "open"
    assert payload["area_id"] == "area-1"
    assert payload["tag_names"] == ["Errand", "P1"]
    assert payload["project_id"] is None


def test_project_to_json_handles_missing_area():
    project = Project(
        id="p1", name="Q2 Planning", notes="", status="open",
        area_id=None, area_name=None, tag_names=[],
        due_date=None, activation_date=None,
        completion_date=None, cancellation_date=None,
        creation_date=None, modification_date=None,
    )
    payload = project.to_json()
    assert payload["area_id"] is None
    assert payload["tag_names"] == []


def test_area_to_json_minimal():
    area = Area(id="a1", name="Personal", tag_names=["home"])
    assert area.to_json() == {"id": "a1", "name": "Personal", "tag_names": ["home"]}
