# Coding Standards

Rules for how code should be written. These supplement the user's global
conventions (conventional commits, bash script style, etc.).

## Naming

- **Units in names** — any numeric configuration field or constant carrying a
  unit must encode it in the name: `timeout_seconds`, `buffer_size_bytes`,
  `max_retries_count`. Never leave the unit implicit.
- **Method names reflect the variant handled** — when a type or concept has
  multiple variants and a function only handles one, put the variant in the
  name: `expire_timed_grants` not `expire_grants`, `parse_json_config` not
  `parse_config`.

## Types and safety

- **Newtypes at security/trust boundaries** — use the language's newtype
  mechanism (`typing.NewType` in Python, newtype wrappers in Rust/Go, branded
  types in TypeScript) for every semantically distinct value at a security
  boundary. Don't accept or return raw bytes/strings where a more specific
  type is possible.
- **Semantic types for structured keys** — prefer named types (named tuples,
  dataclasses, structs) over raw tuples or strings whenever a composite value
  carries structure.

## Configuration

- **Human-editable config defaults to YAML** — use YAML for user-edited
  config files, not JSON. JSON lacks comments, trailing commas, and readable
  grouping.
- **Defaults live in code, not on disk** — do not persist a default config
  file on first run. A fresh install should rely on in-code defaults until
  the user deliberately customises. Writing a defaults file creates a
  parallel source of truth and forces migration work when defaults change.
- **Single source of truth per config value** — for each configurable value,
  pick exactly one source (CLI flag, config field, or env var) and document
  why. Do not duplicate the same setting across multiple sources.
- **Version string from VCS tags** — derive the version from git tags at
  build time (e.g. `setuptools-scm` for Python, `git describe` for others)
  and read it back at runtime. Never hard-code version strings.

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

## Audit and logging

- **Audit-log schema is a public API** — structured log schemas consumed by
  downstream systems (SIEM, compliance, forensics) are load-bearing. Treat
  changes to field names or types as breaking changes and pin the schema
  with tests.
