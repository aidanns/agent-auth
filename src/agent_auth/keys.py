# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Keyring integration for managing signing and encryption keys."""

import base64
import os
from typing import NewType

import keyring

from agent_auth.errors import KeyringError

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

    def _get_or_create_key(self, key_name: str) -> bytes:
        try:
            stored = keyring.get_password(self._service, key_name)
        except Exception as e:
            raise KeyringError(f"Failed to read key '{key_name}' from keyring: {e}") from e

        if stored is not None:
            return base64.b64decode(stored)

        key = os.urandom(KEY_SIZE_BYTES)
        encoded = base64.b64encode(key).decode("ascii")
        try:
            keyring.set_password(self._service, key_name, encoded)
        except Exception as e:
            raise KeyringError(f"Failed to store key '{key_name}' in keyring: {e}") from e

        return key

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
