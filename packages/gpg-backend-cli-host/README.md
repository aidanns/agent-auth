<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# gpg-backend-cli-host

Host-side GPG backend invoked as a subprocess by
[`gpg-bridge`](../gpg-bridge/). Wraps the real host `gpg` binary and
emits a JSON envelope on stdout that the bridge parses; conceptually
the GPG-side analogue of `things-client-cli-applescript`.

## Public surface

### CLI — `gpg-backend-cli-host`

Invoked by `gpg-bridge` per request; not intended to be run
interactively. Each invocation accepts a single sign or verify
operation parsed out of argv, shells to the host `gpg`, and prints a
JSON envelope describing the result (or a structured error).

## Platform requirements

- A working host `gpg` install with the signing key loaded into the
  keyring being used.
- The user's GPG agent is reused; no key material is stored in this
  package.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/gpg-backend-cli-host/install.sh | bash
```

Or run from a development checkout via
`task gpg-backend-host -- <args...>`.

## Related design

- ADR [0033 — gpg-bridge / gpg-cli split](../../design/decisions/0033-gpg-bridge-cli-split.md)
