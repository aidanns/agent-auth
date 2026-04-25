# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI-surface tests for the ``things-bridge`` entrypoint."""

from __future__ import annotations

import re
import sys
from importlib.metadata import version as _dist_version
from io import StringIO
from unittest.mock import patch

import pytest

from things_bridge.cli import main

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")


def test_version_flag_prints_distribution_version() -> None:
    """``--version`` prints ``things-bridge <version>`` and exits 0."""
    argv = ["things-bridge", "--version"]
    stdout = StringIO()
    with (
        patch.object(sys, "argv", argv),
        patch.object(sys, "stdout", stdout),
        pytest.raises(SystemExit) as excinfo,
    ):
        main()

    assert excinfo.value.code == 0
    line = stdout.getvalue().rstrip("\n")
    assert line.startswith("things-bridge "), f"unexpected prefix: {line!r}"
    payload = line[len("things-bridge ") :].strip()
    assert _SEMVER_RE.match(payload), f"unexpected version payload: {payload!r}"
    assert payload == _dist_version("things-bridge"), (
        f"CLI reported {payload!r} but importlib.metadata reports "
        f"{_dist_version('things-bridge')!r}"
    )
