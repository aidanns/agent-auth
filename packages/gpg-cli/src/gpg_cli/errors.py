# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Error hierarchy for gpg-cli HTTP interactions."""


class GpgCliError(Exception):
    """Base exception for gpg-cli HTTP-client failures."""


class BridgeUnauthorizedError(GpgCliError):
    """gpg-bridge rejected the bearer token."""


class BridgeForbiddenError(GpgCliError):
    """gpg-bridge accepted the token but denied the scope or key."""


class BridgeNotFoundError(GpgCliError):
    """gpg-bridge returned 404 (no such key / resource)."""


class BridgeBadSignatureError(GpgCliError):
    """gpg-bridge reported an invalid signature during verify."""


class BridgeUnavailableError(GpgCliError):
    """gpg-bridge could not complete the request (5xx, network error)."""


class BridgeSigningBackendUnavailableError(GpgCliError):
    """gpg-bridge reported the signing backend is wedged or unavailable.

    Distinct from :class:`BridgeUnavailableError`: the bridge itself is
    reachable and authenticated the request, but the host gpg
    subprocess behind it could not complete (typically a misconfigured
    ``gpg-agent``). Surfaced from a 503 response with
    ``error == "signing_backend_unavailable"``.
    """


class BridgeRateLimitedError(GpgCliError):
    """gpg-bridge returned 429; token family is over its rate-limit budget."""

    def __init__(self, message: str, *, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


__all__ = [
    "BridgeBadSignatureError",
    "BridgeForbiddenError",
    "BridgeNotFoundError",
    "BridgeRateLimitedError",
    "BridgeSigningBackendUnavailableError",
    "BridgeUnauthorizedError",
    "BridgeUnavailableError",
    "GpgCliError",
]
