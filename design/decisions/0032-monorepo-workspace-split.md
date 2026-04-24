<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# ADR 0032 — Split services into a uv workspace of per-service subprojects

## Status

Accepted — 2026-04-23.

## Context

Before this ADR every console-script in the repository shipped from a
single `pyproject.toml` at the root: `agent-auth`, `agent-auth-notifier`,
`things-bridge`, `things-cli`, and `things-client-cli-applescript` all
installed together as the `agent-auth` distribution. Running
`install.sh` pulled in the full dependency closure even for consumers
who only wanted a single binary — e.g. a user of `things-cli` would
still get `cryptography`, `keyring`, and the Things AppleScript
helpers they never invoke.

The services have materially different target audiences, platforms,
and release cadences. `things-cli` is a read-only client; it should
be installable on a machine that has no business carrying
`agent-auth`'s keyring-touching dependencies. `things-client-cli-applescript`
only works on macOS. Keeping them coupled at the packaging layer
re-coupled dependency closures, threat models, and release tags.

Issue [#105](https://github.com/aidanns/agent-auth/issues/105) asks for
a per-service subproject split with `agent-auth-common` as a
first-class workspace package for shared types.

## Considered alternatives

### Stay on a single `pyproject.toml`

Keep one distribution that ships every console-script.

**Rejected** because:

- `curl | bash` installs paid for the full dependency closure of every
  service regardless of which binary the caller wants.
- Service-specific refactors required to touch every user of the
  shared wheel — no real insulation.
- ADR 0005's per-service Dockerfile split (#95) anticipated this move
  and named it as the follow-up; keeping the code coupled while the
  images diverged added gratuitous drift.

### Separate Git repositories, one per service

Pull each service into its own repo with its own tag namespace.

**Rejected** for now because:

- The integration tests that exercise the full `agent-auth` ↔
  `things-bridge` ↔ Things-client stack have to live somewhere that
  can reach every service. Splitting repos would require either a
  dependency on every service's release tag or a separate
  integration-tests repo with its own release coordination problem.
- A uv workspace accepts per-package development in one checkout and
  still lets each package publish to PyPI independently. Splitting
  repos is still possible later if a service's release cadence
  diverges enough to warrant it.

### Single package with optional-dependency extras (`agent-auth[bridge]`)

Keep one distribution but gate each service's deps behind an extra.

**Rejected** because extras cannot carry console-scripts through pip's
install flow reliably (`uv tool install agent-auth[bridge]` still
writes every script into the tool env) and extras don't separate
release tags. The refactor cost is the same as a workspace split for
less isolation.

## Decision

Lay the repository out as a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
under `packages/`:

```
packages/
  agent-auth-common/            pyproject.toml + src/
  agent-auth/                   pyproject.toml + install.sh + src/
  things-bridge/                pyproject.toml + install.sh + src/
  things-cli/                   pyproject.toml + install.sh + src/
  things-client-cli-applescript/pyproject.toml + install.sh + src/
```

Root `pyproject.toml` carries only the `[tool.uv.workspace]`
declaration plus the cross-cutting tooling config (pytest, coverage,
mypy, ruff, mutmut) so the tests, type checkers, and linters see every
workspace tree through one invocation. The dev toolchain lives in a
PEP 735 `[dependency-groups] dev` block that `uv sync` installs with
every workspace member as a dev dep.

### Package surfaces

- **`agent-auth-common`** is a library-only workspace package with no
  console-script. It owns:
  - `agent_auth_client`, `things_bridge_client` — the typed HTTP
    clients extracted in #94.
  - `server_metrics` — the Prometheus metrics helper shared by
    `agent-auth` and `things-bridge`.
  - `things_models`, `things_client_common` — the Things dataclasses
    and CLI framework shared by `things-bridge`,
    `things-client-cli-applescript`, and the in-tree fake.
  - `tests_support` — the HTTP notifier sidecar used by the Docker
    integration tests, gated behind a `testing` extra so it never
    enters a production install.
- **`agent-auth`** installs the token server, the `agent-auth` CLI,
  and the `agent-auth-notifier` sidecar.
- **`things-bridge`** installs the HTTP bridge.
- **`things-cli`** installs the read-only CLI.
- **`things-client-cli-applescript`** installs the macOS AppleScript
  CLI (Python installs on Linux too because contract tests need the
  module, but the osascript paths fail outside macOS).

Every service package declares `agent-auth-common` as a dependency.
`[tool.uv.sources]` resolves the common package from the workspace
during development; when common is published to PyPI, consumers can
ignore the source override and pin a PyPI version.

### Install story

The root `install.sh` is deleted. Each service carries its own
`packages/<svc>/install.sh` that `uv tool install`s from
`git+https://github.com/aidanns/agent-auth.git#subdirectory=packages/<svc>`.
Running `curl -fsSL <url>/packages/<svc>/install.sh | bash` therefore
installs only that service's dependency closure (plus
`agent-auth-common`).

