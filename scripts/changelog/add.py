#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI helper for scaffolding ``changelog/@unreleased/*.yml`` entries.

Phase 2 ergonomics on top of #295's hand-authored YAML schema. Sits
alongside #298's bot-mediated path; all three modes (hand, CLI, bot)
converge on the same on-disk YAML.

## Modes

- **Interactive** (no flags) — walks the contributor through:
  1. Type (one of ``feature | improvement | fix | break | deprecation | migration``).
  2. Description (free-text via ``$EDITOR`` or single-line ``input()``).
  3. Packages (zero or more from the on-disk workspace member list).
  4. PR number (auto-detected from ``gh pr view`` if available, else
     prompted).
  5. Optional ``release-as`` (only prompted when ``--release-as`` is
     passed, to avoid surprise overrides).

- **Non-interactive** (``--type … --description … --pr …``) — every
  required field is read from flags. The CLI errors with a clear
  message if a required field is missing AND ``stdin`` is not a TTY
  (so CI pipelines fail fast rather than blocking on ``input()``).

- **Check** (``--check``) — for the optional lefthook pre-push hook.
  Prints a one-line warning to stderr if the current branch has no
  added/modified files under ``changelog/@unreleased/`` vs.
  ``origin/main``. Exits 0 by default; pass ``--strict`` to make the
  warning a hard failure.

## Validation

Every authoring mode runs the same gate before writing:

