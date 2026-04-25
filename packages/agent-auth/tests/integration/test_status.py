# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration tests for the /agent-auth/v1/token/status endpoint."""

import pytest

from agent_auth_client import AuthzTokenInvalidError


@pytest.mark.covers_function("Serve Status Endpoint", "Introspect Token")
def test_status_returns_metadata_for_a_valid_access_token(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    status = agent_auth_container.client().get_status(tokens["access_token"])
    assert status.token_type == "access"
    assert status.scopes == {"things:read": "allow"}
    assert status.family_id == tokens["family_id"]
    assert status.expires_in_seconds > 0


@pytest.mark.covers_function("Serve Status Endpoint")
def test_status_requires_a_bearer_token(agent_auth_container):
    with pytest.raises(AuthzTokenInvalidError, match="missing_token"):
        agent_auth_container.client().get_status(None)
