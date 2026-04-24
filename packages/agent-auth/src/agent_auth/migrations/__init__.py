# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Hand-rolled numbered-SQL migration runner for the agent-auth store.

Scope: the project keeps its runtime deps minimal
(`cryptography`, `keyring`, `pyyaml`) — adopting Alembic or yoyo for a
single-table-family schema would be disproportionate. Instead this
module ships a small, deterministic runner:

- Migrations are Python ``Migration`` instances declared in
  ``_MIGRATIONS`` below; each carries its ``version`` (monotonic
  int), ``name``, ``up_sql`` and ``down_sql``.
- ``migrate_up(conn)`` applies every migration whose version is
  greater than the recorded current version, each in its own
  transaction, in order.
- ``migrate_down(conn, to_version)`` rolls back to the target
  version inclusive-of-target, running the matching ``down_sql``
  in reverse order.
- Applied versions are recorded in a ``schema_migrations`` table
  bootstrapped by the runner itself (the only DDL allowed outside
  the migration SQL).

The recorder column is deliberately an ``INTEGER PRIMARY KEY`` so a
re-applied version raises a unique-constraint error rather than
silently duplicating.
"""

from agent_auth.migrations.runner import (
    Migration,
    current_version,
    migrate_down,
    migrate_up,
)

__all__ = ["Migration", "current_version", "migrate_down", "migrate_up"]
