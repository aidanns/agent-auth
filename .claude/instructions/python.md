# Python-Specific Standards

Language-specific guidance for Python projects. Apply alongside the
general coding standards in `coding-standards.md`.

## Types

- **`typing.NewType`** — use `NewType` for newtypes at trust/security
  boundaries (e.g. `Ciphertext = NewType('Ciphertext', bytes)`).
- **`typing.NamedTuple` or `dataclass`** — use for semantic types and
  structured keys instead of raw tuples or dicts.

## Configuration

- **`PyYAML` with `safe_load`** — use for parsing YAML config files.
- **`setuptools-scm`** — derive version from git tags at build time and
  read back via `importlib.metadata`.

## Tooling

- **`ruff`** — linting and formatting.
- **`mypy` and `pyright`** — type checking. Run both in CI.
- **`uv`** — virtual environment and dependency resolution. Creates `.venv/`
  in the project directory per the global convention.
- **`pytest-cov`** — line and branch coverage with a ratcheting threshold.
- **`pip-audit`** (or `safety`) — dependency vulnerability scanning in CI.
