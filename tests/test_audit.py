"""Tests for audit logging."""

import json
import os

import pytest

from agent_auth.audit import AuditLogger


@pytest.mark.covers_function("Log Token Operation", "Log Authorization Decision")
def test_writes_json_lines(tmp_dir):
    log_path = os.path.join(tmp_dir, "audit.log")
    logger = AuditLogger(log_path)
    logger.log("token_created", family_id="fam1", scopes={"a:read": "allow"})
    logger.log("validation_allowed", token_id="tok1", scope="a:read")

    # Force flush
    for handler in logger._logger.handlers:
        handler.flush()

    with open(log_path) as f:
        lines = f.readlines()
    assert len(lines) == 2

    entry1 = json.loads(lines[0])
    assert entry1["event"] == "token_created"
    assert entry1["family_id"] == "fam1"
    assert "timestamp" in entry1

    entry2 = json.loads(lines[1])
    assert entry2["event"] == "validation_allowed"
