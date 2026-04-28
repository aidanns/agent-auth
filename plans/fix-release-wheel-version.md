<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Fix release wheel versions reading `0.0.0+unknown` (issue #408)

## Symptom

`v0.16.0`'s 70 supply-chain assets all carry `0.0.0+unknown` filenames
(e.g. `agent_auth-0.0.0+unknown-py3-none-any.whl`) instead of `0.16.0`.
The `cosign verify` recipe in `SECURITY.md` § Supply-chain artifacts
expects `${PKG}-${VERSION}-py3-none-any.whl`, so consumers cannot
match the artefacts attached to the release.

## Root cause

Each `packages/<svc>/pyproject.toml` declares
`build-backend = "setuptools.build_meta"` with a `[tool.setuptools_scm]`
block but does not set `root`. `setuptools-scm`'s default behaviour is
to treat the `pyproject.toml`'s parent directory as the SCM root.
With `uv build --all-packages` the build runs from
`packages/<svc>/` — which is **not** a git root — so setuptools-scm
falls through to `fallback_version = "0.0.0+unknown"`. Reproduced
locally with `uv build --all-packages`; setuptools-scm itself emits
the explicit "Set the root explicitly in your configuration" hint.

## Fix

Add `root = "../.."` to every `packages/<svc>/pyproject.toml`'s
`[tool.setuptools_scm]` block. The path is relative to the
pyproject.toml that contains the config; `../..` resolves to the
workspace root, which is the git root the publish workflow checks out
with `fetch-depth: 0`. Reproduced locally that this yields
`0.16.1.devN+g<sha>` on a non-tag commit and `0.16.1` on the tag.

## Regression check

Add `tests/test_release_wheel_version.py` (workspace-root cross-cutting
test) with two cases:

- A static assertion that every `packages/<svc>/pyproject.toml`'s
  `[tool.setuptools_scm].root` is exactly `"../.."`. New packages
  added without the right `root` fail here without paying for a full
  `uv build`.
- A smoke test that runs `scripts/build-release-artifacts.sh` and
  asserts every produced wheel + sdist shares one non-fallback
  version segment (i.e. doesn't contain `0.0.0+unknown`).

Also add a workflow-level guard in `release-publish.yml` between the
`uv build` step and `cosign sign` that fails fast if any artefact
filename does not contain the release-tag's version. This is the
belt-and-braces gate the v0.16.0 ship lacked.

## Out of scope

- Backfilling `v0.16.0`'s assets — already noted in `SECURITY.md`
  § Supply-chain artifacts.
- The `v0.11.0..v0.15.3` missing-assets gap (#372).
- Changing the `fallback_version` placeholder — keeping it preserves
  the build's behaviour when run from a tarball without git history.

## Post-implementation review

- Coding standards: configuration-only change (`root = "../.."`) plus a
  pytest-style regression test; nothing to apply.
- Service design: no service surface affected.
- Release & hygiene: this PR ships a hand-authored
  `changelog/@unreleased/pr-<N>-fix-wheel-version.yml` entry with
  `type: fix` (PATCH bump).
- Testing standards: the new test exercises the public release-build
  contract (filenames on disk after `uv build`), not internal
  setuptools-scm internals. Skipped when `git` is missing.
- Tooling and CI: no workflow additions; the test rides the existing
  `task test` runner.
