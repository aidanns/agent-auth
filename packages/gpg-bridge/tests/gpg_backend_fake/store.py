# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fixture-driven in-memory ``gpg``-substitute used only by tests.

The store owns the keyring lookup and the synthetic-signature shape;
the CLI in ``gpg_backend_fake.cli`` is a thin argv parser that
translates a ``gpg`` invocation into one of :meth:`FakeKeyring.sign`
or :meth:`FakeKeyring.verify` and writes ``gpg``-shaped output to
the streams ``gpg`` would.

Fixture YAML shape::

    keys:
      - fingerprint: "D7A2B4C0E8F11234567890ABCDEF1234567890AB"
        user_ids: ["Test Key <test@example.invalid>"]
        aliases: ["0xCDEF1234567890AB", "test@example.invalid"]
    behaviours:
      deny_key: "NOKEY0000000000000000000000000000000000"
      permission_denied: false
      corrupt_verify: false

``aliases`` are additional ``--local-user`` strings that resolve to
the named key. ``behaviours`` steers the fake into error paths for
negative tests; the CLI translates each into the corresponding gpg
exit code + stderr string.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


class FakeKeyringError(Exception):
    """Raised internally by the store; the CLI maps each subclass to gpg-shaped output."""


class NoSuchKeyError(FakeKeyringError):
    """The requested ``--local-user`` does not match any fixture key."""


class PermissionDeniedError(FakeKeyringError):
    """``behaviours.permission_denied: true`` — emit a pinentry-style failure."""


class BadSignatureError(FakeKeyringError):
    """The verify input did not match the fake's synthetic-signature shape."""


@dataclass(frozen=True)
class _FakeKey:
    fingerprint: str
    user_ids: tuple[str, ...]
    aliases: tuple[str, ...]

    def matches(self, requested: str) -> bool:
        needle = requested.strip().lower()
        if not needle:
            return False
        if needle == self.fingerprint.lower():
            return True
        if any(needle == alias.lower() for alias in self.aliases):
            return True
        return any(needle in user_id.lower() for user_id in self.user_ids)


@dataclass
class _Behaviours:
    deny_key: str = ""
    permission_denied: bool = False
    corrupt_verify: bool = False


@dataclass
class FakeKeyring:
    """Fixture-backed keyring used to satisfy the bridge's ``gpg`` argv."""

    keys: tuple[_FakeKey, ...] = ()
    behaviours: _Behaviours = field(default_factory=_Behaviours)

    def sign(self, *, local_user: str, payload: bytes, armor: bool) -> tuple[bytes, str]:
        """Return ``(signature_bytes, status_text)`` for a ``--detach-sign``."""
        if self.behaviours.permission_denied:
            raise PermissionDeniedError("fake: pinentry denied")
        key = self._resolve(local_user)
        if self.behaviours.deny_key and key.fingerprint == self.behaviours.deny_key:
            raise NoSuchKeyError(f"fake: key {key.fingerprint} denied by fixture")
        signature = _synth_signature(key.fingerprint, payload, armor=armor)
        status_text = (
            f"[GNUPG:] SIG_CREATED D 1 10 00 0 {key.fingerprint} 0 0 0 00000000000000000000\n"
        )
        return signature, status_text

    def verify(self, *, signature: bytes, payload: bytes) -> str:
        """Return the ``--status-fd 2`` text for a successful verify."""
        if self.behaviours.permission_denied:
            raise PermissionDeniedError("fake: keyring unreachable")
        expected_prefix = b"-----BEGIN PGP SIGNATURE-----\n"
        if self.behaviours.corrupt_verify or not signature.startswith(expected_prefix):
            raise BadSignatureError("fake: signature does not match payload")
        try:
            fingerprint = signature.split(b"FAKE-FP:", 1)[1].split(b"\n", 1)[0].decode("ascii")
        except (IndexError, UnicodeDecodeError) as exc:
            raise BadSignatureError("fake: signature missing FAKE-FP marker") from exc
        expected_hash = hashlib.sha256(payload).hexdigest().upper()
        if f"PAYLOAD-HASH:{expected_hash}".encode("ascii") not in signature:
            raise BadSignatureError("fake: payload hash mismatch")
        return (
            f"[GNUPG:] GOODSIG {fingerprint} fake\n"
            f"[GNUPG:] VALIDSIG {fingerprint} 2026-04-23 0 4 0 1 10 00 {fingerprint}\n"
        )

    def _resolve(self, requested: str) -> _FakeKey:
        for key in self.keys:
            if key.matches(requested):
                return key
        raise NoSuchKeyError(f"fake: no key matches {requested!r}")


def load_fixture(data: Any) -> FakeKeyring:
    """Parse a fixture-YAML mapping into a :class:`FakeKeyring`."""
    if not isinstance(data, dict):
        raise ValueError("fake fixture: top-level document must be a mapping")
    raw_keys = data.get("keys") or []
    if not isinstance(raw_keys, list):
        raise ValueError("fake fixture: 'keys' must be a list")
    keys: list[_FakeKey] = []
    for entry in raw_keys:
        if not isinstance(entry, dict):
            raise ValueError("fake fixture: each key entry must be a mapping")
        fingerprint = entry.get("fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("fake fixture: 'fingerprint' is required")
        user_ids_raw = entry.get("user_ids") or []
        aliases_raw = entry.get("aliases") or []
        if not isinstance(user_ids_raw, list) or not isinstance(aliases_raw, list):
            raise ValueError("fake fixture: 'user_ids' and 'aliases' must be lists")
        keys.append(
            _FakeKey(
                fingerprint=fingerprint.upper(),
                user_ids=tuple(str(u) for u in user_ids_raw),
                aliases=tuple(str(a) for a in aliases_raw),
            )
        )
    behaviours_raw = data.get("behaviours") or {}
    if not isinstance(behaviours_raw, dict):
        raise ValueError("fake fixture: 'behaviours' must be a mapping")
    behaviours = _Behaviours(
        deny_key=str(behaviours_raw.get("deny_key") or "").upper(),
        permission_denied=bool(behaviours_raw.get("permission_denied", False)),
        corrupt_verify=bool(behaviours_raw.get("corrupt_verify", False)),
    )
    return FakeKeyring(keys=tuple(keys), behaviours=behaviours)


def _synth_signature(fingerprint: str, payload: bytes, *, armor: bool) -> bytes:
    digest = hashlib.sha256(payload).hexdigest().upper()
    body = (
        b"-----BEGIN PGP SIGNATURE-----\n"
        + f"FAKE-FP:{fingerprint}\n".encode("ascii")
        + f"PAYLOAD-HASH:{digest}\n".encode("ascii")
        + b"-----END PGP SIGNATURE-----\n"
    )
    if not armor:
        return body.replace(b"-----BEGIN PGP SIGNATURE-----\n", b"\x89SIG\n", 1)
    return body


__all__ = [
    "BadSignatureError",
    "FakeKeyring",
    "FakeKeyringError",
    "NoSuchKeyError",
    "PermissionDeniedError",
    "load_fixture",
]
