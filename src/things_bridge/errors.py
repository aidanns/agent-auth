# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Exception hierarchy for things-bridge.

The ``Authz*`` errors raised when delegating token validation to
agent-auth live in :mod:`agent_auth_client.errors`; the
``ThingsError`` family raised from the subprocess client CLIs lives in
:mod:`things_models.errors`. This module owns only the bridge-local
base class.
"""

from things_models.errors import (
    ThingsError,
    ThingsNotFoundError,
    ThingsPermissionError,
)


class ThingsBridgeError(Exception):
    """Base exception for things-bridge-local errors (excludes Things errors)."""


__all__ = [
    "ThingsBridgeError",
    "ThingsError",
    "ThingsNotFoundError",
    "ThingsPermissionError",
]
