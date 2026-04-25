# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for audit logging."""

import json
import os
import re

import pytest

from agent_auth.audit import AuditLogger


@pytest.mark.covers_function("Log Token Operation", "Log Authorization Decision")
def test_writes_json_lines(tmp_dir):
    log_path = os.path.join(tmp_dir, "audit.log")
    logger = AuditLogger(log_path)
    logger.log("token_created", family_id="fam1", scopes={"a:read": "allow"})
    logger.log("validation_allowed", token_id="tok1", scope="a:read")

    with open(log_path) as f:
        lines = f.readlines()
    assert len(lines) == 2

    entry1 = json.loads(lines[0])
    assert entry1["event"] == "token_created"
    assert entry1["family_id"] == "fam1"
    assert entry1["scopes"] == {"a:read": "allow"}

    entry2 = json.loads(lines[1])
    assert entry2["event"] == "validation_allowed"
    assert entry2["token_id"] == "tok1"


@pytest.mark.covers_function("Log Token Operation")
def test_timestamp_is_iso8601_utc(tmp_dir):
    """The timestamp field is part of the public audit-log contract."""
    log_path = os.path.join(tmp_dir, "audit.log")
    AuditLogger(log_path).log("token_created", family_id="fam1")

    with open(log_path) as f:
        entry = json.loads(f.readline())
    # ISO 8601 UTC, e.g. 2026-04-14T12:34:56.789012+00:00
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00$", entry["timestamp"])


@pytest.mark.covers_function("Log Token Operation")
def test_entries_preserve_required_keys(tmp_dir):
    """Every entry must carry timestamp and event keys."""
    log_path = os.path.join(tmp_dir, "audit.log")
    logger = AuditLogger(log_path)
    logger.log_token_operation("token_revoked", family_id="fam1")
    logger.log_authorization_decision("validation_denied", reason="token_expired")

    with open(log_path) as f:
        entries = [json.loads(line) for line in f]
    for entry in entries:
        assert set(entry).issuperset({"timestamp", "event"})
