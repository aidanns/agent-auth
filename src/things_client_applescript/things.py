# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""AppleScript runner and high-level Things client.

The runner shells out to ``osascript`` to execute AppleScript against Things 3.
The client builds AppleScript that emits a tab-separated, record-per-line stream
so results parse cleanly without a JSON dependency on the AppleScript side.

Tabs and newlines in note/name fields are escaped into private-use unicode
separators (U+241E for tab, U+241F for newline) inside AppleScript, and
un-escaped by the parser so free-form text survives the framing.
"""

import subprocess
import sys
from dataclasses import dataclass

from things_models.errors import (
    ThingsError,
    ThingsNotFoundError,
    ThingsPermissionError,
)
from things_models.models import Area, AreaId, Project, ProjectId, Todo, TodoId
from things_models.status import validate_status

TAB_PLACEHOLDER = "\u241e"
NEWLINE_PLACEHOLDER = "\u241f"
MISSING = "missing value"

# AppleScript helper installed at the top of every emitted script.
# Escapes tabs/newlines/carriage returns into unicode placeholders and
# coerces missing value to the literal "missing value" so the parser
# can treat it uniformly.
#
# ``character id N`` is the AppleScript way to produce a Unicode codepoint
# inside a string. AppleScript string literals do NOT support ``\uXXXX``
# escapes — attempting to use them produces a ``-2741`` syntax error at
# compile time.
_HELPERS = r"""
on _esc(v)
    if v is missing value then return "missing value"
    set s to v as text
    set out to ""
    set tabPlaceholder to (character id 9246)
    set linefeedPlaceholder to (character id 9247)
    repeat with i from 1 to count of characters of s
        set c to character i of s
        if c is tab then
            set out to out & tabPlaceholder
        else if c is return or c is linefeed then
            set out to out & linefeedPlaceholder
        else
            set out to out & c
        end if
    end repeat
    return out
end _esc

on _iso(d)
    if d is missing value then return "missing value"
    set y to year of d as integer
    set m to (month of d as integer)
    set dd to day of d as integer
    set hh to hours of d as integer
    set mm to minutes of d as integer
    set ss to seconds of d as integer
    set ys to y as text
    set ms to text -2 thru -1 of ("0" & m)
    set ds to text -2 thru -1 of ("0" & dd)
    set hs to text -2 thru -1 of ("0" & hh)
    set nms to text -2 thru -1 of ("0" & mm)
    set ss_ to text -2 thru -1 of ("0" & ss)
    return ys & "-" & ms & "-" & ds & "T" & hs & ":" & nms & ":" & ss_
end _iso

on _projId(t)
    try
        return id of project of t
    on error
        return "missing value"
    end try
end _projId

on _projName(t)
    try
        return name of project of t
    on error
        return "missing value"
    end try
end _projName

on _areaId(t)
    try
        return id of area of t
    on error
        return "missing value"
    end try
end _areaId

on _areaName(t)
    try
        return name of area of t
    on error
        return "missing value"
    end try
end _areaName

on _statusText(s)
    -- Handlers run outside the enclosing ``tell application "Things3"``
    -- block, so bare Things3 keywords like ``open``/``completed``/``canceled``
    -- are not in scope here. Coerce the status enum to its text name at
    -- the handler boundary and compare as strings instead.
    set stxt to (s as text)
    if stxt is "open" then
        return "open"
    else if stxt is "completed" then
        return "completed"
    else if stxt is "canceled" then
        return "canceled"
    else
        return "open"
    end if
