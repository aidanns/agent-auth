# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Contract tests for the audit-log HMAC chain (schema v2, #103).

Each entry's ``chain_hmac`` is
``HMAC-SHA256(audit_chain_key, prev_chain_hmac || canonical(entry))``,
with ``prev`` of the first entry seeded from 32 zero bytes. This
module exercises:

- End-to-end verification across a multi-entry log.
- Tamper detection on modify, delete, and insert.
- Rollover of a pre-chain (v1) file and a corrupt tail.
- Deterministic replay: re-creating the ``AuditLogger`` on the same
  file resumes from the last chain_hmac.
"""

from __future__ import annotations

import json

import pytest

from agent_auth.audit import (
    AuditLogger,
    ChainVerificationFailure,
    verify_audit_chain,
)
from agent_auth.keys import AuditChainKey


def _log_path(tmp_path):
    return str(tmp_path / "audit.log")


def _fixed_key() -> AuditChainKey:
    # Fixed key for reproducibility; not a real secret.
    return AuditChainKey(b"\x01" * 32)


def _entries(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def test_chain_verifies_over_many_entries(tmp_path):
    path = _log_path(tmp_path)
    logger = AuditLogger(path, audit_chain_key=_fixed_key())
    for i in range(5):
        logger.log("token_created", family_id=f"fam-{i}")
    counts = verify_audit_chain(path, _fixed_key())
    assert counts == {"verified": 5, "legacy_skipped": 0}


def test_modifying_an_entry_breaks_the_chain(tmp_path):
    path = _log_path(tmp_path)
    logger = AuditLogger(path, audit_chain_key=_fixed_key())
    for i in range(3):
        logger.log("token_created", family_id=f"fam-{i}")
    # Tamper: edit the middle entry's family_id without recomputing
    # its chain_hmac.
    entries = _entries(path)
    entries[1]["family_id"] = "fam-tampered"
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    with pytest.raises(ChainVerificationFailure) as exc_info:
        verify_audit_chain(path, _fixed_key())
    assert exc_info.value.line_number == 2


def test_deleting_an_entry_breaks_the_chain(tmp_path):
    path = _log_path(tmp_path)
    logger = AuditLogger(path, audit_chain_key=_fixed_key())
    for i in range(3):
        logger.log("token_created", family_id=f"fam-{i}")
    entries = _entries(path)
    # Drop the middle entry — the next entry's chain_hmac was computed
    # against the dropped entry's hmac, so verification fails there.
    del entries[1]
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    with pytest.raises(ChainVerificationFailure):
        verify_audit_chain(path, _fixed_key())


def test_inserting_a_forged_entry_breaks_the_chain(tmp_path):
    path = _log_path(tmp_path)
    logger = AuditLogger(path, audit_chain_key=_fixed_key())
    logger.log("token_created", family_id="fam-0")
    logger.log("token_revoked", family_id="fam-0")
    entries = _entries(path)
    # Attacker inserts a synthetic entry between the real two.
    forged = dict(entries[0])
    forged["event"] = "token_created"
    forged["family_id"] = "fam-forged"
    forged["chain_hmac"] = "f" * 64  # plausible but wrong
    entries.insert(1, forged)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    with pytest.raises(ChainVerificationFailure) as exc_info:
        verify_audit_chain(path, _fixed_key())
    # The forged line itself has the wrong chain_hmac — verification
    # fails at line 2 (1-indexed).
    assert exc_info.value.line_number == 2


def test_chain_resumes_on_reopen(tmp_path):
    # A second ``AuditLogger`` constructed on the same path must read
    # the tail and seed its prev-hmac from the last entry — otherwise
    # the chain would break across service restarts.
    path = _log_path(tmp_path)
    key = _fixed_key()
    logger_a = AuditLogger(path, audit_chain_key=key)
    logger_a.log("token_created", family_id="fam-0")
    logger_a.log("token_created", family_id="fam-1")
    del logger_a  # simulate process exit / reopen
    logger_b = AuditLogger(path, audit_chain_key=key)
    logger_b.log("token_created", family_id="fam-2")
    counts = verify_audit_chain(path, key)
    assert counts == {"verified": 3, "legacy_skipped": 0}


def test_rollover_on_pre_chain_log(tmp_path):
    # Simulate an existing v1 log (no chain_hmac, schema_version 1).
    # AuditLogger must rename it out of the way and start a fresh
    # chain at the original path.
    path = tmp_path / "audit.log"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-04-22T00:00:00+00:00",
                "schema_version": 1,
                "service.name": "agent-auth",
                "service.version": "0.0.0+unknown",
                "event": "token_created",
                "family_id": "fam-legacy",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    logger = AuditLogger(str(path), audit_chain_key=_fixed_key())
    logger.log("token_created", family_id="fam-new")
    # New chain starts at genesis in the original file; the v1 entry
    # was renamed so the fresh log contains only the v2 entry.
    entries = _entries(path)
    assert len(entries) == 1
    assert entries[0]["schema_version"] == 2
    assert entries[0]["family_id"] == "fam-new"
    # Exactly one archived file exists next to the original.
    archives = [p for p in tmp_path.iterdir() if p.name.startswith("audit.log.pre-chain-v2-")]
    assert len(archives) == 1
    verify_audit_chain(str(path), _fixed_key())


def test_rollover_on_corrupt_tail(tmp_path):
    # A trailing line that isn't valid JSON is treated like a pre-chain
    # file — renamed, fresh chain starts. Can't safely chain onto a
    # line we can't parse.
    path = tmp_path / "audit.log"
    path.write_text("{not-json\n", encoding="utf-8")
    logger = AuditLogger(str(path), audit_chain_key=_fixed_key())
    logger.log("token_created", family_id="fam-0")
    entries = _entries(path)
    assert len(entries) == 1


def test_verifier_tolerates_legacy_only_file(tmp_path):
    # A pre-chain file that happens to still exist (the rollover
    # creates it) must not fail verification — legacy entries count
    # separately rather than raising.
    path = tmp_path / "legacy.log"
    path.write_text(
        "".join(
            json.dumps(
                {
                    "timestamp": "2026-04-22T00:00:00+00:00",
                    "schema_version": 1,
                    "service.name": "agent-auth",
                    "service.version": "0.0.0",
                    "event": "token_created",
                    "family_id": f"fam-{j}",
                }
            )
            + "\n"
            for j in range(3)
        ),
        encoding="utf-8",
    )
    counts = verify_audit_chain(str(path), _fixed_key())
    assert counts == {"verified": 0, "legacy_skipped": 3}


def test_missing_log_file_verifies_empty_counts(tmp_path):
    # A service that has never written an audit entry should verify
    # trivially rather than raising — a fresh install with no
    # operations is a valid state.
    counts = verify_audit_chain(str(tmp_path / "does-not-exist.log"), _fixed_key())
    assert counts == {"verified": 0, "legacy_skipped": 0}


def test_chain_hmac_absent_on_v2_entry_fails_verification(tmp_path):
    # A v2 entry missing its chain_hmac is treated as tampering: the
    # verifier raises rather than silently skipping, because an
    # attacker could otherwise trim the field to bypass checks.
    path = tmp_path / "audit.log"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-04-22T00:00:00+00:00",
                "schema_version": 2,
                "service.name": "agent-auth",
                "service.version": "0.0.0",
                "event": "token_created",
                "family_id": "fam-0",
                # chain_hmac deliberately absent
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ChainVerificationFailure):
        verify_audit_chain(str(path), _fixed_key())
