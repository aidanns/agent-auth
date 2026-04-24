# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Protocol defining the read-only Things 3 client surface.

Shared between the two client CLIs (which implement it) and the
bridge's subprocess client (which delegates to it through JSON).
"""

from typing import Protocol

from things_models.models import Area, AreaId, Project, ProjectId, Todo, TodoId


class ThingsClient(Protocol):
    """Read-only Things 3 client surface."""

    def list_todos(
        self,
        *,
        list_id: str | None = None,
        project_id: ProjectId | None = None,
        area_id: AreaId | None = None,
        tag: str | None = None,
        status: str | None = None,
    ) -> list[Todo]: ...

    def get_todo(self, todo_id: TodoId) -> Todo: ...

    def list_projects(self, *, area_id: AreaId | None = None) -> list[Project]: ...

    def get_project(self, project_id: ProjectId) -> Project: ...

    def list_areas(self) -> list[Area]: ...

    def get_area(self, area_id: AreaId) -> Area: ...
