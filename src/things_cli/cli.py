# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI entrypoint for things-cli."""

import argparse
import os
import sys

from things_cli import output
from things_cli.client import BridgeClient
from things_cli.credentials import Credentials, CredentialStore, select_store
from things_cli.errors import (
    BridgeError,
    BridgeForbiddenError,
    BridgeNotFoundError,
    BridgeRateLimitedError,
    BridgeUnauthorizedError,
    BridgeUnavailableError,
    CredentialsBackendError,
    CredentialsNotFoundError,
)


def _default_file_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", "things-cli", "credentials.yaml")


def _resolve_store(args: argparse.Namespace) -> CredentialStore:
    return select_store(
        args.credential_store,
        file_path=args.credentials_file or _default_file_path(),
    )


def handle_login(args: argparse.Namespace) -> int:
    store = _resolve_store(args)
    creds = Credentials(
        access_token=args.access_token,
        refresh_token=args.refresh_token,
        bridge_url=args.bridge_url,
        auth_url=args.auth_url,
        family_id=args.family_id,
    )
    store.save(creds)
    print("Credentials saved.")
    return 0


def handle_logout(args: argparse.Namespace) -> int:
    store = _resolve_store(args)
    store.clear()
    print("Credentials cleared.")
    return 0


def handle_status(args: argparse.Namespace) -> int:
    store = _resolve_store(args)
    try:
        creds = store.load()
    except CredentialsNotFoundError:
        print("No credentials stored.")
        return 1
    print(f"bridge_url:     {creds.bridge_url}")
    print(f"auth_url:       {creds.auth_url}")
    print(f"family_id:      {creds.family_id or '-'}")
    print(f"access_token:   {'<set>' if creds.access_token else '-'}")
    print(f"refresh_token:  {'<set>' if creds.refresh_token else '-'}")
    return 0


def _load_client(args: argparse.Namespace) -> BridgeClient:
    store = _resolve_store(args)
    creds = store.load()
    return BridgeClient(creds, store, ca_cert_path=getattr(args, "ca_cert", "") or "")


def handle_todos_list(args: argparse.Namespace) -> int:
    client = _load_client(args)
    params: dict[str, str] = {}
    if args.list:
        params["list"] = args.list
    if args.project:
        params["project"] = args.project
    if args.area:
        params["area"] = args.area
    if args.tag:
        params["tag"] = args.tag
    if args.status:
        params["status"] = args.status
    data = client.list_todos(params=params or None)
    output.print_todos(data.get("todos", []), as_json=args.json)
    return 0


def handle_todo_show(args: argparse.Namespace) -> int:
    client = _load_client(args)
    data = client.get_todo(args.id)
    output.print_todo(data["todo"], as_json=args.json)
    return 0


def handle_projects_list(args: argparse.Namespace) -> int:
    client = _load_client(args)
    params: dict[str, str] = {}
    if args.area:
        params["area"] = args.area
    data = client.list_projects(params=params or None)
    output.print_projects(data.get("projects", []), as_json=args.json)
    return 0


def handle_project_show(args: argparse.Namespace) -> int:
    client = _load_client(args)
    data = client.get_project(args.id)
    output.print_project(data["project"], as_json=args.json)
    return 0


def handle_areas_list(args: argparse.Namespace) -> int:
    client = _load_client(args)
    data = client.list_areas()
    output.print_areas(data.get("areas", []), as_json=args.json)
    return 0


