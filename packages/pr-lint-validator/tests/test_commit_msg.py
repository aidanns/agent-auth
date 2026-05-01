# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for ``pr_lint_validator.commit_msg``.

The bundled title-aware and verbose-body self-test fixtures are the
contract surface; the tests below parametrise over both tuples so
each fixture surfaces as its own pytest report line.
"""

from __future__ import annotations

import pytest

from pr_lint_validator import commit_msg


def _label_for(case: tuple[object, ...]) -> str:
    return str(case[-1])


@pytest.mark.parametrize("case", commit_msg._TITLE_AWARE_SELF_TEST_CASES, ids=_label_for)
def test_title_aware_self_test_fixture(case: tuple[object, ...]) -> None:
    body, title_str, expect_pass, _label = case
    if expect_pass:
        commit_msg.validate(body, title=title_str)  # type: ignore[arg-type]
        return
    with pytest.raises(commit_msg.ValidationError):
        commit_msg.validate(body, title=title_str)  # type: ignore[arg-type]


@pytest.mark.parametrize("case", commit_msg._VERBOSE_BODY_SELF_TEST_CASES, ids=_label_for)
def test_verbose_body_self_test_fixture(case: tuple[object, ...]) -> None:
    body, expect_warning, _label = case
    block = commit_msg.extract_commit_msg_block(body)  # type: ignore[arg-type]
    lines = commit_msg.block_lines(block)
    warning_count = commit_msg.check_verbose_body(lines)
    if expect_warning:
        assert warning_count > 0
    else:
        assert warning_count == 0


def test_run_self_test_returns_zero_on_full_pass() -> None:
    """``run_self_test`` exits 0 when every bundled fixture matches."""
    captured: list[str] = []

    def write(msg: str, *, error: bool = False) -> None:
        captured.append(msg)

    rc = commit_msg.run_self_test(write)
    assert rc == 0
    assert any("self-test cases passed" in line for line in captured)


def test_extract_block_returns_none_for_missing_marker() -> None:
    """No marker -> ``None`` (the changelog-bot fall-through contract)."""
    assert commit_msg.extract_block("just a body, no markers", "ANY") is None


def test_extract_block_raises_on_lone_marker() -> None:
    """A single marker line is unbalanced and must raise loud."""
    with pytest.raises(commit_msg.BlockMarkerError):
        commit_msg.extract_block("==COMMIT_MSG==\nbody but no closer", "COMMIT_MSG")


def test_extract_commit_msg_block_raises_on_missing_marker() -> None:
    """The commit-msg wrapper raises ValidationError on absent block.

    The wrapper's contract diverges from the bare ``extract_block``
    return-None pattern: the merge-bot wants a hard failure when the
    ``==COMMIT_MSG==`` block is missing because there is nothing for
    it to paste. Lock down the wrapper's "block is required"
    semantics.
    """
    with pytest.raises(commit_msg.ValidationError, match="missing"):
        commit_msg.extract_commit_msg_block("body without markers")


def test_validate_rejects_missing_signoff() -> None:
    """A block without a ``Signed-off-by:`` trailer fails DCO.

    The merge-bot pastes the block verbatim as the squash-merge
    body, so a missing signoff lands a DCO-violating commit on
    ``main``. The validator must catch this at PR-author time.
    """
    body = (
        "==COMMIT_MSG==\n"
        "Subject summary.\n\n"
        "Some rationale.\n\n"
        "Closes #1\n"
        "==COMMIT_MSG==\n"
    )
    with pytest.raises(commit_msg.ValidationError, match="Signed-off-by"):
        commit_msg.validate(body)


def test_validate_rejects_blank_between_trailers() -> None:
    """Trailer blocks must be contiguous.

    The auto-memory note ``feedback_commit_msg_block_trailer_format``
    documents this exact regression: a blank between ``Closes #N``
    and ``Signed-off-by:`` causes ``git interpret-trailers --parse``
    to drop the leading trailer.
    """
    body = (
        "==COMMIT_MSG==\n"
        "Subject summary.\n\n"
        "Body paragraph.\n\n"
        "Closes #1\n\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n"
    )
    with pytest.raises(commit_msg.ValidationError, match="contiguous"):
        commit_msg.validate(body)


def test_validate_rejects_three_markers() -> None:
    """More than two ``==COMMIT_MSG==`` lines is structurally ambiguous."""
    body = "==COMMIT_MSG==\n" "Body.\n" "==COMMIT_MSG==\n" "==COMMIT_MSG==\n"
    with pytest.raises(commit_msg.ValidationError, match="markers"):
        commit_msg.validate(body)


def test_validate_rejects_overlong_body_line() -> None:
    """Body lines wider than the 72-char cap are rejected.

    Trailer lines are exempt — exercised separately below to lock
    down that exemption against a regression that re-applied the cap
    to the entire block.
    """
    long_line = "x" * 80
    body = (
        "==COMMIT_MSG==\n"
        "Subject summary.\n\n"
        f"{long_line}\n\n"
        "Closes #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n"
    )
    with pytest.raises(commit_msg.ValidationError, match="wider than"):
        commit_msg.validate(body)


def test_validate_allows_long_signoff_trailer() -> None:
    """A long ``Signed-off-by:`` value is not subject to the 72-char cap.

    The release-bot's signoff line carries a numeric-id-prefixed
    no-reply email like
    ``<123456+agent-auth-release-bot[bot]@users.noreply.github.com>``
    which alone is 60 chars; with the trailer token + value it
    exceeds the body wrap. The validator must let trailer lines pass
    or the bot-rendered release body fails CI on its own signoff.
    """
    long_email = (
        "Signed-off-by: agent-auth-release-bot[bot] "
        "<123456789+agent-auth-release-bot[bot]@users.noreply.github.com>"
    )
    assert len(long_email) > commit_msg.MAX_LINE_WIDTH
    body = (
        "==COMMIT_MSG==\n"
        "Subject summary.\n\n"
        "Body paragraph.\n\n"
        f"{long_email}\n"
        "==COMMIT_MSG==\n"
    )
    commit_msg.validate(body)


def test_validate_rejects_markdown_heading() -> None:
    """Markdown headings are reviewer-surface and not allowed in a commit body."""
    body = (
        "==COMMIT_MSG==\n"
        "Subject summary.\n\n"
        "## Review notes\n"
        "Body.\n\n"
        "Closes #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n"
    )
    with pytest.raises(commit_msg.ValidationError, match="markdown"):
        commit_msg.validate(body)


def test_validate_rejects_breaking_change_followed_by_body() -> None:
    """``BREAKING CHANGE:`` must be the last non-signoff line."""
    body = (
        "==COMMIT_MSG==\n"
        "Subject summary.\n\n"
        "Body.\n\n"
        "BREAKING CHANGE: removes the legacy endpoint.\n"
        "More body that should not follow the breaking-change footer.\n\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n"
    )
    with pytest.raises(commit_msg.ValidationError, match="BREAKING"):
        commit_msg.validate(body)


def test_validate_rejects_unknown_trailer_token() -> None:
    """A typo'd trailer (``Cosed:``) fails closed."""
    body = (
        "==COMMIT_MSG==\n"
        "Subject summary.\n\n"
        "Body paragraph.\n\n"
        "Cosed: #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n"
    )
    with pytest.raises(commit_msg.ValidationError, match="unknown token"):
        commit_msg.validate(body)


