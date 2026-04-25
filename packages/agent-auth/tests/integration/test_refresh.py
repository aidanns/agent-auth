# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration tests for the /agent-auth/v1/token/refresh endpoint."""

import pytest

from agent_auth_client import RefreshTokenReuseDetectedError


@pytest.mark.covers_function("Serve Refresh Endpoint", "Refresh Token Pair")
def test_refresh_exchanges_refresh_token_for_a_new_pair(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    refreshed = agent_auth_container.client().refresh(tokens["refresh_token"])
    assert refreshed.access_token
    assert refreshed.refresh_token
    assert refreshed.access_token != tokens["access_token"]
    assert refreshed.refresh_token != tokens["refresh_token"]
    assert refreshed.expires_in_seconds == 900


@pytest.mark.covers_function(
    "Serve Refresh Endpoint", "Detect Refresh Token Reuse", "Revoke Token Family"
)
def test_reusing_a_consumed_refresh_token_revokes_the_family(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")

    agent_auth_container.client().refresh(tokens["refresh_token"])

    with pytest.raises(RefreshTokenReuseDetectedError):
        agent_auth_container.client().refresh(tokens["refresh_token"])

    family = agent_auth_container.get_family(tokens["family_id"])
    assert family is not None
    assert family["revoked"] is True
