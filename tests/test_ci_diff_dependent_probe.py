# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Static-pin tests for the verified partial-rerun on label events.

The CI parent (`.github/workflows/ci.yml`) used to declare
`pull_request: types: [opened, synchronize, reopened, ready_for_review]`,
omitting `labeled` / `unlabeled`. As a result, applying or removing a
label after `gh pr create` did NOT re-fire ci.yml — the
`check-changelog/exists` child evaluated `[[ ",${PR_LABELS}," ==
*",no changelog,"* ]]` against the original `labels=[]` payload and
emitted a stale-failure status that blocked merging. The recurring
workaround was to push an empty commit per PR to re-fire CI; that paid
the full ~5-10 minute CI cost on every label flip.

Issue #527 fixed this in three coupled phases (Option 4 — verified
partial re-run):

1. ``plan`` job's ``Probe prior run state on this head SHA`` step
   queries the Checks API for prior conclusions on the head SHA on
   ``labeled`` / ``unlabeled`` events; sets the
   ``diff_dependent_jobs_already_passed`` job output to ``true`` when
   every diff-dependent child has a non-failing conclusion already.
2. Every diff-dependent ci.yml ``<job>:`` block carries
   ``if: needs.plan.outputs.diff_dependent_jobs_already_passed !=
   'true'`` so it skips on verified-prior-success label flips.
3. ``required-checks-passed`` aggregator gets a tight carve-out: when
   the flag is ``true``, ``skipped`` results on the diff-dependent
   children specifically map to SUCCESS (relaxing the #441 strict
   contract for that specific case only).
4. ``pull_request: types:`` adds ``labeled, unlabeled`` so the
   re-fire actually happens.

These tests pin the public-facing shape of those four properties.
Drift in either direction (a new diff-dependent child added without
the ``if:`` gate, the carve-out widened beyond the verified-prior-
success case, the ``types:`` list narrowed back) breaks the safety
property silently — the tests surface it at PR time instead.

Test placement: tests/ alongside test_merge_bot_workflow_run_trigger.py
— same workflow-yaml-loading pattern, same regression-pin shape.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
HELPER_PATH = REPO_ROOT / "scripts" / "ci" / "diff-dependent-jobs.sh"

# Diff-dependent ci.yml job IDs — the set on which the verified-prior-
# success skip is allowed. The test below cross-checks this against
# (a) the helper script's output by deriving the same set from the
# aggregator's needs and (b) the aggregator's DIFF_DEPENDENT_JOB_IDS
# env entry. Drift across the three locations breaks the carve-out.
DIFF_DEPENDENT_JOB_IDS: frozenset[str] = frozenset(
    {
        "build",
        "check-docs",
        "check-fmt",
        "check-license-allowlist",
        "check-lint",
        "check-publish",
        "check-release",
        "check-security",
        "check-standards",
        "test-integration",
        "test-smoke",
        "test-system",
        "test-unit",
        "test-workspace",
    }
)

# Metadata-dependent children — keep the unconditional `needs: [plan]`
# on every event because their evaluation reads PR metadata
# (`pull_request.labels`, `pull_request.title`, `pull_request.body`,
# DCO sign-off chain, etc.) that can differ between events on the
# same head SHA.
METADATA_DEPENDENT_JOB_IDS: frozenset[str] = frozenset(
    {
        "check-changelog",
        "check-pull-request",
    }
)

# The diff-dependent gate's conditional, spelled exactly as it must
# appear in ci.yml. Yaml booleans `true` / `false` are GitHub Actions
# expression-language strings, not YAML booleans, so quoting matters.
DIFF_DEPENDENT_GATE = "needs.plan.outputs.diff_dependent_jobs_already_passed != 'true'"


def _load_workflow() -> dict[Any, Any]:
    return cast(
        "dict[Any, Any]",
        yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8")),
    )


# `on` is parsed as the Python boolean key `True` by PyYAML 1.1
# semantics. Look it up via either key so the test is robust to
# PyYAML version drift. Mirrors the helper in
# test_merge_bot_workflow_run_trigger.py.
def _on_block(workflow: dict[Any, Any]) -> dict[str, Any]:
    if "on" in workflow:
        return cast("dict[str, Any]", workflow["on"])
    if True in workflow:
        return cast("dict[str, Any]", workflow[True])
    raise AssertionError("ci.yml has no `on:` block")


