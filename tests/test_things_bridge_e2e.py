"""End-to-end test of agent-auth + things-bridge + HTTP client.

Drives the full read path through real HTTP: a client sends a request with
an agent-auth-issued bearer token to things-bridge, which delegates to a
real agent-auth server running in-process, then consults an in-memory
:class:`FakeThingsClient`.

This suite is what makes the stack exercisable in a Linux devcontainer
without ``osascript`` or a real Things 3 installation. The runner-level
AppleScript interaction is not covered here — that's the subject of a
follow-up macOS-runner workflow.
"""

import json
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.audit import AuditLogger
from agent_auth.config import Config as AgentAuthConfig
from agent_auth.plugins import ApprovalResult, NotificationPlugin
from agent_auth.server import AgentAuthServer
from agent_auth.store import TokenStore
from agent_auth.tokens import (
    PREFIX_ACCESS,
    PREFIX_REFRESH,
    generate_token_id,
    sign_token,
)
from things_bridge.authz import AgentAuthClient
from things_bridge.config import Config as BridgeConfig
from things_bridge.fake import FakeThingsClient, FakeThingsStore
from things_bridge.models import Area
from things_bridge.server import ThingsBridgeServer

from tests.factories import make_project as _project, make_todo as _todo


class _AutoApprovePlugin(NotificationPlugin):
    def request_approval(self, scope, description, family_id):
        return ApprovalResult(approved=True, grant_type="once")


def _create_tokens(signing_key, store, scopes=None):
    scopes = scopes or {"things:read": "allow"}
    family_id = generate_token_id()
    store.create_family(family_id, scopes)

    now = datetime.now(timezone.utc)
    access_id = generate_token_id()
    access_token = sign_token(access_id, PREFIX_ACCESS, signing_key)
    _, _, access_sig = access_token.split("_")
    store.create_token(access_id, access_sig, family_id, "access",
                       (now + timedelta(hours=1)).isoformat())

    refresh_id = generate_token_id()
    refresh_token = sign_token(refresh_id, PREFIX_REFRESH, signing_key)
    _, _, refresh_sig = refresh_token.split("_")
    store.create_token(refresh_id, refresh_sig, family_id, "refresh",
                       (now + timedelta(hours=8)).isoformat())
    return family_id, access_token, refresh_token


def _expired_access_tokens(signing_key, store, scopes=None):
    scopes = scopes or {"things:read": "allow"}
    family_id = generate_token_id()
    store.create_family(family_id, scopes)

    now = datetime.now(timezone.utc)
    access_id = generate_token_id()
    access_token = sign_token(access_id, PREFIX_ACCESS, signing_key)
    _, _, access_sig = access_token.split("_")
    store.create_token(access_id, access_sig, family_id, "access",
                       (now - timedelta(hours=1)).isoformat())
    return family_id, access_token


def _seeded_store() -> FakeThingsStore:
    todos = [
        _todo(id="t1", name="Buy milk", area_id="a1", area_name="Personal",
              tag_names=["Errand"]),
        _todo(id="t2", name="Write report",
              notes="Include:\n\t- milestones\n\t- owners",
              project_id="p1", project_name="Q2 Planning",
              area_id="a2", area_name="Work",
              tag_names=["planning", "deep-work"]),
        _todo(id="t3", name="Fix tap", status="completed",
              area_id="a1", area_name="Personal"),
        _todo(id="t4", name="Dentist", area_id="a1", area_name="Personal",
              tag_names=["Errand"]),
    ]
    projects = [
        _project(id="p1", name="Q2 Planning", area_id="a2", area_name="Work"),
        _project(id="p2", name="Home", area_id="a1", area_name="Personal"),
    ]
    areas = [
        Area(id="a1", name="Personal", tag_names=[]),
        Area(id="a2", name="Work", tag_names=[]),
    ]
    return FakeThingsStore(
        todos=todos,
        projects=projects,
        areas=areas,
        list_memberships={"TMTodayListSource": {"t1", "t2"}},
    )


