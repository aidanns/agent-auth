# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP-level tests for per-family rate limiting.

Pins the 429 / Retry-After contract across every authenticated
agent-auth endpoint so a refactor that silently skips the limiter on
one path gets caught. Unit-level token-bucket behaviour is in
``tests/test_rate_limit.py``; this module is the cross-endpoint
integration.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any

import pytest

from agent_auth.approval import ApprovalManager
from agent_auth.approval_client import ApprovalClient
from agent_auth.audit import AuditLogger
from agent_auth.config import Config
from agent_auth.metrics import build_registry
from agent_auth.rate_limit import RateLimiter
from agent_auth.server import MANAGEMENT_SCOPE, AgentAuthServer
from agent_auth.store import TokenStore
from agent_auth.tokens import create_token_pair


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, Any, dict[str, str]]:
    req = urllib.request.Request(url)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"null"), dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            parsed = json.loads(body) if body else None
        except json.JSONDecodeError:
            parsed = None
        return exc.code, parsed, dict((exc.headers or {}).items())


def _post(
    url: str, payload: dict[str, Any], headers: dict[str, str] | None = None
) -> tuple[int, Any, dict[str, str]]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"null"), dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        data = exc.read()
        try:
            parsed = json.loads(data) if data else None
        except json.JSONDecodeError:
            parsed = None
        return exc.code, parsed, dict((exc.headers or {}).items())


