"""Subprocess-backed :class:`ThingsClient` used by things-bridge.

The bridge no longer embeds Things 3 logic. Each request is translated
into an argv for the configured ``things_client_command`` (default:
``things-client-cli-applescript``), which returns a JSON envelope on
stdout. This module is the only place the bridge reasons about the
subprocess protocol.
"""

import json
import subprocess
import sys

from things_models.errors import (
    ThingsError,
    ThingsNotFoundError,
    ThingsPermissionError,
)
from things_models.models import Area, Project, Todo


class ThingsSubprocessClient:
    """Invoke a configured Things client CLI as a subprocess per request.

    ``command`` is the argv prefix (e.g. ``["things-client-cli-applescript"]``
    or ``[sys.executable, "-m", "tests.things_client_fake", "--fixtures", P]``);
    sub-commands matching the request are appended. ``timeout_seconds`` caps
    the per-call wall clock. Subprocess stderr is forwarded to the bridge's
    own stderr for operator diagnostics; the HTTP response body never
    contains subprocess output.
    """

    def __init__(self, command: list[str], timeout_seconds: float = 35.0):
        if not command:
            raise ValueError("ThingsSubprocessClient: command must not be empty")
        self._command = list(command)
        self._timeout_seconds = timeout_seconds

    def list_todos(
        self,
        *,
        list_id: str | None = None,
        project_id: str | None = None,
        area_id: str | None = None,
        tag: str | None = None,
        status: str | None = None,
    ) -> list[Todo]:
        argv = ["todos", "list"]
        if list_id is not None:
            argv.extend(["--list", list_id])
        if project_id is not None:
            argv.extend(["--project", project_id])
        if area_id is not None:
            argv.extend(["--area", area_id])
        if tag is not None:
            argv.extend(["--tag", tag])
        if status is not None:
            argv.extend(["--status", status])
        payload = self._invoke(argv)
        return [Todo.from_json(t) for t in payload.get("todos", [])]

    def get_todo(self, todo_id: str) -> Todo:
        payload = self._invoke(["todos", "show", todo_id])
        return Todo.from_json(payload["todo"])

    def list_projects(self, *, area_id: str | None = None) -> list[Project]:
        argv = ["projects", "list"]
        if area_id is not None:
            argv.extend(["--area", area_id])
        payload = self._invoke(argv)
        return [Project.from_json(p) for p in payload.get("projects", [])]

    def get_project(self, project_id: str) -> Project:
        payload = self._invoke(["projects", "show", project_id])
        return Project.from_json(payload["project"])

    def list_areas(self) -> list[Area]:
        payload = self._invoke(["areas", "list"])
        return [Area.from_json(a) for a in payload.get("areas", [])]

    def get_area(self, area_id: str) -> Area:
        payload = self._invoke(["areas", "show", area_id])
        return Area.from_json(payload["area"])

    def _invoke(self, argv: list[str]) -> dict:
        full_command = [*self._command, *argv]
        try:
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise ThingsError(f"things client not found at {self._command[0]!r}") from exc
        except subprocess.TimeoutExpired as exc:
            partial = (exc.stderr or "").strip()
            print(
                f"things-bridge: things client subprocess timed out after "
                f"{self._timeout_seconds}s: {partial or '<empty stderr>'}",
                file=sys.stderr,
                flush=True,
            )
            raise ThingsError(
                f"things client subprocess timed out after {self._timeout_seconds}s"
            ) from exc

        stderr = (result.stderr or "").strip()
        if stderr:
            # Forward client stderr so operators see osascript diagnostics,
            # fixture-load errors, etc. HTTP responses never include it.
            print(stderr, file=sys.stderr, flush=True)

        payload = _parse_payload(result.stdout or "", full_command, result.returncode)

        if "error" in payload:
            raise _error_from_payload(payload)

        if result.returncode != 0:
            raise ThingsError(
                f"things client exited {result.returncode} without a structured error body"
            )

        return payload


def _parse_payload(stdout: str, command: list[str], returncode: int) -> dict:
    if not stdout or stdout.isspace():
        raise ThingsError(f"things client {command[0]!r} emitted no JSON output (rc={returncode})")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ThingsError(
            f"things client {command[0]!r} emitted non-JSON output (rc={returncode})"
        ) from exc
    if not isinstance(payload, dict):
        raise ThingsError(
            f"things client {command[0]!r} emitted non-object JSON "
            f"(rc={returncode}, got {type(payload).__name__})"
        )
    return payload


def _error_from_payload(payload: dict) -> ThingsError:
    code = payload.get("error")
    detail = payload.get("detail") or ""
    if code == "not_found":
        return ThingsNotFoundError(detail or "not found")
    if code == "things_permission_denied":
        return ThingsPermissionError(detail or "permission denied")
    message = f"{code}: {detail}" if code and detail else detail or code or "things unavailable"
    return ThingsError(message)


__all__ = ["ThingsSubprocessClient"]
