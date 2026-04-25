# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP server exposing GPG sign / verify operations.

Reads a bearer token, delegates validation to agent-auth (scope
``gpg:sign``), enforces the allowlist from :mod:`gpg_bridge.config`,
and shells out to the host ``gpg`` binary via
:class:`gpg_bridge.gpg_client.GpgSubprocessClient`. Per ADR 0033's
2026-04-25 amendment, the bridge invokes ``gpg`` directly rather
than going through a dedicated backend CLI.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import ssl
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from gpg_bridge.authz import AgentAuthClient
from gpg_bridge.config import Config
from gpg_bridge.errors import (
    AuthzRateLimitedError,
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzTokenInvalidError,
    AuthzUnavailableError,
    GpgBackendUnavailableError,
    GpgBadSignatureError,
    GpgError,
    GpgKeyNotAllowedError,
    GpgNoSuchKeyError,
    GpgPermissionError,
    GpgUnsupportedOperationError,
)
from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_bridge.metrics import GpgBridgeMetrics, build_registry
from gpg_models.models import SignRequest, VerifyRequest
from server_metrics import (
    PROMETHEUS_CONTENT_TYPE,
    Registry,
    render_prometheus_text,
)

SIGN_SCOPE = "gpg:sign"
HEALTH_SCOPE = "gpg-bridge:health"
METRICS_SCOPE = "gpg-bridge:metrics"

_UNKNOWN_ROUTE = "/unknown"
_HEALTH_BACKEND_CACHE_TTL_SECONDS = 30.0


class _HealthChecker:
    """Evaluate the bridge's gpg binary resolvability for /health."""

    def __init__(
        self,
        gpg_command: list[str],
        *,
        cache_ttl_seconds: float = _HEALTH_BACKEND_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        resolver: Callable[[str], str | None] = shutil.which,
    ):
        if not gpg_command:
            raise ValueError("_HealthChecker: gpg_command must not be empty")
        self._executable = gpg_command[0]
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
        self._resolver = resolver
        self._cached_at: float | None = None
        self._cached_resolvable: bool = False

    def backend_resolvable(self) -> bool:
        now = self._clock()
        if self._cached_at is not None and now - self._cached_at < self._cache_ttl_seconds:
            return self._cached_resolvable
        # Treat absolute or relative paths (containing '/') literally so a
        # ``python -m`` or ``[sys.executable, '-m', ...]`` config path works.
        if os.path.sep in self._executable or self._executable == sys.executable:
            self._cached_resolvable = os.path.exists(self._executable)
        else:
            self._cached_resolvable = self._resolver(self._executable) is not None
        self._cached_at = now
        return self._cached_resolvable


