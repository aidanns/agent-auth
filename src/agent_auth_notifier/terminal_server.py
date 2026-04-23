# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Terminal-prompt HTTP notifier.

Serves a single endpoint (``POST /``) that reads the approval request
JSON, prompts the operator on stderr, and returns the decision. Uses
``ThreadingHTTPServer`` for the same reason agent-auth does: a
blocking ``input()`` on one request must not wedge a concurrent
health probe from the server.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast


class _TerminalApprovalHandler(BaseHTTPRequestHandler):
    """Handle a single approval request by prompting on stderr."""

    # One input() at a time — otherwise two parallel requests race
    # over the same stdin stream.
    _prompt_lock: threading.Lock = threading.Lock()

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            parsed_any = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"approved": False, "grant_type": "once"})
            return
        if not isinstance(parsed_any, dict):
            self._send_json(400, {"approved": False, "grant_type": "once"})
            return
        parsed = cast(dict[str, Any], parsed_any)
        scope = str(parsed.get("scope", ""))
        description = parsed.get("description")
        family_id = str(parsed.get("family_id", ""))

        decision = self._prompt(scope, description, family_id)
        self._send_json(200, decision)

    def _prompt(
        self,
        scope: str,
        description: object,
        family_id: str,
    ) -> dict[str, Any]:
        with self._prompt_lock:
            print(f"\n{'=' * 60}", file=sys.stderr)
            print("JIT APPROVAL REQUEST", file=sys.stderr)
            print(f"{'=' * 60}", file=sys.stderr)
            print(f"  Scope:     {scope}", file=sys.stderr)
            if description:
                print(f"  Operation: {description}", file=sys.stderr)
            print(f"  Family:    {family_id}", file=sys.stderr)
            print(file=sys.stderr)
            print("Grant options:", file=sys.stderr)
            print("  [y] Approve once", file=sys.stderr)
            print("  [s] Approve for this session (60 minutes)", file=sys.stderr)
            print("  [t] Approve for N minutes", file=sys.stderr)
            print("  [n] Deny", file=sys.stderr)
            print(f"{'=' * 60}", file=sys.stderr)
            try:
                choice = input("Choice [y/s/t/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return {"approved": False, "grant_type": "once"}

            if choice == "y":
                return {"approved": True, "grant_type": "once"}
            if choice == "s":
                return {"approved": True, "grant_type": "timed", "duration_minutes": 60}
            if choice == "t":
                try:
                    minutes = int(input("Minutes: ").strip())
                except (EOFError, KeyboardInterrupt, ValueError):
                    return {"approved": False, "grant_type": "once"}
                return {"approved": True, "grant_type": "timed", "duration_minutes": minutes}
            return {"approved": False, "grant_type": "once"}


def run_terminal_notifier(host: str, port: int) -> None:
    """Start the terminal-mode notifier and block until interrupted."""
    server = ThreadingHTTPServer((host, port), _TerminalApprovalHandler)
    bound = server.server_address[1]
    print(f"agent-auth-notifier terminal listening on http://{host}:{bound}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
