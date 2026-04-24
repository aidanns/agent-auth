<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0029 — Benchmark suite with pytest-benchmark

## Status

Accepted — 2026-04-23.

## Context

`.claude/instructions/testing-standards.md` § Performance mandates a
maintained benchmark suite that runs in CI on a schedule to catch
regressions. Before this ADR no benchmark suite existed; the per-
request latency budget documented in `design/DESIGN.md` § Performance
budget was enforced only by unit tests carrying the `perf_budget`
pytest marker — useful for asserting a ceiling, but not for seeing
*trends* in the cost of the hot path.

Issue #40 names four benchmark targets: token validation (the hot
path), token create, refresh, and DB read of a family with many
scopes. The decision below picks a tool, a layout, and a regression
gate compatible with the existing CI topology.

## Considered alternatives

### Airspeed Velocity (`asv`)

Purpose-built for tracking benchmark time series across commits with
a hosted HTML dashboard.

**Rejected** because:

- Requires a persistent storage location (git branch, S3 bucket, or
  GitHub Pages deployment) for the historical database, which this
  project does not otherwise operate.
- Adds a second test runner alongside pytest for a benefit we do not
  need here — the hot-path surface is small enough that a pytest
  table in a CI log is enough signal.

### Hand-rolled `time.perf_counter` loop

Zero new dependencies.

**Rejected** because:

- No statistical rigour out of the box (warm-up, min-rounds,
  calibration, outlier handling). pytest-benchmark gives these
  defaults tuned for noisy CI runners.
- Re-solving a solved problem goes against the `.claude/instructions`
  bias toward off-the-shelf standard tooling where reasonable.

### Benchmarks interleaved with unit tests (under `tests/`)

Shorter import path and fewer directories.

**Rejected** because:

- `[tool.pytest.ini_options].addopts` already wires the coverage
  floor (`--cov=src --cov-fail-under=74`) for every pytest run. A
  benchmark-only pytest invocation would need to override the flag,
  and routine `task test` runs would pick up the benchmarks as
  regular tests and slow the suite.
- Separate tree aligns with `.claude/instructions/testing-standards.md`
  which discusses benchmarks independently from the unit and chaos
  layers.

## Decision

1. **Tool**: `pytest-benchmark` 5.x, added to
   `[project.optional-dependencies].dev` so developers get it on
   `uv sync --extra dev` and CI gets it via the same path.
2. **Layout**: `packages/agent-auth/benchmarks/` tree with its own
   `conftest.py`. A thin `scripts/benchmark.sh` wrapper overrides
   the project pytest `addopts` so coverage does not run against
   benchmarks.
3. **Coverage**: the four targets named in issue #40 —
   `verify_token`, `create_token_pair`, `TokenStore.get_family`
   (large scope count), plus adjacent steady-state points
   (`parse_token`, `sign_token`, `get_token`, `create_token`).
4. **Schedule**: Sunday 05:00 UTC weekly, offset from the Mutation
   workflow (Monday 04:00 UTC) so the two long-running scheduled
   workflows do not queue for the same runner window.
5. **Regression gate**: 25 % mean runtime, evaluated via
   `--benchmark-compare-fail=mean:25%` against a committed baseline
   at `packages/agent-auth/benchmarks/baselines/ci-linux-x86_64.json`. The gate is
   skipped when the baseline is absent so the first scheduled run
   can capture a baseline without failing.
6. **Baseline refresh**: CI-generated, human-committed. The
   procedure lives in `packages/agent-auth/benchmarks/README.md` — operator downloads
   the JSON artifact from a scheduled run, renames, commits.
7. **Standards gate**: `scripts/verify-standards.sh` asserts the
   `packages/agent-auth/benchmarks/` directory contains at least one
   `test_*.py` and the `benchmark.yml` workflow exists and triggers
   on `schedule:`, so later drift (someone deleting the benchmarks
   while leaving the workflow, or vice versa) fails verify-standards.

## Consequences

- Developers get a `task benchmark` command that produces a stable
  per-run report table, without touching the unit-test workflow.
- The regression gate is loose (25 %) on initial adoption and will
  flake less than a tighter gate would on GitHub-hosted runner
  variance. Tightening happens once the baseline stabilises; that
  is tracked inline in `packages/agent-auth/benchmarks/README.md` rather than as a
  separate issue.
- Baselines live in-repo under `packages/agent-auth/benchmarks/baselines/`. This
  couples the repo to a Linux-on-x86_64 runner assumption; a future
  macOS benchmark workflow would need its own baseline file
  (`ci-darwin-<arch>.json`). Out-of-scope today.
- The benchmark suite is distinct from the perf-budget tests: the
  budget tests assert a ceiling per request; the benchmarks expose
  trends. Both remain required by `testing-standards.md`.

## Follow-ups

- First scheduled run after merge produces the initial baseline
  artifact; a follow-up PR commits it. No separate issue — tracked
  inline in `packages/agent-auth/benchmarks/README.md` § "Baseline refresh procedure".
- Tightening the 25 % threshold once we have 4+ weeks of runs.
