# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Types at the things-bridge config / subprocess boundary.

``ThingsClientCommand`` is the argv prefix used to invoke the Things
client CLI (default ``things-client-cli-applescript``). The NewType
wrapper plus :func:`make_things_client_command` constructor centralise
the "non-empty sequence of strings" invariant so every consumer
(``Config``, ``ThingsSubprocessClient``, ``_HealthChecker``) can accept
the validated value by type and doesn't have to re-check the shape.

See ``.claude/instructions/coding-standards.md`` § *Newtypes at
security/trust boundaries* and issue #70 (itself a follow-up on
``plans/things-client-cli-split.md`` standards-review checkpoint).
"""

from collections.abc import Iterable
from typing import NewType, cast

ThingsClientCommand = NewType("ThingsClientCommand", tuple[str, ...])


def make_things_client_command(argv: Iterable[object]) -> ThingsClientCommand:
    """Validate ``argv`` and wrap it as a :data:`ThingsClientCommand`.

    Accepts any iterable (YAML delivers ``list[Any]`` with no element-
    type guarantee; callers inside the codebase pass properly-typed
    sequences). Rejects empty sequences and non-string elements —
    silently accepting either would turn into an obscure
    ``FileNotFoundError`` later when ``ThingsSubprocessClient`` reaches
    ``subprocess.Popen``. ``argv`` is declared ``Iterable[object]`` so
    the ``isinstance`` narrowing is meaningful to the type checker.
    """
    argv_tuple = tuple(argv)
    if not argv_tuple:
        raise ValueError("ThingsClientCommand must be a non-empty sequence of strings")
    for i, element in enumerate(argv_tuple):
        if not isinstance(element, str):
            raise TypeError(
                f"ThingsClientCommand element {i} must be a str, got {type(element).__name__}"
            )
    # The isinstance loop above ensures every element is str; the cast
    # narrows the tuple-of-object we built to a tuple-of-str for the
    # NewType constructor.
    return ThingsClientCommand(cast(tuple[str, ...], argv_tuple))


__all__ = ["ThingsClientCommand", "make_things_client_command"]
