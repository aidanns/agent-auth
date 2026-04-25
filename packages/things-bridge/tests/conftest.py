# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Per-package conftest for things-bridge unit tests.

Re-exports the workspace-wide ``preserve_signal_handlers`` fixture
from :mod:`tests_support.signals` so the bridge's shutdown-handler
tests pick it up by argument name. The integration container fixtures
(``things_bridge_stack``, etc.) come from
:mod:`tests_support.integration.plugin`, registered globally via
``addopts = ["-p", "tests_support.integration.plugin"]`` in the
workspace ``pyproject.toml``.
"""

from tests_support.signals import preserve_signal_handlers as preserve_signal_handlers
