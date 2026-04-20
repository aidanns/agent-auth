"""Contract tests for the audit-log schema.

Every documented audit event kind is exercised here. Each test writes one
event to a temp log, reads it back, and asserts the required fields are
present with the correct names and types.

Breaking schema changes (renaming a field, removing a field) will fail
these tests, which is the intent: the on-disk format is public API.

Documented events
-----------------
Token operations: token_created, token_refreshed, token_reissued,
  token_revoked, token_rotated, scopes_modified, reissue_denied.
Authorization decisions: validation_allowed, validation_denied,
  approval_granted, approval_denied.
"""

import json
from datetime import datetime

from agent_auth.audit import AuditLogger

# -- helpers --


def _log_path(tmp_path):
    return str(tmp_path / "audit.log")


def _read_last_entry(path: str) -> dict:
    with open(path) as f:
        lines = [line.strip() for line in f if line.strip()]
    assert lines, "audit log is empty"
    return json.loads(lines[-1])


def _assert_base_fields(entry: dict) -> None:
    assert "timestamp" in entry
    assert "event" in entry
    ts = entry["timestamp"]
    # Must be ISO 8601 UTC (ends with +00:00 or Z)
    assert ts.endswith("+00:00") or ts.endswith("Z"), f"timestamp not UTC: {ts!r}"
    # Must parse as a datetime
    datetime.fromisoformat(ts.replace("Z", "+00:00"))


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
