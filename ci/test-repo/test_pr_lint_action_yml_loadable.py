# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Static parse-time guard for the pr-lint surface (issue #511).

PR #506 cut the pr-lint jobs over to a new
``.github/actions/install-pr-lint-validator/action.yml`` composite.
The new action.yml carried a load-time syntax error: a literal
``${{ github.token }}`` expression inside an input ``description:``
field. GitHub rejects that with ``Unrecognized named-value: 'github'``
because composite-action metadata only has the ``inputs`` context in
scope at parse time.

The bug escaped #506's CI because pr-lint.yml ran on
``pull_request_target`` at the time, which checks out the BASE ref's
copy of the workflow + composite — so the new (broken) version was
never exercised on its own PR. The bug only manifested on the next
PR opened against main.

This test is the minimal head-ref guard. It does NOT depend on the
workflow's trigger surface: as long as it executes on every PR, a
load-time bug in either of the two scoped files fails CI on the same
PR that introduces it. The companion ``pr-lint-yaml-loadable-self-test``
job in ``.github/workflows/pr-lint.yml`` is the runner — it checks
out the head ref and invokes pytest on this file in isolation.

Scope is intentionally narrow (the two files called out in the issue):
expanding to every workflow / composite action is one line away if the
need arises but would gold-plate a precise per-issue fix.

Lives under ``ci/test-repo/`` per the directory's README — this test
is a whole-repo invariant (it asserts a property of two specific
files in ``.github/``) and does not belong to any single workspace
package's ``tests/`` tree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# This file lives at ``ci/test-repo/<file>``, so the repo root is two
# parents up (``parents[0]`` = ``test-repo``, ``parents[1]`` = ``ci``,
# ``parents[2]`` = repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "pr-lint.yml"
COMPOSITE_ACTION_PATH = (
    REPO_ROOT / ".github" / "actions" / "install-pr-lint-validator" / "action.yml"
)

# Composite-action metadata only has the ``inputs`` context in scope at
# parse time. Any ``${{ <other-context>.* }}`` expression in these
# fields is rejected by GitHub at workflow-load time with
# ``Unrecognized named-value: '<context>'``. The simplest accurate
# guard is to forbid the literal ``${{`` substring in these fields
# entirely — no production composite action in this repo legitimately
# needs an ``${{ inputs.* }}`` expression in a ``description:`` /
# ``default:`` / ``value:`` slot today, and a future need can be
# carved out when it arises.
_PARSE_TIME_FORBIDDEN_SUBSTRING = "${{"

# Per the action.yml spec: ``inputs.<name>`` accepts ``description``
# and ``default``; ``outputs.<name>`` accepts ``description`` and
# (for composite actions) ``value``. Each of those values is
# evaluated at workflow-load time, before any step has run.
_FIELDS_PARSED_AT_LOAD_TIME: dict[str, tuple[str, ...]] = {
    "inputs": ("description", "default"),
    "outputs": ("description", "value"),
}


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(WORKFLOW_PATH, id="workflow"),
        pytest.param(COMPOSITE_ACTION_PATH, id="composite-action"),
    ],
)
def test_yaml_parses(path: Path) -> None:
    """The file must parse with ``yaml.safe_load`` without raising.

    A YAML-level syntax error (mis-indentation, unbalanced quotes,
    duplicate keys flagged by the safe loader) would prevent GitHub
    from loading the workflow / composite at all and silently break
    every PR opened after the bad version lands on ``main``. Catch
    that on the same PR.
    """
    text = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    assert parsed is not None, f"{path} parsed to None — empty document?"
    assert isinstance(
        parsed, dict
    ), f"{path} top-level must be a mapping, got {type(parsed).__name__}"


def test_composite_action_metadata_has_no_load_time_expressions() -> None:
    """No ``${{`` expressions in composite-action input/output metadata.

    Reproduces the precise failure mode from PR #506: the
    ``github-token`` input's ``description:`` field carried a literal
    ``${{ github.token }}`` expression, which GitHub rejected with
    ``Unrecognized named-value: 'github'`` because only the ``inputs``
    context is in scope at parse time. The composite refused to load
    on every subsequent PR, breaking the entire pr-lint surface.

    Forbid the ``${{`` substring outright in the load-time-evaluated
    fields. If a future legitimate use of ``${{ inputs.* }}`` arises
    in those fields, carve it out with a deliberate exception here
    rather than weaken the guard wholesale.
    """
    parsed = yaml.safe_load(COMPOSITE_ACTION_PATH.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)

    offences: list[str] = []
    for section, fields in _FIELDS_PARSED_AT_LOAD_TIME.items():
        section_block: Any = parsed.get(section) or {}
        if not isinstance(section_block, dict):
            continue
        for entry_name, entry_spec in section_block.items():
            if not isinstance(entry_spec, dict):
                continue
            for field in fields:
                value = entry_spec.get(field)
                if isinstance(value, str) and _PARSE_TIME_FORBIDDEN_SUBSTRING in value:
                    offences.append(
                        f"{section}.{entry_name}.{field} contains "
                        f"{_PARSE_TIME_FORBIDDEN_SUBSTRING!r}: {value!r}"
                    )

    assert not offences, (
        "Composite action metadata may not contain `${{` expressions "
        "in input/output description/default/value fields — only the "
        "`inputs` context is in scope at workflow-load time and a "
        "`${{ github.* }}` reference fails parsing with "
        "'Unrecognized named-value' (issue #511).\n\nOffences:\n  - " + "\n  - ".join(offences)
    )
