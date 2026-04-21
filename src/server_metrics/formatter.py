# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Render a Registry to Prometheus text exposition format v0.0.4."""

from __future__ import annotations

from server_metrics.registry import Counter, Gauge, Registry

# Content type for `Content-Type: text/plain; version=0.0.4; charset=utf-8`
# per https://prometheus.io/docs/instrumenting/exposition_formats/
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _escape_help(text: str) -> str:
    # HELP lines only need backslash and newline escaping per the spec.
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(label_names: tuple[str, ...], label_values: tuple[str, ...]) -> str:
    if not label_names:
        return ""
    pairs = [
        f'{name}="{_escape_label_value(value)}"'
        for name, value in zip(label_names, label_values, strict=True)
    ]
    return "{" + ",".join(pairs) + "}"


def _format_float(value: float) -> str:
    # Prometheus accepts Go-style float formatting. Integer-valued
    # floats emit without a fractional part for readability, matching
    # prometheus_client's output.
    if value != value:  # NaN
        return "NaN"
    if value == float("inf"):
        return "+Inf"
    if value == float("-inf"):
        return "-Inf"
    if value.is_integer() and abs(value) < 1e16:
        return str(int(value))
    return repr(value)


def render_prometheus_text(registry: Registry) -> str:
    """Serialise a registry to Prometheus text exposition.

    Output is newline-terminated (the spec requires a trailing newline
    at EOF) and encodes one ``# HELP`` + ``# TYPE`` block per metric
    followed by its samples in registration order. A metric with no
    recorded samples still emits the HELP / TYPE lines so scrapers
    see the metric existence before the first observation.
    """
    parts: list[str] = []
    for metric in registry.metrics():
        parts.append(f"# HELP {metric.name} {_escape_help(metric.description)}")
        if isinstance(metric, Counter):
            parts.append(f"# TYPE {metric.name} counter")
            for label_values, value in metric.samples():
                parts.append(
                    f"{metric.name}{_format_labels(metric.label_names, label_values)} "
                    f"{_format_float(value)}"
                )
        elif isinstance(metric, Gauge):
            parts.append(f"# TYPE {metric.name} gauge")
            for label_values, value in metric.samples():
                parts.append(
                    f"{metric.name}{_format_labels(metric.label_names, label_values)} "
                    f"{_format_float(value)}"
                )
        else:
            # Metric = Counter | Gauge | Histogram; the two branches
            # above cover Counter / Gauge exhaustively, so anything
            # left is a Histogram (pyright narrows this automatically).
            parts.append(f"# TYPE {metric.name} histogram")
            bucket_label_names = (*metric.label_names, "le")
            for label_values, counts, sum_value in metric.samples():
                for i, upper in enumerate(metric.buckets):
                    bucket_label_values = (*label_values, _format_float(upper))
                    parts.append(
                        f"{metric.name}_bucket"
                        f"{_format_labels(bucket_label_names, bucket_label_values)} "
                        f"{counts[i]}"
                    )
                inf_label_values = (*label_values, "+Inf")
                parts.append(
                    f"{metric.name}_bucket"
                    f"{_format_labels(bucket_label_names, inf_label_values)} "
                    f"{counts[-1]}"
                )
                parts.append(
                    f"{metric.name}_sum"
                    f"{_format_labels(metric.label_names, label_values)} "
                    f"{_format_float(sum_value)}"
                )
                parts.append(
                    f"{metric.name}_count"
                    f"{_format_labels(metric.label_names, label_values)} "
                    f"{counts[-1]}"
                )
    return "\n".join(parts) + "\n"
