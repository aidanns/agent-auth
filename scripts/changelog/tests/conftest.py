# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Add ``scripts/changelog/`` and ``scripts/lint/`` to ``sys.path``.

The changelog tooling lives outside the ``packages/*/src/`` layout (it
is a workspace-level script, not a published package), so pytest's
default discovery doesn't put it on ``sys.path``. Adding the entries
here keeps the production modules' bare ``from version_logic import …``
/ ``from commit_taxonomy import …`` test imports working without
forcing the test files to do their own per-file path setup.

``scripts/changelog/`` is added so ``test_lint``, ``test_add``,
``test_commit_taxonomy``, etc. can ``from version_logic import …``
directly. ``scripts/lint/`` is added so ``test_commit_taxonomy`` can
``from commit_taxonomy import …`` (it uses the bare-name import path
because the lint self-tests assert the public surface as it is loaded
in CI). The production ``version_logic`` module loads
``commit_taxonomy`` via ``importlib.util.spec_from_file_location``
rather than relying on this conftest's ``sys.path`` insertion (see
issue #405) — that keeps the production import side-effect-free even
though the tests still go through bare-name imports here.
"""

from __future__ import annotations

import sys
from pathlib import Path

CHANGELOG_DIR = Path(__file__).resolve().parent.parent
LINT_DIR = CHANGELOG_DIR.parent / "lint"
for path in (CHANGELOG_DIR, LINT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
