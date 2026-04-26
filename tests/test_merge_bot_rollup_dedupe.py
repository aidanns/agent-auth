# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the rollup dedupe predicate in merge-bot.yml.

The merge bot (`.github/workflows/merge-bot.yml`) classifies required
checks into `failed` / `pending` / `success` by piping the GraphQL
`statusCheckRollup` payload through a jq filter. `statusCheckRollup`
returns one entry per check *run*, not per check *name* — a retried
check (workflow rerun, fix-then-push, close+reopen retrigger) appears
multiple times, and the historical FAILURE entry never disappears
from the rollup for the lifetime of the head SHA.

The dedupe step (group by name+context, keep latest by startedAt)
collapses each check name down to its most recent run before the
failure / pending predicates evaluate the rollup. Without it, a
fail-then-pass on the same SHA wedges merge-bot indefinitely — the
bug surfaced on PR #346 / issue #347, where `changelog-lint` failed
on the original `opened` event, was retriggered green via close+reopen,
and the merge call was refused with `FAILED_CHECKS: changelog-lint`
until the stale failed run was manually deleted via `gh run delete`.

The tests pin both selectors (failed *and* pending) by extracting the
jq blocks straight out of the workflow YAML and feeding them
hand-rolled rollup payloads. Pinning the predicates against the
workflow file (rather than copy-pasting them into the test) means a
future edit to the dedupe-or-predicate logic that drifts from this
test will fail at the assert site, not at "the workflow keeps running
green but the bug is back".
"""

from __future__ import annotations

import json
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


def _extract_jq_filter(variable: str) -> str:
    """Pull a `<variable>="$(jq -r '...' <<<"${rollup}")"` filter body.

    The bot writes both selectors as multi-line jq programs assigned
    to `failed=` and `pending=`. Pulling them out via a regex keeps the
    test honest — the test exercises the *actual* filter the bot runs,
    not a hand-typed copy that can silently drift.
    """
    pattern = (
        rf"{re.escape(variable)}=\"\$\(jq -r '\n"
        r"(?P<filter>.*?)\n"
        r"\s*' <<<\"\$\{rollup\}\"\)\""
    )
    match = re.search(pattern, _STEP_BODY, flags=re.DOTALL)
    assert match is not None, f"could not find jq filter for `{variable}=` in workflow"
    return match.group("filter")


_FAILED_FILTER = _extract_jq_filter("failed")
_PENDING_FILTER = _extract_jq_filter("pending")


def _run_jq(filter_body: str, rollup: list[dict[str, Any]]) -> list[str]:
    """Run jq -r over `rollup` with the workflow's filter; return name lines."""
    proc = subprocess.run(
        ["jq", "-r", filter_body],
        input=json.dumps(rollup),
        capture_output=True,
        text=True,
        check=True,
    )
    # The filter emits one name per line via `... | .[]`. An empty stdout
    # means no entries matched (e.g. nothing failed, nothing pending).
    return [line for line in proc.stdout.splitlines() if line]


# Reference rollup entries used across the table-driven cases. Mirroring
# the shape `gh pr view --json statusCheckRollup` returns: `name`,
# `conclusion`, `status`, `startedAt` for Actions check-runs;
# `context`, `state` for legacy commit statuses.

# --- failure selector --------------------------------------------------


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
    assert _run_jq(_FAILED_FILTER, rollup) == []


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
    assert _run_jq(_FAILED_FILTER, rollup) == ["pytest"]


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
    assert sorted(_run_jq(_FAILED_FILTER, rollup)) == ["beta", "gamma"]


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
    assert _run_jq(_FAILED_FILTER, rollup) == []


def test_failed_includes_legacy_commit_status_via_context() -> None:
    """Legacy commit statuses use `context` + `state`, not `name` + `conclusion`.

    The dedupe falls back to `.context` for the group key so legacy
    statuses get the same fail-then-pass treatment as Actions check-runs.
    """
    rollup = [
        {"context": "ci/jenkins", "state": "FAILURE", "startedAt": "2026-04-26T04:00:00Z"},
        {"context": "ci/jenkins", "state": "SUCCESS", "startedAt": "2026-04-26T04:10:00Z"},
    ]
    assert _run_jq(_FAILED_FILTER, rollup) == []


# --- pending selector --------------------------------------------------


def test_pending_empty_when_stale_in_progress_was_superseded_by_success() -> None:
    """Stale IN_PROGRESS from a cancelled run must not pin the wait path.

    The bot exits cleanly (and waits for `check_suite.completed`) when
    `pending` is non-empty. Without dedupe on the pending selector, an
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
    assert _run_jq(_PENDING_FILTER, rollup) == []


def test_pending_reports_name_when_latest_run_is_in_progress() -> None:
    """A genuinely-running rerun after an old completion is still pending."""
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
    assert _run_jq(_PENDING_FILTER, rollup) == ["pytest"]


# --- regression-pin: filters extracted, not invented -------------------


def test_dedupe_step_present_in_both_selectors() -> None:
    """Defence-in-depth: the test relies on the dedupe being in *both* filters.

    A future edit that removes the dedupe from one selector (say,
    pending) but leaves the other intact would pass the
    fail-then-pass case but reintroduce the stale-IN_PROGRESS bug.
    Pin the structural shape so the only way to silence this test is
    to keep the dedupe in both filters — exactly the invariant issue
    #347 calls out.
    """
    for name, filter_body in [("failed", _FAILED_FILTER), ("pending", _PENDING_FILTER)]:
        assert "group_by" in filter_body, f"{name} filter is missing group_by"
        assert "max_by" in filter_body, f"{name} filter is missing max_by"


@pytest.mark.parametrize("filter_body", [_FAILED_FILTER, _PENDING_FILTER])
def test_filters_handle_empty_rollup(filter_body: str) -> None:
    """Empty rollup is valid input; both selectors must return zero names."""
    assert _run_jq(filter_body, []) == []
