"""HTTP client for delegating token validation to agent-auth."""

import json
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlparse

from things_bridge.errors import (
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzTokenInvalidError,
    AuthzUnavailableError,
)


class AgentAuthClient:
    """Validates bearer tokens against agent-auth's ``/agent-auth/validate`` endpoint."""

    def __init__(self, auth_url: str, *, timeout_seconds: float = 30.0):
        parsed = urlparse(auth_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"Invalid auth_url: {auth_url!r}")
        self._host = parsed.hostname
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._conn_cls = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
        self._timeout = timeout_seconds

    def validate(self, token: str, required_scope: str, *, description: str | None = None) -> None:
        """Validate ``token`` carries ``required_scope``.

        Returns normally on success. Raises the appropriate ``Authz*Error`` otherwise.
        """
        payload: dict[str, str] = {"token": token, "required_scope": required_scope}
        if description is not None:
            payload["description"] = description
        body = json.dumps(payload).encode("utf-8")

        conn = self._conn_cls(self._host, self._port, timeout=self._timeout)
        try:
            try:
                conn.request(
                    "POST",
                    "/agent-auth/validate",
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
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise AuthzUnavailableError(
                f"agent-auth returned non-JSON response (status {response.status})"
            ) from exc

        if response.status == 200 and data.get("valid") is True:
            return

        error_code = data.get("error", "")
        if response.status == 401:
            if error_code == "token_expired":
                raise AuthzTokenExpiredError(error_code)
            raise AuthzTokenInvalidError(error_code or "invalid_token")
        if response.status == 403:
            raise AuthzScopeDeniedError(error_code or "scope_denied")
        raise AuthzUnavailableError(
            f"unexpected agent-auth response {response.status}: {error_code or '<no body>'}"
        )
