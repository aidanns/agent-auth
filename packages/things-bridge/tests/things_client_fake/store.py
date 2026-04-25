# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""In-memory ``ThingsClient`` implementation backed by YAML fixtures.

Kept under ``tests/`` (not ``src/``) so it is never shipped in the
production artefact. ``list_id`` is resolved against the store's
``list_memberships`` mapping; all other filters match dataclass fields
directly. Status values are validated against
:data:`things_models.status.VALID_STATUSES`.
"""

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from things_models.errors import ThingsError, ThingsNotFoundError
from things_models.models import Area, AreaId, Project, ProjectId, Todo, TodoId
from things_models.status import VALID_STATUSES, validate_status

_ALLOWED_TOP_LEVEL_KEYS = {"areas", "projects", "todos", "list_memberships"}


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


class FakeThingsClient:
    """In-memory implementation of :class:`things_models.client.ThingsClient`."""

    def __init__(self, store: FakeThingsStore):
        self._store = store

    def list_todos(
        self,
        *,
        list_id: str | None = None,
        project_id: ProjectId | None = None,
        area_id: AreaId | None = None,
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

    def get_todo(self, todo_id: TodoId) -> Todo:
        for todo in self._store.todos:
            if todo.id == todo_id:
                return todo
        raise ThingsNotFoundError(f"todo {todo_id!r} not found")

    def list_projects(self, *, area_id: AreaId | None = None) -> list[Project]:
        if area_id is None:
            return list(self._store.projects)
        return [p for p in self._store.projects if p.area_id == area_id]

    def get_project(self, project_id: ProjectId) -> Project:
        for project in self._store.projects:
            if project.id == project_id:
                return project
        raise ThingsNotFoundError(f"project {project_id!r} not found")

    def list_areas(self) -> list[Area]:
        return list(self._store.areas)

    def get_area(self, area_id: AreaId) -> Area:
        for area in self._store.areas:
            if area.id == area_id:
                return area
        raise ThingsNotFoundError(f"area {area_id!r} not found")


def _tag_names(data: dict[str, Any]) -> list[str]:
    tags = data.get("tag_names", [])
    if tags is None:
        return []
    if not isinstance(tags, list):
        # Guard against YAML scalars like `tag_names: Errand` silently splitting
        # into individual characters via `list("Errand")`.
        raise ThingsError(f"tag_names must be a list, got {type(tags).__name__}: {tags!r}")
    return list(tags)


def _validate_fixture_status(status: str) -> str:
    if status not in VALID_STATUSES:
        raise ThingsError(
            f"Invalid status {status!r} in fixture (expected one of {sorted(VALID_STATUSES)})"
        )
    return status


def _shared_item_kwargs(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data["id"],
        "name": data.get("name", ""),
        "notes": data.get("notes", ""),
        "status": _validate_fixture_status(data.get("status", "open")),
        "area_id": data.get("area_id"),
        "area_name": data.get("area_name"),
        "tag_names": _tag_names(data),
        "due_date": data.get("due_date"),
        "activation_date": data.get("activation_date"),
        "completion_date": data.get("completion_date"),
        "cancellation_date": data.get("cancellation_date"),
        "creation_date": data.get("creation_date"),
        "modification_date": data.get("modification_date"),
    }


def _build_todo(data: dict[str, Any]) -> Todo:
    return Todo(
        **_shared_item_kwargs(data),
        project_id=data.get("project_id"),
        project_name=data.get("project_name"),
    )


def _build_project(data: dict[str, Any]) -> Project:
    return Project(**_shared_item_kwargs(data))


def _build_area(data: dict[str, Any]) -> Area:
    return Area(
        id=data["id"],
        name=data.get("name", ""),
        tag_names=_tag_names(data),
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
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ThingsError(f"fixture must be a YAML mapping, got {type(data).__name__}")

    unknown = set(data) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise ThingsError(
            f"unknown top-level key(s) in fixture: {sorted(unknown)} "
            f"(allowed: {sorted(_ALLOWED_TOP_LEVEL_KEYS)})"
        )

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
