<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Implementation Plan: Subprocess-driven shutdown tests (#163)

## Context

Closes #163. Follow-up to #162 (SIGTERM graceful shutdown for
`agent-auth serve` / `things-bridge serve`), which landed unit-level
coverage but left two of the #154 acceptance criteria exercised only
indirectly:

- **New connections rejected after the signal is delivered** — the unit
  tests reach this via `server.shutdown` / `server_close` rather than a
  real listening socket on the far side of SIGTERM.
- **Process exits 0** — not covered; `run_server` returns cleanly under
  test, but nothing pins `sys.exit(0)` semantics from a real subprocess.

This PR adds `tests/test_shutdown_subprocess.py`, which spawns each
serve command as a real subprocess, drives SIGTERM / SIGINT through
`os.kill`, and asserts exit status, connection refusal, and bounded
wall time.

The remaining #154 acceptance criterion (`phase=compose_stop < 2s per test`) is verified by re-running the integration slice now that #152's
`integration.timing` logger is in place, and recording the observation
on #154.

## Design and verification

- **Verify against design doc** — no design change. The tests pin the
  already-documented *Graceful shutdown* behaviour from `design/DESIGN.md`
  and ADR 0018; they add coverage only.
- **Threat model (`SECURITY.md`)** — no new threat surface. Subprocess
  tests run entirely inside the project's test harness.
