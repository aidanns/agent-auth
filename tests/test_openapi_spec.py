# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Contract tests for the published OpenAPI specs.

Keeps `openapi/agent-auth.v1.yaml` and `openapi/agent-auth.v1.yaml`'s
sibling, `openapi/things-bridge.v1.yaml`, in lockstep with the server
implementations:

- Every route registered by ``AgentAuthHandler.do_GET`` /
  ``do_POST`` / ``do_HEAD`` / ``do_PUT`` / etc. must have a matching
  ``paths`` entry in the spec.
- Every spec path must correspond to a route the server actually
  handles (catches stale spec entries after a route rename).
- Both spec files must parse as valid OpenAPI 3.x (via
  ``openapi-spec-validator``).
"""

import inspect
import re
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from openapi_spec_validator import validate

from agent_auth import server as agent_auth_server
from things_bridge import server as things_bridge_server

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OPENAPI_DIR = _REPO_ROOT / "openapi"
_AGENT_AUTH_SPEC = _OPENAPI_DIR / "agent-auth.v1.yaml"
_THINGS_BRIDGE_SPEC = _OPENAPI_DIR / "things-bridge.v1.yaml"

# Pattern used to extract string literals from source — matches paths on
# ``self.path == "..."``, ``path == "..."``, ``path.startswith("...")``,
# plus bare ``/agent-auth/...`` or ``/things-bridge/...`` strings in
# routing tables.
_PATH_RE = re.compile(r'"(/(?:agent-auth|things-bridge)/[A-Za-z0-9/_\{\}-]*)"')


def _load_spec(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def _handler_paths(handler_cls: type) -> set[str]:
    """Extract the literal HTTP paths referenced by a handler class.

    The servers declare their routes as string literals inside the
    ``do_GET`` / ``do_POST`` method bodies and (for things-bridge)
    via ``startswith`` prefix checks. Reading the source is more
    robust than duck-typing: new routes added without a spec update
    are caught by the parity assertion below.
    """
    src = inspect.getsource(handler_cls)
    return {m.group(1) for m in _PATH_RE.finditer(src)}


def _spec_paths(spec: dict[str, Any]) -> set[str]:
    return set(spec.get("paths", {}).keys())


def _normalise_parameterised(paths: set[str]) -> set[str]:
    """Collapse paths with ``{id}`` (spec) and the server's ``startswith``
    prefix (``/things-bridge/v1/todos/``) to a common form so the two
    sides can be compared directly. Trailing slash is stripped, then
    ``{anything}`` is elided entirely so ``/x/{id}`` and ``/x/`` both
    compare as ``/x``.
    """
    out: set[str] = set()
    for p in paths:
        stripped = p.rstrip("/")
        # Remove any `/{name}` placeholder segment entirely — the servers
        # implement them as `startswith` prefixes, so the spec's `{id}`
        # segment collapses the same way.
        collapsed = re.sub(r"/\{[^/]+\}", "", stripped)
        out.add(collapsed)
    return out


def test_agent_auth_spec_is_valid_openapi():
    spec = _load_spec(_AGENT_AUTH_SPEC)
    validate(spec)


def test_things_bridge_spec_is_valid_openapi():
    spec = _load_spec(_THINGS_BRIDGE_SPEC)
    validate(spec)


def test_agent_auth_routes_match_spec():
    """Every server route has a matching spec path, and vice versa.

    Failure here means either the spec drifted from the server, or the
    server added/renamed a route without updating the spec.
    """
    spec = _load_spec(_AGENT_AUTH_SPEC)
    server_paths = _normalise_parameterised(_handler_paths(agent_auth_server.AgentAuthHandler))
    spec_paths = _normalise_parameterised(_spec_paths(spec))

    missing_from_spec = server_paths - spec_paths
    stale_in_spec = spec_paths - server_paths

    assert (
        not missing_from_spec
    ), f"agent-auth routes missing from openapi/agent-auth.v1.yaml: {missing_from_spec}"
    assert (
        not stale_in_spec
    ), f"openapi/agent-auth.v1.yaml has stale entries not served by agent-auth: {stale_in_spec}"


def test_things_bridge_routes_match_spec():
    """Every server route has a matching spec path, and vice versa."""
    spec = _load_spec(_THINGS_BRIDGE_SPEC)
    server_paths = _normalise_parameterised(
        _handler_paths(things_bridge_server.ThingsBridgeHandler)
    )
    spec_paths = _normalise_parameterised(_spec_paths(spec))

    missing_from_spec = server_paths - spec_paths
    stale_in_spec = spec_paths - server_paths

    assert (
        not missing_from_spec
    ), f"things-bridge routes missing from openapi/things-bridge.v1.yaml: {missing_from_spec}"
    assert not stale_in_spec, (
        f"openapi/things-bridge.v1.yaml has stale entries not served by things-bridge: "
        f"{stale_in_spec}"
    )


@pytest.mark.parametrize(
    "spec_path",
    [
        pytest.param(_AGENT_AUTH_SPEC, id="agent-auth"),
        pytest.param(_THINGS_BRIDGE_SPEC, id="things-bridge"),
    ],
)
def test_error_codes_documented_in_error_taxonomy(spec_path):
    """Every error code used in the spec must be listed in design/error-codes.md.

    Keeps the machine-readable spec and the human-readable taxonomy doc
    (#28) from drifting apart.
    """
    spec = _load_spec(spec_path)
    error_code_schema = spec["components"]["schemas"]["ErrorCode"]
    spec_codes = set(error_code_schema["enum"])

    taxonomy_doc = (_REPO_ROOT / "design" / "error-codes.md").read_text()
    for code in spec_codes:
        assert f"`{code}`" in taxonomy_doc, (
            f"error code {code!r} from {spec_path.name} is not documented in "
            f"design/error-codes.md"
        )
