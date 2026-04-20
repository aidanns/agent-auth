<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Migrate Tooling from pip/venv to uv

Issue: [#49](https://github.com/aidanns/agent-auth/issues/49).

Source standard: `.claude/instructions/python.md` — *`uv`* (virtual
environment and dependency resolution). The standard explicitly
requires pointing uv at `.venv-$(uname -s)-$(uname -m)/` via
`UV_PROJECT_ENVIRONMENT` so macOS and Linux venvs can coexist on a
shared filesystem.

## Goal

Replace the `python3 -m venv` + `pip install -e ".[dev]"` bootstrap
across every `scripts/*.sh` and CI workflow with a single `uv`-based
path. Commit a `uv.lock` for reproducibility. Retain the per-OS/arch
`.venv-$(uname -s)-$(uname -m)/` location that matches the existing
convention (and the python.md standard).

## Non-goals

- Migrating the build-backend away from setuptools / setuptools-scm.
  uv works with any PEP 517 backend; the issue is about tooling, not
  packaging.
- Adopting uv's `dependency-groups` (PEP 735) instead of
  `[project.optional-dependencies].dev`. uv syncs extras with
  `--extra dev` just fine; keeping the existing layout minimises churn
  and stays interoperable with plain `pip install -e ".[dev]"` for
  anyone who hasn't installed uv yet.
- Migrating the dependabot ecosystem. `package-ecosystem: "pip"` is
  the dependabot name for Python dependency tracking regardless of
  resolver; dependabot understands `pyproject.toml` and `uv.lock`
  under that ecosystem.

## Deliverables

01. `scripts/test.sh`, `scripts/build.sh`, `scripts/agent-auth.sh`,
    `scripts/things-bridge.sh`, `scripts/things-cli.sh` — replace the
    `python3 -m venv` + `pip install` bootstrap with a single
    `uv sync --extra dev --quiet` and dispatch with `uv run`.
02. `uv.lock` committed at the repo root.
03. `pyproject.toml` — no structural change; add minimal uv
    configuration (e.g. `required-version`) only if needed.
04. `scripts/verify-dependencies.sh` — require `uv` on PATH.
05. `scripts/verify-standards.sh` — add two new checks:
    - `uv lock --check` (fails if `uv.lock` is missing or stale
      relative to `pyproject.toml` — a single call covers both cases).
    - Fail if any file under `scripts/` invokes `pip install` (or
      `pip3 install`, including backslash-newline continuations).
06. CI workflows (`test.yml`, `check.yml`, `verify-standards.yml`,
    `verify-design.yml`, `verify-function-tests.yml`) — install uv via
    `astral-sh/setup-uv@v5` (pinned), drop `actions/setup-python@v5`
    (uv manages the interpreter), and let the existing `task ...`
    invocations drive the work.
07. `README.md` — document `uv` as a prerequisite alongside `go-task`.
    Update the "bare Python install" fallback to use `uv sync --extra dev`.
08. `CONTRIBUTING.md` — add `uv` to the prerequisites list; reword the
    bootstrap description.
09. `CLAUDE.md` — update the activation command to `uv sync --extra dev`
    and reference `uv run` in place of `pip install -e .`.
10. `.github/dependabot.yml` — no change (the `pip` ecosystem already
    covers uv-managed projects).

## Design and verification

The following plan-template steps are **not applicable** and are
intentionally skipped:

- *Verify implementation against design doc* — tooling migration;
  no behavioural change to the `agent-auth` service, no schema change,
  no appearance in `design/DESIGN.md`, `functional_decomposition.yaml`,
  or `product_breakdown.yaml`.
- *Threat model / cybersecurity standard compliance* — no change to
  the running service's attack surface. The resolver changes at
  developer-machine and CI time; no new code runs in-process for the
  HTTP services. uv verifies package hashes from `uv.lock` by default
  during `uv sync`, which is strictly stronger than the previous
  `pip install -e` flow (no pinning, no hash verification).
- *QM / SIL compliance* — no change to the production code path or
  its evidence requirements.
- *ADRs* — uv is already mandated by `.claude/instructions/python.md`
  as the project's standard resolver. Adopting a pre-chosen standard
  tool is not a novel design decision (same reasoning as the Taskfile
  adoption in `plans/task-runner-taskfile.md`).

## Implementation steps

1. **Install uv locally** so `uv lock` can generate the initial
   lockfile.
2. **`uv.lock`** — run `UV_PROJECT_ENVIRONMENT=".venv-$(uname -s)-$(uname -m)" uv lock`
   to resolve and lock the dependency graph from `pyproject.toml`.
3. **Scripts** — rewrite the five venv-aware scripts. Template:
   ```bash
   export UV_PROJECT_ENVIRONMENT=".venv-$(uname -s)-$(uname -m)"
   uv sync --extra dev --quiet
   exec uv run --no-sync <entrypoint> "$@"
   ```
   For `test.sh`, replace the `exec` line with
   `exec uv run --no-sync pytest tests/ "$@"`. For `build.sh`,
   `exec uv run --no-sync python -m build --outdir "${REPO_ROOT}/dist"`.
   `--no-sync` avoids re-resolving on every dispatch after the initial
   `uv sync`.
4. **`verify-dependencies.sh`** — add `uv` to `REQUIRED_TOOLS`.
5. **`verify-standards.sh`** — add:
   - a `uv lock --check` step that runs only when `pyproject.toml`
     exists. A single call covers both missing and stale lockfiles
     (both exit non-zero).
   - a grep that fails if any `scripts/*.sh` file (excluding the
     check itself) invokes `pip install` or `pip3 install`. Collapse
     backslash-newline continuations before stripping comments so
     line-wrapped invocations are still caught, and reuse the
     existing `strip_comments` helper to avoid false positives from
     heredoc references.
6. **CI workflows** — replace `actions/setup-python@v5` with
   `astral-sh/setup-uv@v5` in all five workflows. Let the action track
   its bundled latest uv (no `version` input) — Dependabot tracks the
   `@v5` action ref but does not touch `with:` inputs, so pinning the
   uv version there would freeze it indefinitely. Remove the
   python-version setup — uv reads `requires-python` from
   `pyproject.toml` and installs a matching CPython on demand. Add
   `enable-cache: true` so the runner caches `~/.cache/uv` across
   runs. No Taskfile changes are needed because `task test` already
   dispatches to `scripts/test.sh`.
7. **Docs** — README gains a prerequisites line for uv
   (`brew install uv` on macOS, `curl -LsSf https://astral.sh/uv/install.sh | sh`
   elsewhere). The "bare install" block becomes
   `uv sync --extra dev` (no activation required; `uv run <cmd>` is
   the canonical entrypoint). CONTRIBUTING.md mirrors the same
   prerequisite list. CLAUDE.md replaces the `pip install -e .` line
   with `uv sync --extra dev` and the activation line with a pointer
   to `uv run`.
8. **`.gitignore`** — already covers `.venv*/`; nothing to change.

## Deterministic regression check

Per the issue: `scripts/verify-standards.sh` runs `uv lock --check`
and fails if any file under `scripts/` invokes `pip install`. A
regression that drifts the lockfile or reintroduces a pip-based
bootstrap in a script will fail CI immediately.

## Post-implementation standards review

Run each of the following against the diff (per CLAUDE.md → *Post-Change
Review*):

- [ ] `/simplify` on the changes.
- [ ] Independent code-review subagent; address findings.
- [ ] One parallel subagent per file in `.claude/instructions/` — each
  reviews the diff against its instruction file and reports
  violations. Address findings.

Specifically verify:

- **`coding-standards.md`** — no Python or identifier changes.
- **`bash.md`** — every touched `*.sh` still follows the standard
  header block (`#!/usr/bin/env bash`, `set -euo pipefail`, blank
  line, description comment, blank line).
- **`service-design.md`** — not applicable (no service changes).
- **`testing-standards.md`** — no behavioural code changes; the
  regression check in `verify-standards.sh` is the test for this
  change.
- **`tooling-and-ci.md`** — the `verify-standards` CI workflow still
  covers the new check. `task test` / `task build` remain the
  canonical entrypoints.
- **`release-and-hygiene.md`** — CONTRIBUTING.md still documents the
  dev setup prerequisites.
- **`python.md`** — uv is now the sole resolver; `UV_PROJECT_ENVIRONMENT`
  points at `.venv-$(uname -s)-$(uname -m)/` per the standard.
