<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# pr-lint validator fixtures

Inputs for the `validator-self-test` job in
`.github/workflows/pr-lint.yml`. Each `valid-*.md` is a PR body that
must pass `scripts/validate-commit-msg-block.py`; each `invalid-*.md`
is a body that must fail it.

A new failure mode goes here as `invalid-<slug>.md` alongside the
extra check it exercises in the validator. The self-test job iterates
the directory and asserts the expected outcome, so adding a fixture
is enough to cover the new branch.

## Warning-only and PR-title rules

A few rules need inputs the file-loop cannot supply (the PR title;
or a warning count rather than raise/no-raise). Those rules live in
inline self-test cases inside the validator scripts and run via
separate self-test jobs in `pr-lint.yml`:

- `pr-lint-validator title --self-test` — title-only rules
  (`pr-title-self-test` job). The `pr-lint-validator` console
  script is on PATH inside the CI composite (see
  `.github/actions/install-pr-lint-validator/action.yml`); locally,
  run `uv run --package pr-lint-validator pr-lint-validator title --self-test`
  to exercise the workspace source.
- `python3 scripts/validate-commit-msg-block.py --self-test` —
  body rules whose outcome is a warning count (currently just the
  verbose-body rule, #395) — `pr-body-warning-self-test` job.

When you add a new title-only or warning-only rule, extend the
corresponding `_SELF_TEST_CASES` / `_VERBOSE_BODY_SELF_TEST_CASES`
tuple in the script. File-based fixtures stay reserved for body
rules whose outcome is raise/no-raise.
