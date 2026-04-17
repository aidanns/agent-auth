# Coding Standards

Rules for how code should be written. These supplement the user's global
conventions (conventional commits, bash script style, etc.).

## Naming

- **Procedures have verb names** — functions and methods that perform actions
  should be named with a verb: `create_token`, `validate_request`,
  `expire_grants`. Reserve noun names for types, constants, and properties.
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
