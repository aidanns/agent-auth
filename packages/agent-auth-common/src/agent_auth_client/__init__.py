# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP client library and credential-rotation orchestration for agent-auth.

:class:`AgentAuthClient` covers every ``/agent-auth/*`` endpoint with
typed methods and a typed error hierarchy. :class:`AuthenticatedRetry`
wraps a downstream HTTP call with the shared refresh + reissue retry
ladder consumed by ``things-cli`` and ``gpg-cli``
(see :doc:`ADR 0043 </design/decisions/0043-shared-authenticated-retry-library>`).
"""

from agent_auth_client.auth_retry import (
    AuthenticatedRetry,
    CredentialsLike,
    CredentialStoreLike,
)
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
    "AuthenticatedRetry",
    "AuthzError",
    "AuthzRateLimitedError",
    "AuthzScopeDeniedError",
    "AuthzTokenExpiredError",
    "AuthzTokenInvalidError",
    "AuthzUnavailableError",
    "CredentialStoreLike",
    "CredentialsLike",
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
