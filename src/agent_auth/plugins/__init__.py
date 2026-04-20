# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Notification plugin system for JIT approval."""

import importlib
from dataclasses import dataclass


@dataclass
class ApprovalResult:
    """Result of a JIT approval request.

    grant_type is either "once" (no caching) or "timed" (cached for
    duration_minutes). Plugins surfacing a "for this session" choice
    should return grant_type="timed" with duration_minutes=60.
    """

    approved: bool
    grant_type: str = "once"
    duration_minutes: int | None = None


class NotificationPlugin:
    """Base class for approval notification plugins."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def request_approval(
        self,
        scope: str,
        description: str | None,
        family_id: str,
    ) -> ApprovalResult:
        """Block until the user approves or denies the request."""
        raise NotImplementedError


def load_plugin(name: str, config: dict | None = None) -> NotificationPlugin:
    """Load a notification plugin by name.

    Looks for the plugin in agent_auth.plugins.<name> or as a fully-qualified module path.
    The module must define a 'Plugin' class that inherits from NotificationPlugin.
    """
    module_path = f"agent_auth.plugins.{name}" if "." not in name else name

    module = importlib.import_module(module_path)
    plugin_class = module.Plugin
    return plugin_class(config)
