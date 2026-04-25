# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: SQLite write errors and read-only database.

The store is the only component that actually owns the database handle,
so asserting the typed error propagates from a forced SQLite failure is
the single most important fault to catch — everything downstream
(server validate/refresh/create handlers, audit pipeline) assumes the
store either succeeds or raises a well-formed ``sqlite3`` exception.
"""

import os
import sqlite3
from pathlib import Path

import pytest

from agent_auth.keys import EncryptionKey
from agent_auth.store import TokenStore
from tests_support.audit_events import read_audit_events


@pytest.fixture
def populated_store(tmp_path: Path) -> TokenStore:
    store = TokenStore(str(tmp_path / "tokens.db"), EncryptionKey(os.urandom(32)))
    store.create_family("fam-1", {"things:read": "allow"})
    store.create_token(
        token_id="tok-1",
        hmac_signature="sig",
        family_id="fam-1",
        token_type="access",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    return store


def test_read_only_database_rejects_writes(tmp_path: Path) -> None:
    """Writing to a read-only SQLite file surfaces the typed sqlite3 error.

    The store opens each connection with ``PRAGMA journal_mode=WAL`` at
    check-out time, so a ``query_only`` pragma on the cached handle is
    how we simulate a runtime read-only database without having to
    orchestrate filesystem permissions.
    """
    db_path = tmp_path / "tokens.db"
    store = TokenStore(str(db_path), EncryptionKey(os.urandom(32)))
    # Touch the connection so the per-thread handle exists, then flip
    # it into query-only mode — this is the closest analogue to the
    # operational failure where a filesystem remounts read-only under
    # a running service.
    store._get_conn().execute("PRAGMA query_only = 1")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        store.create_family("fam-readonly", {"things:read": "allow"})


def test_closed_connection_reads_raise(tmp_path: Path) -> None:
    """Reading through a forcibly-closed connection raises sqlite3 error.

    Models the failure mode where SQLite has already released the
    handle (e.g. after ``close()`` raced the shutdown drain); the
    next read-side operation must fail loudly rather than returning
    stale/empty data.
    """
    store = TokenStore(str(tmp_path / "tokens.db"), EncryptionKey(os.urandom(32)))
    conn = store._get_conn()
    conn.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store.get_family("fam-missing")


def test_store_ping_raises_on_closed_connection(tmp_path: Path) -> None:
    """``store.ping()`` (used by the health handler) raises when the handle is gone.

    The health endpoint uses ``store.ping()`` to distinguish 200 from
    503; silencing a ``sqlite3.ProgrammingError`` here would make the
    service report healthy when it cannot actually answer reads.
    """
    store = TokenStore(str(tmp_path / "tokens.db"), EncryptionKey(os.urandom(32)))
    conn = store._get_conn()
    conn.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store.ping()


def test_sqlite_error_does_not_silently_swallow_audit_event(
    tmp_path: Path, audit, audit_log_path: Path
) -> None:
    """A store failure does not block subsequent audit events from being logged.

    The audit pipeline must keep working even after a store-side fault so
    operators still see the failure in the log.
    """
    db_path = tmp_path / "tokens.db"
    store = TokenStore(str(db_path), EncryptionKey(os.urandom(32)))
    store._get_conn().execute("PRAGMA query_only = 1")
    with pytest.raises(sqlite3.OperationalError):
        store.create_family("fam-fail", {"things:read": "allow"})
    audit.log_authorization_decision("store_failure", reason="readonly_db")

    events = read_audit_events(audit_log_path)
    assert len(events) == 1
    assert events[0]["event"] == "store_failure"
    assert events[0]["reason"] == "readonly_db"
