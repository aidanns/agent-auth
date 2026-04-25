# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared fixtures for the fault-injection test layer.

These tests deliberately force error conditions — SQLite write failures,
keyring unavailability, plugin timeouts, subprocess crashes — to verify
the service surface raises the documented typed error and records the
expected audit event. A fault that passes silently is exactly the gap
this layer is meant to catch.
"""

from pathlib import Path

import pytest

from agent_auth.audit import AuditLogger


@pytest.fixture
def audit_log_path(tmp_path: Path) -> Path:
    return tmp_path / "audit.log"


@pytest.fixture
def audit(audit_log_path: Path) -> AuditLogger:
    return AuditLogger(str(audit_log_path))
