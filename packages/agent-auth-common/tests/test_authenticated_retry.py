# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for :class:`agent_auth_client.AuthenticatedRetry`.

The library carries the refresh + reissue retry ladder shared by
``things-cli`` and ``gpg-cli`` (issue #328). These tests are the
authoritative spec for the orchestration contract in isolation; the
two CLIs each keep their own end-to-end behavioural test suite that
drives the same flows through the production HTTP plumbing
(``packages/things-cli/tests/test_things_cli_client.py`` and
``packages/gpg-cli/tests/test_gpg_cli_client.py``).

The tests use:

- A tiny in-process HTTP server that simulates the agent-auth
  ``/token/refresh`` and ``/token/reissue`` endpoints. This keeps the
  exercise of :class:`AgentAuthClient` honest — we test against the
  real client, not a stub of it.
- A minimal mutable credential record + a recording store that
  satisfy :class:`CredentialsLike` / :class:`CredentialStoreLike`
  structurally.
- Caller-provided exception classes (``_TokenExpired``,
  ``_Unauthorized``, ``_Unavailable``) so we exercise the
  exception-injection seam directly without coupling to either
  CLI's error taxonomy.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest

from agent_auth_client import AgentAuthClient, AuthenticatedRetry

# -- caller-supplied error classes (modelled on each CLI's hierarchy) --


class _TokenExpired(Exception):
    """Stand-in for ``ThingsBridgeTokenExpiredError`` / ``BridgeTokenExpiredError``."""


class _Unauthorized(Exception):
    """Stand-in for the CLI's terminal 401 class."""


class _Unavailable(Exception):
    """Stand-in for the CLI's "downstream unavailable" class."""


# -- structural fakes for the protocols --


@dataclass
class _Credentials:
    """Mutable credential record satisfying :class:`CredentialsLike`."""

    access_token: str
    refresh_token: str
    family_id: str | None


class _RecordingStore:
    """Records every ``save`` so tests can assert persist-before-retry."""

    def __init__(self) -> None:
        self.saves: list[tuple[str, str, str | None]] = []

    def save(self, credentials: _Credentials, /) -> None:
        self.saves.append(
            (credentials.access_token, credentials.refresh_token, credentials.family_id)
        )


# -- in-process agent-auth fake --


class _AuthHandler(BaseHTTPRequestHandler):
    """Drive responses for ``/token/refresh`` and ``/token/reissue`` per test."""

    refresh_responses: ClassVar[list[tuple[int, dict[str, Any]]]] = []
    reissue_responses: ClassVar[list[tuple[int, dict[str, Any]]]] = []
    captured_requests: ClassVar[list[tuple[str, dict[str, Any]]]] = []

    def log_message(self, *args, **kwargs):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else {}
        _AuthHandler.captured_requests.append((self.path, body))
        if self.path == "/agent-auth/v1/token/refresh":
            status, resp = _AuthHandler.refresh_responses.pop(0)
        elif self.path == "/agent-auth/v1/token/reissue":
            status, resp = _AuthHandler.reissue_responses.pop(0)
        else:
            status, resp = 404, {"error": "not_found"}
        out = json.dumps(resp).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


@pytest.fixture
def auth_server():
    _AuthHandler.refresh_responses = []
    _AuthHandler.reissue_responses = []
    _AuthHandler.captured_requests = []
    server = HTTPServer(("127.0.0.1", 0), _AuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _make_retry(
    auth_url: str,
    *,
    family_id: str | None = "fam-1",
) -> tuple[AuthenticatedRetry[dict[str, Any], _Credentials], _Credentials, _RecordingStore]:
    creds = _Credentials(
        access_token="aa_initial",
        refresh_token="rt_initial",
        family_id=family_id,
    )
    store = _RecordingStore()
    retry: AuthenticatedRetry[dict[str, Any], _Credentials] = AuthenticatedRetry(
        creds,
        store,
        AgentAuthClient(auth_url, timeout_seconds=2.0),
        token_expired_exc=_TokenExpired,
        unauthorized_exc=_Unauthorized,
        unavailable_exc=_Unavailable,
        no_family_id_message="no family_id; re-bootstrap",
    )
    return retry, creds, store


# -- happy path --


def test_no_token_expired_returns_call_result_directly(auth_server):
    retry, creds, store = _make_retry(auth_server)
    seen_tokens: list[str] = []

    def call(token: str) -> dict[str, Any]:
        seen_tokens.append(token)
        return {"ok": True}

    assert retry.with_retry(call) == {"ok": True}
    assert seen_tokens == ["aa_initial"]
    # No refresh / reissue calls; no save.
    assert _AuthHandler.captured_requests == []
    assert store.saves == []
    # Credentials untouched.
    assert (creds.access_token, creds.refresh_token) == ("aa_initial", "rt_initial")


# -- refresh path --


def test_token_expired_triggers_refresh_and_retry(auth_server):
    _AuthHandler.refresh_responses = [
        (
            200,
            {
                "access_token": "aa_new",
                "refresh_token": "rt_new",
                "expires_in": 900,
                "scopes": {},
            },
        ),
    ]
    retry, creds, store = _make_retry(auth_server)
    calls: list[str] = []

    def call(token: str) -> dict[str, Any]:
        calls.append(token)
        if len(calls) == 1:
            raise _TokenExpired("token_expired")
        return {"ok": True, "attempt": len(calls)}

    assert retry.with_retry(call) == {"ok": True, "attempt": 2}
    # First with the original token, second with the refreshed one.
    assert calls == ["aa_initial", "aa_new"]
    # Rotated pair persisted before the retry.
    assert store.saves == [("aa_new", "rt_new", "fam-1")]
    assert (creds.access_token, creds.refresh_token) == ("aa_new", "rt_new")
    # No reissue.
    assert all(path == "/agent-auth/v1/token/refresh" for path, _ in _AuthHandler.captured_requests)


def test_persist_before_retry_even_when_retry_fails(auth_server):
    """Refresh tokens are single-use (ADR 0011): the rotated pair must reach the store
    *before* the retried call runs, so a crash between the refresh and the retry
    cannot leave a consumed refresh token behind. The retry-budget cap (one) means a
    second ``token_expired`` collapses to ``unauthorized_exc``.
    """
    _AuthHandler.refresh_responses = [
        (
            200,
            {
                "access_token": "aa_new",
                "refresh_token": "rt_new",
                "expires_in": 900,
                "scopes": {},
            },
        ),
    ]
    retry, _creds, store = _make_retry(auth_server)
    calls: list[str] = []

    def always_token_expired(token: str) -> dict[str, Any]:
        calls.append(token)
        raise _TokenExpired("token_expired")

    with pytest.raises(_Unauthorized):
        retry.with_retry(always_token_expired)
    # Exactly two attempts — the budget is one retry, not unbounded.
    assert calls == ["aa_initial", "aa_new"]
    # Critical: the rotated pair was persisted even though the retry failed.
    assert store.saves == [("aa_new", "rt_new", "fam-1")]


# -- reissue path --


def test_refresh_token_expired_falls_back_to_reissue(auth_server):
    _AuthHandler.refresh_responses = [(401, {"error": "refresh_token_expired"})]
    _AuthHandler.reissue_responses = [
        (
            200,
            {
                "access_token": "aa_reissued",
                "refresh_token": "rt_reissued",
                "expires_in": 900,
                "scopes": {},
            },
        ),
    ]
    retry, creds, store = _make_retry(auth_server)
    calls: list[str] = []

    def call(token: str) -> dict[str, Any]:
        calls.append(token)
        if len(calls) == 1:
            raise _TokenExpired("token_expired")
        return {"ok": True}

    assert retry.with_retry(call) == {"ok": True}
    assert calls == ["aa_initial", "aa_reissued"]
    assert store.saves == [("aa_reissued", "rt_reissued", "fam-1")]
    assert (creds.access_token, creds.refresh_token) == ("aa_reissued", "rt_reissued")


def test_no_family_id_blocks_reissue(auth_server):
    _AuthHandler.refresh_responses = [(401, {"error": "refresh_token_expired"})]
    retry, _creds, store = _make_retry(auth_server, family_id=None)

    def call(token: str) -> dict[str, Any]:
        raise _TokenExpired("token_expired")

    with pytest.raises(_Unauthorized, match="no family_id; re-bootstrap"):
        retry.with_retry(call)
    # Reissue must not have been called.
    assert all(path != "/agent-auth/v1/token/reissue" for path, _ in _AuthHandler.captured_requests)
    # No persistence — nothing rotated.
    assert store.saves == []


# -- terminal-error mapping --


def test_reuse_detected_surfaces_as_unauthorized(auth_server):
    _AuthHandler.refresh_responses = [(401, {"error": "refresh_token_reuse_detected"})]
    retry, _creds, store = _make_retry(auth_server)

    def call(token: str) -> dict[str, Any]:
        raise _TokenExpired("token_expired")

    with pytest.raises(_Unauthorized, match="refresh_token_reuse_detected"):
        retry.with_retry(call)
    assert store.saves == []


def test_family_revoked_on_refresh_surfaces_as_unauthorized(auth_server):
    _AuthHandler.refresh_responses = [(401, {"error": "family_revoked"})]
    retry, _creds, store = _make_retry(auth_server)

    def call(token: str) -> dict[str, Any]:
        raise _TokenExpired("token_expired")

    with pytest.raises(_Unauthorized, match="family_revoked"):
        retry.with_retry(call)
    assert store.saves == []


def test_reissue_denied_surfaces_as_unauthorized(auth_server):
    _AuthHandler.refresh_responses = [(401, {"error": "refresh_token_expired"})]
    _AuthHandler.reissue_responses = [(403, {"error": "reissue_denied"})]
    retry, _creds, store = _make_retry(auth_server)

    def call(token: str) -> dict[str, Any]:
        raise _TokenExpired("token_expired")

    with pytest.raises(_Unauthorized, match="reissue_denied"):
        retry.with_retry(call)
    assert store.saves == []


def test_refresh_unreachable_surfaces_as_unavailable(tmp_path):
    """Pointing the AgentAuthClient at a closed port surfaces ``unavailable_exc``.

    This is the connection-error path: ``AgentAuthClient`` translates
    socket failures into :class:`AuthzUnavailableError`, which the
    retry loop then maps to the caller's ``unavailable_exc``.
    """
    creds = _Credentials(access_token="aa_initial", refresh_token="rt_initial", family_id="fam-1")
    store = _RecordingStore()
    # Port 1 is reserved; nothing is listening, so the connect fails fast.
    retry: AuthenticatedRetry[dict[str, Any], _Credentials] = AuthenticatedRetry(
        creds,
        store,
        AgentAuthClient("http://127.0.0.1:1", timeout_seconds=0.5),
        token_expired_exc=_TokenExpired,
        unauthorized_exc=_Unauthorized,
        unavailable_exc=_Unavailable,
        no_family_id_message="unused",
    )

    def call(token: str) -> dict[str, Any]:
        raise _TokenExpired("token_expired")

    with pytest.raises(_Unavailable):
        retry.with_retry(call)
    assert store.saves == []


# -- internal-contract guarantees --


def test_retry_collapses_second_token_expired_into_unauthorized(auth_server):
    """A ``token_expired`` from the *retried* call (not the first) must
    surface as ``unauthorized_exc``, not as the raw downstream class.

    This guards the orchestration contract: callers see a uniform
    "we tried and failed" type, never a leaked
    ``ThingsBridgeTokenExpiredError`` / ``BridgeTokenExpiredError``.
    """
    _AuthHandler.refresh_responses = [
        (
            200,
            {
                "access_token": "aa_new",
                "refresh_token": "rt_new",
                "expires_in": 900,
                "scopes": {},
            },
        ),
    ]
    retry, _creds, _store = _make_retry(auth_server)

    def call(token: str) -> dict[str, Any]:
        raise _TokenExpired("token_expired")

    with pytest.raises(_Unauthorized) as exc_info:
        retry.with_retry(call)
    # Specifically NOT the downstream class.
    assert not isinstance(exc_info.value, _TokenExpired)


def test_call_result_is_returned_unchanged(auth_server):
    """The orchestration must not transform the downstream result.

    Things-cli passes ``dict[str, Any]`` and gpg-cli composes a dict
    into a typed dataclass at the call site; the orchestration is
    transparent in both cases.
    """
    retry, _creds, _store = _make_retry(auth_server)
    payload = {"deeply": {"nested": ["value"]}}

    def call(token: str) -> dict[str, Any]:
        return payload

    assert retry.with_retry(call) is payload
