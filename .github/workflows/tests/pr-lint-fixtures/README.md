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
