# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the always-approve / always-deny integration-test plugins.

Verifies the loader honours the module names the integration fixture
writes into ``config.yaml`` and that each plugin hard-codes the
advertised decision regardless of the (scope, description, family_id)
triple.
"""

import pytest

from agent_auth.plugins import load_plugin
from tests_support.always_approve import AlwaysApprovePlugin
from tests_support.always_deny import AlwaysDenyPlugin


def test_always_approve_plugin_approves():
    result = AlwaysApprovePlugin().request_approval("things:read", None, "family")
    assert result.approved is True


def test_always_deny_plugin_denies():
    result = AlwaysDenyPlugin().request_approval("things:read", None, "family")
    assert result.approved is False


@pytest.mark.covers_function("Load Notification Plugin")
@pytest.mark.parametrize(
    "module,approved",
    [
        ("tests_support.always_approve", True),
        ("tests_support.always_deny", False),
    ],
)
def test_load_plugin_resolves_tests_support_modules(module, approved):
    plugin = load_plugin(module)
    assert plugin.request_approval("things:read", None, "family").approved is approved
