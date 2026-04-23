# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Benchmarks for the SQLite TokenStore hot path."""

from pytest_benchmark.fixture import BenchmarkFixture

from agent_auth.store import TokenStore


def test_get_family_with_many_scopes_benchmark(
    benchmark: BenchmarkFixture,
    store: TokenStore,
    family_with_many_scopes: str,
) -> None:
    """The 'DB read of a family with many scopes' case named in issue #40.

    ``get_family`` decrypts a JSON blob whose size scales with scope
    count, so the cost is dominated by AES-GCM decrypt + json.loads.
    """
    benchmark(store.get_family, family_with_many_scopes)


def test_get_token_benchmark(
    benchmark: BenchmarkFixture,
    store: TokenStore,
    issued_token_pair: tuple[str, str],
) -> None:
    access_token, _ = issued_token_pair
    from agent_auth.tokens import parse_token

    _, token_id, _ = parse_token(access_token)
    benchmark(store.get_token, token_id)


def test_create_token_benchmark(
    benchmark: BenchmarkFixture,
    store: TokenStore,
    family_with_one_scope: str,
) -> None:
    """Steady-state token insert (no signing cost — isolates the DB write)."""
    from itertools import count

    from agent_auth.tokens import generate_token_id

    counter = count()

    def _insert() -> None:
        token_id = generate_token_id()
        # Per-iteration unique token_id so the PRIMARY KEY constraint
        # never fires; the ``counter`` is only here to guard against
        # pytest-benchmark potentially reusing IDs if generate_token_id
        # ever switched to a deterministic generator.
        next(counter)
        store.create_token(
            token_id=token_id,
            hmac_signature="0" * 64,
            family_id=family_with_one_scope,
            token_type="access",
            expires_at="2099-01-01T00:00:00+00:00",
        )

    benchmark(_insert)
