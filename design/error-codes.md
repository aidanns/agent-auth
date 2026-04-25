<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Error Code Taxonomy

This document is part of the project's **public API surface**. Error codes,
HTTP statuses, and their meanings are stable within a major version. Adding a
new code is non-breaking; removing or renaming one requires a major-version
bump (see the versioning policy in `DESIGN.md`).

All error responses use `Content-Type: application/json` and a body of the
form `{"error": "<code>"}`. Validation endpoint responses additionally include
a `"valid": false` field.

## agent-auth server (`/agent-auth/v1/...`)

### `POST /agent-auth/v1/validate`

| Error code          | HTTP status | Meaning                                                                                                       |
| ------------------- | ----------- | ------------------------------------------------------------------------------------------------------------- |
| `malformed_request` | 400         | Request body is not valid JSON or exceeds the size limit.                                                     |
| `invalid_token`     | 401         | Token is missing, malformed, has an invalid signature, is not an access token, or was not found in the store. |
| `token_expired`     | 401         | Access token has passed its TTL.                                                                              |
| `token_revoked`     | 401         | Token family has been revoked (e.g. after normal revocation).                                                 |
| `scope_denied`      | 403         | The required scope is not granted, or a JIT approval prompt was denied.                                       |

### `POST /agent-auth/v1/token/refresh`

| Error code                     | HTTP status | Meaning                                                                                                  |
| ------------------------------ | ----------- | -------------------------------------------------------------------------------------------------------- |
| `malformed_request`            | 400         | Request body is not valid JSON or exceeds the size limit.                                                |
| `invalid_token`                | 401         | Refresh token is missing, malformed, has an invalid signature, is not a refresh token, or was not found. |
| `family_revoked`               | 401         | Token family has been revoked.                                                                           |
| `refresh_token_expired`        | 401         | Refresh token has passed its TTL.                                                                        |
| `refresh_token_reuse_detected` | 401         | The refresh token has already been consumed. The family is immediately revoked as a security response.   |

### `POST /agent-auth/v1/token/reissue`

| Error code                  | HTTP status | Meaning                                                                                                                 |
| --------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------- |
| `malformed_request`         | 400         | Request body is not valid JSON or exceeds the size limit.                                                               |
| `refresh_token_still_valid` | 400         | Reissue is only available when the refresh token has expired; the current refresh token is still valid and un-consumed. |
| `family_revoked`            | 401         | Token family has been revoked or no valid refresh token exists for the family.                                          |
| `reissue_denied`            | 403         | JIT approval for reissue was denied by the host.                                                                        |

### `GET /agent-auth/v1/token/status`

No error codes — this endpoint does not return 4xx responses beyond the
generic server-wide codes below.

### Management endpoints (`/agent-auth/v1/token/{create,modify,revoke,rotate}`, `/agent-auth/v1/token/list`)

All management endpoints share the same authorization error set, driven by
`_require_management_auth`:

| Error code      | HTTP status | Meaning                                                |
| --------------- | ----------- | ------------------------------------------------------ |
| `missing_token` | 401         | No `Authorization: Bearer` header present.             |
| `invalid_token` | 401         | Token is malformed, not an access token, or not found. |
| `token_expired` | 401         | Access token has passed its TTL.                       |
| `scope_denied`  | 403         | Token does not have the `agent-auth:manage` scope.     |

Per-endpoint error codes:

| Endpoint             | Error code          | HTTP status | Meaning                                                                                  |
| -------------------- | ------------------- | ----------- | ---------------------------------------------------------------------------------------- |
| `POST /token/create` | `malformed_request` | 400         | Request body is not valid JSON or exceeds the size limit.                                |
| `POST /token/create` | `no_scopes`         | 400         | `scopes` is missing, empty, or not a mapping.                                            |
| `POST /token/create` | `invalid_tier`      | 400         | A scope tier is not one of `allow`, `prompt`, `deny`. Detail lists the offending scopes. |
| `POST /token/modify` | `malformed_request` | 400         | Request body is malformed or `family_id` is missing.                                     |
| `POST /token/modify` | `no_modifications`  | 400         | No `add_scopes`, `remove_scopes`, or `set_tiers` provided.                               |
| `POST /token/modify` | `invalid_tier`      | 400         | A scope tier is not one of `allow`, `prompt`, `deny`. Detail lists the offending scopes. |
| `POST /token/modify` | `family_not_found`  | 404         | No token family exists for the given `family_id`.                                        |
| `POST /token/modify` | `family_revoked`    | 409         | Token family has been revoked; cannot modify scopes.                                     |
| `POST /token/revoke` | `malformed_request` | 400         | Request body is malformed or `family_id` is missing.                                     |
| `POST /token/revoke` | `family_not_found`  | 404         | No token family exists for the given `family_id`.                                        |
| `POST /token/rotate` | `malformed_request` | 400         | Request body is malformed or `family_id` is missing.                                     |
| `POST /token/rotate` | `family_not_found`  | 404         | No token family exists for the given `family_id`.                                        |
| `POST /token/rotate` | `family_revoked`    | 409         | Token family has been revoked; cannot rotate.                                            |

