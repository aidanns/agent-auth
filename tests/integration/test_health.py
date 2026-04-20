# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration tests for the /agent-auth/health endpoint."""

import pytest

from tests._http import get


@pytest.mark.covers_function("Serve Health Endpoint")
def test_health_endpoint_reports_ok_when_called_with_the_health_scope(agent_auth_container):
    tokens = agent_auth_container.create_token("agent-auth:health=allow")
    status, body = get(
        agent_auth_container.url("health"),
        {"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert status == 200
    assert body == {"status": "ok"}


@pytest.mark.covers_function("Serve Health Endpoint")
def test_health_endpoint_rejects_unauthenticated_callers(agent_auth_container):
    status, body = get(agent_auth_container.url("health"))
    assert status == 401
    assert body["error"] == "missing_token"


@pytest.mark.covers_function("Serve Health Endpoint")
def test_health_endpoint_rejects_tokens_missing_the_health_scope(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    status, body = get(
        agent_auth_container.url("health"),
        {"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert status == 403
    assert body["error"] == "scope_denied"
