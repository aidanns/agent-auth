# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration tests for the /agent-auth/v1/token/reissue endpoint.

These tests exercise the expired-refresh-token branch by running the
container with a very short ``refresh_token_ttl_seconds`` and sleeping
past the expiry. Nothing reaches into the SQLite token store directly.
"""

import time

import pytest

from agent_auth_client import FamilyRevokedError, ReissueDeniedError

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

    reissued = container.client().reissue(tokens["family_id"])
    assert reissued.access_token
    assert reissued.refresh_token


@pytest.mark.covers_function("Serve Reissue Endpoint", "Request Approval")
def test_reissue_denied_when_plugin_denies(agent_auth_container_factory):
    container = agent_auth_container_factory(
        approval="deny", refresh_token_ttl_seconds=REFRESH_TTL_SECONDS
    )
    tokens = container.create_token("things:read=allow")
    time.sleep(EXPIRY_SLEEP_SECONDS)

    with pytest.raises(ReissueDeniedError, match="reissue_denied"):
        container.client().reissue(tokens["family_id"])


@pytest.mark.covers_function("Serve Reissue Endpoint", "Revoke Token Family")
def test_reissue_rejects_revoked_family(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    agent_auth_container.exec_cli("token", "revoke", tokens["family_id"])

    with pytest.raises(FamilyRevokedError, match="family_revoked"):
        agent_auth_container.client().reissue(tokens["family_id"])
