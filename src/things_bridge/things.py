"""AppleScript runner and high-level Things client.

The runner shells out to ``osascript`` to execute AppleScript against Things 3.
The client builds AppleScript that emits a tab-separated, record-per-line stream
so results parse cleanly without a JSON dependency on the AppleScript side.

Tabs and newlines in note/name fields are escaped into private-use unicode
separators (U+241E for tab, U+241F for newline) inside AppleScript, and
un-escaped by the parser so free-form text survives the framing.
"""

import subprocess
from dataclasses import dataclass

from things_bridge.errors import ThingsError, ThingsNotFoundError, ThingsPermissionError
from things_bridge.models import Area, Project, Todo

TAB_PLACEHOLDER = "\u241e"
NEWLINE_PLACEHOLDER = "\u241f"
MISSING = "missing value"

# AppleScript helper installed at the top of every emitted script.
# Escapes tabs/newlines/carriage returns into unicode placeholders and
# coerces missing value to the literal "missing value" so the parser
# can treat it uniformly.
_HELPERS = r"""
on _esc(v)
    if v is missing value then return "missing value"
    set s to v as text
    set out to ""
    repeat with i from 1 to count of characters of s
        set c to character i of s
        if c is tab then
            set out to out & "\u241e"
        else if c is return or c is linefeed then
            set out to out & "\u241f"
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
    if s is open then
        return "open"
    else if s is completed then
        return "completed"
    else if s is canceled then
        return "canceled"
    else
        return "open"
    end if
end _statusText
"""

_TAB_LIT = "\"\\t\""
_LF_LIT = "\"\\n\""

# Columns emitted for each todo, in order.
_TODO_FIELDS = [
    "id", "name", "notes", "status",
    "project_id", "project_name", "area_id", "area_name",
    "tag_names", "due_date", "activation_date",
    "completion_date", "cancellation_date",
    "creation_date", "modification_date",
]

# Columns emitted for each project, in order.
_PROJECT_FIELDS = [
    "id", "name", "notes", "status",
    "area_id", "area_name", "tag_names",
    "due_date", "activation_date",
    "completion_date", "cancellation_date",
    "creation_date", "modification_date",
]

# Columns emitted for each area, in order.
_AREA_FIELDS = ["id", "name", "tag_names"]


def _todo_row_applescript(var: str) -> str:
    """AppleScript that appends one todo's TSV row to the `out` accumulator."""
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
    return f"""
                set _row to my _esc(id of {var})
                set _row to _row & {_TAB_LIT} & my _esc(name of {var})
                set _row to _row & {_TAB_LIT} & my _esc(tag names of {var})
                set out to out & _row & {_LF_LIT}
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

    def __init__(self, osascript_path: str = "/usr/bin/osascript", timeout: float = 30.0):
        self._osascript_path = osascript_path
        self._timeout = timeout

    def run(self, script: str) -> str:
        try:
            result = subprocess.run(
                [self._osascript_path, "-"],
                input=script,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except FileNotFoundError as exc:
            raise ThingsError(f"osascript not found at {self._osascript_path}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ThingsError(f"osascript timed out after {self._timeout}s") from exc

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
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
                f"Unexpected column count from AppleScript: got {len(parts)}, expected {expected_cols}"
            )
        rows.append(parts)
    return rows


def _row_to_todo(row: list[str]) -> Todo:
    cols = dict(zip(_TODO_FIELDS, row))
    return Todo(
        id=_field(cols["id"]) or "",
        name=_field(cols["name"]) or "",
        notes=_field(cols["notes"]) or "",
        status=_field(cols["status"]) or "open",
        project_id=_field(cols["project_id"]),
        project_name=_field(cols["project_name"]),
        area_id=_field(cols["area_id"]),
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
    cols = dict(zip(_PROJECT_FIELDS, row))
    return Project(
        id=_field(cols["id"]) or "",
        name=_field(cols["name"]) or "",
        notes=_field(cols["notes"]) or "",
        status=_field(cols["status"]) or "open",
        area_id=_field(cols["area_id"]),
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
    cols = dict(zip(_AREA_FIELDS, row))
    return Area(
        id=_field(cols["id"]) or "",
        name=_field(cols["name"]) or "",
        tag_names=_tag_list(cols["tag_names"]),
    )


_FORBIDDEN_ID_CHARS = {
    "\r", "\n", "\t", "\0",
    TAB_PLACEHOLDER, NEWLINE_PLACEHOLDER,
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


_VALID_STATUSES = {"open", "completed", "canceled"}


def _validate_status(status: str | None) -> str | None:
    if status is None:
        return None
    if status not in _VALID_STATUSES:
        raise ThingsError(
            f"Invalid status filter: {status!r} (expected one of {sorted(_VALID_STATUSES)})"
        )
    return status


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
            list_id=list_id, project_id=project_id, area_id=area_id,
            tag=tag, status=_validate_status(status),
        )
        source = _todo_source(flt)
        body = _todo_row_applescript("t")
        if flt.status:
            body = (
                f"                if my _statusText(status of t) is {_quote(flt.status)} then\n"
                f"{body}"
                f"                end if\n"
            )
        script = f"""
{_HELPERS}

tell application "Things3"
    set out to ""
    repeat with t in ({source})
{body}    end repeat
    return out
end tell
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
        if area_id is not None:
            source = f"projects of area id {_quote(area_id)}"
        else:
            source = "projects"
        body = _project_row_applescript("p")
        script = f"""
{_HELPERS}

tell application "Things3"
    set out to ""
    repeat with p in ({source})
{body}    end repeat
    return out
end tell
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
        body = _area_row_applescript("a")
        script = f"""
{_HELPERS}

tell application "Things3"
    set out to ""
    repeat with a in areas
{body}    end repeat
    return out
end tell
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
