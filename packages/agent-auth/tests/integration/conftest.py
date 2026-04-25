# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Per-package conftest for agent-auth integration tests.

All container fixtures (``agent_auth_container``,
``agent_auth_container_factory``) are registered by
:mod:`tests_support.integration.plugin`, which is wired in via
``addopts = ["-p", "tests_support.integration.plugin"]`` at the
workspace root ``pyproject.toml``. This file exists so pytest marks
the directory as a test collection root."""
