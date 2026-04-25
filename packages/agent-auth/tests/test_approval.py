# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for the JIT approval manager."""

import os

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.approval_client import ApprovalClient, ApprovalResult
from agent_auth.audit import AuditLogger
from agent_auth.store import TokenStore
from tests_support.notifier_fake import NotifierFake


def _make_manager(tmp_dir, encryption_key, *, approved, grant_type="once", duration_minutes=None):
    """Return ``(manager, notifier)`` pointed at an in-process HTTP fake."""
    store = TokenStore(os.path.join(tmp_dir, "tokens.db"), encryption_key)
    audit = AuditLogger(os.path.join(tmp_dir, "audit.log"))
    notifier = NotifierFake(
        approved=approved,
        grant_type=grant_type,
        duration_minutes=duration_minutes,
    )
    client = ApprovalClient(url=notifier.url)
    return ApprovalManager(client, store, audit), notifier


@pytest.mark.covers_function("Request Approval", "Record Approval Grant")
def test_approval_granted(tmp_dir, encryption_key):
    manager, notifier = _make_manager(tmp_dir, encryption_key, approved=True)
    try:
        resp = manager.request_approval("fam1", "things:write", "Complete todo")
        assert resp.approved
        assert len(notifier.received) == 1
    finally:
        notifier.stop()


@pytest.mark.covers_function("Request Approval")
def test_approval_denied(tmp_dir, encryption_key):
    manager, notifier = _make_manager(tmp_dir, encryption_key, approved=False)
    try:
        resp = manager.request_approval("fam1", "things:write", "Complete todo")
        assert not resp.approved
    finally:
        notifier.stop()


@pytest.mark.covers_function("Check Existing Grant", "Record Approval Grant", "Expire Grants")
def test_timed_grant_caches(tmp_dir, encryption_key):
    manager, notifier = _make_manager(
        tmp_dir, encryption_key, approved=True, grant_type="timed", duration_minutes=60
    )
    try:
        resp1 = manager.request_approval("fam1", "things:write")
        assert resp1.approved
        assert len(notifier.received) == 1

        resp2 = manager.request_approval("fam1", "things:write")
        assert resp2.approved
        # Notifier not called again — the timed grant is cached.
        assert len(notifier.received) == 1
    finally:
        notifier.stop()


@pytest.mark.covers_function("Check Existing Grant")
def test_once_grant_does_not_cache(tmp_dir, encryption_key):
    manager, notifier = _make_manager(tmp_dir, encryption_key, approved=True, grant_type="once")
    try:
        manager.request_approval("fam1", "things:write")
        manager.request_approval("fam1", "things:write")
        # Notifier hit on both calls — ``once`` is not cached.
        assert len(notifier.received) == 2
    finally:
        notifier.stop()


@pytest.mark.covers_function("Request Approval")
def test_empty_url_client_fails_closed(tmp_dir, encryption_key):
    """An unconfigured ``ApprovalClient`` denies without hitting any URL."""
    store = TokenStore(os.path.join(tmp_dir, "tokens.db"), encryption_key)
    audit = AuditLogger(os.path.join(tmp_dir, "audit.log"))
    client = ApprovalClient(url="")
    manager = ApprovalManager(client, store, audit)
    resp = manager.request_approval("fam1", "things:write", "Complete todo")
    assert not resp.approved
    # Smoke: the client shouldn't even claim to be configured.
    assert client.configured is False
    # Sanity-check the sentinel imports are still available.
    _ = ApprovalResult(approved=False)
