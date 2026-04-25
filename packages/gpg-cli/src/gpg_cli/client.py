# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Authenticated bridge client with refresh + reissue retry.

Composes the raw HTTP wire calls to ``/gpg-bridge/v1/{sign,verify}``
with :class:`agent_auth_client.AgentAuthClient` so the public
:meth:`BridgeClient.sign` / :meth:`BridgeClient.verify` methods own
the credential lifecycle:

1. Attaches ``Authorization: Bearer <access_token>`` from
   :class:`gpg_cli.config.Credentials`.
2. On ``401 {"error": "token_expired"}`` the client calls
   ``POST /agent-auth/v1/token/refresh``, persists the new pair via
   :class:`gpg_cli.config.FileStore`, and retries the original request
   once.
3. If the refresh token has expired (``401 refresh_token_expired``),
   the client falls back to ``POST /agent-auth/v1/token/reissue``
   (which blocks on host-side JIT approval) and retries once.
4. Any further 401 surfaces as :class:`BridgeUnauthorizedError`.

The persistence ordering — write before retry — is the load-bearing
safety property from ADR 0011: refresh tokens are single-use, so a
crash between the refresh response and the retried request must not
leave a consumed refresh token on disk.
"""

from __future__ import annotations

import json
import ssl
from collections.abc import Callable
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlparse

from agent_auth_client import (
    AgentAuthClient,
    AuthzError,
    AuthzUnavailableError,
    RefreshTokenExpiredError,
)
from gpg_cli.config import Credentials, FileStore
from gpg_cli.errors import (
    BridgeBadSignatureError,
    BridgeForbiddenError,
    BridgeNotFoundError,
    BridgeRateLimitedError,
    BridgeTokenExpiredError,
    BridgeUnauthorizedError,
    BridgeUnavailableError,
)
from gpg_models.models import SignRequest, SignResult, VerifyRequest, VerifyResult


class BridgeClient:
    """Authenticated client for ``/gpg-bridge/v1/{sign,verify}`` endpoints.

    Each public method ``call`` runs through :meth:`_with_retry`, which
    catches :class:`BridgeTokenExpiredError`, refreshes the credential
    pair, and retries once. The single-retry budget mirrors the
    things-cli implementation and means a persistent 401 surfaces as
    :class:`BridgeUnauthorizedError` rather than spinning forever.
    """

    def __init__(
        self,
        credentials: Credentials,
        store: FileStore,
        *,
        bridge_url: str,
        timeout_seconds: float = 30.0,
        ca_cert_path: str = "",
    ):
        parsed = urlparse(bridge_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"Invalid bridge_url: {bridge_url!r}")
        self._host = parsed.hostname
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._use_tls = parsed.scheme == "https"
        self._timeout = timeout_seconds
        if self._use_tls:
            if ca_cert_path:
                self._ssl_context: ssl.SSLContext | None = ssl.create_default_context(
                    cafile=ca_cert_path
                )
            else:
                self._ssl_context = ssl.create_default_context()
        else:
            self._ssl_context = None

        self._credentials = credentials
        self._store = store
        self._auth = AgentAuthClient(
            credentials.auth_url,
            timeout_seconds=timeout_seconds,
            ca_cert_path=ca_cert_path,
        )

    @property
    def credentials(self) -> Credentials:
        return self._credentials

    # -- public API: one method per gpg-bridge endpoint --

    def sign(self, request: SignRequest) -> SignResult:
        return SignResult.from_json(
            self._with_retry(
                lambda token: self._post(token, "/gpg-bridge/v1/sign", request.to_json())
            )
        )

    def verify(self, request: VerifyRequest) -> VerifyResult:
        return VerifyResult.from_json(
            self._with_retry(
                lambda token: self._post(token, "/gpg-bridge/v1/verify", request.to_json())
            )
        )

    # -- internal: refresh / reissue retry loop --

    def _with_retry(self, call: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
        """Invoke ``call`` with the current access token; refresh once on 401 token_expired.

        Mirrors :meth:`things_cli.client.BridgeClient._with_retry` —
        single retry budget, with the new credential pair persisted
        *before* the retried call runs (see :meth:`_refresh_access_token`).
        """
        try:
            return call(self._credentials.access_token)
        except BridgeTokenExpiredError:
            pass
        self._refresh_access_token()
        # A second ``token_expired`` after a successful refresh shouldn't
        # happen in practice. Collapse it to a plain unauthorized so the
        # CLI maps it to exit 3 like any other post-retry 401, rather
        # than leaking the internal retry contract.
        try:
            return call(self._credentials.access_token)
        except BridgeTokenExpiredError as exc:
            raise BridgeUnauthorizedError(str(exc) or "token_expired") from exc

    def _refresh_access_token(self) -> None:
        """Exchange the stored refresh token, falling back to reissue on expiry.

        Persists the new pair *before* returning so a crash between the
        refresh response and the next retry attempt cannot leave a
        consumed (single-use) refresh token on disk — see ADR 0011.
        """
        try:
            refreshed = self._auth.refresh(self._credentials.refresh_token)
        except RefreshTokenExpiredError:
            self._reissue_tokens()
            return
        except AuthzUnavailableError as exc:
            raise BridgeUnavailableError(f"agent-auth refresh unavailable: {exc}") from exc
        except AuthzError as exc:
            # Reuse detected, family revoked, scope denied, or any
            # other refresh-side 4xx is terminal. Surface it with the
            # server-supplied error code so the operator sees the
            # specific reason to re-bootstrap.
            raise BridgeUnauthorizedError(str(exc)) from exc
        self._credentials.access_token = refreshed.access_token
        self._credentials.refresh_token = refreshed.refresh_token
        self._store.save(self._credentials)

    def _reissue_tokens(self) -> None:
        """Call the agent-auth reissue endpoint, then persist the new pair."""
        if not self._credentials.family_id:
            raise BridgeUnauthorizedError(
                "refresh_token_expired and no family_id stored; re-run "
                "scripts/setup-devcontainer-signing.sh to bootstrap a new pair"
            )
        try:
            reissued = self._auth.reissue(self._credentials.family_id)
        except AuthzUnavailableError as exc:
            raise BridgeUnavailableError(f"agent-auth reissue unavailable: {exc}") from exc
        except AuthzError as exc:
            raise BridgeUnauthorizedError(str(exc)) from exc
        self._credentials.access_token = reissued.access_token
        self._credentials.refresh_token = reissued.refresh_token
        self._store.save(self._credentials)

    # -- internal HTTP plumbing --

    def _post(self, token: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
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
                    path,
                    body=body,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body)),
                    },
                )
                response = conn.getresponse()
                raw = response.read()
                retry_after_header = response.getheader("Retry-After") or ""
            except (ConnectionError, TimeoutError, OSError) as exc:
                raise BridgeUnavailableError(f"gpg-bridge unreachable: {exc}") from exc
        finally:
            conn.close()

        try:
            data: dict[str, Any] = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise BridgeUnavailableError(
                f"gpg-bridge returned non-JSON response (status {response.status})"
            ) from exc

        if 200 <= response.status < 300:
            return data

        error_code = str(data.get("error") or "")
        if response.status == 401:
            # Discriminate ``token_expired`` from generic ``unauthorized``
            # so :meth:`_with_retry` can refresh on the former and exit
            # on the latter. ADR 0011 is explicit that the bridge
            # surfaces both codes distinctly.
            if error_code == "token_expired":
                raise BridgeTokenExpiredError(error_code)
            raise BridgeUnauthorizedError(error_code or "unauthorized")
        if response.status == 403:
            raise BridgeForbiddenError(error_code or "forbidden")
        if response.status == 404:
            raise BridgeNotFoundError(error_code or "not_found")
        if response.status == 400 and error_code == "bad_signature":
            raise BridgeBadSignatureError(error_code)
        if response.status == 429:
            try:
                retry_after = max(1, int(retry_after_header)) if retry_after_header else 1
            except ValueError:
                retry_after = 1
            raise BridgeRateLimitedError(
                error_code or "rate_limited", retry_after_seconds=retry_after
            )
        raise BridgeUnavailableError(
            f"unexpected gpg-bridge response {response.status}: {error_code or '<no body>'}"
        )


__all__ = ["BridgeClient"]
