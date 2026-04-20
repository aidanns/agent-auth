# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration tests for the /agent-auth/token/refresh endpoint."""

import pytest

from tests._http import post


@pytest.mark.covers_function("Serve Refresh Endpoint", "Refresh Token Pair")
def test_refresh_exchanges_refresh_token_for_a_new_pair(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    status, body = post(
        agent_auth_container.url("token/refresh"),
        {"refresh_token": tokens["refresh_token"]},
    )
    assert status == 200
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["access_token"] != tokens["access_token"]
    assert body["refresh_token"] != tokens["refresh_token"]
    assert body["expires_in"] == 900


@pytest.mark.covers_function(
    "Serve Refresh Endpoint", "Detect Refresh Token Reuse", "Revoke Token Family"
)
def test_reusing_a_consumed_refresh_token_revokes_the_family(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")

    first_status, _ = post(
        agent_auth_container.url("token/refresh"),
        {"refresh_token": tokens["refresh_token"]},
    )
    assert first_status == 200

    second_status, second_body = post(
        agent_auth_container.url("token/refresh"),
        {"refresh_token": tokens["refresh_token"]},
    )
    assert second_status == 401
    assert second_body["error"] == "refresh_token_reuse_detected"

    family = agent_auth_container.get_family(tokens["family_id"])
    assert family is not None
    assert family["revoked"] is True
