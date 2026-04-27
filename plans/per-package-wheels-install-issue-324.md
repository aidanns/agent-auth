<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Per-package wheels and venv-based install (issue #324)

## Problem

1. `release-publish.yml` runs `uv build` from the repo root. Since the
   workspace split (ADR 0032), the root `pyproject.toml` is a
   workspace shell (`agent-auth-workspace`, version `0.0.0`) and
   setuptools rejects it with a flat-layout multiple-packages error.
   Every release since the split has produced **zero** assets (no
   wheels, no SBOMs, no signatures, no SLSA provenance) — confirmed
   via `gh release view v0.13.0 --json assets`. The supply-chain
   posture in `SECURITY.md` § *Supply-chain artifacts* has nothing to
   verify against.
2. Each `packages/<svc>/install.sh` requires `uv` as an end-user
   prereq (`uv tool install git+...#subdirectory=...`). uv is
   uncommon as a prereq for *installing* a Python CLI, blocks a
   future Homebrew formula in `aidanns/homebrew-tools` from following
   the standard `Language::Python::Virtualenv` pattern, and only
   "works" today because `uv tool install` clones the repo and builds
   from source — masking the broken release-asset pipeline.

## Decision summary (drives detail in the relevant sections below)

- **ADR shape.** Add a new ADR (0044) covering the per-package
  distribution model. ADR 0016 documents the *signing/SBOM/SLSA
  policy*; the per-package wheel layout is a distinct distribution
  decision and the way it interacts with workspace deps deserves its
  own page rather than a multi-page amendment to 0016. Cross-link
  both ways. ADR 0035's "single workspace train" stays unchanged —
  every wheel in a release tag still carries the same version.
- **Workspace-dep resolution in `install.sh`.** Hard-code the per-
  service workspace-dep list. Every service's runtime workspace
  closure today is `[agent-auth-common]` (verified across all six
  service `pyproject.toml` files). The list is short, fully audited
  by ADR 0036's workspace-dep-graph allowlist, and parsing
  `pyproject.toml` from a stdlib-only `install.sh` would force a
  `tomllib` dependency that doesn't buy us anything until the
  closure grows past one. The hard-coded list lives at the top of
  each `install.sh` with a comment pointing at ADR 0036 and the
  audit script (`scripts/verify-workspace-dep-graph.sh` if present;
  otherwise just a textual reminder).
- **CI integration-test job placement.** Add the job to `test.yml`
  rather than `release-publish.yml`. Rationale: adding a
  `pull_request` trigger to `release-publish.yml` would widen its
  trigger surface from "tag push only" to "any PR" while it still
  carries `id-token: write` + `contents: write`. That widening
  triggers the orchestrator's CodeQL command-injection rule and adds
  a real (if narrow) supply-chain blast surface — the workflow is on
  the release path, not the test path. `test.yml` already runs on
  every PR, has `contents: read` only, and is the natural home for a
  *test* of the install path. The build leg duplicates the
  `uv build --all-packages` call from `release-publish.yml`, but
  that's two lines of CI YAML and the duplication is the price of
  keeping the release workflow's trigger surface minimal.
- **Services covered by the integration test.** Two: `things-cli`
  (one workspace dep, exercises the dep-first install path with the
  smallest possible surface) and `gpg-bridge` (also one workspace
  dep but with a richer transitive PyPI dependency closure —
  `keyring`, `pyyaml` — which catches pip-resolver issues that a
  pure-stdlib service like `things-client-cli-applescript` would
  hide). Together they validate both the dep-first ordering and
  the third-party resolver path, and cover one CLI installer and
  one server installer, which is the two install-script shapes the
  workspace ships.
- **`--uninstall` flag.** Preserve. Every existing `install.sh`
  exposes it; the systems-engineering reference template also
  carries a clean uninstall path. Users have it muscle-memory and
  it costs nothing to keep.

## Plan

### 1. Verify build and install pattern locally (one service)

- [ ] Build all packages: `uv build --all-packages --out-dir     /tmp/aa-dist/` (verified during scoping — produces one wheel +
  one sdist per workspace member with PEP 625-normalised
  filenames).
- [ ] Generate `.sha256` files alongside each wheel.
- [ ] Hand-run an install simulation:
  - `python3 -m venv /tmp/aa-test-venv`
  - `/tmp/aa-test-venv/bin/pip install  /tmp/aa-dist/agent_auth_common-*.whl  /tmp/aa-dist/things_cli-*.whl`
  - `/tmp/aa-test-venv/bin/things-cli --version`
- [ ] Confirm `--version` resolves the right import-metadata version.

### 2. Write the new `install.sh` template (one service first)

Start with `things-cli` (smallest workspace surface). Cover:

- [ ] Drop `uv` prereq. Require `python3 ≥ 3.11` with importable
  `venv`. Probe `python3` then `python` to match the
  systems-engineering pattern.
- [ ] Argument parsing: positional `[VERSION]`, `--uninstall`,
  `--local <dir>` (mutually exclusive with positional version).
- [ ] Hard-coded `WORKSPACE_DEPS=(agent-auth-common)` array near
  the top with a comment pointing at ADR 0036 and the audit
  script.
- [ ] Remote mode: resolve latest tag from
  `https://api.github.com/repos/aidanns/agent-auth/releases/latest`
  (or `releases/tags/<tag>`). Match assets by name (PEP 625
  normalised: dist-name `things-cli` -> wheel prefix
  `things_cli-`).
- [ ] For each wheel (workspace deps + service): download `.whl`
  and `.whl.sha256`. Verify with `sha256sum -c` (Linux) or
  `shasum -a 256 -c` (macOS).
- [ ] Local mode: pull every wheel matching the service or
  workspace-dep prefix from the `--local <dir>`, plus its
  sibling `.sha256`.
- [ ] Install: `python3 -m venv --clear ~/.local/share/<svc>/venv`,
  then `pip install --no-cache-dir --quiet     <workspace-dep-wheels...> <service-wheel>` in **dep-first**
  order. (Actually, with both wheels passed in one command
  pip's resolver sees both, so order is cosmetic — but keep
  dep-first explicit so a reader doesn't wonder.)
- [ ] Symlink each entrypoint script from
  `<venv>/bin/<entry>` into `~/.local/bin/<entry>`. Multiple
  entrypoints (e.g. `agent-auth` ships `agent-auth` +
  `agent-auth-notifier`) get a list-driven loop.
- [ ] Verification: `<bin> --version` (issue #318 / PR #341 has
  already shipped). Failure => non-zero exit.
- [ ] PATH warning when `~/.local/bin` is not on PATH.
- [ ] `--uninstall`: remove every symlink we created + `rm -rf`
  the venv + `rmdir` the install dir if empty.

### 3. Apply the template to every service

Replicate the template across:

- `packages/agent-auth/install.sh` — entrypoints
  `[agent-auth, agent-auth-notifier]`
- `packages/gpg-bridge/install.sh` — entrypoint `[gpg-bridge]`
- `packages/gpg-cli/install.sh` — entrypoint `[gpg-cli]`
- `packages/things-bridge/install.sh` — entrypoint `[things-bridge]`
- `packages/things-cli/install.sh` — entrypoint `[things-cli]`
- `packages/things-client-cli-applescript/install.sh` — entrypoint
  `[things-client-cli-applescript]`

Every script keeps its existing SPDX header and module-level
docstring (the latter rewritten to reflect the venv-based install).

### 4. Rewrite `release-publish.yml`

- [ ] Replace the single `uv build` step with `uv build     --all-packages --out-dir dist/`.
- [ ] Replace the single sdist/wheel artefact resolution with a loop
  that enumerates `dist/*.whl` + `dist/*.tar.gz`.
- [ ] Generate `.sha256` for every wheel + sdist into `dist/`.
- [ ] Fan out the SBOM + cosign signing steps over every
  `dist/*.whl` and `dist/*.tar.gz`. Each artefact gets:
  - `<artefact>.spdx.json` (Syft SBOM)
  - `<artefact>.sig.bundle` (cosign sig of the artefact)
  - `<artefact>.spdx.json.sig.bundle` (cosign sig of the SBOM)
- [ ] Update the SLSA `hashes` output to enumerate every wheel +
  sdist subject (the SLSA generic generator accepts multiple
  subjects in the same `base64-subjects` blob — `sha256sum`
  multiple files in the same call already produces the right
  shape).
- [ ] Update the `gh release upload` step to upload every per-
  artefact asset + every `.sha256`.
- [ ] Add a `pull_request` trigger that runs only the build leg +
  a new `integration-test` job (no signing/upload). Use a job-
  level `if:` to gate the upload steps to tag-push events only.

### 5. Add the CI integration-test job

In `release-publish.yml`, gated on the new `pull_request` trigger
plus tag pushes (defence in depth):

- [ ] Use `actions/setup-python@v5` with Python 3.11 (NOT uv —
  proves the install path doesn't need uv on PATH).
- [ ] Install uv only for the build step (separate step, separate
  shell), build all wheels into `dist/`, generate `.sha256`s.
- [ ] In a matrix over `[things-cli, gpg-bridge]`, run
  `packages/<svc>/install.sh --local dist/`.
- [ ] Assert: each entrypoint binary exists at `~/.local/bin/`,
  `<bin> --version` exits zero, `<venv>/bin/pip list` includes
  both the service and `agent-auth-common`.
- [ ] `unset` any uv-related env (`UV_*`) before invoking
  `install.sh` so a stray inherit from the build step can't
  mask a uv-dependency regression.

### 6. Update `SECURITY.md` § Supply-chain artifacts

- [ ] Replace the "sdist + wheel + their SBOMs + their cosign
  bundles" description with the per-package layout (one set per
  workspace member).
- [ ] Update the verification recipe to enumerate every wheel +
  sdist (likely as a `for` loop over the seven dist names).
- [ ] Note that the SLSA provenance subjects span every wheel +
  sdist in the release.

### 7. Add ADR 0044 — Per-package release-asset layout

- [ ] Title: "Per-package wheels as release assets, workspace deps
  shipped alongside".
- [ ] Status: Accepted — 2026-04-26.
- [ ] Context: workspace split + broken `uv build` at root + Homebrew-
  friendly install pattern. Reference ADR 0016 (signing/SBOM/
  SLSA), ADR 0032 (workspace split), ADR 0035 (single workspace
  train), ADR 0036 (workspace-dep allowlist).
- [ ] Considered alternatives: PyPI publish of `agent-auth-common`
  (rejected — ADR 0035 defers PyPI), fat wheel that vendors
  workspace deps (rejected — bespoke build, not Homebrew-
  idiomatic).
- [ ] Decision: `uv build --all-packages` produces one wheel + one
  sdist per workspace member, all uploaded as release assets.
  `install.sh` downloads the service wheel + every workspace-dep
  wheel listed in a hard-coded array, verifies sha256, installs
  together into a stdlib `venv`. Workspace-dep list is hard-coded
  and audit-checked against ADR 0036's allowlist.
- [ ] Consequences: install path no longer needs uv; release pipeline
  now produces a complete asset set per package; SLSA provenance
  subject list grows to N×2 (wheel + sdist per package); future
  Homebrew formula can use `Language::Python::Virtualenv` against
  the same assets.

### 8. Update README.md installation section

- [ ] Drop the "Requires uv" sentence above the per-service install
  list. Replace with "Requires Python 3.11+ (with the stdlib
  `venv` module)".
- [ ] Don't change the `curl | bash` URLs — they're stable.

### 9. Self-review checklist (apply BEFORE pushing)

- [ ] `git diff main...HEAD` for missing asset uploads.
- [ ] SLSA hashes enumerate every subject (wheel + sdist per package
  = 14 subjects).
- [ ] `unset UV_*; install.sh --local dist/` works in a clean shell.
- [ ] Workspace deps passed before service wheel.
- [ ] `--uninstall` works after rewrite (remove symlink, rm -rf
  venv).
- [ ] macOS/Linux divergence: `sha256sum` vs `shasum -a 256 -c`.
- [ ] Hand-author `changelog/@unreleased/pr-<N>-...yml` with
  `feature:` type.

## Out of scope (per issue body)

- Homebrew formula (follow-up issue once this lands).
- PyPI publishing (ADR 0035 defers).
- Per-package versioning (ADR 0035 keeps the workspace train).
- Removing the broken `uv tool install git+...` install path as a
  fallback.

## Standards review (post-implementation, per `plan-template.md`)

- **`coding-standards.md`** — install.sh follows the project's bash
  conventions (set -euo pipefail, single blank lines around
  description comment).
- **`service-design.md`** — install paths conform to XDG-style
  conventions (`~/.local/share/<svc>/`).
- **`release-and-hygiene.md`** — per-service `install.sh` retained;
  no top-level meta-installer reintroduced.
- **`testing-standards.md`** — integration test exercises the public
  install surface end-to-end, asserts on observable state (binary
  presence, `--version` exit, pip list contents).
- **`tooling-and-ci.md`** — every release-affecting Action stays SHA-
  pinned; new `actions/setup-python` reference uses a SHA pin.
- **`design.md`** — new ADR added under `design/decisions/`.
