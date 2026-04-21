# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP server for agent-auth API."""

import json
import os
import signal
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from agent_auth.approval import ApprovalManager
from agent_auth.audit import AuditLogger
from agent_auth.config import Config
from agent_auth.errors import ScopeDeniedError, TokenInvalidError
from agent_auth.keys import KeyManager, SigningKey
from agent_auth.plugins import load_plugin
from agent_auth.scopes import VALID_TIERS, check_scope
from agent_auth.store import TokenStore
from agent_auth.tokens import (
    PREFIX_ACCESS,
    PREFIX_REFRESH,
    create_token_pair,
    generate_token_id,
    verify_token,
)

MANAGEMENT_SCOPE = "agent-auth:manage"


class AgentAuthHandler(BaseHTTPRequestHandler):
    """HTTP request handler for agent-auth API endpoints."""

    @property
    def _server(self) -> "AgentAuthServer":
        return cast("AgentAuthServer", self.server)

    MAX_BODY_SIZE = 1_048_576  # 1 MiB

    def _read_json(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > self.MAX_BODY_SIZE:
            return None
        body = self.rfile.read(length)
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return cast(dict[str, Any], parsed)

    def _send_json(self, status: int, data: dict[str, Any] | list[dict[str, Any]]) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        if self.path == "/agent-auth/v1/validate":
            self._handle_validate()
        elif self.path == "/agent-auth/v1/token/refresh":
            self._handle_refresh()
        elif self.path == "/agent-auth/v1/token/reissue":
            self._handle_reissue()
        elif self.path == "/agent-auth/v1/token/create":
            self._handle_token_create()
        elif self.path == "/agent-auth/v1/token/modify":
            self._handle_token_modify()
        elif self.path == "/agent-auth/v1/token/revoke":
            self._handle_token_revoke()
        elif self.path == "/agent-auth/v1/token/rotate":
            self._handle_token_rotate()
        else:
            self._send_json(404, {"error": "not_found"})

    def do_GET(self) -> None:
        if self.path == "/agent-auth/v1/token/status":
            self._handle_status()
        elif self.path == "/agent-auth/health":
            self._handle_health()
        elif self.path == "/agent-auth/v1/token/list":
            self._handle_token_list()
        else:
            self._send_json(404, {"error": "not_found"})

    def _handle_validate(self) -> None:
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "malformed_request"})
            return
        token_raw = data.get("token", "")
        required_scope = data.get("required_scope", "")
        description = data.get("description")

        store: TokenStore = self._server.store
        signing_key: SigningKey = self._server.signing_key
        approval_manager: ApprovalManager = self._server.approval_manager
        audit: AuditLogger = self._server.audit

        try:
            prefix, token_id = verify_token(token_raw, signing_key)
        except TokenInvalidError:
            audit.log_authorization_decision(
                "validation_denied", reason="invalid_token", scope=required_scope
            )
            self._send_json(401, {"valid": False, "error": "invalid_token"})
            return

        if prefix != PREFIX_ACCESS:
            audit.log_authorization_decision(
                "validation_denied", reason="not_access_token", scope=required_scope
            )
            self._send_json(401, {"valid": False, "error": "invalid_token"})
            return

        token_record = store.get_token(token_id)
        if token_record is None:
            audit.log_authorization_decision(
                "validation_denied", reason="token_not_found", scope=required_scope
            )
            self._send_json(401, {"valid": False, "error": "invalid_token"})
            return

        now = datetime.now(UTC)
        expires_at = datetime.fromisoformat(token_record["expires_at"])
        if now >= expires_at:
            audit.log_authorization_decision(
                "validation_denied",
                reason="token_expired",
                token_id=token_id,
                scope=required_scope,
            )
            self._send_json(401, {"valid": False, "error": "token_expired"})
            return

        family = store.get_family(token_record["family_id"])
        if family is None or family["revoked"]:
            audit.log_authorization_decision(
                "validation_denied",
                reason="family_revoked",
                token_id=token_id,
                scope=required_scope,
            )
            self._send_json(401, {"valid": False, "error": "token_revoked"})
            return

        try:
            tier = check_scope(required_scope, family["scopes"])
        except ScopeDeniedError:
            audit.log_authorization_decision(
                "validation_denied",
                reason="scope_denied",
                token_id=token_id,
                scope=required_scope,
            )
            self._send_json(403, {"valid": False, "error": "scope_denied"})
            return

        if tier == "allow":
            audit.log_authorization_decision(
                "validation_allowed",
                token_id=token_id,
                scope=required_scope,
                tier="allow",
            )
            self._send_json(200, {"valid": True})
            return

        if tier == "prompt":
            result = approval_manager.request_approval(family["id"], required_scope, description)
            if result.approved:
                audit.log_authorization_decision(
                    "validation_allowed",
                    token_id=token_id,
                    scope=required_scope,
                    tier="prompt",
                    grant_type=result.grant_type,
                )
                self._send_json(200, {"valid": True})
            else:
                audit.log_authorization_decision(
                    "validation_denied",
                    reason="approval_denied",
                    token_id=token_id,
                    scope=required_scope,
                )
                self._send_json(403, {"valid": False, "error": "scope_denied"})
            return

    def _handle_refresh(self) -> None:
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "malformed_request"})
            return
        refresh_token_raw = data.get("refresh_token", "")

        store: TokenStore = self._server.store
        signing_key: SigningKey = self._server.signing_key
        config: Config = self._server.config
        audit: AuditLogger = self._server.audit

        try:
            prefix, token_id = verify_token(refresh_token_raw, signing_key)
        except TokenInvalidError:
            self._send_json(401, {"error": "invalid_token"})
            return

        if prefix != PREFIX_REFRESH:
            self._send_json(401, {"error": "invalid_token"})
            return

        token_record = store.get_token(token_id)
        if token_record is None:
            self._send_json(401, {"error": "invalid_token"})
            return

        family = store.get_family(token_record["family_id"])
        if family is None or family["revoked"]:
            self._send_json(401, {"error": "family_revoked"})
            return

        now = datetime.now(UTC)
        expires_at = datetime.fromisoformat(token_record["expires_at"])
        if now >= expires_at:
            self._send_json(401, {"error": "refresh_token_expired"})
            return

        # Atomically mark consumed — if already consumed, this is reuse
        if not store.mark_consumed(token_id):
            store.mark_family_revoked(token_record["family_id"])
            audit.log_token_operation(
                "token_revoked",
                family_id=token_record["family_id"],
                reason="refresh_token_reuse_detected",
            )
            self._send_json(
                401,
                {
                    "error": "refresh_token_reuse_detected",
                    "detail": "Token family revoked",
                },
            )
            return

        family_id = token_record["family_id"]
        access_token, new_refresh_token = create_token_pair(signing_key, store, family_id, config)

        audit.log_token_operation("token_refreshed", family_id=family_id)

        self._send_json(
            200,
            {
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "expires_in": config.access_token_ttl_seconds,
                "scopes": family["scopes"],
            },
        )

    def _handle_reissue(self) -> None:
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "malformed_request"})
            return
        family_id = data.get("family_id", "")

        store: TokenStore = self._server.store
        signing_key: SigningKey = self._server.signing_key
        config: Config = self._server.config
        audit: AuditLogger = self._server.audit
        approval_manager: ApprovalManager = self._server.approval_manager

        family = store.get_family(family_id)
        if family is None or family["revoked"]:
            self._send_json(401, {"error": "family_revoked"})
            return

        # Per design: reissue is only available when the refresh token has expired
        # (not consumed by reuse detection). Verify a refresh token exists and is expired.
        family_tokens = store.get_tokens_by_family(family_id)
        refresh_tokens = [t for t in family_tokens if t["type"] == "refresh"]
        if not refresh_tokens:
            self._send_json(401, {"error": "family_revoked"})
            return
        latest_refresh = max(refresh_tokens, key=lambda t: t["expires_at"])
        now = datetime.now(UTC)
        refresh_expires = datetime.fromisoformat(latest_refresh["expires_at"])
        if now < refresh_expires and not latest_refresh["consumed"]:
            self._send_json(400, {"error": "refresh_token_still_valid"})
            return
        if latest_refresh["consumed"]:
            self._send_json(401, {"error": "family_revoked"})
            return

        result = approval_manager.request_approval(
            family_id, "token:reissue", "Re-issue token pair for expired refresh token"
        )
        if not result.approved:
            audit.log_token_operation("reissue_denied", family_id=family_id)
            self._send_json(403, {"error": "reissue_denied"})
            return

        access_token, new_refresh_token = create_token_pair(signing_key, store, family_id, config)

        audit.log_token_operation("token_reissued", family_id=family_id)

        self._send_json(
            200,
            {
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "expires_in": config.access_token_ttl_seconds,
                "scopes": family["scopes"],
            },
        )

    def _require_management_auth(self) -> bool:
        """Validate management bearer token. Sends 401/403 and returns False if invalid."""
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_json(401, {"error": "missing_token"})
            return False

        token_raw = auth_header[7:]
        store: TokenStore = self._server.store
        signing_key: SigningKey = self._server.signing_key

        try:
            prefix, token_id = verify_token(token_raw, signing_key)
        except TokenInvalidError:
            self._send_json(401, {"error": "invalid_token"})
            return False
        if prefix != PREFIX_ACCESS:
            self._send_json(401, {"error": "invalid_token"})
            return False

        token_record = store.get_token(token_id)
        if token_record is None:
            self._send_json(401, {"error": "invalid_token"})
            return False

        family = store.get_family(token_record["family_id"])
        if family is None or family["revoked"]:
            self._send_json(401, {"error": "invalid_token"})
            return False

        now = datetime.now(UTC)
        expires_at = datetime.fromisoformat(token_record["expires_at"])
        if now >= expires_at:
            self._send_json(401, {"error": "token_expired"})
            return False

        if family["scopes"].get(MANAGEMENT_SCOPE) != "allow":
            self._send_json(403, {"error": "scope_denied"})
            return False

        return True

    def _get_active_family(self, store: TokenStore, family_id: str) -> dict[str, Any] | None:
        """Return family if it exists and is not revoked; send 404/409 and return None otherwise."""
        family = store.get_family(family_id)
        if family is None:
            self._send_json(404, {"error": "family_not_found"})
            return None
        if family["revoked"]:
            self._send_json(409, {"error": "family_revoked"})
            return None
        return family

    def _handle_token_create(self) -> None:
        if not self._require_management_auth():
            return
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "malformed_request"})
            return
        scopes_raw = data.get("scopes")
        if not isinstance(scopes_raw, dict) or not scopes_raw:
            self._send_json(400, {"error": "no_scopes"})
            return
        scopes: dict[str, str] = cast(dict[str, str], scopes_raw)
        invalid_tiers = {k: v for k, v in scopes.items() if v not in VALID_TIERS}
        if invalid_tiers:
            self._send_json(400, {"error": "invalid_tier", "detail": invalid_tiers})
            return

        store: TokenStore = self._server.store
        signing_key: SigningKey = self._server.signing_key
        config: Config = self._server.config
        audit: AuditLogger = self._server.audit

        family_id = generate_token_id()
        store.create_family(family_id, scopes)
        access_token, refresh_token = create_token_pair(signing_key, store, family_id, config)
        audit.log_token_operation("token_created", family_id=family_id, scopes=scopes)

        self._send_json(
            200,
            {
                "family_id": family_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "scopes": scopes,
                "expires_in": config.access_token_ttl_seconds,
            },
        )

    def _handle_token_list(self) -> None:
        if not self._require_management_auth():
            return
        store: TokenStore = self._server.store
        families = [f for f in store.list_families() if MANAGEMENT_SCOPE not in f.get("scopes", {})]
        self._send_json(200, families)

    def _handle_token_modify(self) -> None:
        if not self._require_management_auth():
            return
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "malformed_request"})
            return
        family_id = data.get("family_id")
        if not isinstance(family_id, str) or not family_id:
            self._send_json(400, {"error": "malformed_request"})
            return
        add_scopes_raw: object = data.get("add_scopes")
        remove_scopes_raw: object = data.get("remove_scopes")
        set_tiers_raw: object = data.get("set_tiers")
        if add_scopes_raw is None:
            add_scopes_raw = {}
        if remove_scopes_raw is None:
            remove_scopes_raw = []
        if set_tiers_raw is None:
            set_tiers_raw = {}
        if (
            not isinstance(add_scopes_raw, dict)
            or not isinstance(set_tiers_raw, dict)
            or not isinstance(remove_scopes_raw, list)
        ):
            self._send_json(400, {"error": "malformed_request"})
            return
        add_scopes: dict[str, str] = cast(dict[str, str], add_scopes_raw)
        remove_scopes: list[str] = cast(list[str], remove_scopes_raw)
        set_tiers: dict[str, str] = cast(dict[str, str], set_tiers_raw)

        if not add_scopes and not remove_scopes and not set_tiers:
            self._send_json(400, {"error": "no_modifications"})
            return
        invalid_tiers = {k: v for k, v in add_scopes.items() if v not in VALID_TIERS}
        invalid_tiers.update({k: v for k, v in set_tiers.items() if v not in VALID_TIERS})
        if invalid_tiers:
            self._send_json(400, {"error": "invalid_tier", "detail": invalid_tiers})
            return

        store: TokenStore = self._server.store
        audit: AuditLogger = self._server.audit

        family = self._get_active_family(store, family_id)
        if family is None:
            return

        scopes = dict(family["scopes"])
        for name, tier in add_scopes.items():
            scopes[name] = tier
        for name in remove_scopes:
            scopes.pop(name, None)
        for name, tier in set_tiers.items():
            if name in scopes:
                scopes[name] = tier

        store.update_family_scopes(family_id, scopes)
        audit.log_token_operation("scopes_modified", family_id=family_id, scopes=scopes)

        self._send_json(200, {"family_id": family_id, "scopes": scopes})

    def _handle_token_revoke(self) -> None:
        if not self._require_management_auth():
            return
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "malformed_request"})
            return
        family_id = data.get("family_id")
        if not isinstance(family_id, str) or not family_id:
            self._send_json(400, {"error": "malformed_request"})
            return

        store: TokenStore = self._server.store
        audit: AuditLogger = self._server.audit

        family = store.get_family(family_id)
        if family is None:
            self._send_json(404, {"error": "family_not_found"})
            return

        store.mark_family_revoked(family_id)
        audit.log_token_operation("token_revoked", family_id=family_id)

        self._send_json(200, {"family_id": family_id, "revoked": True})

    def _handle_token_rotate(self) -> None:
        if not self._require_management_auth():
            return
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "malformed_request"})
            return
        old_family_id = data.get("family_id")
        if not isinstance(old_family_id, str) or not old_family_id:
            self._send_json(400, {"error": "malformed_request"})
            return

        store: TokenStore = self._server.store
        signing_key: SigningKey = self._server.signing_key
        config: Config = self._server.config
        audit: AuditLogger = self._server.audit

        old_family = self._get_active_family(store, old_family_id)
        if old_family is None:
            return

        scopes = old_family["scopes"]
        new_family_id = generate_token_id()
        store.create_family(new_family_id, scopes)
        access_token, refresh_token = create_token_pair(signing_key, store, new_family_id, config)
        store.mark_family_revoked(old_family_id)

        audit.log_token_operation(
            "token_rotated",
            old_family_id=old_family_id,
            new_family_id=new_family_id,
            scopes=scopes,
        )

        self._send_json(
            200,
            {
                "old_family_id": old_family_id,
                "new_family_id": new_family_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "scopes": scopes,
                "expires_in": config.access_token_ttl_seconds,
            },
        )

    HEALTH_SCOPE = "agent-auth:health"

    def _handle_health(self) -> None:
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_json(401, {"error": "missing_token"})
            return

        token_raw = auth_header[7:]
        store: TokenStore = self._server.store
        signing_key: SigningKey = self._server.signing_key

        try:
            prefix, token_id = verify_token(token_raw, signing_key)
        except TokenInvalidError:
            self._send_json(401, {"error": "invalid_token"})
            return
        if prefix != PREFIX_ACCESS:
            self._send_json(401, {"error": "invalid_token"})
            return

        token_record = store.get_token(token_id)
        if token_record is None:
            self._send_json(401, {"error": "invalid_token"})
            return

        family = store.get_family(token_record["family_id"])
        if family is None or family["revoked"]:
            self._send_json(401, {"error": "invalid_token"})
            return

        now = datetime.now(UTC)
        expires_at = datetime.fromisoformat(token_record["expires_at"])
        if now >= expires_at:
            self._send_json(401, {"error": "token_expired"})
            return

        try:
            check_scope(self.HEALTH_SCOPE, family["scopes"])
        except ScopeDeniedError:
            self._send_json(403, {"error": "scope_denied"})
            return

        try:
            store.ping()
        except Exception:
            self._send_json(503, {"status": "unhealthy"})
            return
        self._send_json(200, {"status": "ok"})

    def _handle_status(self) -> None:
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_json(401, {"error": "missing_token"})
            return

        token_raw = auth_header[7:]
        store: TokenStore = self._server.store
        signing_key: SigningKey = self._server.signing_key

        try:
            _prefix, token_id = verify_token(token_raw, signing_key)
        except TokenInvalidError:
            self._send_json(401, {"error": "invalid_token"})
            return

        token_record = store.get_token(token_id)
        if token_record is None:
            self._send_json(401, {"error": "invalid_token"})
            return

        family = store.get_family(token_record["family_id"])
        if family is None:
            self._send_json(401, {"error": "invalid_token"})
            return

        now = datetime.now(UTC)
        expires_at = datetime.fromisoformat(token_record["expires_at"])
        expires_in = max(0, int((expires_at - now).total_seconds()))

        self._send_json(
            200,
            {
                "token_id": token_id,
                "family_id": token_record["family_id"],
                "type": token_record["type"],
                "scopes": family["scopes"],
                "revoked": family["revoked"],
                "expires_at": token_record["expires_at"],
                "expires_in": expires_in,
            },
        )


