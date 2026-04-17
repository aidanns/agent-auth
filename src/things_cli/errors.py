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