def test_pull_request_types_includes_labeled_and_unlabeled() -> None:
    """``pull_request: types:`` must include ``labeled, unlabeled``.

    Without these, ci.yml never re-fires when an orchestrator applies
    ``no changelog`` after ``gh pr create`` — the meta-circular case
    issue #527 documents (the PR fixing this issue itself paid the
    empty-commit-retrigger cost because its base branch lacked the
    trigger). Pinning the set here surfaces a future narrowing
    immediately.
    """
    on_block = _on_block(_load_workflow())
    pull_request = on_block.get("pull_request")
    assert isinstance(pull_request, dict), "ci.yml must declare pull_request as a mapping"
    types = pull_request.get("types")
    assert isinstance(types, list), "pull_request.types must be a YAML list"
    for required in (
        "opened",
        "synchronize",
        "reopened",
        "ready_for_review",
        "labeled",
        "unlabeled",
    ):
        assert required in types, (
            f"pull_request.types missing '{required}' — without it the "
            f"verified partial re-run path can never fire (issue #527)."
        )


def test_plan_job_emits_diff_dependent_jobs_already_passed_output() -> None:
    """The ``plan`` job must surface the verified-prior-success flag.

    Downstream child gates and the aggregator carve-out both consume
    ``needs.plan.outputs.diff_dependent_jobs_already_passed``; if the
    output is renamed or dropped, every gate silently degrades to
    ``true`` (the ``!= 'true'`` becomes ``!= ''`` which is also
    truthy → children always skip → aggregator fails). Hard-pin the
    name.
    """
    workflow = _load_workflow()
    plan_outputs = workflow["jobs"]["plan"].get("outputs", {})
    assert "diff_dependent_jobs_already_passed" in plan_outputs, (
        "plan job must emit `diff_dependent_jobs_already_passed` output "
        "(issue #527 / Option 4). Downstream `if:` gates and aggregator "
        "carve-out depend on the exact name."
    )
    # Sanity: it must reference the `prior` step's output.
    expr = plan_outputs["diff_dependent_jobs_already_passed"]
    assert "steps.prior.outputs.diff_dependent_jobs_already_passed" in expr, (
        "plan output must source from `steps.prior.outputs."
        "diff_dependent_jobs_already_passed` to keep the contract "
        "auditable (one place defines the value)."
    )


def test_plan_job_has_probe_prior_run_state_step() -> None:
    """The ``plan`` job must run the Checks-API probe step.

    Walk the steps list looking for one with ``id: prior`` and a name
    that mentions probing. The step body's exact shell is not pinned
    here (lines change with comment edits) but the step's existence is.
    """
    workflow = _load_workflow()
    steps = workflow["jobs"]["plan"]["steps"]
    matching = [s for s in steps if s.get("id") == "prior"]
    assert len(matching) == 1, (
        "plan job must have exactly one step with `id: prior` — the "
        "Checks-API probe (issue #527). Found "
        f"{len(matching)}."
    )
    step = matching[0]
    assert "Probe" in step.get("name", ""), (
        "plan job's `prior` step must have a `name:` mentioning "
        "'Probe' so the run logs are scannable."
    )
    # The probe needs HEAD_SHA, EVENT_ACTION, and GH_TOKEN via env so
    # user-controlled label names cannot inject shell syntax. The
    # values themselves are tested via the helper-script tests below.
    env = step.get("env", {})
    for key in ("HEAD_SHA", "EVENT_ACTION", "GH_TOKEN"):
        assert key in env, (
            f"probe step's env block must declare {key!r}; the shell "
            f"body reads it through ${{{key}}} (no inline interpolation)."
        )


