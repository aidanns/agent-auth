# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Helpers for exercising signal-driven behaviour in pytest.

Delivering real signals into the pytest worker would race with
pytest's own signal handling, so shutdown-handler tests call the
registered handler function directly instead.
"""

from __future__ import annotations

import signal


def invoke_installed_handler(sig: int) -> None:
    """Call the handler ``signal.signal`` has registered for ``sig``."""
    handler = signal.getsignal(sig)
    assert callable(handler), f"no handler installed for {sig}"
    handler(sig, None)
