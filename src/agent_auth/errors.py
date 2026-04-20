# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Exception hierarchy for agent-auth."""


class AgentAuthError(Exception):
    """Base exception for all agent-auth errors."""


class TokenError(AgentAuthError):
    """Base exception for token-related errors."""


class TokenInvalidError(TokenError):
    """Token signature verification failed or token is malformed."""


class TokenExpiredError(TokenError):
    """Token has expired."""


class TokenRevokedError(TokenError):
    """Token belongs to a revoked family."""


class ScopeDeniedError(AgentAuthError):
    """Token does not carry the required scope, or scope tier is deny."""


class FamilyRevokedError(AgentAuthError):
    """Token family has been revoked."""


class ApprovalDeniedError(AgentAuthError):
    """JIT approval was denied by the user."""


class KeyringError(AgentAuthError):
    """Failed to access the system keyring."""
