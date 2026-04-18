"""Shared CLI runner for Things client CLIs.

Both client CLIs build their own ``ThingsClient`` from their own config,
then hand off to :func:`run_cli` here. The argument surface, the JSON
envelopes emitted on stdout, and the exit-code conventions are defined
once in this module and tested once against both CLIs so the bridge's
subprocess contract has a single source of truth.

## Subprocess contract

- argv: ``<program> <resource> <verb> [flags]`` — e.g.
  ``things-client-cli-applescript todos list --status open``.
- stdout: always JSON. Success: ``{"todos": [...]}`` /
  ``{"todo": {...}}`` / ``{"projects": [...]}`` / etc. Error:
  ``{"error": "<code>"}`` (``not_found`` | ``things_permission_denied``
  | ``things_unavailable``).
- exit code: 0 on success, non-zero on error (the JSON body is
  authoritative for the error *kind* — the exit code just distinguishes
  success from failure).
- stderr: used for operator diagnostics only. The bridge captures it
  and forwards to its own stderr; it is never returned in HTTP
  responses.
"""

import argparse
import json
import sys
from typing import Callable

from things_models.client import ThingsClient
from things_models.errors import (
    ThingsError,
    ThingsNotFoundError,
    ThingsPermissionError,
)


EXIT_OK = 0
EXIT_NOT_FOUND = 4
EXIT_PERMISSION_DENIED = 5
EXIT_UNAVAILABLE = 6


def add_read_commands(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Attach the todos / projects / areas sub-commands to ``subparsers``.

    The applescript and fake CLIs each own the top-level parser (so they
    can attach their own flags like ``--osascript-path`` or ``--fixtures``)
    and call into this helper to install the shared read surface.
    """
    todos = subparsers.add_parser("todos", help="Todo commands")
    todos_sub = todos.add_subparsers(dest="todos_command")
    todos_list = todos_sub.add_parser("list", help="List todos")
    todos_list.add_argument(
        "--list",
        help="Built-in list id (e.g. TMInboxListSource, TMTodayListSource)",
    )
    todos_list.add_argument("--project", help="Project id filter")
    todos_list.add_argument("--area", help="Area id filter")
    todos_list.add_argument("--tag", help="Tag name filter")
    todos_list.add_argument(
        "--status",
        choices=("open", "completed", "canceled"),
        help="Status filter",
    )
    todos_show = todos_sub.add_parser("show", help="Show a todo by id")
    todos_show.add_argument("id")

    projects = subparsers.add_parser("projects", help="Project commands")
    projects_sub = projects.add_subparsers(dest="projects_command")
    projects_list = projects_sub.add_parser("list", help="List projects")
    projects_list.add_argument("--area", help="Area id filter")
    projects_show = projects_sub.add_parser("show", help="Show a project by id")
    projects_show.add_argument("id")

    areas = subparsers.add_parser("areas", help="Area commands")
    areas_sub = areas.add_subparsers(dest="areas_command")
    areas_sub.add_parser("list", help="List areas")
    areas_show = areas_sub.add_parser("show", help="Show an area by id")
    areas_show.add_argument("id")


def _dispatch_read(client: ThingsClient, args: argparse.Namespace) -> dict:
    if args.command == "todos":
        if args.todos_command == "list":
            todos = client.list_todos(
                list_id=args.list,
                project_id=args.project,
                area_id=args.area,
                tag=args.tag,
                status=args.status,
            )
            return {"todos": [t.to_json() for t in todos]}
        if args.todos_command == "show":
            todo = client.get_todo(args.id)
            return {"todo": todo.to_json()}
    if args.command == "projects":
        if args.projects_command == "list":
            projects = client.list_projects(area_id=args.area)
            return {"projects": [p.to_json() for p in projects]}
        if args.projects_command == "show":
            project = client.get_project(args.id)
            return {"project": project.to_json()}
    if args.command == "areas":
        if args.areas_command == "list":
            areas = client.list_areas()
            return {"areas": [a.to_json() for a in areas]}
        if args.areas_command == "show":
            area = client.get_area(args.id)
            return {"area": area.to_json()}
    # argparse's ``choices`` already narrow the top-level command; hitting
    # this branch means a sub-command was omitted.
    raise _MissingSubcommandError(args.command)


class _MissingSubcommandError(Exception):
    """Top-level command was valid but no sub-command was supplied."""

    def __init__(self, command: str):
        super().__init__(command)
        self.command = command


def run_cli(
    client_factory: Callable[[argparse.Namespace], ThingsClient],
    parser: argparse.ArgumentParser,
    argv: list[str] | None = None,
) -> int:
    """Parse ``argv`` and run the requested read operation.

    ``client_factory`` receives the parsed namespace so the applescript
    CLI can pull ``--osascript-path`` / env vars and the fake CLI can
    pull ``--fixtures``. The factory may raise
    :class:`~things_models.errors.ThingsError`; that is mapped the same
    way as a client-method failure.
    """
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        _emit_error("things_unavailable", "missing sub-command")
        return EXIT_UNAVAILABLE

    try:
        client = client_factory(args)
        result = _dispatch_read(client, args)
    except ThingsNotFoundError as exc:
        _emit_error("not_found", str(exc))
        return EXIT_NOT_FOUND
    except ThingsPermissionError as exc:
        _emit_error("things_permission_denied", str(exc))
        return EXIT_PERMISSION_DENIED
    except ThingsError as exc:
        _emit_error("things_unavailable", str(exc))
        return EXIT_UNAVAILABLE
    except _MissingSubcommandError as exc:
        parser.print_help(sys.stderr)
        _emit_error("things_unavailable", f"missing {exc.command} sub-command")
        return EXIT_UNAVAILABLE

    print(json.dumps(result), flush=True)
    return EXIT_OK


def _emit_error(code: str, detail: str) -> None:
    print(json.dumps({"error": code, "detail": detail}), flush=True)
