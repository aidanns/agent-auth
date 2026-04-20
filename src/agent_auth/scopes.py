# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Scope parsing and access tier resolution."""

from agent_auth.errors import ScopeDeniedError

VALID_TIERS = {"allow", "prompt", "deny"}
DEFAULT_TIER = "allow"


def parse_scope_arg(arg: str) -> tuple[str, str]:
    """Parse a scope argument like 'things:read=allow' into (name, tier).

    If no tier is specified, defaults to 'allow'.
    """
    if "=" in arg:
        name, tier = arg.rsplit("=", 1)
        if tier not in VALID_TIERS:
            valid = ", ".join(sorted(VALID_TIERS))
            raise ValueError(f"Invalid tier '{tier}' for scope '{name}'. Must be one of: {valid}")
        return name, tier
    return arg, DEFAULT_TIER


def check_scope(required_scope: str, granted_scopes: dict[str, str]) -> str:
    """Check whether a required scope is authorized and return its tier.

    Raises ScopeDeniedError if the scope is not granted or has tier 'deny'.
    """
    tier = granted_scopes.get(required_scope)
    if tier is None:
        raise ScopeDeniedError(f"Scope '{required_scope}' not granted")
    if tier == "deny":
        raise ScopeDeniedError(f"Scope '{required_scope}' is denied")
    return tier
