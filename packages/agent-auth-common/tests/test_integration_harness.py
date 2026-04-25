# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the in-tree Docker Compose harness.

These run in the default (``--unit``) pytest invocation and never shell
out to ``docker`` — ``subprocess.run`` is monkeypatched with a fake that
records each call and returns canned output. The harness itself is
pure Python glue plus subprocess choreography; covering the builder,
wait loop, port parsing, and log capture here catches regressions
without spending a CI minute on a docker pull.

The Docker-backed end-to-end exercise of the harness lives in the
integration suite: every agent-auth / things-bridge / things-cli
integration test drives a full ``up → wait → exec → down`` cycle
through this module.
"""

from __future__ import annotations

import email.message
import os
import subprocess
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from tests_support.integration.harness import (
    ClusterStartupTimeout,
    DockerComposeCluster,
    DockerComposeClusterBuilder,
    DockerPort,
    HealthChecks,
    ServiceHandle,
    StartedCluster,
)

# ---------------------------------------------------------------------------
# DockerPort.in_format
# ---------------------------------------------------------------------------


def test_docker_port_in_format_substitutes_all_three_placeholders():
    port = DockerPort(host="127.0.0.1", external_port=54321, internal_port=9100)

    assert (
        port.in_format("http://$HOST:$EXTERNAL_PORT/agent-auth/health")
        == "http://127.0.0.1:54321/agent-auth/health"
    )
    assert port.in_format("$HOST:$EXTERNAL_PORT $INTERNAL_PORT") == "127.0.0.1:54321 9100"


def test_docker_port_in_format_preserves_literal_dollar_outside_placeholders():
    port = DockerPort(host="h", external_port=1, internal_port=2)
    assert port.in_format("price=$5 at $HOST") == "price=$5 at h"


def test_docker_port_in_format_leaves_template_unchanged_when_no_placeholders():
    port = DockerPort(host="h", external_port=1, internal_port=2)
    assert port.in_format("http://static.example/path") == "http://static.example/path"


# ---------------------------------------------------------------------------
# Builder — validation + accumulation
# ---------------------------------------------------------------------------


def test_builder_rejects_missing_project_name(tmp_path):
    b = DockerComposeCluster.builder().file(tmp_path / "compose.yaml")
    with pytest.raises(ValueError, match="project_name"):
        b.build()


def test_builder_rejects_missing_file():
    b = DockerComposeCluster.builder().project_name("proj")
    with pytest.raises(ValueError, match="file"):
        b.build()


def test_builder_accumulates_env_files_and_waits(tmp_path):
    compose_a = tmp_path / "a.yaml"
    compose_b = tmp_path / "b.yaml"
    compose_a.write_text("")
    compose_b.write_text("")

    def _wait(svc: ServiceHandle) -> tuple[bool, str]:
        return True, "ok"

    cluster = (
        DockerComposeCluster.builder()
        .project_name("proj")
        .file(compose_a)
        .file(compose_b)
        .env("IMAGE", "img:v1")
        .env("MODE", "approve")
        .waiting_for_service("svc-a", _wait)
        .waiting_for_service("svc-b", _wait, label="svc-b-http")
        .save_logs_to(tmp_path / "logs")
        .start_timeout_seconds(7.5)
        .poll_interval_seconds(0.05)
        .build()
    )
    assert cluster.project_name == "proj"
    assert cluster.files == (compose_a, compose_b)
    assert cluster.env == {"IMAGE": "img:v1", "MODE": "approve"}
    assert [w.service for w in cluster.waits] == ["svc-a", "svc-b"]
    assert [w.label for w in cluster.waits] == ["svc-a", "svc-b-http"]
    assert cluster.logs_dir == tmp_path / "logs"
    assert cluster.start_timeout_seconds == pytest.approx(7.5)
    assert cluster.poll_interval_seconds == pytest.approx(0.05)


def test_builder_returns_self_from_every_setter(tmp_path):
    b = DockerComposeCluster.builder()
    # Exhaustively check chained returns, so IDE autocomplete and
    # ``self``-return contract stay honest.
    assert b.project_name("p") is b
    assert b.file(tmp_path / "c.yaml") is b
    assert b.env("k", "v") is b
    assert b.waiting_for_service("svc", lambda _s: (True, "ok")) is b
    assert b.save_logs_to(tmp_path / "logs") is b
    assert b.start_timeout_seconds(1.0) is b
    assert b.poll_interval_seconds(0.1) is b


# ---------------------------------------------------------------------------
# HealthChecks factory validation
# ---------------------------------------------------------------------------


def test_health_checks_http_rejects_empty_accept_statuses():
    with pytest.raises(ValueError, match="accept_statuses"):
        HealthChecks.to_respond_over_http(
            internal_port=9100, url_format="http://$HOST", accept_statuses=[]
        )


def test_health_checks_ports_open_rejects_no_ports():
    with pytest.raises(ValueError, match="internal_port"):
        HealthChecks.to_have_ports_open()


# ---------------------------------------------------------------------------
# HealthChecks.to_respond_over_http — mocked HTTP layer
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    status: int

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _stub_service(host: str = "127.0.0.1", external: int = 54321) -> ServiceHandle:
    """Build a ServiceHandle whose .port() returns a fixed DockerPort.

    Avoids spinning up a real StartedCluster — the only surface the
    wait probe touches is ``service.port(internal_port)``.
    """
    fake_port = DockerPort(host=host, external_port=external, internal_port=9100)

    class _StubCluster:
        def resolve_port(self, service: str, internal_port: int) -> DockerPort:
            return fake_port

    return ServiceHandle(cluster=_StubCluster(), name="svc")  # type: ignore[arg-type]


def test_http_wait_returns_true_on_accepted_status():
    check = HealthChecks.to_respond_over_http(
        internal_port=9100,
        url_format="http://$HOST:$EXTERNAL_PORT/health",
        accept_statuses={401, 403},
    )
    with patch("urllib.request.urlopen", return_value=_FakeResponse(status=401)):
        ok, diag = check(_stub_service())
    assert ok is True
    assert "401" in diag


def test_http_wait_returns_false_on_rejected_status():
    check = HealthChecks.to_respond_over_http(
        internal_port=9100,
        url_format="http://$HOST:$EXTERNAL_PORT/health",
        accept_statuses={200},
    )
    with patch("urllib.request.urlopen", return_value=_FakeResponse(status=503)):
        ok, diag = check(_stub_service())
    assert ok is False
    assert "503" in diag
    assert "not in" in diag


def test_http_wait_treats_http_error_in_accept_set_as_healthy():
    check = HealthChecks.to_respond_over_http(
        internal_port=9100,
        url_format="http://$HOST:$EXTERNAL_PORT/health",
        accept_statuses={401},
    )

    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise urllib.error.HTTPError(
            url="http://x",
            code=401,
            msg="unauthorized",
            hdrs=email.message.Message(),
            fp=None,
        )

    with patch("urllib.request.urlopen", side_effect=_raise):
        ok, diag = check(_stub_service())
    assert ok is True
    assert "401" in diag


def test_http_wait_treats_connection_error_as_unhealthy():
    check = HealthChecks.to_respond_over_http(
        internal_port=9100,
        url_format="http://$HOST:$EXTERNAL_PORT/health",
        accept_statuses={200, 401},
    )
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        ok, diag = check(_stub_service())
    assert ok is False
    assert "connection error" in diag


# ---------------------------------------------------------------------------
# StartedCluster subprocess wiring
# ---------------------------------------------------------------------------


@dataclass
class _FakeCompletedProcess:
    args: list[str]
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    env: dict[str, str] | None = None


class _SubprocessRecorder:
    """Fake for ``subprocess.run`` that records every call.

    The test assigns a ``handler`` that returns a :class:`_FakeCompletedProcess`
    for the test's choice of inputs. All calls are accumulated for
    inspection.
    """

    def __init__(
        self, handler: Callable[[list[str], dict[str, str] | None], _FakeCompletedProcess]
    ):
        self.handler = handler
        self.calls: list[_FakeCompletedProcess] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        result = self.handler(argv, kwargs.get("env"))
        record = _FakeCompletedProcess(
            args=list(argv),
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            env=dict(kwargs["env"]) if kwargs.get("env") is not None else None,
        )
        self.calls.append(record)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )


def _make_started_cluster(
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
    logs_dir: Path | None = None,
) -> StartedCluster:
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}")
    return StartedCluster(
        project_name="proj-123",
        files=(compose_file,),
        env=dict(env or {}),
        logs_dir=logs_dir,
        logs_on_success=False,
        stop_timeout_seconds=5.0,
    )


def test_exec_passes_project_name_and_service_and_argv(tmp_path, monkeypatch):
    cluster = _make_started_cluster(tmp_path, env={"IMAGE": "img:v1"})

    def _handler(argv: list[str], env: dict[str, str] | None) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(args=argv, stdout="ok", returncode=0)

    recorder = _SubprocessRecorder(_handler)
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)

    result = cluster.exec("agent-auth", ["agent-auth", "token", "list"])
    assert result.stdout == "ok"
    assert len(recorder.calls) == 1
    argv = recorder.calls[0].args
    assert argv[:2] == ["docker", "compose"]
    assert "-f" in argv
    assert "--project-name" in argv
    assert argv[argv.index("--project-name") + 1] == "proj-123"
    exec_idx = argv.index("exec")
    assert argv[exec_idx : exec_idx + 3] == ["exec", "-T", "agent-auth"]
    assert argv[exec_idx + 3 :] == ["agent-auth", "token", "list"]


def test_exec_forwards_env_without_mutating_os_environ(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_AUTH_HARNESS_TEST_KEY", raising=False)
    cluster = _make_started_cluster(tmp_path, env={"AGENT_AUTH_HARNESS_TEST_KEY": "marker"})

    recorder = _SubprocessRecorder(lambda argv, env: _FakeCompletedProcess(args=argv, returncode=0))
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)

    cluster.exec("svc", ["echo", "hi"])
    assert recorder.calls[0].env is not None
    assert recorder.calls[0].env["AGENT_AUTH_HARNESS_TEST_KEY"] == "marker"
    assert "AGENT_AUTH_HARNESS_TEST_KEY" not in os.environ


def test_stop_service_issues_compose_stop(tmp_path, monkeypatch):
    cluster = _make_started_cluster(tmp_path)
    recorder = _SubprocessRecorder(lambda argv, env: _FakeCompletedProcess(args=argv, returncode=0))
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)

    cluster.stop_service("agent-auth")
    argv = recorder.calls[0].args
    assert argv[argv.index("--project-name") + 1] == "proj-123"
    assert "stop" in argv
    assert argv[-1] == "agent-auth"


def test_stop_service_raises_on_nonzero_exit(tmp_path, monkeypatch):
    cluster = _make_started_cluster(tmp_path)
    recorder = _SubprocessRecorder(
        lambda argv, env: _FakeCompletedProcess(args=argv, returncode=1, stderr="nope")
    )
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)
    with pytest.raises(RuntimeError, match="stop"):
        cluster.stop_service("svc")


# ---------------------------------------------------------------------------
# Port lookup parsing
# ---------------------------------------------------------------------------


def test_resolve_port_parses_host_port_output(tmp_path, monkeypatch):
    cluster = _make_started_cluster(tmp_path)
    recorder = _SubprocessRecorder(
        lambda argv, env: _FakeCompletedProcess(args=argv, stdout="127.0.0.1:54321\n", returncode=0)
    )
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)

    port = cluster.resolve_port("agent-auth", 9100)
    assert port == DockerPort(host="127.0.0.1", external_port=54321, internal_port=9100)


def test_resolve_port_caches_result(tmp_path, monkeypatch):
    cluster = _make_started_cluster(tmp_path)
    recorder = _SubprocessRecorder(
        lambda argv, env: _FakeCompletedProcess(args=argv, stdout="127.0.0.1:1234\n", returncode=0)
    )
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)

    first = cluster.resolve_port("svc", 9100)
    second = cluster.resolve_port("svc", 9100)
    assert first == second
    # Only one subprocess call despite two lookups.
    assert len(recorder.calls) == 1


def test_resolve_port_raises_on_unparseable_output(tmp_path, monkeypatch):
    cluster = _make_started_cluster(tmp_path)
    recorder = _SubprocessRecorder(
        lambda argv, env: _FakeCompletedProcess(
            args=argv, stdout="garbage-no-colon\n", returncode=0
        )
    )
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)
    with pytest.raises(RuntimeError, match="could not parse"):
        cluster.resolve_port("svc", 9100)


def test_resolve_port_raises_on_nonzero_exit(tmp_path, monkeypatch):
    cluster = _make_started_cluster(tmp_path)
    recorder = _SubprocessRecorder(
        lambda argv, env: _FakeCompletedProcess(
            args=argv, stdout="", stderr="no such service", returncode=1
        )
    )
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)
    with pytest.raises(RuntimeError, match="could not resolve"):
        cluster.resolve_port("nope", 9100)


# ---------------------------------------------------------------------------
# Wait loop — timeout behaviour and parallelism under a shared deadline
# ---------------------------------------------------------------------------


def test_wait_loop_fires_timeout_when_probe_never_succeeds(tmp_path, monkeypatch):
    cluster = _make_started_cluster(tmp_path)

    def _never(service: ServiceHandle) -> tuple[bool, str]:
        return False, "still sad"

    from tests_support.integration.harness._cluster import _ServiceWait

    waits = (_ServiceWait(service="svc", check=_never, label="svc"),)
    # Use a small deadline and patch sleep to speed the loop up.
    monkeypatch.setattr("tests_support.integration.harness._cluster.time.sleep", lambda _s: None)

    with pytest.raises(ClusterStartupTimeout) as exc_info:
        cluster._wait_for_all_services(
            waits=waits, deadline_seconds=0.05, poll_interval_seconds=0.01
        )
    assert "still sad" in str(exc_info.value)
    assert "svc" in str(exc_info.value)


def test_wait_loop_returns_when_probe_succeeds(tmp_path, monkeypatch):
    cluster = _make_started_cluster(tmp_path)
    attempts = {"count": 0}

    def _succeeds_second_try(service: ServiceHandle) -> tuple[bool, str]:
        attempts["count"] += 1
        if attempts["count"] >= 2:
            return True, "ready"
        return False, "warming up"

    monkeypatch.setattr("tests_support.integration.harness._cluster.time.sleep", lambda _s: None)
    from tests_support.integration.harness._cluster import _ServiceWait

    waits = (_ServiceWait(service="svc", check=_succeeds_second_try, label="svc"),)
    # Should not raise.
    cluster._wait_for_all_services(waits=waits, deadline_seconds=1.0, poll_interval_seconds=0.01)
    assert attempts["count"] >= 2


# ---------------------------------------------------------------------------
# Log capture on teardown
# ---------------------------------------------------------------------------


def test_save_logs_writes_one_file_per_service(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs-out"
    cluster = _make_started_cluster(tmp_path, logs_dir=logs_dir)

    def _handler(argv: list[str], env: dict[str, str] | None) -> _FakeCompletedProcess:
        if "config" in argv and "--services" in argv:
            return _FakeCompletedProcess(
                args=argv, stdout="agent-auth\nthings-bridge\nnotifier\n", returncode=0
            )
        if "logs" in argv:
            service = argv[-1]
            return _FakeCompletedProcess(
                args=argv, stdout=f"log lines for {service}\n", returncode=0
            )
        if "down" in argv:
            return _FakeCompletedProcess(args=argv, returncode=0)
        return _FakeCompletedProcess(args=argv, returncode=0)

    recorder = _SubprocessRecorder(_handler)
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)

    cluster.stop(test_failed=True)
    assert (logs_dir / "agent-auth.log").read_text() == "log lines for agent-auth\n"
    assert (logs_dir / "things-bridge.log").read_text() == ("log lines for things-bridge\n")
    assert (logs_dir / "notifier.log").read_text() == "log lines for notifier\n"
    # And ``docker compose down`` was invoked at teardown.
    assert any("down" in call.args for call in recorder.calls)


def test_save_logs_skipped_on_success_when_on_success_is_false(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs-out"
    cluster = _make_started_cluster(tmp_path, logs_dir=logs_dir)

    recorder = _SubprocessRecorder(lambda argv, env: _FakeCompletedProcess(args=argv, returncode=0))
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)

    cluster.stop(test_failed=False)
    assert not logs_dir.exists()
    # Down still ran.
    assert any("down" in call.args for call in recorder.calls)


def test_save_logs_falls_back_to_combined_when_config_services_fails(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs-out"
    cluster = _make_started_cluster(tmp_path, logs_dir=logs_dir)

    def _handler(argv: list[str], env: dict[str, str] | None) -> _FakeCompletedProcess:
        if "config" in argv and "--services" in argv:
            return _FakeCompletedProcess(
                args=argv, stdout="", stderr="compose file broken", returncode=1
            )
        if "logs" in argv:
            return _FakeCompletedProcess(args=argv, stdout="combined log\n", returncode=0)
        if "down" in argv:
            return _FakeCompletedProcess(args=argv, returncode=0)
        return _FakeCompletedProcess(args=argv, returncode=0)

    monkeypatch.setattr(
        "tests_support.integration.harness._cluster.subprocess.run",
        _SubprocessRecorder(_handler),
    )

    cluster.stop(test_failed=True)
    assert (logs_dir / "combined.log").read_text() == "combined log\n"


def test_stop_is_idempotent(tmp_path, monkeypatch):
    cluster = _make_started_cluster(tmp_path)
    recorder = _SubprocessRecorder(lambda argv, env: _FakeCompletedProcess(args=argv, returncode=0))
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)
    cluster.stop(test_failed=False)
    first_count = len(recorder.calls)
    cluster.stop(test_failed=False)
    # Second call should be a no-op.
    assert len(recorder.calls) == first_count


def test_compose_down_does_not_pass_explicit_timeout_flag(tmp_path, monkeypatch):
    """Pin #288: ``-t`` would override the compose-file ``stop_grace_period``.

    Hard-coding ``-t 30`` pushed every per-test teardown to ~30 s by
    silently overriding the per-service grace period in
    ``docker/docker-compose.yaml`` (and defeating the SIGTERM handlers
    from #154). Anchoring the down argv shape here prevents a future
    refactor from re-introducing the regression unnoticed.
    """
    cluster = _make_started_cluster(tmp_path)
    recorder = _SubprocessRecorder(lambda argv, env: _FakeCompletedProcess(args=argv, returncode=0))
    monkeypatch.setattr("tests_support.integration.harness._cluster.subprocess.run", recorder)

    cluster.stop(test_failed=False)

    down_call = next(call for call in recorder.calls if "down" in call.args)
    assert "-t" not in down_call.args, (
        f"docker compose down argv contains -t, which overrides the "
        f"compose-file stop_grace_period. argv={down_call.args!r}"
    )
    # Sanity: the rest of the down shape is still what the harness needs.
    assert "-v" in down_call.args
    assert "--remove-orphans" in down_call.args


# ---------------------------------------------------------------------------
# Builder is re-usable as a factory (no accidental freezing)
# ---------------------------------------------------------------------------


def test_builder_build_returns_new_cluster_per_call(tmp_path):
    compose = tmp_path / "c.yaml"
    compose.write_text("")
    builder = DockerComposeCluster.builder().project_name("p").file(compose)
    c1 = builder.build()
    c2 = builder.build()
    # Separate objects, same structural content.
    assert c1 is not c2
    assert c1.project_name == c2.project_name == "p"


def test_builder_type_round_trips(tmp_path):
    """Builder and cluster types remain in the public re-export surface."""
    assert isinstance(DockerComposeCluster.builder(), DockerComposeClusterBuilder)