@pytest.fixture
def stack(tmp_dir, signing_key, encryption_key):
    """Spin up a real agent-auth + things-bridge pair with a fake Things client."""
    agent_auth_config = AgentAuthConfig(
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
        host="127.0.0.1",
        port=0,
    )
    token_store = TokenStore(agent_auth_config.db_path, encryption_key)
    audit = AuditLogger(agent_auth_config.log_path)
    approval_manager = ApprovalManager(_AutoApprovePlugin(), token_store, audit)
    agent_auth_server = AgentAuthServer(
        agent_auth_config, signing_key, token_store, audit, approval_manager,
    )
    agent_auth_port = agent_auth_server.server_address[1]
    agent_auth_thread = threading.Thread(
        target=agent_auth_server.serve_forever, daemon=True,
    )
    agent_auth_thread.start()

    store = _seeded_store()
    things = FakeThingsClient(store)
    authz = AgentAuthClient(f"http://127.0.0.1:{agent_auth_port}", timeout_seconds=5.0)
    bridge_config = BridgeConfig(host="127.0.0.1", port=0)
    bridge_server = ThingsBridgeServer(bridge_config, things, authz)
    bridge_port = bridge_server.server_address[1]
    bridge_thread = threading.Thread(
        target=bridge_server.serve_forever, daemon=True,
    )
    bridge_thread.start()

    try:
        yield {
            "bridge_url": f"http://127.0.0.1:{bridge_port}",
            "signing_key": signing_key,
            "token_store": token_store,
            "store": store,
        }
    finally:
        bridge_server.shutdown()
        bridge_server.server_close()
        bridge_thread.join(timeout=2)
        agent_auth_server.shutdown()
        agent_auth_server.server_close()
        agent_auth_thread.join(timeout=2)


def _get(url, token: str | None):
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"_raw": body.decode("utf-8", errors="replace")}
        return exc.code, parsed


@pytest.mark.covers_function("Delegate Token Validation", "Serve Bridge HTTP API")
def test_list_todos_end_to_end(stack):
    _, token, _ = _create_tokens(stack["signing_key"], stack["token_store"])
    status, data = _get(f"{stack['bridge_url']}/things-bridge/todos", token)
    assert status == 200
    assert {t["id"] for t in data["todos"]} == {"t1", "t2", "t3", "t4"}


@pytest.mark.covers_function("Delegate Token Validation")
def test_list_todos_missing_token_returns_401(stack):
    status, data = _get(f"{stack['bridge_url']}/things-bridge/todos", token=None)
    assert status == 401
    assert data == {"error": "unauthorized"}


@pytest.mark.covers_function("Delegate Token Validation")
def test_list_todos_expired_access_token_returns_401_token_expired(stack):
    _, expired_token = _expired_access_tokens(stack["signing_key"], stack["token_store"])
    status, data = _get(f"{stack['bridge_url']}/things-bridge/todos", expired_token)
    assert status == 401
    assert data == {"error": "token_expired"}


@pytest.mark.covers_function("Delegate Token Validation", "Check Scope Authorization")
def test_list_todos_wrong_scope_returns_403(stack):
    _, token, _ = _create_tokens(
        stack["signing_key"], stack["token_store"],
        scopes={"outlook:mail:read": "allow"},
    )
    status, data = _get(f"{stack['bridge_url']}/things-bridge/todos", token)
    assert status == 403
    assert data == {"error": "scope_denied"}


