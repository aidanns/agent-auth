# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared test fixtures for agent-auth."""

import os
import signal
import tempfile
from unittest.mock import patch

import pytest

from agent_auth.config import Config
from agent_auth.keys import EncryptionKey, SigningKey
from agent_auth.store import TokenStore


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def encryption_key():
    return EncryptionKey(os.urandom(32))


@pytest.fixture
def signing_key():
    return SigningKey(os.urandom(32))


@pytest.fixture
def test_config(tmp_dir):
    return Config(
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
    )


@pytest.fixture
def store(test_config, encryption_key):
    return TokenStore(test_config.db_path, encryption_key)


@pytest.fixture
def preserve_signal_handlers():
    """Restore SIGTERM / SIGINT handlers after the test.

    Any test that calls ``_install_shutdown_handler`` mutates
    process-global signal state; without this fixture a later test's
    SIGINT (or pytest's own interrupt handling) would invoke our
    installed callback.
    """
    originals = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }
    yield
    for sig, handler in originals.items():
        signal.signal(sig, handler)


@pytest.fixture
def mock_keyring():
    """Mock keyring that stores passwords in memory."""
    passwords = {}

    def get_password(service, username):
        return passwords.get((service, username))

    def set_password(service, username, password):
        passwords[(service, username)] = password

    with (
        patch("agent_auth.keys.keyring.get_password", side_effect=get_password),
        patch("agent_auth.keys.keyring.set_password", side_effect=set_password),
    ):
        yield passwords
