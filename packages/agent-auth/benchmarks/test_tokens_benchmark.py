# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Benchmarks for the token hot path: parse, sign, verify, and pair creation."""

from pytest_benchmark.fixture import BenchmarkFixture

from agent_auth.config import Config
from agent_auth.keys import SigningKey
from agent_auth.store import TokenStore
from agent_auth.tokens import (
    PREFIX_ACCESS,
    create_token_pair,
    generate_token_id,
    parse_token,
    sign_token,
    verify_token,
)


def test_parse_token_benchmark(benchmark: BenchmarkFixture, signing_key: SigningKey) -> None:
    token = sign_token(generate_token_id(), PREFIX_ACCESS, signing_key)
    benchmark(parse_token, token)


def test_sign_token_benchmark(benchmark: BenchmarkFixture, signing_key: SigningKey) -> None:
    token_id = generate_token_id()
    benchmark(sign_token, token_id, PREFIX_ACCESS, signing_key)


def test_verify_token_benchmark(benchmark: BenchmarkFixture, signing_key: SigningKey) -> None:
    """Verify-token is the hot path named in issue #40 — called on every authed request."""
    token = sign_token(generate_token_id(), PREFIX_ACCESS, signing_key)
    benchmark(verify_token, token, signing_key)


def test_create_token_pair_benchmark(
    benchmark: BenchmarkFixture,
    store: TokenStore,
    signing_key: SigningKey,
    config: Config,
    family_with_one_scope: str,
) -> None:
    """Covers both 'token create' and 'refresh' from the issue — a refresh is a new pair."""
    benchmark(create_token_pair, signing_key, store, family_with_one_scope, config)
