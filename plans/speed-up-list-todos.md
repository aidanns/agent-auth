# Implementation Plan: Speed up `list_todos` to avoid 30s osascript timeout

## Context

`ThingsApplescriptClient.list_todos` (`src/things_bridge/things.py`) currently
builds an AppleScript of the form:

```applescript
tell application "Things3"
    set out to ""
    repeat with t in (to dos)
        set _row to my _esc(id of t)
        set _row to _row & ... & my _esc(name of t)
        set _row to _row & ... & my _esc(notes of t)
        ...
    end repeat
    return out
end tell
```

Every iteration issues ~15 individual Apple Event lookups (`id of t`,
`name of t`, `notes of t`, `status of t`, the four project/area accessor
handlers, `tag names of t`, and six ISO-date conversions). On a real Things 3
database with hundreds of todos, each Apple Event adds measurable latency and
the unfiltered path blows past the default `AppleScriptRunner` timeout of
30 seconds, surfacing to clients as `502 things_unavailable`.

Filter variants (`list=`, `project=`, `area=`, `tag=`, `status=open`) still
work because the scope is small enough to fit within 30 seconds.

This is acknowledged in the Things guide itself: `design/THINGS.md` notes
that the cheapest way to bulk-read from Things is to batch work inside a
single `tell` block and return a string to the caller — exactly the shape
we already use, but we are still paying per-property round-trips per todo.

GitHub issue: #56. Related (same file, different concern): #55.

## Scope

### In scope

- Re-emit the AppleScript in `list_todos`, `list_projects`, and
  `list_areas` so each property is read from the **collection**, not the
  individual todo/project/area, using `<property> of every to do of <scope>`
  (and the equivalents for projects and areas). Zip the parallel lists into
  the existing TSV row format so the output shape, JSON response, and
  downstream parsers are unchanged.
- Keep per-row iteration only for properties that AppleScript's collection
  form cannot express reliably — notably `project` / `area` lookups, which
  already use `try`/`on error` handlers because the relationship can be
  missing. For those, batch the ids and names into parallel lists by
  iterating the collection **once** and calling each handler per element.
- Preserve behaviour for every filter variant: `list_id`, `project_id`,
  `area_id`, `tag`, and `status`. The status filter continues to suppress
  rows that don't match.
- Keep `get_todo`, `get_project`, `get_area` as-is — they read exactly one
  entity and gain nothing from batching.
- Add a regression test that asserts the emitted AppleScript uses the
  batched form (no `repeat with … in (to dos)` in the unfiltered path) and
  emits the `<property> of every to do` idiom for the properties we
  actually batch.
- Add a synthetic benchmark that substitutes a fake `AppleScriptRunner`
  counting the number of Apple Event round-trips implied by the script
  shape, so we can assert the complexity is O(properties) not O(N × properties)
  without requiring a real Things 3 install.
- Update `design/THINGS.md` performance note, if needed, to match the
  approach taken in our client.

### Out of scope

