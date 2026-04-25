# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Fault-injection: backend produces malformed / oversized stdout.

The bridge contract is that the JSON envelope on the backend's stdout
is authoritative. A backend that writes non-JSON bytes, an array
instead of an object, a truncated envelope, or a multi-megabyte blob
must NOT cause the bridge to crash, hang, or echo the bad bytes back
to the caller — it must surface a typed ``GpgError`` and discard the
malformed stdout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_models.errors import GpgError
from gpg_models.models import SignRequest


def _make_executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(0o755)
    return path


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_non_json_stdout_raises_gpg_error(tmp_path: Path) -> None:
    """A backend that emits non-JSON bytes raises ``GpgError`` (not ``JSONDecodeError``)."""
    script = _make_executable(
        tmp_path / "backend_garbage.sh",
        "#!/usr/bin/env bash\nprintf '<html>not json</html>'\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="non-JSON output"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_truncated_json_raises_gpg_error(tmp_path: Path) -> None:
    """A backend that writes a half-JSON envelope and exits raises ``GpgError``.

    Mirrors the case where the backend dies (e.g. SIGPIPE on a closed
    stdout, or hits an OOM) after starting the envelope — the bridge
    must surface this as a typed JSON-shape error rather than a
    structured-error envelope from the backend.
    """
    script = _make_executable(
        tmp_path / "backend_truncated.sh",
        '#!/usr/bin/env bash\nprintf \'{"signature_b64": "abc\'\n',
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="non-JSON output"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_non_object_json_raises_gpg_error(tmp_path: Path) -> None:
    """A backend that writes a JSON array (not an object) raises ``GpgError``.

    The protocol is a JSON object envelope; an array would parse but
    fail every key lookup. Catching it at the parser level keeps the
    bridge from raising a confusing ``AttributeError`` deep in the
    handler.
    """
    script = _make_executable(
        tmp_path / "backend_array.sh",
        '#!/usr/bin/env bash\nprintf \'["not", "an", "object"]\'\n',
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="non-object JSON"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_empty_stdout_raises_gpg_error(tmp_path: Path) -> None:
    """A backend that writes nothing to stdout raises ``GpgError``.

    Distinguishes from the ``non-JSON`` path because Python's
    ``json.loads('')`` would raise its own confusing message — we
    want the bridge's ``emitted no JSON output`` framing.
    """
    script = _make_executable(
        tmp_path / "backend_empty.sh",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="emitted no JSON output"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_whitespace_only_stdout_raises_gpg_error(tmp_path: Path) -> None:
    """Whitespace-only stdout is treated as ``no JSON output``.

    Without this guard ``json.loads`` would raise a vague
    ``Expecting value`` message that's hard to triage from a log
    line.
    """
    script = _make_executable(
        tmp_path / "backend_whitespace.sh",
        "#!/usr/bin/env bash\nprintf '   \\n\\n\\t   '\n",
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=5.0)
    with pytest.raises(GpgError, match="emitted no JSON output"):
        client.sign(SignRequest(local_user="k", payload=b"x"))


@pytest.mark.covers_function("Run Backend Subprocess")
def test_backend_oversized_garbage_stdout_does_not_leak_into_response(
    tmp_path: Path,
) -> None:
    """A backend that emits ~2 MiB of garbage surfaces as ``GpgError`` without echoing bytes.

    Two failure modes this guards against:

    1. The bridge could OOM trying to ``json.loads`` a multi-megabyte
       garbage blob. ``json.loads`` allocates one parse buffer; we
       want to verify it raises cleanly rather than (e.g.) crash.
    2. The ``GpgError`` message could embed the malformed stdout,
       which would leak the bytes into the HTTP error body the bridge
       sends back to a caller. The current implementation only
       includes the program name and rc — this test pins that
       contract.
    """
    # 2 MiB of repeating non-JSON bytes — large enough to catch a
    # naive "include payload in error message" implementation but
    # small enough to keep the test under a second.
    script = _make_executable(
        tmp_path / "backend_oversized.sh",
        ("#!/usr/bin/env bash\n" "head -c 2097152 /dev/urandom | base64\n"),
    )
    client = GpgSubprocessClient(command=[str(script)], timeout_seconds=10.0)
    with pytest.raises(GpgError) as exc_info:
        client.sign(SignRequest(local_user="k", payload=b"x"))
    message = str(exc_info.value)
    # The bridge's error string must not contain the backend's stdout
    # bytes. ``len < 1024`` is a coarse but effective check that the
    # message stays operator-readable.
    assert "non-JSON output" in message
    assert len(message) < 1024, f"error message leaked oversized stdout: {len(message)}B"
