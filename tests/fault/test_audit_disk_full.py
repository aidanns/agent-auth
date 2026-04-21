# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: audit-log disk full / unwritable.

If the audit log cannot be written the service must surface the failure
(``OSError`` from the underlying write) rather than silently discarding
the event. Silent discard is the exact failure the audit surface exists
to prevent.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_auth.audit import AuditLogger


def test_audit_log_surfaces_disk_full(audit_log_path: Path) -> None:
    """ENOSPC on the audit log write propagates as OSError."""
    audit = AuditLogger(str(audit_log_path))

    def raise_enospc(*args, **kwargs):
        raise OSError(28, "No space left on device")

    with patch("builtins.open", side_effect=raise_enospc), pytest.raises(OSError) as exc_info:
        audit.log_authorization_decision("validation_allowed", scope="things:read")
    assert exc_info.value.errno == 28


def test_audit_log_surfaces_read_only_filesystem(tmp_path: Path) -> None:
    """Writing to an audit-log path without write permission raises PermissionError."""
    log_dir = tmp_path / "audit"
    log_dir.mkdir()
    log_path = log_dir / "audit.log"
    log_path.write_text("")
    log_path.chmod(0o444)
    try:
        audit = AuditLogger(str(log_path))
        with pytest.raises(PermissionError):
            audit.log_authorization_decision("validation_denied", scope="things:read")
    finally:
        log_path.chmod(0o644)
