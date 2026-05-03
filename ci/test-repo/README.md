<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# `ci/test-repo/`

Whole-repo (cross-package) tests that don't belong to any single
workspace member's `packages/<svc>/tests/` tree.

## Scope

Tests here assert invariants over the **entire repository** — the
shape of `.github/` workflows + composite actions, project-wide
configuration files, repo-level conventions. They are not unit tests
of a service's source, and they have no `packages/<svc>/`
counterpart that could meaningfully own them.

The original root-level `tests/` tree is reserved for cross-service
checks that still depend on the workspace install surface
(release-semver, OpenAPI spec, scan-failure formatting). Tests that
are pure static checks over repo-shaped artefacts (workflow YAML,
composite action metadata, branch-protection contracts derived from
files in `.github/`) live here instead so the cross-package nature
is obvious from the path.

Each file in this directory is invoked from a dedicated CI job —
no umbrella runner walks the directory. The job that owns the test
lives next to the surface it guards (e.g. the
`pr-lint-yaml-loadable-self-test` job in
`.github/workflows/pr-lint.yml` runs
`test_pr_lint_action_yml_loadable.py`). This keeps the trigger
surface (which event fires which test) explicit per-test instead of
deferring to a global pytest collector.

## Adding a test

1. Drop a `test_<descriptive_name>.py` file in this directory.
2. Wire a CI job (typically a self-test job alongside the workflow
   under test) that installs `pyyaml` + `pytest` and invokes the
   file with `python3 -m pytest -o addopts= ci/test-repo/<file> -v`.
   Use `-o addopts=` to override the workspace `pyproject.toml`'s
   `[tool.pytest.ini_options].addopts` (which injects `--cov` and
   the integration-fixture plugin) — these tests run in isolated
   jobs without the workspace virtualenv.
3. Document the file's purpose in its top-level docstring; readers
   landing here from a CI failure should be able to understand the
   bug class without grepping issue history.

## Why a separate top-level location

`packages/<svc>/tests/` is for service unit tests. The root
`tests/` tree is for cross-service tests that depend on the
workspace install surface. Repo-shape invariants (workflow YAML,
composite-action metadata, branch-protection contracts) are a third
category — they have no service owner and don't need the workspace
venv to run. Putting them in `ci/test-repo/` makes that category
visible at the directory level and prevents drift back into either
of the other two homes when a future contributor adds a similar
test.
