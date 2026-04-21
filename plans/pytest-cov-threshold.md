<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Enforce line+branch coverage threshold in CI with pytest-cov (#37)

## Context

Issue #37 mandates line+branch coverage in CI with a ratcheting floor,
per `.claude/instructions/testing-standards.md` (Coverage) and
`.claude/instructions/python.md` (Tooling: pytest-cov).

Baseline on `main` at time of this PR (unit-test pass only; integration
tests require Docker and run in a separate job):

```
uv run pytest --cov=src --cov-branch tests/ --ignore=tests/integration
TOTAL    2214 statements   516 missed   556 branches   71 partial   74.77%
```

Initial floor: **74** — one below the measured TOTAL so run-to-run
fluctuation (pytest collection order, platform-specific branches)
doesn't flake CI. The bump procedure in `CONTRIBUTING.md` formalises
this "one below TOTAL" convention.

Deterministic regression check from the issue:

1. `pyproject.toml` (or `pytest.ini`) sets `--cov-fail-under=<floor>`.
2. At least one CI workflow invokes `pytest --cov`.

## Plan

### Implementation

1. **Add `pytest-cov` to dev dependencies.** Add to
   `[project.optional-dependencies].dev` in `pyproject.toml`, refresh
   `uv.lock`.

2. **Configure pytest-cov in `pyproject.toml`.** Under
   `[tool.pytest.ini_options]`:

   - `addopts = ["--cov=src", "--cov-branch", "--cov-report=term-missing", "--cov-fail-under=74"]`
   - `[tool.coverage.run]` with `branch = true`, `source = ["src"]`.
   - `[tool.coverage.report]` with `show_missing = true` and
     `exclude_lines = [ ... ]` for common no-cover pragmas
     (`pragma: no cover`, `if TYPE_CHECKING:`,
     `raise NotImplementedError`, `if __name__ == ...`). An `omit`
     list wasn't needed — TOTAL already passes — so it's deferred to
     the ratchet stage if per-module exclusions become useful.

3. **Wire into existing CI Test workflow.** `scripts/test.sh --unit`
   currently runs unit tests. Extend it (or add an equivalent that the
   `test.yml` workflow calls) so unit runs produce coverage with the
   configured threshold. Integration tests in the parallel job do not
   gate the coverage threshold — the floor is computed from unit tests
   only (integration runtime is too Docker-heavy for quick per-PR
   measurement).

4. **Document ratchet mechanism in `CONTRIBUTING.md`.** A new
   "Coverage" subsection under "Running tasks" explaining:

   - `task test` prints coverage at the end; the threshold comes from
     `pyproject.toml`.
   - To bump the floor: run the test suite locally, read the new
     TOTAL %, update `--cov-fail-under` in `pyproject.toml`, commit
     alongside the coverage-improving changes.
   - Never lower the floor without an explicit justification commit
     message explaining why (e.g. test fixture refactor that
     deliberately removes redundant coverage).

5. **Update `scripts/verify-standards.sh`** with the deterministic
   regression check:

   - `pyproject.toml` contains `--cov-fail-under=<N>` in its pytest
     `addopts` (N must be a non-zero integer).
   - At least one `.github/workflows/*.yml` invokes `pytest --cov`
     (directly or through `task test`).

6. **Update `CHANGELOG.md`** with a `## [Unreleased]` entry.

### Design and verification

- **Verify implementation against design doc.** Tooling change — no
  behaviour/schema impact.
- **Threat model.** *Skipped.* Coverage reporting is a development-time
  tool; it never runs as part of the product.
- **ADR.** No new architectural decision.
- **Cybersecurity standard compliance.** N/A.
- **QM/SIL compliance.** Coverage is supporting evidence for the
  verification activity in `design/ASSURANCE.md`, but the level
  declaration doesn't change here.

### Post-implementation standards review

- **Coding standards.** N/A — no runtime code.
- **Service design.** N/A.
- **Release and hygiene.** CHANGELOG entry added.
- **Testing standards.** This IS the testing-standards implementation.
- **Tooling and CI.** Follow the existing `test.yml` shape;
  verify-standards extends the existing block of Python-tooling
  checks.

### Validation

- `task test` (or equivalent) — runs pytest with `--cov` and exits
  non-zero when coverage falls below 74.
- `task verify-standards` — passes; fails when `--cov-fail-under` is
  removed from `pyproject.toml` or when no CI workflow invokes
  `pytest --cov`.
- Manually bump the floor in a local commit (77), confirm CI would
  succeed; revert.
- Manually drop the floor to 76 with a test temporarily removed that
  drops coverage below 76, confirm CI would fail.

### Out of scope

- **Mutation testing** — separate issue.
- **Integration-test coverage** — the Docker-backed integration tests
  run in a separate CI job with their own cost profile; rolling them
  into the coverage floor would make the floor flaky. Tracked for a
  follow-up once we have a stable way to merge coverage artefacts
  from both jobs.
- **Per-module coverage floors** — the single TOTAL floor is enough
  for foundation; per-module is a ratchet refinement.
