# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Structured audit logging with HMAC chaining.

Every entry carries a ``chain_hmac`` field computed as
``HMAC-SHA256(audit_chain_key, previous_chain_hmac || canonical_json_of_entry)``,
where ``canonical_json_of_entry`` is the entry serialized with
sorted keys and ``chain_hmac`` stripped. A verifier can replay the
chain against the stored audit-chain key and detect any tampering —
a modified, inserted, or deleted entry breaks the chain at the
modification point and at every subsequent entry.

Schema rollover: ``SCHEMA_VERSION`` bumps to ``2`` when chaining
lands. On startup the logger inspects the tail of the existing log:

- If absent → start a fresh chain from the genesis seed.
- If the last entry is already ``schema_version: 2`` and carries a
  valid ``chain_hmac`` → resume the chain from that hmac.
- Otherwise (the log predates chaining, or the tail is unrecoverable)
  → rename the file to ``<log_path>.pre-chain-v2-<timestamp>`` and
  start a fresh chain in the original path. Operators keep the
  archived file as a legacy artefact.

See ADR 0028 for rationale.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from agent_auth import __version__ as _agent_auth_version
from agent_auth.keys import AuditChainKey

# Audit log schema version. Emitted on every entry so downstream consumers
# (SIEM, compliance, forensics) can detect the schema at parse time.
#
# Stability policy (see design/DESIGN.md "Audit log fields"):
#   - Adding a new optional field is non-breaking; version stays the same.
#   - Adding a new `event` kind is non-breaking; version stays the same.
#   - Renaming, removing, or re-typing an existing field is a breaking
#     change; bump SCHEMA_VERSION and announce in CHANGELOG.md.
#
# Version 2 (#103): adds the ``chain_hmac`` field on every entry. A v1
# log cannot be rewritten as v2 without replaying history against the
# audit-chain key, so the on-upgrade path renames the v1 file and
# starts a fresh v2 chain.
SCHEMA_VERSION = 2

# OTel resource attributes attached to every emitted entry. Allow audit
# consumers joining trails across services (SIEM, forensics) to filter
# by emitter without inferring it from the file path. things-bridge does
# not emit its own audit log (see design/DESIGN.md §Log streams — all
# bridge authorization traces come through agent-auth's validate
# endpoint), so ``service.name`` is a constant here. The field exists
# in the envelope so any future audit emitter in this project ships with
# a consistent shape from day one.
_SERVICE_NAME = "agent-auth"

# Genesis seed for the first entry's chain HMAC. 32 zero bytes — a
# fixed, well-known pre-image that the verifier also uses to start
# its replay.
_GENESIS_PREV_HMAC = b"\x00" * 32


