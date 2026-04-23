# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Metric declarations and registry builder for things-bridge.

The bridge has no persistent state — its domain outcomes (authz
denials, Things-app failures) are captured as ``status_code`` labels
on the HTTP duration histogram rather than as separate counters.
"""

from __future__ import annotations

from dataclasses import dataclass

from server_metrics import Gauge, Histogram, Registry


@dataclass(frozen=True)
class ThingsBridgeMetrics:
    """Handle to every metric things-bridge emits."""

    http_request_duration: Histogram
    http_active_requests: Gauge


def build_registry() -> tuple[Registry, ThingsBridgeMetrics]:
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

    registry = Registry()
    for metric in (http_request_duration, http_active_requests):
        registry.register(metric)

    return registry, ThingsBridgeMetrics(
        http_request_duration=http_request_duration,
        http_active_requests=http_active_requests,
    )
