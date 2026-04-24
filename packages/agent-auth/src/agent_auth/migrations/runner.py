# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Migration runner: apply / roll back versioned SQL against a sqlite3 connection."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Migration:
    """A single numbered migration.

    ``version`` must be unique and monotonically increasing across
    the declared migrations; ``up_sql`` and ``down_sql`` are raw
    SQL executed via ``conn.executescript``. Keep each migration
    focused — one logical schema change per version — so partial
    roll-backs stay debuggable.
    """

    version: int
    name: str
    up_sql: str
    down_sql: str


# The ``schema_migrations`` bootstrap is the only DDL the runner
# owns directly. All other tables are expressed as migrations.
_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


def _ensure_bootstrap(conn: sqlite3.Connection) -> None:
    conn.execute(_BOOTSTRAP_SQL)
    conn.commit()


def current_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied migration version, or 0 if none applied."""
    _ensure_bootstrap(conn)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0])


def _declared_sorted(migrations: tuple[Migration, ...]) -> tuple[Migration, ...]:
    seen: set[int] = set()
    for m in migrations:
        if m.version in seen:
            raise ValueError(f"duplicate migration version {m.version}")
        seen.add(m.version)
    return tuple(sorted(migrations, key=lambda m: m.version))


def migrate_up(
    conn: sqlite3.Connection,
    migrations: tuple[Migration, ...] | None = None,
) -> list[Migration]:
    """Apply every pending migration in order; return the ones applied.

    Each migration runs in its own transaction: partial schema
    changes from a failed migration do not leak into subsequent
    ones. The tracking row is written in the same transaction as
    the DDL so the recorded version never drifts from the actual
    schema state.
    """
    _ensure_bootstrap(conn)
    if migrations is None:
        from agent_auth.migrations._catalogue import CATALOGUE

        migrations = CATALOGUE
    ordered = _declared_sorted(migrations)
    applied_rows = {
        int(v) for (v,) in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    applied: list[Migration] = []
    for migration in ordered:
        if migration.version in applied_rows:
            continue
        # Each migration is its own BEGIN/COMMIT so partial failures
        # don't leave the DB in a half-applied state.
        conn.execute("BEGIN")
        try:
            conn.executescript(migration.up_sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, datetime.now(UTC).isoformat()),
            )
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        applied.append(migration)
    return applied


def migrate_down(
    conn: sqlite3.Connection,
    to_version: int = 0,
    migrations: tuple[Migration, ...] | None = None,
) -> list[Migration]:
    """Roll back applied migrations down to (but not through) ``to_version``.

    Migrations whose version is strictly greater than
    ``to_version`` are reverted in reverse order. A missing
    ``down_sql`` on any selected migration raises ``ValueError``
    before any rollback is applied — partial roll-backs with
    irreversible steps would be the worst of both worlds.
    """
    _ensure_bootstrap(conn)
    if migrations is None:
        from agent_auth.migrations._catalogue import CATALOGUE

        migrations = CATALOGUE
    ordered = _declared_sorted(migrations)
    applied_rows = {
        int(v) for (v,) in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    to_revert = [m for m in ordered if m.version > to_version and m.version in applied_rows]
    to_revert.sort(key=lambda m: m.version, reverse=True)

    missing_down = [m for m in to_revert if not m.down_sql.strip()]
    if missing_down:
        versions = ", ".join(str(m.version) for m in missing_down)
        raise ValueError(f"refusing partial rollback: migrations {versions} have no down_sql")

    reverted: list[Migration] = []
    for migration in to_revert:
        conn.execute("BEGIN")
        try:
            conn.executescript(migration.down_sql)
            conn.execute("DELETE FROM schema_migrations WHERE version = ?", (migration.version,))
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        reverted.append(migration)
    return reverted