def test_diff_dependent_children_carry_the_if_gate() -> None:
    """Every diff-dependent child must skip on verified-prior-success.

    The gate's literal text is pinned — ``!= 'true'`` not ``== 'false'``
    so an unset value (the safe default on non-label events) treats
    the children as still needing to run.
    """
    workflow = _load_workflow()
    jobs = workflow["jobs"]
    for jid in DIFF_DEPENDENT_JOB_IDS:
        assert jid in jobs, (
            f"ci.yml job ID {jid!r} listed in DIFF_DEPENDENT_JOB_IDS "
            f"is not in the actual workflow — update one or the other."
        )
        actual = jobs[jid].get("if")
        assert actual == DIFF_DEPENDENT_GATE, (
            f"ci.yml job {jid!r} must carry `if: {DIFF_DEPENDENT_GATE}` "
            f"so it skips on verified-prior-success label re-runs "
            f"(issue #527). Got: {actual!r}."
        )


def test_metadata_dependent_children_have_no_if_gate() -> None:
    """Metadata-dependent children must run on every event.

    ``check-changelog`` reads ``pull_request.labels``;
    ``check-pull-request`` houses the DCO chain plus future pr-lint
    metadata validators. Both must re-evaluate on label flips, which
    means NO ``if:`` gate on the parent ci.yml ``<job>:`` block.
    """
    workflow = _load_workflow()
    for jid in METADATA_DEPENDENT_JOB_IDS:
        assert jid in workflow["jobs"], (
            f"ci.yml job ID {jid!r} listed in METADATA_DEPENDENT_JOB_IDS "
            f"is not in the actual workflow."
        )
        actual = workflow["jobs"][jid].get("if")
        assert actual is None, (
            f"ci.yml job {jid!r} is metadata-dependent — it must "
            f"NOT carry an `if:` gate so it re-runs on label flips. "
            f"Got: {actual!r}."
        )


def test_aggregator_carveout_env_lists_exact_diff_dependent_set() -> None:
    """Aggregator's ``DIFF_DEPENDENT_JOB_IDS`` env must match the set.

    The carve-out only fires when both the verified-prior-success
    flag is true AND the entry's key is in this list. Drift between
    this list and the set actually gated by the ``if:`` above leaks
    one of two ways: a job in the env list but not gated → never
    skips → no effect (harmless but stale); a job gated but not in
    the env list → skips on verified-prior-success → aggregator
    treats it as failure → CI broken. Pin the env list to the
    same set the gate covers.
    """
    workflow = _load_workflow()
    agg = workflow["jobs"]["required-checks-passed"]
    step = agg["steps"][0]
    env = step.get("env", {})
    raw = env.get("DIFF_DEPENDENT_JOB_IDS", "")
    assert isinstance(raw, str), (
        "aggregator's DIFF_DEPENDENT_JOB_IDS env must be a YAML block "
        "scalar (string), so the bash-side splitter sees newline-"
        "separated entries."
    )
    actual = frozenset(line.strip() for line in raw.splitlines() if line.strip())
    assert actual == DIFF_DEPENDENT_JOB_IDS, (
        "aggregator's DIFF_DEPENDENT_JOB_IDS env drift: "
        f"missing={sorted(DIFF_DEPENDENT_JOB_IDS - actual)} "
        f"extra={sorted(actual - DIFF_DEPENDENT_JOB_IDS)}. The set "
        "MUST match the diff-dependent gate's coverage exactly."
    )


