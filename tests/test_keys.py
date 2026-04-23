# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for keyring key management."""

import os

import pytest

from agent_auth.errors import KeyLossError
from agent_auth.keys import KeyManager, check_key_integrity
from agent_auth.store import TokenStore


@pytest.mark.covers_function("Generate Signing Key")
def test_creates_signing_key_on_first_use(mock_keyring):
    km = KeyManager()
    key = km.get_or_create_signing_key()
    assert len(key) == 32
    assert ("agent-auth", "signing-key") in mock_keyring


@pytest.mark.covers_function("Load Signing Key")
def test_returns_same_signing_key(mock_keyring):
    km = KeyManager()
    key1 = km.get_or_create_signing_key()
    key2 = km.get_or_create_signing_key()
    assert key1 == key2


@pytest.mark.covers_function("Generate Encryption Key")
def test_creates_encryption_key_on_first_use(mock_keyring):
    km = KeyManager()
    key = km.get_or_create_encryption_key()
    assert len(key) == 32
    assert ("agent-auth", "encryption-key") in mock_keyring


@pytest.mark.covers_function("Load Encryption Key")
def test_signing_and_encryption_keys_differ(mock_keyring):
    km = KeyManager()
    signing = km.get_or_create_signing_key()
    encryption = km.get_or_create_encryption_key()
    # NewType distinguishes them statically; at runtime both are bytes.
    assert bytes(signing) != bytes(encryption)


# -- key loss detection --


@pytest.mark.covers_function("Load Signing Key")
def test_get_signing_key_returns_none_when_keyring_empty(mock_keyring):
    km = KeyManager()
    assert km.get_signing_key() is None


@pytest.mark.covers_function("Load Encryption Key")
def test_get_encryption_key_returns_none_when_keyring_empty(mock_keyring):
    km = KeyManager()
    assert km.get_encryption_key() is None


@pytest.mark.covers_function("Load Signing Key")
def test_check_key_integrity_passes_on_fresh_install(mock_keyring, tmp_dir):
    """DB absent + keyring empty = first-time install; no error."""
    db_path = os.path.join(tmp_dir, "tokens.db")
    km = KeyManager()
    # Expected: no raise.
    check_key_integrity(db_path, km)


@pytest.mark.covers_function("Load Signing Key")
def test_check_key_integrity_passes_when_db_empty(mock_keyring, tmp_dir):
    """Empty schema + no keys is still the first-time path."""
    db_path = os.path.join(tmp_dir, "tokens.db")
    # Build an empty store (schema only, no families) — this uses
    # get_or_create_encryption_key, so clear the keyring afterwards to
    # simulate a later wipe.
    km = KeyManager()
    encryption_key = km.get_or_create_encryption_key()
    TokenStore(db_path, encryption_key).close()
    mock_keyring.clear()

    # Even though the DB file exists, token_families is empty, so the
    # check must pass — recreating keys on first launch is expected.
    check_key_integrity(db_path, KeyManager())


@pytest.mark.covers_function("Load Signing Key")
def test_check_key_integrity_raises_when_db_has_families_but_keys_missing(mock_keyring, tmp_dir):
    db_path = os.path.join(tmp_dir, "tokens.db")
    km = KeyManager()
    encryption_key = km.get_or_create_encryption_key()
    _signing = km.get_or_create_signing_key()
    store = TokenStore(db_path, encryption_key)
    store.create_family("fam-keyloss-test", {"agent-auth:health": "allow"})
    store.close()

    # Simulate a wiped keyring (user moved hosts, lost keychain, etc.).
    mock_keyring.clear()

    with pytest.raises(KeyLossError) as excinfo:
        check_key_integrity(db_path, KeyManager())
    message = str(excinfo.value)
    # The error names both missing keys and the recovery path so an
    # operator reading only the message can act on it.
    assert "signing key" in message
    assert "encryption key" in message
    assert "delete the token store" in message
    assert db_path in message


@pytest.mark.covers_function("Load Signing Key")
def test_check_key_integrity_raises_when_only_signing_key_missing(mock_keyring, tmp_dir):
    """Partial loss (one of the two keys) still fails startup."""
    db_path = os.path.join(tmp_dir, "tokens.db")
    km = KeyManager()
    encryption_key = km.get_or_create_encryption_key()
    _signing = km.get_or_create_signing_key()
    store = TokenStore(db_path, encryption_key)
    store.create_family("fam-partial-loss", {"agent-auth:health": "allow"})
    store.close()

    # Selectively delete only the signing key from the mock keyring.
    mock_keyring.pop(("agent-auth", "signing-key"), None)

    with pytest.raises(KeyLossError) as excinfo:
        check_key_integrity(db_path, KeyManager())
    message = str(excinfo.value)
    assert "signing key" in message
    # Encryption key is still present, so it should not be named as missing.
    assert "encryption key" not in message
