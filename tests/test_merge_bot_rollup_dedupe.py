# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the rollup dedupe predicate in merge-bot.yml.

The merge bot (`.github/workflows/merge-bot.yml`) classifies required
checks into `failed` / `pending` / `success` by iterating the
required-contexts list and, per context, piping the GraphQL
`statusCheckRollup` payload through a jq filter that takes the latest
run by `startedAt`. `statusCheckRollup` returns one entry per check
*run*, not per check *name* — a retried check (workflow rerun,
fix-then-push, close+reopen retrigger) appears multiple times, and the
historical FAILURE entry never disappears from the rollup for the
lifetime of the head SHA.

The dedupe step (sort by startedAt, take latest per context name)
collapses each check name down to its most recent run before the
bash `case` classifier buckets it into success / pending / fail.
Without it, a fail-then-pass on the same SHA wedges merge-bot
indefinitely — the bug surfaced on PR #346 / issue #347, where
`changelog-lint` failed on the original `opened` event, was
retriggered green via close+reopen, and the merge call was refused
with `FAILED_CHECKS: changelog-lint` until the stale failed run was
manually deleted via `gh run delete`.

The tests pin the dedupe by extracting the per-context bash loop
straight out of the workflow YAML (the inner jq selector + the `case`
classifier) and running it under bash against hand-rolled rollup
payloads. Pinning the loop body against the workflow file (rather
than copy-pasting it into the test) means a future edit to the
dedupe-or-classifier logic that drifts from this test will fail at
the assert site, not at "the workflow keeps running green but the
bug is back".
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "merge-bot.yml"


def _load_inspect_required_checks_step() -> str:
    """Return the bash body of the `Inspect required checks` step."""
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["merge"]["steps"]
    for step in steps:
        if step.get("name") == "Inspect required checks":
            run = step["run"]
            assert isinstance(run, str)
            return run
    raise AssertionError("Inspect required checks step not found in merge-bot.yml")


_STEP_BODY = _load_inspect_required_checks_step()


def _extract_classifier_loop(step_body: str) -> str:
    """Pull the per-context classifier loop body out of the step.

    The merge bot's `Inspect required checks` step iterates
    `REQUIRED_CONTEXTS` and, per context, runs a `jq` selector that
    sorts by `startedAt` and takes the latest matching entry, then a
    `case` classifier that buckets it into success / pending / fail.
    Extracting the loop verbatim — rather than copying the jq selector
    or the `case` arms into the test source — keeps the test honest:
    a future edit that weakens the dedupe (drops `sort_by`, flips
    `(.[-1])` to `(.[0])`, removes the `select((.workflowName // "")
    != "Merge Bot")` self-filter, etc.) will surface here at an assert
    site, not as a silently-passing test against a dead copy.
    """
    pattern = (
        r'^(?P<loop>( *)fail=""\n'
        r'\2pending=""\n'
        r"\2while IFS= read -r ctx; do\n"
        r".*?\n"
        r'\2done <<<"\$\{REQUIRED_CONTEXTS\}")'
    )
    match = re.search(pattern, step_body, flags=re.DOTALL | re.MULTILINE)
    assert match is not None, (
        "could not locate the per-context classifier loop in the "
        "`Inspect required checks` step. The harness pin against "
        "merge-bot.yml has drifted; update the extractor."
    )
    return match.group("loop")


_CLASSIFIER_LOOP = _extract_classifier_loop(_STEP_BODY)


