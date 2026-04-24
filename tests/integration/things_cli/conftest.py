# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Docker-backed fixtures for things-cli integration tests.

Reuses the ``things_bridge_stack`` fixture (multi-service Compose
project running ``agent-auth`` + ``things-bridge``) and adds helpers
that launch the ``things-cli`` binary in its own short-lived container.
Tests exercise ``things-cli`` strictly through its argv / stdout
surface; credentials live in a per-test tmpdir on the host and are
bind-mounted read-write into each ephemeral CLI container.

Under issue #95 the CLI runs in its own image instead of
``docker compose exec``'ing into the bridge. The original ADR 0005
rationale for running inside the bridge (the 0600 credentials file
plus UID-mismatched bind mounts) goes away once the CLI owns its own
image: the credential store's ``file:``-backed path writes with
``0600`` inside the container under its own UID, and the host-side
tmpdir is created by the fixture with world-readable perms (the host
test runner needs to read the rendered file back, but any secrets it
contains were generated in-test and live and die with the fixture).
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

# Re-export the Compose stack fixtures from the sibling things_bridge
# conftest. Sibling conftest.py modules don't share fixtures by default;
# importing the fixture functions into this conftest's namespace makes
# them visible to tests under this directory without needing
# ``pytest_plugins`` (which pytest forbids in non-top-level conftests).
from tests.integration.things_bridge.conftest import (  # noqa: F401
    ThingsBridgeStack,
    things_bridge_stack,
    things_bridge_stack_factory,
)

# Stack pinning: this fixture inherits its Compose topology from
# ``docker/docker-compose.yaml`` via the imported ``ThingsBridgeStack``
# — the ``things-cli`` service is defined alongside ``agent-auth`` and
# ``things-bridge`` in that file and launched per-test via
# ``docker compose run --rm things-cli``.


# Credential file lives inside a per-test tmpdir that is bind-mounted
# into the CLI container. ``_CREDS_FILENAME`` is written once per test
# before the first ``run()`` call; the CLI re-writes it in-place under
# login/refresh. ``_CREDS_PATH_IN_CONTAINER`` is where the fixture
# mounts the tmpdir so the CLI's ``--credentials-file`` argument stays
# stable regardless of host-side path layout.
_CREDS_FILENAME = "credentials.yaml"
_CREDS_PATH_IN_CONTAINER = f"/tmp/things-cli-creds/{_CREDS_FILENAME}"


@dataclass
class ThingsCliInvoker:
    """Run ``things-cli`` in its own ephemeral container against the test stack."""

    stack: ThingsBridgeStack
    creds_dir: Path

    def run(self, *args: str) -> tuple[int, str, str]:
        """Run ``things-cli`` with the file-backed credential store.

        Returns ``(exit_code, stdout, stderr)``. Uses ``docker compose
        run --rm things-cli`` so the CLI executes in its own container
        (issue #95) rather than sharing the bridge's process space.
        ``-T`` disables TTY allocation so stdout / stderr reach the
        subprocess verbatim without termios munging.

        ``-f stack.compose_file`` points at the rendered, per-test
        compose file (which carries the project name via compose v2's
        ``name:`` field), so docker compose addresses the right project
        without any env-var inheritance.
        """
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                self.stack.compose_file,
                "run",
                "-T",
                "--rm",
                "--volume",
                f"{self.creds_dir}:/tmp/things-cli-creds",
                "things-cli",
                "things-cli",
                "--credential-store",
                "file",
                "--credentials-file",
                _CREDS_PATH_IN_CONTAINER,
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr

    def run_ok(self, *args: str) -> str:
        """Run ``things-cli`` and return stdout, raising on non-zero exit."""
        exit_code, stdout, stderr = self.run(*args)
        if exit_code != 0:
            raise RuntimeError(
                f"`things-cli {' '.join(args)}` failed: "
                f"exit={exit_code} stdout={stdout!r} stderr={stderr!r}"
            )
        return stdout

    def login(self, token_payload: dict[str, Any]) -> None:
        """Persist credentials for a token-create payload."""
        # The bridge talks to agent-auth on the in-network address;
        # things-cli does too because it issues refresh / reissue
        # requests directly to the auth server. The bridge URL points
        # at the same things-bridge container we are exec'ing into.
        self.run_ok(
            "login",
            "--bridge-url",
            "http://things-bridge:9200",
            "--auth-url",
            "http://agent-auth:9100",
            "--access-token",
            token_payload["access_token"],
            "--refresh-token",
            token_payload["refresh_token"],
            "--family-id",
            token_payload["family_id"],
        )


@pytest.fixture
def things_cli_invoker(
    things_bridge_stack: ThingsBridgeStack,  # noqa: F811 — pytest re-export
    tmp_path_factory: pytest.TempPathFactory,
) -> ThingsCliInvoker:
    """Default invoker — fresh credentials tmpdir per test."""
    creds_dir = tmp_path_factory.mktemp(f"things-cli-creds-{uuid.uuid4().hex[:8]}")
    # Ensure the bind-mount target is readable/writable by the
    # container's UID 1001 user; pytest's tmpdirs default to 0700.
    os.chmod(creds_dir, 0o777)
    return ThingsCliInvoker(stack=things_bridge_stack, creds_dir=creds_dir)


@pytest.fixture
def things_cli_logged_in(
    things_cli_invoker: ThingsCliInvoker,
) -> ThingsCliInvoker:
    """Invoker pre-loaded with a ``things:read`` token persisted in the
    container's credential file.

    Tests that just want to drive read endpoints can request this
    fixture instead of repeating the seed-and-login dance.
    """
    things_cli_invoker.stack.write_fixture(_DEFAULT_FIXTURE)
    payload = things_cli_invoker.stack.agent_auth.create_token("things:read=allow")
    things_cli_invoker.login(payload)
    return things_cli_invoker


_DEFAULT_FIXTURE = {
    "areas": [{"id": "a1", "name": "Personal", "tag_names": []}],
    "projects": [{"id": "p1", "name": "Q2", "area_id": "a1", "area_name": "Personal"}],
    "todos": [
        {
            "id": "t1",
            "name": "Buy milk",
            "area_id": "a1",
            "area_name": "Personal",
            "tag_names": ["Errand"],
        },
        {
            "id": "t2",
            "name": "Write report",
            "project_id": "p1",
            "project_name": "Q2",
            "status": "open",
        },
    ],
    "list_memberships": {},
}


def parse_json(stdout: str) -> dict[str, Any]:
    """Parse ``things-cli --json`` stdout, raising on empty payloads."""
    stripped = stdout.strip()
    if not stripped:
        raise AssertionError("expected JSON on stdout but got empty output")
    return cast(dict[str, Any], json.loads(stripped))
