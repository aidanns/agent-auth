<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# gpg-cli

Devcontainer-side `gpg` replacement. Wired into git via
`git config gpg.program gpg-cli`, it accepts git's standard sign /
verify argv and forwards each request to a host-side
[`gpg-bridge`](../gpg-bridge/) over HTTPS using a bearer token issued
by [`agent-auth`](../agent-auth/) for the `gpg:sign` scope.

The devcontainer never sees the signing key or the host gpg keyring —
the bridge brokers the call to the host `gpg` and returns the
detached signature.

## Public surface

### CLI — `gpg-cli`

The CLI is a drop-in replacement for `gpg.program`; it implements
exactly the subset of git's gpg invocation surface needed for commit
and tag signing/verification (`--sign`, `--verify`,
`--list-keys`, ...).

## Configuration

`~/.config/gpg-cli/config.yaml` configures the bridge URL and TLS
trust material. Token credentials are stored in the system keyring
(or, when no backend is available, a `0600` YAML fallback under
`~/.config/gpg-cli/`).

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/aidanns/agent-auth/main/packages/gpg-cli/install.sh | bash
```

Or run from a development checkout via `task gpg-cli -- <args...>`.
After install, point git at it once:

```bash
git config --global gpg.program gpg-cli
```

## Related design

- ADR [0033 — gpg-bridge / gpg-cli split](../../design/decisions/0033-gpg-bridge-cli-split.md)
