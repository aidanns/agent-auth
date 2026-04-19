# ADR 0012 — XDG path layout

## Status

Accepted — 2026-04-19.

Backfilled ADR.

## Context

agent-auth (and the adjacent `things-bridge`) write three distinct
classes of file to the user's home directory:

- **Config** — user-editable settings (TTLs, approval plugin
  selection, bridge URLs). Read on startup; not written by the
  server at runtime.
- **Data** — the SQLite token store. Owned by agent-auth; the user
  shouldn't edit it.
- **State** — the audit log. Append-only, grows over time, can be
  rotated or archived.

Shoving all three into `~/.config/agent-auth/` (or worse,
`~/.agent-auth/`) conflates them. The user backing up `~/.config`
picks up the SQLite file and the growing audit log; a tool truncating
"state" directories deletes their tokens.

The
[XDG Base Directory spec](https://specifications.freedesktop.org/basedir-spec/latest/)
defines the right distinction
(`$XDG_CONFIG_HOME` / `$XDG_DATA_HOME` / `$XDG_STATE_HOME`) and
standard defaults for all three.

## Considered alternatives

### Single `~/.agent-auth/` dotfile directory

Minimal. Defeats backup / sync tool heuristics that treat XDG paths
specifically. Doesn't match what `service-design.md` requires.

**Rejected.**

### Respect XDG but fall through to `~/.config/agent-auth/` only

Drop state/data distinction, collapse everything under config.

**Rejected** — makes backing up "just my config" either lose the
audit log or pick up the SQLite DB. The user's mental model of
"config is the stuff I want synced" breaks.

## Decision

Follow the XDG Base Directory spec. Every agent-auth service
computes its paths via small helpers (`src/agent_auth/config.py`,
mirrored in `src/things_bridge/config.py`):

- `_default_config_dir()` → `$XDG_CONFIG_HOME/agent-auth` (default
  `~/.config/agent-auth`). Holds `config.json`.
- `_default_data_dir()` → `$XDG_DATA_HOME/agent-auth` (default
  `~/.local/share/agent-auth`). Holds `tokens.db`.
- `_default_state_dir()` → `$XDG_STATE_HOME/agent-auth` (default
  `~/.local/state/agent-auth`). Holds the audit log.

All three helpers read the env var and fall back to the XDG-specified
default. `things-bridge` does not own a data directory (it's
stateless w.r.t. Things 3 — the upstream state lives in Things 3
itself) and so only defines config and state.

Directories are created on first use with `Path.mkdir(parents=True, exist_ok=True)` (default umask applies). Config files are not
written by the server (it reads defaults and overlays the user's
`config.json` if present) — the server does not own the user's
config.

## Consequences

- Standard tooling respects the separation: `borgbackup`-style tools
  can be configured to archive `$XDG_DATA_HOME`, cloud sync tools
  can target `$XDG_CONFIG_HOME`, log rotators can chew through
  `$XDG_STATE_HOME/agent-auth/audit.log` without touching data.
- Defaults are explicit: on macOS (where XDG isn't the platform
  convention) the defaults still place the SQLite DB at
  `~/.local/share/agent-auth/tokens.db`. Users who want the
  platform-native `~/Library/Application Support/agent-auth/tokens.db`
  can set `XDG_DATA_HOME` to that path explicitly. Tracked as a
  follow-up if it becomes a usability issue.
- Integration tests override all three env vars to a per-test
  tempdir via bind mount (see ADR 0004) so container tests can't
  collide with the host's files.
- Multi-user installs on a shared host get separate agent-auth
  instances naturally — every user has their own `$HOME` and
  therefore their own paths, tokens, and keyring entries.
- The CLI client follows the same scheme for its own config at
  `$XDG_CONFIG_HOME/<app>-cli/`. The optional
  `--credential-store=file` escape hatch writes to
  `$XDG_CONFIG_HOME/<app>-cli/credentials.yaml` with `0600` perms
  (see DESIGN.md).
