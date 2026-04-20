# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for keyring key management."""

import pytest

from agent_auth.keys import KeyManager


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
    assert signing != encryption
