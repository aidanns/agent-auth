# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Authenticated bridge client with automatic token refresh and re-issuance.

This module composes :mod:`things_bridge_client` (one method per
``/things-bridge/*`` endpoint) with :mod:`agent_auth_client` (token
refresh + reissue) into a single callable surface that owns the
credential-lifecycle side-effects:

1. Attaches ``Authorization: Bearer <access_token>`` from the credential store.
2. On ``401 {"error": "token_expired"}`` the client calls
   ``POST /agent-auth/v1/token/refresh``, persists the new tokens, and
   retries the original request once.
3. If the refresh token has itself expired, the client calls
   ``POST /agent-auth/v1/token/reissue`` (which blocks on host-side JIT
   approval) and retries the original request once.
4. Any further 401 surfaces as :class:`ThingsBridgeUnauthorizedError`.

The HTTP plumbing for each individual request is delegated to the
library clients; this module deliberately owns only the orchestration
state.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_auth_client import (
    AgentAuthClient,
    AuthzError,
    AuthzUnavailableError,
    RefreshTokenExpiredError,
)
from things_bridge_client import (
    ThingsBridgeClient,
    ThingsBridgeTokenExpiredError,
    ThingsBridgeUnauthorizedError,
    ThingsBridgeUnavailableError,
)
from things_cli.credentials import Credentials, CredentialStore


class BridgeClient:
    """Authenticated orchestrator over the bridge + agent-auth HTTP APIs.

    Per-endpoint methods mirror :class:`things_bridge_client.ThingsBridgeClient`
    (currently read-only); the wrapper adds the refresh/reissue retry loop
    around each call.
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
        self._bridge = ThingsBridgeClient(
            credentials.bridge_url,
            timeout_seconds=timeout_seconds,
            ca_cert_path=ca_cert_path,
        )
        self._auth = AgentAuthClient(
            credentials.auth_url,
            timeout_seconds=timeout_seconds,
            ca_cert_path=ca_cert_path,
        )

    @property
    def credentials(self) -> Credentials:
        return self._credentials

    # -- public API: one method per bridge endpoint --

    def list_todos(self, params: dict[str, str] | None = None) -> dict[str, Any]:
        return self._with_retry(lambda token: self._bridge.list_todos(token, params=params))

    def get_todo(self, todo_id: str) -> dict[str, Any]:
        return self._with_retry(lambda token: self._bridge.get_todo(token, todo_id))

    def list_projects(self, params: dict[str, str] | None = None) -> dict[str, Any]:
        return self._with_retry(lambda token: self._bridge.list_projects(token, params=params))

    def get_project(self, project_id: str) -> dict[str, Any]:
        return self._with_retry(lambda token: self._bridge.get_project(token, project_id))

    def list_areas(self) -> dict[str, Any]:
        return self._with_retry(lambda token: self._bridge.list_areas(token))

    def get_area(self, area_id: str) -> dict[str, Any]:
        return self._with_retry(lambda token: self._bridge.get_area(token, area_id))

    # -- internal --

    def _with_retry(self, call: Callable[[str | None], dict[str, Any]]) -> dict[str, Any]:
        """Invoke ``call`` with the current access token; refresh once on 401 token_expired."""
        try:
            return call(self._credentials.access_token)
        except ThingsBridgeTokenExpiredError:
            pass
        self._refresh_access_token()
        # A second ``token_expired`` after a successful refresh shouldn't
        # happen in practice, but surfacing the raw
        # ``ThingsBridgeTokenExpiredError`` would leak the internal
        # retry contract. Collapse it into a plain ``unauthorized`` so
        # the CLI maps it to exit 2 like any other post-retry 401.
        try:
            return call(self._credentials.access_token)
        except ThingsBridgeTokenExpiredError as exc:
            raise ThingsBridgeUnauthorizedError(str(exc) or "token_expired") from exc

    def _refresh_access_token(self) -> None:
        """Exchange the stored refresh token, falling back to reissue on expiry."""
        try:
            refreshed = self._auth.refresh(self._credentials.refresh_token)
        except RefreshTokenExpiredError:
            self._reissue_tokens()
            return
        except AuthzUnavailableError as exc:
            raise ThingsBridgeUnavailableError(str(exc)) from exc
        except AuthzError as exc:
            # Any other 401/403/4xx from refresh (reuse detected, family
            # revoked, scope denied, …) is terminal: the CLI must ask
            # the user to log in again. Preserve the server-supplied
            # error code so the operator sees the specific reason.
            raise ThingsBridgeUnauthorizedError(str(exc)) from exc
        self._credentials.access_token = refreshed.access_token
        self._credentials.refresh_token = refreshed.refresh_token
        self._store.save(self._credentials)

    def _reissue_tokens(self) -> None:
        """Call the agent-auth reissue endpoint, then persist the new pair."""
        if not self._credentials.family_id:
            raise ThingsBridgeUnauthorizedError(
                "refresh_token_expired and no family_id stored; run " "`things-cli login` again"
            )
        try:
            reissued = self._auth.reissue(self._credentials.family_id)
        except AuthzUnavailableError as exc:
            raise ThingsBridgeUnavailableError(str(exc)) from exc
        except AuthzError as exc:
            raise ThingsBridgeUnauthorizedError(str(exc)) from exc
        self._credentials.access_token = reissued.access_token
        self._credentials.refresh_token = reissued.refresh_token
        self._store.save(self._credentials)
