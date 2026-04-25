# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI-surface tests for the ``gpg-bridge`` entrypoint.

Today the only stable CLI behaviour worth locking in is the
``--version`` action — every other surface is exercised through the
HTTP server tests (``test_gpg_bridge_server.py``) and the subprocess
client tests. If the CLI grows non-trivial argv handling, those tests
belong here.
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import version as _dist_version
from io import StringIO
from unittest.mock import patch

import pytest

from gpg_bridge.cli import main

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")


def test_version_flag_prints_distribution_version() -> None:
    """``--version`` prints ``gpg-bridge <version>`` and exits 0.

    The version string is the runtime distribution version (see
    ``cli_meta.add_version_flag``); the test asserts the prefix and a
    semver-shaped suffix so a setuptools_scm fallback still matches.
    """
    argv = ["gpg-bridge", "--version"]
    stdout = StringIO()
    with (
        patch.object(sys, "argv", argv),
        patch.object(sys, "stdout", stdout),
        pytest.raises(SystemExit) as excinfo,
    ):
        main()

    assert excinfo.value.code == 0
    line = stdout.getvalue().rstrip("\n")
    assert line.startswith("gpg-bridge "), f"unexpected prefix: {line!r}"
    payload = line[len("gpg-bridge ") :].strip()
    assert _SEMVER_RE.match(payload), f"unexpected version payload: {payload!r}"
    assert payload == _dist_version("gpg-bridge"), (
        f"CLI reported {payload!r} but importlib.metadata reports "
        f"{_dist_version('gpg-bridge')!r}"
    )
