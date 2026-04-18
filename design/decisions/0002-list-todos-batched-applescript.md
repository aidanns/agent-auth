# ADR 0002: Batch AppleScript property reads in `list_todos`

Date: 2026-04-18

## Status

Accepted.

## Context

`ThingsApplescriptClient.list_todos` issued one AppleScript Apple Event
per property per todo via a `repeat with t in (to dos)` loop that read
`id of t`, `name of t`, `notes of t`, and ~12 more properties on each
iteration. On a real Things 3 database (~100+ todos) the unfiltered
`todos list` call exceeded the 30 second `AppleScriptRunner` default
timeout, surfacing to clients as `502 things_unavailable` (issue #56).

Filtered variants (`list=`, `project=`, `area=`, `tag=`) were unaffected
in practice because their cardinality kept the per-todo cost within the
timeout budget.

Three options were considered:

1. **Batch property reads in AppleScript.** Read each property off the
   todo collection with `<property> of every to do [of <scope>]`, which
   returns a parallel list in a single Apple Event. Zip the lists in
   AppleScript and emit the same TSV row stream the parser already
   expects. Same trust boundary, same framing, same output schema.
2. **Switch to the SQLite database via `things.py`.** Changes the trust
   boundary: the bridge would read Things's on-disk store directly rather
   than going through the sanctioned AppleScript surface.
3. **Raise the `AppleScriptRunner` timeout.** Hides the root cause — the
   shape scales linearly in the number of properties per todo, so the
   symptom returns at a slightly larger database.

## Decision

Implement option 1. Use `<property> of every to do of <scope>` for every
property that AppleScript's collection form handles cleanly, and zip
the resulting parallel lists back into the existing TSV row format.

Apply the same shape to `list_projects` and `list_areas` for symmetry
and to avoid the same regression class reappearing if project/area
counts grow on a given user's database.

## Consequences

### Performance

For an N-todo database the unfiltered listing cost drops from roughly
`~15 × N` Apple Events to `~11 + N` Apple Events (eleven batched
property reads plus one pass for the optional project/area handlers —
see "Caveats" below). That's an order of magnitude reduction and brings
the unfiltered path comfortably under the 30s runner timeout for any
database size users are likely to have.

### Output schema

Unchanged. The emitted script still writes one tab-separated row per
todo with the same columns in the same order, so downstream parsers,
HTTP response shapes, and CLI JSON output are unaffected.

### Trust boundary

Unchanged. We still shell out to `osascript` with a fully-parameterised
static script, and every caller-supplied id continues to flow through
`_quote` before reaching AppleScript. No new injection surface.

### Caveats — properties that don't batch

`project` and `area` are optional relationships on a todo. The
`project of every to do of <scope>` form raises as soon as any element
has no project attached, so we cannot use the collection form for those
fields. The implementation keeps a single `repeat` pass that calls the
existing `try`-wrapped handlers (`_projId`, `_projName`, `_areaId`,
`_areaName`) once per todo. That pass is still O(N) Apple Events, but
it only reads four fields per todo instead of all ~15, and it runs
inside the same `tell` block so there is no additional process-launch
cost. The regression test explicitly allows this one remaining
`repeat` and asserts that none of the batched properties regress to
per-element reads.

### Future work

If Things ever adds a richer query surface (for example, a bulk
"resolve project id for every todo of scope" primitive), the project
and area fallback loop can be replaced too. Until then this plan
captures the cheapest change that fits within the AppleScript trust
boundary. A longer-running persistent AppleScript host (JXA daemon,
`py-appscript`, or Scripting Bridge) would remove the per-request
`osascript` launch overhead for sustained workloads, but is out of
scope here.
