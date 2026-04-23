# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Typed exception hierarchy raised by :class:`ThingsBridgeClient`."""

from __future__ import annotations


class ThingsBridgeClientError(Exception):
    """Base for every exception raised by :class:`ThingsBridgeClient`."""


class ThingsBridgeUnauthorizedError(ThingsBridgeClientError):
    """Bridge returned 401 for an operation (generic unauthorized)."""


class ThingsBridgeTokenExpiredError(ThingsBridgeUnauthorizedError):
    """Bridge returned 401 ``token_expired`` — caller should refresh."""


class ThingsBridgeForbiddenError(ThingsBridgeClientError):
    """Bridge returned 403 — scope denied."""


class ThingsBridgeNotFoundError(ThingsBridgeClientError):
    """Bridge returned 404 — target resource does not exist."""


class ThingsBridgeUnavailableError(ThingsBridgeClientError):
    """Bridge returned 5xx, or the connection failed / was malformed."""


class ThingsBridgeRateLimitedError(ThingsBridgeClientError):
    """Bridge returned 429 — the token family is over its rate-limit budget.

    ``retry_after_seconds`` carries the ``Retry-After`` header value so
    the CLI can print a useful hint or a calling automation can pace
    itself.
    """

    def __init__(self, message: str, *, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
