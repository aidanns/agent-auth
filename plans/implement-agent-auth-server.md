# Implementation Plan: agent-auth

## Context

The agent-auth project has a comprehensive design (in `design/DESIGN.md`) but no source code — the previous CLI skeleton was removed. The design specifies a token-based authorization system with an HTTP server, CLI, JIT approval, and field-level encryption. This plan implements the core `agent-auth` server and CLI. The example app bridge and CLI are deferred to a follow-up.

## Dependencies

Add to `pyproject.toml`:
- `keyring>=25.0` — system keyring access for signing/encryption keys
- `cryptography>=42.0` — AES-256-GCM field encryption

Dev dependencies: `pytest>=8.0`

## File Structure

```
src/agent_auth/
    __init__.py
    errors.py          # Exception hierarchy
    config.py          # Config loading (~/.config/agent-auth/config.json)
    keys.py            # Keyring integration (signing + encryption keys)
    crypto.py          # AES-256-GCM encrypt/decrypt
    tokens.py          # Token generation, HMAC signing, parsing
    scopes.py          # Scope parsing and tier resolution
    store.py           # SQLite token store with field encryption
    audit.py           # Structured JSON audit logging
    approval.py        # JIT approval manager + session grants
    plugins/
        __init__.py    # Plugin base class + loader
        terminal.py    # Default: stdin prompt plugin
    server.py          # ThreadingHTTPServer for the HTTP API
    cli.py             # argparse CLI entrypoint
tests/
    conftest.py        # Shared fixtures (mock keyring, temp db, test server)
    test_crypto.py
    test_tokens.py
    test_scopes.py
    test_store.py
    test_keys.py
    test_config.py
    test_audit.py
    test_approval.py
    test_server.py
    test_cli.py
```

## Implementation Phases

### Phase 1: Foundation modules

Build order (each depends on prior):

1. **`errors.py`** — `AgentAuthError` base, `TokenExpiredError`, `TokenInvalidError`, `TokenRevokedError`, `ScopeDeniedError`, `FamilyRevokedError`, `ApprovalDeniedError`, `KeyringError`

2. **`config.py`** — `Config` dataclass with defaults: db_path, host (127.0.0.1), port (9100), access_token_ttl (900s), refresh_token_ttl (28800s), notification_plugin ("terminal"), log_path. `load_config()` reads/creates `~/.config/agent-auth/config.json`.

3. **`keys.py`** — `KeyManager` using `keyring` library. Service name `agent-auth`, usernames `signing-key`/`encryption-key`. 32-byte keys via `os.urandom`, base64-encoded for keyring storage. `get_or_create_signing_key()`, `get_or_create_encryption_key()`.

4. **`crypto.py`** — `encrypt_field(plaintext, key) -> bytes` and `decrypt_field(ciphertext, key) -> bytes`. AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`. Format: `nonce(12) || ciphertext || tag(16)`.

5. **`tokens.py`** — `generate_token_id()` (UUID4 hex), `sign_token(token_id, prefix, signing_key)` → `aa_<id>_<hmac>`, `parse_token(raw)` → (prefix, id, signature), `verify_token(raw, signing_key)` → token_id. Use stdlib `hmac` + `hashlib.sha256`.

6. **`scopes.py`** — `parse_scope_arg("things:read=allow")` → (name, tier). `check_scope(required, granted_scopes)` → tier or raises `ScopeDeniedError`.

7. **`store.py`** — `TokenStore` class. SQLite with WAL mode, `threading.local()` for per-thread connections. Tables: `token_families`, `tokens`, `approval_grants` (per design schema). All CRUD methods, field encryption for sensitive columns (scopes, hmac_signature, scope in grants).

8. **`audit.py`** — `AuditLogger`. JSON lines to `~/.config/agent-auth/audit.log`. Events: token_created, token_refreshed, token_reissued, token_revoked, token_rotated, scopes_modified, validation_allowed, validation_prompted, validation_denied, approval_granted, approval_denied.

### Phase 2: CLI token management

**`cli.py`** — argparse with subcommands:
- `agent-auth token create --scope things:read=allow --scope things:write=prompt`
- `agent-auth token list`
- `agent-auth token modify <family-id> --add-scope ... --remove-scope ... --set-tier ...`
- `agent-auth token revoke <family-id>`
- `agent-auth token rotate <family-id>`
- `agent-auth serve` (wired up in Phase 3)

Support `--json` flag for machine-readable output.

### Phase 3: HTTP server + JIT approval

1. **`plugins/__init__.py`** — `NotificationPlugin` base class with `request_approval(scope, description, family_id) -> ApprovalResult`. `load_plugin(name, config)` using `importlib.import_module`.

2. **`plugins/terminal.py`** — `TerminalPlugin` that prints to stdout and reads approval response from stdin.

3. **`approval.py`** — `ApprovalManager` with in-memory session grants dict (thread-safe). Methods: `check_grant()`, `request_approval()`, `record_grant()`, `expire_grants()`. Also persists grants to `approval_grants` table for audit.

4. **`server.py`** — `AgentAuthServer(ThreadingHTTPServer)` + `AgentAuthHandler(BaseHTTPRequestHandler)`. Routes:
   - `POST /agent-auth/validate` — verify token, check scope, handle prompt tier
   - `POST /agent-auth/token/refresh` — refresh with reuse detection
   - `POST /agent-auth/token/reissue` — JIT-approved re-issuance
   - `GET /agent-auth/token/status` — token introspection

Wire `agent-auth serve` command to start the server.

### Phase 4: Tests

- Unit tests for all foundation modules (mock keyring, in-memory DB)
- Integration tests for CLI commands
- HTTP integration tests (start server on ephemeral port in daemon thread)
- Mock notification plugin for JIT approval tests

## Key Design Decisions

- **stdlib `http.server.ThreadingHTTPServer`** — threading needed because JIT approval blocks handler threads; no framework dependency needed for 4 endpoints
- **Per-thread SQLite connections + WAL** — allows concurrent reads during blocked JIT approval requests
- **stdlib `hmac`** for token signing, `cryptography` only for AES-256-GCM — minimize external dependency surface
- **Session grants in-memory** — design says they expire on server restart, so no persistence needed
- **JSON config file** — no extra parser dependency

## Verification

1. `pip install -e ".[dev]"` succeeds
2. `agent-auth token create --scope things:read=allow` creates a token pair
3. `agent-auth token list` shows the created family
4. `agent-auth serve` starts the HTTP server on 127.0.0.1:9100
5. `curl -X POST http://127.0.0.1:9100/agent-auth/validate -d '{"token":"aa_xxx_yyy","required_scope":"things:read"}'` returns valid response
6. Token refresh, revocation, rotation all work via CLI and HTTP
7. `pytest tests/` passes with full coverage of security-critical paths