end _statusText
"""

_TAB_LIT = '"\\t"'
_LF_LIT = '"\\n"'

# Columns emitted for each todo, in order.
_TODO_FIELDS = [
    "id",
    "name",
    "notes",
    "status",
    "project_id",
    "project_name",
    "area_id",
    "area_name",
    "tag_names",
    "due_date",
    "activation_date",
    "completion_date",
    "cancellation_date",
    "creation_date",
    "modification_date",
]

# Columns emitted for each project, in order.
_PROJECT_FIELDS = [
    "id",
    "name",
    "notes",
    "status",
    "area_id",
    "area_name",
    "tag_names",
    "due_date",
    "activation_date",
    "completion_date",
    "cancellation_date",
    "creation_date",
    "modification_date",
]

# Columns emitted for each area, in order.
_AREA_FIELDS = ["id", "name", "tag_names"]


def _todo_row_applescript(var: str) -> str:
    """AppleScript that appends one todo's TSV row to the `out` accumulator.

    Used by :func:`ThingsApplescriptClient.get_todo`, which reads exactly one
    todo and has nothing to batch. The list endpoints use
    :func:`_todo_batch_applescript` instead to avoid paying ``O(properties)``
    Apple Events per todo.
    """
    return f"""
                set _row to my _esc(id of {var})
                set _row to _row & {_TAB_LIT} & my _esc(name of {var})
                set _row to _row & {_TAB_LIT} & my _esc(notes of {var})
                set _row to _row & {_TAB_LIT} & my _statusText(status of {var})
                set _row to _row & {_TAB_LIT} & my _projId({var})
                set _row to _row & {_TAB_LIT} & my _projName({var})
                set _row to _row & {_TAB_LIT} & my _areaId({var})
                set _row to _row & {_TAB_LIT} & my _areaName({var})
                set _row to _row & {_TAB_LIT} & my _esc(tag names of {var})
                set _row to _row & {_TAB_LIT} & my _iso(due date of {var})
                set _row to _row & {_TAB_LIT} & my _iso(activation date of {var})
                set _row to _row & {_TAB_LIT} & my _iso(completion date of {var})
                set _row to _row & {_TAB_LIT} & my _iso(cancellation date of {var})
                set _row to _row & {_TAB_LIT} & my _iso(creation date of {var})
                set _row to _row & {_TAB_LIT} & my _iso(modification date of {var})
                set out to out & _row & {_LF_LIT}
"""


def _project_row_applescript(var: str) -> str:
    """Per-project TSV row for :func:`ThingsApplescriptClient.get_project`."""
    return f"""
                set _row to my _esc(id of {var})
                set _row to _row & {_TAB_LIT} & my _esc(name of {var})
                set _row to _row & {_TAB_LIT} & my _esc(notes of {var})
                set _row to _row & {_TAB_LIT} & my _statusText(status of {var})
                set _row to _row & {_TAB_LIT} & my _areaId({var})
                set _row to _row & {_TAB_LIT} & my _areaName({var})
                set _row to _row & {_TAB_LIT} & my _esc(tag names of {var})
                set _row to _row & {_TAB_LIT} & my _iso(due date of {var})
                set _row to _row & {_TAB_LIT} & my _iso(activation date of {var})
                set _row to _row & {_TAB_LIT} & my _iso(completion date of {var})
                set _row to _row & {_TAB_LIT} & my _iso(cancellation date of {var})
                set _row to _row & {_TAB_LIT} & my _iso(creation date of {var})
                set _row to _row & {_TAB_LIT} & my _iso(modification date of {var})
                set out to out & _row & {_LF_LIT}
"""


def _area_row_applescript(var: str) -> str:
    """Per-area TSV row for :func:`ThingsApplescriptClient.get_area`."""
    return f"""
                set _row to my _esc(id of {var})
                set _row to _row & {_TAB_LIT} & my _esc(name of {var})
                set _row to _row & {_TAB_LIT} & my _esc(tag names of {var})
                set out to out & _row & {_LF_LIT}
