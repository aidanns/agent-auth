"""Tests for the JIT approval manager."""

import os

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.audit import AuditLogger
from agent_auth.plugins import ApprovalResult, NotificationPlugin
from agent_auth.store import TokenStore


class MockPlugin(NotificationPlugin):
    """Plugin that returns a preconfigured response."""

    def __init__(self, result: ApprovalResult):
        super().__init__()
        self._result = result
        self.calls = []

    def request_approval(self, scope, description, family_id):
        self.calls.append((scope, description, family_id))
        return self._result


def _make_manager(tmp_dir, encryption_key, result):
    store = TokenStore(os.path.join(tmp_dir, "tokens.db"), encryption_key)
    audit = AuditLogger(os.path.join(tmp_dir, "audit.log"))
    plugin = MockPlugin(result)
    return ApprovalManager(plugin, store, audit), plugin


@pytest.mark.covers_function("Request Approval", "Record Approval Grant")
def test_approval_granted(tmp_dir, encryption_key):
    result = ApprovalResult(approved=True, grant_type="once")
    manager, plugin = _make_manager(tmp_dir, encryption_key, result)
    resp = manager.request_approval("fam1", "things:write", "Complete todo")
    assert resp.approved
    assert len(plugin.calls) == 1


@pytest.mark.covers_function("Request Approval")
def test_approval_denied(tmp_dir, encryption_key):
    result = ApprovalResult(approved=False)
    manager, _plugin = _make_manager(tmp_dir, encryption_key, result)
    resp = manager.request_approval("fam1", "things:write", "Complete todo")
    assert not resp.approved


@pytest.mark.covers_function("Check Existing Grant", "Record Approval Grant", "Expire Grants")
def test_timed_grant_caches(tmp_dir, encryption_key):
    result = ApprovalResult(approved=True, grant_type="timed", duration_minutes=60)
    manager, plugin = _make_manager(tmp_dir, encryption_key, result)

    resp1 = manager.request_approval("fam1", "things:write")
    assert resp1.approved
    assert len(plugin.calls) == 1

    resp2 = manager.request_approval("fam1", "things:write")
    assert resp2.approved
    assert len(plugin.calls) == 1  # Plugin not called again — grant still active


@pytest.mark.covers_function("Check Existing Grant")
def test_once_grant_does_not_cache(tmp_dir, encryption_key):
    result = ApprovalResult(approved=True, grant_type="once")
    manager, plugin = _make_manager(tmp_dir, encryption_key, result)

    manager.request_approval("fam1", "things:write")
    manager.request_approval("fam1", "things:write")
    assert len(plugin.calls) == 2  # Plugin called each time
