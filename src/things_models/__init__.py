"""Shared domain models for Things 3 objects and error taxonomy.

Imported by ``things-bridge``, ``things-client-cli-applescript`` and
``tests/things_client_fake``. Keeping the dataclasses + error hierarchy
in one package means the subprocess boundary between bridge and client
CLI can round-trip structured values through JSON without the bridge
re-declaring types it does not own.
"""

from things_models.client import ThingsClient
from things_models.errors import (
    ThingsError,
    ThingsNotFoundError,
    ThingsPermissionError,
)
from things_models.models import Area, Project, Todo
from things_models.status import VALID_STATUSES, validate_status

__all__ = [
    "Area",
    "Project",
    "ThingsClient",
    "ThingsError",
    "ThingsNotFoundError",
    "ThingsPermissionError",
    "Todo",
    "VALID_STATUSES",
    "validate_status",
]
