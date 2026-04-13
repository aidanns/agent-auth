"""HTTP server for agent-auth API."""

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent_auth.approval import ApprovalManager
from agent_auth.audit import AuditLogger
from agent_auth.config import Config
from agent_auth.errors import ScopeDeniedError, TokenInvalidError
from agent_auth.plugins import load_plugin
from agent_auth.scopes import check_scope
from agent_auth.store import TokenStore
from agent_auth.tokens import (
    PREFIX_ACCESS,
    PREFIX_REFRESH,
    create_token_pair,
    verify_token,
)


class AgentAuthHandler(BaseHTTPRequestHandler):
    """HTTP request handler for agent-auth API endpoints."""

    @property
    def _server(self):
        return self.server

    MAX_BODY_SIZE = 1_048_576  # 1 MiB

    def _read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > self.MAX_BODY_SIZE:
            return None
        body = self.rfile.read(length)
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path == "/agent-auth/validate":
            self._handle_validate()
        elif self.path == "/agent-auth/token/refresh":
            self._handle_refresh()
        elif self.path == "/agent-auth/token/reissue":
            self._handle_reissue()
        else:
            self._send_json(404, {"error": "not_found"})

    def do_GET(self):
        if self.path == "/agent-auth/token/status":
            self._handle_status()
        else:
            self._send_json(404, {"error": "not_found"})

    def _handle_validate(self):
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "malformed_request"})
            return
        token_raw = data.get("token", "")
        required_scope = data.get("required_scope", "")
        description = data.get("description")

        store: TokenStore = self._server.store
        signing_key: bytes = self._server.signing_key
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

        now = datetime.now(timezone.utc)
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
            result = approval_manager.request_approval(
                family["id"], required_scope, description
            )
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

    def _handle_refresh(self):
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "malformed_request"})
            return
        refresh_token_raw = data.get("refresh_token", "")

        store: TokenStore = self._server.store
        signing_key: bytes = self._server.signing_key
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

        now = datetime.now(timezone.utc)
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
            self._send_json(401, {
                "error": "refresh_token_reuse_detected",
                "detail": "Token family revoked",
            })
            return

        family_id = token_record["family_id"]
        access_token, new_refresh_token = create_token_pair(
            signing_key, store, family_id, config
        )

        audit.log_token_operation(
            "token_refreshed", family_id=family_id
        )

        self._send_json(200, {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "expires_in": config.access_token_ttl,
            "scopes": family["scopes"],
        })

    def _handle_reissue(self):
        data = self._read_json()
        if data is None:
            self._send_json(400, {"error": "malformed_request"})
            return
        family_id = data.get("family_id", "")

        store: TokenStore = self._server.store
        signing_key: bytes = self._server.signing_key
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
        now = datetime.now(timezone.utc)
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
            audit.log_token_operation(
                "reissue_denied", family_id=family_id
            )
            self._send_json(403, {"error": "reissue_denied"})
            return

        access_token, new_refresh_token = create_token_pair(
            signing_key, store, family_id, config
        )

        audit.log_token_operation(
            "token_reissued", family_id=family_id
        )

        self._send_json(200, {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "expires_in": config.access_token_ttl,
            "scopes": family["scopes"],
        })

    def _handle_status(self):
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_json(401, {"error": "missing_token"})
            return

        token_raw = auth_header[7:]
        store: TokenStore = self._server.store
        signing_key: bytes = self._server.signing_key

        try:
            prefix, token_id = verify_token(token_raw, signing_key)
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

        now = datetime.now(timezone.utc)
        expires_at = datetime.fromisoformat(token_record["expires_at"])
        expires_in = max(0, int((expires_at - now).total_seconds()))

        self._send_json(200, {
            "token_id": token_id,
            "family_id": token_record["family_id"],
            "type": token_record["type"],
            "scopes": family["scopes"],
            "revoked": family["revoked"],
            "expires_at": token_record["expires_at"],
            "expires_in": expires_in,
        })


class AgentAuthServer(ThreadingHTTPServer):
    """Threaded HTTP server with shared state for agent-auth."""

    def __init__(
        self,
        config: Config,
        signing_key: bytes,
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


def run_server(config: Config, signing_key: bytes, store: TokenStore, audit: AuditLogger):
    """Start the agent-auth HTTP server."""
    plugin = load_plugin(config.notification_plugin, config.notification_plugin_config)
    approval_manager = ApprovalManager(plugin, store, audit)
    server = AgentAuthServer(config, signing_key, store, audit, approval_manager)
    print(f"agent-auth server listening on {config.host}:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
