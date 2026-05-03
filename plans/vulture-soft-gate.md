<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Plan: Vulture as a per-package soft (advisory) dead-code gate

Issue: [#578](https://github.com/aidanns/agent-auth/issues/578).

Source standard: `.claude/instructions/python.md` (lint tooling) and
`.claude/instructions/tooling-and-ci.md` (workflow layout, child of
`check-lint.yml`).

## Goal

Add `vulture` as an advisory PR-time check that reports unused
functions, classes, methods, imports, variables, and attributes per
workspace package at `--min-confidence 80`. The check is non-failing:
findings surface in the workflow summary so reviewers see them, but
the job's overall conclusion is always `success` so it never blocks
merge. Suppression is annotation-driven — inline `# noqa` comments
where vulture supports them, and per-package `[tool.vulture]` knobs
for structural false-positive categories. There is no
workspace-wide whitelist module.

## Non-goals

- **Hard gate / required check.** A separate follow-up issue tracks
  promotion from soft to required; promotion is not in scope here.
- **Removing dead code surfaced by the initial run.** Real dead-code
  cleanup is incremental work tracked by separate PRs; this PR only
  pre-suppresses structural false positives so the initial advisory
  output is signal-rich.
- **Workspace-wide single invocation.** Triage explicitly chose the
  per-package shape mirroring `scripts/check-package-coverage.sh`.
- **Whitelist-module-based suppression** (`vulture-whitelist.py`).
  Triage explicitly rejected this approach.
- **Lowering the confidence threshold below 80.** Triage locked 80 as
  the conservative starting point.

## Deliverables

1. **`pyproject.toml`** — add `vulture>=2.16` to the workspace `dev`
   optional-dependencies group so it lands in the per-OS/arch venv.
2. **No per-package `[tool.vulture]` block** — the script invokes
   vulture with `--min-confidence 80 packages/<svc>/src` directly, so
   threshold and path live in one place (the script). Per-package
   config files are explicitly permitted by the brief but unnecessary
   here, and a single source for the threshold is easier to review.
   Every false positive is suppressed at its call site via
   `# noqa: F841,RUF100` — vulture honours `F841` for unused
   parameters per its README; `RUF100` silences ruff (which considers
   `F841` to apply only to unused-locals, not parameters, and would
   otherwise flag every suppression site as an "unused noqa").
3. **`scripts/check-dead-code.sh`** — new per-package helper that
   iterates `packages/*/`, invokes `uv run --no-sync vulture --config <pkg>/pyproject.toml <pkg>/src` per package, and emits
   findings to stdout grouped by package. Exits 0 always (advisory):
   non-zero vulture exit codes are translated to a banner ("found N
   results — advisory only"), so the gate cannot fail merge by
   accident.
4. **`task dead-code`** — workspace-level Taskfile entry that runs
   `scripts/check-dead-code.sh` so the gate is locally reproducible.
5. **`.github/workflows/check-lint.yml`** — add a new `dead-code`
   job alongside the existing `python` and `systems-engineering`
   children. The job:
   - bootstraps the venv (`scripts/_bootstrap_venv.sh` via
     `setup-toolchain`),
   - runs `scripts/check-dead-code.sh`,
   - writes findings to `$GITHUB_STEP_SUMMARY` so reviewers see them
     on the PR's Checks tab,
   - surfaces a `success` conclusion regardless of finding count
     (advisory contract).
6. **Pre-flight false-positive suppression** — add
   `# noqa: F841,RUF100` at each false-positive site:
   - `format` parameter on `log_message` overrides in every
     `BaseHTTPRequestHandler` subclass (six call sites today across
     `agent_auth/server.py`, `agent_auth_notifier/terminal_server.py`,
     `gpg_bridge/server.py`, `things_bridge/server.py`,
     `tests_support/notifier/server.py`, `tests_support/notifier_fake.py`).
   - `size` parameter on `log_request` overrides in
     `gpg_bridge/server.py` and `things_bridge/server.py`.
   - `list_id` parameter on the `ThingsClient.list_todos` Protocol
     method in `things_models/client.py` (one site only).
7. **`design/decisions/0047-vulture-soft-dead-code-gate.md`** — new
   ADR recording the soft-gate decision, the
   `--min-confidence 80` choice, the annotation-only suppression
   policy, and the deferred follow-up to promote to required.
8. **Follow-up issue** — open a tracking issue on
   `aidanns/agent-auth` for promoting the gate from soft to hard
   (required) once the noise floor stabilises. Link from the ADR
   and from the PR body.
9. **`changelog/@unreleased/pr-<N>-vulture-soft-gate.yml`** — author
   the changelog entry by hand (changelog-bot does not auto-author).
   Type is `feature`.

## Verification before push

- `task dead-code` runs locally and exits 0 with the expected
  findings list.
- `task lint` and `task format -- --check` still pass (pyproject.toml
  changes need to round-trip through ruff/taplo without churn).
- `scripts/verify-standards.sh` still passes — vulture is a venv-only
  tool, so it does not enter the tool-versions manifest.
- `scripts/verify-dependencies.sh` still passes for the same reason.
- The ADR and the follow-up issue are both linked from the PR body.

## Design and verification notes

- **Threat model** — N/A. This is a developer-tooling change that
  runs only inside CI / venv; it does not touch the runtime trust
  base, the token store, or any network surface.
- **QM / SIL** — no production code path is touched; the configuration
  changes are scoped to dev-only metadata
  (`pyproject.toml`, `.github/workflows/`, `scripts/`).
- **Cybersecurity standard (NIST SSDF / OWASP ASVS)** — adding a
  static-analysis check for unused code reinforces SSDF practice
  PW.7.1 ("review and analyse human-readable code"). It is not a
  blocker for any control we already meet.

## Post-implementation standards review

- **`coding-standards.md`** — script function names use verbs;
  config keys carry their unit (`min_confidence` is dimensionless,
  no unit needed).
- **`service-design.md`** — N/A (no new service surface).
- **`tooling-and-ci.md`** — new check is wired as a child of the
  correct parent (`check-lint.yml`) per the "Where a new check goes"
  rubric. Vulture is a Python static-analysis tool, so
  `check-lint.yml` is the right slot. No tool-versions manifest
  entry needed because vulture installs from PyPI through the venv.
- **`testing-standards.md`** — N/A (no new tests; the gate itself
  IS a test of the source tree).
- **`release-and-hygiene.md`** — changelog entry is required because
  the prefix is `feature(ci):` (release-entry-bearing). Hand-authored
  per project convention.
