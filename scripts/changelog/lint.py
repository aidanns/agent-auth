# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""PR-time lint over ``changelog/@unreleased/*.yml`` entries.

Invoked from ``.github/workflows/changelog-lint.yml`` on every
``pull_request: opened, synchronize, reopened`` event. The four checks
mirror #295's acceptance criteria:

1. **File presence** — at least one *added* file under
   ``changelog/@unreleased/`` matching ``pr-<N>-*.yml``, OR the PR
   carries the ``no changelog`` label.
2. **File naming** — every YAML under ``changelog/@unreleased/`` (in
   the PR diff) matches ``pr-<N>-<slug>.yml`` with ``<N>`` equal to
   the PR number.
3. **Schema validation** — every YAML parses, required fields are
   present, the nested key matches ``type:``, and ``packages:``
   entries name real workspace members.
4. **release-as invariant** — any ``release-as`` value is strictly
   greater than the version inferred from all unreleased YAMLs
   against the current ``vX.Y.Z`` tag; conflicting values across
   files fail.

The CLI surface is intentionally thin: it consumes PR metadata from
env vars (``PR_NUMBER``, ``PR_LABELS``, ``BASE_SHA``, ``HEAD_SHA``,
``CURRENT_VERSION``) so the workflow YAML only has to forward the
values it already knows. Local dry-runs can pass them as flags.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

# Keep ``version_logic`` importable both when this file is invoked as a
# script (``python scripts/changelog/lint.py`` — Python puts the
# script's directory on sys.path automatically) and when imported from
# a parent package (``python -m scripts.changelog.lint``). The
# explicit insert handles the third case: a future caller that imports
# ``lint`` from another working directory.
_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from version_logic import (  # noqa: E402  -- after sys.path setup
    ENTRY_FILENAME_PATTERN,
    ChangelogEntry,
    ChangelogValidationError,
    infer_next_version,
    parse_entry_file,
    validate_packages_against_workspace,
    validate_release_as,
)

UNRELEASED_DIR = Path("changelog/@unreleased")
NO_CHANGELOG_LABEL = "no changelog"


# Errors are accumulated and reported together so a contributor sees
# every problem in one CI run, rather than fixing one and waiting for
# the next failure.
class LintReport:
    """Accumulates lint errors so the CLI can exit once with all findings."""

    def __init__(self) -> None:
        self._errors: list[str] = []

    def fail(self, message: str) -> None:
        self._errors.append(message)

    def fail_for(self, error: ChangelogValidationError) -> None:
        self._errors.append(str(error))

    @property
    def has_errors(self) -> bool:
        return bool(self._errors)

    def render(self) -> str:
        return "\n".join(self._errors)


def list_workspace_packages(repo_root: Path) -> list[str]:
    """Return the names of every workspace member under ``packages/``.

    Reads each ``packages/*/pyproject.toml`` ``[project].name`` so the
    lint stays in sync with the on-disk workspace without a separate
    allowlist. Skips directories without a ``pyproject.toml``.
    """
    import tomllib

    packages_root = repo_root / "packages"
    if not packages_root.is_dir():
        return []
    names: list[str] = []
    for child in sorted(packages_root.iterdir()):
        pyproject = child / "pyproject.toml"
        if not pyproject.is_file():
            continue
        with pyproject.open("rb") as handle:
            data = tomllib.load(handle)
        project = data.get("project")
        if not isinstance(project, dict):
            continue
        name = project.get("name")
        if isinstance(name, str):
            names.append(name)
    return names


