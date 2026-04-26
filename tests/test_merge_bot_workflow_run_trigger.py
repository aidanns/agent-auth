# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Static-pin tests for the merge-bot's workflow_run trigger surface.

The merge bot (`.github/workflows/merge-bot.yml`) used to trigger on
`check_suite: completed` to refire once CI went green AFTER the
`automerge` label was applied. In practice that event never fired
for this repo: GitHub's documented anti-recursion rule suppresses
`check_suite` events for workflows authenticated with the default
`GITHUB_TOKEN`, and every CI workflow in this repo runs under that
token. The bug surfaced on PR #346 — the bot only ran when the
contributor's label-add coincidentally landed after CI was already
green — and was tracked as issue #348.

The fix swapped `check_suite: completed` for `workflow_run: completed`
with each PR-gating CI workflow listed by name. `workflow_run` events
fire from `GITHUB_TOKEN`-authenticated workflows; the watched-workflows
list is enumerated explicitly so adding a new CI workflow requires
conscious wiring into the merge-bot trigger surface.

These tests pin the public-facing shape of that fix:
  - `on:` declares `workflow_run: types: [completed]` and lists every
    expected workflow.
  - `on:` no longer declares `check_suite`.
  - The pre-filter `if:` recognises the `workflow_run` event and gates
    on `workflow_run.conclusion == 'success'`.
  - The `Resolve target PR` step has a `workflow_run)` case arm that
    reads `github.event.workflow_run.head_sha`.
  - The concurrency-group key includes `workflow_run.head_sha` as a
    fallback (so two triggers on the same SHA serialise correctly).

