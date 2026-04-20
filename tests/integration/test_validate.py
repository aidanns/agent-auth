# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration tests for the /agent-auth/validate endpoint."""

import pytest

from tests._http import post


@pytest.mark.covers_function("Serve Validate Endpoint", "Check Token Expiry")
def test_validate_allows_scope_at_allow_tier(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    status, body = post(
        agent_auth_container.url("validate"),
        {"token": tokens["access_token"], "required_scope": "things:read"},
    )
    assert status == 200
    assert body["valid"] is True


@pytest.mark.covers_function("Serve Validate Endpoint")
def test_validate_rejects_garbage_token(agent_auth_container):
    status, body = post(
        agent_auth_container.url("validate"),
        {"token": "aa_fake_bad", "required_scope": "things:read"},
    )
    assert status == 401
    assert body["valid"] is False


@pytest.mark.covers_function("Serve Validate Endpoint")
def test_validate_denies_scope_not_granted(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    status, body = post(
        agent_auth_container.url("validate"),
        {"token": tokens["access_token"], "required_scope": "things:write"},
    )
    assert status == 403
    assert body["error"] == "scope_denied"


@pytest.mark.covers_function("Serve Validate Endpoint", "Request Approval")
def test_validate_prompt_tier_succeeds_when_plugin_approves(
    agent_auth_container_factory,
):
    container = agent_auth_container_factory(approval="approve")
    tokens = container.create_token("things:write=prompt")
    status, body = post(
        container.url("validate"),
        {
            "token": tokens["access_token"],
            "required_scope": "things:write",
            "description": "Complete todo: Buy milk",
        },
    )
    assert status == 200
    assert body["valid"] is True


@pytest.mark.covers_function("Serve Validate Endpoint", "Request Approval")
def test_validate_prompt_tier_denied_when_plugin_denies(
    agent_auth_container_factory,
):
    container = agent_auth_container_factory(approval="deny")
    tokens = container.create_token("things:write=prompt")
    status, body = post(
        container.url("validate"),
        {"token": tokens["access_token"], "required_scope": "things:write"},
    )
    assert status == 403
    assert body["error"] == "scope_denied"
