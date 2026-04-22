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


class KeyLossError(AgentAuthError):
    """Token store exists but the signing / encryption key is missing.

    Raised at startup when ``$XDG_DATA_HOME/agent-auth/tokens.db`` contains
    any token families but the system keyring no longer holds the matching
    signing or encryption key (keychain wipe, new host, fresh OS install).
    The server refuses to auto-regenerate: a fresh key would silently
    invalidate every live token and render encrypted columns unreadable,
    while the DB would claim the old state. The operator must delete the
    DB to accept the reset, or restore the keyring to resume with live
    tokens. See ``design/DESIGN.md`` "Key loss and recovery".
    """