### `GET /agent-auth/health` *(unversioned)*

| Error code      | HTTP status | Meaning                                            |
| --------------- | ----------- | -------------------------------------------------- |
| `missing_token` | 401         | No `Authorization: Bearer` header present.         |
| `invalid_token` | 401         | Token is malformed or not an access token.         |
| `token_expired` | 401         | Access token has passed its TTL.                   |
| `scope_denied`  | 403         | Token does not have the `agent-auth:health` scope. |

The health endpoint is unversioned by convention (see versioning policy in
`DESIGN.md`). A 503 body of `{"status": "unhealthy"}` (not an error code)
indicates the backing store is unreachable.

### `GET /agent-auth/metrics` *(unversioned)*

| Error code      | HTTP status | Meaning                                             |
| --------------- | ----------- | --------------------------------------------------- |
| `missing_token` | 401         | No `Authorization: Bearer` header present.          |
| `invalid_token` | 401         | Token is malformed or not an access token.          |
| `token_expired` | 401         | Access token has passed its TTL.                    |
| `scope_denied`  | 403         | Token does not have the `agent-auth:metrics` scope. |

Successful scrapes return 200 with a Prometheus text exposition body
(`Content-Type: text/plain; version=0.0.4`).

### Server-wide codes (any endpoint)

| Error code     | HTTP status | Meaning                                                                                                                              |
| -------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `not_found`    | 404         | Path does not match any registered endpoint.                                                                                         |
| `rate_limited` | 429         | The token family is over its rate-limit budget (see ADR 0027). Retry after the integer seconds in the `Retry-After` response header. |

______________________________________________________________________

## things-bridge server (`/things-bridge/v1/...`)

### `GET /things-bridge/v1/todos`, `/things-bridge/v1/todos/{id}`, `/things-bridge/v1/projects`, `/things-bridge/v1/projects/{id}`, `/things-bridge/v1/areas`, `/things-bridge/v1/areas/{id}`

All data endpoints share the same authorization and Things-layer error codes:

**Authorization errors (from agent-auth delegation):**

| Error code          | HTTP status | Meaning                                                                  |
| ------------------- | ----------- | ------------------------------------------------------------------------ |
| `unauthorized`      | 401         | No bearer token, or the token is invalid/missing.                        |
| `token_expired`     | 401         | Access token has passed its TTL (delegated from agent-auth).             |
| `scope_denied`      | 403         | Token does not have the `things:read` scope (delegated from agent-auth). |
| `authz_unavailable` | 502         | The agent-auth service is unreachable.                                   |

**Things-layer errors:**

| Error code                 | HTTP status | Meaning                                                                                        |
| -------------------------- | ----------- | ---------------------------------------------------------------------------------------------- |
| `not_found`                | 404         | The requested resource id does not exist in Things. Also returned for malformed path segments. |
| `things_permission_denied` | 503         | macOS automation permission for Things was denied.                                             |
| `things_unavailable`       | 502         | The Things subprocess failed for an unclassified reason.                                       |

### `GET /things-bridge/health` *(unversioned)*

| Error code          | HTTP status | Meaning                                               |
| ------------------- | ----------- | ----------------------------------------------------- |
| `unauthorized`      | 401         | No bearer token present.                              |
| `token_expired`     | 401         | Access token has passed its TTL.                      |
| `scope_denied`      | 403         | Token does not have the `things-bridge:health` scope. |
| `authz_unavailable` | 502         | The agent-auth service is unreachable.                |

A 503 body of `{"status": "unhealthy"}` (not an error code) indicates a
critical downstream dependency is unavailable — currently that means the
configured `things_client_command` executable cannot be resolved on PATH.
agent-auth reachability surfaces as a 502 `authz_unavailable` from the
probe-authorisation call itself rather than being re-checked here.

### `GET /things-bridge/metrics` *(unversioned)*

| Error code          | HTTP status | Meaning                                                |
| ------------------- | ----------- | ------------------------------------------------------ |
| `unauthorized`      | 401         | No bearer token present.                               |
| `token_expired`     | 401         | Access token has passed its TTL.                       |
| `scope_denied`      | 403         | Token does not have the `things-bridge:metrics` scope. |
| `authz_unavailable` | 502         | The agent-auth service is unreachable.                 |

Successful scrapes return 200 with a Prometheus text exposition body
(`Content-Type: text/plain; version=0.0.4`).

### Server-wide codes (any endpoint)

| Error code           | HTTP status | Meaning                                                                                                                                                                        |
| -------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `not_found`          | 404         | Path does not match any registered endpoint.                                                                                                                                   |
| `method_not_allowed` | 405         | A non-GET method was used on a read-only endpoint.                                                                                                                             |
| `rate_limited`       | 429         | Agent-auth refused the delegated `/validate` call for the bearer token's family (see ADR 0027). The bridge forwards the upstream `Retry-After`; retry after that many seconds. |

______________________________________________________________________

