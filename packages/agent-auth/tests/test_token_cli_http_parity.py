# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Parity check: every ``agent-auth token *`` CLI subcommand has an HTTP route.

Ported from ``packages/agent-auth/scripts/verify-token-cli-http-parity.sh``
(issue #465). The bash script ran as a standalone CI workflow; this pytest
version lives inside the unit-test matrix so the assertion is exercised on
every PR via ``test-unit.yml`` instead of a dedicated workflow.

The check guards against drift between the CLI's ``COMMAND_HANDLERS`` map
(``agent_auth.cli``) and the HTTP route tables on ``AgentAuthHandler``
(``agent_auth.server``) — adding a new ``agent-auth token <verb>``
subcommand without exposing it over HTTP (or vice versa) is a regression
this test catches.
"""

import inspect

from agent_auth.cli import COMMAND_HANDLERS
from agent_auth.server import AgentAuthHandler


def test_every_token_cli_subcommand_has_a_matching_http_route() -> None:
    # The handler dispatches through class-level route tables
    # (_POST_ROUTES / _GET_ROUTES). Join every literal path key so
    # renames that slip out of the tables still trip this gate. Also
    # fall back to the whole-class source in case a future refactor
    # inlines the routes back into do_POST / do_GET.
    routing_source_parts: list[str] = []
    for table_attr in ("_POST_ROUTES", "_GET_ROUTES"):
        table = getattr(AgentAuthHandler, table_attr, None)
        if isinstance(table, dict):
            routing_source_parts.extend(table.keys())
    routing_source_parts.append(inspect.getsource(AgentAuthHandler))
    routing_source = "\n".join(routing_source_parts)

    missing: list[str] = []
    for cmd in sorted(COMMAND_HANDLERS):
        method = f"_handle_token_{cmd}"
        route = f"/agent-auth/v1/token/{cmd}"
        if not hasattr(AgentAuthHandler, method):
            missing.append(f"  token {cmd!r}: no handler method {method!r}")
        elif route not in routing_source:
            missing.append(
                f"  token {cmd!r}: method exists but route {route!r} is "
                f"not wired via the route tables or do_POST/do_GET"
            )

    assert not missing, "agent-auth token subcommands missing HTTP routes:\n" + "\n".join(missing)
