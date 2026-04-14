# agent-auth

| Parent | Name | Type | Description | Functions |
|--------|------|------|-------------|-----------|
|  | agent-auth | System | Token-based authorization system for gating AI agent access to host applications. |  |
| agent-auth | agent-auth | Component | HTTP server and CLI for token lifecycle management, validation, and JIT approval running on the host. |  |
| agent-auth | agent-auth-server | Configuration Item | HTTP server and CLI service providing token lifecycle management, scope-based authorization, JIT approval, and audit logging. | Create Token Pair, Refresh Token Pair, Revoke Token Family, Modify Token Family Scopes, Rotate Token Family, Introspect Token, Detect Refresh Token Reuse, Verify Token Signature, Check Token Expiry, Check Scope Authorization, Resolve Access Tier, Request Approval, Load Notification Plugin, Record Approval Grant, Check Existing Grant, Expire Grants, Encrypt Field, Decrypt Field, Serve Validate Endpoint, Serve Refresh Endpoint, Serve Reissue Endpoint, Serve Status Endpoint, Log Token Operation, Log Authorization Decision, Handle Token Create Command, Handle Token List Command, Handle Token Modify Command, Handle Token Revoke Command, Handle Token Rotate Command, Handle Serve Command |
| agent-auth | SQLite | Configuration Item | Third-party embedded relational database providing persistent storage for token families and tokens. | Store Token Family, Store Token, Mark Token Consumed, Mark Family Revoked, Query Tokens |
| agent-auth | keyring | Configuration Item | Third-party Python library providing a unified API for accessing system keyring backends to store the HMAC signing key and AES-256-GCM encryption key. | Generate Signing Key, Load Signing Key, Generate Encryption Key, Load Encryption Key |
| agent-auth | macOS Keychain | Configuration Item | Operating system keyring backend used to securely store the HMAC signing key and database encryption key on macOS. |  |
| agent-auth | gnome-keyring | Configuration Item | Operating system keyring backend (via libsecret/D-Bus Secret Service) used to securely store the HMAC signing key and database encryption key on Linux. |  |
| agent-auth | example-app-bridge | Component | HTTP server running on the host that proxies operations to an external system, delegating authorization to agent-auth. |  |
| example-app-bridge | example-app-bridge | Configuration Item | HTTP server service that maps endpoints to external system interactions, delegating token validation and JIT approval to agent-auth. | Delegate Token Validation, Execute External System Interaction, Serve Bridge HTTP API |
| agent-auth | example-app-cli | Component | Thin CLI client for interacting with an external system via its bridge, runnable from host or devcontainer. |  |
| example-app-cli | example-app-cli | Configuration Item | CLI client service that sends authenticated HTTP requests to the app bridge, with automatic token refresh and re-issuance on 401 responses. | Send Bridge Request, Auto Refresh Token, Store CLI Credentials, Handle App Commands, Display Results |
| example-app-cli | keyring | Configuration Item | Third-party Python library providing a unified API for accessing system keyring backends to store CLI credentials. |  |
| example-app-cli | macOS Keychain | Configuration Item | Operating system keyring backend used to securely store CLI credentials on macOS. |  |
| example-app-cli | gnome-keyring | Configuration Item | Operating system keyring backend (via libsecret/D-Bus Secret Service) used to securely store CLI credentials on Linux. |  |
