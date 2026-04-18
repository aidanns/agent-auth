"""Tests for token generation, signing, and verification."""

import pytest

from agent_auth.errors import TokenInvalidError
from agent_auth.tokens import (
    PREFIX_ACCESS,
    PREFIX_REFRESH,
    generate_token_id,
    parse_token,
    sign_token,
    verify_token,
)


def test_generate_token_id_is_unique():
    ids = {generate_token_id() for _ in range(100)}
    assert len(ids) == 100


@pytest.mark.covers_function("Verify Token Signature")
def test_sign_and_verify_access_token(signing_key):
    token_id = generate_token_id()
    token = sign_token(token_id, PREFIX_ACCESS, signing_key)
    assert token.startswith("aa_")
    prefix, verified_id = verify_token(token, signing_key)
    assert prefix == PREFIX_ACCESS
    assert verified_id == token_id


@pytest.mark.covers_function("Verify Token Signature")
def test_sign_and_verify_refresh_token(signing_key):
    token_id = generate_token_id()
    token = sign_token(token_id, PREFIX_REFRESH, signing_key)
    assert token.startswith("rt_")
    prefix, verified_id = verify_token(token, signing_key)
    assert prefix == PREFIX_REFRESH
    assert verified_id == token_id


@pytest.mark.covers_function("Verify Token Signature")
def test_verify_with_wrong_key(signing_key):
    import os

    token_id = generate_token_id()
    token = sign_token(token_id, PREFIX_ACCESS, signing_key)
    wrong_key = os.urandom(32)
    with pytest.raises(TokenInvalidError, match="signature verification failed"):
        verify_token(token, wrong_key)


def test_parse_valid_token():
    prefix, token_id, sig = parse_token("aa_abc123_def456")
    assert prefix == "aa"
    assert token_id == "abc123"
    assert sig == "def456"


def test_parse_malformed_token():
    with pytest.raises(TokenInvalidError, match="Malformed"):
        parse_token("invalid")


def test_parse_unknown_prefix():
    with pytest.raises(TokenInvalidError, match="Unknown token prefix"):
        parse_token("xx_abc_def")


def test_sign_invalid_prefix(signing_key):
    with pytest.raises(ValueError, match="Invalid token prefix"):
        sign_token("id", "xx", signing_key)
