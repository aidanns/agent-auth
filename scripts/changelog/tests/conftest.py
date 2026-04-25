# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Add ``scripts/changelog/`` to ``sys.path`` so tests can import the modules.

The changelog tooling lives outside the ``packages/*/src/`` layout (it
is a workspace-level script, not a published package), so pytest's
default discovery doesn't put it on ``sys.path``. Adding it here keeps
the production code free of the path manipulation.
"""

from __future__ import annotations

import sys
from pathlib import Path

CHANGELOG_DIR = Path(__file__).resolve().parent.parent
if str(CHANGELOG_DIR) not in sys.path:
    sys.path.insert(0, str(CHANGELOG_DIR))
