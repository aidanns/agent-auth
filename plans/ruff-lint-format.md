# Plan: Configure ruff lint + format and gate in CI

Issue: [#47](https://github.com/aidanns/agent-auth/issues/47).

Source standard: `.claude/instructions/python.md` — *ruff* for Python
linting and formatting.

## Goal

Adopt `ruff` as the single tool for Python lint (`ruff check`) and
format (`ruff format`), covering every tracked `*.py` file under `src/`
and `tests/`. Wire it through the project's canonical entrypoints:
`pyproject.toml` (rule configuration), `scripts/lint.sh` /
`scripts/format.sh` (developer + CI invocation), `treefmt.toml` (formatter
multiplexer), `lefthook.yml` (pre-commit gate), and the existing
`.github/workflows/check.yml` (CI gate). Apply `ruff format` across the
tree so the baseline is clean and CI is green on merge.

## Non-goals

- **Type checking** (`mypy` / `pyright`) — tracked separately; ruff only
  covers lint + format.
- **Dependency vulnerability scanning** (`pip-audit`) — separate concern
  under `python.md`.
- **Mdformat / taplo** — other formatter integrations tracked under
  [#45](https://github.com/aidanns/agent-auth/issues/45).
- **Adding ruff to `lefthook.yml` beyond lint/format** — no test subset
  or secret scanning changes here.
- **Rewriting existing code for stricter rulesets** — rule set is the
  baseline mandated by the issue (E, F, I, UP, B, SIM, RUF); any
  remaining findings after `ruff format` are fixed narrowly (either
  auto-fix or per-violation) without broader refactoring.

## Deliverables

01. **`pyproject.toml`**
    - `ruff` added to the `dev` optional-dependencies group so it lands
      in the per-OS/arch venv via `scripts/_bootstrap_venv.sh`.
    - `[tool.ruff]` config block with `src = ["src", "tests"]`, a
      `target-version` pinned to the project's Python floor (3.11), and
      `line-length = 100` (a mild relaxation of ruff's 88 default that
      avoids forcing awkward wraps on the descriptive error messages
      and SQL strings already common in this codebase).
    - `[tool.ruff.lint]` selecting rule families `E`, `F`, `I`, `UP`,
      `B`, `SIM`, `RUF`. No custom ignores on day one unless a specific
      rule collides with project style (document with a short comment
      if so).
    - `[tool.ruff.format]` left at defaults (double-quote, space indent)
      — matches the existing codebase after `ruff format`.
02. **`scripts/lint.sh`** — extend the existing shellcheck-only script
    to also invoke `ruff check` against every tracked `*.py` file. Uses
    the venv ruff (`${VENV_DIR}/bin/ruff`) via the shared
    `_bootstrap_venv.sh` helper. Exits non-zero on any finding.
03. **`scripts/format.sh`** — extend to run `ruff format` (write mode)
    and `ruff format --check` (`--check` mode) against every tracked
    `*.py` file, in addition to the existing shfmt invocation.
04. **`treefmt.toml`** — add a `[formatter.ruff]` entry that invokes
    `ruff format` over `*.py`. Keep shellcheck/shfmt entries as-is.
05. **`lefthook.yml`** — add two `pre-commit` commands:
    - `ruff-check` running `ruff check {staged_files}` against staged
      `*.py` files.
    - `ruff-format` running `ruff format --check {staged_files}` against
      staged `*.py` files.
06. **`.github/workflows/check.yml`** — the unified "Check" workflow
    already runs `task check`, which will now invoke ruff via the updated
    scripts. The workflow only needs the venv to exist so ruff is
    available — `task check` already sources `_bootstrap_venv.sh` through
    the lint/format scripts; no new install step is required beyond the
    existing `actions/setup-python` step. Verify the job still goes green.
07. **`scripts/verify-dependencies.sh`** — no change: `ruff` is a venv-
    scoped Python tool, not an external CLI that belongs alongside
    `shellcheck` / `shfmt`. The venv bootstrap is the install channel.
08. **`scripts/verify-standards.sh`** — extend with a new deterministic
    check that asserts:
    - `pyproject.toml` contains a `[tool.ruff]` configuration section.
    - `treefmt.toml` declares a `[formatter.ruff]` entry.
    - At least one `.github/workflows/*.yml` file causes `ruff check`
      and `ruff format --check` to run (directly or via `task check`).
09. **Source tree reformatted** — `ruff format` applied across `src/`
    and `tests/`; any remaining `ruff check` findings resolved via
    auto-fix (`ruff check --fix`) or narrow hand-edits where auto-fix
    is not applicable.
10. **`CONTRIBUTING.md`** — no new install step (ruff is a venv
    dependency). Verify the *Running tasks* table still reads correctly
    after the lint/format scope grows.

## Design and verification

The following plan-template steps are **not applicable** and are
intentionally skipped:

- *Verify implementation against design doc* — Python linting and
  formatting is developer tooling, not a behavioural component of
  `agent-auth` or `things-bridge`. It does not appear in
  `design/DESIGN.md`, `functional_decomposition.yaml`, or
  `product_breakdown.yaml`, and does not need to.
- *Threat model / cybersecurity standard compliance* — no change to
  the running service's attack surface, keys, or data flow. Ruff
  runs at developer-time and CI-time only.
- *QM / SIL compliance* — no change to the production code path or
  its evidence requirements.
- *ADRs* — `ruff` is already mandated by `.claude/instructions/python.md`
  as the standard tool for this category. Adopting a pre-chosen
  standard tool is not a novel design decision.

## Implementation steps

01. **Add `ruff` to dev extras and configure in `pyproject.toml`** — add
    `ruff>=0.6` under `[project.optional-dependencies].dev`. Add
    `[tool.ruff]`, `[tool.ruff.lint]`, and `[tool.ruff.format]` blocks
    per the Deliverables section. Bumping `pyproject.toml` invalidates
    the venv hash marker so `_bootstrap_venv.sh` reinstalls on next run.

02. **Rebuild the venv and run `ruff format` + `ruff check --fix`** —
    after the new config lands, run both against `src/` and `tests/`.
    Inspect the diff for any behavioural changes (`ruff check --fix`
    can rewrite expressions under `SIM`, `UP`, `B`) and confirm the
    test suite still passes afterwards.

03. **Address residual `ruff check` findings** — anything not auto-fixed
    is resolved by hand. Prefer fixing the code over adding file-local
    `# noqa` comments; add rule-scoped `noqa` only when the rule
    genuinely disagrees with intended behaviour.

04. **`scripts/lint.sh`** — keep the shellcheck flow. Add a parallel
    block that collects tracked `*.py` files via `git ls-files '*.py'`,
    sources `_bootstrap_venv.sh`, then runs
    `"${VENV_DIR}/bin/ruff" check` on the batch. Guard for no-op
    (empty file set) the same way the existing code does.

05. **`scripts/format.sh`** — mirror `lint.sh`. Add a block that runs
    `ruff format` (write) or `ruff format --check` (check mode), matching
    the existing `mode` switch. Sources `_bootstrap_venv.sh`.

06. **`treefmt.toml`** — add:

    ```toml
    [formatter.ruff]
    command = "ruff"
    options = ["format"]
    includes = ["*.py"]
    ```

    Treefmt invokes `ruff` from PATH; since developers running `treefmt`
    directly usually also have the venv activated or ruff on PATH, this
    matches how `shellcheck`/`shfmt` are already wired. Document the
    venv install path for ruff in the same comment block.

07. **`lefthook.yml`** — add two pre-commit commands (`ruff-check` and
    `ruff-format`) restricted to `*.py` via `glob`, running against
    `{staged_files}`. Use the venv-local `ruff` when present (via
    relative path or PATH lookup — the existing `shellcheck`/`shfmt`
    pattern uses bare names; keep ruff consistent).

08. **CI workflow** — `check.yml` already runs `task check`. Because
    `scripts/lint.sh` and `scripts/format.sh` now source
    `_bootstrap_venv.sh`, the CI job must have Python available (it does
    via `actions/setup-python@v6`). No new step is strictly required.
    Re-run CI locally via `act` (if available) or trust the PR to exercise
    the gate.

09. **`scripts/verify-standards.sh`** — extend the bash gating block with
    an equivalent ruff gating block:

    - Assert `pyproject.toml` contains a `[tool.ruff]` header (via
      stripped grep, matching the shellcheck/shfmt pattern).
    - Assert `treefmt.toml` contains `[formatter.ruff]`.
    - Assert at least one `.github/workflows/*.yml` file references
      `task check` OR `ruff check` + `ruff format --check` directly.
      (The easy/robust match: `task check` — since that's the single
      command that dispatches to the updated scripts.)

10. **Docs** — spot-check `CONTRIBUTING.md` and `README.md` for any
    stale references to lint/format scope; update if the descriptions
    narrowly say "bash-only".

## Deterministic regression check

Per the issue: `scripts/verify-standards.sh` asserts that ruff is
configured in `pyproject.toml`, wired into `treefmt.toml`, and gated
in CI. Concrete checks:

- `grep -qE '^\[tool\.ruff'` over comment-stripped `pyproject.toml` →
  at least one match.
- `grep -qE '^\[formatter\.ruff\]'` over comment-stripped
  `treefmt.toml` → at least one match.
- `grep -qE '\btask check\b|\bruff check\b'` over comment-stripped
  `.github/workflows/*.yml` → at least one match (the `task check`
  dispatch is the canonical path and satisfies both the lint and
  format-check requirement transitively).

A future regression that removes any of these wirings fails `task verify-standards` immediately.

## Post-implementation standards review

Run each of the following against the diff (per CLAUDE.md → *Post-Change
Review*):

- [ ] `/simplify` on the changes.
- [ ] Independent code-review subagent; address findings.
- [ ] One subagent reviewing the diff sequentially against every file
  in `.claude/instructions/`; address findings.

Specifically verify:

- **`python.md`** — ruff is configured with the rule families the issue
  mandates; venv-scoped install matches the tooling-channel convention
  for Python dev tools.
- **`tooling-and-ci.md`** — `task lint`, `task format`, `task check`
  surfaces are unchanged in shape; CI still gates on `task check`.
- **`coding-standards.md`** — ruff-auto-formatted code still passes
  project naming / type conventions (auto-format does not alter
  identifiers).
- **`service-design.md`** — not applicable (no service changes).
- **`testing-standards.md`** — no behavioural code changes; tests still
  pass after `ruff format` and any `ruff check --fix` edits.
- **`release-and-hygiene.md`** — no changes to required project files.
- **`bash.md`** — bash gating is untouched; the additions run alongside.
- **`design.md`** — no ADR needed (adopting a pre-chosen standard tool).
- **`plan-template.md`** — this document fulfils the required sections.
