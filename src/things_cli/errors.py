# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Exception hierarchy for things-cli.

Credential-lifecycle errors are owned here; bridge HTTP errors live in
:mod:`things_bridge_client.errors` and are re-raised as-is by
:class:`things_cli.client.BridgeClient`. The CLI's top-level dispatcher
catches both hierarchies to produce exit codes.
"""


class ThingsCLIError(Exception):
    """Base exception for all things-cli errors."""


class CredentialsNotFoundError(ThingsCLIError):
    """No credentials are stored; the user must run ``things-cli login`` first."""


class CredentialsBackendError(ThingsCLIError):
    """The configured credential backend is unavailable."""
