# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Error hierarchy for GPG interactions.

Raised by the backend CLIs and re-raised by gpg-bridge after parsing
the ``{"error": ...}`` body returned on subprocess stdout. Kept here
so the bridge and the backend CLIs refer to the same types.
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
