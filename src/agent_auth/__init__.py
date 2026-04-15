"""agent-auth: Token-based authorization for AI agent access to host applications."""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("agent-auth")
except PackageNotFoundError:
    # Package metadata is only available once installed (e.g. ``pip install -e .``).
    # Fall back to a sentinel so importing from a source checkout still works.
    __version__ = "0.0.0+unknown"
