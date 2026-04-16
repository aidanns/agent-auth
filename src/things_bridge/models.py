"""Dataclass models for Things objects returned by the bridge."""

from dataclasses import asdict, dataclass


@dataclass
class Area:
    id: str
    name: str
    tag_names: list[str]

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Project:
    id: str
    name: str
    notes: str
    status: str                       # "open" | "completed" | "canceled"
    area_id: str | None
    area_name: str | None
    tag_names: list[str]
    due_date: str | None              # ISO 8601 date (YYYY-MM-DD) or None
    activation_date: str | None
    completion_date: str | None
    cancellation_date: str | None
    creation_date: str | None
    modification_date: str | None

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Todo:
    id: str
    name: str
    notes: str
    status: str                       # "open" | "completed" | "canceled"
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
