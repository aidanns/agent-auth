# Plan: Fix Stale Venv in `scripts/*.sh` Wrappers + Run Services via Taskfile

Issue: [#60](https://github.com/aidanns/agent-auth/issues/60).

Bundles a secondary change: expose each service/CLI (`agent-auth`,
`things-bridge`, `things-cli`, `things-client-applescript`) through
`task`, so the new wrapper behaviour is reached through the project's
canonical entrypoint as well as via direct script invocation.

## Goal

Re-running any `scripts/*.sh` wrapper must reflect the current state of
`pyproject.toml` (entry points, dependencies, extras) without users
having to remember to reinstall or blow away the venv. In parallel,
surface each of the three tool CLIs as `task` commands so the standard
task-runner entrypoint (see `tooling-and-ci.md` → *Orchestration*) can
start a service or run the client.

## Non-goals

- Replacing `pip` with `uv` or another installer. Out of scope.
- Adding `uv.lock` / `requirements*.txt`. Out of scope.
- Changing how `scripts/test.sh` / `scripts/build.sh` bootstrap the
  venv. Those scripts already reinstall unconditionally (different
  correctness strategy). They will be migrated to the shared helper
  only if the helper's semantics match — see *Implementation steps*.
- Wrapping the CLIs in a long-running supervisor (`systemd`,
  `launchd`, `honcho`). Task dispatch is synchronous and foreground;
  stopping a service is `Ctrl+C`.

## Deliverables

1. `scripts/_bootstrap_venv.sh` — shared helper sourced by every
   wrapper. Ensures the per-OS/arch venv exists and is up-to-date
   against `pyproject.toml` using a hash marker (`pyproject.sha256`)
   stored inside the venv. Fast path (hash match) is a no-op; slow
   path runs `pip install -e ".[dev]"` and refreshes the marker.
2. `scripts/agent-auth.sh`, `scripts/things-bridge.sh`,
   `scripts/things-cli.sh`, `scripts/things-client-applescript.sh` —
   refactored to source the helper. No behavioural change except that
   a changed `pyproject.toml` now triggers a reinstall on the next
   invocation.
3. `scripts/test.sh` and `scripts/build.sh` — refactored to source the
   same helper, so all wrappers share one bootstrap implementation.
   The helper's rebuild-on-hash-change semantics are strictly safer
   than the existing "reinstall every time" behaviour (it still
   reinstalls when the hash changes; it just skips the redundant
   reinstalls), so the migration does not regress correctness and
   removes the duplication these two scripts call out in their own
   comments.
4. `Taskfile.yml` — four new tasks that dispatch to the existing
   wrapper scripts:
   - `agent-auth` → `scripts/agent-auth.sh {{.CLI_ARGS}}`
   - `things-bridge` → `scripts/things-bridge.sh {{.CLI_ARGS}}`
   - `things-cli` → `scripts/things-cli.sh {{.CLI_ARGS}}`
   - `things-client-applescript` →
     `scripts/things-client-applescript.sh {{.CLI_ARGS}}`

   Naming matches the underlying CLI name (not `serve-…`) so the task
   is a general-purpose entrypoint, not a server-only shortcut. The
   same task serves all subcommands — e.g.
   `task agent-auth -- token create --scope things:read=allow`.
5. `scripts/verify-standards.sh` — **does not** list these
   project-specific task names in `REQUIRED_TASKS`. That list is
   reserved for generic, portable tasks mandated by
   `.claude/instructions/tooling-and-ci.md` so the script stays
   applicable across projects. The header comment, `CLAUDE.md`, and
   `tooling-and-ci.md` are updated to make this boundary explicit.
6. `scripts/verify-dependencies.sh` — add `shasum` to the list of
   required CLI tools so a missing `shasum` surfaces as a dependency
   error rather than a cryptic failure inside the bootstrap helper.
7. `README.md` and `CONTRIBUTING.md` — document the new task entries
   and note that the wrapper scripts now self-heal when
   `pyproject.toml` changes.

## Rationale for the chosen rebuild strategy

The issue proposes three options:

1. Reinstall on every invocation — simple but adds ~1s to every
   wrapper call, which compounds for the CLI (`things-cli` is run
   interactively and repeatedly).
2. Compare `pyproject.toml` mtime — fragile under rebases, `touch`,
   and filesystem copy. Mtime loses correctness when users move their
   checkout or revert a file.
3. Hash `pyproject.toml` into a marker — fast path is a single
   `shasum -a 256` compare; slow path is the same `pip install` as
   today. Correct under rebases, reverts, and `touch`. We use
   `shasum -a 256` rather than `sha256sum` because macOS does not
   ship GNU coreutils by default, so `sha256sum` is not on PATH
   there; `shasum` is present on both macOS (perl-backed) and Linux.

(3) is the option the issue calls out as the best trade-off, and this
plan adopts it. The marker file (`pyproject.sha256`) lives inside
the venv, so a `rm -rf .venv-*` force-reinstall workflow still works.

## Design and verification

The following plan-template steps are **not applicable** and are
intentionally skipped:

- *Verify implementation against design doc* — the wrapper scripts
  and task runner are developer tooling, not behavioural components
  of `agent-auth`. They do not appear in `design/DESIGN.md`,
  `functional_decomposition.yaml`, or `product_breakdown.yaml`.
- *Threat model / cybersecurity standard compliance* — no change to
  the running service's attack surface, keys, or data flow. The
  marker file is a local developer-tooling artefact that is never
  loaded by the server. Hashing `pyproject.toml` with `sha256sum` is
  not a security control; it is an integrity check for a local
  cache.
- *QM / SIL compliance* — no change to production code, functional
  behaviour, or evidence requirements.
- *ADRs* — the per-OS/arch venv layout and the go-task dispatch
  pattern are both already standard for this project (documented in
  `CLAUDE.md` and `.claude/instructions/tooling-and-ci.md`). Adding
  a new task that follows the established dispatch pattern and a
  helper that factors duplication out of existing scripts is not a
  novel design decision; no new ADR required.

## Implementation steps

1. **`scripts/_bootstrap_venv.sh`** — new file. Exports `VENV_DIR`
   and `REPO_ROOT`, then chdirs to the repo root so callers can use
   relative paths. Designed to be *sourced*, not executed, so callers
   can then `exec "${VENV_DIR}/bin/<cli>"` in the same process.
   Contract:
   - Resolves repo root via `BASH_SOURCE`, independent of caller CWD.
   - Detects a missing or half-built venv (`[[ -x "${VENV_DIR}/bin/pip" ]]`)
     and (re)creates it with `python3 -m venv --clear` so an interrupted
     prior bootstrap is self-healing.
   - Reinstalls `".[dev]"` when the stored hash differs from the
     current `pyproject.toml` hash, then rewrites the marker.
   - Uses `pip install --quiet` to keep the fast path quiet.
   - Emits a one-line stderr notice ("Bootstrapping venv…" /
     "Refreshing venv (pyproject.toml changed)…") on the slow path
     so users know why the first call after an edit is slower.
   - Fast path reads the current and stored hashes with `read -r`
     (no `awk` / `cat` subprocesses beyond the single `shasum`).
2. **Refactor wrappers** — each of `agent-auth.sh`,
   `things-bridge.sh`, `things-cli.sh` reduces to:
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
   # shellcheck source=./_bootstrap_venv.sh
   source "${SCRIPT_DIR}/_bootstrap_venv.sh"
   exec "${VENV_DIR}/bin/<cli>" "$@"
   ```
3. **Refactor `scripts/test.sh` and `scripts/build.sh`** — same
   source-and-exec pattern. Drop the local "reinstall every time"
   comment (now obsolete).
4. **`Taskfile.yml`** — append three new tasks (`agent-auth`,
   `things-bridge`, `things-cli`) following the existing
   `{{.CLI_ARGS}}` pattern used by `task test`.
5. **`scripts/verify-standards.sh`** — extend `REQUIRED_TASKS` with
   the three new task names (keep-sorted block preserved).
6. **`README.md` / `CONTRIBUTING.md`** — document `task agent-auth`,
   `task things-bridge`, `task things-cli` as the preferred
   entrypoints; note that wrappers reinstall automatically when
   `pyproject.toml` changes.

## Deterministic regression check

- `scripts/verify-standards.sh` now fails if any of `agent-auth`,
  `things-bridge`, `things-cli` is removed from `Taskfile.yml`.
- The bootstrap helper is exercised by the full test suite on every
  `task test` run (same bootstrap runs there), so a regression that
  breaks the fast path or the rebuild trigger is caught by CI.

## Post-implementation standards review

Run each of the following against the diff (per CLAUDE.md → *Post-Change
Review*):

- [ ] `/simplify` on the changes.
- [ ] Independent code-review subagent; address findings.
- [ ] One parallel subagent per file in `.claude/instructions/` — each
      reviews the diff against its instruction file and reports
      violations. Address findings.

Specifically verify:

- **`coding-standards.md`** — no implicit-unit names
  (marker file is a hash, not a duration). The helper exports
  `VENV_DIR`, a path, not a numeric config value.
- **`bash.md`** — every new and refactored `*.sh` follows the
  standard header block (`#!/usr/bin/env bash`, blank-line-padded
  description comment, `set -euo pipefail`).
- **`service-design.md`** — not applicable (no service changes).
- **`testing-standards.md`** — no behavioural code changes, so no
  new unit tests. The deterministic regression check (updated
  `verify-standards.sh`) is the test for the task-surface change;
  the rebuild logic is exercised by every developer's next
  `task test` run and by CI.
- **`tooling-and-ci.md`** — the new tasks are the canonical
  entrypoint for running each service; the Taskfile remains the
  single `task --list` source of truth.
- **`release-and-hygiene.md`** — no impact on release artefacts or
  required files.
- **`python.md`** — no Python-code changes.
