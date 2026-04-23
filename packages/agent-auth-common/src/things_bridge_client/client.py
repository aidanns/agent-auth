# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP client for the things-bridge service.

One method per public ``/things-bridge/*`` endpoint. The bearer token is
supplied per request — the client deliberately does not manage its own
credentials so it can be wrapped by the CLI's higher-level
refresh/reissue orchestrator without surprising state sharing.
"""

from __future__ import annotations

import json
import ssl
from http.client import HTTPConnection, HTTPSConnection
from typing import Any, cast
from urllib.parse import quote, urlencode, urlparse

from things_bridge_client.errors import (
    ThingsBridgeClientError,
    ThingsBridgeForbiddenError,
    ThingsBridgeNotFoundError,
    ThingsBridgeRateLimitedError,
    ThingsBridgeTokenExpiredError,
    ThingsBridgeUnauthorizedError,
    ThingsBridgeUnavailableError,
)
from things_models.models import AreaId, ProjectId, TodoId


class ThingsBridgeClient:
    """Typed client for the ``/things-bridge/*`` HTTP API.

    Stateless by design — a single instance may be shared across
    threads. The TLS context is built once at construction so a
    per-request CA-bundle reload does not charge every call.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30.0,
        ca_cert_path: str = "",
    ):
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"Invalid base_url: {base_url!r}")
        self._host = parsed.hostname
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._use_tls = parsed.scheme == "https"
        self._base_path = parsed.path.rstrip("/")
        self._timeout_seconds = timeout_seconds
        if self._use_tls:
            if ca_cert_path:
                self._ssl_context: ssl.SSLContext | None = ssl.create_default_context(
                    cafile=ca_cert_path
                )
            else:
                self._ssl_context = ssl.create_default_context()
        else:
            self._ssl_context = None

    # -- public API: one method per endpoint --

    def list_todos(
        self,
        access_token: str | None,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """GET ``/things-bridge/v1/todos``, optionally filtered by query params."""
        return self._get_json("/things-bridge/v1/todos", access_token, params=params)

    def get_todo(self, access_token: str | None, todo_id: TodoId) -> dict[str, Any]:
        """GET ``/things-bridge/v1/todos/{id}``."""
        return self._get_json(f"/things-bridge/v1/todos/{quote(todo_id, safe='')}", access_token)

    def list_projects(
        self,
        access_token: str | None,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """GET ``/things-bridge/v1/projects``, optionally filtered by query params."""
        return self._get_json("/things-bridge/v1/projects", access_token, params=params)

    def get_project(self, access_token: str | None, project_id: ProjectId) -> dict[str, Any]:
        """GET ``/things-bridge/v1/projects/{id}``."""
        return self._get_json(
            f"/things-bridge/v1/projects/{quote(project_id, safe='')}", access_token
        )

    def list_areas(self, access_token: str | None) -> dict[str, Any]:
        """GET ``/things-bridge/v1/areas``."""
        return self._get_json("/things-bridge/v1/areas", access_token)

    def get_area(self, access_token: str | None, area_id: AreaId) -> dict[str, Any]:
        """GET ``/things-bridge/v1/areas/{id}``."""
        return self._get_json(f"/things-bridge/v1/areas/{quote(area_id, safe='')}", access_token)

    def check_health(self, access_token: str | None) -> dict[str, Any]:
        """GET ``/things-bridge/health`` — returns 200 body on ok.

        Requires a token with ``things-bridge:health=allow``.
        """
        status, data, retry_after = self._request(
            "GET", "/things-bridge/health", bearer=access_token
        )
        if status == 200:
            return data
        _raise_bridge_error(status, data, retry_after)
        raise ThingsBridgeUnavailableError(
            f"Bridge health returned {status}: {data.get('error') or '<no body>'}"
        )

    def get_metrics_text(self, access_token: str | None) -> tuple[str, str]:
        """GET ``/things-bridge/metrics``.

        Returns ``(content_type, body)`` on 200. Requires a token with
        ``things-bridge:metrics=allow``.
        """
        status, content_type, body, retry_after = self._request_text(
            "GET", "/things-bridge/metrics", bearer=access_token
        )
        if status == 200:
            return content_type, body
        data = _parse_json_or_empty(body)
        _raise_bridge_error(status, data, retry_after)
        raise ThingsBridgeUnavailableError(
            f"Bridge metrics returned {status}: {data.get('error') or '<no body>'}"
        )

    # -- internal --

    def _get_json(
        self,
        path: str,
        access_token: str | None,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Issue a GET and enforce the ``dict`` response shape."""
        status, data, retry_after = self._request("GET", path, bearer=access_token, params=params)
        if 200 <= status < 300:
            if not data:
                # A 2xx with no body is never expected from the bridge;
                # surface it as a typed error rather than crashing
                # callers that expect a dict to ``.get()`` on.
                raise ThingsBridgeUnavailableError(
                    f"Bridge returned status {status} with empty body"
                )
            return data
        _raise_bridge_error(status, data, retry_after)
        raise ThingsBridgeUnavailableError(
            f"Bridge returned status {status}: {data.get('error') or '<no body>'}"
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        bearer: str | None = None,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any], str]:
        status, _content_type, raw, retry_after = self._request_text(
            method, path, bearer=bearer, body=body, params=params
        )
        return status, _parse_json_or_empty(raw), retry_after

    def _request_text(
        self,
        method: str,
        path: str,
        *,
        bearer: str | None = None,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> tuple[int, str, str, str]:
        full_path = self._base_path + path
        if params:
            full_path += "?" + urlencode(params)

        headers: dict[str, str] = {"Accept": "application/json"}
        request_body: bytes | None = None
        if body is not None:
            request_body = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(request_body))
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer}"

        conn: HTTPConnection
        if self._use_tls:
            conn = HTTPSConnection(
                self._host,
                self._port,
                timeout=self._timeout_seconds,
                context=self._ssl_context,
            )
        else:
            conn = HTTPConnection(self._host, self._port, timeout=self._timeout_seconds)
        try:
            try:
                conn.request(method, full_path, body=request_body, headers=headers)
                response = conn.getresponse()
                raw = response.read()
                status = response.status
                content_type = response.getheader("Content-Type") or ""
                retry_after = response.getheader("Retry-After") or ""
            except (ConnectionError, TimeoutError, OSError) as exc:
                raise ThingsBridgeUnavailableError(f"Bridge connection failed: {exc}") from exc
        finally:
            conn.close()
        return status, content_type, raw.decode("utf-8", errors="replace"), retry_after


def _parse_json_or_empty(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return cast(dict[str, Any], parsed)
    return {}


def _parse_retry_after(raw: str) -> int:
    if not raw:
        return 1
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _raise_bridge_error(status: int, data: dict[str, Any], retry_after: str) -> None:
    """Map common bridge error status codes to typed exceptions.

    Raises :class:`ThingsBridgeClientError` subclasses for 401 / 403 /
    404 / 429. Returns normally for any other status — the caller
    raises :class:`ThingsBridgeUnavailableError` with additional context
    (the status code, the specific endpoint) which this helper does not
    have.
    """
    error_code = str(data.get("error") or "")
    if status == 401:
        if error_code == "token_expired":
            raise ThingsBridgeTokenExpiredError(error_code)
        raise ThingsBridgeUnauthorizedError(error_code or "unauthorized")
    if status == 403:
        raise ThingsBridgeForbiddenError(error_code or "forbidden")
    if status == 404:
        raise ThingsBridgeNotFoundError(error_code or "not_found")
    if status == 429:
        raise ThingsBridgeRateLimitedError(
            error_code or "rate_limited",
            retry_after_seconds=_parse_retry_after(retry_after),
        )


__all__ = [
    "ThingsBridgeClient",
    "ThingsBridgeClientError",
]
