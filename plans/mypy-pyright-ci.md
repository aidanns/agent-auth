# Wire mypy + pyright into CI (#48)

## Context

Issue #48 mandates mypy and pyright (both) running in CI on `src/` and
`tests/` per `.claude/instructions/python.md`. Today neither type checker
is configured; mypy `--strict` reports 118 errors across 18 source files,
and 655 errors across 41 test files.

The user has chosen the **foundation + ratchet** approach (option C):
land the infrastructure with strict defaults and per-module relaxations,
then file follow-up issues to tighten each relaxed module one at a time.
This mirrors how the coverage issue (#37) handles its floor — never
lowered without explicit justification, raised as the codebase improves.

The deterministic regression check from the issue requires:

1. `pyproject.toml` has `[tool.mypy]` with `strict = true`.
2. `pyrightconfig.json` exists with equivalent strictness.
3. At least one CI workflow runs both `mypy` and `pyright`.

## Plan

### Implementation

01. **Add mypy + pyright to dev dependencies.** Add `mypy>=1.20` and
    `pyright>=1.1.408` to `[project.optional-dependencies].dev` in
    `pyproject.toml`. Run `uv lock` to refresh `uv.lock`.

02. **Add mypy configuration to `pyproject.toml`.**

    - `[tool.mypy]` with `strict = true` as the default for new code.
    - `[[tool.mypy.overrides]]` entries relaxing `disallow_untyped_defs`,
      `disallow_untyped_calls`, and `disallow_any_generics` for each
      module in the current failure set. Each override comments the
      tracking issue that will ratchet it tighter.
    - `[[tool.mypy.overrides]]` for `tests.*` / `tests_support.*` /
      `tests.integration.*` with the same relaxations (tests are heavier
      on pytest fixture magic that strict mypy doesn't like).
    - `[[tool.mypy.overrides]]` for third-party imports without stubs
      (`keyring`, `testcontainers`, `yaml`) with `ignore_missing_imports`.

03. **Add `pyrightconfig.json`.**

    - `typeCheckingMode: "strict"` as default.
    - `ignore` list containing every `.py` file currently failing (same
      set as the mypy overrides). Pyright treats `ignore` as "don't
      report diagnostics", which matches the per-module relaxation
      intent.
    - `exclude` for `.venv*/`, `build/`, `dist/`, `.egg-info/`.
    - Track the venv via `venvPath` + `venv` so pyright picks up the
      per-OS/arch virtualenv (`.venv-$(uname -s)-$(uname -m)`). Fall
      back to `pythonVersion: "3.11"` when the venv isn't present (local
      CI bootstrap).

04. **Add `scripts/typecheck.sh`.**

    - `bash.md`-conformant shebang + description + `set -euo pipefail`.
    - Runs `mypy src tests` then `pyright` (pyright reads the config).
    - Follows the same pattern as `scripts/lint.sh` / `scripts/test.sh`.

05. **Add `task typecheck` to `Taskfile.yml`** that dispatches to the
    script. No need to add to `REQUIRED_TASKS` in
    `scripts/verify-standards.sh` — that list is reserved for the
    cross-project tooling standard; `typecheck` is Python-specific and
    belongs in `python.md` (implicit via the regression check added
    below).

06. **Wire into CI** — add `.github/workflows/typecheck.yml` that sets
    up the toolchain and runs `task typecheck`. Parallel to `check.yml`
    so type errors and lint errors surface independently.

07. **Update `scripts/verify-dependencies.sh`.** Not needed — mypy and
    pyright are dev dependencies installed into the project venv, not
    system tools. `task verify-dependencies` continues to only check
    system PATH tools.

08. **Update `scripts/verify-standards.sh`.** Add a regression check:

    - `[tool.mypy]` in `pyproject.toml` contains `strict = true`.
    - `pyrightconfig.json` exists at the repo root.
    - At least one `.github/workflows/*.yml` runs both `mypy` and
      `pyright` (the new `typecheck.yml` step).

09. **Update `CONTRIBUTING.md`.** Add `task typecheck` to the task
    catalogue table. Note in the Dev setup section that mypy and pyright
    ship via `uv sync --extra dev` — no separate install step.

10. **File follow-up ratcheting issues.** Group by module namespace to
    keep the issue count manageable:

    - `agent_auth/*` — 8 modules to tighten.
    - `things_bridge/*` — 4 modules.
    - `things_cli/*` + `things_client_common/*` + `things_models/*` —
      6 modules.
    - `tests/*` + `tests_support/*` + `tests/integration/*` — 41+
      modules; collapse into one issue since the pattern is uniform.
      Each follow-up issue lists the modules and the error codes the
      override currently disables. Closing the issue means removing the
      corresponding override and confirming `task typecheck` stays green.

### Design and verification

- **Verify implementation against design doc.** Tooling change — no
  behaviour/schema impact. Confirm by skimming `design/DESIGN.md`.
- **Threat model.** *Skipped.* Type checkers are a development-time
  correctness tool; they never run as part of the product.
  Justification identical to the ripsecrets skip in the #42 plan.
- **ADR.** No new architectural decision — standards-driven tooling.
- **Cybersecurity standard compliance.** N/A — not a runtime control.
- **QM/SIL compliance.** Type checking is supporting evidence for SI-10
  (Input Validation) and adjacent controls, but this PR doesn't change
  the assurance posture. `design/ASSURANCE.md` already lists mypy as
  part of the QM toolchain via the python.md reference; no update
  needed.

### Post-implementation standards review

- **Coding standards.** New bash script (`scripts/typecheck.sh`) must
  follow `bash.md` — shebang, set flags, description padded by blank
  lines.
- **Service design standards.** N/A.
- **Release and hygiene standards.** Add `## [Unreleased]` entry to
  `CHANGELOG.md`.
- **Testing standards.** No new runtime code; the regression check IS
  the test.
- **Tooling and CI standards.** This is the standard being implemented.

### Validation

- `task typecheck` — passes on the branch with the strict+relaxations
  config.
- `task verify-standards` — passes with the new regression check, and
  fails if `[tool.mypy]` loses `strict = true` / `pyrightconfig.json`
  is deleted / the CI workflow drops `mypy` or `pyright`.
- `task check` — existing gates still pass.
- Ratchet smoke-test: pick one relaxed module (smallest error set),
  remove its override, confirm `task typecheck` fails with a clear
  message. Restore the override before commit.

### Out of scope

- **Actually fixing the 118 + 655 errors.** Deferred to the ratcheting
  follow-up issues.
- **Third-party stub packages.** If `types-PyYAML` / similar stubs
  exist on PyPI, prefer those over `ignore_missing_imports`. Out of
  scope for this PR — tackled as part of the ratcheting per-module.
- **NewType / semantic type adoption (#22, #23, #24).** This PR only
  lands the checkers; the type-design work referenced in the issue's
  "Ties into" list is addressed by those separate issues.
