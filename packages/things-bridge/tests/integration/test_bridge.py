# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""End-to-end Docker integration tests for things-bridge.

Drives the full read path through real HTTP: a client sends a request
with an agent-auth-issued bearer token to the containerised
``things-bridge``, which delegates to the in-network ``agent-auth``
service for token validation and shells out to the in-tree fake
things-client subprocess for the Things response.

This suite replaces the in-process ``tests/test_things_bridge_e2e.py``;
it relies on the ``things_bridge_stack`` fixture (see ``conftest.py``)
to manage the multi-service Compose project.

HTTP is driven through :class:`things_bridge_client.ThingsBridgeClient`
so the same code path ships to real callers. Raw ``urllib`` is no
longer used here.
"""

from __future__ import annotations

import time

import pytest

from things_bridge_client import (
    ThingsBridgeForbiddenError,
    ThingsBridgeNotFoundError,
    ThingsBridgeTokenExpiredError,
    ThingsBridgeUnauthorizedError,
    ThingsBridgeUnavailableError,
)

_SEEDED_FIXTURE = {
    "areas": [
        {"id": "a1", "name": "Personal", "tag_names": []},
        {"id": "a2", "name": "Work", "tag_names": []},
    ],
    "projects": [
        {"id": "p1", "name": "Q2 Planning", "area_id": "a2", "area_name": "Work"},
        {"id": "p2", "name": "Home", "area_id": "a1", "area_name": "Personal"},
    ],
    "todos": [
        {
            "id": "t1",
            "name": "Buy milk",
            "area_id": "a1",
            "area_name": "Personal",
            "tag_names": ["Errand"],
        },
        {
            "id": "t2",
            "name": "Write report",
            "notes": "Include:\n\t- milestones\n\t- owners",
            "project_id": "p1",
            "project_name": "Q2 Planning",
            "area_id": "a2",
            "area_name": "Work",
            "tag_names": ["planning", "deep-work"],
        },
        {
            "id": "t3",
            "name": "Fix tap",
            "status": "completed",
            "area_id": "a1",
            "area_name": "Personal",
        },
        {
            "id": "t4",
            "name": "Dentist",
            "area_id": "a1",
            "area_name": "Personal",
            "tag_names": ["Errand"],
        },
    ],
    "list_memberships": {"TMTodayListSource": ["t1", "t2"]},
}


@pytest.fixture
def stack(things_bridge_stack):
    """Pre-seed the bridge fixture and mint a ``things:read`` token."""
    things_bridge_stack.write_fixture(_SEEDED_FIXTURE)
    token_payload = things_bridge_stack.agent_auth.create_token("things:read=allow")
    return {
        "stack": things_bridge_stack,
        "token": token_payload["access_token"],
        "family_id": token_payload["family_id"],
    }


@pytest.mark.covers_function("Delegate Token Validation", "Serve Bridge HTTP API")
def test_list_todos_end_to_end(stack):
    data = stack["stack"].client().list_todos(stack["token"])
    assert {t["id"] for t in data["todos"]} == {"t1", "t2", "t3", "t4"}


@pytest.mark.covers_function("Delegate Token Validation")
def test_list_todos_missing_token_returns_401(stack):
    with pytest.raises(ThingsBridgeUnauthorizedError, match="unauthorized"):
        stack["stack"].client().list_todos(None)


@pytest.mark.covers_function("Delegate Token Validation", "Check Scope Authorization")
def test_list_todos_wrong_scope_returns_403(things_bridge_stack):
    things_bridge_stack.write_fixture(_SEEDED_FIXTURE)
    payload = things_bridge_stack.agent_auth.create_token("outlook:mail:read=allow")
    with pytest.raises(ThingsBridgeForbiddenError, match="scope_denied"):
        things_bridge_stack.client().list_todos(payload["access_token"])


@pytest.mark.covers_function("Delegate Token Validation")
def test_list_todos_revoked_family_returns_401(stack):
    stack["stack"].agent_auth.exec_cli("token", "revoke", stack["family_id"])
    with pytest.raises(ThingsBridgeUnauthorizedError, match="unauthorized"):
        stack["stack"].client().list_todos(stack["token"])


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_list_todos_filters_forwarded_through_fake(stack):
    data = stack["stack"].client().list_todos(stack["token"], params={"project": "p1"})
    assert [t["id"] for t in data["todos"]] == ["t2"]


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_list_todos_list_filter_resolves_via_memberships(stack):
    data = stack["stack"].client().list_todos(stack["token"], params={"list": "TMTodayListSource"})
    assert {t["id"] for t in data["todos"]} == {"t1", "t2"}


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_list_todos_tag_filter(stack):
    data = stack["stack"].client().list_todos(stack["token"], params={"tag": "Errand"})
    assert {t["id"] for t in data["todos"]} == {"t1", "t4"}


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_list_todos_status_filter(stack):
    data = stack["stack"].client().list_todos(stack["token"], params={"status": "completed"})
    assert [t["id"] for t in data["todos"]] == ["t3"]


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_get_todo_by_id_roundtrips_freeform_notes(stack):
    # Notes on t2 contain \n and \t; confirm they survive the JSON
    # round-trip so CLI clients can rely on free-form text being preserved.
    data = stack["stack"].client().get_todo(stack["token"], "t2")
    assert data["todo"]["id"] == "t2"
    assert "\t" in data["todo"]["notes"]
    assert "\n" in data["todo"]["notes"]


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_get_unknown_todo_returns_404(stack):
    with pytest.raises(ThingsBridgeNotFoundError, match="not_found"):
        stack["stack"].client().get_todo(stack["token"], "does-not-exist")


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_projects_and_areas(stack):
    client = stack["stack"].client()
    token = stack["token"]

    projects = client.list_projects(token)
    assert {p["id"] for p in projects["projects"]} == {"p1", "p2"}

    filtered = client.list_projects(token, params={"area": "a1"})
    assert [p["id"] for p in filtered["projects"]] == ["p2"]

    project = client.get_project(token, "p1")
    assert project["project"]["id"] == "p1"

    areas = client.list_areas(token)
    assert {a["id"] for a in areas["areas"]} == {"a1", "a2"}

    area = client.get_area(token, "a1")
    assert area["area"]["id"] == "a1"


@pytest.mark.covers_function("Delegate Token Validation")
def test_expired_access_token_returns_401_token_expired(
    things_bridge_stack_factory,
):
    # End-to-end coverage of the time-based expiry path. Pinning this
    # at the integration layer guards against the bridge dropping the
    # ``token_expired`` discriminator in favour of a generic 401, which
    # the CLI relies on to decide whether to refresh.
    stack = things_bridge_stack_factory(access_token_ttl_seconds=1)
    payload = stack.agent_auth.create_token("things:read=allow")
    time.sleep(2)
    with pytest.raises(ThingsBridgeTokenExpiredError, match="token_expired"):
        stack.client().list_todos(payload["access_token"])


@pytest.mark.covers_function("Delegate Token Validation")
def test_list_todos_authz_unavailable_returns_502(stack):
    # Stop the in-network agent-auth service mid-test so the bridge's
    # ``authz.validate`` call surfaces a real connection error, not a
    # mocked one. The 502 ``authz_unavailable`` discriminator is what
    # clients rely on to distinguish upstream outage from bad tokens —
    # and the client maps it to :class:`ThingsBridgeUnavailableError`.
    stack["stack"].stop_agent_auth()
    with pytest.raises(ThingsBridgeUnavailableError, match="authz_unavailable"):
        stack["stack"].client().list_todos(stack["token"])


@pytest.mark.covers_function("Delegate Token Validation", "Serve Bridge Health Endpoint")
def test_health_endpoint_requires_token(things_bridge_stack):
    # Regression guard: dropping the bearer check would let any caller
    # probe service-internal state without authorization.
    with pytest.raises(ThingsBridgeUnauthorizedError, match="unauthorized"):
        things_bridge_stack.client().check_health(None)


@pytest.mark.covers_function(
    "Delegate Token Validation",
    "Check Scope Authorization",
    "Serve Bridge Health Endpoint",
)
def test_health_endpoint_requires_health_scope(things_bridge_stack):
    # A token without ``things-bridge:health`` must not satisfy the
    # health endpoint — it pins the scope-check path on /health, mirroring
    # the agent-auth/health behaviour.
    payload = things_bridge_stack.agent_auth.create_token("things:read=allow")
    with pytest.raises(ThingsBridgeForbiddenError, match="scope_denied"):
        things_bridge_stack.client().check_health(payload["access_token"])


@pytest.mark.covers_function("Delegate Token Validation", "Serve Bridge Health Endpoint")
def test_health_endpoint_returns_ok_with_health_scope(things_bridge_stack):
    # In the Compose stack, things-client-cli-applescript is installed on
    # PATH, so the deepened resolvability check passes and /health returns
    # 200. This is the positive end-to-end evidence that the check doesn't
    # regress the readiness-probe path used by Docker healthchecks.
    payload = things_bridge_stack.agent_auth.create_token("things-bridge:health=allow")
    data = things_bridge_stack.client().check_health(payload["access_token"])
    assert data == {"status": "ok"}