def handle_area_show(args: argparse.Namespace) -> int:
    client = _load_client(args)
    data = client.get_area(args.id)
    output.print_area(data["area"], as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="things-cli",
        description="CLI client for the Things 3 bridge (read-only).",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--credential-store",
        choices=("auto", "keyring", "file"),
        default="auto",
        help="Credential backend (default: auto)",
    )
    parser.add_argument(
        "--credentials-file",
        help="Path for --credential-store=file (default: ~/.config/things-cli/credentials.yaml)",
    )
    parser.add_argument(
        "--ca-cert",
        help=(
            "Path to a PEM bundle used to verify HTTPS certificates for the bridge and "
            "agent-auth URLs (e.g. a self-signed cert for a devcontainer-to-host setup). "
            "Empty falls back to the system trust store."
        ),
    )

    subparsers = parser.add_subparsers(dest="command")

    login = subparsers.add_parser("login", help="Save credentials for the bridge and auth server")
    login.add_argument(
        "--bridge-url",
        required=True,
        help="Bridge base URL (e.g. http://127.0.0.1:9200)",
    )
    login.add_argument(
        "--auth-url",
        required=True,
        help="agent-auth base URL (e.g. http://127.0.0.1:9100)",
    )
    login.add_argument("--access-token", required=True, help="agent-auth access token")
    login.add_argument("--refresh-token", required=True, help="agent-auth refresh token")
    login.add_argument(
        "--family-id",
        help="agent-auth token family ID (optional, required for reissue)",
    )

    subparsers.add_parser("logout", help="Clear stored credentials")
    subparsers.add_parser("status", help="Show stored credential metadata (values are redacted)")

    # todos
    todos = subparsers.add_parser("todos", help="Todo commands")
    todos_sub = todos.add_subparsers(dest="todos_command")
    todos_list = todos_sub.add_parser("list", help="List todos")
    todos_list.add_argument(
        "--list", help="Built-in list id (e.g. TMInboxListSource, TMTodayListSource)"
    )
    todos_list.add_argument("--project", help="Project id filter")
    todos_list.add_argument("--area", help="Area id filter")
    todos_list.add_argument("--tag", help="Tag name filter")
    todos_list.add_argument(
        "--status", choices=("open", "completed", "canceled"), help="Status filter"
    )
    todos_show = todos_sub.add_parser("show", help="Show a todo by id")
    todos_show.add_argument("id")

    # projects
    projects = subparsers.add_parser("projects", help="Project commands")
    projects_sub = projects.add_subparsers(dest="projects_command")
    projects_list = projects_sub.add_parser("list", help="List projects")
    projects_list.add_argument("--area", help="Area id filter")
    projects_show = projects_sub.add_parser("show", help="Show a project by id")
    projects_show.add_argument("id")

    # areas
    areas = subparsers.add_parser("areas", help="Area commands")
    areas_sub = areas.add_subparsers(dest="areas_command")
    areas_sub.add_parser("list", help="List areas")
    areas_show = areas_sub.add_parser("show", help="Show an area by id")
    areas_show.add_argument("id")

    return parser


_DISPATCH = {
    ("login", None): handle_login,
    ("logout", None): handle_logout,
    ("status", None): handle_status,
    ("todos", "list"): handle_todos_list,
    ("todos", "show"): handle_todo_show,
    ("projects", "list"): handle_projects_list,
    ("projects", "show"): handle_project_show,
    ("areas", "list"): handle_areas_list,
    ("areas", "show"): handle_area_show,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    sub = None
    if args.command == "todos":
        sub = args.todos_command
    elif args.command == "projects":
        sub = args.projects_command
    elif args.command == "areas":
        sub = args.areas_command

    handler = _DISPATCH.get((args.command, sub))
    if handler is None:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except (CredentialsNotFoundError, CredentialsBackendError) as exc:
        output.error(str(exc))
        return 2
    except BridgeUnauthorizedError as exc:
        output.error(f"authentication failed: {exc}. Try `things-cli login` again.")
        return 2
    except BridgeForbiddenError as exc:
        output.error(f"scope denied: {exc}")
        return 3
    except BridgeNotFoundError as exc:
        output.error(f"not found: {exc}")
        return 4
    except BridgeRateLimitedError as exc:
        output.error(f"rate limited: {exc}. Retry after {exc.retry_after_seconds}s.")
        return 6
    except BridgeUnavailableError as exc:
        output.error(f"bridge unavailable: {exc}")
        return 5
    except BridgeError as exc:
        output.error(str(exc))
        return 5


if __name__ == "__main__":
    sys.exit(main())
