"""Tests for the SQLite token store."""

import json

import pytest

from agent_auth.store import TokenStore


@pytest.mark.covers_function("Store Token Family", "Query Tokens")
def test_create_and_get_family(store):
    family = store.create_family("fam1", {"things:read": "allow"})
    assert family["id"] == "fam1"
    assert family["scopes"] == {"things:read": "allow"}
    assert not family["revoked"]

    fetched = store.get_family("fam1")
    assert fetched is not None
    assert fetched["scopes"] == {"things:read": "allow"}


@pytest.mark.covers_function("Query Tokens")
def test_get_nonexistent_family(store):
    assert store.get_family("nonexistent") is None


@pytest.mark.covers_function("Query Tokens")
def test_list_families(store):
    store.create_family("fam1", {"a:read": "allow"})
    store.create_family("fam2", {"b:write": "prompt"})
    families = store.list_families()
    assert len(families) == 2
    ids = {f["id"] for f in families}
    assert ids == {"fam1", "fam2"}


@pytest.mark.covers_function("Mark Family Revoked")
def test_revoke_family(store):
    store.create_family("fam1", {"a:read": "allow"})
    store.mark_family_revoked("fam1")
    family = store.get_family("fam1")
    assert family["revoked"] is True


def test_update_family_scopes(store):
    store.create_family("fam1", {"a:read": "allow"})
    store.update_family_scopes("fam1", {"a:read": "allow", "b:write": "prompt"})
    family = store.get_family("fam1")
    assert family["scopes"] == {"a:read": "allow", "b:write": "prompt"}


@pytest.mark.covers_function("Store Token", "Query Tokens")
def test_create_and_get_token(store):
    store.create_family("fam1", {"a:read": "allow"})
    token = store.create_token("tok1", "sig123", "fam1", "access", "2099-01-01T00:00:00+00:00")
    assert token["id"] == "tok1"

    fetched = store.get_token("tok1")
    assert fetched is not None
    assert fetched["hmac_signature"] == "sig123"
    assert fetched["family_id"] == "fam1"
    assert fetched["type"] == "access"
    assert not fetched["consumed"]


@pytest.mark.covers_function("Query Tokens")
def test_get_nonexistent_token(store):
    assert store.get_token("nonexistent") is None


@pytest.mark.covers_function("Mark Token Consumed")
def test_mark_consumed(store):
    store.create_family("fam1", {"a:read": "allow"})
    store.create_token("tok1", "sig", "fam1", "refresh", "2099-01-01T00:00:00+00:00")
    store.mark_consumed("tok1")
    token = store.get_token("tok1")
    assert token["consumed"] is True


@pytest.mark.covers_function("Query Tokens")
def test_get_tokens_by_family(store):
    store.create_family("fam1", {"a:read": "allow"})
    store.create_token("tok1", "sig1", "fam1", "access", "2099-01-01T00:00:00+00:00")
    store.create_token("tok2", "sig2", "fam1", "refresh", "2099-01-01T00:00:00+00:00")
    tokens = store.get_tokens_by_family("fam1")
    assert len(tokens) == 2


@pytest.mark.covers_function("Encrypt Field")
def test_scopes_are_encrypted_in_db(store, encryption_key):
    """Verify that scope data is stored encrypted, not as plaintext JSON."""
    store.create_family("fam1", {"secret:scope": "allow"})
    import sqlite3
    conn = sqlite3.connect(store._db_path)
    row = conn.execute("SELECT scopes FROM token_families WHERE id = 'fam1'").fetchone()
    raw = row[0]
    assert isinstance(raw, bytes)
    assert b"secret:scope" not in raw
    conn.close()
