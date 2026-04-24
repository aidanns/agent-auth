# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP client library for the agent-auth service.

Covers every ``/agent-auth/*`` endpoint with typed methods and a
typed error hierarchy. Replaces the partial per-caller clients that
previously lived inside ``things_bridge.authz`` and the token-refresh
path of ``things_cli.client``.
"""

from agent_auth_client.client import (
    AgentAuthClient,
    RefreshedTokens,
    ReissuedTokens,
    TokenFamilySummary,
    TokenPair,
    TokenStatus,
)
from agent_auth_client.errors import (
    AgentAuthError,
    AgentAuthUnavailableError,
    AuthzError,
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

__all__ = [
    "AgentAuthClient",
    "AgentAuthError",
    "AgentAuthUnavailableError",
    "AuthzError",
    "AuthzRateLimitedError",
    "AuthzScopeDeniedError",
    "AuthzTokenExpiredError",
    "AuthzTokenInvalidError",
    "AuthzUnavailableError",
    "FamilyNotFoundError",
    "FamilyRevokedError",
    "MalformedRequestError",
    "RefreshTokenExpiredError",
    "RefreshTokenReuseDetectedError",
    "RefreshedTokens",
    "ReissueDeniedError",
    "ReissuedTokens",
    "TokenFamilySummary",
    "TokenPair",
    "TokenStatus",
]
