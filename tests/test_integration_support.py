# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for pure helpers in ``tests.integration._support`` and the
image-tag resolution branch of ``tests.integration.conftest``.

The docker-driving helpers require a live daemon and are exercised by
the integration suite; the pieces tested here (``phase_timer`` and the
``AGENT_AUTH_TEST_IMAGE_SESSION`` short-circuit) are the plumbing that
runs on the host, not in a container.
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


# ``_resolve_test_image_tags`` decides whether the session owns the
# images or whether the harness was handed a prebuilt set. Getting this
# wrong in CI is load-bearing: an unexpected "managed" result would
# rebuild images the CI step just built, and an unexpected
# "unmanaged" result would skip the build when no images exist. Both
# branches are covered here so the contract survives refactors.


def test_resolve_test_image_tags_reuses_prebuilt_env_suffix(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_TEST_IMAGE_SESSION", "ci")

    tags, managed = integration_conftest._resolve_test_image_tags()

    assert managed is False
    assert tags == {
        "agent-auth": "agent-auth-test:ci",
        "things-bridge": "things-bridge-test:ci",
        "things-cli": "things-cli-test:ci",
        "things-client-applescript": "things-client-applescript-test:ci",
    }


def test_resolve_test_image_tags_mints_managed_session_when_env_unset(monkeypatch):
    monkeypatch.delenv("AGENT_AUTH_TEST_IMAGE_SESSION", raising=False)

    tags, managed = integration_conftest._resolve_test_image_tags()

    assert managed is True
    assert set(tags) == {
        "agent-auth",
        "things-bridge",
        "things-cli",
        "things-client-applescript",
    }
    # Every tag shares the same ``pytest-<hex>`` suffix so all N images
    # are anchored at the same session id — mismatching suffixes would
    # let one session's compose project accidentally pick up another
    # session's stale image.
    suffixes = {tag.split(":", 1)[1] for tag in tags.values()}
    assert len(suffixes) == 1
    assert next(iter(suffixes)).startswith("pytest-")


def test_resolve_test_image_tags_mints_fresh_session_per_call(monkeypatch):
    monkeypatch.delenv("AGENT_AUTH_TEST_IMAGE_SESSION", raising=False)

    first, _ = integration_conftest._resolve_test_image_tags()
    second, _ = integration_conftest._resolve_test_image_tags()

    assert first != second
