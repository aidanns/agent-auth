# Security

## Trust Boundaries

agent-auth runs as a local daemon on the host machine. It binds to `127.0.0.1` by default, restricting all network access to the local host. No credential material is transmitted over the network except within the localhost loopback interface.

There are two trust zones:

- **Host process trust**: any process on the host that can reach `127.0.0.1:9100` can call the agent-auth HTTP API. This is equivalent to having local shell access.
- **Devcontainer trust**: the host forwards port 9100 to devcontainers via Docker networking (`host.docker.internal`). Code running in the devcontainer has the same API access as host processes.

## Token Management Endpoints

The management endpoints (`POST /agent-auth/token/create`, `GET /agent-auth/token/list`, `POST /agent-auth/token/modify`, `POST /agent-auth/token/revoke`, `POST /agent-auth/token/rotate`) require `Authorization: Bearer <token>` where the token's family carries `agent-auth:manage=allow` in its scopes.

On first startup the server creates this management token family directly via the store and stores the refresh token in the OS keyring. Operators retrieve it with `agent-auth management-token show` and exchange it for an access token via `POST /agent-auth/token/refresh`. External clients must refresh before each management session (access tokens expire after 900 s by default).

The `agent-auth:manage` scope is reserved. The management token family is excluded from `GET /token/list` responses. If the management family is rotated or revoked, the server recreates it automatically on the next restart. See `design/decisions/0006-management-endpoint-no-auth.md` for the full rationale.

## Cryptographic Key Handling

- **Signing key**: HMAC-SHA256 key stored in the system keyring (macOS Keychain or libsecret). Generated on first startup. All token signatures are verified against this key; a compromised key allows token forgery.
- **Encryption key**: AES-256-GCM key stored in the system keyring. Used for field-level encryption of sensitive database columns (token HMAC signatures, scope definitions). A compromised encryption key exposes scope definitions and allows offline brute-force of token IDs, but does not allow token forgery without also compromising the signing key.

**Key loss**: if the signing key is lost, all issued tokens become unverifiable. Recovery requires revoking all token families (via the database) and issuing new credentials. If the encryption key is lost, the database is unreadable; the SQLite file must be deleted and all token families recreated. No automatic key backup or escrow is provided.

## Token Revocation

Revocation is propagated immediately: any call to `/agent-auth/validate` checks the token family's revocation flag in the database before returning a result. There is no TTL-based propagation delay.

Refresh token reuse triggers automatic family revocation: if a consumed refresh token is presented again, agent-auth revokes the entire token family (all access and refresh tokens) and returns an error. This detects replay attacks by stolen refresh tokens.

## Audit Surface

All token operations and authorization decisions are written to the audit log at `~/.local/state/agent-auth/audit.log`. The log records:

- Token creation, modification, revocation, rotation, and re-issuance
- Every `/validate` call with outcome (allowed / denied), scope, and tier
- JIT approval requests, grants, and denials

The audit log is append-only. It is not encrypted. Operators who need tamper-evident audit trails should ship the log to an external SIEM.

## Vulnerability Reporting

Report security vulnerabilities by email to `aidanns@gmail.com`. Include a description of the issue, reproduction steps, and potential impact. Do not file public GitHub issues for security vulnerabilities until a fix is available.
