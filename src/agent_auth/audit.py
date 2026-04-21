# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Structured audit logging for token operations and authorization decisions."""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLogger:
    """Writes JSON-lines audit log entries to a file.

    The on-disk format is part of the project's public surface: one JSON
    object per line with at minimum ``timestamp`` (ISO 8601 UTC) and
    ``event`` keys, plus any event-specific fields. See
    ``tests/test_audit.py`` for the contract.
    """

    def __init__(self, log_path: str):
        self._log_path = log_path
        self._lock = threading.Lock()
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **details: Any) -> None:
        """Write an audit log entry."""
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            **details,
        }
        line = json.dumps(entry, default=str) + "\n"
        with self._lock, open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line)

    def log_token_operation(self, event: str, **details: Any) -> None:
        self.log(event, **details)

    def log_authorization_decision(self, event: str, **details: Any) -> None:
        self.log(event, **details)
