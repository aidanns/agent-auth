"""In-memory fake of :class:`things_bridge.things.ThingsClient`.

Selected at runtime via ``things-bridge serve --fake-things[=PATH]`` so the
full HTTP stack can be exercised without ``osascript`` or Things 3.

``list_id`` is resolved against the store's ``list_memberships`` mapping;
all other filters match dataclass fields directly. Status values are
validated via :func:`things_bridge.things.validate_status`. See
``design/decisions/0001-things-client-fake.md``.
"""

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from things_bridge.errors import ThingsNotFoundError
from things_bridge.models import Area, Project, Todo
from things_bridge.things import validate_status


@dataclass
class FakeThingsStore:
    """In-memory container for Things objects consumed by :class:`FakeThingsClient`.

    ``list_memberships`` maps a Things built-in list id (e.g.
    ``TMTodayListSource``) to the set of todo ids that should be returned
    when a caller filters by that list. The real client delegates list
    semantics to Things — the fake cannot, so callers opt in per fixture.
    """

    todos: list[Todo] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)
    list_memberships: dict[str, set[str]] = field(default_factory=dict)

    @property
    def todos_by_id(self) -> dict[str, Todo]:
        return {t.id: t for t in self.todos}

    @property
    def projects_by_id(self) -> dict[str, Project]:
        return {p.id: p for p in self.projects}

    @property
    def areas_by_id(self) -> dict[str, Area]:
        return {a.id: a for a in self.areas}


class FakeThingsClient:
    """In-memory implementation of :class:`things_bridge.things.ThingsClient`."""

    def __init__(self, store: FakeThingsStore):
        self._store = store

    def list_todos(
        self,
        *,
        list_id: str | None = None,
        project_id: str | None = None,
        area_id: str | None = None,
        tag: str | None = None,
        status: str | None = None,
    ) -> list[Todo]:
        validate_status(status)

        results = list(self._store.todos)

        if list_id is not None:
            member_ids = self._store.list_memberships.get(list_id, set())
            results = [t for t in results if t.id in member_ids]
        if project_id is not None:
            results = [t for t in results if t.project_id == project_id]
        if area_id is not None:
            results = [t for t in results if t.area_id == area_id]
        if tag is not None:
            results = [t for t in results if tag in t.tag_names]
        if status is not None:
            results = [t for t in results if t.status == status]

        return results

    def get_todo(self, todo_id: str) -> Todo:
        todo = self._store.todos_by_id.get(todo_id)
        if todo is None:
            raise ThingsNotFoundError(f"todo {todo_id!r} not found")
        return todo

    def list_projects(self, *, area_id: str | None = None) -> list[Project]:
        if area_id is None:
            return list(self._store.projects)
        return [p for p in self._store.projects if p.area_id == area_id]

    def get_project(self, project_id: str) -> Project:
        project = self._store.projects_by_id.get(project_id)
        if project is None:
            raise ThingsNotFoundError(f"project {project_id!r} not found")
        return project

    def list_areas(self) -> list[Area]:
        return list(self._store.areas)

    def get_area(self, area_id: str) -> Area:
        area = self._store.areas_by_id.get(area_id)
        if area is None:
            raise ThingsNotFoundError(f"area {area_id!r} not found")
        return area


def _build_todo(data: dict[str, Any]) -> Todo:
    return Todo(
        id=data["id"],
        name=data.get("name", ""),
        notes=data.get("notes", ""),
        status=data.get("status", "open"),
        project_id=data.get("project_id"),
        project_name=data.get("project_name"),
        area_id=data.get("area_id"),
        area_name=data.get("area_name"),
        tag_names=list(data.get("tag_names", [])),
        due_date=data.get("due_date"),
        activation_date=data.get("activation_date"),
        completion_date=data.get("completion_date"),
        cancellation_date=data.get("cancellation_date"),
        creation_date=data.get("creation_date"),
        modification_date=data.get("modification_date"),
    )


def _build_project(data: dict[str, Any]) -> Project:
    return Project(
        id=data["id"],
        name=data.get("name", ""),
        notes=data.get("notes", ""),
        status=data.get("status", "open"),
        area_id=data.get("area_id"),
        area_name=data.get("area_name"),
        tag_names=list(data.get("tag_names", [])),
        due_date=data.get("due_date"),
        activation_date=data.get("activation_date"),
        completion_date=data.get("completion_date"),
        cancellation_date=data.get("cancellation_date"),
        creation_date=data.get("creation_date"),
        modification_date=data.get("modification_date"),
    )


def _build_area(data: dict[str, Any]) -> Area:
    return Area(
        id=data["id"],
        name=data.get("name", ""),
        tag_names=list(data.get("tag_names", [])),
    )


def load_fake_store(path: str | os.PathLike[str]) -> FakeThingsStore:
    """Read a YAML fixture file and return a populated :class:`FakeThingsStore`.

    Schema (all top-level keys optional):

    .. code-block:: yaml

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
            tag_names: [P1]
        todos:
          - id: t1
            name: Buy milk
            status: open
            project_id: p1
            project_name: Q2 Planning
            tag_names: [Errand]
        list_memberships:
          TMTodayListSource: [t1]
    """
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    areas = [_build_area(a) for a in data.get("areas", []) or []]
    projects = [_build_project(p) for p in data.get("projects", []) or []]
    todos = [_build_todo(t) for t in data.get("todos", []) or []]

    memberships_raw = data.get("list_memberships", {}) or {}
    list_memberships = {
        list_id: set(todo_ids or []) for list_id, todo_ids in memberships_raw.items()
    }

    return FakeThingsStore(
        todos=todos,
        projects=projects,
        areas=areas,
        list_memberships=list_memberships,
    )


__all__ = [
    "FakeThingsClient",
    "FakeThingsStore",
    "load_fake_store",
]
