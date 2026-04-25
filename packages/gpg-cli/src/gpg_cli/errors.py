# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Error hierarchy for gpg-cli HTTP and credential interactions."""


class GpgCliError(Exception):
    """Base exception for gpg-cli HTTP-client and credential failures."""


class BridgeUnauthorizedError(GpgCliError):
    """gpg-bridge rejected the bearer token (generic 401)."""


class BridgeTokenExpiredError(BridgeUnauthorizedError):
    """gpg-bridge returned 401 ``token_expired`` — caller should refresh.

    Subclass of :class:`BridgeUnauthorizedError` so callers that catch
    the generic class continue to work; the retry loop in
    :class:`gpg_cli.client.BridgeClient` discriminates on the subclass.
    """


class BridgeForbiddenError(GpgCliError):
    """gpg-bridge accepted the token but denied the scope or key."""


class BridgeNotFoundError(GpgCliError):
    """gpg-bridge returned 404 (no such key / resource)."""


class BridgeBadSignatureError(GpgCliError):
    """gpg-bridge reported an invalid signature during verify."""


class BridgeUnavailableError(GpgCliError):
    """gpg-bridge could not complete the request (5xx, network error)."""


class BridgeRateLimitedError(GpgCliError):
    """gpg-bridge returned 429; token family is over its rate-limit budget."""

    def __init__(self, message: str, *, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class CredentialsNotFoundError(GpgCliError):
    """No gpg-cli credentials are stored.

    Raised by :class:`gpg_cli.config.FileStore` when the configured
    credentials file does not exist. The CLI surfaces it as exit 2 with
    a message naming ``scripts/setup-devcontainer-signing.sh`` as the
    recovery command.
    """


class CredentialsBackendError(GpgCliError):
    """The credentials file is unreadable, corrupt, or has wrong mode."""


class ConfigMigrationRequiredError(GpgCliError):
    """The on-disk config file uses the pre-refresh single-token schema.

    Raised by :func:`gpg_cli.config.load_config` when the config file
    contains a top-level ``token:`` key but no ``access_token:`` /
    ``refresh_token:`` pair. The single-bearer schema cannot be
    auto-migrated — there is no refresh token to derive — so the
    operator must re-run ``scripts/setup-devcontainer-signing.sh`` with
    the new ``--access-token`` / ``--refresh-token`` flags. The error
    message names the recovery command verbatim.
    """


__all__ = [
    "BridgeBadSignatureError",
    "BridgeForbiddenError",
    "BridgeNotFoundError",
    "BridgeRateLimitedError",
    "BridgeTokenExpiredError",
    "BridgeUnauthorizedError",
    "BridgeUnavailableError",
    "ConfigMigrationRequiredError",
    "CredentialsBackendError",
    "CredentialsNotFoundError",
    "GpgCliError",
]
