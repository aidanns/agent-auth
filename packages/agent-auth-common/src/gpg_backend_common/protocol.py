# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Stdin framing for the ``verify`` backend subcommand.

The sign command reads the whole stdin as the payload. The verify
command reads a 4-byte big-endian length, then that many bytes of
signature, then the payload to end-of-stream. Framing lives inside the
bridge ↔ backend contract so the bridge's HTTP surface can stay a
single JSON document.
"""

from __future__ import annotations

import struct
from typing import IO

_LENGTH_STRUCT = struct.Struct(">I")
_MAX_SIGNATURE_BYTES = 1 * 1024 * 1024  # 1 MiB — sigs are <10 KiB in practice.


def read_verify_input(stdin: IO[bytes]) -> tuple[bytes, bytes]:
    """Read a verify-framed ``(signature, payload)`` pair from ``stdin``."""
    header = _read_exact(stdin, _LENGTH_STRUCT.size)
    (sig_len,) = _LENGTH_STRUCT.unpack(header)
    if sig_len > _MAX_SIGNATURE_BYTES:
        raise ValueError(f"verify signature length {sig_len} exceeds max {_MAX_SIGNATURE_BYTES}")
    signature = _read_exact(stdin, sig_len)
    payload = stdin.read()
    return signature, payload


def write_verify_input(stdin: IO[bytes], signature: bytes, payload: bytes) -> None:
    """Write a verify-framed ``(signature, payload)`` pair to ``stdin``."""
    if len(signature) > _MAX_SIGNATURE_BYTES:
        raise ValueError(
            f"verify signature length {len(signature)} exceeds max {_MAX_SIGNATURE_BYTES}"
        )
    stdin.write(_LENGTH_STRUCT.pack(len(signature)))
    stdin.write(signature)
    stdin.write(payload)


def _read_exact(stdin: IO[bytes], n: int) -> bytes:
    buf = bytearray()
    remaining = n
    while remaining > 0:
        chunk = stdin.read(remaining)
        if not chunk:
            raise ValueError(f"verify stdin truncated: expected {n} bytes, got {len(buf)}")
        buf.extend(chunk)
        remaining -= len(chunk)
    return bytes(buf)


__all__ = ["read_verify_input", "write_verify_input"]
