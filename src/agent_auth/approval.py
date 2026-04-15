"""JIT approval manager with in-memory timed grants."""

import threading
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from agent_auth.audit import AuditLogger
from agent_auth.plugins import ApprovalResult, NotificationPlugin
from agent_auth.store import TokenStore


class GrantKey(NamedTuple):
    """Identifies a cached approval grant by (family, scope)."""

    family_id: str
    scope: str


class ApprovalManager:
    """Manages JIT approval requests and in-memory timed grants.

    Grants are "timed" only: an approval that covers subsequent requests
    for the same (family_id, scope) until its expiry. "Once" approvals
    are not cached — the plugin is called again on the next request. The
    design defines no permanent grant.
    """

    def __init__(
        self,
        plugin: NotificationPlugin,
        store: TokenStore,
        audit: AuditLogger,
    ):
        self._plugin = plugin
        self._store = store
        self._audit = audit
        # Maps (family_id, scope) → absolute expiry. Accessed from handler
        # threads in the ThreadingHTTPServer, so all reads/writes must be
        # serialised with _lock.
        self._grants: dict[GrantKey, datetime] = {}
        self._lock = threading.Lock()

    def check_grant(self, family_id: str, scope: str) -> bool:
        """Return True iff a non-expired timed grant covers this scope."""
        with self._lock:
            self._expire_grants()
            return GrantKey(family_id, scope) in self._grants

    def request_approval(
        self,
        family_id: str,
        scope: str,
        description: str | None = None,
    ) -> ApprovalResult:
        """Request approval from the user via the notification plugin."""
        if self.check_grant(family_id, scope):
            return ApprovalResult(approved=True, grant_type="timed")

        result = self._plugin.request_approval(scope, description, family_id)

        if result.approved:
            if result.grant_type == "timed":
                self._record_timed_grant(family_id, scope, result)
            self._audit.log_authorization_decision(
                "approval_granted",
                family_id=family_id,
                scope=scope,
                grant_type=result.grant_type,
                duration_minutes=result.duration_minutes,
            )
        else:
            self._audit.log_authorization_decision(
                "approval_denied",
                family_id=family_id,
                scope=scope,
            )

        return result

    def _record_timed_grant(self, family_id: str, scope: str, result: ApprovalResult):
        """Cache a timed grant until its duration elapses."""
        if not result.duration_minutes:
            return
        with self._lock:
            expires = datetime.now(timezone.utc) + timedelta(minutes=result.duration_minutes)
            self._grants[GrantKey(family_id, scope)] = expires

    def _expire_grants(self):
        """Remove expired grants. Must be called with lock held."""
        now = datetime.now(timezone.utc)
        expired = [key for key, exp in self._grants.items() if exp <= now]
        for key in expired:
            del self._grants[key]
