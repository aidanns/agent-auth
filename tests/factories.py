# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared test factories for Things model fixtures."""

from typing import Any

from things_models.models import Area, Project, Todo


def make_todo(**overrides: Any) -> Todo:
    defaults = dict(
        id="t1",
        name="",
        notes="",
        status="open",
        project_id=None,
        project_name=None,
        area_id=None,
        area_name=None,
        tag_names=[],
        due_date=None,
        activation_date=None,
        completion_date=None,
        cancellation_date=None,
        creation_date=None,
        modification_date=None,
    )
    defaults.update(overrides)
    return Todo(**defaults)


def make_project(**overrides: Any) -> Project:
    defaults = dict(
        id="p1",
        name="",
        notes="",
        status="open",
        area_id=None,
        area_name=None,
        tag_names=[],
        due_date=None,
        activation_date=None,
        completion_date=None,
        cancellation_date=None,
        creation_date=None,
        modification_date=None,
    )
    defaults.update(overrides)
    return Project(**defaults)


def make_area(**overrides: Any) -> Area:
    defaults = dict(id="a1", name="", tag_names=[])
    defaults.update(overrides)
    return Area(**defaults)
