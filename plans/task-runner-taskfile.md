# Plan: Add `Taskfile.yml` (go-task) as Unified Task Runner

Issue: [#43](https://github.com/aidanns/agent-auth/issues/43).

Source standard: `.claude/instructions/tooling-and-ci.md` — *Orchestration
(go-task)*.

## Goal

Install `go-task` as the canonical task runner for this project and commit a
`Taskfile.yml` at the repo root whose `task --list` catalogue contains every
repeatable operation called out by the tooling-and-ci standard. Each task
dispatches to a `scripts/*.sh` implementation so the underlying shell scripts
remain the single source of truth (callable by CI, editors, humans, and the
Taskfile alike).

## Non-goals

- Wiring up the underlying formatters, linters, and git-hook manager
  (`ruff`, `shellcheck`, `shfmt`, `treefmt`, `lefthook`, `keep-sorted`,
  `ripsecrets`). Those are separate tooling-and-ci entries and will get
  their own issues.
- Automating the full release process — tracked separately in
  [#18](https://github.com/aidanns/agent-auth/issues/18). This plan delivers
  a `release` task surface and a script stub; #18 replaces the stub with a
  real implementation.

## Deliverables

1. `Taskfile.yml` at repo root with these tasks:
   - `test`, `lint`, `format`, `verify-design`, `verify-function-tests`,
     `verify-standards`, `release`, `build`, `install-hooks`.
2. `scripts/*.sh` implementation for each task. Use existing scripts where
   they already exist; stub the rest with a clear "not yet wired" message
   and exit code so the acceptance check (presence in `task --list`) passes
   and follow-up issues can replace the stub body without touching the
   Taskfile wiring.
3. `scripts/verify-standards.sh` — runs `task --list` (machine-readable
   form) and asserts every required task name is present. Exits non-zero
   with a clear message listing any missing tasks.
4. `.github/workflows/verify-standards.yml` — CI workflow that installs
   go-task and runs `scripts/verify-standards.sh`, per the tooling-and-ci
   rule that every check script must have a CI workflow.
5. `README.md` — replace the scattered shell commands in *Installation* /
   *Usage* with `task <name>` invocations as the canonical entrypoint, and
   keep a short "without go-task" pointer to `scripts/*.sh` for users who
   don't have `task` installed.
6. `CONTRIBUTING.md` — new file documenting the task-runner-first
   workflow (install go-task, `task --list`, common commands). Minimal
   scope; full CONTRIBUTING coverage (release cutting, signing, etc.) is
   out of scope.

## Design and verification

The following plan-template steps are **not applicable** and are
intentionally skipped:

- *Verify implementation against design doc* — the task runner is project
  infrastructure, not a behavioural component of the `agent-auth` service.
  It does not appear in `design/DESIGN.md`, `functional_decomposition.yaml`,
  or `product_breakdown.yaml`, and does not need to.
- *Threat model / cybersecurity standard compliance* — no change to the
  running service's attack surface, keys, or data flow. The Taskfile is a
  developer-tooling dispatcher; it is not loaded by the server or CLI at
  runtime.
- *QM / SIL compliance* — no change to the production code path or its
  evidence requirements.
- *ADRs* — go-task is already mandated by `.claude/instructions/tooling-and-ci.md`
  as the standard tool for this category. Adopting a pre-chosen standard
  tool is not a novel design decision that warrants a new ADR.

## Implementation steps

1. **Scripts** — create the missing `scripts/*.sh` files. Each follows the
   project's bash convention (`#!/usr/bin/env bash`, `set -euo pipefail`,
   description comment surrounded by blank lines).
   - `scripts/build.sh` — runs `python -m build` inside the project venv
     (non-stub; standard Python build with no extra dependencies).
   - `scripts/lint.sh` — stub that prints "linters not yet wired (see
     tooling-and-ci.md)" and exits 0 so CI doesn't regress before the
     real linters land. Exits 0, not non-zero, so `task lint` is
     callable today without surprising contributors.
   - `scripts/format.sh` — same stub pattern.
   - `scripts/release.sh` — stub pointing to #18; exits 1 because
     releasing without the automation is a footgun.
   - `scripts/install-hooks.sh` — stub pointing to the future lefthook
     issue; exits 0.
   - `scripts/verify-standards.sh` — real implementation; runs
     `task --list-all --json` and asserts the required task set is
     present. Exits 1 on any missing task.
2. **Taskfile.yml** — version 3 syntax; each task has a one-line
   description and a single `cmds:` entry that invokes the
   corresponding script. No hidden logic.
3. **CI** — add `.github/workflows/verify-standards.yml` mirroring the
   existing workflow structure (checkout, setup-python), plus a step to
   install go-task, then `scripts/verify-standards.sh`.
4. **README** — switch the canonical commands to `task <name>` and keep
   the "direct script" form as a fallback for environments without
   `task`.
5. **CONTRIBUTING.md** — create with sections: *Dev setup*,
   *Running tasks* (install go-task, `task --list`, common operations),
   *Commit conventions* (link to CLAUDE.md).

## Deterministic regression check

Per the issue: `scripts/verify-standards.sh` runs `task --list-all --json`
and asserts the presence of each required task name. A future regression
that removes or renames a required task fails CI immediately.

## Post-implementation standards review

Run each of the following against the diff (per CLAUDE.md → *Post-Change
Review*):

- [ ] `/simplify` on the changes.
- [ ] Independent code-review subagent; address findings.
- [ ] One parallel subagent per file in `.claude/instructions/` — each
  reviews the diff against its instruction file and reports
  violations. Address findings.

Specifically verify:

- **`coding-standards.md`** — script names are verbs or verb-phrases
  (`build.sh`, `verify-standards.sh`), no implicit units.
- **`bash.md`** — every new `*.sh` follows the standard header block.
- **`service-design.md`** — not applicable (no service changes).
- **`testing-standards.md`** — no behavioural code changes, so no new
  unit tests. The deterministic regression check *is* the test for this
  change.
- **`tooling-and-ci.md`** — `verify-standards.sh` has a CI workflow;
  the Taskfile is the canonical entrypoint.
- **`release-and-hygiene.md`** — `CONTRIBUTING.md` now exists (partial
  coverage acknowledged in the file; full coverage tracked separately).
- **`python.md`** — no Python-code changes.
