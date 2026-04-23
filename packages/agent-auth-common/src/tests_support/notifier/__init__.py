# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Deterministic approve / deny HTTP notifiers for integration tests.

Replaces the deleted ``always_approve`` / ``always_deny`` in-process
plugins. Invoked as::

    python -m tests_support.notifier approve --port 9150
    python -m tests_support.notifier deny    --port 9150

Integration-test use only — never shipped in the production wheel
(``[tool.setuptools.packages.find].exclude`` covers the whole
``tests_support`` tree).
"""

from tests_support.notifier.server import run_fixed_notifier

__all__ = ["run_fixed_notifier"]
