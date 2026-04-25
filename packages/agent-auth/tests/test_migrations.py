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