- Migrating to `things.py` / SQLite (issue #56 option 2). Rejected: changes
  the trust boundary.
- Raising the default runner timeout (option 3). Rejected: hides the root
  cause and pushes the problem to slightly larger databases.
- Persistent AppleScript process (JXA daemon). Future work.
- Write/mutation paths.

## Approach

### AppleScript shape

Replace the existing per-todo `repeat` with a batched collection read. The
new body for unfiltered `list_todos` looks like:

```applescript
tell application "Things3"
    set _src to (to dos)
    set _ids to id of every to do of ...      -- (*)
    set _names to name of every to do of ...
    set _notes to notes of every to do of ...
    set _statuses to status of every to do of ...
    set _tagNames to tag names of every to do of ...
    set _dueDates to due date of every to do of ...
    set _activationDates to activation date of every to do of ...
    set _completionDates to completion date of every to do of ...
    set _cancellationDates to cancellation date of every to do of ...
    set _creationDates to creation date of every to do of ...
    set _modificationDates to modification date of every to do of ...

    -- project/area can't be batched as simply because the relationship is
    -- optional and the collection form coerces missing values
    -- inconsistently. Pay one extra round-trip per todo for these.
    set _projectIds to {}
    set _projectNames to {}
    set _areaIds to {}
    set _areaNames to {}
    repeat with _t in _src
        set end of _projectIds to my _projId(_t)
        set end of _projectNames to my _projName(_t)
        set end of _areaIds to my _areaId(_t)
        set end of _areaNames to my _areaName(_t)
    end repeat

    set out to ""
    set _n to count of _ids
    repeat with _i from 1 to _n
        set _row to my _esc(item _i of _ids)
        set _row to _row & <TAB> & my _esc(item _i of _names)
        ...
        set out to out & _row & <LF>
    end repeat
    return out
end tell
```

(*) For filtered variants the `every to do of <scope>` becomes e.g.
`every to do of project id "p1"` — straightforward substitution.

This trades 15 Apple Events per todo for ~11 Apple Events total plus one
pass over the collection for the project/area accessors. On an N-todo
database the total Apple Event count drops from `~15N` to `N + 11` —
roughly one order of magnitude reduction even keeping the fallback loop.

### Properties that do not batch cleanly

`project of t` and `area of t` are **optional relationships**. The existing
handlers (`_projId`, `_projName`, `_areaId`, `_areaName`) already wrap the
lookup in a `try` block because a todo without a project raises an error
rather than returning `missing value`. AppleScript's collection form
(`project of every to do`) inherits the same behaviour — if any element
has no project the whole batch call fails — so we cannot use it.

Fallback: keep a single-pass loop that calls the per-element handlers for
the four project/area fields. This is still O(N) Apple Events but only
four per todo rather than ~15, and it runs inside the same `tell` block as
the collection reads so there is no extra process-launch cost.

This caveat is called out in the regression test so the reader knows why
the emitted script still contains `repeat with` (for project/area), just
not a `repeat` that reads every property per-todo.

### Empty-database edge case

- `id of every to do of (to dos)` on an empty collection returns `{}` in
  AppleScript — not `missing value` and not an error. The subsequent
  `count of _ids` is `0` and the `repeat _i from 1 to 0` loop is a no-op,
  yielding an empty `out` string. The existing `_parse_rows` already
  accepts empty output and returns `[]`.
- Verify with a unit test that the fake runner returning empty output
  continues to yield `[]`.

### JSON output shape

Unchanged. The TSV rows written by the new script have identical columns
(count and order) and the parser (`_row_to_todo`, `_parse_rows`) is
untouched. The server's JSON serialisation reads from `Todo`, `Project`,
`Area` dataclasses and is unaffected.

### Status filter

The existing server-side status filter appends an `if my _statusText(status
of t) is "..." then ... end if` guard around the per-row body. In the new
shape we instead compare `item _i of _statuses` (already coerced to text
by a batched map call) against the filter value and skip the row append
accordingly.

### Apply same shape to `list_projects` / `list_areas`

For symmetry and to avoid future regressions of the same class, port
`list_projects` and `list_areas` to the batched form as well. Projects
typically number in the tens and areas in the single digits, so the
practical win is small, but keeping all three on the same pattern reduces
reviewer confusion.

## Testing

### Unit tests

1. **Unfiltered `todos list` uses the batched AppleScript shape** — new
   test describing the impact (unfiltered `todos list` must stay under the
   osascript timeout ceiling on real databases) and what's tested (the
   script contains no `repeat with _t in (to dos)` over every property and
   does contain `id of every to do` / `name of every to do` / etc.).
2. **Unfiltered `todos list` on an empty database returns `[]`** — fake
   runner returns empty output; client returns `[]` without error.
