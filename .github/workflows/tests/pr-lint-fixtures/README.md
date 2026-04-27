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

## Title-aware and PR-title rules

A few rules need inputs the file-loop cannot supply (the PR title, or
a (body, title) pair for the subject-dup check). Those rules live in
inline self-test cases inside the validator scripts and run via
separate self-test jobs in `pr-lint.yml`:

- `python3 scripts/validate-pr-title.py --self-test` — title-only
  rules (`pr-title-self-test` job).
- `python3 scripts/validate-commit-msg-block.py --self-test` —
  body rules that need a paired title (`pr-body-title-aware-self-test`
  job).

When you add a new title-only or title-aware rule, extend the
corresponding `_SELF_TEST_CASES` / `_TITLE_AWARE_SELF_TEST_CASES`
tuple in the script. File-based fixtures stay reserved for body-only
rules.
