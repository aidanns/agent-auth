<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Release and Project Hygiene

Standard files, processes, and metadata every project should maintain.

## Required project files

- **`CONTRIBUTING.md`** — document dev setup, testing, release cutting, and
  signing procedures. Even for personal projects, this saves time for
  future-you and for Claude.
- **`CHANGELOG.md`** — track user-visible changes using Keep-a-Changelog
  formatting paired with semantic versioning. Require updates on every
  user-facing PR.
- **`LICENSE.md`** — add a license file (default: MIT) and link to it from
  the README's "License" section.
- **`SECURITY.md`** — document trust boundaries, threat model, key handling,
  revocation flow, audit surface, and vulnerability reporting.

## Versioning

- **Version string from VCS tags** — derive the version from git tags at
  build time and read it back at runtime. Never hard-code version strings.

## Release process

- **Release instructions in `CONTRIBUTING.md`** — document how to cut a
  release (version bump, tag, GitHub release, publish) in the contributing
  guide.
- **Release task** — automate version bumping, tagging, and posting the
  GitHub release as a task in the project's task runner.
- **Per-service `install.sh`** — for user-facing binaries/daemons in a
  monorepo, add a dedicated install script under each `packages/<svc>/`
  so `curl -fsSL <raw-url>/packages/<svc>/install.sh | bash` installs
  only that service's dependency closure (see #105). The root must not
  carry a meta-installer — a single top-level `install.sh` re-couples
  services at the install layer and is rejected by
  `scripts/verify-standards.sh`. Document each per-service idiom under
  an "Installation" section in the root README.

## Commit and PR conventions

- **Conventional commits in project CLAUDE.md** — the project-level CLAUDE.md
  must state the commit-message convention so all contributors (human or
  Claude) see it without needing the user's global config.

## Repository metadata

- **GitHub repo "About"** — populate the repository description and topics
  with a one-line description matching the README summary. Homepage is
  optional and not gated by `verify-standards.sh`.

## Structured output schemas

- **Log and audit schemas are public APIs** — structured log schemas and
  audit-log schemas consumed by downstream systems (SIEM, compliance,
  forensics, monitoring) are load-bearing. Treat changes to field names or
  types as breaking changes and pin schemas with tests. This applies to
  application logs, audit logs, and metrics output alike.
