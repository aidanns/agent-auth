# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: system keyring backend unavailable.

``KeyManager`` wraps every ``keyring.*`` call in a try/except that
re-raises as ``KeyringError``. A missing or failing backend
(libsecret not installed; macOS Keychain locked; keyring.alt RAM
backend crashed) must surface as ``KeyringError`` rather than
propagating the raw third-party exception — downstream code
matches on ``KeyringError``.
"""

from unittest.mock import patch

import pytest

from agent_auth.errors import KeyringError
from agent_auth.keys import KeyManager


def test_keyring_get_failure_raises_keyring_error() -> None:
    """``keyring.get_password`` raising is re-wrapped as ``KeyringError``."""
    km = KeyManager()
    with (
        patch(
            "agent_auth.keys.keyring.get_password",
            side_effect=RuntimeError("no keyring backend"),
        ),
        pytest.raises(KeyringError, match="Failed to read"),
    ):
        km.get_or_create_signing_key()


def test_keyring_set_failure_raises_keyring_error() -> None:
    """A write to the keyring that fails surfaces as ``KeyringError``."""
    km = KeyManager()
    # get_password returns None (key absent) then set_password fails.
    with (
        patch("agent_auth.keys.keyring.get_password", return_value=None),
        patch(
            "agent_auth.keys.keyring.set_password",
            side_effect=RuntimeError("backend refused write"),
        ),
        pytest.raises(KeyringError, match="Failed to store"),
    ):
        km.get_or_create_encryption_key()


def test_management_token_read_failure_raises_keyring_error() -> None:
    """Management-token getter also surfaces a failing backend as ``KeyringError``."""
    km = KeyManager()
    with (
        patch(
            "agent_auth.keys.keyring.get_password",
            side_effect=OSError("dbus not available"),
        ),
        pytest.raises(KeyringError, match="management refresh token"),
    ):
        km.get_management_refresh_token()
