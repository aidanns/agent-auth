# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""HTTP client library for the things-bridge service.

Covers every ``/things-bridge/*`` endpoint with typed methods and a
typed error hierarchy. Scope is deliberately kept to the bridge surface
— the token refresh / reissue dance lives in
:class:`agent_auth_client.AgentAuthClient` and the ``things_cli`` CLI
orchestrates both.
"""

from things_bridge_client.client import ThingsBridgeClient
from things_bridge_client.errors import (
    ThingsBridgeClientError,
    ThingsBridgeForbiddenError,
    ThingsBridgeNotFoundError,
    ThingsBridgeRateLimitedError,
    ThingsBridgeTokenExpiredError,
    ThingsBridgeUnauthorizedError,
    ThingsBridgeUnavailableError,
)

__all__ = [
    "ThingsBridgeClient",
    "ThingsBridgeClientError",
    "ThingsBridgeForbiddenError",
    "ThingsBridgeNotFoundError",
    "ThingsBridgeRateLimitedError",
    "ThingsBridgeTokenExpiredError",
    "ThingsBridgeUnauthorizedError",
    "ThingsBridgeUnavailableError",
]
