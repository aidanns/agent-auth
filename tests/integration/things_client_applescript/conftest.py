"""Docker-backed fixtures for the things-client-cli contract tests.

The things-client-cli-applescript binary is macOS-only — its osascript
calls cannot run in a Linux container. The JSON-on-stdout / exit-code
contract that ``things-bridge`` depends on, however, lives in
``things_client_common.cli`` and is shared with the in-tree fake
``tests.things_client_fake`` CLI. The fixture here builds the standard
test image and exposes a helper that runs the fake CLI inside a
short-lived container, so the wire-protocol expectations are pinned by
the same Docker pattern as the other services.

A real macOS run still owns AppleScript-specific behaviour and is
covered by the Darwin-gated tests in
``tests/test_things_client_applescript_things.py``.
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

_FAKE_FIXTURE_PATH_IN_CONTAINER = "/srv/things-fixtures/things.yaml"


@dataclass
class FakeCliRunner:
    """Run ``python -m tests.things_client_fake`` inside the test image."""

    image_tag: str
    fixtures_dir: Path

    def write_fixture(self, yaml_text: str) -> None:
        path = self.fixtures_dir / "things.yaml"
        path.write_text(yaml_text)

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        # ``--rm`` so the container is reaped immediately; ``--network none``
        # because the fake CLI never needs the network and dropping it
        # narrows the test's blast radius.
        # ``--entrypoint python`` overrides the image's default
        # ``["agent-auth", "serve"]`` ENTRYPOINT so the trailing argv is
        # interpreted by Python (running the in-tree fake CLI module),
        # not appended to ``agent-auth serve``.
        cmd = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--name",
            f"things-client-fake-{uuid.uuid4().hex[:8]}",
            "-v",
            f"{self.fixtures_dir}:/srv/things-fixtures:ro",
            "--entrypoint",
            "python",
            self.image_tag,
            "-m",
            "tests.things_client_fake",
            "--fixtures",
            _FAKE_FIXTURE_PATH_IN_CONTAINER,
            *args,
        ]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )


@pytest.fixture
def fake_cli_runner(_test_image_tag, tmp_path_factory) -> FakeCliRunner:
    fixtures_dir = tmp_path_factory.mktemp(f"things-fix-{uuid.uuid4().hex[:8]}")
    # Default to an empty fixture so callers can opt in to writing one.
    (fixtures_dir / "things.yaml").write_text("todos: []\n")
    return FakeCliRunner(image_tag=_test_image_tag, fixtures_dir=fixtures_dir)
