# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Error hierarchy for GPG interactions.

Raised by ``gpg-bridge`` from its gpg-subprocess wrapper and surfaced
on the HTTP error envelope. Kept in ``agent-auth-common`` so
downstream consumers (``gpg-cli``, callers binding the typed HTTP
client) refer to the same types.
"""


class GpgError(Exception):
    """Failure interacting with the host gpg binary."""


class GpgNoSuchKeyError(GpgError):
    """The requested signing key is not present in the host keyring."""


class GpgBadSignatureError(GpgError):
    """A verify request found the signature invalid."""


class GpgPermissionError(GpgError):
    """The host gpg could not access the keyring (e.g. locked, agent down)."""


class GpgUnsupportedOperationError(GpgError):
    """The requested operation is not implemented by this CLI."""


__all__ = [
    "GpgBadSignatureError",
    "GpgError",
    "GpgNoSuchKeyError",
    "GpgPermissionError",
    "GpgUnsupportedOperationError",
]
