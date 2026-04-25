# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for the numbered-SQL migration runner."""

from __future__ import annotations

import sqlite3

import pytest

from agent_auth.migrations import (
    Migration,
    current_version,
    migrate_down,
    migrate_up,
)
from agent_auth.migrations._catalogue import CATALOGUE


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _index_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }


@pytest.fixture
def conn(tmp_path):
    """In-memory-backed SQLite connection shared by a test."""
    path = tmp_path / "mig.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def test_current_version_is_zero_on_empty_db(conn):
    assert current_version(conn) == 0


def test_current_version_creates_tracking_table(conn):
    current_version(conn)
    assert "schema_migrations" in _table_names(conn)


def test_migrate_up_applies_initial_migration(conn):
    applied = migrate_up(conn)
    assert [m.version for m in applied] == [1]
    tables = _table_names(conn)
    assert "token_families" in tables
    assert "tokens" in tables
    assert "idx_tokens_family_id" in _index_names(conn)
    assert current_version(conn) == 1


def test_migrate_up_is_idempotent(conn):
    migrate_up(conn)
    second = migrate_up(conn)
    # No pending migrations on the second pass.
    assert second == []


def test_migrate_down_removes_initial_schema(conn):
    migrate_up(conn)
    reverted = migrate_down(conn, to_version=0)
    assert [m.version for m in reverted] == [1]
    # Down returns to the pre-migration state: tracking table stays
    # (so a future up can find v=0), every declared table is gone.
    tables = _table_names(conn)
    assert tables == {"schema_migrations"}
    assert current_version(conn) == 0


def test_up_down_up_cycles_cleanly(conn):
    migrate_up(conn)
    migrate_down(conn, to_version=0)
    applied = migrate_up(conn)
    # Second up replays the same migration against a cleared tracker.
    assert [m.version for m in applied] == [1]
    assert "token_families" in _table_names(conn)


def test_migrate_up_rejects_duplicate_versions(conn):
    dup = (
        Migration(version=1, name="a", up_sql="", down_sql=""),
        Migration(version=1, name="b", up_sql="", down_sql=""),
    )
    with pytest.raises(ValueError, match="duplicate migration version"):
        migrate_up(conn, migrations=dup)


def test_partial_rollback_with_missing_down_raises_before_touching_db(conn):
    migrations = (
        Migration(
            version=1,
            name="has_down",
            up_sql="CREATE TABLE one (id INTEGER);",
            down_sql="DROP TABLE one;",
        ),
        Migration(
            version=2,
            name="no_down",
            up_sql="CREATE TABLE two (id INTEGER);",
            down_sql="",  # irreversible
        ),
    )
    migrate_up(conn, migrations=migrations)
    with pytest.raises(ValueError, match="refusing partial rollback"):
        migrate_down(conn, to_version=0, migrations=migrations)
    # Nothing was reverted — both tables are still there and the
    # tracker still reflects both versions.
    tables = _table_names(conn)
    assert "one" in tables
    assert "two" in tables


def test_catalogue_versions_are_monotonic_and_unique():
    versions = [m.version for m in CATALOGUE]
    assert versions == sorted(set(versions))
    assert all(m.version > 0 for m in CATALOGUE)


def test_catalogue_initial_migration_is_reversible():
    initial = next(m for m in CATALOGUE if m.version == 1)
    # A stray empty down_sql here would let a "rollback then re-apply"
    # workflow silently fail to clean up — the runner would refuse
    # the partial rollback at runtime, but asserting it at the catalogue
    # level gives a nicer failure message during development.
    assert initial.down_sql.strip(), "initial migration must declare a non-empty down_sql"


def test_migrate_up_failure_surfaces_original_sql_error(conn):
    """A failing up-migration must propagate the SQL error verbatim.

    Regression for #319: ``conn.executescript`` performs an implicit
    ``COMMIT`` before running its payload, so a separately-issued
    ``conn.execute("BEGIN")`` was silently committed and the rollback
    in the except branch raised ``cannot rollback - no transaction
    is active``, masking the real ``OperationalError`` via Python's
    exception chaining. Reproducing the pre-#222-style "table
    already exists" failure is the cleanest way to keep that bug
    pinned: pre-create ``token_families`` so the catalogue's v=1
    ``CREATE TABLE token_families`` fails on first contact.
    """
    conn.execute("CREATE TABLE token_families (id TEXT PRIMARY KEY)")
    conn.commit()

    with pytest.raises(sqlite3.OperationalError) as excinfo:
        migrate_up(conn)

    assert "already exists" in str(excinfo.value)
    # The ``raise`` in the except branch must not have been shadowed by
    # a fresh "cannot rollback" error from ``conn.execute("ROLLBACK")``
    # against a non-existent transaction. Both the chained context
    # (``__context__`` from a bare ``raise`` inside ``except``) and
    # the explicit cause (``__cause__``) are checked because the
    # original masking bug surfaced via ``__context__``.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None or "cannot rollback" not in str(
        excinfo.value.__context__
    )


def test_migrate_down_failure_surfaces_original_sql_error(conn):
    """Same #319 contract as ``migrate_up`` for the reverse path.

    ``migrate_down`` shares the BEGIN/executescript/ROLLBACK pattern,
    so the same masking bug would surface there too. Drop the table
    that the down-migration tries to drop, so its first statement
    fails the way migration 1's would on a pre-#222 store.
    """
    migrations = (
        Migration(
            version=1,
            name="creates_t",
            up_sql="CREATE TABLE t (id INTEGER);",
            down_sql="DROP TABLE t;",
        ),
    )
    migrate_up(conn, migrations=migrations)
    # Pull the table out from under the down-migration; its
    # ``DROP TABLE t`` will then fail with "no such table".
    conn.execute("DROP TABLE t")
    conn.commit()

    with pytest.raises(sqlite3.OperationalError) as excinfo:
        migrate_down(conn, to_version=0, migrations=migrations)

    assert "no such table" in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None or "cannot rollback" not in str(
        excinfo.value.__context__
    )
