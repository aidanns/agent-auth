"""Integration tests for the /agent-auth/v1/token/reissue endpoint.

These tests exercise the expired-refresh-token branch by running the
container with a very short ``refresh_token_ttl_seconds`` and sleeping
past the expiry. Nothing reaches into the SQLite token store directly.
"""

import time

import pytest

from tests._http import post

REFRESH_TTL_SECONDS = 1
EXPIRY_SLEEP_SECONDS = REFRESH_TTL_SECONDS + 1


@pytest.mark.covers_function("Serve Reissue Endpoint", "Request Approval")
def test_reissue_succeeds_after_refresh_expiry_when_plugin_approves(
    agent_auth_container_factory,
):
    container = agent_auth_container_factory(
        approval="approve", refresh_token_ttl_seconds=REFRESH_TTL_SECONDS
    )
    tokens = container.create_token("things:read=allow")
    time.sleep(EXPIRY_SLEEP_SECONDS)

    status, body = post(
        container.url("token/reissue"),
        {"family_id": tokens["family_id"]},
    )
    assert status == 200
    assert "access_token" in body
    assert "refresh_token" in body


@pytest.mark.covers_function("Serve Reissue Endpoint", "Request Approval")
def test_reissue_denied_when_plugin_denies(agent_auth_container_factory):
    container = agent_auth_container_factory(
        approval="deny", refresh_token_ttl_seconds=REFRESH_TTL_SECONDS
    )
    tokens = container.create_token("things:read=allow")
    time.sleep(EXPIRY_SLEEP_SECONDS)

    status, body = post(
        container.url("token/reissue"),
        {"family_id": tokens["family_id"]},
    )
    assert status == 403
    assert body["error"] == "reissue_denied"


@pytest.mark.covers_function("Serve Reissue Endpoint", "Revoke Token Family")
def test_reissue_rejects_revoked_family(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    agent_auth_container.exec_cli("token", "revoke", tokens["family_id"])

    status, body = post(
        agent_auth_container.url("token/reissue"),
        {"family_id": tokens["family_id"]},
    )
    assert status == 401
    assert body["error"] == "family_revoked"
