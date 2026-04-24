# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Error hierarchy for Things 3 interactions.

These errors are raised by the Things client CLIs and re-raised by the
bridge after parsing the ``{"error": ...}`` body returned on subprocess
stdout. Kept here — rather than in any single consumer — so the bridge
and the client CLIs refer to the same types.
"""


class ThingsError(Exception):
    """Failure interacting with the Things application."""


class ThingsNotFoundError(ThingsError):
    """Referenced Things object does not exist."""


class ThingsPermissionError(ThingsError):
    """macOS Automation permission has not been granted for Things 3."""
