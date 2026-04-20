"""Notification plugin that denies every request.

Integration-test use only. Paired with ``always_approve`` so tests can
pick a deterministic plugin in ``config.yaml`` rather than threading an
env-var through the container.
"""

from agent_auth.plugins import ApprovalResult, NotificationPlugin


class AlwaysDenyPlugin(NotificationPlugin):
    """Deny every request unconditionally."""

    def request_approval(
        self,
        scope: str,
        description: str | None,
        family_id: str,
    ) -> ApprovalResult:
        return ApprovalResult(approved=False, grant_type="once")


Plugin = AlwaysDenyPlugin
