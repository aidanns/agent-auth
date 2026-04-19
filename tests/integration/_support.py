"""Shared helpers for the per-service Docker integration test fixtures.

Each per-service ``conftest.py`` imports the helpers here so the
container-readiness probe, scoped env-var management, and Docker
availability check have a single implementation.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_DIR = REPO_ROOT / "docker"
DOCKERFILE = DOCKER_DIR / "Dockerfile.test"

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

    The agent-auth health endpoint requires an ``agent-auth:health``
    token, so an unauthenticated probe returns ``401``. The fixture
    treats that — along with ``403`` (valid shape, scope missing) — as
    a positive "server is up" signal. The things-bridge health endpoint
    is unauthenticated, so any 2xx response is up.
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


@contextlib.contextmanager
def scoped_env(**values: str) -> Iterator[None]:
    """Temporarily set env vars, restoring their prior values on exit.

    The fixtures drive ``docker compose`` indirectly via
    ``testcontainers``, which invokes ``docker compose`` as a subprocess
    without an explicit ``env=`` argument — so the subprocess inherits
    whatever is in ``os.environ`` at the moment the call is made. Both
    ``compose.start()`` and ``compose.stop()`` rely on that inheritance
    (e.g. for ``COMPOSE_PROJECT_NAME``), and both must see *this*
    project's values, not whichever were last written by an unrelated
    factory invocation.
    """
    previous: dict[str, str | None] = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, prior in previous.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior


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
