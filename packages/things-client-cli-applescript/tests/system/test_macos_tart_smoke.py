# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""macOS-Tart-VM smoke test for ``things-client-cli-applescript``.

Companion to ``.github/workflows/test-system-macos-tart.yml``. The
workflow boots a clean macOS guest under Tart, installs Things 3,
seeds an ``kTCCServiceAppleEvents`` Automation grant in TCC.db,
seeds a single ``ci-smoke-todo`` to-do via raw ``osascript``, then
runs this test against ``AGENT_AUTH_REAL_THINGS3=1``. The test
exercises the full read path through real Things 3:

    things-client-cli-applescript todos list --status open
    -> osascript -> Things 3 (live) -> JSON envelope back

so a regression in the AppleScript dictionary, the ``things.py``
runner, the JSON envelope shape, or the TCC grant surfaces here.
``things-client-cli-applescript`` is read-only (the CLI does not
expose a ``todos create`` command), which is why the seed is done
with raw ``osascript`` in the workflow's bootstrap step rather than
via the CLI itself — see ADR 0047 -> "Considered alternatives".

Skip semantics:

- ``sys.platform != "darwin"`` -> skip (CLI cannot exec osascript
  off macOS).
- ``AGENT_AUTH_REAL_THINGS3 != "1"`` -> skip even on a Darwin
  developer machine, so a local ``pytest`` invocation does not
  silently mutate (or assert against) the developer's real Things
  database.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

_SEEDED_TODO_NAME = "ci-smoke-todo"


pytestmark = pytest.mark.requires_real_things3

_skip_when_not_real_things3 = pytest.mark.skipif(
    sys.platform != "darwin"
    or shutil.which("osascript") is None
    or os.environ.get("AGENT_AUTH_REAL_THINGS3") != "1",
    reason=(
        "macOS-Tart smoke test requires AGENT_AUTH_REAL_THINGS3=1 on Darwin "
        "with osascript available — set the env var only inside the boot-prepped "
        "Tart VM (see .github/workflows/test-system-macos-tart.yml)."
    ),
)


@_skip_when_not_real_things3
def test_things_client_cli_applescript_round_trips_seeded_todo() -> None:
    """End-to-end: seeded ``ci-smoke-todo`` must come back via the CLI.

    The boot-prep script wrote exactly one to-do to a freshly-installed
    Things 3 inside the Tart VM. ``todos list --status open`` must
    therefore return that single to-do — the CLI's JSON envelope is
    ``{"todos": [{...}]}`` (see
    ``packages/agent-auth-common/src/things_client_common/cli.py``;
    note that the issue brief's "data list" wording maps to the
    ``todos`` key in the actual envelope contract). Asserting the
    *exact* singleton list (rather than a permissive
    ``len(todos) >= 1``) guards against a regression where the CLI
    returns the wrong list scope or the AppleScript runner emits
    duplicates per row.
    """
    proc = subprocess.run(
        ["things-client-cli-applescript", "todos", "list", "--status", "open"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"things-client-cli-applescript exited {proc.returncode}; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    body = json.loads(proc.stdout)
    assert "todos" in body, (
        "things-client-cli-applescript envelope missing 'todos' key — "
        f"the CLI changed its contract (got keys: {sorted(body)})."
    )
    todos = body["todos"]
    assert isinstance(
        todos, list
    ), f"'todos' must be a JSON list per the contract; got {type(todos).__name__}"
    names = [t.get("name") for t in todos]
    assert names == [_SEEDED_TODO_NAME], (
        "expected exactly one seeded to-do "
        f"({_SEEDED_TODO_NAME!r}); got names={names!r}, full body={body!r}"
    )
