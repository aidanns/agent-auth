<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# OpenAPI specs

Machine-readable descriptions of the HTTP surfaces defined in
[`design/DESIGN.md`](../design/DESIGN.md) and pinned against the
running servers by `tests/test_openapi_spec.py`.

| File                                               | Surface                                                             |
| -------------------------------------------------- | ------------------------------------------------------------------- |
| [`agent-auth.v1.yaml`](./agent-auth.v1.yaml)       | `agent-auth` — `/agent-auth/v1/*` and `/agent-auth/health`          |
| [`things-bridge.v1.yaml`](./things-bridge.v1.yaml) | `things-bridge` — `/things-bridge/v1/*` and `/things-bridge/health` |

## Stability

Both specs carry a `v1` URL prefix. Breaking changes (field
removal, rename, re-typing, status-code repurposing, endpoint
removal) bump the URL to `/v2/` and are announced in
[`CHANGELOG.md`](../CHANGELOG.md). Additive changes (new optional
request fields, new response fields, new endpoints, new error
codes) stay on the current version — see
[`design/DESIGN.md`](../design/DESIGN.md) "API Versioning Policy"
for the full definition and deprecation window.

Error codes referenced from the specs are enumerated in
[`design/error-codes.md`](../design/error-codes.md), which
also documents their HTTP status and stability guarantee.

## Regression checks

- `tests/test_openapi_spec.py` reflects on each server's request
  handler, extracts every registered route, and asserts parity
  with the spec (the spec cannot list operations the server does
  not serve, and the server cannot register routes the spec does
  not document).
- `openapi-spec-validator` is run against each file in the same
  test so any edit that makes the spec invalid fails CI.
- `scripts/verify-standards.sh` asserts both spec files exist and
  that the contract test references both filenames.

## Rendering

GitHub renders the YAML directly. For a richer view, point
[Swagger Editor](https://editor.swagger.io/) or a local
[Redocly CLI](https://redocly.com/docs/cli/) at the raw file.
