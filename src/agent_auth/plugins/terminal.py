"""Terminal-based notification plugin for JIT approval.

Prompts the user on the server's stdin/stdout for approval decisions.
"""

import sys

from agent_auth.plugins import ApprovalResult, NotificationPlugin


class Plugin(NotificationPlugin):
    """Prompts for approval on the terminal."""

    def request_approval(
        self,
        scope: str,
        description: str | None,
        family_id: str,
    ) -> ApprovalResult:
        print(f"\n{'=' * 60}", file=sys.stderr)
        print("JIT APPROVAL REQUEST", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)
        print(f"  Scope:     {scope}", file=sys.stderr)
        if description:
            print(f"  Operation: {description}", file=sys.stderr)
        print(f"  Family:    {family_id}", file=sys.stderr)
        print(file=sys.stderr)
        print("Grant options:", file=sys.stderr)
        print("  [y] Approve once", file=sys.stderr)
        print("  [s] Approve for this session (60 minutes)", file=sys.stderr)
        print("  [t] Approve for N minutes", file=sys.stderr)
        print("  [n] Deny", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)

        try:
            choice = input("Choice [y/s/t/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ApprovalResult(approved=False)

        if choice == "y":
            return ApprovalResult(approved=True, grant_type="once")
        elif choice == "s":
            return ApprovalResult(approved=True, grant_type="timed", duration_minutes=60)
        elif choice == "t":
            try:
                minutes = int(input("Minutes: ").strip())
            except (EOFError, KeyboardInterrupt, ValueError):
                return ApprovalResult(approved=False)
            return ApprovalResult(approved=True, grant_type="timed", duration_minutes=minutes)
        else:
            return ApprovalResult(approved=False)
