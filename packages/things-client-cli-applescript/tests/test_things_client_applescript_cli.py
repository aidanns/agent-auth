# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI-surface tests for ``things-client-cli-applescript``.

Today the only stable cross-platform CLI behaviour worth locking in is
the ``--version`` action; the read-command surface is exercised via the
shared ``things_client_common.cli`` tests and the integration harness.
"""

from __future__ import annotations

import re
from importlib.metadata import version as _dist_version

import pytest

from things_client_applescript.cli import main

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")


def test_version_flag_prints_distribution_version(capsys) -> None:
    """``--version`` prints ``things-client-cli-applescript <version>`` and exits 0."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    line = capsys.readouterr().out.rstrip("\n")
    assert line.startswith("things-client-cli-applescript "), f"unexpected prefix: {line!r}"
    payload = line[len("things-client-cli-applescript ") :].strip()
    assert _SEMVER_RE.match(payload), f"unexpected version payload: {payload!r}"
    assert payload == _dist_version("things-client-cli-applescript"), (
        f"CLI reported {payload!r} but importlib.metadata reports "
        f"{_dist_version('things-client-cli-applescript')!r}"
    )
