# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for the ``pr-lint-validator`` CLI dispatch.

The CLI is the contract surface that #477 will consume from the
released wheel. The tests below exercise each subcommand's argv
shape, focusing on the exit-code contract (0 / 1 / 2) and the
stderr message family — those are what a workflow ``run:`` block
reads.
"""

from __future__ import annotations

import pytest

from pr_lint_validator import cli


def test_title_subcommand_passing(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["title", "--title", "chore(ci): tweak something", "--self-test"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "self-test cases passed" in out


def test_title_subcommand_validates_passing_input(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(
        [
            "title",
            "--title",
            "chore(ci): consolidate release workflows into release-bot.yml",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "subject OK" in out


def test_title_subcommand_rejects_failing_input(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["title", "--title", "fix: drop the trailing period."])
    assert rc == 1
    err = capsys.readouterr().err
    assert "trailing period" in err


def test_title_subcommand_missing_title_argv(capsys: pytest.CaptureFixture[str]) -> None:
    """No ``--title`` and no ``--self-test`` is a 2 (usage error).

    The original ``scripts/validate-pr-title.py`` returned via
    ``parser.error`` (exit 2). The CLI mirrors that exit code so
    pr-lint.yml can distinguish "validator misconfigured" (2) from
    "validation failed" (1) once #477 lands.
    """
    rc = cli.main(["title"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "title is required" in err


def test_commit_msg_subcommand_self_test(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["commit-msg", "--self-test"])
    assert rc == 0


def test_commit_msg_subcommand_validates_passing_body(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = tmp_path / "body.md"
    body.write_text(
        "==COMMIT_MSG==\n"
        "Wire the foo into the bar.\n\n"
        "Some why-this-change rationale.\n\n"
        "Closes #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n",
        encoding="utf-8",
    )
    rc = cli.main(["commit-msg", str(body)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "block OK" in out


def test_commit_msg_subcommand_rejects_leading_subject_line(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A leading CC-shaped first line in the block is rejected (rule 8).

    Post-#478 the block is body + trailers only — the squash commit's
    subject is rendered from the PR title, so a CC-shaped first line
    in the block would render twice on ``main``. The CLI's
    ``commit-msg`` subcommand must surface this as exit code 1 with a
    fix-it pointer mentioning the body-only convention.
    """
    body = tmp_path / "body.md"
    body.write_text(
        "==COMMIT_MSG==\n"
        "improvement(ci): wire the foo into the bar\n\n"
        "Body paragraph.\n\n"
        "Closes #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n",
        encoding="utf-8",
    )
    rc = cli.main(["commit-msg", str(body)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "leading subject line" in err


def test_commit_msg_subcommand_rejects_missing_signoff(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = tmp_path / "body.md"
    body.write_text(
        "==COMMIT_MSG==\n"
        "Subject only.\n\n"
        "Body paragraph.\n\n"
        "Closes #1\n"
        "==COMMIT_MSG==\n",
        encoding="utf-8",
    )
    rc = cli.main(["commit-msg", str(body)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Signed-off-by" in err


def test_commit_msg_subcommand_missing_body_argv(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["commit-msg"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "body_path is required" in err


def test_top_level_help_lists_subcommands() -> None:
    """Both subcommands appear in ``--help`` so a contributor can discover them."""
    parser = cli._build_parser()
    help_text = parser.format_help()
    assert "title" in help_text
    assert "commit-msg" in help_text


def test_no_subcommand_is_argparse_error() -> None:
    """Bare ``pr-lint-validator`` exits via argparse's required-subparser error."""
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    # argparse uses exit code 2 for usage errors.
    assert exc.value.code == 2
