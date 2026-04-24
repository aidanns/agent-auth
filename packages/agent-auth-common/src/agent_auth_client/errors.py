# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Typed exception hierarchy raised by :class:`AgentAuthClient`.

The ``Authz*`` names are preserved for backwards compatibility with the
pre-split ``things_bridge.authz`` hierarchy — callers who already
except on ``AuthzTokenExpiredError`` keep working once they re-import
from this package. ``AgentAuthError`` is a superclass of everything
raised by the client; grouped aliases (``AuthzError``,
``AgentAuthUnavailableError``) document intent at the call site.
"""

from __future__ import annotations


class AgentAuthError(Exception):
    """Base for every exception raised by :class:`AgentAuthClient`."""


class AuthzError(AgentAuthError):
    """Raised on validation, refresh, or reissue failure.

    Kept as an alias of :class:`AgentAuthError` for compatibility with
    callers inherited from the pre-split ``things_bridge.authz``
    hierarchy. New code may depend on :class:`AgentAuthError` directly.
    """


class AuthzTokenInvalidError(AuthzError):
    """Token is missing, malformed, or not recognised by agent-auth."""


class AuthzTokenExpiredError(AuthzError):
    """Token has expired; the caller should refresh."""


class AuthzScopeDeniedError(AuthzError):
    """Token does not carry the required scope, or scope is deny-tier."""


class RefreshTokenExpiredError(AuthzError):
    """Refresh token has expired; a re-issue is required."""


class RefreshTokenReuseDetectedError(AuthzError):
    """A consumed refresh token was re-used; the family has been revoked."""


class FamilyRevokedError(AuthzError):
    """Token family has been revoked and can no longer be refreshed or reissued."""


class FamilyNotFoundError(AgentAuthError):
    """Management endpoint could not find the referenced family."""


class ReissueDeniedError(AuthzError):
    """Human approval for re-issuing an expired family was denied."""


class MalformedRequestError(AgentAuthError):
    """agent-auth rejected the request body (400)."""


class AuthzUnavailableError(AgentAuthError):
    """agent-auth is unreachable or returned an unexpected response.

    Covers connection errors, timeouts, non-JSON response bodies, and
    any status code not explicitly handled by the caller. The bridge's
    validation path maps this to a 502 ``authz_unavailable`` response.
    """


# ``AgentAuthUnavailableError`` is accepted as an idiomatic alias for
# new code; existing tests and call sites use ``AuthzUnavailableError``.
AgentAuthUnavailableError = AuthzUnavailableError


class AuthzRateLimitedError(AuthzError):
    """agent-auth returned 429.

    ``retry_after_seconds`` carries the ``Retry-After`` header verbatim
    so callers can surface it to users or pass it through in their own
    429 response.
    """

    def __init__(self, message: str, *, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
