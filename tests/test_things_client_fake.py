"""Unit tests for the in-memory :class:`FakeThingsClient`."""

import pytest

from tests.factories import make_project as _project
from tests.factories import make_todo as _todo
from tests.things_client_fake.store import (
    FakeThingsClient,
    FakeThingsStore,
    load_fake_store,
)
from things_models.errors import ThingsError, ThingsNotFoundError
from things_models.models import Area


def test_list_todos_returns_all_without_filters():
    store = FakeThingsStore(todos=[_todo(id="t1"), _todo(id="t2")])
    client = FakeThingsClient(store)
    assert [t.id for t in client.list_todos()] == ["t1", "t2"]


def test_list_todos_filters_by_project_id():
    store = FakeThingsStore(
        todos=[
            _todo(id="t1", project_id="p1"),
            _todo(id="t2", project_id="p2"),
            _todo(id="t3", project_id="p1"),
        ]
    )
    client = FakeThingsClient(store)
    assert [t.id for t in client.list_todos(project_id="p1")] == ["t1", "t3"]


def test_list_todos_filters_by_area_id():
    store = FakeThingsStore(
        todos=[
            _todo(id="t1", area_id="a1"),
            _todo(id="t2", area_id="a2"),
        ]
    )
    client = FakeThingsClient(store)
    assert [t.id for t in client.list_todos(area_id="a2")] == ["t2"]


def test_list_todos_filters_by_tag():
    store = FakeThingsStore(
        todos=[
            _todo(id="t1", tag_names=["Errand", "Urgent"]),
            _todo(id="t2", tag_names=["Deep"]),
            _todo(id="t3", tag_names=["Errand"]),
        ]
    )
    client = FakeThingsClient(store)
    assert [t.id for t in client.list_todos(tag="Errand")] == ["t1", "t3"]


def test_list_todos_filters_by_status():
    store = FakeThingsStore(
        todos=[
            _todo(id="t1", status="open"),
            _todo(id="t2", status="completed"),
            _todo(id="t3", status="canceled"),
        ]
    )
    client = FakeThingsClient(store)
    assert [t.id for t in client.list_todos(status="completed")] == ["t2"]


def test_list_todos_rejects_invalid_status():
    # Shares validate_status with ThingsApplescriptClient so bridge error mapping is uniform.
    client = FakeThingsClient(FakeThingsStore())
    with pytest.raises(ThingsError):
        client.list_todos(status="in_progress")


def test_list_todos_filters_by_list_id_via_memberships():
    store = FakeThingsStore(
        todos=[_todo(id="t1"), _todo(id="t2"), _todo(id="t3")],
        list_memberships={"TMTodayListSource": {"t1", "t3"}},
    )
    client = FakeThingsClient(store)
    assert {t.id for t in client.list_todos(list_id="TMTodayListSource")} == {
        "t1",
        "t3",
    }


def test_list_todos_list_id_without_membership_returns_empty():
    store = FakeThingsStore(todos=[_todo(id="t1")])
    client = FakeThingsClient(store)
    assert client.list_todos(list_id="TMTodayListSource") == []


def test_list_todos_combines_filters():
    store = FakeThingsStore(
        todos=[
            _todo(id="t1", project_id="p1", status="open", tag_names=["A"]),
            _todo(id="t2", project_id="p1", status="completed", tag_names=["A"]),
            _todo(id="t3", project_id="p1", status="open", tag_names=["B"]),
        ]
    )
    client = FakeThingsClient(store)
    result = client.list_todos(project_id="p1", status="open", tag="A")
    assert [t.id for t in result] == ["t1"]


def test_get_todo_returns_match():
    store = FakeThingsStore(todos=[_todo(id="t1"), _todo(id="t2")])
    client = FakeThingsClient(store)
    assert client.get_todo("t2").id == "t2"


def test_get_todo_raises_on_miss():
    client = FakeThingsClient(FakeThingsStore())
    with pytest.raises(ThingsNotFoundError):
        client.get_todo("nope")


def test_list_projects_filters_by_area():
    store = FakeThingsStore(
        projects=[
            _project(id="p1", area_id="a1"),
            _project(id="p2", area_id="a2"),
        ]
    )
    client = FakeThingsClient(store)
    assert [p.id for p in client.list_projects(area_id="a2")] == ["p2"]


def test_get_project_raises_on_miss():
    client = FakeThingsClient(FakeThingsStore())
    with pytest.raises(ThingsNotFoundError):
        client.get_project("nope")


def test_list_areas_and_get_area():
    area = Area(id="a1", name="Personal", tag_names=["home"])
    store = FakeThingsStore(areas=[area])
    client = FakeThingsClient(store)
    assert [a.id for a in client.list_areas()] == ["a1"]
    assert client.get_area("a1").tag_names == ["home"]
    with pytest.raises(ThingsNotFoundError):
        client.get_area("missing")


def test_load_fake_store_reads_full_fixture(tmp_path):
    path = tmp_path / "things.yaml"
    path.write_text(
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
    area_id: a1
    tag_names: [Errand]
list_memberships:
  TMTodayListSource: [t1]
""",
        encoding="utf-8",
    )
    store = load_fake_store(path)
    assert [a.id for a in store.areas] == ["a1"]
    assert [p.id for p in store.projects] == ["p1"]
    assert [t.id for t in store.todos] == ["t1"]
    assert store.list_memberships == {"TMTodayListSource": {"t1"}}
    assert store.todos[0].name == "Buy milk"


def test_load_fake_store_tolerates_missing_optional_fields(tmp_path):
    path = tmp_path / "things.yaml"
    path.write_text("todos:\n  - id: t1\n", encoding="utf-8")
    store = load_fake_store(path)
    todo = store.todos[0]
    assert todo.status == "open"
    assert todo.tag_names == []
    assert todo.project_id is None


def test_load_fake_store_empty_yaml(tmp_path):
    path = tmp_path / "things.yaml"
    path.write_text("", encoding="utf-8")
    store = load_fake_store(path)
    assert store.todos == []
    assert store.projects == []
    assert store.areas == []
    assert store.list_memberships == {}


def test_load_fake_store_rejects_unknown_top_level_key(tmp_path):
    # Typos in top-level keys (e.g. `todoss:`) must fail loud, otherwise
    # fixtures silently load as empty and tests pass for the wrong reason.
    path = tmp_path / "things.yaml"
    path.write_text("todoss:\n  - id: t1\n", encoding="utf-8")
    with pytest.raises(ThingsError, match="unknown top-level key"):
        load_fake_store(path)


def test_load_fake_store_rejects_non_mapping_root(tmp_path):
    path = tmp_path / "things.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ThingsError, match="YAML mapping"):
        load_fake_store(path)


def test_load_fake_store_rejects_scalar_tag_names(tmp_path):
    # Guard against `tag_names: Errand` silently becoming ["E","r","r","a","n","d"].
    path = tmp_path / "things.yaml"
    path.write_text("todos:\n  - id: t1\n    tag_names: Errand\n", encoding="utf-8")
    with pytest.raises(ThingsError, match="tag_names must be a list"):
        load_fake_store(path)


def test_load_fake_store_rejects_invalid_status(tmp_path):
    path = tmp_path / "things.yaml"
    path.write_text("todos:\n  - id: t1\n    status: done\n", encoding="utf-8")
    with pytest.raises(ThingsError, match="Invalid status"):
        load_fake_store(path)
