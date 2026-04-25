# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared fixtures for the agent-auth benchmark suite.

The benchmark tree sits next to the package's ``src/`` (and, once
tests move in #270, ``tests/``) so the coverage gate in
``pyproject.toml`` — which runs on every ``pytest`` invocation
against the test tree — does not apply to benchmarks. See
``packages/agent-auth/benchmarks/README.md``.
"""

import os
import tempfile
from collections.abc import Iterator

import pytest

from agent_auth.config import Config
from agent_auth.keys import EncryptionKey, SigningKey
from agent_auth.store import TokenStore
from agent_auth.tokens import create_token_pair

LARGE_FAMILY_SCOPE_COUNT = 200


@pytest.fixture
def tmp_dir() -> Iterator[str]:
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def signing_key() -> SigningKey:
    return SigningKey(os.urandom(32))


@pytest.fixture
def encryption_key() -> EncryptionKey:
    return EncryptionKey(os.urandom(32))


@pytest.fixture
def config(tmp_dir: str) -> Config:
    return Config(
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
    )


@pytest.fixture
def store(config: Config, encryption_key: EncryptionKey) -> TokenStore:
    return TokenStore(config.db_path, encryption_key)


@pytest.fixture
def family_with_many_scopes(store: TokenStore) -> str:
    """A token family pre-populated with a large scope map.

    Models the "DB read of a family with many scopes" case named in
    issue #40: encrypted JSON blob decrypt cost scales with scope
    count, so ``get_family`` is the DB-side hot path we want a
    baseline for.
    """
    family_id = "fam_large"
    scopes = {f"scope_{i}": "allow" for i in range(LARGE_FAMILY_SCOPE_COUNT)}
    store.create_family(family_id, scopes)
    return family_id


@pytest.fixture
def family_with_one_scope(store: TokenStore) -> str:
    """A token family with a single scope, for steady-state benchmarks."""
    family_id = "fam_small"
    store.create_family(family_id, {"things:read": "allow"})
    return family_id


@pytest.fixture
def issued_token_pair(
    store: TokenStore,
    signing_key: SigningKey,
    config: Config,
    family_with_one_scope: str,
) -> tuple[str, str]:
    """An (access_token, refresh_token) pair already persisted in the store."""
    return create_token_pair(signing_key, store, family_with_one_scope, config)