class AgentAuthServer(ThreadingHTTPServer):
    """Threaded HTTP server with shared state for agent-auth."""

    # Non-daemon request threads combined with ``block_on_close=True``
    # (inherited default from ``ThreadingMixIn``) let ``server_close``
    # wait for in-flight requests to complete during graceful shutdown.
    # The shutdown watchdog in ``run_server`` bounds the wait.
    daemon_threads = False

    def __init__(
        self,
        config: Config,
        signing_key: SigningKey,
        store: TokenStore,
        audit: AuditLogger,
        approval_manager: ApprovalManager,
    ):
        self.config = config
        self.signing_key = signing_key
        self.store = store
        self.audit = audit
        self.approval_manager = approval_manager
        super().__init__((config.host, config.port), AgentAuthHandler)


def _bootstrap_management_token(
    store: TokenStore,
    signing_key: SigningKey,
    config: Config,
    key_manager: KeyManager,
) -> None:
    """Create the management token family on first startup if one does not already exist."""
    existing_refresh = key_manager.get_management_refresh_token()
    if existing_refresh is not None:
        try:
            _prefix, token_id = verify_token(existing_refresh, signing_key)
        except TokenInvalidError:
            # Signing key was rotated (or the keyring entry is corrupt); fall
            # through to regenerate. DB errors below intentionally propagate.
            pass
        else:
            token_record = store.get_token(token_id)
            if token_record is not None:
                family = store.get_family(token_record["family_id"])
                if family is not None and not family["revoked"]:
                    return

    family_id = generate_token_id()
    store.create_family(family_id, {MANAGEMENT_SCOPE: "allow"})
    _access_token, refresh_token = create_token_pair(signing_key, store, family_id, config)
    key_manager.set_management_refresh_token(refresh_token)


