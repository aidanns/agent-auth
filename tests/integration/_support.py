# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared helpers for the per-service Docker integration test fixtures.

Each per-service ``conftest.py`` imports the helpers here so the
compose template renderer, container-readiness probe, and Docker
availability check have a single implementation.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_DIR = REPO_ROOT / "docker"
DOCKERFILE = DOCKER_DIR / "Dockerfile.test"
COMPOSE_TEMPLATE = DOCKER_DIR / "docker-compose.yaml"
COMPOSE_FILE_NAME = "docker-compose.yaml"
_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}")

DOCKER_BUILD_TIMEOUT_SECONDS = 600.0
READY_POLL_TIMEOUT_SECONDS = 30.0
READY_POLL_INTERVAL_SECONDS = 0.2


def docker_compose_available() -> bool:
    """Return True if both ``docker`` and ``docker compose`` work on the host."""
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "compose", "version"],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return True


def wait_until_server_ready(
    health_url: str,
    *,
    accept_status: tuple[int, ...] = (401, 403),
) -> None:
    """Block until ``health_url`` answers, treating ``accept_status`` as up.

    Both health endpoints (``agent-auth/health`` and
    ``things-bridge/health``) require a scoped bearer token, so an
    unauthenticated probe returns ``401``. The fixture treats that —
    along with ``403`` (valid shape, scope missing) — as a positive
    "server is up" signal.
    """
    deadline = time.monotonic() + READY_POLL_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as resp:
                if 200 <= resp.status < 300:
                    return
        except urllib.error.HTTPError as exc:
            if exc.code in accept_status:
                return
            last_error = exc
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_error = exc
        time.sleep(READY_POLL_INTERVAL_SECONDS)
    raise RuntimeError(
        f"Service never became reachable at {health_url} within "
        f"{READY_POLL_TIMEOUT_SECONDS}s (last error: {last_error!r})"
    )


def render_compose_file(target_dir: Path, **substitutions: str) -> Path:
    """Render the compose template with double-brace placeholders
    substituted, writing the result into ``target_dir`` and returning
    the rendered path.

    The compose template carries every test-specific value as a
    double-brace placeholder so the rendered file is self-contained:
    docker compose never has to inherit env vars from the test runner,
    and there is no shared mutable state between concurrent fixture
    invocations.

    Comment lines (those whose first non-whitespace char is ``#``) are
    excluded from the leftover-placeholder check, so the template can
    document its own substitution syntax in YAML comments without
    tripping the guard.

    Raises ``KeyError`` if a substitution doesn't match any placeholder
    in the template (typo guard) or if the rendered output still
    contains an unsubstituted placeholder outside a comment (forgotten
    value guard).
    """
    template = COMPOSE_TEMPLATE.read_text()
    for key, value in substitutions.items():
        placeholder = f"{{{{ {key} }}}}"
        if placeholder not in template:
            raise KeyError(f"placeholder {placeholder!r} not found in {COMPOSE_TEMPLATE.name}")
        template = template.replace(placeholder, value)
    non_comment = "\n".join(
        line for line in template.splitlines() if not line.lstrip().startswith("#")
    )
    leftover = sorted(set(_PLACEHOLDER_PATTERN.findall(non_comment)))
    if leftover:
        raise KeyError(f"unsubstituted placeholders in {COMPOSE_TEMPLATE.name}: {leftover}")
    target = target_dir / COMPOSE_FILE_NAME
    target.write_text(template)
    return target


def seed_empty_fixtures_dir(fixtures_dir: Path) -> None:
    """Write an empty ``things.yaml`` into ``fixtures_dir``.

    The combined Compose file always starts the things-bridge container
    (even for agent-auth-only tests), and the bridge invokes the fake
    Things CLI which expects a fixture file. Tests that exercise the
    bridge overwrite this file via ``ThingsBridgeStack.write_fixture``.
    """
    fixtures_dir.joinpath("things.yaml").write_text("todos: []\n")
    os.chmod(fixtures_dir, 0o755)
    os.chmod(fixtures_dir / "things.yaml", 0o644)


def build_test_image(tag: str) -> None:
    """Run ``docker build`` against ``DOCKERFILE`` and tag the result.

    Raises ``RuntimeError`` with build output on a non-zero exit so
    pytest tracebacks show why the build failed.
    """
    result = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            str(DOCKERFILE),
            "-t",
            tag,
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=DOCKER_BUILD_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"`docker build` failed for {tag}: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