def test_aggregator_carveout_conditional_is_tight() -> None:
    """Aggregator must require BOTH the flag AND set membership.

    The relaxation is auditable only because the conditional gates
    on TWO conditions: the verified-prior-success flag (so a SHA
    whose CI never finished can't claim the skip) AND the entry's
    key being in the diff-dependent set (so the metadata-dependent
    children's `skipped` is still treated as failure per #441).
    Pin the bash so a future edit can't accidentally widen.
    """
    workflow = _load_workflow()
    agg = workflow["jobs"]["required-checks-passed"]
    step = agg["steps"][0]
    body = step["run"]
    # The jq filter must reference both the flag and the set.
    assert '$flag == "true"' in body, (
        "aggregator carve-out must gate on the verified-prior-success "
        'flag — `$flag == "true"` — so an unset flag does not allow '
        "skipped to count as success."
    )
    assert "$dd[.key]" in body, (
        "aggregator carve-out must gate on per-key set membership — "
        "`$dd[.key]` — so only the diff-dependent children get the "
        "skipped → success treatment."
    )
    assert '.value.result == "skipped"' in body, (
        "aggregator carve-out must only relax `skipped` results — "
        "`failure` / `cancelled` / `timed_out` must still fail."
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_helper_script_outputs_all_expected_check_run_names() -> None:
    """``scripts/ci/diff-dependent-jobs.sh`` must enumerate the right leaves.

    The helper expands each diff-dependent ci.yml job ID into one or
    more leaf check-run names (matrix-expanded). The plan-job probe
    iterates these names against the GitHub Checks API, so an empty
    or short list means the verified-prior-success flag will be
    `true` even when not every child actually passed. Pin the
    expected leaf set explicitly so a matrix-membership change in
    test-unit / test-integration / test-smoke surfaces here.
    """
    expected_leaves = {
        # Single-job direct children publish one check-run each.
        "check-docs / check-docs",
        "check-publish / check-publish",
        "check-release / check-release",
        "check-standards / verify-standards",
        "build / build",
        "test-system / macos-applescript",
        # check-fmt expands into the leaf jobs of its workflow_call.
        # The intermediate `required-checks-passed` aggregator was
        # dropped (issue #556 / ADR 0046); the helper enumerates each
        # leaf directly from the workflow's `jobs:` keys.
        "check-fmt / treefmt",
        "check-fmt / ruff-format",
        "check-fmt / spdx-license-headers / reuse",
        # check-lint leaves (workflow_call → workflow_call → job, plus
        # the direct `dead-code` job that lives in check-lint.yml itself).
        "check-lint / python / ruff",
        "check-lint / python / mypy",
        "check-lint / python / pyright",
        "check-lint / systems-engineering / verify-design",
        "check-lint / systems-engineering / verify-function-tests",
        "check-lint / dead-code",
        # check-security leaves.
        "check-security / codeql-analyse / analyze (python)",
        "check-security / codeql-analyse / analyze (actions)",
        "check-security / ripsecrets / ripsecrets",
        "check-security / check-dependency-review / dependency-review",
        "check-security / check-dependency-submission / submit",
        # check-license-allowlist matrix (issue #575 / ADR 0048) —
        # one job per workspace member, including `pr-lint-validator`
        # (which `test-unit.yml` excludes because it has no shipped
        # runtime tests; the license gate covers it because a
        # copyleft transitive in its closure is still a compliance
        # signal worth flagging at PR time).
        "check-license-allowlist / check-license-allowlist (agent-auth)",
        "check-license-allowlist / check-license-allowlist (agent-auth-common)",
        "check-license-allowlist / check-license-allowlist (gpg-bridge)",
        "check-license-allowlist / check-license-allowlist (gpg-cli)",
        "check-license-allowlist / check-license-allowlist (pr-lint-validator)",
        "check-license-allowlist / check-license-allowlist (things-bridge)",
        "check-license-allowlist / check-license-allowlist (things-cli)",
        "check-license-allowlist / check-license-allowlist (things-client-cli-applescript)",
        # test-unit matrix.
        "test-unit / unit-tests (agent-auth)",
        "test-unit / unit-tests (agent-auth-common)",
        "test-unit / unit-tests (gpg-bridge)",
        "test-unit / unit-tests (gpg-cli)",
        "test-unit / unit-tests (things-bridge)",
        "test-unit / unit-tests (things-cli)",
        "test-unit / unit-tests (things-client-cli-applescript)",
        # test-workspace single-job child publishes one check-run.
        "test-workspace / test-workspace",
        # test-integration matrix.
        "test-integration / integration-tests (agent-auth)",
        "test-integration / integration-tests (gpg-bridge)",
        "test-integration / integration-tests (things-bridge)",
        "test-integration / integration-tests (things-cli)",
        "test-integration / integration-tests (things-client-applescript)",
        # test-smoke matrix — the parens-variant convention emits
        # `(<service.name>, <service.entrypoint>)` for object matrix
        # rows, even when both values are identical.
        "test-smoke / install-from-wheels (gpg-bridge, gpg-bridge)",
        "test-smoke / install-from-wheels (things-cli, things-cli)",
    }

    result = subprocess.run(
        [str(HELPER_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )
    actual = {line for line in result.stdout.splitlines() if line.strip()}
    missing = expected_leaves - actual
    extra = actual - expected_leaves
    assert not missing and not extra, (
        f"diff-dependent-jobs.sh leaf drift: "
        f"missing={sorted(missing)} extra={sorted(extra)}. Update both "
        "the helper's `emit_leaves()` mapping and this test's "
        "`expected_leaves` set."
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_helper_script_is_idempotent() -> None:
    """Multiple invocations must produce byte-identical output.

    The helper is invoked once per ci.yml run; a non-deterministic
    output (e.g. set iteration order in bash) would mean the probe
    hits a different leaf set across runs and the verified-prior-
    success flag becomes flaky. Pin determinism here.
    """
    runs = [
        subprocess.run(
            [str(HELPER_PATH)],
            capture_output=True,
            text=True,
            check=True,
        )
        for _ in range(3)
    ]
    first = runs[0].stdout
    for r in runs[1:]:
        assert r.stdout == first, (
            "diff-dependent-jobs.sh produced non-deterministic output "
            "across invocations — the probe will see different leaf "
            "sets across runs and the verified-prior-success flag "
            "will be flaky."
        )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_helper_script_excludes_metadata_dependent_set() -> None:
    """Helper must NEVER list a metadata-dependent child's leaves.

    `check-changelog` and `check-pull-request` re-run on every event
    by design (their evaluation depends on PR metadata, not the
    diff). Listing them in the helper would cause the probe to check
    their prior conclusion and — if green — let the verified-prior-
    success flag flip to true even when the metadata HAS changed
    between events. The probe must only ever see diff-dependent
    leaves; the metadata-dependent ones surface their pass/fail
    through their own re-run.
    """
    result = subprocess.run(
        [str(HELPER_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout
    # Match the prefix `<jid> /` to catch any leaf rooted under a
    # metadata-dependent ci.yml job. After ADR 0046 every workflow /
    # action name is kebab-case (= filename / directory), so a single
    # prefix form suffices.
    for jid in METADATA_DEPENDENT_JOB_IDS:
        prefix = f"{jid} /"
        assert prefix not in output, (
            f"diff-dependent-jobs.sh emitted a leaf rooted under "
            f"metadata-dependent job {jid!r} (matched prefix "
            f"{prefix!r}). Metadata-dependent children must NOT "
            f"be probed — see issue #527."
        )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_helper_script_covers_required_checks_passed_needs_minus_metadata() -> None:
    """Helper's covered job IDs must equal `needs:` minus metadata set.

    The whole point of deriving the list rather than enumerating it
    inline is that adding a new child to ``required-checks-passed.
    needs:`` automatically extends the verified-prior-success
    coverage. Verify the derivation: parse ``needs:`` from ci.yml,
    subtract `plan` and the metadata-dependent set, and assert every
    surviving job ID has at least one leaf in the helper's output.
    """
    workflow = _load_workflow()
    needs = workflow["jobs"]["required-checks-passed"]["needs"]
    assert isinstance(needs, list), "required-checks-passed.needs must be a list"
    derived = (set(needs) - {"plan"}) - METADATA_DEPENDENT_JOB_IDS

    result = subprocess.run(
        [str(HELPER_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout

    # Every derived job ID must appear as the prefix of at least one
    # leaf. Since ADR 0046, workflow `name:` = filename — so the leaf
    # always starts `<jid> /` (kebab-case, no capitalisation drift).
    for jid in derived:
        prefix = f"{jid} /"
        assert prefix in output, (
            f"diff-dependent-jobs.sh produced no leaf for derived job "
            f"ID {jid!r} (looked for prefix {prefix!r}). A new entry "
            f"was added to required-checks-passed.needs without "
            f"extending the helper, or a child workflow's `jobs:` "
            f"keys do not match the expected kebab-case names."
        )

    # Derived set must equal DIFF_DEPENDENT_JOB_IDS — keeps the test's
    # local constant in lockstep with the workflow's actual surface.
    assert derived == DIFF_DEPENDENT_JOB_IDS, (
        "DIFF_DEPENDENT_JOB_IDS in this test drifted from "
        "required-checks-passed.needs minus the metadata-dependent set. "
        f"derived-from-yaml={sorted(derived)} test-constant="
        f"{sorted(DIFF_DEPENDENT_JOB_IDS)}."
    )
