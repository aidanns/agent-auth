# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Exception hierarchy for gpg-bridge.

GPG errors live in :mod:`gpg_models.errors`; this module owns only the
authz-delegation errors, mirroring the split in
:mod:`things_bridge.errors`.
"""

from gpg_models.errors import (
    GpgBadSignatureError,
    GpgError,
    GpgNoSuchKeyError,
    GpgPermissionError,
    GpgUnsupportedOperationError,
)


class GpgBridgeError(Exception):
    """Base exception for gpg-bridge-local errors (excludes GPG errors)."""


class AuthzError(GpgBridgeError):
    """Base exception for agent-auth validation failures."""


class AuthzTokenInvalidError(AuthzError):
    """Token is missing, malformed, or not recognised by agent-auth."""


class AuthzTokenExpiredError(AuthzError):
    """Token has expired; the CLI should refresh."""


class AuthzScopeDeniedError(AuthzError):
    """Token does not carry the required scope."""


class AuthzUnavailableError(AuthzError):
    """agent-auth server is unreachable or returned an unexpected response."""


class AuthzRateLimitedError(AuthzError):
    """agent-auth returned 429; token family is over its rate-limit budget."""

    def __init__(self, message: str, *, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class GpgKeyNotAllowedError(GpgBridgeError):
    """The requested signing key is not in the bridge's allowlist."""


__all__ = [
    "AuthzError",
    "AuthzRateLimitedError",
    "AuthzScopeDeniedError",
    "AuthzTokenExpiredError",
    "AuthzTokenInvalidError",
    "AuthzUnavailableError",
    "GpgBadSignatureError",
    "GpgBridgeError",
    "GpgError",
    "GpgKeyNotAllowedError",
    "GpgNoSuchKeyError",
    "GpgPermissionError",
    "GpgUnsupportedOperationError",
]
