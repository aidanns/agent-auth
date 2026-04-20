# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Notification plugin that approves every request.

Integration-test use only. The production ``terminal`` plugin prompts
the user; the tests swap this in via ``notification_plugin`` in the
bind-mounted ``config.yaml`` when they need approvals to succeed.
"""

from agent_auth.plugins import ApprovalResult, NotificationPlugin


class AlwaysApprovePlugin(NotificationPlugin):
    """Approve every request unconditionally."""

    def request_approval(
        self,
        scope: str,
        description: str | None,
        family_id: str,
    ) -> ApprovalResult:
        return ApprovalResult(approved=True, grant_type="once")


Plugin = AlwaysApprovePlugin