01. ``--type`` is a known ``EntryType`` value.
02. ``--packages`` (if provided) all exist in the workspace member
    list (read from ``packages/*/pyproject.toml``).
03. The PR number is a positive integer.
04. The composed YAML round-trips through
    ``version_logic.parse_entry_file`` successfully.
05. If ``--release-as`` is set, ``validate_release_as`` accepts the
    new entry alongside the existing ``@unreleased/`` set.

The CLI is intentionally a thin wrapper around #295's surface — every
predicate above is a direct call into ``version_logic`` /
``lint``. There is no duplicate validation logic.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import IO

# Keep ``version_logic`` and ``lint`` importable when this file is
# invoked as a script (``python scripts/changelog/add.py`` — Python
# puts the script's directory on sys.path automatically) and when
# imported from a parent package. Same trick as ``lint.py``.
_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from lint import (  # noqa: E402  -- after sys.path setup
    UNRELEASED_DIR,
    detect_current_version,
    list_present_changelog_files,
    list_workspace_packages,
)
from version_logic import (  # noqa: E402  -- after sys.path setup
    ENTRY_FILENAME_PATTERN,
    ChangelogValidationError,
    EntryType,
    parse_entry_file,
    validate_packages_against_workspace,
    validate_release_as,
)
from wordlist import WORDS  # noqa: E402  -- after sys.path setup

# --- Public types ------------------------------------------------------------

#: Maximum number of slug retries before giving up. The combination
#: space (~190k two-word permutations from a ~437-word list) makes a
#: real collision essentially impossible; the cap exists so a bug in
#: the randomness source can't loop forever.
MAX_SLUG_RETRIES = 5

#: Type values accepted on the CLI ``--type`` flag. Mirrors
#: ``EntryType`` (string-valued enum) so we can compare against
#: ``argparse.Namespace.type`` directly.
TYPE_CHOICES: tuple[str, ...] = tuple(t.value for t in EntryType)

#: Pattern used to validate the slug we generate matches the lint's
#: filename rule. Keeps the slug-generator honest if the wordlist ever
#: drifts (e.g. a contributor adds a non-``[a-z]`` word).
_SLUG_PART_RE = re.compile(r"^[a-z]+$")


@dataclasses.dataclass(frozen=True)
class EntryDraft:
    """In-memory representation of an entry the CLI is about to write.

    Mirrors the on-disk YAML schema (``type``, ``description``,
    ``packages``, ``release-as``, ``links``) so the renderer is a
    pure function over this dataclass.
    """

    entry_type: EntryType
    description: str
    pr_number: int
    packages: tuple[str, ...] | None
    release_as: str | None


class CliError(RuntimeError):
    """Raised for unrecoverable CLI errors (validation, IO).

    Caught at ``main()`` and rendered as a single ``error: <message>``
    line on stderr, then non-zero exit. Lets the rest of the module
    raise instead of returning sentinel error codes.
    """


# --- Slug generation ---------------------------------------------------------


def derive_slug(rng: random.Random) -> str:
    """Pick two random words and join with ``-`` to form a slug.

    Uses the supplied ``random.Random`` so tests can pin the seed and
    assert against deterministic output. Validates each word against
    ``[a-z]+`` so a future drift in the wordlist surfaces here, not
    via a downstream lint failure.
    """
    a = rng.choice(WORDS)
    b = rng.choice(WORDS)
    if not (_SLUG_PART_RE.match(a) and _SLUG_PART_RE.match(b)):
        raise CliError(f"wordlist drift: slug parts {a!r}/{b!r} contain non-lowercase letters")
    return f"{a}-{b}"


def candidate_path(repo_root: Path, pr_number: int, slug: str) -> Path:
    """Return the path the CLI would write for ``(pr_number, slug)``."""
    return repo_root / UNRELEASED_DIR / f"pr-{pr_number}-{slug}.yml"


def derive_unique_path(
    repo_root: Path,
    pr_number: int,
    rng: random.Random,
    *,
    max_retries: int = MAX_SLUG_RETRIES,
) -> Path:
    """Pick a slug whose filename does not collide on disk.

    Retries up to ``max_retries`` times before raising ``CliError``.
    The retry cap is a defence-in-depth against a bug in the
    randomness source — a real collision against the existing on-disk
    set is vanishingly rare given the combination space.
    """
    for _ in range(max_retries):
        slug = derive_slug(rng)
        candidate = candidate_path(repo_root, pr_number, slug)
        if not candidate.exists():
            return candidate
    raise CliError(
        f"failed to find a unique slug after {max_retries} attempts; "
        "rerun (the slug pool is large enough that a real collision is "
        "essentially impossible — this likely indicates a bug)"
    )


# --- YAML composition --------------------------------------------------------


def compose_yaml(draft: EntryDraft) -> str:
    """Render ``draft`` as a YAML string matching the project's layout.

    Hand-rendered (rather than ``yaml.safe_dump``) so the file matches
    the existing ``changelog/@unreleased/*.yml`` style: SPDX header,
    ``description: |`` block scalar, optional ``links``, optional
    ``packages``, optional ``release-as``. PyYAML's default emitter
    re-quotes block scalars with newlines in surprising ways which
    the project's ``mdformat`` style does not match.

    The output is parseable by ``parse_entry_file`` — the caller
    re-parses to gate the write.
    """
    cleaned_lines = [line.rstrip() for line in draft.description.strip().splitlines()]
    if not any(line.strip() for line in cleaned_lines):
        raise CliError("description is empty after stripping whitespace")
    indented = "\n".join(f"    {line}" if line else "" for line in cleaned_lines)

    pr_link = f"https://github.com/aidanns/agent-auth/pull/{draft.pr_number}"
    type_value = draft.entry_type.value

    # REUSE-IgnoreStart -- the SPDX header strings below are written
    # to the generated YAML (not a declaration about this source
    # file). Without the ignore markers, REUSE reads the multi-line
    # Python string literal as a malformed
    # `SPDX-License-Identifier: MIT\n` declaration on this source.
    parts = [
        "# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith",
        "#",
        "# SPDX-License-Identifier: MIT",
        "",
        f"type: {type_value}",
        f"{type_value}:",
        "  description: |",
        indented,
        "  links:",
        f"    - {pr_link}",
    ]
    # REUSE-IgnoreEnd
    if draft.packages:
        parts.append("packages:")
        for pkg in draft.packages:
            parts.append(f"  - {pkg}")
    if draft.release_as is not None:
        parts.append(f"release-as: {draft.release_as}")
    parts.append("")  # trailing newline
    return "\n".join(parts)


# --- Validation --------------------------------------------------------------


def parse_entry_type(value: str) -> EntryType:
    """Convert a CLI string to the ``EntryType`` enum or raise CliError."""
    try:
        return EntryType(value)
    except ValueError as exc:
        allowed = ", ".join(TYPE_CHOICES)
        raise CliError(f"unknown --type {value!r}; expected one of: {allowed}") from exc


def parse_packages_csv(raw: str | None) -> tuple[str, ...] | None:
    """Parse a ``--packages a,b,c`` value into a tuple, or ``None``.

    Empty input (None or '') means workspace-wide (no ``packages:`` key
    in the YAML). Whitespace around each entry is stripped.
    """
    if raw is None or not raw.strip():
        return None
    parts = [p.strip() for p in raw.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    return tuple(parts)


def assert_valid_pr_number(value: int) -> None:
    """Reject zero / negative PR numbers up front."""
    if value <= 0:
        raise CliError(f"--pr must be a positive integer (got {value})")


def assert_packages_in_workspace(
    packages: Sequence[str],
    workspace: Sequence[str],
) -> None:
    """Reject ``--packages`` entries that don't name a workspace member."""
    if not packages:
        return
    known = set(workspace)
    unknown = sorted(p for p in packages if p not in known)
    if unknown:
        # Render the workspace list so the contributor sees the valid set.
        rendered = ", ".join(sorted(known))
        raise CliError(
            f"--packages references unknown workspace members: "
            f"{', '.join(unknown)} (known: {rendered})"
        )


def assert_release_as_valid(
    draft: EntryDraft,
    repo_root: Path,
    current_version: str,
) -> None:
    """Validate ``release-as`` against the existing ``@unreleased/`` set.

    Composes the draft as if it were already on disk, parses it back
    to a ``ChangelogEntry``, joins the present entries, and runs
    ``validate_release_as``. Re-uses #295's logic verbatim so the
    rule stays in one place.
    """
    if draft.release_as is None:
        return
    body = compose_yaml(draft)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / f"pr-{draft.pr_number}-draft.yml"
        tmp_path.write_text(body, encoding="utf-8")
        try:
            new_entry = parse_entry_file(tmp_path)
        except ChangelogValidationError as exc:
            raise CliError(f"composed YAML failed schema validation: {exc}") from exc
    existing_entries = []
    for path in list_present_changelog_files(repo_root):
        try:
            existing_entries.append(parse_entry_file(path))
        except ChangelogValidationError:
            # Skip already-present entries the lint would also reject;
            # surfacing them here would conflate two different problems.
            continue
    try:
        validate_release_as([*existing_entries, new_entry], current_version)
    except ChangelogValidationError as exc:
        raise CliError(f"--release-as rejected: {exc}") from exc


def gate_write(
    draft: EntryDraft,
    repo_root: Path,
    current_version: str,
) -> None:
    """Run every validation gate. Raises ``CliError`` on the first failure."""
    assert_valid_pr_number(draft.pr_number)

    workspace = list_workspace_packages(repo_root)
    if draft.packages is not None:
        assert_packages_in_workspace(draft.packages, workspace)

    # Gate the schema by composing + parsing through ``parse_entry_file``.
    # This catches malformed combinations (e.g. an empty description)
    # that the per-field validators didn't.
    body = compose_yaml(draft)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / f"pr-{draft.pr_number}-draft.yml"
        tmp_path.write_text(body, encoding="utf-8")
        try:
            entry = parse_entry_file(tmp_path)
        except ChangelogValidationError as exc:
            raise CliError(f"composed YAML failed schema validation: {exc}") from exc
        if draft.packages is not None:
            try:
                validate_packages_against_workspace(entry, workspace)
            except ChangelogValidationError as exc:
                raise CliError(str(exc)) from exc

    # Run the release-as invariant (composes + parses again, but the
    # extra round-trip is cheap and the duplication keeps each gate
    # independently callable).
    assert_release_as_valid(draft, repo_root, current_version)


# --- PR-number resolution ----------------------------------------------------


def detect_pr_number(repo_root: Path) -> int | None:
    """Best-effort lookup of the current branch's PR number via ``gh``.

    Returns ``None`` on any failure (gh not installed, not in a git
    checkout, no PR for this branch). Never raises — the caller falls
    back to a prompt.
    """
    if shutil.which("gh") is None:
        return None
    try:
        completed = subprocess.run(
            ["gh", "pr", "view", "--json", "number", "--jq", ".number"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    raw = completed.stdout.strip()
    if not raw.isdigit():
        return None
    return int(raw)


# --- Interactive prompts -----------------------------------------------------


def _is_interactive(stdin: IO[str], stdout: IO[str]) -> bool:
    """True only when both stdin and stdout are TTYs.

    Prevents the CLI from blocking on ``input()`` in CI / piped
    invocations where there is no human to answer.
    """
    return bool(getattr(stdin, "isatty", lambda: False)()) and bool(
        getattr(stdout, "isatty", lambda: False)()
    )


def prompt_for_type(
    stdin: IO[str],
    stdout: IO[str],
) -> EntryType:
    """Ask the user to pick a type from the menu of ``EntryType`` values."""
    print("Select changelog entry type:", file=stdout)
    for index, value in enumerate(TYPE_CHOICES, start=1):
        print(f"  {index}. {value}", file=stdout)
    while True:
        print("Choice [1]: ", end="", file=stdout, flush=True)
        raw = stdin.readline().strip() or "1"
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(TYPE_CHOICES):
                return EntryType(TYPE_CHOICES[idx - 1])
        # Allow typing the literal value too.
        try:
            return EntryType(raw)
        except ValueError:
            print(
                f"  '{raw}' is not a valid choice; pick 1-{len(TYPE_CHOICES)} "
                "or a literal type value.",
                file=stdout,
            )


def prompt_for_description(
    stdin: IO[str],
    stdout: IO[str],
    editor: str | None,
) -> str:
    """Open ``$EDITOR`` if set, else read a single line from ``stdin``.

    The editor mode pre-populates the temp file with a one-line
    instruction comment. Every comment line is stripped before the
    text is returned, so a contributor who leaves the comment in place
    doesn't accidentally embed it in the description.
    """
    if editor:
        return _read_via_editor(editor)
    print(
        "Enter description (single line; set $EDITOR for multi-line input):",
        file=stdout,
    )
    print("> ", end="", file=stdout, flush=True)
    line = stdin.readline().strip()
    if not line:
        raise CliError("description is required")
    return line


def _read_via_editor(editor: str) -> str:
    """Open ``editor`` against a tempfile and return the user's input."""
    placeholder = (
        "# Write the changelog description below. Lines starting with `#` "
        "are stripped.\n"
        "# Markdown is allowed. Save and quit when done.\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w+",
        suffix=".md",
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(placeholder)
        tmp_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [*editor.split(), str(tmp_path)],
            check=False,
        )
        if completed.returncode != 0:
            raise CliError(f"editor {editor!r} exited non-zero (returncode={completed.returncode})")
        text = tmp_path.read_text(encoding="utf-8")
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
    body_lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    body = "\n".join(body_lines).strip()
    if not body:
        raise CliError("description is empty after stripping comment lines")
    return body


def prompt_for_packages(
    stdin: IO[str],
    stdout: IO[str],
    workspace: Sequence[str],
) -> tuple[str, ...] | None:
    """Ask the user to pick zero or more workspace members.

    Returns ``None`` (workspace-wide) when the user accepts the empty
    default. The prompt accepts comma-separated literals (e.g.
    ``agent-auth,gpg-bridge``) and validates against the workspace
    list.
    """
    if not workspace:
        return None
    print("Workspace members (comma-separated, or empty for workspace-wide):", file=stdout)
    for name in workspace:
        print(f"  - {name}", file=stdout)
    while True:
        print("Packages: ", end="", file=stdout, flush=True)
        raw = stdin.readline().strip()
        if not raw:
            return None
        candidate = parse_packages_csv(raw)
        if candidate is None:
            return None
        try:
            assert_packages_in_workspace(candidate, workspace)
        except CliError as exc:
            print(f"  {exc}", file=stdout)
            continue
        return candidate


def prompt_for_pr_number(
    stdin: IO[str],
    stdout: IO[str],
    detected: int | None,
) -> int:
    """Ask for the PR number; default to the auto-detected value if any."""
    prompt = f"PR number [{detected}]: " if detected is not None else "PR number: "
    while True:
        print(prompt, end="", file=stdout, flush=True)
        raw = stdin.readline().strip()
        if not raw and detected is not None:
            return detected
        if raw.isdigit():
            value = int(raw)
            if value > 0:
                return value
        print("  PR number must be a positive integer.", file=stdout)


def prompt_for_release_as(stdin: IO[str], stdout: IO[str]) -> str | None:
    """Ask the user for a ``release-as`` override (optional)."""
    print(
        "release-as override (X.Y.Z, must be > inferred next version), " "empty to skip:",
        file=stdout,
    )
    print("release-as: ", end="", file=stdout, flush=True)
    raw = stdin.readline().strip()
    return raw or None


# --- Draft assembly ----------------------------------------------------------


def build_draft_interactive(
    *,
    repo_root: Path,
    args: argparse.Namespace,
    stdin: IO[str],
    stdout: IO[str],
) -> EntryDraft:
    """Walk the user through the prompts and return a populated draft.

    Honours flag values when present (so ``--type fix`` skips the type
    prompt) and only prompts for ``release-as`` when the
    ``--release-as`` flag was passed (avoids accidental overrides).
    """
    if args.type is not None:
        entry_type = parse_entry_type(args.type)
    else:
        entry_type = prompt_for_type(stdin, stdout)

    if args.description is not None:
        description = args.description
    else:
        editor = os.environ.get("EDITOR") if args.editor else None
        description = prompt_for_description(stdin, stdout, editor)

    if args.packages is not None:
        packages = parse_packages_csv(args.packages)
    else:
        workspace = list_workspace_packages(repo_root)
        packages = prompt_for_packages(stdin, stdout, workspace)

    if args.pr is not None:
        pr_number = args.pr
    else:
        detected = detect_pr_number(repo_root)
        pr_number = prompt_for_pr_number(stdin, stdout, detected)

    # Only prompt for release-as when the flag was passed (avoids
    # accidental overrides in the happy path).
    if args.release_as_present:
        if args.release_as is not None:
            release_as: str | None = args.release_as
        else:
            release_as = prompt_for_release_as(stdin, stdout)
    else:
        release_as = None

    return EntryDraft(
        entry_type=entry_type,
        description=description,
        pr_number=pr_number,
        packages=packages,
        release_as=release_as,
    )


def build_draft_non_interactive(args: argparse.Namespace) -> EntryDraft:
    """Build a draft strictly from CLI flags. Errors on missing fields."""
    missing: list[str] = []
    if args.type is None:
        missing.append("--type")
    if args.description is None:
        missing.append("--description")
    if args.pr is None:
        missing.append("--pr")
    if missing:
        rendered = ", ".join(missing)
        raise CliError(
            f"non-interactive mode requires {rendered} (no TTY detected, "
            "or non-interactive flags incomplete)"
        )
    entry_type = parse_entry_type(args.type)
    packages = parse_packages_csv(args.packages)
    return EntryDraft(
        entry_type=entry_type,
        description=args.description,
        pr_number=args.pr,
        packages=packages,
        release_as=args.release_as,
    )


# --- --check mode (lefthook hook) -------------------------------------------


def check_branch_has_entry(repo_root: Path, base_ref: str) -> bool:
    """Return True if the current branch has any added/modified file
    under ``changelog/@unreleased/`` vs. ``base_ref``.

    Defensive against missing ``base_ref`` (returns True so we don't
    spam a user mid-rebase with a misleading warning).
    """
    if shutil.which("git") is None:
        return True
    cmd = [
        "git",
        "diff",
        "--name-only",
        f"{base_ref}...HEAD",
        "--",
        f"{UNRELEASED_DIR}/",
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        # Likely no merge-base with origin/main — treat as "can't tell"
        # rather than warning falsely.
        return True
    for line in completed.stdout.splitlines():
        if line.strip() and ENTRY_FILENAME_PATTERN.match(Path(line).name):
            return True
    return False


def run_check_mode(
    args: argparse.Namespace,
    repo_root: Path,
    stderr: IO[str],
) -> int:
    """Implement ``--check``. Advisory by default, hard fail under ``--strict``."""
    has_entry = check_branch_has_entry(repo_root, args.base_ref)
    if has_entry:
        return 0
    message = (
        "changelog-add: no changelog/@unreleased/pr-<N>-*.yml entry on this "
        f"branch vs. {args.base_ref}. Run `task changelog:add` to create one, "
        "or apply the `no changelog` label to opt out."
    )
    print(message, file=stderr)
    return 1 if args.strict else 0


# --- Argparse plumbing -------------------------------------------------------


class _ReleaseAsAction(argparse.Action):
    """Records that ``--release-as`` was passed (with or without value).

    Lets the interactive path differentiate "user wants to set
    release-as, prompt them" from "user didn't mention release-as,
    skip the prompt".
    """

    def __call__(  # type: ignore[override]
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, values)
        namespace.release_as_present = True


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="changelog-add",
        description=(
            "Scaffold a changelog/@unreleased/*.yml entry. "
            "Run with no flags for an interactive prompt; pass --type / "
            "--description / --pr for non-interactive use."
        ),
    )
    parser.add_argument(
        "--type",
        choices=TYPE_CHOICES,
        default=None,
        help="Entry type (required in non-interactive mode).",
    )
    parser.add_argument(
        "--description",
        default=None,
        help="Description text (required in non-interactive mode).",
    )
    parser.add_argument(
        "--pr",
        type=int,
        default=None,
        help=(
            "Pull-request number. Auto-detected from `gh pr view` when "
            "omitted in interactive mode; required in non-interactive."
        ),
    )
    parser.add_argument(
        "--packages",
        default=None,
        help=(
            "Comma-separated list of workspace members the change "
            "affects. Omit for workspace-wide entries."
        ),
    )
    parser.add_argument(
        "--release-as",
        action=_ReleaseAsAction,
        default=None,
        help=(
            "Force a specific next version (must be > inferred next "
            "version). Pass the flag with no value in interactive mode "
            "to be prompted."
        ),
    )
    parser.add_argument(
        "--editor",
        action="store_true",
        help=(
            "When running interactively without --description, open "
            "$EDITOR for multi-line input. Default is a single-line prompt."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("REPO_ROOT", "."),
        help="Repository root (default: $REPO_ROOT or `.`).",
    )
    parser.add_argument(
        "--current-version",
        default=os.environ.get("CURRENT_VERSION", ""),
        help=(
            "Current released version (default: $CURRENT_VERSION; falls "
            "back to `git describe --tags --abbrev=0 --match v*.*.*`)."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Lefthook hook mode: warn (and optionally fail under "
            "--strict) when the current branch has no changelog entry "
            "vs. --base-ref."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Make --check exit non-zero (default: warn-only).",
    )
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="Base ref --check diffs against (default: origin/main).",
    )
    args = parser.parse_args(argv)
    # Default ``release_as_present`` so downstream code can read the
    # attribute unconditionally without needing ``getattr`` everywhere.
    if not hasattr(args, "release_as_present"):
        args.release_as_present = False
    return args


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    in_ = stdin if stdin is not None else sys.stdin
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    repo_root = Path(args.repo_root).resolve()

    if args.check:
        return run_check_mode(args, repo_root, err)

    try:
        if _is_interactive(in_, out):
            draft = build_draft_interactive(
                repo_root=repo_root,
                args=args,
                stdin=in_,
                stdout=out,
            )
        else:
            draft = build_draft_non_interactive(args)

        current_version = detect_current_version(
            repo_root,
            args.current_version or None,
        )
        gate_write(draft, repo_root, current_version)

        rng = random.Random()
        target = derive_unique_path(repo_root, draft.pr_number, rng)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(compose_yaml(draft), encoding="utf-8")
    except CliError as exc:
        print(f"changelog-add: error: {exc}", file=err)
        return 1

    print(f"changelog-add: wrote {target.relative_to(repo_root)}", file=out)
    return 0


__all__ = [
    "EntryDraft",
    "MAX_SLUG_RETRIES",
    "TYPE_CHOICES",
    "CliError",
    "build_draft_interactive",
    "build_draft_non_interactive",
    "candidate_path",
    "check_branch_has_entry",
    "compose_yaml",
    "derive_slug",
    "derive_unique_path",
    "detect_pr_number",
    "gate_write",
    "main",
    "parse_args",
    "parse_entry_type",
    "parse_packages_csv",
]


if __name__ == "__main__":
    sys.exit(main())
