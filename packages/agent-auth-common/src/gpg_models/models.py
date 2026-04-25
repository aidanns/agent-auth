# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Request / result dataclasses for the gpg sign and verify flows.

These are the on-the-wire shapes between gpg-cli and gpg-bridge.
The bridge translates HTTP JSON bodies into these dataclasses on
ingress and serialises them back to JSON on the response. Per the
2026-04-25 collapse-the-backend-hop amendment to ADR 0033, the
bridge invokes ``gpg`` directly per request, so these dataclasses
no longer flow over a separate subprocess JSON envelope —
HTTP is the only on-the-wire usage.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

_KEYID_FORMATS = frozenset({"none", "short", "0xshort", "long", "0xlong"})


def validate_keyid_format(value: str) -> str:
    """Return ``value`` if it is one of the keyid formats gpg accepts."""
    if value not in _KEYID_FORMATS:
        valid = ", ".join(sorted(_KEYID_FORMATS))
        raise ValueError(f"Invalid keyid_format {value!r}; must be one of: {valid}")
    return value


@dataclass(frozen=True)
class SignRequest:
    """Inputs to a single ``gpg --detach-sign`` invocation."""

    local_user: str
    payload: bytes
    armor: bool = True
    status_fd_enabled: bool = True
    keyid_format: str = "long"

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SignRequest:
        payload_b64 = data.get("payload_b64")
        if not isinstance(payload_b64, str):
            raise ValueError("SignRequest: payload_b64 is required and must be a string")
        local_user = data.get("local_user")
        if not isinstance(local_user, str) or not local_user:
            raise ValueError("SignRequest: local_user is required and must be non-empty")
        keyid_format = data.get("keyid_format", "long")
        if not isinstance(keyid_format, str):
            raise ValueError("SignRequest: keyid_format must be a string")
        return cls(
            local_user=local_user,
            payload=base64.b64decode(payload_b64, validate=True),
            armor=bool(data.get("armor", True)),
            status_fd_enabled=bool(data.get("status_fd_enabled", True)),
            keyid_format=validate_keyid_format(keyid_format),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "local_user": self.local_user,
            "armor": self.armor,
            "status_fd_enabled": self.status_fd_enabled,
            "keyid_format": self.keyid_format,
            "payload_b64": base64.b64encode(self.payload).decode("ascii"),
        }


@dataclass(frozen=True)
class SignResult:
    """Outputs of a successful sign invocation."""

    signature: bytes
    status_text: str
    exit_code: int
    resolved_key_fingerprint: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SignResult:
        signature_b64 = data.get("signature_b64")
        if not isinstance(signature_b64, str):
            raise ValueError("SignResult: signature_b64 is required and must be a string")
        status_text = data.get("status_text") or ""
        if not isinstance(status_text, str):
            raise ValueError("SignResult: status_text must be a string")
        exit_code = data.get("exit_code", 0)
        if not isinstance(exit_code, int):
            raise ValueError("SignResult: exit_code must be an int")
        resolved = data.get("resolved_key_fingerprint", "") or ""
        if not isinstance(resolved, str):
            raise ValueError("SignResult: resolved_key_fingerprint must be a string")
        return cls(
            signature=base64.b64decode(signature_b64, validate=True),
            status_text=status_text,
            exit_code=exit_code,
            resolved_key_fingerprint=resolved,
        )

    def to_json(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "signature_b64": base64.b64encode(self.signature).decode("ascii"),
            "status_text": self.status_text,
            "exit_code": self.exit_code,
        }
        if self.resolved_key_fingerprint:
            body["resolved_key_fingerprint"] = self.resolved_key_fingerprint
        return body


@dataclass(frozen=True)
class VerifyRequest:
    """Inputs to a single ``gpg --verify`` invocation."""

    signature: bytes
    payload: bytes
    keyid_format: str = "long"

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> VerifyRequest:
        signature_b64 = data.get("signature_b64")
        payload_b64 = data.get("payload_b64")
        if not isinstance(signature_b64, str) or not isinstance(payload_b64, str):
            raise ValueError("VerifyRequest: signature_b64 and payload_b64 are required strings")
        keyid_format = data.get("keyid_format", "long")
        if not isinstance(keyid_format, str):
            raise ValueError("VerifyRequest: keyid_format must be a string")
        return cls(
            signature=base64.b64decode(signature_b64, validate=True),
            payload=base64.b64decode(payload_b64, validate=True),
            keyid_format=validate_keyid_format(keyid_format),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "signature_b64": base64.b64encode(self.signature).decode("ascii"),
            "payload_b64": base64.b64encode(self.payload).decode("ascii"),
            "keyid_format": self.keyid_format,
        }


@dataclass(frozen=True)
class VerifyResult:
    """Outputs of a verify invocation."""

    status_text: str
    exit_code: int

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> VerifyResult:
        status_text = data.get("status_text") or ""
        if not isinstance(status_text, str):
            raise ValueError("VerifyResult: status_text must be a string")
        exit_code = data.get("exit_code", 0)
        if not isinstance(exit_code, int):
            raise ValueError("VerifyResult: exit_code must be an int")
        return cls(status_text=status_text, exit_code=exit_code)

    def to_json(self) -> dict[str, Any]:
        return {
            "status_text": self.status_text,
            "exit_code": self.exit_code,
        }


__all__ = [
    "SignRequest",
    "SignResult",
    "VerifyRequest",
    "VerifyResult",
    "validate_keyid_format",
]