"""


def _every_form(plural: str, singular: str, scope: str) -> str:
    """Translate a plural element scope into the ``every <singular>`` form.

    AppleScript's batched property reads (``id of every to do of …``) and
    the plural iteration (``repeat with t in (to dos of …)``) use the same
    reference under two surface syntaxes. ``_todo_source`` and the project
    list branches already emit the plural form, so this helper just swaps
    the prefix so the same scope expression can drive both styles.

    Caller invariant: ``scope`` is either exactly ``plural`` or
    ``f"{plural} of <reference>"``. Any other shape signals a bug in the
    caller and is surfaced rather than smuggled into emitted AppleScript.
    """
    if scope == plural:
        return f"every {singular}"
    prefix = f"{plural} of "
    if scope.startswith(prefix):
        return f"every {singular} of " + scope[len(prefix) :]
    raise ThingsError(f"Internal error: unsupported {singular} scope expression: {scope!r}")


def _todo_batch_applescript(scope: str, status_filter: str | None) -> str:
    """Batched AppleScript body that emits TSV rows for every todo in ``scope``.

    ``scope`` is the AppleScript element reference that selects which todos
    to read, e.g. ``"to dos"``, ``"to dos of project id \\"p1\\""``,
    ``"to dos of tag \\"Urgent\\""``. It is translated internally to the
    ``every to do ...`` form so each property can be read as a collection
    in a single Apple Event — ``id of every to do of <X>`` returns a list
    of ids in one round-trip, versus ``id of t`` inside a ``repeat`` which
    costs one Apple Event per todo.

    The ``project`` and ``area`` relationships are optional on a todo. The
    collection forms ``project of every to do of <X>`` and ``area of every
    to do of <X>`` raise when any element has no project/area attached, so
    those four fields stay on per-element handlers wrapped in ``try``.
    That's still one ``repeat`` pass over the collection, but it only
    reads the four project/area fields per todo instead of all ~15.

    ``status_filter`` — when non-null, rows whose coerced status text does
    not match are omitted from ``out``. The filter runs against the
    already-batched status list, so it costs no extra Apple Events.
    """
    every_scope = _every_form("to dos", "to do", scope)

    if status_filter is not None:
        status_guard_open = (
            f"        if my _statusText(item _i of _statuses) is {_quote(status_filter)} then\n"
        )
        status_guard_close = "        end if\n"
    else:
        status_guard_open = ""
        status_guard_close = ""

    return f"""
    set _ids to id of {every_scope}
    set _n to count of _ids
    if _n is 0 then return ""
    set _names to name of {every_scope}
    set _notes to notes of {every_scope}
    set _statuses to status of {every_scope}
    set _tagNames to tag names of {every_scope}
    set _dueDates to due date of {every_scope}
    set _activationDates to activation date of {every_scope}
    set _completionDates to completion date of {every_scope}
    set _cancellationDates to cancellation date of {every_scope}
    set _creationDates to creation date of {every_scope}
    set _modificationDates to modification date of {every_scope}

    -- project and area are optional relationships; the collection form
    -- errors when any element has no project/area. Fall back to a single
    -- pass that invokes the try-wrapped per-element handlers.
    set _projectIds to {{}}
    set _projectNames to {{}}
    set _areaIds to {{}}
    set _areaNames to {{}}
    repeat with _t in ({scope})
        set end of _projectIds to my _projId(_t)
        set end of _projectNames to my _projName(_t)
        set end of _areaIds to my _areaId(_t)
        set end of _areaNames to my _areaName(_t)
    end repeat

    set out to ""
    repeat with _i from 1 to _n
{status_guard_open}        set _row to my _esc(item _i of _ids)
        set _row to _row & {_TAB_LIT} & my _esc(item _i of _names)
        set _row to _row & {_TAB_LIT} & my _esc(item _i of _notes)
        set _row to _row & {_TAB_LIT} & my _statusText(item _i of _statuses)
        set _row to _row & {_TAB_LIT} & (item _i of _projectIds)
        set _row to _row & {_TAB_LIT} & (item _i of _projectNames)
        set _row to _row & {_TAB_LIT} & (item _i of _areaIds)
        set _row to _row & {_TAB_LIT} & (item _i of _areaNames)
        set _row to _row & {_TAB_LIT} & my _esc(item _i of _tagNames)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _dueDates)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _activationDates)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _completionDates)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _cancellationDates)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _creationDates)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _modificationDates)
        set out to out & _row & {_LF_LIT}
{status_guard_close}    end repeat
    return out
