# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Exception hierarchy for things-bridge.

Things-related errors live in :mod:`things_models.errors` since they
are raised inside the subprocess client CLIs and re-raised here; this
module owns only the authz-delegation errors.
"""

from things_models.errors import (
    ThingsError,
    ThingsNotFoundError,
    ThingsPermissionError,
)


class ThingsBridgeError(Exception):
    """Base exception for things-bridge-local errors (excludes Things errors)."""


class AuthzError(ThingsBridgeError):
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
    """agent-auth returned 429; the token family is over its rate-limit budget.

    ``retry_after_seconds`` carries the ``Retry-After`` header value so
    the bridge can pass it through verbatim in its own 429 response.
    """

    def __init__(self, message: str, *, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


__all__ = [
    "AuthzError",
    "AuthzRateLimitedError",
    "AuthzScopeDeniedError",
    "AuthzTokenExpiredError",
    "AuthzTokenInvalidError",
    "AuthzUnavailableError",
    "ThingsBridgeError",
    "ThingsError",
    "ThingsNotFoundError",
    "ThingsPermissionError",
]
