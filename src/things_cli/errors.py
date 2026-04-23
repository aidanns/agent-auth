# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Exception hierarchy for things-cli."""


class ThingsCLIError(Exception):
    """Base exception for all things-cli errors."""


class CredentialsNotFoundError(ThingsCLIError):
    """No credentials are stored; the user must run ``things-cli login`` first."""


class CredentialsBackendError(ThingsCLIError):
    """The configured credential backend is unavailable."""


class BridgeError(ThingsCLIError):
    """Base exception for bridge HTTP failures."""


class BridgeUnauthorizedError(BridgeError):
    """Bridge returned 401 for an operation and refresh/reissue did not recover."""


class BridgeForbiddenError(BridgeError):
    """Bridge returned 403 — scope denied."""


class BridgeNotFoundError(BridgeError):
    """Bridge returned 404 — target resource does not exist."""


class BridgeUnavailableError(BridgeError):
    """Bridge or agent-auth returned 5xx, or the connection failed."""


class BridgeRateLimitedError(BridgeError):
    """Bridge or agent-auth returned 429 — the token family is over its rate-limit budget.

    ``retry_after_seconds`` carries the ``Retry-After`` header so the
    CLI can print a useful hint or a calling automation can pace
    itself.
    """

    def __init__(self, message: str, *, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