### Dockerfiles

The per-service Dockerfiles introduced in #95 are updated to
`COPY packages/<svc>/` + `COPY packages/agent-auth-common/` and
`pip install ./packages/agent-auth-common ./packages/<svc>`. No
shared base layer; each Dockerfile stays self-contained per ADR 0005
(amended).

### Tests, benchmarks, fixtures

The `tests/` tree stays at the repo root because the integration and
cross-service tests reach every service. `pyproject.toml`'s
`pythonpath` lists every package's `src/` root so pytest resolves
`from agent_auth import ...` regardless of whether the dev did a
fresh `uv sync` or an in-place edit. The tests and benchmarks
continue to drive the same behaviour; only the import paths for
tooling configuration (mypy `files`, ruff `src`, pyright `include`,
mutmut `paths_to_mutate`, `scripts/verify-standards.sh`) were
re-anchored at `packages/<svc>/src/`.

### Release automation

The existing semantic-release config remains on a single repo-wide
`v<X>.<Y>.<Z>` tag. Namespaced per-package tags
(`agent-auth/v<X>.<Y>.<Z>`, `things-cli/v<X>.<Y>.<Z>`, …) + per-package
`CHANGELOG.md` files + independent CI publish jobs are a planned
follow-up — see *Follow-ups* below. Every workspace package still
carries its own `[project] dynamic = ["version"]` + `setuptools_scm`
block, so the moment that namespaced tags start being cut, the
per-package version resolution works without further code change.

## Consequences

Positive:

- Dependency closures shrink for single-service installs.
  `curl | bash` for `things-cli` no longer pulls in `cryptography` /
  `keyring` / `pyyaml`-bridge-only transitive deps.
- Service-specific refactors isolate in one package's tree: a change
  to `things-bridge` cannot accidentally pull an unrelated
  `agent-auth` module into the bridge's wheel.
- The uv workspace gives a single `uv sync --extra dev` that still
  covers every package, so local dev doesn't regress.
- The pre-requisite for per-package releases is now code; when the
  release-automation work lands, no structural refactor is needed.

Negative:

- More boilerplate: five `pyproject.toml` files instead of one, five
  `install.sh` scripts, five sets of SPDX headers.
- A root `install.sh` one-liner no longer exists. Users installing
  every service run four per-service installers instead. Acceptable
  because the single-install use case was never more than a
  convenience — real users were already picking which binaries they
  wanted.
- CI integration jobs still each build every per-service Docker
  image. Selective per-job builds would save time; tracked as a
  follow-up under #129 (the existing buildx caching work) since the
  GHA cache makes the redundant builds cheap.

Negative, unresolved:

- `uv.lock` covers the entire workspace. Per-package lock files are
  not yet split; a change that only affects one service still churns
  the single root lockfile. This is acceptable for the current
  single-version-across-packages release strategy and will be
  revisited when release tags namespace.

## Follow-ups

- Per-package release automation: namespaced tags
  (`agent-auth/v<X>.<Y>.<Z>`), per-package `CHANGELOG.md`, per-package
  `SECURITY.md` where relevant, independent semantic-release
  configuration. Tracked separately once the workspace has settled.
- PyPI publishing: once per-package releases are in place, each
  package can publish its wheel independently. Until then, the
  per-service `install.sh` scripts install straight from the Git
  tree.
- Move cross-service integration tests under `tests/integration/` into
  their own workspace test package (`agent-auth-integration`?) so the
  test tree can consume published-style installs rather than the
  in-tree workspace — captured as part of the release-automation
  follow-up above.
