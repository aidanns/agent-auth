#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT
#
# Extract the contents between the `==COMMIT_MSG==` markers of a PR
# body and write them to stdout. Used by the merge-bot workflow
# (`.github/workflows/merge-bot.yml`) to compute the `commit_message`
# for the `PUT /repos/.../pulls/{n}/merge` API call.
#
# Reuses `scripts/validate-commit-msg-block.py`'s `extract_block`
# parser so the extractor and the validator agree on what
# constitutes "the block content" — there is no second regex.
#
# Exits 0 with the block content on stdout on success. Exits 1 with a
# human-readable error on stderr if the block is missing or malformed
# (callers should treat this as "do not merge"). The error string is
# safe to surface verbatim in a PR comment because both the validator
# and this script come from the base ref of the PR (the workflow
# checks out the base ref) — a contributor cannot influence the
# wording from inside a PR.
#
# CLI surface:
#   python3 scripts/extract-commit-msg-block.py <body-file>
#
# Why a separate CLI: the validator runs the full lint and exits 1 on
# any rule violation. The extractor exits 0 with the block content on
# stdout for the bot to pipe into the merge API. Both share the same
# parser; only the calling convention differs.

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_validator_module() -> ModuleType:
    """Import the validator script as a module.

    The validator script is named `validate-commit-msg-block.py` (with
    dashes, the project's script convention), which is not a legal
    Python module name for `import`. Load it via `importlib.util`
    against its file path so the dashes don't matter.
    """
    here = Path(__file__).resolve().parent
    target = here / "validate-commit-msg-block.py"
    spec = importlib.util.spec_from_file_location("validate_commit_msg_block", target)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import validator from {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_VALIDATOR = _load_validator_module()
extract_block = _VALIDATOR.extract_block
ValidationError = _VALIDATOR.ValidationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract the ==COMMIT_MSG== block content from a PR body "
            "for the merge bot. Writes the block content to stdout."
        )
    )
    parser.add_argument(
        "body_path",
        type=Path,
        help="Path to a file containing the PR body markdown.",
    )
    args = parser.parse_args(argv)
    body = args.body_path.read_text(encoding="utf-8")
    try:
        block = extract_block(body)
    except ValidationError as err:
        print(f"extract-commit-msg-block: {err}", file=sys.stderr)
        return 1
    # Print without an extra trailing newline — the block content is
    # what the merge bot pastes verbatim into commit_message, and a
    # spurious extra newline would shift the commit body shape.
    sys.stdout.write(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