"""


def _project_batch_applescript(scope: str) -> str:
    """Batched AppleScript body for :func:`ThingsApplescriptClient.list_projects`.

    See :func:`_todo_batch_applescript` for the rationale. Projects always
    have an area relationship available via the same try-wrapped handlers,
    so we use the same per-element fallback for those fields.
    """
    every_scope = _every_form("projects", "project", scope)

    return f"""
    set _ids to id of {every_scope}
    set _n to count of _ids
    if _n is 0 then return ""
    set _names to name of {every_scope}
    set _notes to notes of {every_scope}
    set _statuses to status of {every_scope}
    set _tagNames to tag names of {every_scope}
    set _dueDates to due date of {every_scope}
    set _activationDates to activation date of {every_scope}
    set _completionDates to completion date of {every_scope}
    set _cancellationDates to cancellation date of {every_scope}
    set _creationDates to creation date of {every_scope}
    set _modificationDates to modification date of {every_scope}

    set _areaIds to {{}}
    set _areaNames to {{}}
    repeat with _p in ({scope})
        set end of _areaIds to my _areaId(_p)
        set end of _areaNames to my _areaName(_p)
    end repeat

    set out to ""
    repeat with _i from 1 to _n
        set _row to my _esc(item _i of _ids)
        set _row to _row & {_TAB_LIT} & my _esc(item _i of _names)
        set _row to _row & {_TAB_LIT} & my _esc(item _i of _notes)
        set _row to _row & {_TAB_LIT} & my _statusText(item _i of _statuses)
        set _row to _row & {_TAB_LIT} & (item _i of _areaIds)
        set _row to _row & {_TAB_LIT} & (item _i of _areaNames)
        set _row to _row & {_TAB_LIT} & my _esc(item _i of _tagNames)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _dueDates)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _activationDates)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _completionDates)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _cancellationDates)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _creationDates)
        set _row to _row & {_TAB_LIT} & my _iso(item _i of _modificationDates)
        set out to out & _row & {_LF_LIT}
    end repeat
    return out
"""


def _area_batch_applescript() -> str:
    """Batched AppleScript body for :func:`ThingsApplescriptClient.list_areas`."""
    return f"""
    set _ids to id of every area
    set _n to count of _ids
    if _n is 0 then return ""
    set _names to name of every area
    set _tagNames to tag names of every area
    set out to ""
    repeat with _i from 1 to _n
        set _row to my _esc(item _i of _ids)
        set _row to _row & {_TAB_LIT} & my _esc(item _i of _names)
        set _row to _row & {_TAB_LIT} & my _esc(item _i of _tagNames)
        set out to out & _row & {_LF_LIT}
    end repeat
    return out
