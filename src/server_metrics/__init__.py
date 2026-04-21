# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Thread-safe Prometheus metrics primitives and exposition formatter.

Hand-rolled so agent-auth and things-bridge can expose `/metrics`
without taking a dependency on `prometheus_client` or the
OpenTelemetry SDK. ADR 0017 pins the project to OTel semconv names,
not their SDK. Primitives are intentionally minimal — `Counter`,
`Gauge`, `Histogram`, `Registry` — and reproduce only the Prometheus
text-exposition features the two services emit today.
"""

from server_metrics.formatter import (
    PROMETHEUS_CONTENT_TYPE,
    render_prometheus_text,
)
from server_metrics.registry import (
    DEFAULT_HTTP_DURATION_BUCKETS,
    Counter,
    Gauge,
    Histogram,
    Registry,
)

__all__ = [
    "Counter",
    "DEFAULT_HTTP_DURATION_BUCKETS",
    "Gauge",
    "Histogram",
    "PROMETHEUS_CONTENT_TYPE",
    "Registry",
    "render_prometheus_text",
]