def test_validate_rejects_fixes_sha_without_subject() -> None:
    """Kernel-style ``Fixes:`` without a quoted subject is rejected."""
    body = (
        "==COMMIT_MSG==\n"
        "Subject summary.\n\n"
        "Body paragraph.\n\n"
        "Fixes: 9c4f1a2 broken\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n"
    )
    with pytest.raises(commit_msg.ValidationError, match="Fixes"):
        commit_msg.validate(body)


def test_validate_rejects_leading_blank_in_block() -> None:
    """A leading blank line drops the bot's pasted subject."""
    body = (
        "==COMMIT_MSG==\n"
        "\n"
        "Subject summary.\n\n"
        "Body.\n\n"
        "Closes #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n"
    )
    with pytest.raises(commit_msg.ValidationError, match="blank"):
        commit_msg.validate(body)


def test_validate_rejects_no_blank_before_trailers() -> None:
    """A body that runs straight into the trailer block fails the layout rule."""
    body = (
        "==COMMIT_MSG==\n"
        "Subject summary.\n\n"
        "Body paragraph that runs straight into the trailers.\n"
        "Closes #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n"
    )
    with pytest.raises(commit_msg.ValidationError, match="blank line"):
        commit_msg.validate(body)


def test_validate_rejects_empty_block_after_comments() -> None:
    """An all-HTML-comment block is empty after stripping."""
    body = "==COMMIT_MSG==\n" "<!-- placeholder from the template -->\n" "==COMMIT_MSG==\n"
    with pytest.raises(commit_msg.ValidationError, match="empty"):
        commit_msg.validate(body)


def test_validate_rejects_empty_trailer_value() -> None:
    """An empty trailer value (``Closes:``) fails closed.

    ``parse_trailer_block`` only matches non-empty values, so
    ``Closes:`` with nothing after it doesn't even register as a
    trailer line. The structural failure here is therefore "missing
    Signed-off-by" because the broken trailer line splits the
    trailer block; the test name asserts the symptom, not the
    underlying mechanism.
    """
    body = (
        "==COMMIT_MSG==\n"
        "Subject summary.\n\n"
        "Body paragraph.\n\n"
        "Closes:   \n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>\n"
        "==COMMIT_MSG==\n"
    )
    with pytest.raises(commit_msg.ValidationError):
        commit_msg.validate(body)
