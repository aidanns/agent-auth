# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Per-package conftest for things-bridge integration tests.

All container fixtures (``things_bridge_stack``, etc.) are registered
by :mod:`tests_support.integration.plugin`, which is wired in via
``addopts = ["-p", "tests_support.integration.plugin"]`` at the
workspace root ``pyproject.toml``. This file exists so pytest marks
the directory as a test collection root.
"""