"""


@dataclass
class TodoFilter:
    list_id: str | None = None
    project_id: str | None = None
    area_id: str | None = None
    tag: str | None = None
    status: str | None = None


class AppleScriptRunner:
    """Runs AppleScript by shelling out to ``osascript``."""

    def __init__(self, osascript_path: str = "/usr/bin/osascript", timeout_seconds: float = 30.0):
        self._osascript_path = osascript_path
        self._timeout_seconds = timeout_seconds

    def run(self, script: str) -> str:
        try:
            result = subprocess.run(
                [self._osascript_path, "-"],
                input=script,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise ThingsError(f"osascript not found at {self._osascript_path}") from exc
        except subprocess.TimeoutExpired as exc:
            # Mirror the non-zero exit diagnostic: keep the stderr detail on
            # the process's own stderr while raising a sparse ThingsError so
            # callers can distinguish timeouts from other unavailable causes.
            # TimeoutExpired carries any partial stderr captured before the
            # kill — surface it so a permissions prompt or similar hint
            # doesn't get dropped.
            partial = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
            print(
                f"things-client-cli-applescript: osascript timed out after "
                f"{self._timeout_seconds}s: {partial or '<empty stderr>'}",
                file=sys.stderr,
                flush=True,
            )
            raise ThingsError(f"osascript timed out after {self._timeout_seconds}s") from exc

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            # Forward the raw osascript diagnostic to stderr so operators
            # can diagnose failures. The CLI JSON body is intentionally
            # sparse (see cli.py) to avoid leaking host paths or script
            # fragments to callers — the parent bridge strips this stderr
            # from the HTTP response for the same reason.
            print(
                f"things-client-cli-applescript: osascript failed "
                f"(rc={result.returncode}): {stderr or '<empty stderr>'}",
                file=sys.stderr,
                flush=True,
            )
            if "-1743" in stderr:
                raise ThingsPermissionError(
                    "macOS Automation permission has not been granted for Things3. "
                    "Grant it in System Settings → Privacy & Security → Automation."
                )
            if "-1728" in stderr or "-1719" in stderr:
                raise ThingsNotFoundError(stderr)
            raise ThingsError(stderr or "osascript failed without a message")
        return result.stdout


def _unescape(value: str) -> str:
    return value.replace(TAB_PLACEHOLDER, "\t").replace(NEWLINE_PLACEHOLDER, "\n")


def _field(value: str) -> str | None:
    if value == MISSING:
        return None
    return _unescape(value)


def _tag_list(value: str) -> list[str]:
    decoded = _field(value)
    if not decoded:
        return []
    return [t.strip() for t in decoded.split(",") if t.strip()]


def _parse_rows(output: str, expected_cols: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_line in output.splitlines():
        if not raw_line:
            continue
        parts = raw_line.split("\t")
        if len(parts) != expected_cols:
            raise ThingsError(
                f"Unexpected column count from AppleScript: "
                f"got {len(parts)}, expected {expected_cols}"
            )
        rows.append(parts)
    return rows


def _row_to_todo(row: list[str]) -> Todo:
    cols = dict(zip(_TODO_FIELDS, row, strict=False))
    project_id_raw = _field(cols["project_id"])
    area_id_raw = _field(cols["area_id"])
    return Todo(
        id=TodoId(_field(cols["id"]) or ""),
        name=_field(cols["name"]) or "",
        notes=_field(cols["notes"]) or "",
        status=_field(cols["status"]) or "open",
        project_id=ProjectId(project_id_raw) if project_id_raw is not None else None,
        project_name=_field(cols["project_name"]),
        area_id=AreaId(area_id_raw) if area_id_raw is not None else None,
        area_name=_field(cols["area_name"]),
        tag_names=_tag_list(cols["tag_names"]),
        due_date=_field(cols["due_date"]),
        activation_date=_field(cols["activation_date"]),
        completion_date=_field(cols["completion_date"]),
        cancellation_date=_field(cols["cancellation_date"]),
        creation_date=_field(cols["creation_date"]),
        modification_date=_field(cols["modification_date"]),
    )


def _row_to_project(row: list[str]) -> Project:
    cols = dict(zip(_PROJECT_FIELDS, row, strict=False))
    area_id_raw = _field(cols["area_id"])
    return Project(
        id=ProjectId(_field(cols["id"]) or ""),
        name=_field(cols["name"]) or "",
        notes=_field(cols["notes"]) or "",
        status=_field(cols["status"]) or "open",
        area_id=AreaId(area_id_raw) if area_id_raw is not None else None,
        area_name=_field(cols["area_name"]),
        tag_names=_tag_list(cols["tag_names"]),
        due_date=_field(cols["due_date"]),
        activation_date=_field(cols["activation_date"]),
        completion_date=_field(cols["completion_date"]),
        cancellation_date=_field(cols["cancellation_date"]),
        creation_date=_field(cols["creation_date"]),
        modification_date=_field(cols["modification_date"]),
    )


def _row_to_area(row: list[str]) -> Area:
    cols = dict(zip(_AREA_FIELDS, row, strict=False))
    return Area(
        id=AreaId(_field(cols["id"]) or ""),
        name=_field(cols["name"]) or "",
        tag_names=_tag_list(cols["tag_names"]),
    )


_FORBIDDEN_ID_CHARS = {
    "\r",
    "\n",
    "\t",
    "\0",
    TAB_PLACEHOLDER,
    NEWLINE_PLACEHOLDER,
}


def _quote(value: str) -> str:
    """AppleScript string-literal quoting for caller-supplied ids, names, and tags.

    Rejects any input containing characters that cannot appear inside a
    single-line AppleScript string literal, that would corrupt the TSV framing,
    or that could otherwise alter the surrounding script. This is the primary
    defence against AppleScript injection via URL-derived ids. Query-parameter
    inputs (``list``, ``project``, ``area``, ``tag``) reach this function
    without passing through ``_safe_id`` on the server, so the control-char
    check must be at least as strict as ``_safe_id`` (C0 range plus DEL).
    """
    for ch in value:
        if ch in _FORBIDDEN_ID_CHARS or ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise ThingsError(
                "Invalid character in Things identifier (control or framing character rejected)"
            )
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _todo_source(flt: TodoFilter) -> str:
    """Build the AppleScript source expression that yields the todos to iterate."""
    if flt.project_id is not None:
        return f"to dos of project id {_quote(flt.project_id)}"
    if flt.area_id is not None:
        return f"to dos of area id {_quote(flt.area_id)}"
    if flt.list_id is not None:
        return f"to dos of list id {_quote(flt.list_id)}"
    if flt.tag is not None:
        return f"to dos of tag {_quote(flt.tag)}"
    return "to dos"


class ThingsApplescriptClient:
    """High-level read-only API for Things 3 built on top of :class:`AppleScriptRunner`."""

    def __init__(self, runner: AppleScriptRunner):
        self._runner = runner

    def list_todos(
        self,
        *,
        list_id: str | None = None,
        project_id: str | None = None,
        area_id: str | None = None,
        tag: str | None = None,
        status: str | None = None,
    ) -> list[Todo]:
        flt = TodoFilter(
            list_id=list_id,
            project_id=project_id,
            area_id=area_id,
            tag=tag,
            status=validate_status(status),
        )
        source = _todo_source(flt)
        body = _todo_batch_applescript(source, flt.status)
        script = f"""
{_HELPERS}

