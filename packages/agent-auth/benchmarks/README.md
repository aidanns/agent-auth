<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Benchmarks

Performance benchmarks for the token hot path and SQLite store, run
on a schedule in CI to catch regressions. Originating standard:
`.claude/instructions/testing-standards.md` § Performance —
"Benchmark suite". See
[ADR 0029](../../../design/decisions/0029-benchmark-suite.md)
for the decision record.

## Scope

Each benchmark file covers one layer of the stack:

- `test_tokens_benchmark.py` — `parse_token`, `sign_token`,
  `verify_token` (the per-request hot path), and `create_token_pair`
  (which underpins both token creation and refresh).
- `test_store_benchmark.py` — `TokenStore.get_family` for a family
  with 200 scopes (the "DB read of a family with many scopes" case
  from issue #40), plus `get_token` and `create_token` for
  steady-state DB numbers.

Benchmarks live under `packages/agent-auth/benchmarks/` — a sibling
of the package's `src/` and (future) `tests/` — because the
project-wide `[tool.pytest.ini_options].addopts` wires the coverage
floor (`--cov=packages --cov-fail-under=74`). Coverage against the
benchmark suite alone would always fail. The `scripts/benchmark.sh`
wrapper overrides `addopts` when running the benchmarks.

## Running locally

```bash
task benchmark
```

Pass-through arguments are forwarded to `pytest`:

```bash
# Narrow to a single benchmark
task benchmark -- -k verify_token

# Save a local baseline
task benchmark -- --benchmark-save=local

# Compare against a saved baseline
task benchmark -- --benchmark-compare=ci-linux-x86_64
```

Baselines are stored under `packages/agent-auth/benchmarks/baselines/`
— that directory is the configured `--benchmark-storage` root.

## Regression threshold

The documented threshold is **25 % mean runtime** (i.e. a benchmark
whose mean runtime increases by more than 25 % vs the most recent
committed baseline fails the scheduled CI job).

The threshold is deliberately loose. It balances:

- GitHub-hosted runner variance (second-by-second noise can reach
  10-15 % for nanosecond-scale benchmarks like `parse_token`);
- initial signal — we would rather catch a catastrophic 2× regression
  than flake on normal noise;
- a tightening path — once the suite has run for a few weeks and the
  baseline stabilises, the threshold can be lowered in a follow-up.

The gate applies only when
`packages/agent-auth/benchmarks/baselines/ci-linux-x86_64.json`
exists. If the baseline file is absent the scheduled job runs the
benchmarks, prints the table, and uploads the JSON artifact without
failing — see `Baseline refresh procedure` below.

## Baseline refresh procedure

Baselines are CI-generated rather than author-generated so the numbers
match the runner that will later be compared against.

1. Trigger the benchmark workflow manually
   (`gh workflow run benchmark.yml`).
2. Download the artifact produced by the run: the JSON report lands
   at `packages/agent-auth/benchmarks/results.json`.
3. Rename it to
   `packages/agent-auth/benchmarks/baselines/ci-linux-x86_64.json`
   (or whatever target runner it is for).
4. Commit under a `chore(benchmark):` prefix and open a PR. Include
   a brief note on what prompted the refresh (e.g. "after #123
   intentionally traded 10 % on get_family for DB correctness").

First baseline: the initial scheduled run after this PR merges is
what seeds `ci-linux-x86_64.json`. The threshold gate is inactive
until that baseline is committed.

## What this is _not_

Benchmarks measure; they do not assert a service-level budget. The
per-request latency budget is documented in
`design/DESIGN.md` § Performance budget and enforced by tests
carrying the `perf_budget` pytest marker. If the two disagree
(benchmarks regressed but the budget test still passes), the
benchmark is the leading indicator — the budget is a ceiling, not a
target.
