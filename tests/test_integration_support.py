# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for pure helpers in ``tests.integration._support``.

The module's docker-driving helpers require a live daemon and are
exercised by the integration suite, but ``phase_timer`` is a plain
context manager that can be tested without docker.
"""

from __future__ import annotations

import logging
import time

from tests.integration._support import phase_timer


def test_phase_timer_logs_phase_name_and_elapsed_seconds(caplog):
    with (
        caplog.at_level(logging.INFO, logger="integration.timing"),
        phase_timer("spam_phase"),
    ):
        pass

    (record,) = caplog.records
    assert "phase=spam_phase" in record.message
    assert "elapsed_seconds=" in record.message


def test_phase_timer_appends_fields_in_order(caplog):
    with (
        caplog.at_level(logging.INFO, logger="integration.timing"),
        phase_timer("eggs_phase", project="proj-1", service="bridge"),
    ):
        pass

    (record,) = caplog.records
    assert record.message.endswith(" project=proj-1 service=bridge")


def test_phase_timer_logs_on_exception(caplog):
    class Sentinel(Exception):
        pass

    with caplog.at_level(logging.INFO, logger="integration.timing"):
        try:
            with phase_timer("failing_phase"):
                raise Sentinel
        except Sentinel:
            pass

    (record,) = caplog.records
    assert "phase=failing_phase" in record.message


def test_phase_timer_elapsed_is_monotonic(caplog):
    with (
        caplog.at_level(logging.INFO, logger="integration.timing"),
        phase_timer("sleep_phase"),
    ):
        time.sleep(0.01)

    (record,) = caplog.records
    # Parse the "elapsed_seconds=N.NNN" slice; guard against the exact
    # sleep duration being racy on a loaded CI box — we only assert the
    # value is positive and finite, not a tight upper bound.
    elapsed_token = next(t for t in record.message.split() if t.startswith("elapsed_seconds="))
    elapsed = float(elapsed_token.split("=", 1)[1])
    assert elapsed > 0.0