tell application "Things3"
{body}end tell
"""
        output = self._runner.run(script)
        return [_row_to_todo(row) for row in _parse_rows(output, len(_TODO_FIELDS))]

    def get_todo(self, todo_id: str) -> Todo:
        body = _todo_row_applescript("t")
        script = f"""
{_HELPERS}

tell application "Things3"
    set out to ""
    try
        set t to to do id {_quote(todo_id)}
    on error errMsg number errNum
        if errNum is -1728 or errNum is -1719 then
            error "not_found:" & errNum
        end if
        error errMsg
    end try
{body}    return out
end tell
"""
        output = self._runner.run(script)
        rows = _parse_rows(output, len(_TODO_FIELDS))
        if not rows:
            raise ThingsNotFoundError(f"todo {todo_id!r} not found")
        return _row_to_todo(rows[0])

    def list_projects(self, *, area_id: str | None = None) -> list[Project]:
        source = f"projects of area id {_quote(area_id)}" if area_id is not None else "projects"
        body = _project_batch_applescript(source)
        script = f"""
{_HELPERS}

tell application "Things3"
{body}end tell
"""
        output = self._runner.run(script)
        return [_row_to_project(row) for row in _parse_rows(output, len(_PROJECT_FIELDS))]

    def get_project(self, project_id: str) -> Project:
        body = _project_row_applescript("p")
        script = f"""
{_HELPERS}

tell application "Things3"
    set out to ""
    try
        set p to project id {_quote(project_id)}
    on error errMsg number errNum
        if errNum is -1728 or errNum is -1719 then
            error "not_found:" & errNum
        end if
        error errMsg
    end try
{body}    return out
end tell
"""
        output = self._runner.run(script)
        rows = _parse_rows(output, len(_PROJECT_FIELDS))
        if not rows:
            raise ThingsNotFoundError(f"project {project_id!r} not found")
        return _row_to_project(rows[0])

    def list_areas(self) -> list[Area]:
        body = _area_batch_applescript()
        script = f"""
{_HELPERS}

tell application "Things3"
{body}end tell
"""
        output = self._runner.run(script)
        return [_row_to_area(row) for row in _parse_rows(output, len(_AREA_FIELDS))]

    def get_area(self, area_id: str) -> Area:
        body = _area_row_applescript("a")
        script = f"""
{_HELPERS}

tell application "Things3"
    set out to ""
    try
        set a to area id {_quote(area_id)}
    on error errMsg number errNum
        if errNum is -1728 or errNum is -1719 then
            error "not_found:" & errNum
        end if
        error errMsg
    end try
{body}    return out
end tell
"""
        output = self._runner.run(script)
        rows = _parse_rows(output, len(_AREA_FIELDS))
        if not rows:
            raise ThingsNotFoundError(f"area {area_id!r} not found")
        return _row_to_area(rows[0])


__all__ = [
    "AppleScriptRunner",
    "ThingsApplescriptClient",
    "TodoFilter",
]
