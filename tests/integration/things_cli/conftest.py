# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Docker-backed fixtures for things-cli integration tests.

Reuses the ``things_bridge_stack`` fixture (multi-service Compose
project running ``agent-auth`` + ``things-bridge``) and adds helpers to
invoke the ``things-cli`` binary inside the bridge container. Tests
exercise ``things-cli`` strictly through its argv / stdout surface,
with credentials persisted to a per-test path inside the container.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass

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
# — things-cli runs inside that bridge container.


# Credential file lives inside the container so the test never has to
# resolve UID-mismatched bind-mount permissions for a 0600 file. The
# path is per-test so concurrent tests on the same Compose project
# (none today, but the contract is cheap to preserve) cannot collide.
_CREDS_PATH_TEMPLATE = "/tmp/things-cli-creds-{}.yaml"


@dataclass
class ThingsCliInvoker:
    """Run the in-container ``things-cli`` against the test stack."""

    stack: ThingsBridgeStack
    creds_path: str

    def run(self, *args: str) -> tuple[int, str, str]:
        """Run ``things-cli`` with the file-backed credential store.

        Returns ``(exit_code, stdout, stderr)``. Calls ``docker compose
        exec`` directly because ``testcontainers``'s ``exec_in_container``
        wraps ``subprocess.run(check=True)`` and raises on non-zero exit
        — which would prevent negative-path tests from inspecting the
        CLI's ``BridgeForbiddenError``/``NotFoundError`` exit codes.

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
                "exec",
                "-T",
                "things-bridge",
                "things-cli",
                "--credential-store",
                "file",
                "--credentials-file",
                self.creds_path,
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

    def login(self, token_payload: dict) -> None:
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
) -> ThingsCliInvoker:
    """Default invoker — fresh credential file per test."""
    creds_path = _CREDS_PATH_TEMPLATE.format(uuid.uuid4().hex[:8])
    return ThingsCliInvoker(stack=things_bridge_stack, creds_path=creds_path)


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


def parse_json(stdout: str) -> dict:
    """Parse ``things-cli --json`` stdout, raising on empty payloads."""
    stripped = stdout.strip()
    if not stripped:
        raise AssertionError("expected JSON on stdout but got empty output")
    return json.loads(stripped)