@pytest.mark.covers_function("Delegate Token Validation")
def test_list_todos_revoked_family_returns_401(stack):
    family_id, token, _ = _create_tokens(stack["signing_key"], stack["token_store"])
    stack["token_store"].mark_family_revoked(family_id)
    status, data = _get(f"{stack['bridge_url']}/things-bridge/todos", token)
    assert status == 401
    assert data == {"error": "unauthorized"}


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_list_todos_filters_forwarded_through_fake(stack):
    _, token, _ = _create_tokens(stack["signing_key"], stack["token_store"])
    status, data = _get(
        f"{stack['bridge_url']}/things-bridge/todos?project=p1", token,
    )
    assert status == 200
    assert [t["id"] for t in data["todos"]] == ["t2"]


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_list_todos_list_filter_resolves_via_memberships(stack):
    _, token, _ = _create_tokens(stack["signing_key"], stack["token_store"])
    status, data = _get(
        f"{stack['bridge_url']}/things-bridge/todos?list=TMTodayListSource", token,
    )
    assert status == 200
    assert {t["id"] for t in data["todos"]} == {"t1", "t2"}


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_list_todos_tag_filter(stack):
    _, token, _ = _create_tokens(stack["signing_key"], stack["token_store"])
    status, data = _get(
        f"{stack['bridge_url']}/things-bridge/todos?tag=Errand", token,
    )
    assert status == 200
    assert {t["id"] for t in data["todos"]} == {"t1", "t4"}


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_list_todos_status_filter(stack):
    _, token, _ = _create_tokens(stack["signing_key"], stack["token_store"])
    status, data = _get(
        f"{stack['bridge_url']}/things-bridge/todos?status=completed", token,
    )
    assert status == 200
    assert [t["id"] for t in data["todos"]] == ["t3"]


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_get_todo_by_id_roundtrips_freeform_notes(stack):
    # The notes on t2 contain \n and \t; confirm they survive the JSON
    # round-trip so CLI clients can rely on free-form text being preserved.
    _, token, _ = _create_tokens(stack["signing_key"], stack["token_store"])
    status, data = _get(f"{stack['bridge_url']}/things-bridge/todos/t2", token)
    assert status == 200
    assert data["todo"]["id"] == "t2"
    assert "\t" in data["todo"]["notes"]
    assert "\n" in data["todo"]["notes"]


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_get_unknown_todo_returns_404(stack):
    _, token, _ = _create_tokens(stack["signing_key"], stack["token_store"])
    status, data = _get(f"{stack['bridge_url']}/things-bridge/todos/does-not-exist", token)
    assert status == 404
    assert data == {"error": "not_found"}


@pytest.mark.covers_function("Serve Bridge HTTP API")
def test_projects_and_areas(stack):
    _, token, _ = _create_tokens(stack["signing_key"], stack["token_store"])

    status, projects = _get(f"{stack['bridge_url']}/things-bridge/projects", token)
    assert status == 200
    assert {p["id"] for p in projects["projects"]} == {"p1", "p2"}

    status, filtered = _get(
        f"{stack['bridge_url']}/things-bridge/projects?area=a1", token,
    )
    assert status == 200
    assert [p["id"] for p in filtered["projects"]] == ["p2"]

    status, project = _get(f"{stack['bridge_url']}/things-bridge/projects/p1", token)
    assert status == 200
    assert project["project"]["id"] == "p1"

    status, areas = _get(f"{stack['bridge_url']}/things-bridge/areas", token)
    assert status == 200
    assert {a["id"] for a in areas["areas"]} == {"a1", "a2"}

    status, area = _get(f"{stack['bridge_url']}/things-bridge/areas/a1", token)
    assert status == 200
    assert area["area"]["id"] == "a1"


def test_list_todos_authz_unavailable_returns_502(tmp_dir):
    """If agent-auth isn't reachable, the bridge should report 502 authz_unavailable."""
    # Point the bridge at a port nothing is listening on.
    authz = AgentAuthClient("http://127.0.0.1:1", timeout_seconds=1.0)
    bridge_config = BridgeConfig(host="127.0.0.1", port=0)
    things = FakeThingsClient(FakeThingsStore())
    server = ThingsBridgeServer(bridge_config, things, authz)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, data = _get(f"http://127.0.0.1:{port}/things-bridge/todos", "aa_any_thing")
        assert status == 502
        assert data["error"] == "authz_unavailable"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
