"""Token generation, HMAC signing, parsing, and verification."""

import hashlib
import hmac
import uuid

from agent_auth.errors import TokenInvalidError
from agent_auth.keys import SigningKey

PREFIX_ACCESS = "aa"
PREFIX_REFRESH = "rt"
VALID_PREFIXES = {PREFIX_ACCESS, PREFIX_REFRESH}


def generate_token_id() -> str:
    """Generate a random token ID (UUID4 hex)."""
    return uuid.uuid4().hex


def _compute_hmac(prefix: str, token_id: str, signing_key: SigningKey) -> str:
    """Compute HMAC-SHA256 over prefix + token_id, returning the hex digest."""
    message = f"{prefix}_{token_id}".encode("utf-8")
    return hmac.new(signing_key, message, hashlib.sha256).hexdigest()


def sign_token(token_id: str, prefix: str, signing_key: SigningKey) -> str:
    """Create a signed token string: <prefix>_<token_id>_<hmac>."""
    if prefix not in VALID_PREFIXES:
        raise ValueError(f"Invalid token prefix: {prefix}")
    signature = _compute_hmac(prefix, token_id, signing_key)
    return f"{prefix}_{token_id}_{signature}"


def parse_token(raw: str) -> tuple[str, str, str]:
    """Parse a raw token string into (prefix, token_id, signature).

    Raises TokenInvalidError if the format is wrong.
    """
    parts = raw.split("_", 2)
    if len(parts) != 3:
        raise TokenInvalidError("Malformed token: expected format <prefix>_<id>_<signature>")
    prefix, token_id, signature = parts
    if prefix not in VALID_PREFIXES:
        raise TokenInvalidError(f"Unknown token prefix: {prefix}")
    return prefix, token_id, signature


def create_token_pair(signing_key: SigningKey, store, family_id: str, config) -> tuple[str, str]:
    """Create an access + refresh token pair, persist both, return (access_token, refresh_token)."""
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)

    access_id = generate_token_id()
    access_token = sign_token(access_id, PREFIX_ACCESS, signing_key)
    access_expires = (now + timedelta(seconds=config.access_token_ttl_seconds)).isoformat()
    _, _, access_sig = parse_token(access_token)
    store.create_token(access_id, access_sig, family_id, "access", access_expires)

    refresh_id = generate_token_id()
    refresh_token = sign_token(refresh_id, PREFIX_REFRESH, signing_key)
    refresh_expires = (now + timedelta(seconds=config.refresh_token_ttl_seconds)).isoformat()
    _, _, refresh_sig = parse_token(refresh_token)
    store.create_token(refresh_id, refresh_sig, family_id, "refresh", refresh_expires)

    return access_token, refresh_token


def verify_token(raw: str, signing_key: SigningKey) -> tuple[str, str]:
    """Verify a token's HMAC signature.

    Returns (prefix, token_id) if valid.
    Raises TokenInvalidError if signature verification fails.
    """
    prefix, token_id, signature = parse_token(raw)
    expected = _compute_hmac(prefix, token_id, signing_key)
    if not hmac.compare_digest(signature, expected):
        raise TokenInvalidError("Token signature verification failed")
    return prefix, token_id
