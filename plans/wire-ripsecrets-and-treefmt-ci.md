# Wire ripsecrets pre-commit + treefmt CI gate (#42)

## Context

Issue #42 mandates `treefmt` (formatter multiplexer), `lefthook` (git hook
manager), and `ripsecrets` (secret-scanning pre-commit) per
`.claude/instructions/tooling-and-ci.md`. Today:

- `treefmt.toml` exists with formatters wired (mdformat, ruff, shellcheck,
  shfmt, taplo).
- `lefthook.yml` exists with per-formatter pre-commit commands but does
  **not** invoke `treefmt` directly and does **not** invoke `ripsecrets`.
- `ripsecrets` is not installed by `setup-toolchain`, not in
  `verify-dependencies.sh`, and has no config baseline.
- No CI workflow runs `treefmt --ci` (CI uses the project-authoritative
  `task check` which dispatches to `scripts/lint.sh` + `scripts/format.sh --check`).
- `verify-standards.sh` does not yet assert the new requirements.

The deterministic regression check from the issue requires:

1. `treefmt.toml` and `lefthook.yml` exist at the repo root.
2. `lefthook.yml` pre-commit stage includes `ripsecrets` and `treefmt`.
3. At least one CI workflow runs `treefmt --ci` (or equivalent check mode).

## Plan

### Implementation

1. **Add `ripsecrets` to the toolchain.**

   - Pin a version (latest stable) in
     `.github/actions/setup-toolchain/action.yml` and install via
     `uv tool install ripsecrets==<version>` (it ships on PyPI as
     `ripsecrets`). Confirm uv-tool installation works in CI; fall back
     to `cargo install` only if the PyPI artefact is unavailable.
   - Add `ripsecrets` to `REQUIRED_TOOLS` in
     `scripts/verify-dependencies.sh` so local `task verify-dependencies`
     surfaces a missing install.

2. **Add `ripsecrets`, `treefmt`, and a fast unit-test subset to
   `lefthook.yml`.**

   - Add a `ripsecrets` pre-commit command running over `{staged_files}`
     (so it scans only the diff, not the whole tree, on every commit).
   - Replace the per-language formatter check entries (mdformat, ruff
     format, shellcheck, shfmt, taplo) with a single `treefmt --no-cache --fail-on-change {staged_files}` entry — treefmt multiplexes them
     via `treefmt.toml`. Keep `keep-sorted` and `ruff-check` as separate
     entries (neither is a treefmt formatter).
   - Add a `test-fast` pre-commit command that runs `bash scripts/test.sh --fast -q` (a curated smoke subset: tokens, scopes, crypto, keys —
     the security-critical core, sub-second runtime). Required by
     `.claude/instructions/tooling-and-ci.md` Orchestration ("quick unit
     tests on pre-commit"). Add `--fast` mode to `scripts/test.sh` so
     the curated test list lives in the test runner, not lefthook.

3. **Wire `treefmt --ci` into CI.**

   - Extend `.github/workflows/check.yml` with a `Run treefmt --ci` step
     after the existing `task check` step. This satisfies the issue's
     "at least one CI workflow runs `treefmt --ci`" requirement without
     replacing the project-authoritative `task check` gate.
   - `treefmt` is not yet in the toolchain. Pin a version in
     `setup-toolchain/action.yml` and install it (treefmt is a Go binary
     released on GitHub).

4. **Add a `ripsecrets` baseline if necessary.**

   - Run `ripsecrets` over the current tree. If it flags false positives
     (e.g. fixture data in `tests/`), add a `.ripsecretsignore` (or the
     tool's equivalent baseline mechanism — confirm syntax) at the repo
     root, listing each false-positive path with a comment explaining
     why. If no false positives surface, skip this step.

5. **Document the install in `CONTRIBUTING.md`.**

   - The dev-setup section already mentions `task install-hooks`. Confirm
     it explicitly references `lefthook install` (or the wrapping task)
     and `ripsecrets` as part of the required tooling list. Update the
     section if either is missing.

6. **Update `scripts/verify-standards.sh` with the new assertions.**

   - Add a check that `treefmt.toml` and `lefthook.yml` exist at the
     repo root (currently only their *contents* are spot-checked).
   - Add a check that `lefthook.yml`'s pre-commit stage includes
     `ripsecrets` and `treefmt` (comment-stripped grep, matching the
     existing pattern).
   - Add a check that at least one `.github/workflows/*.yml` runs
     `treefmt --ci`.

### Design and verification

- **Verify implementation against design doc.** This is a tooling
  change with no behaviour or schema impact, so the design doc should
  not need updating. Confirm by skimming `design/DESIGN.md` for any
  reference to formatter or pre-commit policy.
- **Threat model.** *Skipped.* ripsecrets is a development-time
  control (pre-commit hook + CI gate); it never runs as part of the
  product. `SECURITY.md` documents the runtime/product threat model,
  and the cybersecurity-standard table (NIST 800-53) explicitly
  scopes out personnel and supply-chain controls. Pre-commit secret
  scanning belongs to the SDLC discipline (CONTRIBUTING.md +
  CHANGELOG.md), not the product threat model.
- **ADR.** No new architectural decision — this is a standards-driven
  tooling addition. Skip ADR.
- **Cybersecurity standard compliance.** Check whether the chosen
  cybersecurity standard in `SECURITY.md` lists pre-commit secret
  scanning as a control; if so, mark the gap closed there.
- **QM/SIL compliance.** Tooling change; no QM/SIL evidence impact.
  Confirm by skimming `design/ASSURANCE.md`.

### Post-implementation standards review

- **Coding standards.** Bash scripts only — verify
  `#!/usr/bin/env bash`, `set -euo pipefail`, single-blank-line
  description comment.
- **Service design standards.** N/A — no runtime service code touched.
- **Release and hygiene standards.** Add a `## [Unreleased]` entry to
  `CHANGELOG.md` describing the tooling addition.
- **Testing standards.** No new runtime code; the regression check
  IS the test. Confirm by running `task verify-standards` after the
  changes.
- **Tooling and CI standards.** This is the standard being implemented.
  Cross-check the issue's deterministic regression check fires green
  and red appropriately.

### Validation

- `task verify-dependencies` — confirms ripsecrets and treefmt land on
  PATH after a fresh `setup-toolchain` run.
- `task verify-standards` — confirms the new assertions pass on the
  branch and would fail if ripsecrets or treefmt were removed from
  lefthook/CI.
- `task check` — confirms the existing gate still passes.
- Manual: stage a fake secret in a test file, run `git commit`, confirm
  ripsecrets blocks the commit. Roll back the fake secret before
  pushing.

### Out of scope

- Replacing `scripts/lint.sh` + `scripts/format.sh` with `treefmt` as
  the sole authoritative gate. The project intentionally keeps the
  scripts as the per-tool entry points (`treefmt.toml` comment notes
  this); converting to a single treefmt-only flow is a separate PR.
- Tuning ripsecrets' regex set or false-positive baseline beyond what
  surfaces on first run.