- **ADR** — no new decision. The subprocess-test split was already
  captured in the *Alternatives considered* section of ADR 0018 (the
  in-process tests "deliberately skip subprocess-level testing because
  driving a real `agent-auth serve` subprocess needs a keyring backend
  that works without a GUI ...").
- **Cybersecurity standard compliance (NIST SSDF)** — the new test file
  strengthens PW.7 (test executable code) by exercising shutdown on the
  real process boundary. No code-level compliance delta.
- **QM / SIL** — QM applies. New tests raise coverage of the graceful
  shutdown functional-decomposition leaves without adding new leaves.

## Functional decomposition updates

None. The tests attach additional `@pytest.mark.covers_function` markers
to the existing leaves `Handle Graceful Shutdown` and
`Handle Bridge Graceful Shutdown` introduced by #162.

## File structure

```
pyproject.toml                  # add keyrings.alt>=5.0 to [project.optional-dependencies].dev
src/agent_auth/server.py        # print the bound port (not the configured port) on startup
src/things_bridge/server.py     # same
tests/test_shutdown_subprocess.py   # new — subprocess shutdown tests
plans/shutdown-subprocess-tests.md  # this file
```

## Implementation

### 1. Dev dependency: `keyrings.alt`

The Docker integration image already installs `keyrings.alt>=5.0` and
sets `PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring` so
`agent-auth serve` can bootstrap the management token without a GUI.
Reuse the same backend in the subprocess tests — consistent with the
Docker image, one source of truth.

Add `keyrings.alt>=5.0` to `[project.optional-dependencies].dev` so
`uv sync --extra dev` provides it. No runtime dependency change.

### 2. Print the bound port

Both `run_server` functions currently print
`f"listening on {config.host}:{config.port}"`, which shows the
*configured* port. With `port: 0` the printed port is `0`, so there's no
race-free way for a subprocess test to discover the OS-assigned port.

Change the print in `src/agent_auth/server.py` and
`src/things_bridge/server.py` to read from `server.server_address`
(which is populated by `socketserver.TCPServer.server_bind`). The line
becomes `f"listening on {host}:{port}"` where `(host, port) = server.server_address`. Works for any configured port, makes `port: 0`
actually usable, and is a legitimate observability improvement
independent of these tests.

### 3. `tests/test_shutdown_subprocess.py`

Structure:

- **Fixture `subprocess_env`** — builds a dict environ for the child
  with `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME` all
  rooted inside a `tmp_path` subtree, plus
  `PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring`. This
  isolates both agent-auth's XDG paths and `keyrings.alt`'s plaintext
  keyring file (which lives at the keyring library's `data_root()`) so
  the test never touches the developer's real keyring.
- **Helper `_spawn(argv, env, cwd)`** — `subprocess.Popen` with
  `stdout=subprocess.PIPE`, `stderr=subprocess.STDOUT`, `text=True`. A
  reader thread drains stdout line-by-line into a `queue.Queue`, so the
  main test thread can both poll the child for a "listening on" line
  and also capture the full output for assertion messages when the
  child crashes.
- **Helper `_wait_for_listening(proc, out_queue, pattern)`** — drains
  the queue until a line matches `listening on 127\.0\.0\.1:(\d+)`,
  returns the int port. Times out if the child exits first or stays
  silent longer than `READY_TIMEOUT_SECONDS`.
- **Helper `_config_dir_for_agent_auth(tmp_path, port=0, shutdown_deadline_seconds=1.0)`** — writes a minimal `config.yaml`
  into a tmp dir, using port 0 so the OS picks a free port. The test
  uses a shorter-than-default 1s deadline to keep the total wall time
  low while still safely inside the CI's budget.
- **Helper `_config_dir_for_things_bridge(tmp_path, port=0, ...)`** —
  same shape; the bridge's config has no keyring requirement, but the
  test still isolates XDG paths for consistency.

Tests (one per server, parametrized over signal):

- **`test_agent_auth_serve_exits_zero_and_closes_socket`** —
  parametrized over `[signal.SIGTERM, signal.SIGINT]`. Spawn
  `python -m agent_auth.cli --config-dir CFG serve`, wait for the
  `listening on` line to discover the bound port, deliver the signal,
  and assert all three #154 properties in one go:
  `exit_code == 0`, `elapsed_seconds < WALL_TIME_BUDGET_SECONDS`, and
  a fresh `socket.create_connection` to the bound port raises
  `ConnectionRefusedError` (pins that the listening socket was torn
  down, not swapped with a black-hole handler). Marked
  `covers_function("Handle Graceful Shutdown", "Handle Serve Command")`.
- **`test_things_bridge_serve_exits_zero_and_closes_socket`** — same
  shape for `things-bridge`. Marked
  `covers_function("Handle Bridge Graceful Shutdown")`.

Consolidating the earlier `_sigterm` / `_sigint` / `_shutdown_is_bounded`
triplets per service into these two parametrized functions keeps the
spawn overhead to one subprocess per signal rather than three, with
no property dropped — each parametrized case pins exit status,
bounded wall time, and connection refusal together.

### 4. Running the subprocess via `python -m`

`scripts/agent-auth.sh` and the `agent-auth` console script both
ultimately call `agent_auth.cli:main`. The test spawns
`sys.executable -m agent_auth.cli` so it inherits the running venv's
site-packages without needing the console script on `PATH` — the venv
is rebuilt per CI run and may or may not have scripts exposed.

### 5. Integration verification for #154

After this PR is ready locally, run
`scripts/test.sh --integration agent-auth` and
`scripts/test.sh --integration things-bridge` and grep the
`phase=compose_stop` lines. Confirm every teardown is below 2s. If any
exceed, investigate before opening the PR — the goal is to tick the
final unchecked #154 acceptance criterion based on evidence.

Since the verification is a one-shot evidence exercise (not a
permanent harness assertion), the finding goes in the PR description /
#154 comment rather than a new assertion in the test suite.

## Test plan

- `task test` passes (new subprocess tests run as part of the unit
  suite).
- `task test:fast` still passes — the fast smoke subset is unaffected.
- `task lint`, `task typecheck`, `task format -- --check` pass.
- `task verify-function-tests` passes — the new tests attach the
  required `covers_function` markers.
- `task verify-standards`, `task verify-design` pass.
- `scripts/test.sh --integration agent-auth` — evidence that
  `phase=compose_stop < 2s` per test; record in PR.
- `scripts/test.sh --integration things-bridge` — same.

## Post-implementation standards review

- **Coding standards** — test function names are verbs-with-conditions
  (`test_agent_auth_serve_exits_zero_on_sigterm`); constants carry
  units (`READY_TIMEOUT_SECONDS`, `WALL_TIME_BUDGET_SECONDS`); no raw
  tuples at trust boundaries.
- **Service design** — no service-surface change. The bound-port print
  improvement strengthens the "observable startup" aspect of the
  resilience bullet.
- **Release and hygiene** — `keyrings.alt` is a dev-only dependency;
  no user-facing version or API change.
- **Testing standards** — tests exercise the public surface
  (`subprocess.Popen` + HTTP + `os.kill`); no internal imports; each
  test declares its covered leaf. The keyring isolation keeps the
  test hermetic.
- **Tooling and CI** — no new check scripts; existing
  `scripts/test.sh --unit` path runs the new file.
