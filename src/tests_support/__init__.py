# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Test-support package for agent-auth integration tests.

Packaged alongside ``agent-auth`` so it can be installed into the same
environment as the server (notably inside the test Docker image) but is
never loaded in a production deployment. The sole consumer is the
integration-test suite under ``tests/integration/``.
"""
