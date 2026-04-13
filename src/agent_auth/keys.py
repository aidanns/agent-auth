"""Keyring integration for managing signing and encryption keys."""

import base64
import os

import keyring

from agent_auth.errors import KeyringError

SERVICE_NAME = "agent-auth"
SIGNING_KEY_USERNAME = "signing-key"
ENCRYPTION_KEY_USERNAME = "encryption-key"
KEY_SIZE = 32


class KeyManager:
    """Manages HMAC signing and AES-256-GCM encryption keys via the system keyring."""

    def __init__(self, service_name: str = SERVICE_NAME):
        self._service = service_name

    def _get_or_create_key(self, username: str) -> bytes:
        try:
            stored = keyring.get_password(self._service, username)
        except Exception as e:
            raise KeyringError(f"Failed to read key '{username}' from keyring: {e}") from e

        if stored is not None:
            return base64.b64decode(stored)

        key = os.urandom(KEY_SIZE)
        encoded = base64.b64encode(key).decode("ascii")
        try:
            keyring.set_password(self._service, username, encoded)
        except Exception as e:
            raise KeyringError(f"Failed to store key '{username}' in keyring: {e}") from e

        return key

    def get_or_create_signing_key(self) -> bytes:
        """Return the HMAC signing key, generating it on first use."""
        return self._get_or_create_key(SIGNING_KEY_USERNAME)

    def get_or_create_encryption_key(self) -> bytes:
        """Return the AES-256-GCM encryption key, generating it on first use."""
        return self._get_or_create_key(ENCRYPTION_KEY_USERNAME)
