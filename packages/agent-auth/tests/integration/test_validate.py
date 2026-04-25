# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration tests for the /agent-auth/v1/validate endpoint."""

import pytest

from agent_auth_client import AuthzScopeDeniedError, AuthzTokenInvalidError


@pytest.mark.covers_function("Serve Validate Endpoint", "Check Token Expiry")
def test_validate_allows_scope_at_allow_tier(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    # No exception == validate() returned normally; there is no other
    # success signal to assert on.
    agent_auth_container.client().validate(tokens["access_token"], "things:read")


@pytest.mark.covers_function("Serve Validate Endpoint")
def test_validate_rejects_garbage_token(agent_auth_container):
    with pytest.raises(AuthzTokenInvalidError):
        agent_auth_container.client().validate("aa_fake_bad", "things:read")


@pytest.mark.covers_function("Serve Validate Endpoint")
def test_validate_denies_scope_not_granted(agent_auth_container):
    tokens = agent_auth_container.create_token("things:read=allow")
    with pytest.raises(AuthzScopeDeniedError, match="scope_denied"):
        agent_auth_container.client().validate(tokens["access_token"], "things:write")


@pytest.mark.covers_function("Serve Validate Endpoint", "Request Approval")
def test_validate_prompt_tier_succeeds_when_plugin_approves(
    agent_auth_container_factory,
):
    container = agent_auth_container_factory(approval="approve")
    tokens = container.create_token("things:write=prompt")
    container.client().validate(
        tokens["access_token"],
        "things:write",
        description="Complete todo: Buy milk",
    )


@pytest.mark.covers_function("Serve Validate Endpoint", "Request Approval")
def test_validate_prompt_tier_denied_when_plugin_denies(
    agent_auth_container_factory,
):
    container = agent_auth_container_factory(approval="deny")
    tokens = container.create_token("things:write=prompt")
    with pytest.raises(AuthzScopeDeniedError, match="scope_denied"):
        container.client().validate(tokens["access_token"], "things:write")