3. **Filter variants still emit the batched form scoped to the filter** —
   `list_id`, `project_id`, `area_id`, `tag` each result in a script that
   reads `every to do of <scope>` rather than `every to do of (to dos)`.
4. **Status filter preserves semantics** — the emitted script includes
   a per-row status check referencing `_statuses` and still produces
   correctly filtered rows when the fake runner returns mixed rows.
5. **Existing tests stay green** — TSV parsing, injection rejection,
   status validation, malformed-row handling, `_HELPERS` still compiles.

### Synthetic benchmark

Add a "round-trip counter" regression. Implement as a pure-python metric
over the emitted script string:

- Count occurrences of `every to do` / `every project` / `every area` —
  should equal the number of batched properties.
- Count occurrences of `of t)` / `of p)` / `of a)` at the top level —
  should be zero in the unfiltered case except for the four
  project/area handler calls plus the trailing status check.

Tradeoff noted: a timed benchmark against real Things 3 would give a
concrete "completes under 30s on 500 todos" number, but it requires a
macOS host with Things 3 installed and populated, which the CI does not
have. The structural assertion guards re-introduction of per-property
round-trips, which is the underlying cause the issue calls out; if a
macOS-only benchmark is added later it should live behind the existing
`_requires_things3` marker.

### Test suite

Run `pytest` across the full tree under the project venv to confirm no
regressions in the bridge HTTP layer, CLI, or server tests.

## Docs review

- `README.md` — skim for `list_todos` performance claims. Expected: no
  change required (the README does not document AppleScript shape).
- `design/DESIGN.md` — confirm no documented AppleScript shape that would
  drift. Expected: no change required.
- `design/THINGS.md` — already has a performance note (§15). Extend with
  a short bullet that says "prefer `<property> of every to do of <scope>`
  over `repeat with t in (every to do of <scope>)` to cut per-property
  round-trips by a factor of N".
- `design/functional_decomposition.yaml` / `product_breakdown.yaml` —
  scan for a node documenting the Things read shape. Expected: none.

## Plan commit

Commit this plan file to `plans/speed-up-list-todos.md` in the same PR as
the implementation.

## Design and verification

- **Verify implementation against design doc** — after implementing,
  re-read `design/DESIGN.md` §`things-bridge` and `design/THINGS.md` §15
  (performance) and reconcile. Expect only the §15 extension noted above.
- **Threat model** — no change. The trust boundary is unchanged: we still
  shell out to `osascript` with a fully-parameterised static script and
  quote all caller-supplied ids via `_quote`. No new code paths accept
  untrusted input. STRIDE categories unaffected.
- **ADR** — add a short ADR `design/decisions/00XX-list-todos-batched-applescript.md`
  recording the three options, why we picked Option 1 (batch), and the
  caveat that `project`/`area` stay per-element.
- **Cybersecurity standard compliance** — no new network surface, no new
  data exposure, no new secrets. No controls to re-walk.
- **QM / SIL compliance** — performance fix in a read-only path; the
  correctness invariants covered by existing tests are preserved. No new
  SIL obligations.

## Post-implementation standards review

Follow the checklist in `.claude/instructions/plan-template.md`:

- **coding-standards.md** — procedure names still verbs, numeric names
  carry units where relevant (`timeout_seconds` is already correct).
  Verify newtype use for the quoted strings remains sound.
- **service-design.md** — HTTP surface, error taxonomy, metrics, health
  are unaffected. Confirm the error code `things_unavailable` no longer
  fires for the symptomatic unfiltered path.
- **release-and-hygiene.md** — no schema change; no CHANGELOG entry
  required for this project's current stage, but mention the perf fix in
  the commit body.
- **testing-standards.md** — new tests exercise the public
  `ThingsApplescriptClient.list_todos` API and assert observable shape
  (emitted script string and parsed result), not internal state.
- **tooling-and-ci.md** — no new CI step needed; the regression test runs
  under the default `pytest` invocation.
