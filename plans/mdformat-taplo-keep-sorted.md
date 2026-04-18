# Plan: Adopt mdformat, taplo, and keep-sorted

Issue: [#45](https://github.com/aidanns/agent-auth/issues/45).

Source standard: `.claude/instructions/tooling-and-ci.md` — *Markdown*
(`mdformat` with GFM + tables plugins), *TOML* (`taplo`), *Orchestration*
(`keep-sorted` for sorted-block annotations).

## Goal

Adopt `mdformat`, `taplo`, and `keep-sorted` as the project's standard
formatters/linters for Markdown, TOML, and sorted-block annotations. Wire
all three through the existing orchestration surfaces — `treefmt.toml`
(formatter multiplexer), `lefthook.yml` (pre-commit hooks),
`Taskfile.yml`/`scripts/*.sh` (canonical local entrypoints),
`.github/workflows/check.yml` (CI gate),
`scripts/verify-dependencies.sh` (tooling preflight), and
`scripts/verify-standards.sh` (regression check) — so a future
regression fails CI rather than drifting silently.

## Non-goals

- Adopting `ripsecrets` or fast-unit-test hooks in `lefthook.yml` — tracked
  under [#42](https://github.com/aidanns/agent-auth/issues/42).
- Adopting `ruff` for Python linting/formatting — tracked under
  [#47](https://github.com/aidanns/agent-auth/issues/47).
- Renaming `scripts/lint.sh` / `scripts/format.sh` or splitting them per
  language. This plan extends their scope but keeps the existing
  entrypoint names stable.
- Building a container image with pinned tool versions — out of scope.

## Deliverables

01. **`.mdformat.toml`** at repo root — `mdformat` configuration. Committed
    even if empty-by-defaults so the file's existence documents the
    decision and pins us to the config-file code path if defaults change.
02. **`taplo.toml`** at repo root — `taplo` configuration covering the
    formatter options the project has opinions on (column width, alignment,
    trailing newline).
03. **`treefmt.toml`** extended with `[formatter.mdformat]` and
    `[formatter.taplo]` entries matching `*.md` and `*.toml` respectively.
    `mdformat` is invoked with the GFM and tables plugins active (plugins
    auto-activate when installed into the same environment as `mdformat`).
04. **`scripts/format.sh`** extended to invoke `mdformat` and `taplo format`
    over every tracked `*.md` / `*.toml` file after the existing `shfmt`
    pass. `--check` mode runs each in diff/check mode and exits non-zero on
    drift.
05. **`scripts/lint.sh`** extended to run `keep-sorted --mode=lint` over
    every tracked file after the existing `shellcheck` pass. Exits
    non-zero if any annotated block is out of order.
06. **`lefthook.yml`** extended with three new `pre-commit` commands —
    `mdformat` on staged `*.md`, `taplo format --check` on staged `*.toml`,
    `keep-sorted --mode=lint` on staged files — following the existing
    shellcheck/shfmt invocation pattern (direct tool calls with
    `{staged_files}` substitution).
07. **`.github/workflows/check.yml`** extended with install steps for
    `mdformat` (pip, with the `mdformat-gfm` and `mdformat-tables`
    plugins), `taplo` (GitHub release binary), and `keep-sorted` (GitHub
    release binary). The job still runs `task check`, which now covers
    the three new tools transitively via the extended `lint.sh` /
    `format.sh`.
08. **`scripts/verify-dependencies.sh`** extended to require
    `keep-sorted`, `mdformat`, and `taplo` on `PATH`. These additions go
    inside the existing `keep-sorted` start/end block so the list stays
    sorted deterministically.
09. **`scripts/verify-standards.sh`** extended with two new assertions:
    - `treefmt.toml` contains a `[formatter.mdformat]` section AND a
      `[formatter.taplo]` section (same `grep` strategy used today for
      `[formatter.shellcheck]` / `[formatter.shfmt]`).
    - `keep-sorted` is referenced in `lefthook.yml` pre-commit OR at
      least one `.github/workflows/*.yml` file (matching the issue's
      acceptance wording "either in `lefthook.yml` pre-commit or a CI
      workflow").
10. **Sorted-block annotations** — add `keep-sorted` start/end markers
    around sortable blocks that do not yet have them:
    - `pyproject.toml` — `[project]` `dependencies`, `[project.optional-dependencies]`
      `dev`, and `[project.scripts]` keys.
    - `.gitignore` — pattern list.
    - `Taskfile.yml` — top-level tasks if they are alphabetically sorted.
      (If the current order is deliberate non-alphabetical, annotate
      `keep-sorted skip` or leave unannotated; decide at implementation
      time based on current ordering.)
11. **Existing Markdown and TOML normalised** — run `mdformat` and
    `taplo format` over every tracked `*.md` / `*.toml` file and commit the
    resulting diff so the first post-adoption CI run is clean.
12. **`CONTRIBUTING.md`** — document how to install `mdformat`, `taplo`,
    and `keep-sorted` locally (pip for mdformat+plugins, binary releases
    for taplo/keep-sorted with Homebrew fallback where available) and
    how they participate in `task lint` / `task format` / pre-commit.
13. **`README.md`** — no substantive change expected; verify links and
    fenced code blocks still render after `mdformat` normalises the file.

## Design and verification

The following plan-template steps are **not applicable** and are
intentionally skipped (same rationale as
`plans/shellcheck-shfmt-ci.md`):

- *Verify implementation against design doc* — Markdown/TOML
  formatting and sorted-block annotations are developer tooling, not a
  behavioural component of `agent-auth`, `things-bridge`, or the CLI
  clients. They do not appear in `design/DESIGN.md`,
  `design/functional_decomposition.yaml`, or
  `design/product_breakdown.yaml`, and do not need to.
- *Threat model / cybersecurity standard compliance* — no change to
  any running service's attack surface, keys, or data flow. These
  tools run at developer-time and CI-time only.
- *QM / SIL compliance* — no change to the production code path or its
  evidence requirements.
- *ADRs* — `mdformat`, `taplo`, and `keep-sorted` are the tools
  pre-chosen by `.claude/instructions/tooling-and-ci.md` for their
  respective slots. Adopting a pre-specified standard tool is not a
  novel design decision worth an ADR.

## Implementation steps

01. **Commit `.mdformat.toml` and `taplo.toml` configs.** `.mdformat.toml`
    pins `wrap`, `number`, and `end_of_line` to the project's preferred
    values. `taplo.toml` pins `column_width`, `indent_string`, and
    `align_entries`.
02. **Extend `treefmt.toml`** with `[formatter.mdformat]` (command
    `mdformat`, `includes = ["*.md"]`) and `[formatter.taplo]` (command
    `taplo`, options `["format"]`, `includes = ["*.toml"]`). Update the
    existing header comment to explain that md/toml go through treefmt
    while bash still has its authoritative gate in
    `scripts/lint.sh` / `scripts/format.sh`.
03. **Extend `scripts/format.sh`** — after the existing `shfmt` pass,
    discover tracked `*.md` and `*.toml` files via `git ls-files`, then
    invoke `mdformat` and `taplo format`. In `--check` mode, invoke both in
    diff/check mode. Guard each tool with a `command -v` preflight and a
    clear install hint (same pattern as today's `shfmt` guard). Update
    the header comment to reflect the expanded scope.
04. **Extend `scripts/lint.sh`** — after the existing `shellcheck` pass,
    discover tracked files and invoke `keep-sorted --mode=lint`. Guard
    with a `command -v` preflight. Update the header comment.
05. **Extend `lefthook.yml`** — add `mdformat`, `taplo`, and
    `keep-sorted` pre-commit commands following the shellcheck/shfmt
    pattern (glob + `run: <tool> {staged_files}`). Put the three new
    entries after the existing two so diffs stay minimal.
06. **Extend `.github/workflows/check.yml`** — add three install steps
    (pip for `mdformat` + `mdformat-gfm` + `mdformat-tables`; curl for
    `taplo` release binary; curl or `go install` for `keep-sorted`
    release binary) before the existing `Verify Required Tooling` step.
    Pin versions via `env:` vars following the `SHELLCHECK_VERSION` /
    `SHFMT_VERSION` pattern. The existing `task check` invocation picks
    the new tools up without further workflow changes.
07. **Extend `scripts/verify-dependencies.sh`** — add `keep-sorted`,
    `mdformat`, and `taplo` to the `REQUIRED_TOOLS` array, keeping the
    list alphabetical inside the `keep-sorted` start/end markers.
08. **Extend `scripts/verify-standards.sh`** — add a new section that:
    a. `grep`s `treefmt.toml` (comment-stripped, matching the existing
    shellcheck/shfmt check) for `^\[formatter\.mdformat\]` and
    `^\[formatter\.taplo\]`;
    b. `grep`s `lefthook.yml` (pre-commit section) OR
    `.github/workflows/*.yml` (comment-stripped) for `keep-sorted`;
    fails if neither matches.
    Print a single "verify-standards: mdformat + taplo + keep-sorted
    wiring OK" line on success.
09. **Annotate sortable blocks** — add `keep-sorted` start/end around
    `pyproject.toml` `dependencies`, `[project.optional-dependencies]`
    `dev`, `[project.scripts]`, `.gitignore`, and `Taskfile.yml` task
    list (if it is alphabetical today). Pre-existing annotations in
    `scripts/verify-dependencies.sh` and `scripts/verify-standards.sh`
    stay untouched.
10. **Normalise existing Markdown / TOML** — run
    `scripts/format.sh` (which now covers md + toml) and commit the
    resulting diff in a single commit labelled `style:`.
11. **Update `CONTRIBUTING.md`** — extend the *Dev setup* section with
    install instructions for the three tools (Homebrew on macOS where
    available, pip / GitHub releases elsewhere). Extend the *Running
    tasks* table to mention that `task lint` now covers `keep-sorted`
    and `task format` covers `mdformat` + `taplo`.

## Deterministic regression check

Per the issue's acceptance:

- `scripts/verify-standards.sh` asserts `[formatter.mdformat]` and
  `[formatter.taplo]` appear in `treefmt.toml`.
- `scripts/verify-standards.sh` asserts a `keep-sorted` hook is
  configured in either `lefthook.yml` pre-commit or at least one file
  under `.github/workflows/*.yml`.

A future regression that removes any of these wirings fails
`task verify-standards` immediately.

## Post-implementation standards review

Per CLAUDE.md → *Post-Change Review*:

- [ ] Run `/simplify` on the changes.
- [ ] Spawn an independent code-review subagent; address findings.
- [ ] Spawn a single subagent that walks through every file in
  `.claude/instructions/` against the diff and reports violations;
  address findings.

Specific checks expected against each instruction file:

- **`coding-standards.md`** — script arguments keep verb names
  (`--check`), tool invocations use explicit subcommands (`taplo format`,
  not `taplo f`).
- **`bash.md`** — every modified `*.sh` still passes `shellcheck` and
  `shfmt` (by construction, since CI gates on it).
- **`service-design.md`** — not applicable (no service changes).
- **`testing-standards.md`** — no behavioural code changes, so no new
  unit tests. The deterministic regression check *is* the test.
- **`tooling-and-ci.md`** — `mdformat`, `taplo`, and `keep-sorted` are
  now wired into `treefmt`, `lefthook`, and CI per the standard's
  requirements.
- **`release-and-hygiene.md`** — no changes to required project files.
- **`python.md`** — no Python-code changes (`mdformat` is Python-backed
  but installed as a developer tool, not a project dependency).
- **`design.md`** — no design-doc changes; decision captured in this
  plan file.
