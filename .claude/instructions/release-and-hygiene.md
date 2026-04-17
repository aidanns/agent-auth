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
- **`SECURITY.md`** — for network-facing or credential-handling projects,
  document trust boundaries, threat model, key handling, revocation flow,
  audit surface, and vulnerability reporting.

## Release process

- **Release instructions in README** — add a "Releasing" section documenting
  how to cut a release (version bump, tag, GitHub release, publish).
- **`scripts/release.sh`** — automate version bumping, tagging, and posting
  the GitHub release in a repeatable script.
- **`install.sh`** — for user-facing binaries/daemons, add an install script
  at the repo root and document the `curl -fsSL <url> | bash` idiom in the
  README.

## Commit and PR conventions

- **Conventional commits in project CLAUDE.md** — the project-level CLAUDE.md
  must state the commit-message convention so all contributors (human or
  Claude) see it without needing the user's global config.

## Repository metadata

- **GitHub repo "About"** — populate the repository description, homepage,
  and topics with a one-line description matching the README summary.