def _install_shutdown_handler(
    server: ThreadingHTTPServer,
    deadline_seconds: float,
    service_name: str = "agent-auth",
) -> threading.Event:
    """Install SIGTERM / SIGINT handlers that bound the full shutdown.

    On first signal, spawns two daemon threads: one calls
    ``server.shutdown()`` to kick ``serve_forever`` out of its loop
    (this must not run on the ``serve_forever`` thread or the call
    deadlocks), and a watchdog that ``os._exit(1)``s if
    ``deadline_seconds`` elapses without the returned ``drain_complete``
    event being set.

    The caller is responsible for setting ``drain_complete`` once
    *every* post-shutdown cleanup step has returned —
    ``server.server_close()`` (which with non-daemon request threads
    blocks on ``_threads.join_all``) and any resource close. The
    watchdog therefore spans the full drain, not just the
    ``serve_forever`` unwind: a request handler hung inside
    ``server_close`` cannot hold the process past its container's
    ``stop_grace_period``.
    """
    shutdown_started = threading.Event()
    drain_complete = threading.Event()

    def _watchdog() -> None:
        if drain_complete.wait(timeout=deadline_seconds):
            return
        print(
            f"{service_name}: shutdown deadline of {deadline_seconds}s exceeded, force-exiting",
            file=sys.stderr,
            flush=True,
        )
        os._exit(1)

    def _handle(_signum: int, _frame: object) -> None:
        if shutdown_started.is_set():
            return
        shutdown_started.set()
        threading.Thread(target=_watchdog, daemon=True).start()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    return drain_complete


def run_server(
    config: Config,
    signing_key: SigningKey,
    store: TokenStore,
    audit: AuditLogger,
    key_manager: KeyManager,
) -> None:
    """Start the agent-auth HTTP server.

    Registers SIGTERM and SIGINT handlers that drain in-flight requests
    within ``config.shutdown_deadline_seconds`` before returning. On
    drain completion the token store's WAL is checkpointed so the next
    process start does not replay journalled writes.
    """
    _bootstrap_management_token(store, signing_key, config, key_manager)
    plugin = load_plugin(config.notification_plugin, config.notification_plugin_config)
    approval_manager = ApprovalManager(plugin, store, audit)
    server = AgentAuthServer(config, signing_key, store, audit, approval_manager)
    drain_complete = _install_shutdown_handler(server, config.shutdown_deadline_seconds)
    # Read the bound port from ``server_address`` (populated during
    # ``server_bind``) so a ``port: 0`` config surfaces the real port.
    bound_port = server.server_address[1]
    print(f"agent-auth server listening on {config.host}:{bound_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        try:
            server.server_close()
            store.close()
        finally:
            drain_complete.set()