class AuditLogger:
    """Writes HMAC-chained JSON-lines audit log entries to a file.

    The on-disk format is part of the project's public surface: one JSON
    object per line with at minimum ``timestamp`` (ISO 8601 UTC),
    ``schema_version`` (int, currently ``2``), ``service.name`` (string),
    ``service.version`` (string), ``event`` (string), and ``chain_hmac``
    (lowercase hex string, 64 chars for SHA-256) keys, plus any
    event-specific fields. See ``tests/test_audit_schema.py`` for the
    contract and ``tests/test_audit_chain.py`` for the chain contract.

    Thread-safe: a single ``threading.Lock`` guards both the prev-hmac
    state and the file append so concurrent writes produce a totally-
    ordered chain with no interleaved entries.
    """

    def __init__(self, log_path: str, audit_chain_key: AuditChainKey | None = None):
        self._log_path = log_path
        self._lock = threading.Lock()
        # Tests that don't care about chain verification don't need a
        # provisioned key; generate an ephemeral per-process key in
        # that case so chaining still runs through the real code
        # path. Production code always passes a keyring-provisioned
        # key via ``_init_services``.
        self._key: bytes = audit_chain_key if audit_chain_key is not None else os.urandom(32)
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        self._prev_chain_hmac: bytes = _resolve_initial_prev_hmac(log_path)

    def log(self, event: str, **details: Any) -> None:
        """Write a chained audit log entry."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "service.name": _SERVICE_NAME,
            "service.version": _agent_auth_version,
            "event": event,
            **details,
        }
        with self._lock:
            chain_hmac = _compute_chain_hmac(self._key, self._prev_chain_hmac, entry)
            entry["chain_hmac"] = chain_hmac.hex()
            line = json.dumps(entry, default=str) + "\n"
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line)
            self._prev_chain_hmac = chain_hmac

    def log_token_operation(self, event: str, **details: Any) -> None:
        self.log(event, **details)

    def log_authorization_decision(self, event: str, **details: Any) -> None:
        self.log(event, **details)


def _canonical_bytes(entry: dict[str, Any]) -> bytes:
    """Return the deterministic byte representation of an entry for HMAC input.

    Sorted keys and tight separators — the on-disk form stays in
    insertion order for readability, so the HMAC input is not the
    exact file bytes. Canonicalising here keeps the chain robust
    against reformatting that doesn't change semantics, but the
    trade-off is that a verifier must re-serialise rather than hash
    the raw line.
    """
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _compute_chain_hmac(
    key: bytes,
    prev_chain_hmac: bytes,
    entry_without_chain_hmac: dict[str, Any],
) -> bytes:
    """Compute HMAC-SHA256 over ``prev_hmac || canonical(entry)``.

    The prev-hmac prefix is what makes the chain detectable: changing
    any earlier entry changes the prev-hmac fed into every subsequent
    entry, so tampering cascades visibly.
    """
    canonical = _canonical_bytes(entry_without_chain_hmac)
    return hmac.new(key, prev_chain_hmac + canonical, hashlib.sha256).digest()


def _resolve_initial_prev_hmac(log_path: str) -> bytes:
    """Seed ``_prev_chain_hmac`` from the tail of an existing log.

    Returns ``_GENESIS_PREV_HMAC`` for a fresh log. Rolls over a
    pre-chain (v1) file by renaming it to
    ``<log_path>.pre-chain-v2-<YYYYMMDDTHHMMSSZ>`` so operators keep
    the legacy records as an archived artefact; the new chain then
    starts at genesis in the original path. A corrupt v2 tail is
    treated the same way — we cannot safely chain onto a line we
    cannot parse.
    """
    path = Path(log_path)
    if not path.is_file():
        return _GENESIS_PREV_HMAC

    last = _read_last_nonblank_line(path)
    if last is None:
        return _GENESIS_PREV_HMAC

    try:
        tail = json.loads(last)
    except json.JSONDecodeError:
        _rollover(path, reason="tail line is not valid JSON")
        return _GENESIS_PREV_HMAC

    if not isinstance(tail, dict):
        _rollover(path, reason="tail line is not a JSON object")
        return _GENESIS_PREV_HMAC

    tail_obj = cast(dict[str, Any], tail)
    if tail_obj.get("schema_version") != SCHEMA_VERSION:
        _rollover(
            path,
            reason=f"schema_version {tail_obj.get('schema_version')!r} precedes chaining",
        )
        return _GENESIS_PREV_HMAC

    stored_hmac = tail_obj.get("chain_hmac")
    if not isinstance(stored_hmac, str):
        _rollover(path, reason="tail entry missing chain_hmac")
        return _GENESIS_PREV_HMAC
    try:
        return bytes.fromhex(stored_hmac)
    except ValueError:
        _rollover(path, reason="tail chain_hmac is not valid hex")
        return _GENESIS_PREV_HMAC


def _read_last_nonblank_line(path: Path) -> str | None:
    """Return the last non-blank line of ``path``, or ``None`` if empty.

    Read whole-file — audit logs tend to be modest and operators rotate
    them out via ``logrotate``, so a naive pass is acceptable for the
    once-per-process startup cost.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = [line for line in content.splitlines() if line.strip()]
    if not lines:
        return None
    return lines[-1]


