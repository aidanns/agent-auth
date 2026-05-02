<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# pr-lint-validator

Standalone, releasable PR-title and `==COMMIT_MSG==` block validators
extracted from `scripts/validate-*.py` (issue #446).

## Scope

The package provides the prose-style rule logic that
`.github/workflows/pr-lint.yml` runs on every PR — the rules that
sit alongside `amannn/action-semantic-pull-request`'s
prefix-allowlist check. Two subcommands:

- **`title`** — checks the PR title (and therefore the squash-merge
  commit subject) against the rules documented in CONTRIBUTING.md
  → "Writing release-worthy commits" → "Subject (PR title)":
  72-char hard cap (with merge-bot suffix awareness), no trailing
  period, imperative mood (closed-list past-tense rejection),
  type x scope matrix, and the two-tier package / area scope
  allowlist.

- **`commit-msg`** — checks the `==COMMIT_MSG==` block in a PR
  body against the conventions in CONTRIBUTING.md § "Writing PRs"
  and ADR 0037: exactly one block, 72-char body line cap (trailers
  exempt), no markdown headings / task checkboxes / image embeds,
  contiguous trailer block with a blank-line separator before it,
  at least one `Signed-off-by:` trailer (DCO), and a soft warning
  on unusually verbose bodies.

The Palantir-style prefix allowlist itself
(`feature` / `improvement` / `fix` / `chore` / `deprecation` /
`migration` / `break`) is enforced upstream by
`amannn/action-semantic-pull-request` — that check is not part of
this package.

A future `release-impact` subcommand is reserved for when the
changelog tooling under `scripts/changelog/` is ready to be packaged
alongside; see the issue's "Out of scope" section.

## Installation

The package ships as a per-package wheel + sdist on every release of
[`aidanns/agent-auth`](https://github.com/aidanns/agent-auth/releases).
Both the wheel and the sdist carry a `.sha256` sidecar for tamper-
evident verification, plus a cosign bundle and an SPDX SBOM (the
release-bot fans the per-artefact signing / SBOM chain across every
workspace member).

### Pin to a tag and download

```bash
TAG=v0.16.6  # pick a tag from https://github.com/aidanns/agent-auth/releases
gh release download "${TAG}" --repo aidanns/agent-auth \
  --pattern 'pr_lint_validator-*-py3-none-any.whl' \
  --pattern 'pr_lint_validator-*-py3-none-any.whl.sha256'
sha256sum -c pr_lint_validator-*-py3-none-any.whl.sha256
pip install --user pr_lint_validator-*-py3-none-any.whl
```

The wheel is `py3-none-any` (pure-stdlib Python ≥ 3.11), so a single
asset works on every runner. Cosign bundle + SPDX SBOM verification
follow the project's standard recipe (see
[`SECURITY.md` § "Supply-chain artifacts"](../../SECURITY.md)).

### Inside the agent-auth workspace

```bash
task pr-lint-validator -- title --self-test
task pr-lint-validator -- commit-msg --self-test
```

`task pr-lint-validator -- <args>` forwards to `uv run pr-lint-validator`
inside the workspace virtualenv.

## Usage

### Validate a PR title

```bash
pr-lint-validator title \
  --title 'feature(agent-auth): add JIT approval flow' \
  --pr-number 123 \
  --changed-files-from changed-files.txt
```

`changed-files.txt` is a newline-separated list of paths produced by
`gh pr view --json files --jq '.files[].path'`. When provided, the
two-tier scope rule (#402) runs: a PR contained to a single
`packages/<name>/` directory must use `(<name>)` as the scope; a PR
that spans multiple packages or sits outside `packages/` falls
through to the area-tier `AREA_SCOPES` allowlist.

`--pr-number` is optional; when present the 72-char length cap is
applied to the *projected* squash-merge subject (the un-suffixed
title plus the ` (#<n>)` suffix `merge-bot.yml` appends), not just
the bare title. See #399.

`--repo-root` overrides the directory used for workspace package
discovery — defaults to the current working directory, which is what
GitHub Actions provides.

### Validate a `==COMMIT_MSG==` block

```bash
pr-lint-validator commit-msg \
  pr-body.md \
  --title 'feature(agent-auth): add JIT approval flow'
```

The body file is the PR's full markdown. The `--title` flag is
optional; passing it enables the "first body line duplicates the PR
title" check, which is the rule with title context.

### Self-test mode

Both subcommands accept `--self-test` to exercise the bundled
fixtures and exit non-zero on any regression:

```bash
pr-lint-validator title --self-test
pr-lint-validator commit-msg --self-test
```

This is what the consumer's CI should run on every PR after a
release-bot tag bump, to catch a validator regression before the
artifact is consumed in earnest.

## Versioning

The package follows the workspace-wide release tag train (ADR 0035
/ ADR 0044). Each `vX.Y.Z` tag publishes a matching
`pr_lint_validator-X.Y.Z-py3-none-any.whl` asset. Pin by tag in
downstream CI; the validator's exit-code contract and CLI flag
surface are kept stable across patch releases (the underlying rule
set may grow as new conventions land in CONTRIBUTING.md, but a
tightening that fails a previously-passing fixture is a `break:` PR
and surfaces as a major bump).

## License

MIT — see [`LICENSE.md`](../../LICENSE.md).

## Author

Aidan Nagorcka-Smith — <aidanns@gmail.com>
