#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

# Verify every `agent-auth token *` CLI subcommand has a corresponding HTTP
# route registered on AgentAuthHandler. Prevents adding a new CLI subcommand
# without exposing it over HTTP (or vice versa).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

cd "${REPO_ROOT}"

if [[ ! -f pyproject.toml ]]; then
  echo "verify-token-cli-http-parity: pyproject.toml not found; run from repo root" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "verify-token-cli-http-parity: 'uv' is required on PATH" >&2
  exit 1
fi

uv run python3 - <<'PY'
import inspect
import sys

try:
    from agent_auth.cli import COMMAND_HANDLERS
    from agent_auth.server import AgentAuthHandler
except ImportError as e:
    print(f"verify-token-cli-http-parity: could not import agent_auth modules: {e}", file=sys.stderr)
    sys.exit(1)

# The handler dispatches through class-level route tables
# (_POST_ROUTES / _GET_ROUTES). Join every literal path key so renames
# that slip out of the tables still trip this gate. Also fall back to
# the whole-class source in case a future refactor inlines the
# routes back into do_POST / do_GET.
routing_source_parts: list[str] = []
for table_attr in ("_POST_ROUTES", "_GET_ROUTES"):
    table = getattr(AgentAuthHandler, table_attr, None)
    if isinstance(table, dict):
        routing_source_parts.extend(table.keys())
routing_source_parts.append(inspect.getsource(AgentAuthHandler))
routing_source = "\n".join(routing_source_parts)

missing = []
for cmd in sorted(COMMAND_HANDLERS):
    method = f"_handle_token_{cmd}"
    route = f"/agent-auth/v1/token/{cmd}"
    if not hasattr(AgentAuthHandler, method):
        missing.append(f"  token {cmd!r}: no handler method {method!r}")
    elif route not in routing_source:
        missing.append(
            f"  token {cmd!r}: method exists but route {route!r} is not wired via the route tables or do_POST/do_GET"
        )

if missing:
    print("verify-token-cli-http-parity: agent-auth token subcommands missing HTTP routes:", file=sys.stderr)
    for line in missing:
        print(line, file=sys.stderr)
    sys.exit(1)

print("verify-token-cli-http-parity: every 'agent-auth token *' subcommand has a matching HTTP route.")
PY
