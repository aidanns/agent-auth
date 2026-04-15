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

    Only prompt-tier scopes reach this manager. Allow-tier scopes are
    effectively permanent grants configured at token creation and are
    short-circuited by the server before any approval step; deny-tier
    scopes are rejected up-front the same way.

    For the prompt-tier scopes that *do* reach this manager, the design
    defines two grant shapes returned by notification plugins:

    - ``once`` — approval applies to this request only and is not cached
    - ``timed`` — approval covers subsequent requests for the same
      (family_id, scope) until its duration elapses

    There is no runtime-issued "permanent" grant — durable allowance
    belongs in the token's scope configuration as ``allow``, not here.
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
        # Maps (family_id, scope) → absolute expiry for timed grants.
        # Accessed from handler threads in the ThreadingHTTPServer, so all
        # reads/writes must be serialised with _lock.
        self._timed_grants: dict[GrantKey, datetime] = {}
        self._lock = threading.Lock()

    def check_timed_grant(self, family_id: str, scope: str) -> bool:
        """Return True iff a non-expired timed grant covers this scope."""
        with self._lock:
            self._expire_timed_grants()
            return GrantKey(family_id, scope) in self._timed_grants

    def request_approval(
        self,
        family_id: str,
        scope: str,
        description: str | None = None,
    ) -> ApprovalResult:
        """Request approval from the user via the notification plugin."""
        if self.check_timed_grant(family_id, scope):
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
            self._timed_grants[GrantKey(family_id, scope)] = expires

    def _expire_timed_grants(self):
        """Remove expired timed grants. Must be called with lock held."""
        now = datetime.now(timezone.utc)
        expired = [key for key, exp in self._timed_grants.items() if exp <= now]
        for key in expired:
            del self._timed_grants[key]
