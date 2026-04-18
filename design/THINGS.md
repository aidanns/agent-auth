# Things 3 AppleScript API Reference

This document describes the complete AppleScript interface exposed by Things 3 (by Cultured Code). It is intended to allow an implementer with no direct access to a Mac running Things to write an application that reads from and writes to a Things database via AppleScript (e.g. by shelling out to `osascript`, or by using a language binding like JXA, Scripting Bridge, or PyObjC).

The information below was extracted directly from the `Things.sdef` scripting definition that ships with the app (at `/Applications/Things3.app/Contents/Resources/Things.sdef`) and supplemented with empirically verified behavior. The app identifier is `Things3` (not `Things`).

## Table of contents

01. [Executing AppleScript against Things](#executing-applescript-against-things)
02. [Object model overview](#object-model-overview)
03. [Application root object](#application-root-object)
04. [The `list` class and built-in lists](#the-list-class-and-built-in-lists)
05. [The `area` class](#the-area-class)
06. [The `project` class](#the-project-class)
07. [The `to do` class](#the-to-do-class)
08. [The `selected to do` class](#the-selected-to-do-class)
09. [The `tag` class](#the-tag-class)
10. [The `contact` class](#the-contact-class)
11. [The `item details` record type](#the-item-details-record-type)
12. [Enumerations](#enumerations)
13. [Commands (verbs)](#commands-verbs)
14. [Reference patterns (how to identify objects)](#reference-patterns-how-to-identify-objects)
15. [Filtering with `whose` clauses](#filtering-with-whose-clauses)
16. [Creating objects (`make`)](#creating-objects-make)
17. [Deleting / archiving items](#deleting--archiving-items)
18. [Scheduling and dates](#scheduling-and-dates)
19. [Tags: working with the `tag names` property](#tags-working-with-the-tag-names-property)
20. [Null / missing values](#null--missing-values)
21. [Error codes you will encounter](#error-codes-you-will-encounter)
22. [Hidden / experimental / undocumented members](#hidden--experimental--undocumented-members)
23. [End-to-end recipes](#end-to-end-recipes)
24. [Gotchas and caveats](#gotchas-and-caveats)

______________________________________________________________________

## Executing AppleScript against Things

Things 3 exposes a classic AppleScript scripting suite (`THGS`). All communication goes through the macOS Apple Events system. There are three practical ways to talk to it:

1. **`osascript`** — invoke the `osascript` command-line tool with `-e` for inline script or a `.applescript`/`.scpt` file path. Returns the final expression on stdout. This is the simplest option from any language, but it spawns a process per call and passes arguments as strings.
2. **JXA (JavaScript for Automation)** — `osascript -l JavaScript`. Same Apple Events, JavaScript syntax. The object model is identical; you use `Application("Things3")` to get the root.
3. **Native binding** — Scripting Bridge (Objective-C / Swift), PyObjC, `appscript`/`py-appscript`, etc. Faster than `osascript` because the process and connection are persistent.

Regardless of transport, the command vocabulary, class model, and semantics documented below are the same.

### Minimal smoke test

AppleScript:

```applescript
tell application "Things3"
    return name of application
end tell
```

JXA:

```javascript
const Things = Application("Things3");
Things.name();   // "Things"
```

Things must be running (or launchable) on the target machine. Sending an Apple Event to a non-running app will normally auto-launch it; in a headless/background context you may want to `launch application "Things3"` first to avoid bringing it to the foreground.

### Permissions

On modern macOS, sending Apple Events to another app requires the user to have granted the calling process Automation permission for Things (System Settings → Privacy & Security → Automation). The first call will prompt if the process is not yet authorized; in non-interactive contexts it will fail silently with error `-1743` (`errAEEventNotPermitted`).

______________________________________________________________________

## Object model overview

```
application
├── windows            (Standard Suite)
├── lists              (built-in smart lists + areas)
│   └── to dos
├── areas              (user-defined areas of responsibility)
│   ├── to dos
│   └── tags
├── projects           (user-defined projects; a project IS-A to do)
│   └── to dos
├── to dos             (all to dos across the database)
│   └── tags
├── selected to dos    (to dos currently selected in the UI)
├── tags               (flat collection; hierarchy via `parent tag`)
│   ├── tags           (child tags)
│   └── to dos         (to dos with this tag)
└── contacts           (people assignable to to dos)
    └── to dos         (to dos assigned to this contact)
```

Inheritance (important — it controls which properties and commands are available):

- `area` inherits from `list`
- `contact` inherits from `list`
- `project` inherits from `to do` ← note: projects are to dos, not lists
- `selected to do` inherits from `to do`

So any property defined on `to do` is also valid on `project`, and any property on `list` is valid on `area` and `contact`. Conversely, the `move` command (which takes a `list` target) accepts areas and contacts, but **not** projects (see [Deleting / archiving items](#deleting--archiving-items) and the `move` command).

______________________________________________________________________

## Application root object

Target: `application "Things3"`

### Properties

| Property    | Type    | Access | Description                                      |
| ----------- | ------- | ------ | ------------------------------------------------ |
| `name`      | text    | r      | The name of the application (always `"Things"`). |
| `frontmost` | boolean | r      | `true` if Things is the active/frontmost app.    |
| `version`   | text    | r      | Version string (e.g. `"3.21.4"`).                |

### Element collections

These are the ordered collections you can query from the app root. Most are read-only at the app level, meaning you cannot `make new … at application "Things3"` against these collections directly (exception: `to do`, `project`, `area`, `tag`, `contact`, which you create without an `at` clause and they default to their natural home — see [Creating objects](#creating-objects-make)).

| Element           | Class          | Notes                                                                                                                                                 |
| ----------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `windows`         | window         | Standard Suite windows.                                                                                                                               |
| `lists`           | list           | **Built-in lists AND all user areas**. Does NOT include projects.                                                                                     |
| `to dos`          | to do          | Every to do in the database that is neither trashed nor logged (empirical). Use `to dos of list "Logbook"` / `to dos of list "Trash"` to reach those. |
| `projects`        | project        | All user-defined projects (across all areas).                                                                                                         |
| `areas`           | area           | All user-defined areas of responsibility.                                                                                                             |
| `contacts`        | contact        | All Things contacts.                                                                                                                                  |
| `tags`            | tag            | All tags, **flat** (children and parents are all present). Use `parent tag` to reconstruct hierarchy.                                                 |
| `selected to dos` | selected to do | To dos currently selected in the Things UI. Empty if no window is open or no selection.                                                               |

### Notes on `lists`

`lists` mixes two very different kinds of things: built-in smart lists (`Inbox`, `Today`, …) and user-defined areas (because `area` inherits from `list`). To tell them apart, check the `class` of each element — built-in ones are class `list`, user areas are class `area`. Their `id` format also differs (see below).

______________________________________________________________________

## The `list` class and built-in lists

Code: `tsls`. Represents a Things list (a named collection of to dos).

### Properties

| Property | Type | Access | Description                                                                                                                 |
| -------- | ---- | ------ | --------------------------------------------------------------------------------------------------------------------------- |
| `id`     | text | r      | Stable unique identifier. Built-in lists use stable string IDs (table below); user areas use random-looking Base58-ish IDs. |
| `name`   | text | rw     | Localized display name.                                                                                                     |

### Element collections

| Element  | Class | Notes                            |
| -------- | ----- | -------------------------------- |
| `to dos` | to do | The to dos visible in this list. |

### Commands

- `show` — scrolls Things' UI to and selects this list.

### Built-in lists (smart lists)

These are always present. Use the stable IDs below rather than names when you want to be robust against localization or renaming. However the **English names also work** as references (e.g. `list "Today"`) on a non-localized system.

| Name (en)      | Stable `id`            | What's in it                                                                                                                                    |
| -------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Inbox          | `TMInboxListSource`    | To dos with no project, area, or schedule.                                                                                                      |
| Today          | `TMTodayListSource`    | To dos whose activation date is today (or earlier).                                                                                             |
| Tomorrow       | `tomorrow`             | "This Evening" partition conceptually — in practice, used as part of the Today view in newer versions. (Non-canonical; don't rely on contents.) |
| Anytime        | `TMNextListSource`     | Active, unscheduled to dos from projects/areas (Things' "Next" semantics).                                                                      |
| Upcoming       | `TMCalendarListSource` | To dos scheduled for future dates.                                                                                                              |
| Someday        | `TMSomedayListSource`  | To dos scheduled as "Someday".                                                                                                                  |
| Later Projects | `later-projects`       | Projects marked "Someday" (newer Things versions).                                                                                              |
| Logbook        | `TMLogbookListSource`  | Completed / canceled to dos after they have been logged.                                                                                        |
| Trash          | `TMTrashListSource`    | Deleted items (soft-delete bucket).                                                                                                             |

The list names on a localized Things install will be the user's locale (e.g. `Heute` in German). Prefer `list id "TMTodayListSource"` if you don't know the locale.

### Reading a list's to dos

```applescript
tell application "Things3"
    set ts to to dos of list "Today"              -- by localized name
    set ts to to dos of list id "TMTodayListSource" -- locale-independent
end tell
```

### Reading areas through `lists`

Because areas appear in `lists`, you can also do:

```applescript
tell application "Things3"
    to dos of list "Personal"
end tell
```

This returns the same result as `to dos of area "Personal"`.

______________________________________________________________________

## The `area` class

Code: `tsaa`. Inherits from `list`.

### Properties (in addition to those inherited from `list`)

| Property    | Type    | Access | Description                                                     |
| ----------- | ------- | ------ | --------------------------------------------------------------- |
| `tag names` | text    | rw     | Comma-separated tag names for this area (areas can carry tags). |
| `collapsed` | boolean | rw     | Whether this area is collapsed in the sidebar.                  |

### Element collections (in addition to `list.to dos`)

| Element | Class | Notes                       |
| ------- | ----- | --------------------------- |
| `tags`  | tag   | Tags attached to this area. |

### Creating areas

```applescript
tell application "Things3"
    make new area with properties {name:"Home", tag names:"Errands"}
end tell
```

`make new area` with no `at` clause creates a top-level area.

### Deleting areas

`delete anArea` works for user-created areas (verified).

______________________________________________________________________

## The `project` class

Code: `tspt`. **Inherits from `to do`** (projects are a specialization of to do, not list). This means every property and command on `to do` also applies to `project`. This is important: a `project` has a `status`, a `due date`, an `area`, tags, notes, completion/cancellation dates, etc.

### Element collections beyond those inherited from `to do`

| Element  | Class | Notes                                   |
| -------- | ----- | --------------------------------------- |
| `to dos` | to do | The to dos that belong to this project. |

### Properties a project has (via `to do`)

`id`, `name`, `creation date`, `modification date`, `due date`, `activation date`, `completion date`, `cancellation date`, `status`, `tag names`, `notes`, `area` (a project can live in an area), `contact`. See [The `to do` class](#the-to-do-class) for details.

The `project` property on a `to do` points at its parent project, **not** the project itself — so there is no `project of someProject` self-reference.

### Creating projects

```applescript
tell application "Things3"
    set p to make new project with properties {name:"Q2 Planning", notes:"...", area:area "Personal"}
    -- add a to do directly to the project
    make new to do at p with properties {name:"Draft goals"}
end tell
```

### Moving to dos into projects

`move` does **not** accept a project as target (the `move` verb's `to` parameter is typed as `list`, and `project` is not a `list`). To assign a to do to a project, either:

1. Create it in place: `make new to do at projectRef`, or
2. Set the property: `set project of todoRef to projectRef`.

______________________________________________________________________

## The `to do` class

Code: `tstk`. The primary data object. Cocoa class is `ASTask`.

### Properties

| Property            | Type        | Access | Description                                                                                                                                                     |
| ------------------- | ----------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                | text        | r      | Stable unique identifier (Base58-ish string, ~22 chars).                                                                                                        |
| `name`              | text        | rw     | Title of the to do.                                                                                                                                             |
| `notes`             | text        | rw     | Freeform notes body. Supports plain text including URLs.                                                                                                        |
| `creation date`     | date        | rw     | When the to do was created. Writable (rare).                                                                                                                    |
| `modification date` | date        | rw     | Last-modified timestamp.                                                                                                                                        |
| `due date`          | date        | rw     | **Deadline** date (the red flag in the UI). Set to `missing value` to clear.                                                                                    |
| `activation date`   | date        | **r**  | When the to do becomes active (i.e. the scheduled start date). **Read-only.** Change it via the `schedule` command or by moving into `Today` / `Someday` / etc. |
| `completion date`   | date        | rw     | Date the to do was marked complete. Setting `status` to `completed` sets this; clearing completion via `status` = `open` zeroes it.                             |
| `cancellation date` | date        | rw     | Date the to do was canceled. Symmetric with `completion date`.                                                                                                  |
| `status`            | status enum | rw     | One of `open`, `completed`, `canceled`. See [Enumerations](#enumerations).                                                                                      |
| `tag names`         | text        | rw     | **Comma-separated** tag names (e.g. `"P1, Errand"`). See [Tags](#tags-working-with-the-tag-names-property).                                                     |
| `project`           | project     | rw     | The parent project, or `missing value`.                                                                                                                         |
| `area`              | area        | rw     | The parent area, or `missing value`. A to do has at most one of `project`/`area`.                                                                               |
| `contact`           | contact     | rw     | Assigned contact, or `missing value`.                                                                                                                           |

### Element collections

| Element | Class | Notes                                                                                   |
| ------- | ----- | --------------------------------------------------------------------------------------- |
| `tags`  | tag   | The tag objects attached to this to do. Read/write via `tag names` is generally easier. |

### Commands supported by `to do`

- `move` — move to another list (see [Commands](#commands-verbs)).
- `schedule` — set activation date.
- `show` — reveal in the Things UI.
- `edit` — open the to do's edit/detail view.

### Distinguishing open vs. logged/trashed to dos

When you access `application.to dos` you get active (non-logged, non-trashed) to dos. Logged and trashed to dos are NOT included in that collection — you must reach them through `to dos of list "Logbook"` or `to dos of list "Trash"`.

### Status transitions

- `set status to completed` → moves the task to the "completed" bucket and stamps `completion date` with now. It is visible in Today/Anytime/etc. until the **logger** runs (see [`log completed now`](#log-completed-now)), after which it moves to Logbook.
- `set status to canceled` → same behavior but stamps `cancellation date`.
- `set status to open` → reopens; clears `completion date` / `cancellation date` back to `missing value`.

______________________________________________________________________

## The `selected to do` class

Code: `tslt`. Inherits from `to do`. Returned from `application.selected to dos` — the set of to dos the user currently has selected in Things' UI.

Empirical note: reading `class of aToDo` sometimes returns `selected to do` even when you fetched the object from a list (not the selection). Because `selected to do` inherits from `to do`, treat them interchangeably for property access. If you need to type-check, accept both `to do` and `selected to do` as "a to do".

______________________________________________________________________

## The `tag` class

Code: `tstg`.

### Properties

| Property            | Type | Access | Description                                                                                                                                                                                                                              |
| ------------------- | ---- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                | text | r      | Stable unique identifier (Base58-ish).                                                                                                                                                                                                   |
| `name`              | text | rw     | Tag name. Unique-ish but Things does not strictly enforce uniqueness.                                                                                                                                                                    |
| `keyboard shortcut` | text | rw     | The single-letter (or chord) keyboard shortcut for this tag, or empty string.                                                                                                                                                            |
| `parent tag`        | tag  | rw     | Parent tag for hierarchical tags. `missing value` for root tags — but because the property is typed as `tag`, reading it on a root tag raises an error rather than returning `missing value`. Always wrap in `try` or test via `exists`. |

### Element collections

| Element  | Class | Notes                                      |
| -------- | ----- | ------------------------------------------ |
| `tags`   | tag   | Child tags.                                |
| `to dos` | to do | **Read-only.** To dos that carry this tag. |

### Creating tags

```applescript
tell application "Things3"
    make new tag with properties {name:"Urgent"}
end tell
```

With a parent:

```applescript
tell application "Things3"
    set parentT to tag "Work"
    make new tag with properties {name:"DeepWork", parent tag:parentT}
end tell
```

### Deleting tags

`delete aTag` works on user tags.

### Safely reading `parent tag`

```applescript
tell application "Things3"
    set t to tag "Urgent"
    try
        set p to parent tag of t
        set parentName to name of p
    on error
        set parentName to missing value
    end try
end tell
```

______________________________________________________________________

## The `contact` class

Code: `tspn`. Inherits from `list`.

Contacts in Things are a way to assign a to do to a person. The `contacts` collection on the app root lists them.

### Creating contacts

Use the dedicated verb (not `make new contact`):

```applescript
tell application "Things3"
    set c to add contact named "Jane Doe"
end tell
```

The direct-parameter is the contact's name. The command returns the new `contact` object.

### Reading to dos for a contact

```applescript
tell application "Things3"
    to dos of contact "Jane Doe"
end tell
```

______________________________________________________________________

## The `item details` record type

Code: `idts`. A *record* (AppleScript dictionary) used only as the `with properties` argument to `show quick entry panel`.

Fields:

| Field       | Type | Description              |
| ----------- | ---- | ------------------------ |
| `name`      | text | Title for the new to do. |
| `notes`     | text | Notes.                   |
| `due date`  | date | Deadline.                |
| `tag names` | text | Comma-separated tags.    |

Example:

```applescript
tell application "Things3"
    show quick entry panel with properties {name:"Call dentist", notes:"Confirm cleaning", tag names:"Errand"}
end tell
```

______________________________________________________________________

## Enumerations

### `status` (code `tdst`)

The value of a to do's `status` property.

| Enumerator  | Code   | Meaning                                                             |
| ----------- | ------ | ------------------------------------------------------------------- |
| `open`      | `tdio` | Active / not yet done.                                              |
| `completed` | `tdcm` | Marked done.                                                        |
| `canceled`  | `tdcl` | Marked canceled (Things distinguishes "canceled" from "completed"). |

In AppleScript you just use the bare word: `set status of t to completed`.

### `printing error handling` (from Standard Suite)

Inherited from the Standard Suite — only relevant if you use the `print` command. Values: `standard`, `detailed`. Generally not needed for Things automation.

______________________________________________________________________

## Commands (verbs)

Ordered by usefulness.

### `make`

Standard Suite verb. Creates a new object.

```
make new <class> [at <location specifier>] [with properties <record>]
```

Result: a specifier to the new object.

- `make new to do` — defaults to Inbox (verified).
- `make new to do at project "Foo"` — create inside a project.
- `make new to do at area "Bar"` — create inside an area.
- `make new to do at list "Today"` — empirically, creates in Today-schedule state.
- `make new project with properties {name:"…"}` — top-level project (unless you pass `area:` in properties).
- `make new area` — top-level area.
- `make new tag` — top-level tag (unless you pass `parent tag:`).

**You cannot `make new contact`.** Use `add contact named` instead.

### `delete`

Standard Suite verb. `delete <specifier>`.

- Works on: to dos in open lists (Inbox/Today/Anytime/Upcoming/Someday + project/area), projects, areas, tags.
- **Does NOT reliably work** on to dos in Logbook or Trash (verified: calls appear to succeed but item remains in Logbook, and subsequent references to the item error with `-1728`). To get rid of a logged/trashed item, either leave it (Trash) or call `empty trash`.
- For soft-delete, prefer `move aToDo to list "Trash"` — this is what Things' own UI does.

### `move`

Things-specific verb. Moves a to do between lists.

```
move <to do specifier> to <list>
```

Valid targets for the `to` parameter (type `list` or subclasses):

- Built-in lists: `Inbox`, `Today`, `Anytime`, `Upcoming`, `Someday`, `Trash`. (`Logbook` is not typically a legal destination — `log completed now` is how things get there.)
- An `area` (because area inherits from list).
- A `contact` (because contact inherits from list — moves a to do to be "assigned to" that contact).

**Invalid targets:**

- A `project` — `move` raises error `Cannot move to-do` (301). To place a to do into a project, use `set project of …` or `make new to do at project …`.

Effect on dates:

- `move t to list "Today"` sets `activation date` to today.
- `move t to list "Someday"` clears `activation date`.

### `schedule`

Things-specific verb. Schedules a to do for a specific date (sets `activation date`).

```
schedule <to do specifier> for <date>
```

Example:

```applescript
tell application "Things3"
    schedule (to do id "…") for (current date) + (7 * days)
end tell
```

This is the **only** way to programmatically set the `activation date` (the property itself is read-only).

### `show`

Things-specific verb. Opens Things' UI to the given item.

```
show <specifier>
```

Argument may be a `list`, `area`, `project`, or `to do`. Brings Things to the foreground and scrolls to / selects the item. Does not return a value.

### `edit`

Things-specific verb. Opens the edit/detail pane for a to do.

```
edit <to do specifier>
```

Only valid for `to do` specifiers (not lists/areas/projects).

### `show quick entry panel`

Things-specific verb. Displays the Things Quick Entry panel (the HUD window that lets users add a new to do).

```
show quick entry panel [with autofill <boolean>] [with properties <item details>]
```

- `with autofill true` — populate the panel from the currently focused/selected app (URL, selected text, etc.). `with properties` is ignored when autofill is `true`.
- `with properties {name:"…", notes:"…", due date:…, tag names:"…"}` — pre-populate the panel with these values (see [item details](#the-item-details-record-type)).

This command shows UI; it does not create a to do on its own. The user must confirm in the panel for the to do to be saved.

### `add contact named`

Things-specific verb. Creates a new contact.

```
add contact named <text>
```

Returns the new `contact`.

### `parse quicksilver input`

Things-specific verb. Creates a new to do from a single-line "Quicksilver syntax" string and returns it.

```
parse quicksilver input <text>
```

Returns the new `to do`. Empirical note: on current versions the parsing rules for the various `//`, `@`, `#` tokens may be reduced or stubbed; test on your specific Things version, or prefer building a properties record with `make new to do` for reliability.

### `log completed now`

Things-specific verb. Immediately runs the "Log completed items" sweep, moving everything marked `completed` / `canceled` into the Logbook. Normally Things runs this on its own schedule (configured in Preferences). No arguments.

```applescript
tell application "Things3" to log completed now
```

### `empty trash`

Things-specific verb. Permanently deletes everything in the `Trash` list. **No confirmation.** No arguments.

```applescript
tell application "Things3" to empty trash
```

### `count`

Standard Suite. Counts elements.

```applescript
count of to dos of list "Today"
count every project
```

### `exists`

Standard Suite. Test for existence of a specifier.

```applescript
exists to do id "abc123"
```

### `duplicate`

Standard Suite. Duplicates a specifier at a new location. Works on to dos; behavior on projects/areas is not officially documented but likely supported.

### `close`, `print`, `quit`

Standard Suite. Act on windows / application lifecycle. `quit` exits Things.

### Hidden / experimental

Several hidden commands exist in the sdef (they are marked `hidden="yes"` and have names prefixed `_private_experimental_`); see [Hidden members](#hidden--experimental--undocumented-members). Do not rely on these.

______________________________________________________________________

## Reference patterns (how to identify objects)

AppleScript references can be by index, by name, by ID, by `whose` clause, or `first`/`last`/`middle`.

### By index (1-based)

```applescript
tell application "Things3"
    to do 1 of list "Today"
    project 1
end tell
```

### By name (localization-sensitive)

```applescript
tell application "Things3"
    list "Today"
    area "Personal"
    project "Q2 Planning"
    tag "Urgent"
end tell
```

Name matching is exact and case-sensitive. If multiple objects share a name, AppleScript returns the first match (error if none).

### By ID (preferred for long-term references)

```applescript
tell application "Things3"
    to do id "Jso2YLTSiLmVjtEB31m52N"
    list id "TMInboxListSource"
    project id "4fCabeMj6dsR3WUNb9iyea"
    area id "NWvTpAG4cX6e3hnfxgJ4Ko"
    tag id "FBLq6vojz56u8EYTZnnJ7j"
end tell
```

IDs are stable across app restarts, sync, and renames. Use them whenever you need a durable reference from your own storage. Built-in list IDs are listed in [the built-in lists table](#built-in-lists-smart-lists).

### `first` / `last` / `middle` / `some` / `every`

```applescript
tell application "Things3"
    first to do of list "Today"
    last to do of list "Today"
    every to do of project "Q2 Planning"
end tell
```

### From a named context

```applescript
tell application "Things3"
    to dos of project "Q2 Planning"
    to dos of area "Personal"
    to dos of tag "Urgent"
end tell
```

______________________________________________________________________

## Filtering with `whose` clauses

`whose` clauses are evaluated server-side by Things and are vastly faster than fetching everything and filtering in your own code.

```applescript
tell application "Things3"
    -- All open to dos with tag "P1"
    every to do whose status is open and tag names contains "P1"
    -- Overdue to dos
    every to do whose due date is less than (current date) and status is open
    -- To dos in a specific area
    every to do whose area is area "Personal"
    -- Root tags only — NOTE: "is missing value" is not always reliable on
    -- properties that are typed as an object; use try/exists patterns instead.
end tell
```

Supported comparisons include `is`, `is not`, `contains`, `does not contain`, `starts with`, `ends with`, `is greater than`, `is less than`, etc. Boolean combinators `and`, `or`, `not`.

### Known limitation

Using `whose parent tag is missing value` on tags can fail with a type-coercion error because `parent tag` is typed as `tag`, not nullable. Workaround: iterate and use `try`:

```applescript
set rootTags to {}
repeat with t in (every tag)
    try
        parent tag of t
    on error
        set end of rootTags to contents of t
    end try
end repeat
```

______________________________________________________________________

## Creating objects (`make`)

Summary of creation patterns.

### To do

```applescript
-- Inbox (default)
make new to do with properties {name:"Buy milk"}
-- Inside a project
make new to do at project "Q2" with properties {name:"Draft"}
-- Inside an area
make new to do at area "Personal" with properties {name:"Fix sink"}
-- With all supported properties
make new to do with properties {
    name:"Write report",
    notes:"First draft due Friday",
    tag names:"Work, P1",
    due date:(current date) + (14 * days)
}
```

Note: you cannot set `activation date` at creation time — use `schedule` afterwards, or pass `at list "Today"` / `at list "Someday"`.

### Project

```applescript
set p to make new project with properties {
    name:"Website redesign",
    notes:"Kickoff Monday",
    area:area "Work",
    tag names:"P2",
    due date:(current date) + (90 * days)
}
```

### Area

```applescript
make new area with properties {name:"Family", tag names:"Personal"}
```

### Tag

```applescript
-- Top-level
make new tag with properties {name:"Waiting"}
-- Child
make new tag with properties {name:"External", parent tag:tag "Waiting"}
-- With keyboard shortcut (single character)
make new tag with properties {name:"Urgent", keyboard shortcut:"u"}
```

### Contact

```applescript
-- NOT make new contact — use:
set c to add contact named "Alex Example"
```

______________________________________________________________________

## Deleting / archiving items

| Target        | `delete`                                         | `move to Trash` | `empty trash`                          | Notes                                                                                      |
| ------------- | ------------------------------------------------ | --------------- | -------------------------------------- | ------------------------------------------------------------------------------------------ |
| Active to do  | ✅                                               | ✅              | —                                      | `delete` hard-deletes (bypasses Trash). `move to list "Trash"` is the graceful path.       |
| Logged to do  | ❌ (unreliable — call returns but item persists) | ❓ untested     | Cleared along with everything in Trash | Generally avoid touching logbook items programmatically.                                   |
| Trashed to do | ❌                                               | —               | ✅ (all-at-once)                       | `empty trash` is the only way to permanently clear Trash without user action.              |
| Project       | ✅                                               | ✅              | —                                      |                                                                                            |
| Area          | ✅                                               | —               | —                                      | Deleting an area does NOT delete the to dos/projects inside; they become orphaned (Inbox). |
| Tag           | ✅                                               | —               | —                                      | Deleting a tag removes it from all items that carried it.                                  |
| Contact       | ✅ (untested here, but sdef permits it)          | —               | —                                      |                                                                                            |

To batch-empty the Trash: `empty trash`.

______________________________________________________________________

## Scheduling and dates

Things has three independent date fields per to do:

- **`activation date`** (also called "When"/"Scheduled for") — **when** the to do should appear as actionable. Read-only. Controlled by `schedule … for <date>`, or by `move to list "Today" / "Someday" / "Anytime"`, or by creating `at list "Today"`.
- **`due date`** ("Deadline") — when the to do is overdue. Read-write directly. Pass a `date` or `missing value` to clear.
- `completion date` / `cancellation date` — set by `status` transitions, or writable for backfilling.

Date construction in AppleScript:

```applescript
-- Today at midnight local
set midnightToday to current date - (time of (current date))
-- 7 days from now
set in7 to (current date) + (7 * days)
-- Specific date: use "date" coercion from a string (US-like locale-sensitive!)
set d to date "Friday, 1 May 2026 at 9:00:00 AM"
```

For programmatic portability across locales, construct dates from components:

```applescript
set d to current date
set year of d to 2026
set month of d to 5
set day of d to 1
set time of d to 9 * hours
```

Things stores activation dates as day-granularity (empirically always midnight local). Due dates are also day-granularity.

______________________________________________________________________

## Tags: working with the `tag names` property

The `tag names` property is a **string** containing a comma-separated list of tag names. Example value: `"P1, Work"`. Whitespace around commas is tolerated on write; reading returns a canonical form. Things automatically:

- Creates tags on the fly when you assign a name that doesn't exist yet.
- Maps name → existing tag object (case-sensitive match).

To add a tag while preserving existing ones:

```applescript
tell application "Things3"
    set t to to do id "…"
    set current to tag names of t
    if current is "" then
        set tag names of t to "NewTag"
    else
        set tag names of t to current & ", NewTag"
    end if
end tell
```

To remove a tag, rewrite the string without it.

Alternatively, you can manipulate the `tags` element collection directly (make/remove `tag` associations), but `tag names` is almost always simpler.

______________________________________________________________________

## Null / missing values

- Optional date properties (`due date`, `activation date`, `completion date`, `cancellation date`) return `missing value` when unset. Assigning `missing value` clears them (where writable).

- Optional object references (`project`, `area`, `contact`) return `missing value` when unset. Attempting `name of (project of t)` when there is no project raises `Can't make name of missing value into type Unicode text` (error `-1700`). Always test first:

  ```applescript
  set projName to ""
  if exists project of t then set projName to name of project of t
  -- or:
  try
      set projName to name of project of t
  on error
      set projName to ""
  end try
  ```

- `parent tag` on a root tag raises a type-coercion error rather than returning `missing value` cleanly. Always wrap access in `try`.

- `coerce` `missing value` to text with `as text` yields the literal string `"missing value"` — useful for diagnostic logging.

______________________________________________________________________

## Error codes you will encounter

| Code                    | Meaning / cause                                                                                                                             |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `-1700`                 | Type coercion failed. Usually `Can't make <thing> of missing value into …` when you dereference a null.                                     |
| `-1719`                 | Invalid index / object not found when resolving a specifier with a `whose` clause. (E.g. `first to do whose name is "x"` returned nothing.) |
| `-1728`                 | Can't get <object> — reference became invalid (commonly after you deleted or soft-deleted the item; subsequent access errors).              |
| `-1743`                 | `errAEEventNotPermitted` — macOS Automation privacy has not granted your process permission to control Things.                              |
| `301` (Things-specific) | `Cannot move to-do` — typically raised by `move` when the target is a `project` (not allowed) or otherwise invalid.                         |

Your code should:

- Wrap individual operations in `try` and surface human-readable errors.
- Cache IDs rather than references; re-resolve by `id` if an operation fails with `-1728`.
- Be defensive about `missing value`.

______________________________________________________________________

## Hidden / experimental / undocumented members

The following appear in `Things.sdef` but are marked `hidden="yes"`. They are **not** part of the supported API; Cultured Code can change or remove them at any time. Use only if you accept the risk.

- Application properties:
  - `current list url` — URL of the list currently visible in the frontmost window.
  - `current list name` — Display name of same.
  - `_private_experimental_ current list json` — JSON blob describing the current list's contents (experimental).
- Per-`to do` property:
  - `_private_experimental_ json` — JSON blob with the to do's full state (experimental).
- Commands:
  - `filter by previous top tag`, `filter by next top tag` — UI tag-filter navigation.
  - `get localized string (from <table>)` — internal localization helper.
  - `_private_experimental_ reorder to dos in <list> with ids <text>` — reorder to dos in a list by passing a list of IDs.

______________________________________________________________________

## End-to-end recipes

These recipes use `osascript -e '…'` syntax for portability. Adapt to JXA or another binding as needed.

### 1. Add a to do to Inbox

```applescript
tell application "Things3"
    make new to do with properties {name:"Buy milk", notes:"2L full-fat", tag names:"Errand"}
end tell
```

### 2. Add a to do to Today, scheduled for now

```applescript
tell application "Things3"
    set t to make new to do with properties {name:"Respond to email"}
    move t to list "Today"
    return id of t
end tell
```

### 3. Add a to do to a project, due in 3 days

```applescript
tell application "Things3"
    set p to project "Q2 Planning"
    set t to make new to do at p with properties {
        name:"Draft OKRs",
        due date:(current date) + (3 * days),
        tag names:"P1"
    }
    return id of t
end tell
```

### 4. Export all open to dos in Today as tab-separated records

```applescript
tell application "Things3"
    set out to ""
    repeat with t in (to dos of list "Today")
        set due to "-"
        try
            set due to (due date of t) as text
        end try
        set proj to "-"
        try
            set proj to name of project of t
        end try
        set out to out & (id of t) & tab & (name of t) & tab & proj & tab & due & linefeed
    end repeat
    return out
end tell
```

### 5. Find all overdue open to dos

```applescript
tell application "Things3"
    every to do whose status is open and due date is less than (current date)
end tell
```

### 6. Mark a to do complete by ID

```applescript
tell application "Things3"
    set status of (to do id "Jso2YLTSiLmVjtEB31m52N") to completed
end tell
```

### 7. Reopen a completed/canceled to do

```applescript
tell application "Things3"
    set status of (to do id "…") to open
    -- completion date / cancellation date clear automatically
end tell
```

### 8. Reschedule a to do for next Monday

```applescript
tell application "Things3"
    set t to to do id "…"
    -- compute next Monday
    set d to current date
    set dow to weekday of d as integer   -- 1..7, Sunday==1
    set offset to (2 - dow + 7) mod 7
    if offset is 0 then set offset to 7
    schedule t for (d + offset * days)
end tell
```

### 9. Create a project with nested to dos

```applescript
tell application "Things3"
    set p to make new project with properties {
        name:"Website redesign",
        notes:"See brief at https://…",
        area:area "Work",
        due date:(current date) + (60 * days)
    }
    repeat with n in {"Audit analytics", "Draft IA", "Hi-fi mocks", "QA pass"}
        make new to do at p with properties {name:(contents of n)}
    end repeat
    return id of p
end tell
```

### 10. Soft-delete (move to trash) all to dos with a given tag

```applescript
tell application "Things3"
    repeat with t in (every to do whose tag names contains "Abandoned")
        move t to list "Trash"
    end repeat
end tell
```

### 11. Iterate all projects and summarize progress

```applescript
tell application "Things3"
    set out to ""
    repeat with p in projects
        set openCount to count of (to dos of p whose status is open)
        set doneCount to count of (to dos of p whose status is completed)
        set out to out & (name of p) & ": " & openCount & " open / " & doneCount & " done" & linefeed
    end repeat
    return out
end tell
```

### 12. Open Things' UI on a specific project

```applescript
tell application "Things3" to show project "Q2 Planning"
```

### 13. Force the log-completed sweep (move completed items to Logbook)

```applescript
tell application "Things3" to log completed now
```

### 14. Read the currently selected to dos

```applescript
tell application "Things3"
    set names to {}
    repeat with t in selected to dos
        set end of names to name of t
    end repeat
    return names
end tell
```

### 15. Dump all tags with their parents

```applescript
tell application "Things3"
    set out to ""
    repeat with t in tags
        set parentName to ""
        try
            set parentName to name of parent tag of t
        end try
        set out to out & (name of t) & tab & parentName & linefeed
    end repeat
    return out
end tell
```

______________________________________________________________________

## Gotchas and caveats

01. **Bundle identifier / app name.** Target is `Things3`, not `Things`. In AppleScript `tell application "Things3"`. Bundle ID is `com.culturedcode.ThingsMac`.

02. **Localization.** `list "Today"` only works on an English Things install. On a localized install, the names are translated. Use `list id "TMTodayListSource"` etc. for robustness.

03. **`project` is a `to do`, not a `list`.** So `to dos of project "X"` works (projects have a `to dos` element), but `move t to project "X"` does **not** (move's `to` parameter is a list, and project is not a list). Use `set project of t` or create `at project`.

04. **`lists` collection is heterogeneous.** It contains built-in lists AND areas. Check `class` to tell them apart if needed.

05. **`to dos` at the application level excludes Logbook and Trash.** If you want every to do ever, you must also iterate `to dos of list "Logbook"` and `to dos of list "Trash"`.

06. **`activation date` is read-only.** Must be set via `schedule for …` or by moving into Today/Someday/Anytime.

07. **`tag names` is a single string, not a list.** Commas separate. Tags are auto-created on assignment; they're never auto-deleted.

08. **`missing value` coercion errors.** Dereferencing `name of project of t` on a to do with no project raises `-1700`. Always guard.

09. **`parent tag is missing value` doesn't work in `whose`.** Iterate with `try` instead.

10. **`delete` on logbook items silently fails.** Use `empty trash` or leave them.

11. **Status transitions have side effects on dates.** Marking `completed` sets `completion date`. Marking `canceled` sets `cancellation date`. Reopening (`open`) clears both.

12. **`move` with project target errors.** Use `set project of t`.

13. **Automation privacy prompt.** The first Apple Event from a new process pops a macOS dialog asking the user to authorize. In headless environments (CI, SSH with no GUI) you need to pre-authorize the driving process via `tccutil` / TCC plist / MDM, or the event will fail with `-1743`.

14. **`selected to dos`** returns empty when no Things window is open or nothing is selected. Don't assume it has contents.

15. **Performance.** `osascript -e` has ~50–200 ms per-invocation overhead (process launch + Apple Event roundtrip). For bulk reads, batch work inside a single `tell` block (ideally returning a string you parse on the caller side) rather than making many small calls. For sustained workloads, prefer a persistent binding (JXA via a long-running Node process, `py-appscript`, Scripting Bridge) over repeated `osascript` shells. Within a `tell` block, **also prefer `<property> of every to do of <scope>` over `repeat with t in (every to do of <scope>) … <property> of t`**: the collection form returns a parallel list in a single Apple Event, while per-element property reads inside a `repeat` pay one Apple Event per property per todo. On a ~500-todo database the difference is roughly an order of magnitude in wall-clock time. Note that this only works for properties AppleScript can resolve uniformly across every element — `project of every to do` and `area of every to do` raise when any element has no project/area attached, so optional relationships still need a per-element `try`-wrapped accessor.

16. **`make`'s `at` clause type.** Accepts: nothing (defaults), `list` (built-in or area), `project`, `area`. Does NOT accept tags or contacts as a creation target for to dos.

17. **Re-entrancy.** Things serializes AppleScript calls. If your process makes concurrent calls from multiple threads you will see them queued, not parallelized.

18. **There is no `save` command.** All mutations persist immediately in Things' own store (and sync via Things Cloud if enabled). You do not need to call anything to "commit".

19. **No notifications / eventing.** The AppleScript interface is purely request/response. There is no way to subscribe to "to do changed" events via this API. If you need change detection, poll (e.g. check `modification date`) or use the JSON export properties (`_private_experimental_` — unsupported).

20. **The `things://` URL scheme.** Things also exposes a `things://` x-callback URL scheme (e.g. `things:///add?title=…`). It is separate from AppleScript, is supported on both macOS and iOS, and is often used for "add a to do" integrations. This document does not cover it. For anything beyond "add" (reading data, complex updates), AppleScript is strictly more capable on macOS.
