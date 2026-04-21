# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for server_metrics primitives and Prometheus text formatter."""

from __future__ import annotations

import pytest

from server_metrics import (
    PROMETHEUS_CONTENT_TYPE,
    Counter,
    Gauge,
    Histogram,
    Registry,
    render_prometheus_text,
)


def test_counter_increments_and_cannot_go_negative():
    c = Counter("requests_total", "Request count.", label_names=("method",))
    c.inc(method="GET")
    c.inc(method="GET")
    c.inc(method="POST", amount=3)
    samples = dict(c.samples())
    assert samples[("GET",)] == 2
    assert samples[("POST",)] == 3
    with pytest.raises(ValueError):
        c.inc(amount=-1, method="GET")


def test_counter_rejects_unknown_labels():
    c = Counter("x_total", "desc", label_names=("a",))
    with pytest.raises(ValueError):
        c.inc(b="oops")


def test_gauge_goes_up_and_down_and_supports_set():
    g = Gauge("active", "Active count.", label_names=())
    g.inc()
    g.inc(2)
    g.dec()
    samples = dict(g.samples())
    assert samples[()] == 2
    g.set(10)
    assert dict(g.samples())[()] == 10


def test_histogram_buckets_are_cumulative_and_track_sum():
    h = Histogram(
        "latency_seconds",
        "Latency.",
        label_names=("route",),
        buckets=(0.1, 0.5, 1.0),
    )
    for v in (0.05, 0.2, 0.8, 1.5):
        h.observe(v, route="/foo")
    ((labels, counts, sum_value),) = h.samples()
    assert labels == ("/foo",)
    # buckets: <=0.1, <=0.5, <=1.0, +Inf
    assert counts == [1, 2, 3, 4]
    assert sum_value == pytest.approx(0.05 + 0.2 + 0.8 + 1.5)


def test_histogram_requires_buckets():
    with pytest.raises(ValueError):
        Histogram("bad", "desc", buckets=())


def test_registry_preserves_registration_order_and_rejects_duplicates():
    r = Registry()
    a = Counter("a_total", "A")
    b = Counter("b_total", "B")
    r.register(a)
    r.register(b)
    assert [m.name for m in r.metrics()] == ["a_total", "b_total"]
    with pytest.raises(ValueError):
        r.register(Counter("a_total", "dup"))


def test_render_emits_help_type_and_samples_in_order():
    r = Registry()
    c = Counter("http_requests_total", "HTTP request count.", label_names=("method",))
    c.inc(method="GET")
    r.register(c)
    text = render_prometheus_text(r)
    assert text.endswith("\n")
    lines = text.splitlines()
    assert lines[0] == "# HELP http_requests_total HTTP request count."
    assert lines[1] == "# TYPE http_requests_total counter"
    assert lines[2] == 'http_requests_total{method="GET"} 1'


def test_render_escapes_backslash_quote_and_newline_in_label_values():
    r = Registry()
    c = Counter("edge_total", "edge", label_names=("path",))
    c.inc(path='a"b\\c\nd')
    r.register(c)
    text = render_prometheus_text(r)
    assert 'path="a\\"b\\\\c\\nd"' in text


def test_render_histogram_emits_bucket_sum_and_count_lines():
    r = Registry()
    h = Histogram(
        "http_duration_seconds",
        "Request duration.",
        label_names=("route",),
        buckets=(0.1, 1.0),
    )
    h.observe(0.05, route="/x")
    h.observe(0.5, route="/x")
    r.register(h)
    text = render_prometheus_text(r)
    # Every bucket line plus +Inf, sum, count present.
    assert 'http_duration_seconds_bucket{route="/x",le="0.1"} 1' in text
    assert 'http_duration_seconds_bucket{route="/x",le="1"} 2' in text
    assert 'http_duration_seconds_bucket{route="/x",le="+Inf"} 2' in text
    assert 'http_duration_seconds_count{route="/x"} 2' in text
    assert 'http_duration_seconds_sum{route="/x"}' in text


def test_render_handles_zero_sample_metric():
    r = Registry()
    r.register(Counter("unused_total", "Never touched."))
    text = render_prometheus_text(r)
    lines = text.splitlines()
    assert lines == [
        "# HELP unused_total Never touched.",
        "# TYPE unused_total counter",
    ]


def test_prometheus_content_type_matches_spec():
    assert PROMETHEUS_CONTENT_TYPE == "text/plain; version=0.0.4; charset=utf-8"
