# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Structured audit logging for token operations and authorization decisions."""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_auth import __version__ as _agent_auth_version

# Audit log schema version. Emitted on every entry so downstream consumers
# (SIEM, compliance, forensics) can detect the schema at parse time.
#
# Stability policy (see design/DESIGN.md "Audit log fields"):
#   - Adding a new optional field is non-breaking; version stays the same.
#   - Adding a new `event` kind is non-breaking; version stays the same.
#   - Renaming, removing, or re-typing an existing field is a breaking
#     change; bump SCHEMA_VERSION and announce in CHANGELOG.md.
SCHEMA_VERSION = 1

# OTel resource attributes attached to every emitted entry. Allow audit
# consumers joining trails across services (SIEM, forensics) to filter
# by emitter without inferring it from the file path. things-bridge does
# not emit its own audit log (see design/DESIGN.md §Log streams — all
# bridge authorization traces come through agent-auth's validate
# endpoint), so ``service.name`` is a constant here. The field exists
# in the envelope so any future audit emitter in this project ships with
# a consistent shape from day one.
_SERVICE_NAME = "agent-auth"


class AuditLogger:
    """Writes JSON-lines audit log entries to a file.

    The on-disk format is part of the project's public surface: one JSON
    object per line with at minimum ``timestamp`` (ISO 8601 UTC),
    ``schema_version`` (int), ``service.name`` (string),
    ``service.version`` (string), and ``event`` (string) keys, plus any
    event-specific fields. See ``tests/test_audit_schema.py`` for the
    contract.
    """

    def __init__(self, log_path: str):
        self._log_path = log_path
        self._lock = threading.Lock()
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **details: Any) -> None:
        """Write an audit log entry."""
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "service.name": _SERVICE_NAME,
            "service.version": _agent_auth_version,
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