class GpgBridgeHandler(BaseHTTPRequestHandler):
    """HTTP request handler for gpg-bridge endpoints."""

    @property
    def _bridge(self) -> GpgBridgeServer:
        return self.server  # type: ignore[return-value]

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_429(self, retry_after_seconds: int) -> None:
        body = json.dumps({"error": "rate_limited"}).encode("utf-8")
        self.send_response(429)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Retry-After", str(retry_after_seconds))
        self.end_headers()
        self.wfile.write(body)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        # Request paths can appear in bearer-token-carrying headers; suppress
        # default access log the same way things-bridge does.
        pass

    def send_response(self, code: int, message: str | None = None) -> None:
        self._last_status_code = int(code)
        super().send_response(code, message)

    def _extract_bearer(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        return header[7:].strip() or None

    def _validate(self, token: str, scope: str, description: str) -> bool:
        try:
            self._bridge.authz.validate(token, scope, description=description)
            return True
        except AuthzTokenExpiredError:
            self._send_json(401, {"error": "token_expired"})
        except AuthzTokenInvalidError:
            self._send_json(401, {"error": "unauthorized"})
        except AuthzScopeDeniedError:
            self._send_json(403, {"error": "scope_denied"})
        except AuthzRateLimitedError as exc:
            self._send_429(exc.retry_after_seconds)
        except AuthzUnavailableError:
            self._send_json(502, {"error": "authz_unavailable"})
        return False

    def _send_gpg_error_response(self, exc: GpgError) -> None:
        if isinstance(exc, GpgNoSuchKeyError):
            self._send_json(404, {"error": "no_such_key"})
            return
        if isinstance(exc, GpgBadSignatureError):
            self._send_json(400, {"error": "bad_signature"})
            return
        if isinstance(exc, GpgBackendUnavailableError):
            # Wedged gpg subprocess (typically a misconfigured host
            # gpg-agent waiting on a non-existent pinentry). Surface
            # a directed detail so operators don't have to dig
            # through bridge logs to learn it's a host-side gpg
            # config issue. The detail string is the public API
            # surface that gpg-cli bubbles up to the user — keep the
            # wording stable.
            self._send_json(
                503,
                {
                    "error": "signing_backend_unavailable",
                    "detail": (
                        "host gpg-agent likely needs allow-loopback-pinentry "
                        "and a primed passphrase cache; see "
                        "docs/operations/gpg-bridge-host-setup.md"
                    ),
                },
            )
            return
        if isinstance(exc, GpgPermissionError):
            self._send_json(503, {"error": "gpg_permission_denied"})
            return
        if isinstance(exc, GpgUnsupportedOperationError):
            self._send_json(400, {"error": "unsupported_operation"})
            return
        self._send_json(502, {"error": "gpg_unavailable"})

    def _read_request_body(self) -> dict[str, Any] | None:
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            self._send_json(411, {"error": "length_required"})
            return None
        try:
            length = int(length_header)
        except ValueError:
            self._send_json(400, {"error": "invalid_content_length"})
            return None
        if length < 0:
            self._send_json(400, {"error": "invalid_content_length"})
            return None
        if length > self._bridge.config.max_request_bytes:
            self._send_json(413, {"error": "payload_too_large"})
            return None
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid_json"})
            return None
        if not isinstance(parsed, dict):
            self._send_json(400, {"error": "invalid_json"})
            return None
        return cast(dict[str, Any], parsed)

    def _handle_metrics(self) -> None:
        token = self._extract_bearer()
        if token is None:
            self._send_json(401, {"error": "unauthorized"})
            return
        if not self._validate(token, METRICS_SCOPE, "gpg-bridge metrics scrape"):
            return
        registry: Registry = self._bridge.registry
        body = render_prometheus_text(registry).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", PROMETHEUS_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        metrics = self._bridge.metrics
        metrics.http_active_requests.inc(method="GET")
        start = time.perf_counter()
        self._route_template = _UNKNOWN_ROUTE
        try:
            self._dispatch_get()
        finally:
            duration = time.perf_counter() - start
            metrics.http_active_requests.dec(method="GET")
            status_code = str(getattr(self, "_last_status_code", 0))
            metrics.http_request_duration.observe(
                duration,
                method="GET",
                route=self._route_template,
                status_code=status_code,
            )

    def _dispatch_get(self) -> None:
        path = self.path.split("?", 1)[0]
        token = self._extract_bearer()
        if token is None:
            self._send_json(401, {"error": "unauthorized"})
            return

        if path == "/gpg-bridge/health":
            self._route_template = path
            if not self._validate(token, HEALTH_SCOPE, "gpg-bridge health check"):
                return
            if not self._bridge.health_checker.backend_resolvable():
                self._send_json(503, {"status": "unhealthy"})
                return
            self._send_json(200, {"status": "ok"})
            return

        if path == "/gpg-bridge/metrics":
            self._route_template = path
            self._handle_metrics()
            return

        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        metrics = self._bridge.metrics
        metrics.http_active_requests.inc(method="POST")
        start = time.perf_counter()
        self._route_template = _UNKNOWN_ROUTE
        try:
            self._dispatch_post()
        finally:
            duration = time.perf_counter() - start
            metrics.http_active_requests.dec(method="POST")
            status_code = str(getattr(self, "_last_status_code", 0))
            metrics.http_request_duration.observe(
                duration,
                method="POST",
                route=self._route_template,
                status_code=status_code,
            )

    def _dispatch_post(self) -> None:
        path = self.path.split("?", 1)[0]
        token = self._extract_bearer()
        if token is None:
            self._send_json(401, {"error": "unauthorized"})
            return

        if path == "/gpg-bridge/v1/sign":
            self._route_template = path
            self._handle_sign(token)
            return
        if path == "/gpg-bridge/v1/verify":
            self._route_template = path
            self._handle_verify(token)
            return

        self._send_json(404, {"error": "not_found"})

    def _handle_sign(self, token: str) -> None:
        body = self._read_request_body()
        if body is None:
            return
        try:
            request = SignRequest.from_json(body)
        except ValueError as exc:
            self._send_json(400, {"error": "invalid_request", "detail": str(exc)})
            return
        if not self._bridge.config.key_allowed(request.local_user):
            self._send_json(403, {"error": "key_not_allowed"})
            return
        if not self._validate(token, SIGN_SCOPE, f"gpg-bridge sign with {request.local_user}"):
            return
        try:
            result = self._bridge.gpg.sign(request)
        except GpgKeyNotAllowedError:
            self._send_json(403, {"error": "key_not_allowed"})
            return
        except GpgError as exc:
            self._send_gpg_error_response(exc)
            return
        self._send_json(200, result.to_json())

    def _handle_verify(self, token: str) -> None:
        body = self._read_request_body()
        if body is None:
            return
        try:
            request = VerifyRequest.from_json(body)
        except ValueError as exc:
            self._send_json(400, {"error": "invalid_request", "detail": str(exc)})
            return
        if not self._validate(token, SIGN_SCOPE, "gpg-bridge verify"):
            return
        try:
            result = self._bridge.gpg.verify(request)
        except GpgError as exc:
            self._send_gpg_error_response(exc)
            return
        self._send_json(200, result.to_json())

    def _method_not_allowed(self) -> None:
        self._route_template = _UNKNOWN_ROUTE
        self.send_response(405)
        self.send_header("Allow", "GET, POST")
        body = json.dumps({"error": "method_not_allowed"}).encode("utf-8")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_HEAD = _method_not_allowed
    do_OPTIONS = _method_not_allowed


def _build_tls_context(cert_path: str, key_path: str) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    return context


class GpgBridgeServer(ThreadingHTTPServer):
    """Threaded HTTP server with shared state for gpg-bridge."""

    daemon_threads = False

    def __init__(
        self,
        config: Config,
        gpg: GpgSubprocessClient,
        authz: AgentAuthClient,
        registry: Registry,
        metrics: GpgBridgeMetrics,
        health_checker: _HealthChecker | None = None,
    ):
        self.config = config
        self.gpg = gpg
        self.authz = authz
        self.registry = registry
        self.metrics = metrics
        self.health_checker = health_checker or _HealthChecker(config.gpg_command)
        super().__init__((config.host, config.port), GpgBridgeHandler)
        if config.tls_enabled:
            self.socket = _build_tls_context(config.tls_cert_path, config.tls_key_path).wrap_socket(
                self.socket, server_side=True
            )


def _install_shutdown_handler(
    server: ThreadingHTTPServer,
    deadline_seconds: float,
    service_name: str = "gpg-bridge",
) -> threading.Event:
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


def run_server(config: Config, gpg: GpgSubprocessClient, authz: AgentAuthClient) -> None:
    """Start the gpg-bridge HTTP server."""
    registry, metrics = build_registry()
    server = GpgBridgeServer(config, gpg, authz, registry, metrics)
    drain_complete = _install_shutdown_handler(server, config.shutdown_deadline_seconds)
    bound_port = server.server_address[1]
    scheme = "https" if config.tls_enabled else "http"
    print(f"gpg-bridge listening on {scheme}://{config.host}:{bound_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        try:
            server.server_close()
        finally:
            drain_complete.set()


__all__ = [
    "GpgBridgeHandler",
    "GpgBridgeServer",
    "HEALTH_SCOPE",
    "METRICS_SCOPE",
    "SIGN_SCOPE",
    "run_server",
]
