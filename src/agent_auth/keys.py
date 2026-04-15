"""Keyring integration for managing signing and encryption keys."""

import base64
import os

import keyring

from agent_auth.errors import KeyringError

SERVICE_NAME = "agent-auth"
# These are the "username" parameter of the system keyring API, but semantically
# they are the names under which we store each key inside our service entry.
SIGNING_KEY_NAME = "signing-key"
ENCRYPTION_KEY_NAME = "encryption-key"
KEY_SIZE_BYTES = 32


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

    def get_or_create_signing_key(self) -> bytes:
        """Return the HMAC signing key, generating it on first use."""
        return self._get_or_create_key(SIGNING_KEY_NAME)

    def get_or_create_encryption_key(self) -> bytes:
        """Return the AES-256-GCM encryption key, generating it on first use."""
        return self._get_or_create_key(ENCRYPTION_KEY_NAME)
