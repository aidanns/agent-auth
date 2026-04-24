# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for scripts/ci/report-scan-failure.sh.

The script chooses between ``gh issue create`` / ``comment`` / ``close``
based on whether an open issue with the dedupe label already exists. If
the branch selection regresses — e.g. it always opens a new issue on
recurring failures — the Security tab will fill up with duplicates or,
worse, recovered failures will stay open silently. The logic is small
but the blast radius of a miss is the scheduled security signal
becoming untrustworthy, so each branch is pinned down with a test.

The tests substitute ``gh`` on ``PATH`` for a tiny Python recorder that
writes every call (argv + any ``--body`` input) to a JSONL file, so the
assertions can speak in terms of "what subcommands did the script
invoke".
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ci" / "report-scan-failure.sh"


def _install_fake_gh(tmp_path: Path, list_stdout: str) -> tuple[Path, Path]:
    """Put a fake ``gh`` recorder on ``PATH``.

    ``list_stdout`` is what the fake returns for ``gh issue list ...`` —
    already post-``--jq`` processed, because reproducing gh's --jq
    evaluator in the fake would couple the test to jq semantics rather
    than the script's branch-selection logic. Tests should pass ``""``
    when the dedupe query finds no open issue and ``"<n>"`` when it
    finds issue ``<n>``. All other subcommands return empty stdout and
    exit 0. Every call is appended to ``calls.jsonl`` in the tmp bin
    dir; tests read that file to assert which subcommands the script
    invoked.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_file = bin_dir / "calls.jsonl"
    fake = bin_dir / "gh"
    fake.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json, sys
            calls_path = {str(calls_file)!r}
            list_stdout = {list_stdout!r}
            body = ""
            # Capture --body <value> so the test can assert on issue contents.
            args = sys.argv[1:]
            i = 0
            while i < len(args):
                if args[i] == "--body" and i + 1 < len(args):
                    body = args[i + 1]
                    break
                i += 1
            with open(calls_path, "a") as f:
                f.write(json.dumps({{"argv": args, "body": body}}) + "\\n")
            if len(args) >= 2 and args[0] == "issue" and args[1] == "list":
                sys.stdout.write(list_stdout)
            sys.exit(0)
            """
        )
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir, calls_file


def _run(
    tmp_path: Path,
    *args: str,
    list_stdout: str = "",
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, Any]]]:
    bin_dir, calls_file = _install_fake_gh(tmp_path, list_stdout)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    # Unset gh credentials so the fake isn't shadowed by a real auth path.
    env.pop("GITHUB_TOKEN", None)
    env.pop("GH_TOKEN", None)
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
    )
    calls: list[dict[str, Any]] = []
    if calls_file.exists():
        for line in calls_file.read_text().splitlines():
            if line.strip():
                calls.append(json.loads(line))
    return result, calls


def test_bad_argv_exits_nonzero(tmp_path):
    result, _ = _run(tmp_path, "only-one-arg")
    assert result.returncode == 2
    assert "expected 5 args" in result.stderr


def test_unknown_status_exits_nonzero(tmp_path):
    result, _ = _run(
        tmp_path,
        "bogus",
        "pip-audit-failure",
        "title",
        "abc",
        "https://example/run/1",
    )
    assert result.returncode == 2
    assert "unknown status" in result.stderr


def test_failed_without_existing_opens_new_issue(tmp_path):
    # No open issues with the label → script must create one.
    result, calls = _run(
        tmp_path,
        "failed",
        "pip-audit-failure",
        "pip-audit: scheduled scan failed",
        "deadbeef",
        "https://github.com/org/repo/actions/runs/99",
        list_stdout="",
    )
    assert result.returncode == 0, result.stderr
    subcommands = [tuple(c["argv"][:2]) for c in calls]
    assert ("issue", "list") in subcommands
    assert ("issue", "create") in subcommands
    assert ("issue", "comment") not in subcommands
    assert ("issue", "close") not in subcommands

    create_call = next(c for c in calls if c["argv"][:2] == ["issue", "create"])
    # --title / --label / --body must all be passed and carry the expected values.
    assert "--title" in create_call["argv"]
    assert "pip-audit: scheduled scan failed" in create_call["argv"]
    assert "--label" in create_call["argv"]
    assert "pip-audit-failure" in create_call["argv"]
    assert "deadbeef" in create_call["body"]
    assert "https://github.com/org/repo/actions/runs/99" in create_call["body"]


