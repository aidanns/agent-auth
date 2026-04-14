"""JIT approval manager with in-memory timed grants."""

import threading
from datetime import datetime, timedelta, timezone

from agent_auth.audit import AuditLogger
from agent_auth.plugins import ApprovalResult, NotificationPlugin
from agent_auth.store import TokenStore


class ApprovalManager:
    """Manages JIT approval requests and in-memory timed grants."""

    def __init__(
        self,
        plugin: NotificationPlugin,
        store: TokenStore,
        audit: AuditLogger,
    ):
        self._plugin = plugin
        self._store = store
        self._audit = audit
        self._grants: dict[tuple[str, str], datetime] = {}
        self._lock = threading.Lock()

    def check_grant(self, family_id: str, scope: str) -> bool:
        """Check if an active grant covers this scope."""
        with self._lock:
            self._expire_grants()
            key = (family_id, scope)
            return key in self._grants

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
            self._record_grant(family_id, scope, result)
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

    def _record_grant(self, family_id: str, scope: str, result: ApprovalResult):
        """Record an approval grant."""
        if result.grant_type != "timed" or not result.duration_minutes:
            return

        with self._lock:
            expires = datetime.now(timezone.utc) + timedelta(minutes=result.duration_minutes)
            self._grants[(family_id, scope)] = expires

    def _expire_grants(self):
        """Remove expired grants. Must be called with lock held."""
        now = datetime.now(timezone.utc)
        expired = [key for key, exp in self._grants.items() if exp <= now]
        for key in expired:
            del self._grants[key]
