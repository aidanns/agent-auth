<!--
SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith

SPDX-License-Identifier: MIT
-->

# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — domain glossary.
- **`design/decisions/`** — ADRs that touch the area you're about to work in. ADRs live at `design/decisions/`, not the default `docs/adr/`.
- **`design/`** — broader documentation: `DESIGN.md` (architecture), `THINGS.md` (Things 3 integration), `functional_decomposition.*`, `product_breakdown.*`, and assurance docs (`ASSURANCE.md`, `ASVS.md`, `SSDF.md`, `SELF_ASSESSMENT.md`). Consult when the topic is broader than a single ADR.

The canonical layout of `design/` is documented in `.claude/instructions/design.md`.

If `CONTEXT.md` doesn't exist, **proceed silently**. Don't flag its absence; don't suggest creating it upfront. The producer skill (`/grill-with-docs`) populates it lazily when terms get resolved.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (SQLite field-level encryption) — but worth reopening because…_
