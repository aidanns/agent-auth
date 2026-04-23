# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration tests for the /agent-auth/health endpoint."""

import pytest

from agent_auth_client import AuthzScopeDeniedError, AuthzTokenInvalidError


@pytest.mark.covers_function("Serve Health Endpoint")
def test_health_endpoint_reports_ok_when_called_with_the_health_scope(agent_auth_container):
    tokens = agent_auth_container.create_token("agent-auth:health=allow")
    body = agent_auth_container.client().check_health(tokens["access_token"])
    assert body == {"status": "ok"}


@pytest.mark.covers_function("Serve Health Endpoint")
def test_health_endpoint_rejects_unauthenticated_callers(agent_auth_container):
    with pytest.raises(AuthzTokenInvalidError, match="missing_token"):
        agent_auth_container.client().check_health(None)


@pytest.mark.covers_function("Serve Health Endpoint")
def test_health_endpoint_rejects_tokens_missing_the_health_scope(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    with pytest.raises(AuthzScopeDeniedError, match="scope_denied"):
        agent_auth_container.client().check_health(tokens["access_token"])
