# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP client for the things-bridge with automatic token refresh and re-issuance."""

import json
import ssl
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from things_cli.credentials import Credentials, CredentialStore
from things_cli.errors import (
    BridgeForbiddenError,
    BridgeNotFoundError,
    BridgeUnauthorizedError,
    BridgeUnavailableError,
)


class BridgeClient:
    """Makes authenticated requests to the things-bridge.

    Handles the token lifecycle automatically:

    1. Attaches ``Authorization: Bearer <access_token>`` from the credential store.
    2. On ``401 {"error": "token_expired"}`` calls ``/agent-auth/v1/token/refresh``,
       persists the new tokens, and retries the original request once.
    3. If the refresh token has itself expired (``401 refresh_token_expired``),
       calls ``/agent-auth/v1/token/reissue`` (which blocks on host-side JIT approval)
       and retries once.
    4. Any further 401 surfaces as :class:`BridgeUnauthorizedError`.
    """

    def __init__(
        self,
        credentials: Credentials,
        store: CredentialStore,
        *,
        timeout_seconds: float = 30.0,
        ca_cert_path: str = "",
    ):
        self._credentials = credentials
        self._store = store
        self._timeout = timeout_seconds
        # Pre-build the TLS context once; reused for every HTTPS call.
        # An explicit ``ca_cert_path`` means the operator trusts a
        # self-signed or private CA (typical for a devcontainer-host
        # deployment where the bridge and agent-auth serve TLS with a
        # locally-generated cert). Empty falls back to the system trust
        # store for public CAs or remains unused when every URL is
        # plaintext HTTP on loopback.
        if ca_cert_path:
            self._ssl_context: ssl.SSLContext | None = ssl.create_default_context(
                cafile=ca_cert_path
            )
        else:
            self._ssl_context = None

    @property
    def credentials(self) -> Credentials:
        return self._credentials

    # -- public API: one method per bridge endpoint --

    def list_todos(self, params: dict[str, str] | None = None) -> dict[str, Any]:
        """List todos from the bridge, optionally filtered by query params."""
        return self._request("GET", "/things-bridge/v1/todos", params=params)

    def get_todo(self, todo_id: str) -> dict[str, Any]:
        """Get a single todo by id."""
        return self._request("GET", f"/things-bridge/v1/todos/{quote(todo_id, safe='')}")

    def list_projects(self, params: dict[str, str] | None = None) -> dict[str, Any]:
        """List projects from the bridge, optionally filtered by query params."""
        return self._request("GET", "/things-bridge/v1/projects", params=params)

    def get_project(self, project_id: str) -> dict[str, Any]:
        """Get a single project by id."""
        return self._request("GET", f"/things-bridge/v1/projects/{quote(project_id, safe='')}")

    def list_areas(self) -> dict[str, Any]:
        """List areas from the bridge."""
        return self._request("GET", "/things-bridge/v1/areas")

    def get_area(self, area_id: str) -> dict[str, Any]:
        """Get a single area by id."""
        return self._request("GET", f"/things-bridge/v1/areas/{quote(area_id, safe='')}")

    # -- internal --

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        _already_retried: bool = False,
    ) -> dict[str, Any]:
        status, data = self._do_http(
            self._credentials.bridge_url,
            method,
            path,
            params=params,
            headers=self._bearer_headers(),
        )
        if 200 <= status < 300:
            if data is None:
                # A 2xx with no body is never expected from things-bridge; surface
                # it as a typed error rather than crashing callers that expect
                # a dict to `.get()` on.
                raise BridgeUnavailableError(f"Bridge returned status {status} with empty body")
            return data

        if status == 401 and not _already_retried:
            error = (data or {}).get("error", "")
            if error == "token_expired":
                self._refresh_access_token()
                return self._request(method, path, params=params, _already_retried=True)

        if status == 401:
            raise BridgeUnauthorizedError((data or {}).get("error") or "unauthorized")
        if status == 403:
            raise BridgeForbiddenError((data or {}).get("error") or "forbidden")
        if status == 404:
            raise BridgeNotFoundError((data or {}).get("error") or "not_found")
        raise BridgeUnavailableError(
            f"Bridge returned status {status}: {(data or {}).get('error') or '<no body>'}"
        )

    def _bearer_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._credentials.access_token}",
            "Accept": "application/json",
        }

    def _refresh_access_token(self) -> None:
        status, data = self._do_http(
            self._credentials.auth_url,
            "POST",
            "/agent-auth/v1/token/refresh",
            body={"refresh_token": self._credentials.refresh_token},
        )
        if status == 200 and data:
            self._credentials.access_token = data["access_token"]
            self._credentials.refresh_token = data["refresh_token"]
            self._store.save(self._credentials)
            return

        if status == 401 and (data or {}).get("error") == "refresh_token_expired":
            self._reissue_tokens()
            return

        error_code = (data or {}).get("error") or "refresh_failed"
        if status in (401, 403):
            raise BridgeUnauthorizedError(error_code)
        raise BridgeUnavailableError(f"Token refresh failed ({status}): {error_code}")

    def _reissue_tokens(self) -> None:
        if not self._credentials.family_id:
            raise BridgeUnauthorizedError(
                "refresh_token_expired and no family_id stored; run `things-cli login` again"
            )
        status, data = self._do_http(
            self._credentials.auth_url,
            "POST",
            "/agent-auth/v1/token/reissue",
            body={"family_id": self._credentials.family_id},
        )
        if status == 200 and data:
            self._credentials.access_token = data["access_token"]
            self._credentials.refresh_token = data["refresh_token"]
            self._store.save(self._credentials)
            return

        error_code = (data or {}).get("error") or "reissue_failed"
        if status in (401, 403):
            raise BridgeUnauthorizedError(error_code)
        raise BridgeUnavailableError(f"Token reissue failed ({status}): {error_code}")

    def _do_http(
        self,
        base_url: str,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any] | None]:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise BridgeUnavailableError(f"Invalid URL: {base_url!r}")
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        use_tls = parsed.scheme == "https"

        query = ""
        if params:
            query = "?" + urlencode(params)
        full_path = (parsed.path.rstrip("/") + path) + query

        request_body: bytes | None = None
        send_headers = dict(headers or {})
        if body is not None:
            request_body = json.dumps(body).encode("utf-8")
            send_headers.setdefault("Content-Type", "application/json")
            send_headers["Content-Length"] = str(len(request_body))

        conn: HTTPConnection
        if use_tls:
            conn = HTTPSConnection(host, port, timeout=self._timeout, context=self._ssl_context)
        else:
            conn = HTTPConnection(host, port, timeout=self._timeout)
        try:
            try:
                conn.request(method, full_path, body=request_body, headers=send_headers)
                response = conn.getresponse()
                raw = response.read()
                status = response.status
            except (ConnectionError, TimeoutError, OSError) as exc:
                raise BridgeUnavailableError(f"Connection to {base_url} failed: {exc}") from exc
        finally:
            conn.close()

        if not raw:
            return status, None
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BridgeUnavailableError(
                f"Non-JSON response from {base_url} (status {status})"
            ) from exc
