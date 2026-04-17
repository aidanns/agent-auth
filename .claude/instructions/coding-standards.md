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
  mechanism for every semantically distinct value at a security boundary.
  Don't accept or return raw bytes/strings where a more specific type is
  possible.
- **Prefer explicit typing to prevent misuse** — whenever a value has been
  validated, sanitised, or transformed, wrap it in a distinct type so that
  callers cannot accidentally pass the raw form. For example, a sanitise
  function should return `SanitizedString` rather than `str`, and a function
  that expects sanitised text should accept `SanitizedString` as a parameter.
  This applies broadly: validated IDs, parsed configs, normalised paths, etc.
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
  pick exactly one source and document why. Do not duplicate the same setting
  across multiple sources. Prefer configuration files for servers. For CLIs,
  prefer command-line switches, with secrets held in the system keychain (if
  available) or in files on disk with 600 permissions.
- **Version string from VCS tags** — derive the version from git tags at
  build time and read it back at runtime. Never hard-code version strings.

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

## Logging

- **Log and audit schemas are public APIs** — structured log schemas and
  audit-log schemas consumed by downstream systems (SIEM, compliance,
  forensics, monitoring) are load-bearing. Treat changes to field names or
  types as breaking changes and pin schemas with tests. This applies to
  application logs, audit logs, and metrics output alike.
