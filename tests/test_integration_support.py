# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for pure helpers in ``tests.integration._support`` and the
image-tag resolution branch of ``tests.integration.conftest``.

The docker-driving helpers require a live daemon and are exercised by
the integration suite; the pieces tested here (``phase_timer`` and the
``AGENT_AUTH_TEST_IMAGE_TAG`` short-circuit) are the plumbing that runs
on the host, not in a container.
"""

from __future__ import annotations

import logging
import time

from tests.integration import conftest as integration_conftest
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


# ``_resolve_test_image_tag`` decides whether the session owns the
# image or whether the harness was handed a prebuilt one. Getting this
# wrong in CI is load-bearing: an unexpected "managed" result would
# rebuild the image the CI step just built, and an unexpected
# "unmanaged" result would skip the build when no image exists. Both
# branches are covered here so the contract survives refactors.


def test_resolve_test_image_tag_reuses_prebuilt_env_value(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_TEST_IMAGE_TAG", "prebuilt-tag:test")

    tag, managed = integration_conftest._resolve_test_image_tag()

    assert tag == "prebuilt-tag:test"
    assert managed is False


def test_resolve_test_image_tag_mints_managed_tag_when_env_unset(monkeypatch):
    monkeypatch.delenv("AGENT_AUTH_TEST_IMAGE_TAG", raising=False)

    tag, managed = integration_conftest._resolve_test_image_tag()

    assert tag.startswith("agent-auth-test:pytest-")
    assert managed is True


def test_resolve_test_image_tag_mints_fresh_tag_per_call(monkeypatch):
    monkeypatch.delenv("AGENT_AUTH_TEST_IMAGE_TAG", raising=False)

    first, _ = integration_conftest._resolve_test_image_tag()
    second, _ = integration_conftest._resolve_test_image_tag()

    assert first != second