Test placement: tests/ alongside test_merge_bot_rollup_dedupe.py
(merged in PR #350) — same merge-bot.yml surface, same yaml-loading
shape, same regression-pin pattern.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "merge-bot.yml"

# Every workflow name expected to feed merge-bot via workflow_run. The
# list MUST stay in sync with merge-bot.yml. Drift in either direction
# (workflow renamed, new required workflow added without updating the
# merge-bot list) breaks the bot's refire-on-CI-green path silently —
# pinning the exact set here surfaces the drift at test time. See
# issue #348 for the rationale; the list excludes Merge Bot itself
# (anti-recursion), release / publish / scorecard / dependency-
# submission / mutation / benchmark workflows that don't run on PRs,
# and Release Tag (only fires on PR `closed`, well after merge).
EXPECTED_WORKFLOWS: frozenset[str] = frozenset(
    {
        "Test",
        "Check",
        "Typecheck",
        "CodeQL",
        "PR Lint",
        "DCO",
        "Changelog Lint",
        "REUSE",
        "Dependency Review",
        "Verify Design",
        "Verify Function Tests",
        "Verify Standards",
        "Verify Token CLI / HTTP Parity",
        "Changelog Bot",
    }
)


def _load_workflow() -> dict[Any, Any]:
    return cast("dict[Any, Any]", yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8")))


# `on` is parsed as the Python boolean key `True` by PyYAML 1.1 semantics
# (the YAML 1.1 spec treats `on` / `off` / `yes` / `no` as booleans).
# Look it up via either key so the test is robust to PyYAML version drift.
# Hence the dict key type is Any: a string under modern PyYAML, the
# boolean True under YAML 1.1 strict parsers.
def _on_block(workflow: dict[Any, Any]) -> dict[str, Any]:
    if "on" in workflow:
        return cast("dict[str, Any]", workflow["on"])
    if True in workflow:
        return cast("dict[str, Any]", workflow[True])
    raise AssertionError("merge-bot.yml has no `on:` block")


def test_on_block_declares_workflow_run_completed() -> None:
    """The bot must trigger on `workflow_run: types: [completed]`.

    `workflow_run` is the only trigger that fires from upstream
    workflows authenticated with the default `GITHUB_TOKEN`; without it
    the bot never refires when CI goes green and the `automerge` label
    becomes a footgun (issue #348).
    """
    on_block = _on_block(_load_workflow())
    assert "workflow_run" in on_block, (
        "merge-bot.yml must declare `workflow_run` in its `on:` block; "
        "without it, CI-green retriggers never fire (issue #348)."
    )
    workflow_run = on_block["workflow_run"]
    assert workflow_run.get("types") == [
        "completed"
    ], "merge-bot.yml `workflow_run` must subscribe to `[completed]`."


def test_on_block_does_not_declare_check_suite() -> None:
    """Belt-and-braces is rejected: `check_suite` never delivered.

    Keeping `check_suite` alongside `workflow_run` is just clutter
    because GitHub's anti-recursion rule suppresses `check_suite` for
    GITHUB_TOKEN-authenticated upstream workflows. Drop it.
    """
    on_block = _on_block(_load_workflow())
    assert "check_suite" not in on_block, (
        "merge-bot.yml must NOT declare `check_suite` — it never "
        "delivers for GITHUB_TOKEN-authenticated upstream workflows "
        "and is just clutter (issue #348)."
    )


def test_workflow_run_lists_every_expected_workflow() -> None:
    """The watched-workflows set must match the curated list exactly.

    Adding a new required-check workflow without wiring it into the
    merge-bot's `workflow_run.workflows` list silently regresses the
    bot back to the "only fires on label toggle" failure mode for that
    workflow. Removing one without updating this test lets dead
    entries accumulate. Pin the set so drift in either direction
    surfaces here.
    """
    on_block = _on_block(_load_workflow())
    workflows = on_block["workflow_run"].get("workflows")
    assert isinstance(
        workflows, list
    ), "merge-bot.yml `workflow_run.workflows` must be a YAML list."
    actual = set(workflows)
    missing = EXPECTED_WORKFLOWS - actual
    extra = actual - EXPECTED_WORKFLOWS
    assert not missing and not extra, (
        f"merge-bot.yml watched-workflows drift: "
        f"missing={sorted(missing)} extra={sorted(extra)}. "
        f"Update both merge-bot.yml and EXPECTED_WORKFLOWS in this test."
    )


def test_every_expected_workflow_exists_in_repo() -> None:
    """Each watched workflow name must resolve to a real workflow file.

    `workflow_run` matches by the upstream workflow's `name:` field;
    a typo here means the bot silently doesn't refire for that
    workflow. Walk `.github/workflows/*.yml` and confirm every name
    in the watched list has a matching `name:`.
    """
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    actual_names = set()
    for path in workflows_dir.glob("*.yml"):
        if path.name == "merge-bot.yml":
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("name"), str):
            actual_names.add(data["name"])
    missing = EXPECTED_WORKFLOWS - actual_names
    assert not missing, (
        f"merge-bot.yml watches workflows that don't exist (renamed "
        f"or deleted?): {sorted(missing)}. `workflow_run` matches by "
        f"the upstream workflow's `name:` field — a typo here means "
        f"the bot silently won't refire for that workflow."
    )


def test_pre_filter_recognises_workflow_run_success() -> None:
    """The job `if:` must gate `workflow_run` on `conclusion == 'success'`.

    The pre-filter saves us from burning a runner on every label
    event and every workflow_run event — only the `automerge` label
    add and successful workflow_run completions should reach the
    steps. Pin the exact predicate so a regression in the boolean
    structure (e.g. dropping the conclusion check, or matching on
    `status` instead of `conclusion`) shows up here.
    """
    workflow = _load_workflow()
    job = workflow["jobs"]["merge"]
    if_clause = job["if"]
    assert (
        "github.event_name == 'workflow_run'" in if_clause
    ), "merge-bot.yml job `if:` must recognise `workflow_run` events."
    assert "github.event.workflow_run.conclusion == 'success'" in if_clause, (
        "merge-bot.yml job `if:` must gate `workflow_run` events on "
        "`workflow_run.conclusion == 'success'`."
    )
    # The old `check_suite` predicate must not linger.
    assert "check_suite" not in if_clause, (
        "merge-bot.yml job `if:` still references `check_suite`; "
        "it should reference `workflow_run` only (issue #348)."
    )


def test_resolve_target_pr_step_handles_workflow_run() -> None:
    """The `Resolve target PR` case block must have a `workflow_run)` arm.

    The arm sources the head SHA from `github.event.workflow_run.head_sha`
    and reuses the same `gh pr list --search <sha> --label automerge`
    lookup the old `check_suite)` arm used. Without the rename, the
    bot's case statement drops through to the default and resolves no
    PR — every refire becomes a silent no-op.
    """
    workflow = _load_workflow()
    steps = workflow["jobs"]["merge"]["steps"]
    resolve_step = next((s for s in steps if s.get("name") == "Resolve target PR"), None)
    assert resolve_step is not None, "merge-bot.yml is missing the `Resolve target PR` step."
    run_body = resolve_step["run"]
    assert "workflow_run)" in run_body, (
        "merge-bot.yml `Resolve target PR` must have a `workflow_run)` " "case arm."
    )
    # The head-SHA env var must be wired from the workflow_run payload.
    env = resolve_step.get("env", {})
    head_sha_value = env.get("WORKFLOW_RUN_HEAD_SHA", "")
    assert "github.event.workflow_run.head_sha" in head_sha_value, (
        "merge-bot.yml `Resolve target PR` must read the head SHA from "
        "`github.event.workflow_run.head_sha`."
    )
    # The stale `check_suite)` arm must be gone.
    assert "check_suite)" not in run_body, (
        "merge-bot.yml `Resolve target PR` still has a `check_suite)` "
        "case arm; it should be `workflow_run)` (issue #348)."
    )


def test_concurrency_group_includes_workflow_run_head_sha() -> None:
    """The concurrency-group key must fall back to `workflow_run.head_sha`.

    Two simultaneous triggers on the same head SHA (one from a label
    add, one from a workflow_run completion) must serialise on the
    same group key. Without the `workflow_run.head_sha` fallback, the
    workflow_run trigger's group key collapses to `merge-bot-` (the
    PR number is unset on workflow_run events) and every workflow_run
    trigger contends on the same singleton group regardless of PR.
    """
    workflow = _load_workflow()
    group_expr = workflow["concurrency"]["group"]
    assert "github.event.workflow_run.head_sha" in group_expr, (
        "merge-bot.yml concurrency-group key must include "
        "`github.event.workflow_run.head_sha` as a fallback."
    )
    assert "github.event.check_suite.head_sha" not in group_expr, (
        "merge-bot.yml concurrency-group key still references "
        "`check_suite.head_sha`; it should reference "
        "`workflow_run.head_sha` (issue #348)."
    )