def _classify(
    rollup: list[dict[str, Any]],
    contexts: list[str],
) -> tuple[list[str], list[str]]:
    """Run the extracted classifier loop against `rollup` for `contexts`.

    Returns `(failed, pending)` — the names that the merge bot would
    bucket as failing or pending, respectively, for the given fixture
    rollup and required-context list. `success` is the implicit third
    bucket: any context not in either returned list.

    The extracted loop reads `${rollup}` and `${REQUIRED_CONTEXTS}`
    from the environment of the bash invocation; the wrapper here
    sets both, runs the loop, then prints the post-`awk 'NF'` `fail`
    and `pending` strings on disjoint stdout lines so we can split
    them back into Python lists.
    """
    script = (
        "set -euo pipefail\n"
        'rollup="${ROLLUP}"\n' + _CLASSIFIER_LOOP + "\n"
        # Same post-loop tidy-up the workflow performs before writing
        # to GITHUB_OUTPUT; included so the test exercises the same
        # final shape the downstream `Refuse to merge` / `Wait for
        # pending checks` steps see.
        "fail=\"$(printf '%s' \"${fail}\" | awk 'NF')\"\n"
        "pending=\"$(printf '%s' \"${pending}\" | awk 'NF')\"\n"
        "printf 'FAIL_BEGIN\\n%s\\nFAIL_END\\nPENDING_BEGIN\\n%s\\nPENDING_END\\n' "
        '"${fail}" "${pending}"\n'
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        env={
            "ROLLUP": json.dumps(rollup),
            "REQUIRED_CONTEXTS": "\n".join(contexts),
            "PATH": os.environ.get("PATH", ""),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return _parse_buckets(proc.stdout)


def _parse_buckets(stdout: str) -> tuple[list[str], list[str]]:
    """Split the bash wrapper's stdout into `(failed, pending)` lists."""
    fail_match = re.search(r"FAIL_BEGIN\n(.*?)\nFAIL_END", stdout, re.DOTALL)
    pending_match = re.search(r"PENDING_BEGIN\n(.*?)\nPENDING_END", stdout, re.DOTALL)
    assert fail_match is not None, f"no FAIL_BEGIN block in stdout: {stdout!r}"
    assert pending_match is not None, f"no PENDING_BEGIN block in stdout: {stdout!r}"
    failed = [line for line in fail_match.group(1).splitlines() if line]
    pending = [line for line in pending_match.group(1).splitlines() if line]
    return failed, pending


# Reference rollup entries used across the table-driven cases. Mirroring
# the shape `gh pr view --json statusCheckRollup` returns: `name`,
# `conclusion`, `status`, `startedAt` for Actions check-runs;
# `context`, `state` for legacy commit statuses.

# --- failure bucket ----------------------------------------------------


def test_failed_empty_when_latest_run_per_name_succeeded() -> None:
    """The bug from issue #347: fail-then-pass must read as 'currently passing'.

    `changelog-lint` failed on the first run and passed on the
    retrigger. With dedupe, the latest entry per name is the SUCCESS,
    so `failed` is empty and the bot proceeds to merge.
    """
    rollup = [
        {
            "name": "changelog-lint",
            "conclusion": "FAILURE",
            "status": "COMPLETED",
            "startedAt": "2026-04-26T04:04:06Z",
        },
        {
            "name": "changelog-lint",
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
            "startedAt": "2026-04-26T04:16:24Z",
        },
        {
            "name": "pr-lint",
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
            "startedAt": "2026-04-26T04:00:00Z",
        },
    ]
    failed, pending = _classify(rollup, ["changelog-lint", "pr-lint"])
    assert failed == []
    assert pending == []


def test_failed_reports_name_when_latest_run_is_failure() -> None:
    """Inverse of the dedupe case: pass-then-fail must still hard-fail.

    The dedupe must not become a "drop FAILUREs blindly" filter — if
    the most recent run for a name is a FAILURE, the bot must still
    refuse the merge.
    """
    rollup = [
        {
            "name": "pytest",
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
            "startedAt": "2026-04-26T04:00:00Z",
        },
        {
            "name": "pytest",
            "conclusion": "FAILURE",
            "status": "COMPLETED",
            "startedAt": "2026-04-26T04:30:00Z",
        },
    ]
    failed, pending = _classify(rollup, ["pytest"])
    assert failed == ["pytest"]
    assert pending == []


def test_failed_handles_mixed_names_with_multiple_history_each() -> None:
    """Only one entry per name is evaluated, even with deep history.

    Three names, each with two historical runs:
      - alpha: FAILURE then SUCCESS   -> ok, drops out of `failed`.
      - beta:  SUCCESS then FAILURE   -> latest is FAILURE, surfaces.
      - gamma: FAILURE then FAILURE   -> latest is FAILURE, surfaces.
    """
    rollup = [
        {"name": "alpha", "conclusion": "FAILURE", "startedAt": "2026-04-26T04:00:00Z"},
        {"name": "alpha", "conclusion": "SUCCESS", "startedAt": "2026-04-26T04:10:00Z"},
        {"name": "beta", "conclusion": "SUCCESS", "startedAt": "2026-04-26T04:00:00Z"},
        {"name": "beta", "conclusion": "FAILURE", "startedAt": "2026-04-26T04:10:00Z"},
        {"name": "gamma", "conclusion": "FAILURE", "startedAt": "2026-04-26T04:00:00Z"},
        {"name": "gamma", "conclusion": "FAILURE", "startedAt": "2026-04-26T04:10:00Z"},
    ]
    failed, pending = _classify(rollup, ["alpha", "beta", "gamma"])
    assert sorted(failed) == ["beta", "gamma"]
    assert pending == []


def test_failed_excludes_merge_bot_own_runs() -> None:
    """The dedupe must run *after* the merge-bot self-filter.

    A previous merge-bot run that failed must not be considered a
    failure, regardless of how recent its startedAt is. Without the
    self-filter the bot would refuse to merge forever after its own
    first failure; the dedupe being upstream of it would not change
    that — but a future edit that swaps the order should still pass
    this test.
    """
    rollup = [
        {
            "name": "Merge ==COMMIT_MSG== block as squash body",
            "workflowName": "Merge Bot",
            "conclusion": "FAILURE",
            "startedAt": "2026-04-26T05:00:00Z",
        },
        {
            "name": "pr-lint",
            "conclusion": "SUCCESS",
            "startedAt": "2026-04-26T04:00:00Z",
        },
    ]
    # `Merge ==COMMIT_MSG== block as squash body` is intentionally
    # listed in the required contexts to prove the self-filter
    # short-circuits before the classifier sees the entry: with the
    # filter active the context falls through to "missing" and lands
    # in `pending`; without it, the entry's FAILURE conclusion would
    # surface in `failed`.
    failed, pending = _classify(
        rollup,
        ["pr-lint", "Merge ==COMMIT_MSG== block as squash body"],
    )
    assert failed == []
    assert pending == ["Merge ==COMMIT_MSG== block as squash body"]


def test_failed_classifies_legacy_commit_status_via_context() -> None:
    """Legacy commit statuses use `context` + `state`, not `name` + `conclusion`.

    The classifier falls back to `.context` for the match key and
    `.state` for the conclusion so legacy statuses get the same
    fail-then-pass treatment as Actions check-runs.
    """
    rollup = [
        {"context": "ci/jenkins", "state": "FAILURE", "startedAt": "2026-04-26T04:00:00Z"},
        {"context": "ci/jenkins", "state": "SUCCESS", "startedAt": "2026-04-26T04:10:00Z"},
    ]
    failed, pending = _classify(rollup, ["ci/jenkins"])
    assert failed == []
    assert pending == []


# --- pending bucket ----------------------------------------------------


def test_pending_empty_when_stale_in_progress_was_superseded_by_success() -> None:
    """Stale IN_PROGRESS from a cancelled run must not pin the wait path.

    The bot exits cleanly (and waits for `check_suite.completed`) when
    `pending` is non-empty. Without the latest-run dedupe, an
    abandoned IN_PROGRESS entry — common after a cancelled rerun —
    keeps the bot in the wait-clean-exit branch even though every
    check has since completed. With dedupe, the latest SUCCESS entry
    wins and the bot proceeds to merge.
    """
    rollup = [
        {
            "name": "pytest",
            "conclusion": "",
            "status": "IN_PROGRESS",
            "startedAt": "2026-04-26T03:00:00Z",
        },
        {
            "name": "pytest",
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
            "startedAt": "2026-04-26T04:00:00Z",
        },
    ]
    failed, pending = _classify(rollup, ["pytest"])
    assert failed == []
    assert pending == []


def test_pending_reports_name_when_latest_run_is_in_progress() -> None:
    """A genuinely-running rerun after an old completion is still pending.

    The classifier reads `.conclusion` first; an IN_PROGRESS entry
    has an empty / missing conclusion, which under `ascii_downcase`
    becomes the empty string and falls through the empty/null/missing
    `case` arm into the `pending` bucket. (The `status` field isn't
    consulted; the empty-conclusion path is the workflow's signal for
    "still running".)
    """
    rollup = [
        {
            "name": "pytest",
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
            "startedAt": "2026-04-26T04:00:00Z",
        },
        {
            "name": "pytest",
            "conclusion": "",
            "status": "IN_PROGRESS",
            "startedAt": "2026-04-26T04:30:00Z",
        },
    ]
    failed, pending = _classify(rollup, ["pytest"])
    assert failed == []
    assert pending == ["pytest"]


# --- regression-pin: classifier extracted, not invented ----------------


def test_classifier_pins_dedupe_against_workflow_yaml() -> None:
    """Defence-in-depth: the loop body must keep the dedupe primitives.

    `_classify` relies on the extracted loop containing both the
    `sort_by(.startedAt)` clause and the `(.[-1])` "take latest"
    selection. A future edit that drops either — say, by replacing
    `sort_by` with a no-op `select(true)` or flipping `(.[-1])` to
    `(.[0])` — would silently wedge the bot on the issue #347
    fail-then-pass case. Pin the structural shape so the only way to
    silence this test is to keep the dedupe primitives intact, which
    is exactly the invariant issue #347 calls out.
    """
    assert (
        "sort_by(.startedAt" in _CLASSIFIER_LOOP
    ), "extracted loop is missing the `sort_by(.startedAt)` dedupe primitive"
    assert (
        "(.[-1]" in _CLASSIFIER_LOOP
    ), "extracted loop is missing the `(.[-1])` 'take latest' selector"
    assert (
        'workflowName // ""' in _CLASSIFIER_LOOP and "Merge Bot" in _CLASSIFIER_LOOP
    ), "extracted loop is missing the merge-bot self-filter"


def test_classifier_handles_empty_rollup() -> None:
    """Empty rollup with required contexts: every context buckets as pending.

    `missing` is the workflow's sentinel for "context exists in
    branch protection but no run reported yet" — bucketed as pending
    so the bot waits rather than refusing.
    """
    failed, pending = _classify([], ["alpha", "beta"])
    assert failed == []
    assert sorted(pending) == ["alpha", "beta"]


@pytest.mark.parametrize("contexts", [[], [""]])
def test_classifier_handles_empty_required_contexts(contexts: list[str]) -> None:
    """No required contexts (or only blank lines) yields empty buckets.

    The fail-closed branch upstream of this step refuses the merge
    when `REQUIRED_SOURCE == "empty"`, so the loop never runs against
    a truly-empty contexts list in production. Pin the shape anyway
    so a future refactor that lets this code path execute won't
    silently bypass classification.
    """
    failed, pending = _classify([{"name": "ignored"}], contexts)
    assert failed == []
    assert pending == []