def _rollover(path: Path, *, reason: str) -> None:
    """Rename a pre-chain or corrupt log out of the way and report it to stderr.

    The caller then begins a fresh chain in the original path. Done
    synchronously on startup so the operator sees the rename in the
    process log and can locate the archived file.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archived = path.with_name(f"{path.name}.pre-chain-v2-{stamp}")
    try:
        path.rename(archived)
    except OSError as exc:
        print(
            f"agent-auth audit: failed to rename {path} to {archived} ({exc}); "
            "starting new chain in place (existing content will be appended)",
            file=sys.stderr,
            flush=True,
        )
        return
    print(
        f"agent-auth audit: rolled over {path} to {archived} ({reason}); "
        "starting fresh HMAC-chained log",
        file=sys.stderr,
        flush=True,
    )


class ChainVerificationFailure(Exception):
    """Audit-log chain verification found a mismatch or a missing entry."""

    def __init__(self, message: str, *, line_number: int):
        super().__init__(message)
        self.line_number = line_number


def verify_audit_chain(log_path: str, audit_chain_key: AuditChainKey) -> dict[str, int]:
    """Replay the HMAC chain in ``log_path`` against ``audit_chain_key``.

    Returns a counts dict with ``verified`` (chained entries whose
    ``chain_hmac`` matches the replayed computation) and
    ``legacy_skipped`` (entries with ``schema_version`` < 2, which
    predate chaining and are reported rather than verified). Raises
    ``ChainVerificationFailure`` on the first mismatch or malformed
    v2 entry; the exception carries the 1-based line number so the
    operator can locate the problem entry quickly.

    The verifier intentionally does not auto-skip a bad entry to
    resume after it — any tampering must be surfaced, and it is the
    operator's job to investigate before re-running.
    """
    counts = {"verified": 0, "legacy_skipped": 0}
    prev = _GENESIS_PREV_HMAC
    path = Path(log_path)
    if not path.is_file():
        return counts
    with path.open(encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ChainVerificationFailure(
                    f"line {line_number}: not valid JSON ({exc})",
                    line_number=line_number,
                ) from exc
            if not isinstance(entry, dict):
                raise ChainVerificationFailure(
                    f"line {line_number}: entry is not a JSON object",
                    line_number=line_number,
                )
            entry_obj = cast(dict[str, Any], entry)
            version = entry_obj.get("schema_version")
            if version != SCHEMA_VERSION:
                # Pre-chain entry — no HMAC to check. Reset prev to
                # genesis after the last legacy entry so the first v2
                # entry (if any) chains onto the right seed.
                counts["legacy_skipped"] += 1
                prev = _GENESIS_PREV_HMAC
                continue
            stored = entry_obj.get("chain_hmac")
            if not isinstance(stored, str):
                raise ChainVerificationFailure(
                    f"line {line_number}: schema_version {SCHEMA_VERSION} entry missing chain_hmac",
                    line_number=line_number,
                )
            try:
                stored_bytes = bytes.fromhex(stored)
            except ValueError as exc:
                raise ChainVerificationFailure(
                    f"line {line_number}: chain_hmac is not valid hex",
                    line_number=line_number,
                ) from exc
            entry_without_hmac: dict[str, Any] = {
                k: v for k, v in entry_obj.items() if k != "chain_hmac"
            }
            expected = _compute_chain_hmac(audit_chain_key, prev, entry_without_hmac)
            if not hmac.compare_digest(expected, stored_bytes):
                raise ChainVerificationFailure(
                    f"line {line_number}: chain_hmac mismatch (entry modified, "
                    "or a preceding entry was inserted / removed / tampered)",
                    line_number=line_number,
                )
            counts["verified"] += 1
            prev = stored_bytes
    return counts
