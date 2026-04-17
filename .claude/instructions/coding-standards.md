# Coding Standards

Rules for how code should be written in this project. These supplement the
user's global conventions (conventional commits, bash script style, etc.).

## Naming

- **Units in names** — any numeric configuration field or constant carrying a
  unit must encode it in the name: `access_token_ttl_seconds`,
  `KEY_SIZE_BYTES`, `max_retries_count`. Never leave the unit implicit.
- **Method names reflect the variant handled** — when a type or concept has
  multiple variants and a function only handles one, put the variant in the
  name: `check_timed_grant` not `check_grant`, `_expire_timed_grants` not
  `_expire_grants`.

## Types and safety

- **`NewType` at security/trust boundaries** — use `typing.NewType` (or
  equivalent) for every semantically distinct byte blob at a security
  boundary: ciphertext vs plaintext, signing key vs encryption key, token
  signature vs token id. Don't accept or return raw `bytes` where a more
  specific type is possible.
- **Semantic types for structured keys** — prefer `typing.NamedTuple` or
  `dataclass` over raw tuples or strings whenever a composite value carries
  structure (e.g. `dict[GrantKey, datetime]` instead of
  `dict[tuple[str, str], datetime]`).

## Configuration

- **Human-editable config defaults to YAML** — use YAML (parsed with
  `PyYAML` `safe_load`) for user-edited config files, not JSON. JSON lacks
  comments, trailing commas, and readable grouping.
- **Defaults live in code, not on disk** — do not persist a default config
  file on first run. A fresh install should rely on in-code defaults until
  the user deliberately customises. Writing a defaults file creates a
  parallel source of truth and forces migration work when defaults change.
- **Single source of truth per config value** — for each configurable value,
  pick exactly one source (CLI flag, config field, or env var) and document
  why. Do not duplicate the same setting across multiple sources.
- **Version string from git tags** — derive the version from git tags at
  build time (e.g. `setuptools-scm`) and read it back via
  `importlib.metadata`. Never hard-code version strings.

## File paths

- **XDG Base Directory compliance** — map each file class to the correct XDG
  variable:
  - Config files -> `$XDG_CONFIG_HOME` (`~/.config/`)
  - Data files (DB, tokens) -> `$XDG_DATA_HOME` (`~/.local/share/`)
  - State/logs -> `$XDG_STATE_HOME` (`~/.local/state/`)

  Never put everything under `~/.config/`.

## Plugin and extension surfaces

- **Out-of-process by default** — when the host process holds secrets (signing
  keys, encryption keys), plugin/extension surfaces must default to
  out-of-process communication (HTTP, IPC). Never load third-party code via
  `importlib` into a secret-holding process without explicit design review.

## Audit and logging

- **Audit-log schema is a public API** — the JSON-lines schema of audit logs
  is load-bearing for downstream consumers (SIEM, compliance, forensics).
  Treat changes to field names or types as breaking changes and pin the
  schema with tests.
