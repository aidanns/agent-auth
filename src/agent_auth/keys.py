# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Keyring integration for managing signing and encryption keys."""

import base64
import os
import sqlite3
from pathlib import Path
from typing import NewType

import keyring

from agent_auth.errors import KeyLossError, KeyringError

SERVICE_NAME = "agent-auth"
# These are the "username" parameter of the system keyring API, but semantically
# they are the names under which we store each key inside our service entry.
SIGNING_KEY_NAME = "signing-key"
ENCRYPTION_KEY_NAME = "encryption-key"
MANAGEMENT_REFRESH_TOKEN_NAME = "management-refresh-token"
KEY_SIZE_BYTES = 32

# Distinguish the two 32-byte secrets at the type level so a signing key
# cannot accidentally be handed to AES-GCM (or vice versa). Runtime
# representation is still ``bytes``; callers obtain instances only via
# ``KeyManager``.
SigningKey = NewType("SigningKey", bytes)
EncryptionKey = NewType("EncryptionKey", bytes)


class KeyManager:
    """Manages HMAC signing and AES-256-GCM encryption keys via the system keyring."""

    def __init__(self, service_name: str = SERVICE_NAME):
        self._service = service_name

    def _read_key(self, key_name: str) -> bytes | None:
        """Return the key bytes if present in the keyring, else ``None``.

        Split from ``_get_or_create_key`` so startup can detect key loss
        (keyring empty while the token store holds state) without
        silently regenerating.
        """
        try:
            stored = keyring.get_password(self._service, key_name)
        except Exception as e:
            raise KeyringError(f"Failed to read key '{key_name}' from keyring: {e}") from e
        if stored is None:
            return None
        return base64.b64decode(stored)

    def _write_key(self, key_name: str, key: bytes) -> None:
        encoded = base64.b64encode(key).decode("ascii")
        try:
            keyring.set_password(self._service, key_name, encoded)
        except Exception as e:
            raise KeyringError(f"Failed to store key '{key_name}' in keyring: {e}") from e

    def _get_or_create_key(self, key_name: str) -> bytes:
        existing = self._read_key(key_name)
        if existing is not None:
            return existing
        key = os.urandom(KEY_SIZE_BYTES)
        self._write_key(key_name, key)
        return key

    def get_signing_key(self) -> SigningKey | None:
        """Return the HMAC signing key, or ``None`` if not yet provisioned."""
        raw = self._read_key(SIGNING_KEY_NAME)
        return None if raw is None else SigningKey(raw)

    def get_encryption_key(self) -> EncryptionKey | None:
        """Return the AES-256-GCM encryption key, or ``None`` if not yet provisioned."""
        raw = self._read_key(ENCRYPTION_KEY_NAME)
        return None if raw is None else EncryptionKey(raw)

    def get_or_create_signing_key(self) -> SigningKey:
        """Return the HMAC signing key, generating it on first use."""
        return SigningKey(self._get_or_create_key(SIGNING_KEY_NAME))

    def get_or_create_encryption_key(self) -> EncryptionKey:
        """Return the AES-256-GCM encryption key, generating it on first use."""
        return EncryptionKey(self._get_or_create_key(ENCRYPTION_KEY_NAME))

    def get_management_refresh_token(self) -> str | None:
        """Return the stored management refresh token, or None if not yet bootstrapped."""
        try:
            return keyring.get_password(self._service, MANAGEMENT_REFRESH_TOKEN_NAME)
        except Exception as e:
            raise KeyringError(f"Failed to read management refresh token from keyring: {e}") from e

    def set_management_refresh_token(self, token: str) -> None:
        """Persist the management refresh token to the keyring."""
        try:
            keyring.set_password(self._service, MANAGEMENT_REFRESH_TOKEN_NAME, token)
        except Exception as e:
            raise KeyringError(f"Failed to store management refresh token in keyring: {e}") from e


def _db_has_token_families(db_path: str) -> bool:
    """Return True iff the token-store DB at ``db_path`` has any rows.

    Opens a read-only SQLite connection so we don't need the encryption
    key (the encryption is field-level, not database-level). A missing
    file or an empty schema both count as "no rows" — the legitimate
    first-run case.
    """
    if not Path(db_path).is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.DatabaseError:
        return False
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='token_families'"
        )
        if cursor.fetchone() is None:
            return False
        cursor = conn.execute("SELECT 1 FROM token_families LIMIT 1")
        return cursor.fetchone() is not None
    finally:
        conn.close()


def check_key_integrity(db_path: str, key_manager: "KeyManager") -> None:
    """Raise ``KeyLossError`` when the DB holds state but the keyring is empty.

    The check runs before any call to ``get_or_create_*``: if the token
    store already has families, silently regenerating a fresh signing or
    encryption key would invalidate every live token and render the
    encrypted columns unreadable. Refusing to start and surfacing a
    clear operator error is the safer failure mode — the operator can
    either restore their keyring entry or delete the DB to accept a
    fresh install.
    """
    if not _db_has_token_families(db_path):
        return
    signing = key_manager.get_signing_key()
    encryption = key_manager.get_encryption_key()
    missing: list[str] = []
    if signing is None:
        missing.append("signing key")
    if encryption is None:
        missing.append("encryption key")
    if not missing:
        return
    raise KeyLossError(
        f"Token store at {db_path} contains families but the keyring is "
        f"missing the {' and '.join(missing)}. agent-auth refuses to "
        "auto-regenerate these keys — a fresh key would silently "
        "invalidate every live token and render encrypted columns "
        "unreadable. Either restore the keyring entry for the "
        "'agent-auth' service, or delete the token store "
        f"({db_path}) and any Write-Ahead Log siblings to accept a "
        "fresh install. See design/DESIGN.md 'Key loss and recovery'."
    )
