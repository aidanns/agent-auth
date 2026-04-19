"""Integration tests for the token management HTTP endpoints (create, list, modify, revoke, rotate)."""

import pytest

from tests._http import get, post


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_returns_valid_token_pair(agent_auth_container):
    status, body = post(
        agent_auth_container.url("token/create"),
        {"scopes": {"things:read": "allow"}},
    )
    assert status == 200
    assert body["family_id"]
    assert body["access_token"].startswith("aa_")
    assert body["refresh_token"].startswith("rt_")
    assert body["scopes"] == {"things:read": "allow"}


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_token_is_immediately_usable_for_validation(agent_auth_container):
    _, create_body = post(
        agent_auth_container.url("token/create"),
        {"scopes": {"things:read": "allow"}},
    )
    status, body = post(
        agent_auth_container.url("validate"),
        {"token": create_body["access_token"], "required_scope": "things:read"},
    )
    assert status == 200
    assert body["valid"] is True


@pytest.mark.covers_function("Serve Token Create Endpoint")
def test_token_create_rejects_empty_scopes(agent_auth_container):
    status, body = post(agent_auth_container.url("token/create"), {"scopes": {}})
    assert status == 400
    assert body["error"] == "no_scopes"


@pytest.mark.covers_function("Serve Token List Endpoint")
def test_token_list_includes_family_created_via_http(agent_auth_container):
    _, create_body = post(
        agent_auth_container.url("token/create"),
        {"scopes": {"things:read": "allow"}},
    )
    family_id = create_body["family_id"]

    status, body = get(agent_auth_container.url("token/list"))
    assert status == 200
    assert any(f["id"] == family_id for f in body)


@pytest.mark.covers_function("Serve Token List Endpoint")
def test_token_list_includes_family_created_via_cli(agent_auth_container):
    cli_result = agent_auth_container.create_token("things:write=allow")
    family_id = cli_result["family_id"]

    status, body = get(agent_auth_container.url("token/list"))
    assert status == 200
    assert any(f["id"] == family_id for f in body)


@pytest.mark.covers_function("Serve Token Modify Endpoint")
def test_token_modify_add_scope_is_reflected_in_validation(agent_auth_container):
    _, create_body = post(
        agent_auth_container.url("token/create"),
        {"scopes": {"things:read": "allow"}},
    )
    family_id = create_body["family_id"]

    post(
        agent_auth_container.url("token/modify"),
        {"family_id": family_id, "add_scopes": {"things:write": "allow"}},
    )

    # Refresh to get new access token reflecting updated scopes
    _, refresh_body = post(
        agent_auth_container.url("token/refresh"),
        {"refresh_token": create_body["refresh_token"]},
    )
    status, body = post(
        agent_auth_container.url("validate"),
        {"token": refresh_body["access_token"], "required_scope": "things:write"},
    )
    assert status == 200
    assert body["valid"] is True


@pytest.mark.covers_function("Serve Token Revoke Endpoint")
def test_token_revoke_makes_access_token_invalid(agent_auth_container):
    _, create_body = post(
        agent_auth_container.url("token/create"),
        {"scopes": {"things:read": "allow"}},
    )
    family_id = create_body["family_id"]
    access_token = create_body["access_token"]

    status, body = post(agent_auth_container.url("token/revoke"), {"family_id": family_id})
    assert status == 200
    assert body["revoked"] is True

    status, body = post(
        agent_auth_container.url("validate"),
        {"token": access_token, "required_scope": "things:read"},
    )
    assert status == 401
    assert body["valid"] is False


@pytest.mark.covers_function("Serve Token Revoke Endpoint")
def test_token_revoke_returns_404_for_unknown_family(agent_auth_container):
    status, body = post(agent_auth_container.url("token/revoke"), {"family_id": "no-such"})
    assert status == 404
    assert body["error"] == "family_not_found"


@pytest.mark.covers_function("Serve Token Rotate Endpoint")
def test_token_rotate_old_token_is_invalid_new_token_is_valid(agent_auth_container):
    _, create_body = post(
        agent_auth_container.url("token/create"),
        {"scopes": {"things:read": "allow"}},
    )
    old_access_token = create_body["access_token"]

    _, rotate_body = post(
        agent_auth_container.url("token/rotate"),
        {"family_id": create_body["family_id"]},
    )
    new_access_token = rotate_body["access_token"]

    old_status, old_body = post(
        agent_auth_container.url("validate"),
        {"token": old_access_token, "required_scope": "things:read"},
    )
    assert old_status == 401
    assert old_body["valid"] is False

    new_status, new_body = post(
        agent_auth_container.url("validate"),
        {"token": new_access_token, "required_scope": "things:read"},
    )
    assert new_status == 200
    assert new_body["valid"] is True


@pytest.mark.covers_function("Serve Token Rotate Endpoint")
def test_token_rotate_preserves_scopes(agent_auth_container):
    _, create_body = post(
        agent_auth_container.url("token/create"),
        {"scopes": {"things:read": "allow", "things:write": "prompt"}},
    )
    _, rotate_body = post(
        agent_auth_container.url("token/rotate"),
        {"family_id": create_body["family_id"]},
    )
    assert rotate_body["scopes"] == {"things:read": "allow", "things:write": "prompt"}


@pytest.mark.covers_function("Serve Token Rotate Endpoint")
def test_token_rotate_returns_409_for_revoked_family(agent_auth_container):
    _, create_body = post(
        agent_auth_container.url("token/create"),
        {"scopes": {"things:read": "allow"}},
    )
    family_id = create_body["family_id"]
    post(agent_auth_container.url("token/revoke"), {"family_id": family_id})

    status, body = post(agent_auth_container.url("token/rotate"), {"family_id": family_id})
    assert status == 409
    assert body["error"] == "family_revoked"
