# Plan: Gate PRs with shellcheck and shfmt for bash scripts

Issue: [#51](https://github.com/aidanns/agent-auth/issues/51).

Source standard: `.claude/instructions/bash.md` — *shellcheck* and *shfmt*
gate PRs for every `*.sh` file.

## Goal

Gate PRs on bash linting (`shellcheck`) and formatting (`shfmt`) for every
tracked `*.sh` file. Wire both tools through the project's canonical
entrypoints: `Taskfile.yml` → `scripts/lint.sh` / `scripts/format.sh`, a new
`treefmt.toml`, a new `lefthook.yml` pre-commit stage, and a dedicated GitHub
Actions workflow. The existing scripts under `scripts/` must be brought into
compliance so CI is green on merge.

## Non-goals

- Wiring other formatters (`ruff`, `mdformat`, `taplo`) into `treefmt.toml` —
  tracked separately under issues [#47](https://github.com/aidanns/agent-auth/issues/47)
  and [#45](https://github.com/aidanns/agent-auth/issues/45).
- Adding `ripsecrets` or a fast unit-test subset to `lefthook.yml` — tracked
  under [#42](https://github.com/aidanns/agent-auth/issues/42). This plan
  introduces `lefthook.yml` and wires in shellcheck/shfmt only; #42 extends it.
- Building a container image with pinned tool versions — out of scope.

## Deliverables

1. **`treefmt.toml`** at repo root with a `shellcheck` formatter (lint mode)
   and a `shfmt` formatter covering every tracked `*.sh` file.
2. **`lefthook.yml`** at repo root with a `pre-commit` stage that runs
   `shellcheck` and `shfmt` on staged `*.sh` files. Wired so future issues
   (#42) can append additional hooks without restructuring.
3. **`scripts/lint.sh`** — replaces the placeholder with a real implementation
   that runs `shellcheck` against every tracked `*.sh` file in the repo.
   Exits non-zero on any finding.
4. **`scripts/format.sh`** — replaces the placeholder with a real implementation
   that runs `shfmt -w` to write canonical formatting. A `--check` mode runs
   `shfmt -d` (diff) and exits non-zero on any drift; CI uses this mode.
5. **`.github/workflows/check.yml`** — new unified "Check" workflow that
   installs `shellcheck` and `shfmt` (and future cross-language lint/format
   tooling), runs `task verify-dependencies` as a preflight, then invokes
   `task check` (which wraps `task lint` + `task format -- --check`). Gates
   PRs for every `*.sh`; extension points for other languages land in the
   same workflow rather than fanning out per-language workflows.
6. **`scripts/verify-standards.sh`** — extend with a new deterministic check
   that asserts:
   - At least one `.github/workflows/*.yml` invokes `shellcheck` AND `shfmt`.
   - `treefmt.toml` exists and references both `shellcheck` and `shfmt`.
   - `lefthook.yml` exists and references both `shellcheck` and `shfmt` in
     its `pre-commit` stage.
7. **Existing scripts brought into compliance** — run `shfmt -w` and
   `shellcheck` over every `scripts/*.sh`, fix any findings by hand where
   auto-format is not applicable.
8. **`CONTRIBUTING.md`** — document how to install `shellcheck` and `shfmt`,
   and how to run `task lint` / `task format` locally.
9. **`README.md`** — no substantive change expected; verify links are still
   correct after CONTRIBUTING updates.

## Design and verification

The following plan-template steps are **not applicable** and are
intentionally skipped:

- *Verify implementation against design doc* — bash linting and formatting
  is developer tooling, not a behavioural component of `agent-auth` or
  `things-bridge`. It does not appear in `design/DESIGN.md`,
  `functional_decomposition.yaml`, or `product_breakdown.yaml`, and does
  not need to.
- *Threat model / cybersecurity standard compliance* — no change to the
  running service's attack surface, keys, or data flow. These tools run at
  developer-time and CI-time only.
- *QM / SIL compliance* — no change to the production code path or its
  evidence requirements.
- *ADRs* — `shellcheck` and `shfmt` are already mandated by
  `.claude/instructions/bash.md` as the standard tools for this category.
  Adopting a pre-chosen standard tool is not a novel design decision.

## Implementation steps

1. **Configure shfmt flags via `.editorconfig`** — settle on two-space
   indent, case indent, and binary ops on next line (matches the existing
   script style). Commit an `.editorconfig` at repo root that `shfmt`
   reads automatically, so every invocation path (local, pre-commit, CI,
   task runner) gets the same flags without duplicating a literal
   `-i 2 -ci -bn` in three config files.
2. **`scripts/lint.sh`** — discover every tracked `*.sh` file via
   `git ls-files '*.sh'`, then exec `shellcheck` on the batch. Fail fast on
   any finding. Guard against `shellcheck` not being on `PATH` with a clear
   install hint (same pattern as `scripts/install-hooks.sh`).
3. **`scripts/format.sh`** — same discovery logic as `lint.sh`. Accept a
   `--check` flag: default runs `shfmt -w` (write in place); `--check` runs
   `shfmt -d` (diff) and exits non-zero if any diff is produced. Guard
   `shfmt` presence with an install hint.
4. **`treefmt.toml`** — two formatters: one for `shellcheck` (treefmt
   supports lint-mode formatters via `options`), one for `shfmt`. Both
   match `*.sh`.
5. **`lefthook.yml`** — `pre-commit` stage with two commands: `shellcheck`
   and `shfmt -d`, each run only on staged `*.sh` files (using lefthook's
   `{staged_files}` substitution). Glob restricted to `*.sh`. shfmt flags
   come from `.editorconfig`, not inline.
6. **`.github/workflows/check.yml`** — mirror the `verify-standards.yml`
   skeleton. Install `shellcheck` and `shfmt` from pinned GitHub releases
   (both tools are also declared in `scripts/verify-dependencies.sh` so the
   preflight catches drift). Run `task verify-dependencies` then
   `task check`. Job name is `check` and the workflow is a single
   cross-language "check" entrypoint rather than one-per-language.
7. **`scripts/verify-standards.sh`** — extend the existing script with a
   section that uses `grep` against `treefmt.toml`, `lefthook.yml`, and
   `.github/workflows/*.yml` to assert the three regression checks above.
   Fail fast with a clear message per missing invocation. Keep the existing
   Taskfile check intact.
8. **Bring existing scripts into compliance** — run `scripts/format.sh`
   and `scripts/lint.sh` over every tracked `*.sh` and address any
   findings. Expected changes are minor (one heredoc reformat in
   `verify-standards.sh` per a pre-check).
9. **Docs** — update `CONTRIBUTING.md` *Dev setup* with `shellcheck` / `shfmt`
   install steps (apt on Linux, Homebrew on macOS). Link from the *Running
   tasks* table row for `task lint` / `task format`.

## Deterministic regression check

Per the issue: `scripts/verify-standards.sh` asserts that `shellcheck` and
`shfmt` are invoked by at least one `.github/workflows/*.yml` file AND are
wired into `treefmt.toml` / `lefthook.yml`. Concrete checks:

- `grep -qE '\bshellcheck\b'` over `.github/workflows/*.yml` → at least one match.
- `grep -qE '\bshfmt\b'` over `.github/workflows/*.yml` → at least one match.
- `treefmt.toml` contains `shellcheck` and `shfmt`.
- `lefthook.yml` contains `shellcheck` and `shfmt` under `pre-commit`.

A future regression that removes any of these wirings fails `task
verify-standards` immediately.

## Post-implementation standards review

Run each of the following against the diff (per CLAUDE.md → *Post-Change
Review*):

- [ ] `/simplify` on the changes.
- [ ] Independent code-review subagent; address findings.
- [ ] One parallel subagent per file in `.claude/instructions/` — each
      reviews the diff against its instruction file and reports
      violations. Address findings.

Specifically verify:

- **`coding-standards.md`** — script names are verbs (`lint.sh`,
  `format.sh`), flags have explicit names.
- **`bash.md`** — every `*.sh` passes `shellcheck` and `shfmt` (by
  construction, since CI gates on it).
- **`service-design.md`** — not applicable (no service changes).
- **`testing-standards.md`** — no behavioural code changes, so no new unit
  tests. The deterministic regression check *is* the test.
- **`tooling-and-ci.md`** — `scripts/lint.sh` and `scripts/format.sh` have a
  CI workflow; the Taskfile surfaces are unchanged.
- **`release-and-hygiene.md`** — no changes to required project files.
- **`python.md`** — no Python-code changes.
