# Service Design Standards

Standards for how services and applications should be designed and
configured.

## Configuration

- **Human-editable config defaults to YAML** — use YAML for user-edited
  config files, not JSON. JSON lacks comments, trailing commas, and readable
  grouping.
- **Defaults live in code, not on disk** — do not persist a default config
  file on first run. A fresh install should rely on in-code defaults until
  the user deliberately customises. Writing a defaults file creates a
  parallel source of truth and forces migration work when defaults change.
- **Single source of truth per config value** — for each configurable value,
  pick exactly one source and document why. Do not duplicate the same setting
  across multiple sources. Prefer configuration files for servers. For CLIs,
  prefer command-line switches, with secrets held in the system keychain (if
  available) or in files on disk with 600 permissions.

## File paths

- **XDG Base Directory compliance** — map each file class to the correct XDG
  variable:
  - Config files -> `$XDG_CONFIG_HOME` (`~/.config/`)
  - Data files (DB, persistent state) -> `$XDG_DATA_HOME` (`~/.local/share/`)
  - Runtime state/logs -> `$XDG_STATE_HOME` (`~/.local/state/`)

  Never put everything under `~/.config/`.

## Plugin and extension surfaces

- **Out-of-process by default** — when the host process holds secrets,
  plugin/extension surfaces must default to out-of-process communication
  (HTTP, IPC). Never load third-party code into a secret-holding process
  without explicit design review.

## HTTP services

- **Health-check endpoint** — every HTTP service should expose a health
  endpoint that returns 200 when critical subsystems are healthy.
- **Metrics endpoint** — every HTTP service should expose a metrics endpoint
  with Prometheus-compatible output covering request counts, latency, and
  domain-specific counters.
- **Rate limiting / DoS posture** — decide an expected request rate and
  ceiling, document it, and implement or explicitly note why it is not
  required.

## Security

- **Key recovery and loss scenarios** — design a deliberate recovery / backup
  / warning flow for when secrets are lost.

## Resilience

- **Graceful shutdown** — design and test shutdown behaviour so in-flight
  requests complete cleanly on SIGTERM.
- **Observability design** — document log schema, log levels, retention
  policy, log location (per XDG: `$XDG_STATE_HOME`), and any emitted
  metrics.