@pytest.fixture
def server_with_tight_rate_limit(tmp_dir, signing_key, encryption_key):
    # rate_limit_per_minute=3 → bucket capacity 3, refill 0.05/sec.
    # The fourth consume denies within the same test window.
    config = Config(
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
        host="127.0.0.1",
        port=0,
        rate_limit_per_minute=3,
    )
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path)
    approval_manager = ApprovalManager(ApprovalClient(url=""), store, audit)
    registry, metrics = build_registry()
    server = AgentAuthServer(config, signing_key, store, audit, approval_manager, registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{port}", store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _issue_token(server, store, scopes: dict[str, str]) -> tuple[str, str]:
    family_id = f"fam-{len(store.list_families())}"
    store.create_family(family_id, scopes)
    access_token, _refresh_token = create_token_pair(
        server.signing_key, store, family_id, server.config
    )
    return family_id, access_token


def test_health_returns_429_after_bucket_exhausted(server_with_tight_rate_limit):
    # All four endpoint categories drain the same per-family bucket; use
    # /health as the probe since it has the smallest surface area. The
    # limiter is set to 3 requests/minute so the 4th hit is denied.
    server, base, store = server_with_tight_rate_limit
    _, token = _issue_token(server, store, {"agent-auth:health": "allow"})
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(3):
        status, body, _ = _get(f"{base}/agent-auth/health", headers)
        assert status == 200, body
    status, body, resp_headers = _get(f"{base}/agent-auth/health", headers)
    assert status == 429
    assert body == {"error": "rate_limited"}
    # Retry-After must be a positive integer per RFC 7231.
    retry_after = resp_headers.get("Retry-After", "")
    assert retry_after.isdigit() and int(retry_after) >= 1


def test_management_endpoints_share_bucket_with_validate(server_with_tight_rate_limit):
    # Management + validate should pull from the same bucket keyed on
    # the family that presented the token — otherwise a rate-limited
    # family could hop endpoints to bypass the ceiling.
    server, base, store = server_with_tight_rate_limit
    _family_id, access_token = _issue_token(
        server, store, {MANAGEMENT_SCOPE: "allow", "demo:scope": "allow"}
    )
    headers = {"Authorization": f"Bearer {access_token}"}
    # Spend 2 from bucket on /token/list, 1 on /validate, then expect 429 anywhere.
    for _ in range(2):
        status, _, _ = _get(f"{base}/agent-auth/v1/token/list", headers)
        assert status == 200
    status, _, _ = _post(
        f"{base}/agent-auth/v1/validate",
        {"token": access_token, "required_scope": "demo:scope"},
    )
    assert status == 200
    # Bucket empty; next request from the same family is 429 regardless
    # of endpoint.
    status, body, _ = _get(f"{base}/agent-auth/v1/token/list", headers)
    assert status == 429
    assert body == {"error": "rate_limited"}


def test_separate_families_have_independent_buckets(server_with_tight_rate_limit):
    server, base, store = server_with_tight_rate_limit
    _, token_a = _issue_token(server, store, {"agent-auth:health": "allow"})
    _, token_b = _issue_token(server, store, {"agent-auth:health": "allow"})
    for _ in range(3):
        status, _, _ = _get(f"{base}/agent-auth/health", {"Authorization": f"Bearer {token_a}"})
        assert status == 200
    # Family A drained; family B still has a full bucket.
    status, _, _ = _get(f"{base}/agent-auth/health", {"Authorization": f"Bearer {token_a}"})
    assert status == 429
    status, _, _ = _get(f"{base}/agent-auth/health", {"Authorization": f"Bearer {token_b}"})
    assert status == 200


def test_rate_limit_denial_writes_audit_entry(server_with_tight_rate_limit):
    server, base, store = server_with_tight_rate_limit
    family_id, token = _issue_token(server, store, {"agent-auth:health": "allow"})
    headers = {"Authorization": f"Bearer {token}"}
    responses = [_get(f"{base}/agent-auth/health", headers) for _ in range(4)]
    # Sanity-check the bucket actually drained — otherwise the audit
    # assertion below is vacuous.
    statuses = [r[0] for r in responses]
    assert 429 in statuses, f"no 429 in {statuses}; bucket may have refilled under load"
    # Scan the audit log for the rate_limited event on this family. The
    # log path comes from the fixture's Config, which roots everything
    # on the server's own config.log_path — reading straight off the
    # server avoids any tmp-dir fixture resolution ambiguity.
    with open(server.config.log_path) as f:
        entries = [json.loads(line) for line in f if line.strip()]
    rate_limited = [
        e for e in entries if e["event"] == "rate_limited" and e.get("family_id") == family_id
    ]
    assert len(rate_limited) >= 1
    assert rate_limited[0]["service.name"] == "agent-auth"
    assert rate_limited[0]["scope"] == "agent-auth:health"


def test_disabled_limit_never_denies(tmp_dir, signing_key, encryption_key):
    # rate_limit_per_minute=0 disables the gate — the deferred posture
    # of ADR 0022 must remain available as a backwards-compatible
    # off switch.
    config = Config(
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
        host="127.0.0.1",
        port=0,
        rate_limit_per_minute=0,
    )
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path)
    approval_manager = ApprovalManager(ApprovalClient(url=""), store, audit)
    registry, metrics = build_registry()
    server = AgentAuthServer(config, signing_key, store, audit, approval_manager, registry, metrics)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        _, token = _issue_token(server, store, {"agent-auth:health": "allow"})
        headers = {"Authorization": f"Bearer {token}"}
        # Run well past the default bucket capacity of 600.
        for _ in range(50):
            status, _, _ = _get(f"{base}/agent-auth/health", headers)
            assert status == 200
        # Rate-limiter itself reports disabled.
        assert server.rate_limiter.enabled is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_rate_limiter_can_be_injected_for_determinism(tmp_dir, signing_key, encryption_key):
    # Tests should be able to drive a pinned clock into the limiter so
    # refill behaviour at the HTTP boundary is deterministic.
    now = [0.0]
    injected = RateLimiter(60, clock=lambda: now[0])
    config = Config(
        db_path=os.path.join(tmp_dir, "tokens.db"),
        log_path=os.path.join(tmp_dir, "audit.log"),
        host="127.0.0.1",
        port=0,
        rate_limit_per_minute=60,
    )
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path)
    approval_manager = ApprovalManager(ApprovalClient(url=""), store, audit)
    registry, metrics = build_registry()
    server = AgentAuthServer(
        config,
        signing_key,
        store,
        audit,
        approval_manager,
        registry,
        metrics,
        rate_limiter=injected,
    )
    assert server.rate_limiter is injected
    server.server_close()
