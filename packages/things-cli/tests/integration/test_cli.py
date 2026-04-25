# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""End-to-end Docker integration tests for things-cli.

Drives ``things-cli`` inside the ``things-bridge`` container against the
multi-service stack defined in ``things_bridge/conftest.py``. Covers:

- credential-store login + status round-trip
- read commands (``todos list``, ``todos show``, etc.) hitting the real
  bridge through the real authz delegation path
- error mapping when the token's scope is wrong (403 -> exit 3)
"""

from __future__ import annotations

import pytest

from .conftest import parse_json


@pytest.mark.covers_function(
    "Serve Bridge HTTP API",
    "Store CLI Credentials",
    "Handle App Commands",
)
def test_login_and_status_roundtrip(things_cli_invoker):
    payload = things_cli_invoker.stack.agent_auth.create_token("things:read=allow")
    things_cli_invoker.login(payload)
    stdout = things_cli_invoker.run_ok("status")
    assert payload["family_id"] in stdout
    # Tokens themselves must be redacted from `status` output.
    assert payload["access_token"] not in stdout
    assert payload["refresh_token"] not in stdout


@pytest.mark.covers_function(
    "Serve Bridge HTTP API",
    "Send Bridge Request",
    "Display Results",
)
def test_todos_list_returns_seeded_todos(things_cli_logged_in):
    stdout = things_cli_logged_in.run_ok("--json", "todos", "list")
    payload = parse_json(stdout)
    assert {t["id"] for t in payload["todos"]} == {"t1", "t2"}


@pytest.mark.covers_function(
    "Serve Bridge HTTP API",
    "Send Bridge Request",
    "Display Results",
)
def test_todos_show_returns_single_todo(things_cli_logged_in):
    stdout = things_cli_logged_in.run_ok("--json", "todos", "show", "t1")
    payload = parse_json(stdout)
    assert payload["todo"]["id"] == "t1"


@pytest.mark.covers_function("Delegate Token Validation", "Check Scope Authorization")
def test_wrong_scope_exits_with_forbidden_status(things_cli_invoker):
    payload = things_cli_invoker.stack.agent_auth.create_token("outlook:mail:read=allow")
    things_cli_invoker.login(payload)
    exit_code, _stdout, stderr = things_cli_invoker.run("todos", "list")
    # things-cli maps BridgeForbiddenError to exit code 3.
    assert exit_code == 3
    assert "scope" in stderr.lower()


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_unknown_todo_exits_not_found(things_cli_logged_in):
    exit_code, _stdout, stderr = things_cli_logged_in.run(
        "todos",
        "show",
        "does-not-exist",
    )
    # things-cli maps BridgeNotFoundError to exit code 4.
    assert exit_code == 4
    assert "not_found" in stderr or "not found" in stderr.lower()
