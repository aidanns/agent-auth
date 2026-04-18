"""Env-driven notification plugin for integration tests.

Reads ``AGENT_AUTH_TEST_APPROVAL`` at call time and returns an approve /
deny ``ApprovalResult`` accordingly. Defaults to deny so a misconfigured
container fails closed.
"""

import os

from agent_auth.plugins import ApprovalResult, NotificationPlugin


ENV_VAR = "AGENT_AUTH_TEST_APPROVAL"


class EnvPlugin(NotificationPlugin):
    """Return approve / deny based on the ``AGENT_AUTH_TEST_APPROVAL`` env var."""

    def request_approval(
        self,
        scope: str,
        description: str | None,
        family_id: str,
    ) -> ApprovalResult:
        decision = os.environ.get(ENV_VAR, "deny").strip().lower()
        return ApprovalResult(approved=decision == "approve", grant_type="once")


Plugin = EnvPlugin
