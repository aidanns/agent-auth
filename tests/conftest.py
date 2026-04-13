"""Shared test fixtures for agent-auth."""

import os
import tempfile
from unittest.mock import patch

import pytest

from agent_auth.config import Config
from agent_auth.store import TokenStore


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def encryption_key():
    return os.urandom(32)


@pytest.fixture
def signing_key():
    return os.urandom(32)


@pytest.fixture
def test_config(tmp_dir):
    return Config(
        config_dir=tmp_dir,
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
    )


@pytest.fixture
def store(test_config, encryption_key):
    return TokenStore(test_config.db_path, encryption_key)


@pytest.fixture
def mock_keyring():
    """Mock keyring that stores passwords in memory."""
    passwords = {}

    def get_password(service, username):
        return passwords.get((service, username))

    def set_password(service, username, password):
        passwords[(service, username)] = password

    with patch("agent_auth.keys.keyring.get_password", side_effect=get_password), \
         patch("agent_auth.keys.keyring.set_password", side_effect=set_password):
        yield passwords
