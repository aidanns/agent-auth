# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Authenticated bridge client with automatic token refresh and re-issuance.

Composes :mod:`things_bridge_client` (one method per
``/things-bridge/*`` endpoint) with
:class:`agent_auth_client.AuthenticatedRetry` (the shared refresh +
reissue retry loop) into a single callable surface that owns the
credential-lifecycle side-effects:

1. Attaches ``Authorization: Bearer <access_token>`` from the credential
   store.
2. On ``401 {"error": "token_expired"}`` the shared retry loop calls
   ``POST /agent-auth/v1/token/refresh``, persists the new tokens, and
   retries the original request once.
3. If the refresh token has itself expired, the loop calls
   ``POST /agent-auth/v1/token/reissue`` (which blocks on host-side JIT
   approval) and retries the original request once.
4. Any further 401 surfaces as :class:`ThingsBridgeUnauthorizedError`.

The HTTP plumbing for each individual request is delegated to the
library clients; the orchestration ladder lives in
:class:`agent_auth_client.AuthenticatedRetry` so ``things-cli`` and
``gpg-cli`` share a single implementation (issue #328).
"""

from __future__ import annotations

from typing import Any

from agent_auth_client import AgentAuthClient, AuthenticatedRetry
from things_bridge_client import (
    ThingsBridgeClient,
    ThingsBridgeTokenExpiredError,
    ThingsBridgeUnauthorizedError,
    ThingsBridgeUnavailableError,
)
from things_cli.credentials import Credentials, CredentialStore
from things_models.models import AreaId, ProjectId, TodoId

_NO_FAMILY_ID_MESSAGE = (
    "refresh_token_expired and no family_id stored; run `things-cli login` again"
)


class BridgeClient:
    """Authenticated orchestrator over the bridge + agent-auth HTTP APIs.

    Per-endpoint methods mirror :class:`things_bridge_client.ThingsBridgeClient`
    (currently read-only); the wrapper adds the shared refresh/reissue
    retry loop around each call.
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
        self._bridge = ThingsBridgeClient(
            credentials.bridge_url,
            timeout_seconds=timeout_seconds,
            ca_cert_path=ca_cert_path,
        )
        self._retry = AuthenticatedRetry[dict[str, Any], Credentials](
            credentials,
            store,
            AgentAuthClient(
                credentials.auth_url,
                timeout_seconds=timeout_seconds,
                ca_cert_path=ca_cert_path,
            ),
            token_expired_exc=ThingsBridgeTokenExpiredError,
            unauthorized_exc=ThingsBridgeUnauthorizedError,
            unavailable_exc=ThingsBridgeUnavailableError,
            no_family_id_message=_NO_FAMILY_ID_MESSAGE,
        )

    @property
    def credentials(self) -> Credentials:
        return self._credentials

    # -- public API: one method per bridge endpoint --

    def list_todos(self, params: dict[str, str] | None = None) -> dict[str, Any]:
        return self._retry.with_retry(lambda token: self._bridge.list_todos(token, params=params))

    def get_todo(self, todo_id: TodoId) -> dict[str, Any]:
        return self._retry.with_retry(lambda token: self._bridge.get_todo(token, todo_id))

    def list_projects(self, params: dict[str, str] | None = None) -> dict[str, Any]:
        return self._retry.with_retry(
            lambda token: self._bridge.list_projects(token, params=params)
        )

    def get_project(self, project_id: ProjectId) -> dict[str, Any]:
        return self._retry.with_retry(lambda token: self._bridge.get_project(token, project_id))

    def list_areas(self) -> dict[str, Any]:
        return self._retry.with_retry(lambda token: self._bridge.list_areas(token))

    def get_area(self, area_id: AreaId) -> dict[str, Any]:
        return self._retry.with_retry(lambda token: self._bridge.get_area(token, area_id))
