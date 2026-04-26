<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

<!-- REUSE-IgnoreStart -->

# ADR 0043 — Per-package wheels as release assets, workspace deps shipped alongside

## Status

Accepted — 2026-04-26.

Builds on
[ADR 0016](0016-release-supply-chain.md) (signing / SBOM / SLSA
policy — extended in this ADR to fan out across every workspace
package),
[ADR 0032](0032-monorepo-workspace-split.md) (uv workspace split),
[ADR 0035](0035-workspace-release-model.md) (single workspace tag
train, no PyPI yet),
and
[ADR 0036](0036-workspace-dep-graph-allowlist.md) (workspace
dependency-graph allowlist that pins which workspace edges are
legal).
[#324](https://github.com/aidanns/agent-auth/issues/324) is the
tracking issue.

## Context

Two pressure points stacked up against the post-workspace-split
release pipeline:

1. **The release pipeline has been broken since the workspace split
   (ADR 0032).** `release-publish.yml` ran `uv build` from the repo
   root. The root `pyproject.toml` is a workspace shell
   (`agent-auth-workspace`, version `0.0.0`) and setuptools rejected
   it with the *Multiple top-level packages discovered in a
   flat-layout: ['plans', 'docker', 'design', 'LICENSES', 'packages']*
   error. Every release run since the split (`v0.13.0`, `v0.12.2`,
   `v0.12.1`, …) failed at the *Build sdist and wheel* step.
   `gh release view v0.13.0 --json assets` returns `{"assets":[]}` —
   no wheels, no SBOMs, no signatures, no SLSA provenance. The
   supply-chain story in
   `SECURITY.md` § *Supply-chain artifacts* had nothing to verify
   against. semantic-release still tagged + wrote CHANGELOG entries,
   so the release *appeared* to publish; nothing on the install path
   surfaced the breakage because the existing per-service
   `install.sh` scripts used `uv tool install git+...#subdirectory=packages/<svc>`, which clones the repo and
   builds from source rather than reading any release asset.

2. **The install scripts required `uv` as an end-user prereq.** Each
   `packages/<svc>/install.sh` rejected machines without `uv` on
   PATH. uv is mainstream for *development* but uncommon as a prereq
   for *installing* a Python CLI — pipx and "wheel into venv" (the
   `aidanns/systems-engineering` pattern) are the dominant paths,
   and Homebrew formulas (`Language::Python::Virtualenv`) always use
   stdlib `venv` + `pip`. Requiring uv blocks a future Homebrew
   formula in `aidanns/homebrew-tools` from following the standard
   pattern and adds a hard dependency on a fast-moving Astral tool
   to every install lane.

The complication for fixing both at once is the workspace-dep graph
that ADR 0036 pinned. Every service depends on `agent-auth-common`;
when `pip install <service>.whl` runs in an isolated venv, pip needs
to resolve `agent-auth-common` from somewhere. Three places it
*could* come from:

- the same release as the service wheel (this ADR);
- PyPI (rejected — ADR 0035 defers PyPI distribution explicitly,
  and committing to PyPI publishing for one library is a larger
  commitment than this issue); or
- vendored inside the service wheel (rejected — see *Considered
  alternatives*).

## Considered alternatives

### Publish `agent-auth-common` to PyPI

Bring `agent-auth-common` up to PyPI as the canonical resolution
source for the workspace dep, and let each service wheel pin a
`Requires-Dist: agent-auth-common>=X.Y` line that pip resolves from
PyPI at install time.

**Rejected** because:

- ADR 0035 explicitly defers PyPI distribution. A PyPI publish of
  `agent-auth-common` is itself one of ADR 0035's *revisit triggers*
  (the canonical "external consumer" event), so doing it here would
  pre-emptively flip a decision that has its own ADR pending.
- Once published to PyPI the namespace is permanent and a future
  rename / yank costs operator pain. Locking that in for one
  internal library to make the install path slightly cleaner is a
  bad trade.

### Fat wheel that vendors workspace deps

Build each service wheel as a "fat" wheel that re-exports
`agent_auth_common`'s modules from inside its own wheel layout.
Install path then needs only the service wheel.

**Rejected** because:

- Not idiomatic Python packaging. setuptools-scm + `Language::Python::Virtualenv`
  have no native support for vendored workspace deps; we'd have to
  write a bespoke build helper that copies sibling-package source
  into each service's wheel layout.
- Re-declares every transitive PyPI dep at every leaf (otherwise
  the vendored module imports something the service wheel didn't
  declare). That doubles the maintenance burden of the workspace
  dep graph.
- Homebrew's `Language::Python::Virtualenv` expects each Python
  dependency to be a separately resolvable distribution it can list
  as a `resource` block. Vendored workspace deps inside a single
  wheel don't fit that shape; a future Homebrew formula would have
  to either skip the helper and bring up its own venv (defeating
  the helper's purpose) or special-case our wheel layout.

### Keep the `uv tool install git+...` path forever

Drop the release-asset path entirely; rely on the `uv tool install git+...#subdirectory=packages/<svc>` path that the broken
`install.sh` scripts already used.

**Rejected** because:

- Requires `uv` on every consumer machine (the issue we're trying
  to remove).
- Builds from source on every install — slow, requires the build
  toolchain on the target, and unverifiable against any signed
  release asset.
- Releases stop carrying signed wheels, undoing the SLSA, cosign,
  and SBOM work in ADR 0016.

## Decision

Adopt a per-package release-asset model. Concrete decisions:

- **Build.** `release-publish.yml` calls
  `uv build --all-packages --out-dir dist/`, which iterates every
  workspace member declared under `[tool.uv.workspace].members` in
  the root `pyproject.toml` and emits one wheel + one sdist per
  member.
- **Per-artefact assets.** For every wheel and sdist, the workflow
  emits a sha256 sidecar (`.sha256`), an SPDX SBOM
  (`.spdx.json`), and two cosign keyless signature bundles
  (`.sig.bundle` for the artefact, `.spdx.json.sig.bundle` for the
  SBOM). The asset set per package is therefore the cross product
  of {wheel, sdist} × {raw, .sha256, .spdx.json,
  .sig.bundle, .spdx.json.sig.bundle}.
- **SLSA provenance.** The SLSA generator's
  `base64-subjects` enumerates every wheel + sdist in the release.
  The `multiple.intoto.jsonl` attestation continues to bind every
  subject to the exact `release-publish.yml` workflow run.
- **Install path.** `packages/<svc>/install.sh` no longer requires
  `uv`. It requires Python 3.11+ with the stdlib `venv` module on
  PATH. It downloads the service's wheel + every workspace-dep
  wheel listed in a hard-coded `WORKSPACE_DEP_WHEEL_PREFIXES`
  array near the top of the script, downloads each `.sha256`,
  verifies with `sha256sum -c` (or `shasum -a 256 -c` on macOS),
  installs every wheel into a stdlib venv at
  `~/.local/share/<svc>/venv` via `python3 -m venv` + `pip install`,
  and symlinks every console-script entrypoint into
  `~/.local/bin/`. The `--uninstall` flag removes the symlinks +
  the venv.
- **Workspace-dep resolution.** Hard-coded per-service rather than
  parsed from `pyproject.toml` at install time. The audit gate is
  ADR 0036's `scripts/verify_workspace_deps.py`, which already
  pins the legal workspace edges. Today every service's runtime
  workspace closure is exactly `{agent-auth-common}` — a one-element
  list. Parsing TOML from a stdlib-only `install.sh` would force a
  `tomllib` round-trip with no payoff until the closure grows.
  When the closure grows, both the install script's array and the
  `verify_workspace_deps.py` allowlist need to move together; the
  comment at the top of each `install.sh` calls that out.
- **Local-mode flag.** `install.sh --local <dir>` lets the
  release-publish CI integration test (and any maintainer doing
  bench work) install from a directory of locally-built wheels +
  `.sha256` sidecars without round-tripping a published release.
- **CI integration test.** `test.yml` carries a new
  `install-from-wheels` matrix job (services: `things-cli`,
  `gpg-bridge`) that builds every workspace wheel via `uv build --all-packages`, generates `.sha256` sidecars, and runs
  `install.sh --local dist/` in a shell with `uv` scrubbed off
  PATH. The job asserts the entrypoint binary is on
  `~/.local/bin/`, `--version` exits 0, the venv at
  `~/.local/share/<svc>/venv` carries both the service and
  `agent-auth-common`, and `--uninstall` removes everything.

## Consequences

**Positive**

- The release pipeline produces a complete asset set again. Every
  release tag attaches one wheel + sdist + SBOM + cosign bundle +
  sha256 sidecar per workspace package (seven packages today).
- The install path no longer needs `uv` on PATH. Stdlib Python
  3.11+ is enough.
- A future Homebrew formula in `aidanns/homebrew-tools` can use
  `Language::Python::Virtualenv` with one `resource` block per
  workspace-dep wheel, against the same release assets the
  `install.sh` scripts consume.
- The `--local <dir>` flag gives both CI and local-bench work the
  same install path the released script uses, so a regression in
  install behaviour fails the integration test before a release
  even cuts.
- SLSA Build L3 provenance now spans every release artefact, not
  just two; the `slsa-verifier` recipe in `SECURITY.md` enumerates
  every wheel + sdist.

**Negative / trade-offs**

- The release-asset count multiplies by the workspace-package count
  (~5x with seven packages). The signing + SBOM loops in
  `release-publish.yml` therefore loop ~14 times instead of 4. CI
  cost and storage stay small in absolute terms; the only operator
  pain is a busier release-page asset list.
- Workspace-dep lists are duplicated: once in
  `packages/<svc>/pyproject.toml`'s `[project] dependencies`, once
  in the install script's `WORKSPACE_DEP_WHEEL_PREFIXES` array,
  once in ADR 0036's allowlist. Three places to update for any
  workspace-edge change. Mitigated by a cross-referenced comment at
  the top of every install.sh; if the edge count ever grows past
  ~3 we should revisit and parse `pyproject.toml` at install time.
- The `==COMMIT_MSG==` block can no longer credibly say "the
  release wheel" because there are now seven of them. The
  verification recipe in `SECURITY.md` carries the per-package
  enumeration loop.
- The integration test only covers two services
  (`things-cli`, `gpg-bridge`) on Linux today. macOS coverage and
  the remaining services (which share the install template
  byte-for-byte modulo the per-service variables) ride on the
  template's structural correctness rather than per-service CI.
  Acceptable while the install scripts are mechanically generated
  from the same template; a future divergence would mean
  expanding the matrix.

**Neutral**

- ADR 0035 (single workspace train) is unchanged. Every wheel in a
  release tag still carries the same version (semantic-release
  still tags repo-wide).
- The `git+...#subdirectory=...` install path is not deleted;
  consumers who prefer it can continue to `uv tool install` from
  source. This ADR adds the wheel-and-checksum path as the
  default, not the only path. Removing the source path is tracked
  separately if a maintainer ever wants to.

## Follow-ups

- Homebrew formula in `aidanns/homebrew-tools` once this lands.
- Decide whether to delete the `git+...#subdirectory=...` source-
  install path; tracked as a follow-up issue, not gated by this
  ADR.

<!-- REUSE-IgnoreEnd -->
