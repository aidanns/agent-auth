# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for scripts/parse-close-keywords.py.

The parser is the helper merge-bot (#291, #429) uses to extract
auto-close issue references from a squash commit body. GitHub's
auto-close-on-`Closes #N` does not fire for App-token-mediated
`PUT /pulls/{n}/merge` calls (issue #429); the bot reads the body it
pasted, parses it for auto-close references, and calls
`PATCH /repos/.../issues/{N}` itself.

These tests pin the public surface (`find_same_repo_issue_numbers`,
`find_cross_repo_references`, the CLI's stdout/stderr contract) so a
change that drifts from GitHub's auto-close keyword set is caught
here before it reaches the bot.
"""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "parse-close-keywords.py"


def _load_parser() -> ModuleType:
    """Import the dash-named script as a module."""
    spec = importlib.util.spec_from_file_location("parse_close_keywords", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parser = _load_parser()


# --- AUTO_CLOSE_KEYWORDS pin -------------------------------------------


def test_auto_close_keywords_match_github_ui_set() -> None:
    """The keyword set must match what GitHub's UI auto-closer recognises.

    Drift here would silently miss issue closures the contributor
    expected to fire (`Resolved #N` is recognised by the UI; if the
    bot's set forgets `resolved` the issue stays open). Pinning the
    full set as a literal anchor catches future edits that prune
    inflections.
    """
    expected = {
        "close",
        "closes",
        "closed",
        "closing",
        "fix",
        "fixes",
        "fixed",
        "fixing",
        "resolve",
        "resolves",
        "resolved",
        "resolving",
    }
    assert expected == parser.AUTO_CLOSE_KEYWORDS


# --- find_same_repo_issue_numbers --------------------------------------


def test_simple_closes_reference_returns_issue_number() -> None:
    """The canonical `Closes #N` git trailer must produce one match."""
    body = "Subject line.\n\nCloses #429\nSigned-off-by: A <a@example.com>\n"
    assert parser.find_same_repo_issue_numbers(body) == [429]


@pytest.mark.parametrize(
    "keyword",
    [
        "close",
        "closes",
        "closed",
        "closing",
        "fix",
        "fixes",
        "fixed",
        "fixing",
        "resolve",
        "resolves",
        "resolved",
        "resolving",
    ],
)
def test_every_keyword_inflection_matches(keyword: str) -> None:
    """Every keyword in the AUTO_CLOSE_KEYWORDS set must produce a match.

    Catches a regression where the regex compiled the keyword set as a
    plain alternation that ate prefix-substring matches (e.g. `close`
    would match before `closes` and lose the trailing `s`). The
    parametrised case forces every entry through the matcher.
    """
    body = f"{keyword} #1"
    assert parser.find_same_repo_issue_numbers(body) == [1]


@pytest.mark.parametrize("variant", ["closes", "Closes", "CLOSES", "cLoSeS"])
def test_keyword_match_is_case_insensitive(variant: str) -> None:
    """Case must not matter — GitHub's UI accepts any case mix."""
    body = f"{variant} #42"
    assert parser.find_same_repo_issue_numbers(body) == [42]


def test_keyword_with_trailing_colon_matches() -> None:
    """The git-trailer form (`Closes:`) must also match.

    The validator's `GITHUB_KEYWORD_RE` rejects the colon form (project
    convention is the no-colon form), but a contributor who writes
    `Closes: #N` shouldn't have their issue stay open just because
    they used the kernel-style trailer punctuation. GitHub's UI
    accepts both.
    """
    body = "Closes: #5"
    assert parser.find_same_repo_issue_numbers(body) == [5]


def test_trailing_punctuation_on_issue_number_is_tolerated() -> None:
    """`Closes #N.` (period after the number) must still extract `N`.

    The validator allows an optional trailing period on the
    GitHub-keyword form; the parser must too, otherwise contributors
    who end the trailer with a period have their issue stay open.
    """
    body = "Closes #100."
    assert parser.find_same_repo_issue_numbers(body) == [100]


def test_multiple_distinct_references_in_one_body() -> None:
    """Multi-issue PRs (`Closes #N\\nCloses #M`) close every one."""
    body = "Closes #1\nFixes #2\nResolves #3\n"
    assert parser.find_same_repo_issue_numbers(body) == [1, 2, 3]


def test_duplicate_references_are_deduplicated_in_first_seen_order() -> None:
    """Body that mentions the same issue twice produces one merge-API call.

    Idempotency is enforced at the close-call layer, but emitting the
    issue number twice would result in two close-call attempts (and
    two `Closed by merge of PR ...` comments if the second call
    happened to land before the first comment). Dedupe at the parser
    layer keeps the workflow loop body honest.
    """
    body = "Closes #7\nFixes #7\nresolves #7\n"
    assert parser.find_same_repo_issue_numbers(body) == [7]


def test_keyword_without_issue_reference_does_not_match() -> None:
    """Body prose containing the keyword as a regular word must NOT match.

    "fixes a bug in the X module" is not an auto-close reference. The
    matcher requires a `#N` (or `owner/repo#N`) follow-on; without
    one, the keyword is just prose.
    """
    body = "This patch fixes a bug in the X module without any references."
    assert parser.find_same_repo_issue_numbers(body) == []


def test_empty_body_returns_empty_list() -> None:
    """Empty input is success with no references found."""
    assert parser.find_same_repo_issue_numbers("") == []


def test_body_with_no_auto_close_references_returns_empty_list() -> None:
    """A normal commit body with prose but no keywords returns nothing."""
    body = "Subject.\n\nA paragraph of body text.\n\nSigned-off-by: A <a@example.com>\n"
    assert parser.find_same_repo_issue_numbers(body) == []


def test_keyword_inside_word_boundary_does_not_match() -> None:
    """`prefix-closes #N` must not match — keyword needs a word boundary.

    Without the word-boundary anchor a word like `precloses` followed
    by `#N` would match. The `\\b` in the regex prevents that.
    """
    body = "preclose #5"  # no boundary before `close`
    assert parser.find_same_repo_issue_numbers(body) == []


def test_bare_issue_reference_without_keyword_does_not_match() -> None:
    """`#N` on its own (no keyword) is not an auto-close reference.

    The validator accepts a trailer like `Refs #N` for a non-closing
    cross-link; the parser must not treat that as auto-close.
    """
    body = "See #5 for context.\nRefs #6\n"
    assert parser.find_same_repo_issue_numbers(body) == []


def test_html_comments_are_stripped_before_matching() -> None:
    """Template scaffolding comments containing keyword examples must NOT match.

    The PR template's `==COMMIT_MSG==` block can carry HTML comment
    scaffolding, and the extractor preserves comments verbatim
    because they round-trip into the squash commit body. A comment
    with example keywords like
    `<!-- "Closes #N" is also accepted -->` would otherwise produce
    a false-positive auto-close on a literal issue number cited in
    template prose. Strip comments before scanning — same defensive
    shape the validator uses for linting.
    """
    body = (
        "<!-- Trailers like `Closes #999` follow git-trailer format -->\n"
        "Subject.\n\n"
        "Closes #5\n"
    )
    assert parser.find_same_repo_issue_numbers(body) == [5]


def test_multi_line_html_comment_is_stripped() -> None:
    """A multi-line `<!-- ... -->` block must not produce false-positive matches."""
    body = (
        "<!--\n"
        "Author the squash-merge commit body here.\n"
        "Trailers (`Closes #999`, `Co-authored-by`, `Signed-off-by`) follow ...\n"
        "-->\n"
        "Closes #5\n"
    )
    assert parser.find_same_repo_issue_numbers(body) == [5]


# --- find_cross_repo_references ---------------------------------------


def test_cross_repo_reference_is_parsed_separately() -> None:
    """`Closes other-org/other-repo#N` is in the cross-repo bucket only.

    The merge-bot's installation token is scoped to a single repo;
    cross-repo references are unactionable and must be reported via
    the cross-repo enumerator (which feeds the workflow's
    `::notice::` log line) rather than the same-repo issue-number
    stream that gets fed to the close API.
    """
    body = "Closes other-org/other-repo#42"
    assert parser.find_same_repo_issue_numbers(body) == []
    assert parser.find_cross_repo_references(body) == ["other-org/other-repo#42"]


def test_mixed_same_repo_and_cross_repo_references() -> None:
    """A body with both kinds splits cleanly across the two buckets."""
    body = (
        "Closes #1\n"
        "Fixes other-org/other-repo#2\n"
        "Resolves #3\n"
        "Resolves another-org/another-repo#4\n"
    )
    assert parser.find_same_repo_issue_numbers(body) == [1, 3]
    assert parser.find_cross_repo_references(body) == [
        "other-org/other-repo#2",
        "another-org/another-repo#4",
    ]


def test_cross_repo_references_are_deduplicated() -> None:
    """Repeated cross-repo references collapse to one notice."""
    body = "Closes other-org/other-repo#5\nFixes other-org/other-repo#5\n"
    assert parser.find_cross_repo_references(body) == ["other-org/other-repo#5"]


# --- emit + CLI contract -----------------------------------------------


def test_emit_writes_same_repo_to_stdout_one_per_line() -> None:
    """The merge-bot loop reads stdout via `mapfile`; pin the shape."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    parser.emit([1, 2, 42], [], stdout, stderr)
    assert stdout.getvalue() == "1\n2\n42\n"
    assert stderr.getvalue() == ""


def test_emit_writes_cross_repo_to_stderr_as_notice() -> None:
    """Cross-repo skips must surface in the workflow run log via `::notice::`."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    parser.emit([], ["other-org/other-repo#5"], stdout, stderr)
    assert stdout.getvalue() == ""
    assert "::notice::" in stderr.getvalue()
    assert "other-org/other-repo#5" in stderr.getvalue()


def _run_cli(body: str) -> subprocess.CompletedProcess[str]:
    """Run the script as a subprocess against `body` and return the result."""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "/dev/stdin"],
        input=body,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exits_zero_on_empty_body() -> None:
    """Empty body → exit 0, empty stdout, empty stderr."""
    result = _run_cli("")
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_cli_emits_same_repo_numbers_to_stdout() -> None:
    """The bot's `mapfile -t` loop body must see one issue number per line."""
    result = _run_cli("Closes #1\nFixes #2\n")
    assert result.returncode == 0
    assert result.stdout == "1\n2\n"
    assert result.stderr == ""


def test_cli_emits_cross_repo_notice_to_stderr() -> None:
    """A cross-repo reference produces a stderr `::notice::` and no stdout."""
    result = _run_cli("Closes other-org/other-repo#5\n")
    assert result.returncode == 0
    assert result.stdout == ""
    assert "::notice::" in result.stderr
    assert "other-org/other-repo#5" in result.stderr


def test_cli_help_advertises_arg() -> None:
    """`--help` must include the `body_path` positional in usage."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "body_path" in result.stdout


def test_cli_handles_body_with_shell_metacharacters_safely() -> None:
    """A body containing backticks / `$(...)` must NOT be shell-evaluated.

    The script reads the body via `Path.read_text` rather than echoing
    it through a shell pipeline; this is a regression pin for the
    CodeQL `js/actions/command-injection` discipline the workflow
    file already follows.
    """
    body = "Closes #1\n`rm -rf /` $(echo pwned)\n"
    result = _run_cli(body)
    assert result.returncode == 0
    assert result.stdout == "1\n"
    assert "pwned" not in result.stdout
    assert "pwned" not in result.stderr
