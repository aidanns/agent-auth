# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Command-line entry point for the PR-lint validators.

The ``pr-lint-validator`` console script dispatches into one of two
subcommands:

* ``title`` — validate a PR title (the squash-merge subject) against
  the prose-style rules in :mod:`pr_lint_validator.title`.
* ``commit-msg`` — validate the ``==COMMIT_MSG==`` block in a PR
  body against the conventions in :mod:`pr_lint_validator.commit_msg`.

Each subcommand accepts ``--self-test`` to exercise the bundled
fixtures, mirroring the original ``scripts/validate-*.py`` scripts'
self-test contract.

A future ``release-impact`` subcommand is reserved (issue #446 §
"Out of scope") for when the changelog tooling under
``scripts/changelog/`` is ready to be packaged alongside.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import commit_msg, title
from .title import Writer


def _writer() -> Writer:
    """Return a print-shaped callable suitable for ``run_self_test``.

    The two ``run_self_test`` helpers expect a callable
    ``write(msg, *, error=False) -> None``; using a closure here keeps
    the dependency-injection surface narrow and lets tests substitute
    a list-appending mock without monkey-patching ``builtins.print``.
    """

    def write(msg: str, *, error: bool = False) -> None:
        print(msg, file=sys.stderr if error else sys.stdout)

    return write


def _run_title(args: argparse.Namespace) -> int:
    if args.self_test:
        return title.run_self_test(_writer())
    if args.title is None:
        print(
            "pr-lint-validator title: title is required unless --self-test is given",
            file=sys.stderr,
        )
        return 2
    changed_files: list[str] | None = None
    if args.changed_files_from is not None:
        changed_files = title.read_changed_files(args.changed_files_from)
    repo_root = Path(args.repo_root) if args.repo_root is not None else None
    try:
        title.validate(
            args.title,
            changed_files,
            args.pr_number,
            repo_root=repo_root,
        )
    except title.TitleValidationError as err:
        print(f"pr-title: {err}", file=sys.stderr)
        return 1
    print("pr-title: subject OK")
    return 0


def _run_commit_msg(args: argparse.Namespace) -> int:
    if args.self_test:
        return commit_msg.run_self_test(_writer())
    if args.body_path is None:
        print(
            "pr-lint-validator commit-msg: body_path is required unless --self-test is given",
            file=sys.stderr,
        )
        return 2
    body = Path(args.body_path).read_text(encoding="utf-8")
    try:
        commit_msg.validate(body, title=args.title)
    except commit_msg.ValidationError as err:
        print(f"pr-lint: {err}", file=sys.stderr)
        return 1
    print("pr-lint: ==COMMIT_MSG== block OK")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-lint-validator",
        description=(
            "Validate PR titles and ==COMMIT_MSG== blocks against the "
            "prose-style rules in CONTRIBUTING.md → 'Writing release-"
            "worthy commits'. Each subcommand owns one rule family; the "
            "Palantir-style prefix allowlist itself is enforced upstream "
            "by amannn/action-semantic-pull-request."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    title_parser = sub.add_parser(
        "title",
        help="Validate a PR title (the squash-merge commit subject).",
        description=(
            "Validate the PR title (squash-merge commit subject) against "
            "CONTRIBUTING.md → 'Writing release-worthy commits' → "
            "'Subject (PR title)' prose rules."
        ),
    )
    title_parser.add_argument(
        "--title",
        default=None,
        help="The PR title to validate (the full subject including prefix).",
    )
    title_parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run the inline self-test cases instead of validating a title.",
    )
    title_parser.add_argument(
        "--changed-files-from",
        default=None,
        metavar="PATH",
        help=(
            "Path to a newline-separated list of files changed in the PR. "
            "When provided, the two-tier scope rule (#402) runs against "
            "the diff."
        ),
    )
    title_parser.add_argument(
        "--pr-number",
        default=None,
        type=int,
        metavar="N",
        help=(
            "PR number this title belongs to. When provided, the 72-char "
            "length cap is applied to the projected squash-merge subject "
            "(un-suffixed title + ` (#<n>)`). See #399."
        ),
    )
    title_parser.add_argument(
        "--repo-root",
        default=None,
        metavar="PATH",
        help=(
            "Repository root used for `packages/<name>/` discovery. "
            "Defaults to the current working directory; override when "
            "the validator is invoked from a non-standard CWD."
        ),
    )

    commit_msg_parser = sub.add_parser(
        "commit-msg",
        help="Validate the ==COMMIT_MSG== block of a PR body.",
        description=(
            "Validate the ==COMMIT_MSG== block in a PR body against "
            "ADR 0037 and CONTRIBUTING.md."
        ),
    )
    commit_msg_parser.add_argument(
        "body_path",
        nargs="?",
        default=None,
        help="Path to a file containing the PR body markdown.",
    )
    commit_msg_parser.add_argument(
        "--title",
        default=None,
        help=(
            "PR title (the squash-merge subject). When provided, the "
            "first body line is also checked for duplication of the "
            "title."
        ),
    )
    commit_msg_parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run the inline self-test cases instead of validating a body file.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.command == "title":
        return _run_title(args)
    if args.command == "commit-msg":
        return _run_commit_msg(args)
    # argparse's required=True on the subparsers above means this
    # branch is only reachable if a future change adds a subcommand
    # without wiring its dispatch — fail loud rather than silently
    # exit 0 on an unrecognised command.
    parser.error(f"unrecognised command: {args.command!r}")
    return 2  # pragma: no cover  -- parser.error raises SystemExit


if __name__ == "__main__":
    sys.exit(main())
