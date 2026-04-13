"""Structured audit logging for token operations and authorization decisions."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

_logger_counter = 0


class AuditLogger:
    """Writes JSON-lines audit log entries to a file."""

    def __init__(self, log_path: str):
        global _logger_counter
        Path(os.path.dirname(log_path)).mkdir(parents=True, exist_ok=True)
        _logger_counter += 1
        self._logger = logging.getLogger(f"agent_auth.audit.{_logger_counter}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        handler = logging.FileHandler(log_path)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)

    def log(self, event: str, **details):
        """Write an audit log entry."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **details,
        }
        self._logger.info(json.dumps(entry, default=str))

    def log_token_operation(self, event: str, **details):
        self.log(event, **details)

    def log_authorization_decision(self, event: str, **details):
        self.log(event, **details)