def list_added_changelog_files(
    base_sha: str,
    head_sha: str,
    *,
    repo_root: Path,
) -> list[Path]:
    """Return paths added in the PR that live under ``changelog/@unreleased/``.

    Uses ``git diff --diff-filter=A`` so renames and modifications
    don't count toward the file-presence check — the issue's rule is
    that a PR must *add* a new entry.
    """
    cmd = [
        "git",
        "diff",
        "--name-only",
        "--diff-filter=A",
        f"{base_sha}...{head_sha}",
    ]
    completed = subprocess.run(
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    paths: list[Path] = []
    prefix = str(UNRELEASED_DIR) + "/"
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        if line.startswith(prefix) and line.endswith(".yml"):
            paths.append(repo_root / line)
    return paths


def list_present_changelog_files(repo_root: Path) -> list[Path]:
    """Return every YAML currently under ``changelog/@unreleased/``.

    Used by the ``release-as`` check, which has to consider all
    unreleased entries (not just the ones added in this PR).
    """
    target = repo_root / UNRELEASED_DIR
    if not target.is_dir():
        return []
    return sorted(p for p in target.iterdir() if p.suffix == ".yml" and p.is_file())


def parse_pr_labels(env_value: str | None) -> set[str]:
    """Parse a comma-separated label list from the workflow env.

    GitHub Actions exposes labels as ``${{ join(github.event.pull_request.labels.*.name, ',') }}``.
    Empty input yields an empty set.
    """
    if not env_value:
        return set()
    return {label.strip() for label in env_value.split(",") if label.strip()}


def check_file_presence(
    pr_number: int,
    added_files: Sequence[Path],
    labels: Iterable[str],
    report: LintReport,
) -> None:
    """Enforce: at least one matching added file, OR the bypass label."""
    if NO_CHANGELOG_LABEL in labels:
        return
    matching = [path for path in added_files if _filename_matches_pr(path.name, pr_number)]
    if not matching:
        report.fail(
            f"PR #{pr_number}: no changelog entry added under "
            f"`{UNRELEASED_DIR}/pr-{pr_number}-<slug>.yml`. "
            f"Add a YAML entry per CONTRIBUTING.md, or apply the "
            f"`{NO_CHANGELOG_LABEL}` label to bypass."
        )


def check_file_naming(
    pr_number: int,
    added_files: Sequence[Path],
    report: LintReport,
) -> None:
    """Enforce: every added YAML matches ``pr-<N>-<slug>.yml`` for *this* PR."""
    for path in added_files:
        match = ENTRY_FILENAME_PATTERN.match(path.name)
        if match is None:
            report.fail(
                f"{path}: filename must match `pr-<N>-<slug>.yml` "
                f"(letters, digits, dashes, underscores in the slug)"
            )
            continue
        embedded_pr = int(match["pr_number"])
        if embedded_pr != pr_number:
            report.fail(
                f"{path}: embedded PR number `{embedded_pr}` does not match "
                f"the current PR number `{pr_number}`"
            )


def _filename_matches_pr(name: str, pr_number: int) -> bool:
    match = ENTRY_FILENAME_PATTERN.match(name)
    if match is None:
        return False
    return int(match["pr_number"]) == pr_number


def check_schema(
    files: Sequence[Path],
    workspace_packages: Sequence[str],
    report: LintReport,
) -> list[ChangelogEntry]:
    """Parse + validate every file. Returns the successfully-parsed entries."""
    parsed: list[ChangelogEntry] = []
    for path in files:
        try:
            entry = parse_entry_file(path)
        except ChangelogValidationError as exc:
            report.fail_for(exc)
            continue
        try:
            validate_packages_against_workspace(entry, workspace_packages)
        except ChangelogValidationError as exc:
            report.fail_for(exc)
            continue
        parsed.append(entry)
    return parsed


def check_release_as_invariant(
    entries: Sequence[ChangelogEntry],
    current_version: str,
    report: LintReport,
) -> None:
    """Run the ``release-as`` validator and surface errors via the report."""
    try:
        validate_release_as(entries, current_version)
    except ChangelogValidationError as exc:
        report.fail_for(exc)


def detect_current_version(repo_root: Path, override: str | None) -> str:
    """Resolve the current ``vX.Y.Z`` tag.

    ``override`` (from ``--current-version`` or ``$CURRENT_VERSION``)
    wins; otherwise ``git describe --tags --abbrev=0 --match 'v*.*.*'``
    is used. Falls back to ``0.0.0`` when no tag exists yet.
    """
    if override:
        return override.lstrip("v")
    try:
        completed = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*.*.*"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return "0.0.0"
    return completed.stdout.strip().lstrip("v")


def run_lint(
    *,
    pr_number: int,
    base_sha: str,
    head_sha: str,
    labels: Iterable[str],
    current_version: str,
    repo_root: Path,
) -> LintReport:
    """Run all four checks. Returns the report; caller decides exit code."""
    report = LintReport()
    workspace_packages = list_workspace_packages(repo_root)

    added_files = list_added_changelog_files(base_sha, head_sha, repo_root=repo_root)

    # Check 1: file presence (skipped under the bypass label).
    check_file_presence(pr_number, added_files, labels, report)

    # Check 2: file naming on every added file.
    check_file_naming(pr_number, added_files, report)

    # Check 3: schema over the union of (added in this PR) plus
    # (already present in the directory). The release-as invariant
    # needs every entry; the schema check catches bad files even
    # under the `no changelog` label so a bypass PR can't sneak in
    # malformed YAML.
    union_files = sorted({*added_files, *list_present_changelog_files(repo_root)})
    parsed_entries = check_schema(union_files, workspace_packages, report)

    # Check 4: release-as invariant.
    if parsed_entries:
        next_version = infer_next_version(current_version, parsed_entries)
        # Surface the inferred version in CI logs to make the
        # release-as failure mode self-explanatory.
        print(
            f"changelog-lint: current={current_version} "
            f"inferred-next={next_version} "
            f"entries={len(parsed_entries)}"
        )
        check_release_as_invariant(parsed_entries, current_version, report)

    return report


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lint changelog/@unreleased/*.yml entries on a PR.",
    )
    parser.add_argument(
        "--pr-number",
        type=int,
        default=_env_int("PR_NUMBER"),
        help="GitHub PR number (default: $PR_NUMBER).",
    )
    parser.add_argument(
        "--base-sha",
        default=os.environ.get("BASE_SHA", ""),
        help="Base SHA of the PR (default: $BASE_SHA).",
    )
    parser.add_argument(
        "--head-sha",
        default=os.environ.get("HEAD_SHA", ""),
        help="Head SHA of the PR (default: $HEAD_SHA).",
    )
    parser.add_argument(
        "--labels",
        default=os.environ.get("PR_LABELS", ""),
        help="Comma-separated PR labels (default: $PR_LABELS).",
    )
    parser.add_argument(
        "--current-version",
        default=os.environ.get("CURRENT_VERSION", ""),
        help=(
            "Current released version (default: $CURRENT_VERSION; "
            "falls back to `git describe --tags --abbrev=0 --match v*.*.*`)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("REPO_ROOT", "."),
        help="Repository root (default: $REPO_ROOT or `.`).",
    )
    return parser.parse_args(argv)


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return int(raw)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.pr_number is None:
        print(
            "changelog-lint: --pr-number (or $PR_NUMBER) is required",
            file=sys.stderr,
        )
        return 2
    if not args.base_sha or not args.head_sha:
        print(
            "changelog-lint: --base-sha and --head-sha (or $BASE_SHA / $HEAD_SHA) are required",
            file=sys.stderr,
        )
        return 2

    repo_root = Path(args.repo_root).resolve()
    current_version = detect_current_version(repo_root, args.current_version or None)
    labels = parse_pr_labels(args.labels)

    report = run_lint(
        pr_number=args.pr_number,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
        labels=labels,
        current_version=current_version,
        repo_root=repo_root,
    )

    if report.has_errors:
        # Render each finding as a GitHub Actions error annotation so
        # they surface in the PR Files Changed view alongside the offending lines.
        for line in report.render().splitlines():
            print(f"::error::{line}")
        print(
            f"\nchangelog-lint: {len(report.render().splitlines())} "
            f"error(s); see annotations above.",
            file=sys.stderr,
        )
        return 1

    print("changelog-lint: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
