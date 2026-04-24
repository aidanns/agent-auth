# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Contract tests for the audit-log schema.

Every documented audit event kind is exercised here. Each test writes one
event to a temp log, reads it back, and asserts the required fields are
present with the correct names and types.

Breaking schema changes (renaming a field, removing a field) will fail
these tests, which is the intent: the on-disk format is public API.
A breaking change must also bump ``SCHEMA_VERSION`` in
``packages/agent-auth/src/agent_auth/audit.py`` and announce in ``CHANGELOG.md`` (see
``design/DESIGN.md`` "Audit log fields").

Documented events
-----------------
Token operations: token_created, token_refreshed, token_reissued,
  token_revoked, token_rotated, scopes_modified, reissue_denied.
Authorization decisions: validation_allowed, validation_denied,
  approval_granted, approval_denied.
"""

import json
from datetime import datetime
from typing import Any, cast

from agent_auth.audit import SCHEMA_VERSION, AuditLogger

# -- helpers --


def _log_path(tmp_path):
    return str(tmp_path / "audit.log")


def _read_last_entry(path: str) -> dict[str, Any]:
    with open(path) as f:
        lines = [line.strip() for line in f if line.strip()]
    assert lines, "audit log is empty"
    return cast(dict[str, Any], json.loads(lines[-1]))


def test_schema_version_value(tmp_path):
    # The current wire-format schema version. A breaking change to the
    # audit-log schema must bump this constant. v2 (#103) added the
    # chain_hmac field — see tests/test_audit_chain.py for the chain
    # contract.
    assert SCHEMA_VERSION == 2
    logger = AuditLogger(_log_path(tmp_path))
    logger.log("token_created", family_id="fam-1")
    entry = _read_last_entry(_log_path(tmp_path))
    assert entry["schema_version"] == SCHEMA_VERSION


def test_service_resource_attributes_on_every_entry(tmp_path):
    # Pin the OTel resource envelope: downstream audit consumers rely
    # on ``service.name`` / ``service.version`` being present with
    # exactly those keys (dotted semconv names, not ``service_name``
    # etc.) on every entry regardless of event kind. A rename breaks
    # SIEM filter expressions.
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_token_operation("token_created", family_id="fam-1")
    logger.log_authorization_decision("validation_allowed", scope="x", tier="allow")
    with open(_log_path(tmp_path)) as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) == 2
    for entry in lines:
        assert entry["service.name"] == "agent-auth"
        assert isinstance(entry["service.version"], str) and entry["service.version"]


def _assert_base_fields(entry: dict[str, Any]) -> None:
    assert "timestamp" in entry
    assert "event" in entry
    assert "schema_version" in entry
    assert isinstance(entry["schema_version"], int)
    assert entry["schema_version"] == SCHEMA_VERSION
    ts = entry["timestamp"]
    # Must be ISO 8601 UTC (ends with +00:00 or Z)
    assert ts.endswith("+00:00") or ts.endswith("Z"), f"timestamp not UTC: {ts!r}"
    # Must parse as a datetime
    datetime.fromisoformat(ts.replace("Z", "+00:00"))
    # HMAC chain (schema_version == 2): every entry carries a lowercase
    # hex chain_hmac of SHA-256 width so a verifier can replay the chain
    # without special-casing missing fields. See tests/test_audit_chain.py
    # for the full chain contract (genesis seeding, tamper detection,
    # rollover semantics).
    assert "chain_hmac" in entry
    assert isinstance(entry["chain_hmac"], str)
    assert len(entry["chain_hmac"]) == 64  # SHA-256 hex
    assert all(c in "0123456789abcdef" for c in entry["chain_hmac"])
    # OTel resource attributes: every entry identifies its emitter so
    # SIEMs joining multi-service audit trails don't need to infer
    # service from the log path. ``service.name`` is constant today
    # (agent-auth is the only emitter by design — see DESIGN.md §Log
    # streams), but the schema reserves the field so a future emitter
    # ships with a consistent envelope.
    assert entry["service.name"] == "agent-auth"
    assert isinstance(entry["service.version"], str)
    assert entry["service.version"]  # non-empty


# -- token operation events --


def test_token_created_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_token_operation("token_created", family_id="fam-1", scopes=["things:read=allow"])
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "token_created"
    assert isinstance(entry["family_id"], str)
    assert "scopes" in entry


def test_token_refreshed_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_token_operation("token_refreshed", family_id="fam-1")
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "token_refreshed"
    assert isinstance(entry["family_id"], str)


def test_token_reissued_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_token_operation("token_reissued", family_id="fam-1")
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "token_reissued"
    assert isinstance(entry["family_id"], str)


def test_token_revoked_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_token_operation("token_revoked", family_id="fam-1")
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "token_revoked"
    assert isinstance(entry["family_id"], str)


def test_token_revoked_with_reason_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_token_operation(
        "token_revoked", family_id="fam-1", reason="refresh_token_reuse_detected"
    )
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "token_revoked"
    assert isinstance(entry["family_id"], str)
    assert isinstance(entry["reason"], str)


def test_token_rotated_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_token_operation(
        "token_rotated",
        old_family_id="fam-old",
        new_family_id="fam-new",
        scopes=["things:read=allow"],
    )
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "token_rotated"
    assert isinstance(entry["old_family_id"], str)
    assert isinstance(entry["new_family_id"], str)
    assert "scopes" in entry


def test_scopes_modified_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_token_operation("scopes_modified", family_id="fam-1", scopes=["things:read=allow"])
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "scopes_modified"
    assert isinstance(entry["family_id"], str)
    assert "scopes" in entry


def test_reissue_denied_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_token_operation("reissue_denied", family_id="fam-1")
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "reissue_denied"
    assert isinstance(entry["family_id"], str)


# -- authorization decision events --


def test_validation_allowed_allow_tier_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_authorization_decision(
        "validation_allowed", token_id="tok-1", scope="things:read", tier="allow"
    )
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "validation_allowed"
    assert isinstance(entry["token_id"], str)
    assert isinstance(entry["scope"], str)
    assert isinstance(entry["tier"], str)


def test_validation_allowed_prompt_tier_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_authorization_decision(
        "validation_allowed",
        token_id="tok-1",
        scope="things:read",
        tier="prompt",
        grant_type="once",
    )
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "validation_allowed"
    assert isinstance(entry["token_id"], str)
    assert isinstance(entry["scope"], str)
    assert entry["tier"] == "prompt"
    assert isinstance(entry["grant_type"], str)


def test_validation_denied_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_authorization_decision(
        "validation_denied", reason="token_expired", token_id="tok-1", scope="things:read"
    )
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "validation_denied"
    assert isinstance(entry["reason"], str)
    assert isinstance(entry["scope"], str)


def test_validation_denied_without_token_id_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_authorization_decision(
        "validation_denied", reason="invalid_token", scope="things:read"
    )
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "validation_denied"
    assert isinstance(entry["reason"], str)
    assert isinstance(entry["scope"], str)


def test_approval_granted_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_authorization_decision(
        "approval_granted",
        family_id="fam-1",
        scope="things:read",
        grant_type="once",
        duration_minutes=None,
    )
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "approval_granted"
    assert isinstance(entry["family_id"], str)
    assert isinstance(entry["scope"], str)
    assert "grant_type" in entry
    assert "duration_minutes" in entry


def test_approval_denied_schema(tmp_path):
    logger = AuditLogger(_log_path(tmp_path))
    logger.log_authorization_decision("approval_denied", family_id="fam-1", scope="things:read")
    entry = _read_last_entry(_log_path(tmp_path))
    _assert_base_fields(entry)
    assert entry["event"] == "approval_denied"
    assert isinstance(entry["family_id"], str)
    assert isinstance(entry["scope"], str)
