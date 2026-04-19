"""Dataclass models for Things 3 objects returned by the client CLIs.

Shared between the bridge (which parses subprocess JSON back into these
dataclasses before re-serialising for HTTP responses) and the client
CLIs (which build and emit them).
"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Area:
    id: str
    name: str
    tag_names: list[str]

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Area":
        return cls(
            id=data["id"],
            name=data["name"],
            tag_names=list(data.get("tag_names") or []),
        )


@dataclass
class Project:
    id: str
    name: str
    notes: str
    status: str  # "open" | "completed" | "canceled"
    area_id: str | None
    area_name: str | None
    tag_names: list[str]
    due_date: str | None  # ISO 8601 date (YYYY-MM-DD) or None
    activation_date: str | None
    completion_date: str | None
    cancellation_date: str | None
    creation_date: str | None
    modification_date: str | None

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Project":
        return cls(
            id=data["id"],
            name=data["name"],
            notes=data.get("notes", ""),
            status=data.get("status", "open"),
            area_id=data.get("area_id"),
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
    id: str
    name: str
    notes: str
    status: str  # "open" | "completed" | "canceled"
    project_id: str | None
    project_name: str | None
    area_id: str | None
    area_name: str | None
    tag_names: list[str]
    due_date: str | None
    activation_date: str | None
    completion_date: str | None
    cancellation_date: str | None
    creation_date: str | None
    modification_date: str | None

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Todo":
        return cls(
            id=data["id"],
            name=data["name"],
            notes=data.get("notes", ""),
            status=data.get("status", "open"),
            project_id=data.get("project_id"),
            project_name=data.get("project_name"),
            area_id=data.get("area_id"),
            area_name=data.get("area_name"),
            tag_names=list(data.get("tag_names") or []),
            due_date=data.get("due_date"),
            activation_date=data.get("activation_date"),
            completion_date=data.get("completion_date"),
            cancellation_date=data.get("cancellation_date"),
            creation_date=data.get("creation_date"),
            modification_date=data.get("modification_date"),
        )
