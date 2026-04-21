# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""In-process metric storage with label sets.

Each primitive is independently thread-safe. Labels are presented as
keyword arguments and stored as positional tuples in declaration order
to keep both snapshot reads and formatting O(1) per sample.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping

# OTel semconv's recommended HTTP latency buckets (seconds).
DEFAULT_HTTP_DURATION_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
)


def _validate_name(name: str) -> None:
    if not name:
        raise ValueError("metric name must be non-empty")
    # Prometheus metric-name grammar: [a-zA-Z_:][a-zA-Z0-9_:]*
    # We use a simpler, stricter subset that excludes ':' (reserved for
    # recording rules in ops-land) so nothing emitted here collides.
    valid = all(c.isalnum() or c == "_" for c in name)
    if not valid or not (name[0].isalpha() or name[0] == "_"):
        raise ValueError(f"invalid metric name: {name!r}")


def _labels_to_key(label_names: tuple[str, ...], labels: Mapping[str, str]) -> tuple[str, ...]:
    """Project a user-supplied label mapping onto the declared label order.

    Missing labels become the empty string rather than raising — mirrors
    prometheus_client's "labelless" path and lets callers omit labels
    they don't care about. Extra labels raise, since a silent drop would
    hide typos.
    """
    extra = set(labels) - set(label_names)
    if extra:
        raise ValueError(f"unexpected label(s): {sorted(extra)}")
    return tuple(labels.get(name, "") for name in label_names)


class Counter:
    """Monotonically increasing counter."""

    def __init__(self, name: str, description: str, label_names: Iterable[str] = ()) -> None:
        _validate_name(name)
        self.name = name
        self.description = description
        self.label_names: tuple[str, ...] = tuple(label_names)
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        if amount < 0:
            raise ValueError(f"Counter {self.name!r} cannot decrement")
        key = _labels_to_key(self.label_names, labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def samples(self) -> list[tuple[tuple[str, ...], float]]:
        """Return a point-in-time snapshot of label-values pairs."""
        with self._lock:
            return list(self._values.items())


class Gauge:
    """Gauge value that may go up or down."""

    def __init__(self, name: str, description: str, label_names: Iterable[str] = ()) -> None:
        _validate_name(name)
        self.name = name
        self.description = description
        self.label_names: tuple[str, ...] = tuple(label_names)
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = _labels_to_key(self.label_names, labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        self.inc(-amount, **labels)

    def set(self, value: float, **labels: str) -> None:
        key = _labels_to_key(self.label_names, labels)
        with self._lock:
            self._values[key] = value

    def samples(self) -> list[tuple[tuple[str, ...], float]]:
        with self._lock:
            return list(self._values.items())


class Histogram:
    """Cumulative histogram with caller-supplied bucket boundaries.

    Prometheus semantics: each ``_bucket{le="x"}`` count is the total
    number of observations with value <= x. The synthetic ``+Inf``
    bucket equals the total observation count and is emitted verbatim
    in the text format.
    """

    def __init__(
        self,
        name: str,
        description: str,
        label_names: Iterable[str] = (),
        buckets: Iterable[float] = DEFAULT_HTTP_DURATION_BUCKETS,
    ) -> None:
        _validate_name(name)
        self.name = name
        self.description = description
        self.label_names: tuple[str, ...] = tuple(label_names)
        sorted_buckets = tuple(sorted(buckets))
        if not sorted_buckets:
            raise ValueError(f"Histogram {name!r} requires at least one bucket")
        self.buckets: tuple[float, ...] = sorted_buckets
        # ``counts[i]`` for i in [0, len(buckets)] = <= buckets[i] count;
        # ``counts[len(buckets)]`` = +Inf bucket (== total observations).
        self._counts: dict[tuple[str, ...], list[int]] = {}
        self._sums: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, **labels: str) -> None:
        key = _labels_to_key(self.label_names, labels)
        with self._lock:
            counts = self._counts.get(key)
            if counts is None:
                counts = [0] * (len(self.buckets) + 1)
                self._counts[key] = counts
            for i, upper in enumerate(self.buckets):
                if value <= upper:
                    counts[i] += 1
            counts[-1] += 1  # +Inf / total count
            self._sums[key] = self._sums.get(key, 0.0) + value

    def samples(self) -> list[tuple[tuple[str, ...], list[int], float]]:
        with self._lock:
            return [
                (key, list(counts), self._sums.get(key, 0.0))
                for key, counts in self._counts.items()
            ]


Metric = Counter | Gauge | Histogram


class Registry:
    """An ordered collection of metrics.

    Registration order is preserved so the exposition output is
    deterministic for tests and eyeballing a ``curl`` response.
    """

    def __init__(self) -> None:
        self._metrics: list[Metric] = []
        self._names: set[str] = set()

    def register(self, metric: Metric) -> None:
        if metric.name in self._names:
            raise ValueError(f"metric {metric.name!r} already registered")
        self._metrics.append(metric)
        self._names.add(metric.name)

    def metrics(self) -> list[Metric]:
        return list(self._metrics)
