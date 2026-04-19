"""Integration tests for the /agent-auth/token/status endpoint."""

import pytest

from tests._http import get


@pytest.mark.covers_function("Serve Status Endpoint", "Introspect Token")
def test_status_returns_metadata_for_a_valid_access_token(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    status, body = get(
        agent_auth_container.url("token/status"),
        {"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert status == 200
    assert body["type"] == "access"
    assert body["scopes"] == {"things:read": "allow"}
    assert body["family_id"] == tokens["family_id"]
    assert "expires_in" in body


@pytest.mark.covers_function("Serve Status Endpoint")
def test_status_requires_a_bearer_token(agent_auth_container):
    status, body = get(agent_auth_container.url("token/status"))
    assert status == 401
    assert body["error"] == "missing_token"
