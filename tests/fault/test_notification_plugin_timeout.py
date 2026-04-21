# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: notification plugin timeout / exception.

The notification plugin is in-process (see #6 for the out-of-process
migration), so a plugin that raises or never returns is today the
single dominant JIT-approval failure mode. These tests assert that
both behaviours propagate out of ``ApprovalManager.request_approval``
rather than being silently converted to "approved" or "denied".
"""

import contextlib
import os
from pathlib import Path
from typing import Any

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.audit import AuditLogger
from agent_auth.keys import EncryptionKey
from agent_auth.plugins import ApprovalResult, NotificationPlugin
from agent_auth.store import TokenStore
from tests.fault.conftest import read_audit_events


@pytest.fixture
def store(tmp_path: Path) -> TokenStore:
    return TokenStore(str(tmp_path / "tokens.db"), EncryptionKey(os.urandom(32)))


class _RaisingPlugin(NotificationPlugin):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)

    def request_approval(
        self, scope: str, description: str | None, family_id: str
    ) -> ApprovalResult:
        raise TimeoutError("notification plugin timed out after 30s")


class _GenericErrorPlugin(NotificationPlugin):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)

    def request_approval(
        self, scope: str, description: str | None, family_id: str
    ) -> ApprovalResult:
        raise RuntimeError("macOS Notification Center returned an error")


def test_plugin_timeout_propagates(store: TokenStore, audit: AuditLogger) -> None:
    """A TimeoutError from the plugin propagates out of ``request_approval``.

    The manager must not silently convert the timeout into an approval
    or a denial — the caller (the server validate handler) decides
    how to translate the failure into an HTTP response.
    """
    manager = ApprovalManager(plugin=_RaisingPlugin(), store=store, audit=audit)
    with pytest.raises(TimeoutError, match="timed out after 30s"):
        manager.request_approval("fam-1", "things:read", description="list todos")


def test_plugin_exception_propagates(store: TokenStore, audit: AuditLogger) -> None:
    """A generic plugin RuntimeError also propagates (not swallowed)."""
    manager = ApprovalManager(plugin=_GenericErrorPlugin(), store=store, audit=audit)
    with pytest.raises(RuntimeError, match="Notification Center returned an error"):
        manager.request_approval("fam-1", "things:read", description="list todos")


def test_plugin_failure_does_not_leave_stale_grant(
    store: TokenStore, audit: AuditLogger, audit_log_path: Path
) -> None:
    """A failed plugin call must not record an approval_granted audit event.

    The audit stream is the authoritative record of what actually
    happened; emitting ``approval_granted`` on an exception would give
    an operator a false "user approved this request" signal.
    """
    manager = ApprovalManager(plugin=_RaisingPlugin(), store=store, audit=audit)
    with contextlib.suppress(TimeoutError):
        manager.request_approval("fam-1", "things:read")

    events = read_audit_events(audit_log_path)
    assert not any(e.get("event") == "approval_granted" for e in events)
    assert not manager.check_timed_grant("fam-1", "things:read")
