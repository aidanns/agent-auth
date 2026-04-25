# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for pure helpers in ``tests_support.integration.support``
and the image-tag resolution branch of
``tests_support.integration.plugin``.

The docker-driving helpers require a live daemon and are exercised by
the integration suite; the pieces tested here (``phase_timer``, the
``AGENT_AUTH_TEST_IMAGE_SESSION`` short-circuit, and the
``AGENT_AUTH_DOCKER_CACHE`` build-arg synthesis) are the plumbing that
runs on the host, not in a container.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

from tests_support.integration import plugin as integration_plugin
from tests_support.integration.support import (
    _cache_scope_for_dockerfile,
    _gha_cache_args,
    clear_phase_budget_breaches,
    phase_budget_breaches,
    phase_timer,
)


@pytest.fixture(autouse=True)
def _isolate_phase_budget_breaches():
    """Reset the module-level breach list around every test in this file.

    ``phase_timer`` writes into a shared list so the integration plugin's
    ``pytest_sessionfinish`` hook can fail the run on a teardown-budget
    regression. Tests in this file deliberately drive the same list, so
    we clear it before *and* after each test to keep one test from
    leaking state into the next.
    """
    clear_phase_budget_breaches()
    yield
    clear_phase_budget_breaches()


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


# ``phase_timer(budget_seconds=...)`` underpins the #288 CI gate: a
# breach is appended to a module-level list that the integration
# plugin's ``pytest_sessionfinish`` hook converts into a non-zero
# session exit. Tests below pin the contract: no breach when within
# budget, exactly one breach (with the right metadata) when over,
# and no surprise raise from the context manager itself.


def test_phase_timer_records_no_breach_when_within_budget():
    with phase_timer("ok_phase", budget_seconds=10.0):
        pass

    assert phase_budget_breaches() == ()


def test_phase_timer_records_breach_when_budget_exceeded(monkeypatch, caplog):
    # Drive elapsed time deterministically so the test doesn't depend on
    # ``time.sleep`` precision. Patching ``time.monotonic`` inside the
    # support module is enough — phase_timer reads it via the bare
    # ``time`` import, so the patch lands on the same function object.
    clock = iter([100.0, 100.5])
    monkeypatch.setattr("tests_support.integration.support.time.monotonic", lambda: next(clock))

    with (
        caplog.at_level(logging.WARNING, logger="integration.timing"),
        phase_timer("compose_stop", budget_seconds=0.1, project="proj-x", service="svc-y"),
    ):
        pass

    (breach,) = phase_budget_breaches()
    assert breach.phase == "compose_stop"
    assert breach.budget_seconds == 0.1
    # The deterministic clock above means elapsed is exactly 0.5 s.
    assert breach.elapsed_seconds == pytest.approx(0.5)
    assert breach.fields == {"project": "proj-x", "service": "svc-y"}
    # And the WARNING fires alongside the INFO line so a developer
    # tailing logs sees the regression even before sessionfinish runs.
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
    assert "exceeded budget" in warning_records[0].message


def test_phase_timer_does_not_raise_on_breach():
    """The breach is recorded; the ``with`` block itself completes cleanly.

    The fixture teardowns that wrap ``running.stop()`` catch ``Exception``
    to avoid masking earlier test failures. If ``phase_timer`` raised
    inline on a breach, that ``except`` would swallow the regression
    signal — which is exactly the ``compose_stop`` budget gap #288 fixes.
    """
    sentinel = object()

    with phase_timer("compose_stop", budget_seconds=0.0):
        result = sentinel

    assert result is sentinel
    assert len(phase_budget_breaches()) == 1


def test_phase_timer_without_budget_records_no_breach_even_when_slow(monkeypatch):
    clock = iter([0.0, 999.0])
    monkeypatch.setattr("tests_support.integration.support.time.monotonic", lambda: next(clock))
    with phase_timer("untimed_phase"):
        pass
    assert phase_budget_breaches() == ()


# ``_resolve_test_image_tags`` decides whether the session owns the
# images or whether the harness was handed a prebuilt set. Getting this
# wrong in CI is load-bearing: an unexpected "managed" result would
# rebuild images the CI step just built, and an unexpected
# "unmanaged" result would skip the build when no images exist. Both
# branches are covered here so the contract survives refactors.


def test_resolve_test_image_tags_reuses_prebuilt_env_suffix(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_TEST_IMAGE_SESSION", "ci")

    tags, managed = integration_plugin._resolve_test_image_tags()

    assert managed is False
    assert tags == {
        "agent-auth": "agent-auth-test:ci",
        "gpg-bridge": "gpg-bridge-test:ci",
        "gpg-cli": "gpg-cli-test:ci",
        "things-bridge": "things-bridge-test:ci",
        "things-cli": "things-cli-test:ci",
        "things-client-applescript": "things-client-applescript-test:ci",
    }


def test_resolve_test_image_tags_mints_managed_session_when_env_unset(monkeypatch):
    monkeypatch.delenv("AGENT_AUTH_TEST_IMAGE_SESSION", raising=False)

    tags, managed = integration_plugin._resolve_test_image_tags()

    assert managed is True
    assert set(tags) == {
        "agent-auth",
        "gpg-bridge",
        "gpg-cli",
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

    first, _ = integration_plugin._resolve_test_image_tags()
    second, _ = integration_plugin._resolve_test_image_tags()

    assert first != second


# ``AGENT_AUTH_DOCKER_CACHE=gha`` opts the build into buildx-backed
# GitHub Actions caching. CI drives its own caching path via
# .github/actions/build-integration-test-image, so these tests pin the
# local / manual-opt-in contract: the env var is read at build time
# (not import time), the scope is derived from the per-service
# Dockerfile name, and disabling the env var yields no extra argv.


def test_gha_cache_args_returns_empty_list_when_env_unset(monkeypatch):
    monkeypatch.delenv("AGENT_AUTH_DOCKER_CACHE", raising=False)
    assert _gha_cache_args(Path("docker/Dockerfile.agent-auth.test")) == []


def test_gha_cache_args_returns_empty_list_when_env_not_gha(monkeypatch):
    # Any value other than ``gha`` is treated as "no cache". Pins the
    # contract against a future expansion adding other cache backends
    # — a typo / wrong value must not silently enable buildx caching.
    monkeypatch.setenv("AGENT_AUTH_DOCKER_CACHE", "local")
    assert _gha_cache_args(Path("docker/Dockerfile.agent-auth.test")) == []


def test_gha_cache_args_emits_buildx_cache_and_load_flags(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_DOCKER_CACHE", "gha")

    args = _gha_cache_args(Path("docker/Dockerfile.things-bridge.test"))

    assert args == [
        "--cache-from",
        "type=gha,scope=things-bridge-test",
        "--cache-to",
        "type=gha,mode=max,scope=things-bridge-test",
        # ``--load`` imports the built image into the local Docker
        # daemon; omitting it leaves the image in buildx's internal
        # cache and downstream ``docker compose`` can't find it.
        "--load",
    ]


def test_cache_scope_strips_dockerfile_prefix_only():
    # ``Dockerfile.<service>.test`` → ``<service>-test``. The suffix
    # ``.test`` is preserved so the scope doesn't collide with a
    # hypothetical non-test Dockerfile named ``Dockerfile.<svc>``.
    assert (
        _cache_scope_for_dockerfile(Path("docker/Dockerfile.agent-auth.test")) == "agent-auth-test"
    )
    assert (
        _cache_scope_for_dockerfile(Path("docker/Dockerfile.things-client-applescript.test"))
        == "things-client-applescript-test"
    )
