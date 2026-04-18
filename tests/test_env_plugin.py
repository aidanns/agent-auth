"""Unit tests for the env-driven integration-test plugin."""

import pytest

from tests_support.env_plugin import ENV_VAR, EnvPlugin


@pytest.fixture
def plugin():
    return EnvPlugin()


def test_env_plugin_approves_when_env_is_approve(monkeypatch, plugin):
    monkeypatch.setenv(ENV_VAR, "approve")
    result = plugin.request_approval("things:read", None, "family")
    assert result.approved is True


def test_env_plugin_denies_when_env_is_deny(monkeypatch, plugin):
    monkeypatch.setenv(ENV_VAR, "deny")
    result = plugin.request_approval("things:read", None, "family")
    assert result.approved is False


def test_env_plugin_fails_closed_when_env_unset(monkeypatch, plugin):
    monkeypatch.delenv(ENV_VAR, raising=False)
    result = plugin.request_approval("things:read", None, "family")
    assert result.approved is False


def test_env_plugin_is_case_insensitive(monkeypatch, plugin):
    monkeypatch.setenv(ENV_VAR, "APPROVE")
    result = plugin.request_approval("things:read", None, "family")
    assert result.approved is True


def test_env_plugin_trims_whitespace(monkeypatch, plugin):
    monkeypatch.setenv(ENV_VAR, "  approve  ")
    result = plugin.request_approval("things:read", None, "family")
    assert result.approved is True


def test_env_plugin_rejects_unknown_value(monkeypatch, plugin):
    monkeypatch.setenv(ENV_VAR, "maybe")
    result = plugin.request_approval("things:read", None, "family")
    assert result.approved is False
