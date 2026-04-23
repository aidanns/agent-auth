# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fixture-driven in-memory backend used only by tests.

Fixture YAML shape:

```yaml
keys:
  - fingerprint: "D7A2B4C0E8F11234567890ABCDEF1234567890AB"
    user_ids: ["Test Key <test@example.invalid>"]
    aliases: ["0xCDEF1234567890AB", "test@example.invalid"]
behaviours:
  deny_key: "NOKEY0000000000000000000000000000000000"
  permission_denied: false
```

``aliases`` are additional strings the bridge may pass in
``--local-user`` that should resolve to the named key. ``behaviours``
steers the fake into error paths for negative tests.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from gpg_backend_common.cli import GpgBackend
from gpg_models.errors import (
    GpgBadSignatureError,
    GpgError,
    GpgNoSuchKeyError,
    GpgPermissionError,
)
from gpg_models.models import (
    SignRequest,
    SignResult,
    VerifyRequest,
    VerifyResult,
)


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
class FakeBackendStore(GpgBackend):
    """Fixture-driven backend used by tests and the e2e bridge harness."""

    keys: tuple[_FakeKey, ...] = ()
    behaviours: _Behaviours = field(default_factory=_Behaviours)

    def sign(self, request: SignRequest) -> SignResult:
        if self.behaviours.permission_denied:
            raise GpgPermissionError("fake: pinentry denied")
        key = self._resolve(request.local_user)
        if self.behaviours.deny_key and key.fingerprint == self.behaviours.deny_key:
            raise GpgNoSuchKeyError(f"fake: key {key.fingerprint} denied by fixture")
        signature = _synth_signature(key.fingerprint, request.payload, armor=request.armor)
        status_text = (
            f"[GNUPG:] SIG_CREATED D 1 10 00 0 {key.fingerprint} " "0 0 0 00000000000000000000\n"
        )
        return SignResult(
            signature=signature,
            status_text=status_text,
            exit_code=0,
            resolved_key_fingerprint=key.fingerprint,
        )

    def verify(self, request: VerifyRequest) -> VerifyResult:
        if self.behaviours.permission_denied:
            raise GpgPermissionError("fake: keyring unreachable")
        expected_prefix = b"-----BEGIN PGP SIGNATURE-----\n"
        if self.behaviours.corrupt_verify or not request.signature.startswith(expected_prefix):
            raise GpgBadSignatureError("fake: signature does not match payload")
        try:
            fingerprint = (
                request.signature.split(b"FAKE-FP:", 1)[1].split(b"\n", 1)[0].decode("ascii")
            )
        except (IndexError, UnicodeDecodeError) as exc:
            raise GpgBadSignatureError("fake: signature missing FAKE-FP marker") from exc
        expected_hash = hashlib.sha256(request.payload).hexdigest().upper()
        if f"PAYLOAD-HASH:{expected_hash}".encode("ascii") not in request.signature:
            raise GpgBadSignatureError("fake: payload hash mismatch")
        status_text = (
            f"[GNUPG:] GOODSIG {fingerprint} fake\n"
            f"[GNUPG:] VALIDSIG {fingerprint} 2026-04-23 0 4 0 1 10 00 {fingerprint}\n"
        )
        return VerifyResult(status_text=status_text, exit_code=0)

    def _resolve(self, requested: str) -> _FakeKey:
        for key in self.keys:
            if key.matches(requested):
                return key
        raise GpgNoSuchKeyError(f"fake: no key matches {requested!r}")


def load_fixture(data: Any) -> FakeBackendStore:
    """Parse a fixture-YAML mapping into a :class:`FakeBackendStore`."""
    if not isinstance(data, dict):
        raise GpgError("fake fixture: top-level document must be a mapping")
    raw_keys = data.get("keys") or []
    if not isinstance(raw_keys, list):
        raise GpgError("fake fixture: 'keys' must be a list")
    keys: list[_FakeKey] = []
    for entry in raw_keys:
        if not isinstance(entry, dict):
            raise GpgError("fake fixture: each key entry must be a mapping")
        fingerprint = entry.get("fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise GpgError("fake fixture: 'fingerprint' is required")
        user_ids_raw = entry.get("user_ids") or []
        aliases_raw = entry.get("aliases") or []
        if not isinstance(user_ids_raw, list) or not isinstance(aliases_raw, list):
            raise GpgError("fake fixture: 'user_ids' and 'aliases' must be lists")
        keys.append(
            _FakeKey(
                fingerprint=fingerprint.upper(),
                user_ids=tuple(str(u) for u in user_ids_raw),
                aliases=tuple(str(a) for a in aliases_raw),
            )
        )
    behaviours_raw = data.get("behaviours") or {}
    if not isinstance(behaviours_raw, dict):
        raise GpgError("fake fixture: 'behaviours' must be a mapping")
    behaviours = _Behaviours(
        deny_key=str(behaviours_raw.get("deny_key") or "").upper(),
        permission_denied=bool(behaviours_raw.get("permission_denied", False)),
        corrupt_verify=bool(behaviours_raw.get("corrupt_verify", False)),
    )
    return FakeBackendStore(keys=tuple(keys), behaviours=behaviours)


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


__all__ = ["FakeBackendStore", "load_fixture"]
