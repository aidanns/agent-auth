# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP client for delegating token validation to agent-auth."""

import json
import ssl
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlparse

from things_bridge.errors import (
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzTokenInvalidError,
    AuthzUnavailableError,
)


class AgentAuthClient:
    """Validates bearer tokens against agent-auth's ``/agent-auth/v1/validate`` endpoint."""

    def __init__(
        self,
        auth_url: str,
        *,
        timeout_seconds: float = 30.0,
        ca_cert_path: str = "",
    ):
        parsed = urlparse(auth_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"Invalid auth_url: {auth_url!r}")
        self._host = parsed.hostname
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._use_tls = parsed.scheme == "https"
        self._timeout = timeout_seconds
        # Build the SSL context once per client and reuse it — loading
        # a CA bundle is cheap but not free, and doing it per request
        # would needlessly charge the authz hot path. A configured
        # ``ca_cert_path`` means the operator runs agent-auth behind a
        # self-signed or private CA (typical for a devcontainer-host
        # deployment); an empty path falls back to the system trust
        # store.
        if self._use_tls:
            if ca_cert_path:
                self._ssl_context: ssl.SSLContext | None = ssl.create_default_context(
                    cafile=ca_cert_path
                )
            else:
                self._ssl_context = ssl.create_default_context()
        else:
            self._ssl_context = None

    def validate(self, token: str, required_scope: str, *, description: str | None = None) -> None:
        """Validate ``token`` carries ``required_scope``.

        Returns normally on success. Raises the appropriate ``Authz*Error`` otherwise.
        """
        payload: dict[str, str] = {"token": token, "required_scope": required_scope}
        if description is not None:
            payload["description"] = description
        body = json.dumps(payload).encode("utf-8")

        if self._use_tls:
            conn: HTTPConnection = HTTPSConnection(
                self._host, self._port, timeout=self._timeout, context=self._ssl_context
            )
        else:
            conn = HTTPConnection(self._host, self._port, timeout=self._timeout)
        try:
            try:
                conn.request(
                    "POST",
                    "/agent-auth/v1/validate",
                    body=body,
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body)),
                    },
                )
                response = conn.getresponse()
                raw = response.read()
            except (ConnectionError, TimeoutError, OSError) as exc:
                raise AuthzUnavailableError(f"agent-auth unreachable: {exc}") from exc
        finally:
            conn.close()

        try:
            data: dict[str, Any] = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise AuthzUnavailableError(
                f"agent-auth returned non-JSON response (status {response.status})"
            ) from exc

        if response.status == 200 and data.get("valid") is True:
            return

        error_code = str(data.get("error") or "")
        if response.status == 401:
            if error_code == "token_expired":
                raise AuthzTokenExpiredError(error_code)
            raise AuthzTokenInvalidError(error_code or "invalid_token")
        if response.status == 403:
            raise AuthzScopeDeniedError(error_code or "scope_denied")
        raise AuthzUnavailableError(
            f"unexpected agent-auth response {response.status}: {error_code or '<no body>'}"
        )
