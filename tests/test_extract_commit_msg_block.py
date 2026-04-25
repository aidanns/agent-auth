# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for scripts/extract-commit-msg-block.py.

The extractor is the parser the merge bot (#291) uses to compute the
`commit_message` for the `PUT /repos/.../pulls/{n}/merge` API call.
It is the single most important behavioural gate on the bot's output:
if extraction returns the wrong text, the squash commit body on
`main` becomes wrong.

These tests pin the public API surface (`extract_block` and the CLI
exit codes) against the existing pr-lint fixtures so a change to the
extractor that drifts from the validator's parser is caught here
before it reaches the bot.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "extract-commit-msg-block.py"
FIXTURES_DIR = REPO_ROOT / ".github" / "workflows" / "tests" / "pr-lint-fixtures"


def _load_extractor() -> ModuleType:
    """Import the dash-named extractor script as a module."""
    spec = importlib.util.spec_from_file_location("extract_commit_msg_block", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extractor = _load_extractor()


def test_extract_block_returns_content_between_markers() -> None:
    body = (FIXTURES_DIR / "valid-minimal.md").read_text(encoding="utf-8")
    block = extractor.extract_block(body)
    # Expect the content between the markers, exclusive of the
    # markers themselves. The bot pastes this verbatim into
    # commit_message, so any change to whitespace or content here
    # changes the squash commit body shape.
    assert block == (
        "Add a thing.\n"
        "\n"
        "The thing is small but useful.\n"
        "\n"
        "Closes #1\n"
        "Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>"
    )


def test_extract_block_preserves_html_comments_inside_block() -> None:
    """The bot pastes the block as-is — HTML comments must round-trip.

    The validator strips HTML comments for *linting* (so template
    scaffolding doesn't fail rules like the line-width check), but
    the extractor returns the raw block. A future contributor who
    adds prose around the template's `<!-- Author the squash-merge
    commit body here. -->` placeholder will have that comment land
    in the squash commit body — that's intentional and documented
    in CONTRIBUTING.md § Writing PRs.
    """
    body = (FIXTURES_DIR / "valid-template-default.md").read_text(encoding="utf-8")
    block = extractor.extract_block(body)
    assert "<!--" in block
    assert "Author the squash-merge commit body here." in block
    assert "Wire the foo into the bar." in block


def test_extract_block_preserves_breaking_change_footer_position() -> None:
    body = (FIXTURES_DIR / "valid-breaking.md").read_text(encoding="utf-8")
    block = extractor.extract_block(body)
    lines = block.splitlines()
    # The footer must be the second-to-last line (sign-off is last).
    # If the extractor ever reorders lines, the squash commit body
    # would lose the BREAKING CHANGE positioning the validator
    # enforces upstream.
    assert lines[-2] == "BREAKING CHANGE: /v0 is removed; switch to /v1."
    assert lines[-1].startswith("Signed-off-by:")


def test_extract_block_raises_on_missing_block() -> None:
    body = (FIXTURES_DIR / "invalid-no-block.md").read_text(encoding="utf-8")
    with pytest.raises(extractor.ValidationError):
        extractor.extract_block(body)


def test_extract_block_raises_on_multiple_blocks() -> None:
    body = (FIXTURES_DIR / "invalid-multiple-blocks.md").read_text(encoding="utf-8")
    with pytest.raises(extractor.ValidationError):
        extractor.extract_block(body)


def test_cli_writes_block_to_stdout_with_no_trailing_newline(tmp_path: Path) -> None:
    """The CLI must emit the block verbatim — no extra trailing newline.

    A spurious trailing newline would shift the commit body shape
    when the bot passes it to the GitHub merge API. The merge call
    treats `commit_message` as the literal body bytes.
    """
    body = (FIXTURES_DIR / "valid-minimal.md").read_text(encoding="utf-8")
    body_path = tmp_path / "body.md"
    body_path.write_text(body, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(body_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = extractor.extract_block(body)
    assert result.stdout == expected
    assert result.returncode == 0


def test_cli_exits_nonzero_on_missing_block(tmp_path: Path) -> None:
    body = (FIXTURES_DIR / "invalid-no-block.md").read_text(encoding="utf-8")
    body_path = tmp_path / "body.md"
    body_path.write_text(body, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(body_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    # The bot surfaces the stderr verbatim in the `Claude: Cannot
    # merge` comment, so the prefix must stay stable.
    assert "extract-commit-msg-block:" in result.stderr
