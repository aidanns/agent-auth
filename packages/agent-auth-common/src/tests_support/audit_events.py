# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared helper for the fault-injection layer.

Lives in ``tests_support`` rather than each per-package fault
``conftest.py`` so mypy can resolve it via a stable absolute import.
Per-package ``tests/`` and ``tests/fault/`` directories are namespace
packages (no ``__init__.py``), which mypy collapses to colliding
``conftest`` module names across the workspace; routing the helper
through ``tests_support`` keeps the import absolute and unique.
"""

from __future__ import annotations

import json
from pathlib import Path


def read_audit_events(audit_log_path: Path) -> list[dict[str, object]]:
    """Parse the JSONL audit log into a list of events (empty if absent)."""
    if not audit_log_path.exists():
        return []
    return [
        json.loads(line)
        for line in audit_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
