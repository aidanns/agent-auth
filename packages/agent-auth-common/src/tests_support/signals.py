# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Helpers and fixtures for exercising signal-driven behaviour in
pytest.

Delivering real signals into the pytest worker would race with
pytest's own signal handling, so shutdown-handler tests call the
registered handler function directly instead.
"""

from __future__ import annotations

import signal
from collections.abc import Iterator

import pytest


def invoke_installed_handler(sig: int) -> None:
    """Call the handler ``signal.signal`` has registered for ``sig``."""
    handler = signal.getsignal(sig)
    assert callable(handler), f"no handler installed for {sig}"
    handler(sig, None)


@pytest.fixture
def preserve_signal_handlers() -> Iterator[None]:
    """Restore SIGTERM / SIGINT handlers after the test.

    Any test that calls ``_install_shutdown_handler`` mutates
    process-global signal state; without this fixture a later test's
    SIGINT (or pytest's own interrupt handling) would invoke our
    installed callback.
    """
    originals = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }
    yield
    for sig, handler in originals.items():
        signal.signal(sig, handler)
