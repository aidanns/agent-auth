"""Shared status-value validation for Things 3 todos and projects."""

from things_models.errors import ThingsError

VALID_STATUSES = {"open", "completed", "canceled"}


def validate_status(status: str | None) -> str | None:
    if status is None:
        return None
    if status not in VALID_STATUSES:
        raise ThingsError(
            f"Invalid status filter: {status!r} (expected one of {sorted(VALID_STATUSES)})"
        )
    return status
