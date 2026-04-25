# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Integration tests for the token management HTTP endpoints."""

import pytest

from agent_auth_client import (
    AuthzTokenInvalidError,
    FamilyNotFoundError,
    FamilyRevokedError,
    MalformedRequestError,
)


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_requires_management_auth(agent_auth_container):
    with pytest.raises(AuthzTokenInvalidError, match="missing_token"):
        agent_auth_container.client().create_token({"things:read": "allow"}, management_token=None)


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_returns_valid_token_pair(agent_auth_container):
    pair = agent_auth_container.client().create_token(
        {"things:read": "allow"},
        management_token=agent_auth_container.management_token(),
    )
    assert pair.family_id
    assert pair.access_token.startswith("aa_")
    assert pair.refresh_token.startswith("rt_")
    assert pair.scopes == {"things:read": "allow"}


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_token_is_immediately_usable_for_validation(agent_auth_container):
    pair = agent_auth_container.client().create_token(
        {"things:read": "allow"},
        management_token=agent_auth_container.management_token(),
    )
    # validate() returns None on success; the absence of an exception
    # is the assertion.
    agent_auth_container.client().validate(pair.access_token, "things:read")


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_rejects_empty_scopes(agent_auth_container):
    with pytest.raises(MalformedRequestError, match="no_scopes"):
        agent_auth_container.client().create_token(
            {}, management_token=agent_auth_container.management_token()
        )


@pytest.mark.covers_function("Serve Token List Endpoint")
def test_token_list_requires_management_auth(agent_auth_container):
    with pytest.raises(AuthzTokenInvalidError, match="missing_token"):
        agent_auth_container.client().list_tokens(management_token=None)


@pytest.mark.covers_function("Serve Token List Endpoint")
def test_token_list_includes_family_created_via_http(agent_auth_container):
    mgmt = agent_auth_container.management_token()
    pair = agent_auth_container.client().create_token(
        {"things:read": "allow"}, management_token=mgmt
    )
    families = agent_auth_container.client().list_tokens(management_token=mgmt)
    assert any(f.id == pair.family_id for f in families)


@pytest.mark.covers_function("Serve Token List Endpoint")
def test_token_list_includes_family_created_via_cli(agent_auth_container):
    cli_result = agent_auth_container.create_token("things:write=allow")
    mgmt = agent_auth_container.management_token()
    families = agent_auth_container.client().list_tokens(management_token=mgmt)
    assert any(f.id == cli_result["family_id"] for f in families)


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_add_scope_is_reflected_in_validation(agent_auth_container):
    client = agent_auth_container.client()
    mgmt = agent_auth_container.management_token()
    pair = client.create_token({"things:read": "allow"}, management_token=mgmt)

    client.modify_token(
        pair.family_id,
        management_token=mgmt,
        add_scopes={"things:write": "allow"},
    )

    # Refresh to get a new access token reflecting updated scopes.
    refreshed = client.refresh(pair.refresh_token)
    client.validate(refreshed.access_token, "things:write")


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_returns_404_for_unknown_family(agent_auth_container):
    with pytest.raises(FamilyNotFoundError, match="family_not_found"):
        agent_auth_container.client().modify_token(
            "no-such-family",
            management_token=agent_auth_container.management_token(),
            add_scopes={"x": "allow"},
        )


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_returns_409_for_revoked_family(agent_auth_container):
    client = agent_auth_container.client()
    mgmt = agent_auth_container.management_token()
    pair = client.create_token({"things:read": "allow"}, management_token=mgmt)
    client.revoke_token(pair.family_id, management_token=mgmt)

    with pytest.raises(FamilyRevokedError, match="family_revoked"):
        client.modify_token(
            pair.family_id,
            management_token=mgmt,
            add_scopes={"things:write": "allow"},
        )


@pytest.mark.covers_function("Serve Token Revoke Endpoint")
def test_token_revoke_makes_access_token_invalid(agent_auth_container):
    client = agent_auth_container.client()
    mgmt = agent_auth_container.management_token()
    pair = client.create_token({"things:read": "allow"}, management_token=mgmt)

    result = client.revoke_token(pair.family_id, management_token=mgmt)
    assert result["revoked"] is True

    with pytest.raises(AuthzTokenInvalidError, match="token_revoked"):
        client.validate(pair.access_token, "things:read")


@pytest.mark.covers_function("Serve Token Revoke Endpoint")
def test_token_revoke_returns_404_for_unknown_family(agent_auth_container):
    with pytest.raises(FamilyNotFoundError, match="family_not_found"):
        agent_auth_container.client().revoke_token(
            "no-such", management_token=agent_auth_container.management_token()
        )


@pytest.mark.covers_function("Serve Token Rotate Endpoint")
def test_token_rotate_old_token_is_invalid_new_token_is_valid(agent_auth_container):
    client = agent_auth_container.client()
    mgmt = agent_auth_container.management_token()
    pair = client.create_token({"things:read": "allow"}, management_token=mgmt)

    rotated = client.rotate_token(pair.family_id, management_token=mgmt)

    with pytest.raises(AuthzTokenInvalidError):
        client.validate(pair.access_token, "things:read")

    client.validate(rotated.access_token, "things:read")


@pytest.mark.covers_function("Serve Token Rotate Endpoint")
def test_token_rotate_preserves_scopes(agent_auth_container):
    client = agent_auth_container.client()
    mgmt = agent_auth_container.management_token()
    pair = client.create_token(
        {"things:read": "allow", "things:write": "prompt"}, management_token=mgmt
    )
    rotated = client.rotate_token(pair.family_id, management_token=mgmt)
    assert rotated.scopes == {"things:read": "allow", "things:write": "prompt"}


@pytest.mark.covers_function("Serve Token Rotate Endpoint")
def test_token_rotate_returns_409_for_revoked_family(agent_auth_container):
    client = agent_auth_container.client()
    mgmt = agent_auth_container.management_token()
    pair = client.create_token({"things:read": "allow"}, management_token=mgmt)
    client.revoke_token(pair.family_id, management_token=mgmt)

    with pytest.raises(FamilyRevokedError, match="family_revoked"):
        client.rotate_token(pair.family_id, management_token=mgmt)
