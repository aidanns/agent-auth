# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Per-package conftest for gpg-bridge integration tests.

Container fixtures (``gpg_bridge_stack``, ``gpg_bridge_stack_factory``,
the shared ``_test_image_tags`` builder) are registered by
:mod:`tests_support.integration.plugin`, wired in via ``addopts =
["-p", "tests_support.integration.plugin"]`` at the workspace root
``pyproject.toml``. This file adds the gpg-cli invoker — a thin
wrapper over ``docker compose run --rm gpg-cli`` that exercises the
real container-to-container ``gpg-cli → gpg-bridge`` HTTP path under
each test's per-test compose project.

Stack pinning: this fixture inherits its compose topology from
``docker/docker-compose.yaml`` via the ``GpgBridgeStack`` returned by
the shared plugin — the ``gpg-cli`` service is defined alongside
``gpg-bridge`` in that file (under the shared ``gpg`` profile) and
launched per-test via ``docker compose run --rm gpg-cli``.
"""

from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import dataclass

import pytest

from tests_support.integration.plugin import GpgBridgeStack

# In-network address gpg-cli uses to reach the bridge. The compose
# network resolves ``gpg-bridge`` via Docker DNS — only the host-side
# test runner uses the published loopback port mapping (none of the
# test bodies below do).
_BRIDGE_URL_IN_NETWORK = "http://gpg-bridge:9300"
_GPG_CLI_RUN_TIMEOUT_SECONDS = 30.0


@dataclass
class GpgCliInvoker:
    """Run ``gpg-cli`` in its own ephemeral container against the bridge.

    Mirrors :class:`tests_support.integration.plugin.AgentAuthContainer`
    in spirit: helper methods accept typed inputs and surface raw
    :class:`subprocess.CompletedProcess` results so each test reads
    as a sequence of HTTP-shaped operations rather than
    ``subprocess.run`` boilerplate, while still letting negative-path
    cases inspect exit codes verbatim.
    """

    stack: GpgBridgeStack

    def run(
        self,
        argv: list[str],
        *,
        token: str,
        stdin_bytes: bytes = b"",
        extra_env: dict[str, str] | None = None,
        entrypoint: str | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run ``gpg-cli <argv>`` (or ``entrypoint`` if set) in a fresh container.

        Returns the raw :class:`subprocess.CompletedProcess` so
        negative-path callers can inspect exit code + stderr without
        the helper deciding which exit codes are acceptable. ``token``
        is forwarded as ``AGENT_AUTH_GPG_TOKEN``; tests pass
        intentionally invalid tokens (revoked, missing scope) to
        exercise the bridge's authz path.

        ``entrypoint`` overrides the image's default ENTRYPOINT (which
        is unset in ``Dockerfile.gpg-cli.test`` — the helper prepends
        ``gpg-cli`` as the binary when no override is set). The
        verify-path helper passes ``sh`` here so it can stage the
        signature inside the container without sharing a host bind-
        mount.
        """
        cluster = self.stack.cluster
        compose_argv: list[str] = [
            "docker",
            "compose",
            *cluster.file_args(),
            "--project-name",
            cluster.project_name,
            "run",
            "-T",
            "--rm",
            "--env",
            f"AGENT_AUTH_GPG_BRIDGE_URL={_BRIDGE_URL_IN_NETWORK}",
            "--env",
            f"AGENT_AUTH_GPG_TOKEN={token}",
        ]
        for key, value in (extra_env or {}).items():
            compose_argv.extend(["--env", f"{key}={value}"])
        if entrypoint is not None:
            compose_argv.extend(["--entrypoint", entrypoint])
        compose_argv.append("gpg-cli")  # compose service name
        # When no entrypoint override is set, ``Dockerfile.gpg-cli.test``
        # has no ENTRYPOINT, so the first argv item is the binary docker
        # tries to exec. Without an explicit ``gpg-cli`` here docker
        # would try to exec the first flag (e.g. ``--status-fd``) as a
        # binary and fail with "executable file not found in $PATH".
        # The entrypoint=sh path (verify) skips this prefix because
        # ``sh -c '...'`` runs gpg-cli itself inside the script body.
        if entrypoint is None:
            compose_argv.append("gpg-cli")  # binary
        compose_argv.extend(argv)

        env = {**os.environ, **cluster.env}
        return subprocess.run(
            compose_argv,
            env=env,
            input=stdin_bytes,
            capture_output=True,
            timeout=_GPG_CLI_RUN_TIMEOUT_SECONDS,
            check=False,
        )

    def sign(
        self,
        *,
        token: str,
        fingerprint: str,
        payload: bytes,
    ) -> subprocess.CompletedProcess[bytes]:
        """Drive a detached-armoured sign through ``gpg-cli`` like git does.

        Argv shape mirrors what ``git commit -S`` invokes (see ADR
        0033 § Supported gpg CLI surface). ``--status-fd 2`` keeps the
        ``[GNUPG:] SIG_CREATED`` marker visible on the captured
        stderr without reserving an extra fd at the subprocess layer.
        """
        return self.run(
            [
                "--status-fd",
                "2",
                "--keyid-format",
                "long",
                "-bsau",
                fingerprint,
            ],
            token=token,
            stdin_bytes=payload,
        )

    def verify(
        self,
        *,
        token: str,
        signature: bytes,
        payload: bytes,
    ) -> subprocess.CompletedProcess[bytes]:
        """Verify a detached signature against an explicit payload.

        Stages the signature on the per-call gpg-cli container's
        in-memory tmpfs (no host bind-mount, no cross-container
        sharing) and runs ``gpg-cli --verify <staged-path> -`` with
        the payload on stdin. The signature is base64-encoded into
        an env var to keep the staging shell line free of binary
        bytes; the helper script decodes it on the way to disk.
        """
        return self.run(
            argv=[
                "-c",
                # Decode the base64-encoded signature into a temp
                # file inside the container, then drive ``gpg-cli``'s
                # ``--verify <sigfile> -`` shape with the payload on
                # stdin.
                "set -eu; "
                "sig_path=$(mktemp); "
                'printf "%s" "$SIGNATURE_B64" | base64 -d > "$sig_path"; '
                'gpg-cli --status-fd 2 --verify "$sig_path" -',
            ],
            token=token,
            stdin_bytes=payload,
            entrypoint="sh",
            extra_env={"SIGNATURE_B64": base64.b64encode(signature).decode("ascii")},
        )


@pytest.fixture
def gpg_cli_invoker(gpg_bridge_stack: GpgBridgeStack) -> GpgCliInvoker:
    """Default invoker — bound to the per-test gpg-bridge stack."""
    return GpgCliInvoker(stack=gpg_bridge_stack)