def test_failed_with_existing_comments_instead_of_duplicating(tmp_path):
    # One open issue with the label → script must comment, not create.
    result, calls = _run(
        tmp_path,
        "failed",
        "pip-audit-failure",
        "pip-audit: scheduled scan failed",
        "cafef00d",
        "https://github.com/org/repo/actions/runs/100",
        list_stdout="42",
    )
    assert result.returncode == 0, result.stderr
    subcommands = [tuple(c["argv"][:2]) for c in calls]
    assert ("issue", "create") not in subcommands
    assert ("issue", "comment") in subcommands

    comment_call = next(c for c in calls if c["argv"][:2] == ["issue", "comment"])
    # Issue number must be the existing open issue so we don't fan out.
    assert comment_call["argv"][2] == "42"
    assert "cafef00d" in comment_call["body"]
    assert "https://github.com/org/repo/actions/runs/100" in comment_call["body"]


def test_succeeded_with_existing_closes_issue(tmp_path):
    # Recovery path: open issue exists, status is "succeeded" → script
    # must post a recovery comment and then close the issue.
    result, calls = _run(
        tmp_path,
        "succeeded",
        "pip-audit-failure",
        "pip-audit: scheduled scan failed",
        "feedface",
        "https://github.com/org/repo/actions/runs/101",
        list_stdout="43",
    )
    assert result.returncode == 0, result.stderr
    subcommands = [tuple(c["argv"][:2]) for c in calls]
    assert ("issue", "comment") in subcommands
    assert ("issue", "close") in subcommands
    assert ("issue", "create") not in subcommands

    comment_call = next(c for c in calls if c["argv"][:2] == ["issue", "comment"])
    assert "recovered" in comment_call["body"].lower()
    close_call = next(c for c in calls if c["argv"][:2] == ["issue", "close"])
    assert close_call["argv"][2] == "43"


def test_succeeded_without_existing_is_noop(tmp_path):
    # No open failure issue → nothing to close. Must not open / comment
    # on / close anything.
    result, calls = _run(
        tmp_path,
        "succeeded",
        "pip-audit-failure",
        "pip-audit: scheduled scan failed",
        "beadbead",
        "https://github.com/org/repo/actions/runs/102",
        list_stdout="",
    )
    assert result.returncode == 0, result.stderr
    subcommands = [tuple(c["argv"][:2]) for c in calls]
    # Only the initial `issue list` query — no mutating calls.
    assert subcommands == [("issue", "list")]


def test_issue_list_uses_label_and_state_open(tmp_path):
    # The dedupe query must be scoped to open issues carrying the label;
    # otherwise a closed failure-issue from last week would mask a new
    # failure (or vice versa).
    _, calls = _run(
        tmp_path,
        "failed",
        "pip-audit-failure",
        "t",
        "s",
        "https://example/run",
        list_stdout="",
    )
    list_call = next(c for c in calls if c["argv"][:2] == ["issue", "list"])
    argv = list_call["argv"]
    assert "--state" in argv and argv[argv.index("--state") + 1] == "open"
    assert "--label" in argv and argv[argv.index("--label") + 1] == "pip-audit-failure"


def _check_script_shellcheck_clean():
    """The script is non-trivial; shellcheck guards against lurking bugs."""
    if shutil.which("shellcheck") is None:
        return  # best-effort — CI runs shellcheck via task lint
    result = subprocess.run(
        ["shellcheck", "--severity=warning", str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_script_is_shellcheck_clean():
    _check_script_shellcheck_clean()
