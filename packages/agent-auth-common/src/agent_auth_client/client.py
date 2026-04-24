# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP client for the agent-auth service.

One method per public ``/agent-auth/*`` endpoint. Non-2xx responses are
mapped to the typed errors in :mod:`agent_auth_client.errors`; callers
never need to inspect raw status codes.
"""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
from typing import Any, cast
from urllib.parse import urlparse

from agent_auth_client.errors import (
    AuthzRateLimitedError,
    AuthzScopeDeniedError,
    AuthzTokenExpiredError,
    AuthzTokenInvalidError,
    AuthzUnavailableError,
    FamilyNotFoundError,
    FamilyRevokedError,
    MalformedRequestError,
    RefreshTokenExpiredError,
    RefreshTokenReuseDetectedError,
    ReissueDeniedError,
)


@dataclass(frozen=True)
class TokenPair:
    """Newly-minted access/refresh token pair returned by create/rotate."""

    family_id: str
    access_token: str
    refresh_token: str
    scopes: dict[str, str]
    expires_in_seconds: int


@dataclass(frozen=True)
class RefreshedTokens:
    """Access/refresh token pair returned by ``POST /token/refresh``.

    ``family_id`` is not echoed by the endpoint; callers tracking family
    identity across refreshes store it client-side.
    """

    access_token: str
    refresh_token: str
    scopes: dict[str, str]
    expires_in_seconds: int


@dataclass(frozen=True)
class ReissuedTokens:
    """Access/refresh token pair returned by ``POST /token/reissue``."""

    access_token: str
    refresh_token: str
    scopes: dict[str, str]
    expires_in_seconds: int


@dataclass(frozen=True)
class TokenStatus:
    """Introspection result for ``GET /token/status``."""

    token_id: str
    family_id: str
    token_type: str
    scopes: dict[str, str]
    revoked: bool
    expires_at: str
    expires_in_seconds: int


@dataclass(frozen=True)
class TokenFamilySummary:
    """Summary of a token family returned by ``GET /token/list``."""

    id: str
    scopes: dict[str, str]
    revoked: bool
    created_at: str
    raw: dict[str, Any]


class AgentAuthClient:
    """Typed client for the agent-auth HTTP API.

    One method per endpoint. Non-2xx responses are mapped to the typed
    errors in :mod:`agent_auth_client.errors`.

    The client is stateless: a single instance may be shared across
    threads, so the TLS context is built once at construction and reused
    for every request.
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
        # Build the SSL context once per client and reuse it — loading a
        # CA bundle per request would needlessly charge the validation
        # hot path that gates every bridge request. A configured
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

    # -- public API: one method per endpoint --

    def validate(
        self,
        token: str,
        required_scope: str,
        *,
        description: str | None = None,
    ) -> None:
        """Validate ``token`` carries ``required_scope``.

        Returns normally on success. Raises the appropriate
        :class:`AuthzError` subclass otherwise.
        """
        payload: dict[str, Any] = {"token": token, "required_scope": required_scope}
        if description is not None:
            payload["description"] = description
        status, data, retry_after = self._request("POST", "/agent-auth/v1/validate", body=payload)
        if status == 200 and data.get("valid") is True:
            return
        error_code = str(data.get("error") or "")
        if status == 401:
            if error_code == "token_expired":
                raise AuthzTokenExpiredError(error_code)
            raise AuthzTokenInvalidError(error_code or "invalid_token")
        if status == 403:
            raise AuthzScopeDeniedError(error_code or "scope_denied")
        if status == 429:
            raise AuthzRateLimitedError(
                error_code or "rate_limited",
                retry_after_seconds=_parse_retry_after(retry_after),
            )
        raise AuthzUnavailableError(
            f"unexpected agent-auth response {status}: {error_code or '<no body>'}"
        )

    def refresh(self, refresh_token: str) -> RefreshedTokens:
        """Exchange ``refresh_token`` for a new access/refresh pair."""
        status, data, retry_after = self._request(
            "POST",
            "/agent-auth/v1/token/refresh",
            body={"refresh_token": refresh_token},
        )
        if status == 200:
            return RefreshedTokens(
                access_token=str(data["access_token"]),
                refresh_token=str(data["refresh_token"]),
                scopes=cast(dict[str, str], data.get("scopes") or {}),
                expires_in_seconds=int(data["expires_in"]),
            )
        error_code = str(data.get("error") or "")
        if status == 429:
            raise AuthzRateLimitedError(
                error_code or "rate_limited",
                retry_after_seconds=_parse_retry_after(retry_after),
            )
        if status == 400:
            raise MalformedRequestError(error_code or "malformed_request")
        if status in (401, 403):
            if error_code == "refresh_token_expired":
                raise RefreshTokenExpiredError(error_code)
            if error_code == "refresh_token_reuse_detected":
                raise RefreshTokenReuseDetectedError(error_code)
            if error_code == "family_revoked":
                raise FamilyRevokedError(error_code)
            if status == 401:
                raise AuthzTokenInvalidError(error_code or "invalid_token")
            raise AuthzScopeDeniedError(error_code or "scope_denied")
        raise AuthzUnavailableError(f"Token refresh failed ({status}): {error_code or '<no body>'}")

    def reissue(self, family_id: str) -> ReissuedTokens:
        """Reissue a token family whose refresh token has expired."""
        status, data, retry_after = self._request(
            "POST",
            "/agent-auth/v1/token/reissue",
            body={"family_id": family_id},
        )
        if status == 200:
            return ReissuedTokens(
                access_token=str(data["access_token"]),
                refresh_token=str(data["refresh_token"]),
                scopes=cast(dict[str, str], data.get("scopes") or {}),
                expires_in_seconds=int(data["expires_in"]),
            )
        error_code = str(data.get("error") or "")
        if status == 429:
            raise AuthzRateLimitedError(
                error_code or "rate_limited",
                retry_after_seconds=_parse_retry_after(retry_after),
            )
        if status == 400:
            raise MalformedRequestError(error_code or "malformed_request")
        if status in (401, 403):
            if error_code == "reissue_denied":
                raise ReissueDeniedError(error_code)
            if error_code == "family_revoked":
                raise FamilyRevokedError(error_code)
            if status == 401:
                raise AuthzTokenInvalidError(error_code or "invalid_token")
            raise AuthzScopeDeniedError(error_code or "scope_denied")
        raise AuthzUnavailableError(f"Token reissue failed ({status}): {error_code or '<no body>'}")

    def get_status(self, access_token: str | None) -> TokenStatus:
        """Return introspection metadata for ``access_token``.

        ``None`` sends no Authorization header; useful for tests that
        assert the endpoint rejects anonymous callers.
        """
        status, data, retry_after = self._request(
            "GET",
            "/agent-auth/v1/token/status",
            bearer=access_token,
        )
        if status == 200:
            return TokenStatus(
                token_id=str(data["token_id"]),
                family_id=str(data["family_id"]),
                token_type=str(data["type"]),
                scopes=cast(dict[str, str], data.get("scopes") or {}),
                revoked=bool(data.get("revoked", False)),
                expires_at=str(data["expires_at"]),
                expires_in_seconds=int(data["expires_in"]),
            )
        _raise_unauthenticated(status, data, retry_after)
        raise AuthzUnavailableError(
            f"token status failed ({status}): {data.get('error') or '<no body>'}"
        )

    def check_health(self, access_token: str | None) -> dict[str, Any]:
        """GET ``/agent-auth/health`` with ``access_token``.

        Returns the health JSON body on 200, otherwise raises the
        appropriate error. Requires a token carrying
        ``agent-auth:health=allow``; passing ``None`` sends no bearer
        header so tests can assert the anonymous-rejection path.
        """
        status, data, retry_after = self._request("GET", "/agent-auth/health", bearer=access_token)
        if status == 200:
            return data
        _raise_unauthenticated(status, data, retry_after)
        if status == 503:
            raise AuthzUnavailableError(
                f"agent-auth reported unhealthy: {data.get('status') or '<no body>'}"
            )
        raise AuthzUnavailableError(
            f"agent-auth health returned {status}: {data.get('error') or '<no body>'}"
        )

    def get_metrics_text(self, access_token: str | None) -> tuple[str, str]:
        """GET ``/agent-auth/metrics`` with ``access_token``.

        Returns ``(content_type, body)`` on 200. Requires a token
        carrying ``agent-auth:metrics=allow``; passing ``None`` sends no
        bearer header. Caller inspects the body as Prometheus text; the
        client deliberately does not parse it.
        """
        status, content_type, body, retry_after = self._request_text(
            "GET", "/agent-auth/metrics", bearer=access_token
        )
        if status == 200:
            return content_type, body
        data = _parse_json_or_empty(body)
        _raise_unauthenticated(status, data, retry_after)
        raise AuthzUnavailableError(
            f"agent-auth metrics returned {status}: {data.get('error') or '<no body>'}"
        )

    # -- management endpoints (require agent-auth:manage bearer token) --

    def create_token(self, scopes: dict[str, str], *, management_token: str | None) -> TokenPair:
        status, data, retry_after = self._request(
            "POST",
            "/agent-auth/v1/token/create",
            body={"scopes": scopes},
            bearer=management_token,
        )
        if status == 200:
            return TokenPair(
                family_id=str(data["family_id"]),
                access_token=str(data["access_token"]),
                refresh_token=str(data["refresh_token"]),
                scopes=cast(dict[str, str], data.get("scopes") or {}),
                expires_in_seconds=int(data["expires_in"]),
            )
        _raise_unauthenticated(status, data, retry_after)
        if status == 400:
            raise MalformedRequestError(str(data.get("error") or "malformed_request"))
        raise AuthzUnavailableError(
            f"token create failed ({status}): {data.get('error') or '<no body>'}"
        )

    def list_tokens(self, *, management_token: str | None) -> list[TokenFamilySummary]:
        status, payload, retry_after = self._request_list(
            "GET", "/agent-auth/v1/token/list", bearer=management_token
        )
        if status == 200:
            return [
                TokenFamilySummary(
                    id=str(f["id"]),
                    scopes=cast(dict[str, str], f.get("scopes") or {}),
                    revoked=bool(f.get("revoked", False)),
                    created_at=str(f.get("created_at", "")),
                    raw=f,
                )
                for f in payload
            ]
        # ``/token/list`` failures still surface a dict-shaped error body;
        # ``_request_list`` wraps the error dict in a singleton list so a
        # non-2xx response has ``payload[0]`` typed as the same
        # ``dict[str, Any]`` the error mapper expects.
        data: dict[str, Any] = payload[0] if payload else {}
        _raise_unauthenticated(status, data, retry_after)
        raise AuthzUnavailableError(
            f"token list failed ({status}): {data.get('error') or '<no body>'}"
        )

    def modify_token(
        self,
        family_id: str,
        *,
        management_token: str | None,
        add_scopes: dict[str, str] | None = None,
        remove_scopes: list[str] | None = None,
        set_tiers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"family_id": family_id}
        if add_scopes is not None:
            body["add_scopes"] = add_scopes
        if remove_scopes is not None:
            body["remove_scopes"] = remove_scopes
        if set_tiers is not None:
            body["set_tiers"] = set_tiers
        status, data, retry_after = self._request(
            "POST",
            "/agent-auth/v1/token/modify",
            body=body,
            bearer=management_token,
        )
        if status == 200:
            return data
        _raise_unauthenticated(status, data, retry_after)
        if status == 404:
            raise FamilyNotFoundError(str(data.get("error") or "family_not_found"))
        if status == 409:
            raise FamilyRevokedError(str(data.get("error") or "family_revoked"))
        if status == 400:
            raise MalformedRequestError(str(data.get("error") or "malformed_request"))
        raise AuthzUnavailableError(
            f"token modify failed ({status}): {data.get('error') or '<no body>'}"
        )

    def revoke_token(self, family_id: str, *, management_token: str | None) -> dict[str, Any]:
        status, data, retry_after = self._request(
            "POST",
            "/agent-auth/v1/token/revoke",
            body={"family_id": family_id},
            bearer=management_token,
        )
        if status == 200:
            return data
        _raise_unauthenticated(status, data, retry_after)
        if status == 404:
            raise FamilyNotFoundError(str(data.get("error") or "family_not_found"))
        if status == 400:
            raise MalformedRequestError(str(data.get("error") or "malformed_request"))
        raise AuthzUnavailableError(
            f"token revoke failed ({status}): {data.get('error') or '<no body>'}"
        )

    def rotate_token(self, family_id: str, *, management_token: str | None) -> TokenPair:
        status, data, retry_after = self._request(
            "POST",
            "/agent-auth/v1/token/rotate",
            body={"family_id": family_id},
            bearer=management_token,
        )
        if status == 200:
            return TokenPair(
                family_id=str(data["new_family_id"]),
                access_token=str(data["access_token"]),
                refresh_token=str(data["refresh_token"]),
                scopes=cast(dict[str, str], data.get("scopes") or {}),
                expires_in_seconds=int(data["expires_in"]),
            )
        _raise_unauthenticated(status, data, retry_after)
        if status == 404:
            raise FamilyNotFoundError(str(data.get("error") or "family_not_found"))
        if status == 409:
            raise FamilyRevokedError(str(data.get("error") or "family_revoked"))
        if status == 400:
            raise MalformedRequestError(str(data.get("error") or "malformed_request"))
        raise AuthzUnavailableError(
            f"token rotate failed ({status}): {data.get('error') or '<no body>'}"
        )

    # -- internal HTTP plumbing --

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        bearer: str | None = None,
    ) -> tuple[int, dict[str, Any], str]:
        """Issue an HTTP request expecting a JSON object or empty body."""
        status, _content_type, raw, retry_after = self._request_text(
            method, path, body=body, bearer=bearer
        )
        return status, _parse_json_or_empty(raw), retry_after

    def _request_list(
        self,
        method: str,
        path: str,
        *,
        bearer: str | None = None,
    ) -> tuple[int, list[dict[str, Any]], str]:
        """Issue an HTTP request expecting a JSON list on success."""
        status, _content_type, raw, retry_after = self._request_text(method, path, bearer=bearer)
        if not raw:
            return status, [], retry_after
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthzUnavailableError(
                f"agent-auth returned non-JSON response (status {status})"
            ) from exc
        if isinstance(parsed, list):
            return status, cast(list[dict[str, Any]], parsed), retry_after
        if isinstance(parsed, dict):
            # ``/token/list`` returns a list on success; error bodies
            # are dicts. Surface the dict wrapped in a singleton so the
            # caller's error path has access to ``error``.
            return status, [cast(dict[str, Any], parsed)], retry_after
        raise AuthzUnavailableError(f"agent-auth returned unexpected JSON shape for {path}")

    def _request_text(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        bearer: str | None = None,
    ) -> tuple[int, str, str, str]:
        """Issue an HTTP request and return ``(status, content_type, body, retry_after)``.

        Wraps all ``http.client`` and socket-level exceptions in
        :class:`AuthzUnavailableError` so callers never see a raw
        ``OSError`` / ``ConnectionError``.
        """
        full_path = self._base_path + path
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
                raise AuthzUnavailableError(f"agent-auth unreachable: {exc}") from exc
        finally:
            conn.close()
        return status, content_type, raw.decode("utf-8", errors="replace"), retry_after


def _parse_retry_after(raw: str) -> int:
    """Parse a ``Retry-After`` header as integer seconds.

    Falls back to 1 on missing / malformed values. RFC 7231 §7.1.3
    allows HTTP-date too; agent-auth only emits integer seconds, so
    callers that hit a date value still get the conservative 1 s
    fallback instead of crashing.
    """
    if not raw:
        return 1
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _parse_json_or_empty(raw: str) -> dict[str, Any]:
    """Parse ``raw`` as a JSON object; empty / non-dict → ``{}``.

    The raw agent-auth handlers return either a JSON object on success
    or an ``{"error": ...}`` body on failure; anything else is a
    protocol violation, but returning an empty dict keeps the caller's
    error-mapping tables total.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return cast(dict[str, Any], parsed)
    return {}


def _raise_unauthenticated(status: int, data: dict[str, Any], retry_after: str) -> None:
    """Raise for 401 / 403 / 429 responses.

    Shared across get/post methods that authenticate with a bearer
    token. Returns normally if ``status`` is not one of those; the
    caller is then responsible for mapping it.
    """
    error_code = str(data.get("error") or "")
    if status == 401:
        if error_code == "token_expired":
            raise AuthzTokenExpiredError(error_code)
        raise AuthzTokenInvalidError(error_code or "invalid_token")
    if status == 403:
        raise AuthzScopeDeniedError(error_code or "scope_denied")
    if status == 429:
        raise AuthzRateLimitedError(
            error_code or "rate_limited",
            retry_after_seconds=_parse_retry_after(retry_after),
        )
