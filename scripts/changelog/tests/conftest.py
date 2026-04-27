# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Add ``scripts/changelog/`` and ``scripts/lint/`` to ``sys.path``.

The changelog tooling lives outside the ``packages/*/src/`` layout (it
is a workspace-level script, not a published package), so pytest's
default discovery doesn't put it on ``sys.path``. Adding it here keeps
the production code free of the path manipulation. ``scripts/lint/``
joins the path for the same reason once ``commit_taxonomy`` started
being imported by ``version_logic`` and the lint self-tests
(see issue #405).
"""

from __future__ import annotations

import sys
from pathlib import Path

CHANGELOG_DIR = Path(__file__).resolve().parent.parent
LINT_DIR = CHANGELOG_DIR.parent / "lint"
for path in (CHANGELOG_DIR, LINT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
