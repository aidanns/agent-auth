# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Metric declarations and registry builder for agent-auth.

Names + attributes follow the catalogue in
``design/DESIGN.md`` "Observability". HTTP metrics use OTel semconv
names; domain counters use the ``agent_auth_`` prefix. The registry
is owned by ``AgentAuthServer`` so every request handler can update
counters without threading a registry through every call site.
"""

from __future__ import annotations

from dataclasses import dataclass

from server_metrics import Counter, Gauge, Histogram, Registry


@dataclass(frozen=True)
class AgentAuthMetrics:
    """Handle to every metric agent-auth emits."""

    http_request_duration: Histogram
    http_active_requests: Gauge
    token_operations: Counter
    validation_outcomes: Counter
    approval_outcomes: Counter


# Canonical reason labels for ``agent_auth_validation_outcomes_total``.
# "ok" is used for the allowed path; the denied reasons mirror the
# ``validation_denied`` audit-log reason strings so the two surfaces
# stay in step.
VALIDATION_REASON_OK = "ok"
VALIDATION_DENIED_REASONS = (
    "invalid_token",
    "not_access_token",
    "token_not_found",
    "token_expired",
    "family_revoked",
    "scope_denied",
    "approval_denied",
)


def build_registry() -> tuple[Registry, AgentAuthMetrics]:
    """Return a fresh registry and the named metric handles."""
    http_request_duration = Histogram(
        "http_server_request_duration_seconds",
        "Duration of HTTP server requests in seconds.",
        label_names=("method", "route", "status_code"),
    )
    http_active_requests = Gauge(
        "http_server_active_requests",
        "Number of HTTP server requests currently in flight.",
        label_names=("method",),
    )
    token_operations = Counter(
        "agent_auth_token_operations_total",
        "Count of token lifecycle operations by type.",
        label_names=("operation",),
    )
    validation_outcomes = Counter(
        "agent_auth_validation_outcomes_total",
        "Count of token validation outcomes by reason.",
        label_names=("outcome", "reason"),
    )
    approval_outcomes = Counter(
        "agent_auth_approval_outcomes_total",
        "Count of JIT approval outcomes.",
        label_names=("outcome",),
    )

    registry = Registry()
    for metric in (
        http_request_duration,
        http_active_requests,
        token_operations,
        validation_outcomes,
        approval_outcomes,
    ):
        registry.register(metric)

    return registry, AgentAuthMetrics(
        http_request_duration=http_request_duration,
        http_active_requests=http_active_requests,
        token_operations=token_operations,
        validation_outcomes=validation_outcomes,
        approval_outcomes=approval_outcomes,
    )
