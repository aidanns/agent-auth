# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared helpers for the per-service Docker integration test fixtures.

Per-service conftests use the :mod:`tests.integration.harness` builder
to drive the compose lifecycle. The helpers here cover everything
adjacent to that: session-scoped per-service image builds (with
optional GitHub Actions cache passthrough), the docker availability
probe, the empty ``things.yaml`` seed for the bridge bind-mount, and
the structured phase-timing logger.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_DIR = REPO_ROOT / "docker"
COMPOSE_FILE = DOCKER_DIR / "docker-compose.yaml"

DOCKER_BUILD_TIMEOUT_SECONDS = 600.0

# Mapping from service name (as used by the Compose topology) to the
# per-service Dockerfile that builds its integration test image. One
# image is built per entry on first use of the ``_test_image_tags``
# session fixture; ``Dockerfile.<service>.test`` matches the on-disk
# naming convention.
PER_SERVICE_DOCKERFILES: dict[str, Path] = {
    "agent-auth": DOCKER_DIR / "Dockerfile.agent-auth.test",
    "things-bridge": DOCKER_DIR / "Dockerfile.things-bridge.test",
    "things-cli": DOCKER_DIR / "Dockerfile.things-cli.test",
    "things-client-applescript": DOCKER_DIR / "Dockerfile.things-client-applescript.test",
}

# Phase timings are emitted as INFO logs on the ``integration.timing``
# logger so CI can surface them with ``-o log_cli=true``. The
# structured ``phase=<name> elapsed_seconds=<n>`` shape is grep-friendly
# and survives pytest's per-test capture.
_timing_log = logging.getLogger("integration.timing")


@contextmanager
def phase_timer(phase: str, **fields: object) -> Iterator[None]:
    """Log wall-clock time spent inside the ``with`` block.

    Extra ``fields`` are appended as ``key=value`` pairs so callers can
    correlate phases (e.g. compose project name, image tag) without
    parsing test ids.
    """
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        suffix = "".join(f" {k}={v}" for k, v in fields.items())
        _timing_log.info("phase=%s elapsed_seconds=%.3f%s", phase, elapsed, suffix)


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


def seed_empty_fixtures_dir(fixtures_dir: Path) -> None:
    """Write an empty ``things.yaml`` into ``fixtures_dir``.

    The shared Compose file always starts the things-bridge container
    (even for agent-auth-only tests), and the bridge invokes the fake
    Things CLI which expects a fixture file. Tests that exercise the
    bridge overwrite this file via ``ThingsBridgeStack.write_fixture``.
    """
    fixtures_dir.joinpath("things.yaml").write_text("todos: []\n")
    os.chmod(fixtures_dir, 0o755)
    os.chmod(fixtures_dir / "things.yaml", 0o644)


def build_test_image(dockerfile: Path, tag: str) -> None:
    """Run ``docker build -f <dockerfile>`` and tag the result.

    Raises ``RuntimeError`` with build output on a non-zero exit so
    pytest tracebacks show why the build failed.

    When ``AGENT_AUTH_DOCKER_CACHE=gha`` is set, the build opts in to
    GitHub Actions cache via buildx (``--cache-from`` /
    ``--cache-to type=gha``) under a per-service scope derived from
    the Dockerfile name (``Dockerfile.<service>.test`` →
    ``<service>-test``). The CI integration jobs go through
    ``.github/actions/build-integration-test-image`` today, so this
    branch is primarily a local-dev / non-CI-script escape hatch. Any
    other value of the env var falls back to classic ``docker build``
    so local runs without buildx don't pay the setup cost.
    """
    cache_args = _gha_cache_args(dockerfile)
    with phase_timer("build_test_image", dockerfile=dockerfile.name, tag=tag):
        result = subprocess.run(
            [
                "docker",
                "build",
                *cache_args,
                "-f",
                str(dockerfile),
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
            f"`docker build` failed for {tag} ({dockerfile.name}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


def _gha_cache_args(dockerfile: Path) -> list[str]:
    """Return buildx cache flags appropriate for the ambient env.

    Caller sets ``AGENT_AUTH_DOCKER_CACHE=gha`` to opt in. The cache
    scope is derived from the Dockerfile's per-service suffix so a
    Dockerfile edit on one service doesn't evict the cache for the
    others. Returns ``[]`` when caching is disabled; callers splat
    the result into their ``docker build`` argv with ``*``.
    """
    if os.environ.get("AGENT_AUTH_DOCKER_CACHE") != "gha":
        return []
    scope = _cache_scope_for_dockerfile(dockerfile)
    return [
        "--cache-from",
        f"type=gha,scope={scope}",
        "--cache-to",
        f"type=gha,mode=max,scope={scope}",
        "--load",
    ]


def _cache_scope_for_dockerfile(dockerfile: Path) -> str:
    """Return the cache scope string for ``dockerfile``.

    Matches the scope used by
    ``.github/actions/build-integration-test-image`` so a local run
    under ``AGENT_AUTH_DOCKER_CACHE=gha`` shares the same cache key
    space as CI — useful for anyone driving a GHA-cache-backed
    buildx builder locally.
    """
    # ``Dockerfile.things-bridge.test`` → scope ``things-bridge-test``.
    stem = dockerfile.stem  # ``Dockerfile.things-bridge``
    service = stem.removeprefix("Dockerfile.")
    return f"{service}-test"
