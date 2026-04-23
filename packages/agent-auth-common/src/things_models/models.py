# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Dataclass models for Things 3 objects returned by the client CLIs.

Shared between the bridge (which parses subprocess JSON back into these
dataclasses before re-serialising for HTTP responses) and the client
CLIs (which build and emit them).

Entity identifiers use ``typing.NewType`` wrappers so a ``TodoId`` and
a ``ProjectId`` are not interchangeable from the type checker's
perspective. See ``.claude/instructions/coding-standards.md`` § *Types
and safety*.
"""

from dataclasses import asdict, dataclass
from typing import Any, NewType

TodoId = NewType("TodoId", str)
"""Stable identifier for a :class:`Todo`."""

ProjectId = NewType("ProjectId", str)
"""Stable identifier for a :class:`Project`."""

AreaId = NewType("AreaId", str)
"""Stable identifier for an :class:`Area`."""


@dataclass
class Area:
    id: AreaId
    name: str
    tag_names: list[str]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Area":
        return cls(
            id=AreaId(data["id"]),
            name=data["name"],
            tag_names=list(data.get("tag_names") or []),
        )


@dataclass
class Project:
    id: ProjectId
    name: str
    notes: str
    status: str  # "open" | "completed" | "canceled"
    area_id: AreaId | None
    area_name: str | None
    tag_names: list[str]
    due_date: str | None  # ISO 8601 date (YYYY-MM-DD) or None
    activation_date: str | None
    completion_date: str | None
    cancellation_date: str | None
    creation_date: str | None
    modification_date: str | None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Project":
        raw_area_id = data.get("area_id")
        return cls(
            id=ProjectId(data["id"]),
            name=data["name"],
            notes=data.get("notes", ""),
            status=data.get("status", "open"),
            area_id=AreaId(raw_area_id) if raw_area_id is not None else None,
            area_name=data.get("area_name"),
            tag_names=list(data.get("tag_names") or []),
            due_date=data.get("due_date"),
            activation_date=data.get("activation_date"),
            completion_date=data.get("completion_date"),
            cancellation_date=data.get("cancellation_date"),
            creation_date=data.get("creation_date"),
            modification_date=data.get("modification_date"),
        )


@dataclass
class Todo:
    id: TodoId
    name: str
    notes: str
    status: str  # "open" | "completed" | "canceled"
    project_id: ProjectId | None
    project_name: str | None
    area_id: AreaId | None
    area_name: str | None
    tag_names: list[str]
    due_date: str | None
    activation_date: str | None
    completion_date: str | None
    cancellation_date: str | None
    creation_date: str | None
    modification_date: str | None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Todo":
        raw_project_id = data.get("project_id")
        raw_area_id = data.get("area_id")
        return cls(
            id=TodoId(data["id"]),
            name=data["name"],
            notes=data.get("notes", ""),
            status=data.get("status", "open"),
            project_id=ProjectId(raw_project_id) if raw_project_id is not None else None,
            project_name=data.get("project_name"),
            area_id=AreaId(raw_area_id) if raw_area_id is not None else None,
            area_name=data.get("area_name"),
            tag_names=list(data.get("tag_names") or []),
            due_date=data.get("due_date"),
            activation_date=data.get("activation_date"),
            completion_date=data.get("completion_date"),
            cancellation_date=data.get("cancellation_date"),
            creation_date=data.get("creation_date"),
            modification_date=data.get("modification_date"),
        )
