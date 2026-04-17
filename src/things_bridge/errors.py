"""Exception hierarchy for things-bridge."""


class ThingsBridgeError(Exception):
    """Base exception for all things-bridge errors."""


class ThingsError(ThingsBridgeError):
    """Failure interacting with the Things application via AppleScript."""


class ThingsNotFoundError(ThingsError):
    """Referenced Things object does not exist."""


class ThingsPermissionError(ThingsError):
    """macOS Automation permission has not been granted to the bridge process."""


class AuthzError(ThingsBridgeError):
    """Base exception for agent-auth validation failures."""


class AuthzTokenInvalidError(AuthzError):
    """Token is missing, malformed, or not recognised by agent-auth."""


class AuthzTokenExpiredError(AuthzError):
    """Token has expired; the CLI should refresh."""


class AuthzScopeDeniedError(AuthzError):
    """Token does not carry the required scope."""


class AuthzUnavailableError(AuthzError):
    """agent-auth server is unreachable or returned an unexpected response."""