## gpg-bridge server (`/gpg-bridge/v1/...`)

See `design/decisions/0033-gpg-bridge-cli-split.md` for the bridge / backend
architecture. Token validation is delegated to agent-auth; sign / verify
require the `gpg:sign` scope, the probe endpoints carry their own scopes
(`gpg-bridge:health`, `gpg-bridge:metrics`).

### `POST /gpg-bridge/v1/sign`, `POST /gpg-bridge/v1/verify`

**Request-shape errors:**

| Error code               | HTTP status | Meaning                                                                                                                                        |
| ------------------------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `length_required`        | 411         | Request did not include a `Content-Length` header.                                                                                             |
| `invalid_content_length` | 400         | `Content-Length` header is not a non-negative integer.                                                                                         |
| `payload_too_large`      | 413         | Request body exceeds the bridge's configured `max_request_bytes` limit.                                                                        |
| `invalid_json`           | 400         | Request body is not a JSON object.                                                                                                             |
| `invalid_request`        | 400         | Request body parsed as JSON but failed schema validation (missing required fields, wrong types, invalid base64, unknown `keyid_format`, etc.). |

**Authorization errors (from agent-auth delegation):**

| Error code          | HTTP status | Meaning                                                                                         |
| ------------------- | ----------- | ----------------------------------------------------------------------------------------------- |
| `unauthorized`      | 401         | No bearer token, or the token is invalid/missing.                                               |
| `token_expired`     | 401         | Access token has passed its TTL (delegated from agent-auth).                                    |
| `scope_denied`      | 403         | Token does not have the `gpg:sign` scope (delegated from agent-auth).                           |
| `key_not_allowed`   | 403         | Requested `local_user` is not in the bridge's `allowed_signing_keys` allowlist (sign endpoint). |
| `authz_unavailable` | 502         | The agent-auth service is unreachable.                                                          |

**GPG-layer errors:**

| Error code                    | HTTP status | Meaning                                                                                                                                                                                                                                                                                                                                                                                        |
| ----------------------------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `no_such_key`                 | 404         | The requested signing key is not present in the host keyring (sign endpoint).                                                                                                                                                                                                                                                                                                                  |
| `bad_signature`               | 400         | A verify request found the signature invalid (verify endpoint).                                                                                                                                                                                                                                                                                                                                |
| `gpg_permission_denied`       | 503         | The host gpg could not access the keyring (e.g. agent down, keyring locked).                                                                                                                                                                                                                                                                                                                   |
| `signing_backend_unavailable` | 503         | The signing backend cannot complete the request right now. Typical cause: the host gpg subprocess hung past the bridge's deadline, almost always because `gpg-agent` is blocked waiting on a non-existent pinentry. Response body's `detail` field points at `~/.gnupg/gpg-agent.conf` (`allow-loopback-pinentry` + a primed passphrase cache) and `docs/operations/gpg-bridge-host-setup.md`. |
| `unsupported_operation`       | 400         | The configured backend does not implement the requested operation.                                                                                                                                                                                                                                                                                                                             |
| `gpg_unavailable`             | 502         | The gpg backend subprocess failed for an unclassified reason.                                                                                                                                                                                                                                                                                                                                  |

### `GET /gpg-bridge/health` *(unversioned)*

| Error code          | HTTP status | Meaning                                            |
| ------------------- | ----------- | -------------------------------------------------- |
| `unauthorized`      | 401         | No bearer token present, or the token is invalid.  |
| `token_expired`     | 401         | Access token has passed its TTL.                   |
| `scope_denied`      | 403         | Token does not have the `gpg-bridge:health` scope. |
| `authz_unavailable` | 502         | The agent-auth service is unreachable.             |

A 503 body of `{"status": "unhealthy"}` (not an error code) indicates a
critical downstream dependency is unavailable — currently that means the
configured `gpg_command` executable cannot be resolved on PATH.

### `GET /gpg-bridge/metrics` *(unversioned)*

| Error code          | HTTP status | Meaning                                             |
| ------------------- | ----------- | --------------------------------------------------- |
| `unauthorized`      | 401         | No bearer token present, or the token is invalid.   |
| `token_expired`     | 401         | Access token has passed its TTL.                    |
| `scope_denied`      | 403         | Token does not have the `gpg-bridge:metrics` scope. |
| `authz_unavailable` | 502         | The agent-auth service is unreachable.              |

Successful scrapes return 200 with a Prometheus text exposition body
(`Content-Type: text/plain; version=0.0.4`).

### Server-wide codes (any endpoint)

| Error code           | HTTP status | Meaning                                                                                                                                                                        |
| -------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `not_found`          | 404         | Path does not match any registered endpoint.                                                                                                                                   |
| `method_not_allowed` | 405         | An unsupported HTTP method was used (only `GET` and `POST` are accepted).                                                                                                      |
| `rate_limited`       | 429         | Agent-auth refused the delegated `/validate` call for the bearer token's family (see ADR 0027). The bridge forwards the upstream `Retry-After`; retry after that many seconds. |
