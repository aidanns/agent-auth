# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Per-package dependency-license allowlist gate.

Inputs (read from argv):
    --package <name>     Workspace member name
                         (the directory under ``packages/``).
    --closure <file>     Newline-delimited ``name==version`` list of
                         every dep in this package's resolved
                         closure (runtime + workspace dev). The
                         caller (``scripts/check-license-allowlist.sh``)
                         produces this from ``uv export``.
    --metadata <file>    JSON dump of the workspace venv emitted by
                         the ``--emit-metadata`` mode (below). Maps
                         each installed dist to its declared SPDX
                         expression, the legacy free-form license
                         field, and the classifier list.
    --exceptions <file>  Optional. Per-package exception YAML at
                         ``packages/<svc>/licenses.exceptions.yml``.

Behaviour:
    - Loads the allowlist (constant below).
    - For each ``name==version`` in the closure, looks up the
      license expression from the metadata dump. Prefers PEP 639
      ``License-Expression`` over the legacy free-form ``License``
      field; falls back to the ``License ::`` classifier list when
      neither is set.
    - Resolves SPDX disjunctions (``A OR B``) by picking the first
      allowlisted alternative; only fails when every alternative
      is rejected.
    - SPDX conjunctions (``A AND B``) require every alternative to
      be on the allowlist — this is the SPDX semantics of "you
      must comply with all listed licenses".
    - Skips entries matched by a non-expired exception entry. An
      exception entry with a missing or expired ``expires`` field,
      or a missing ``reason`` field, is itself a violation.
    - Exits 0 if every dep is on the allowlist (or covered by an
      active exception); exits 1 otherwise. Violations print to
      stderr with ``<name>==<version>: <license>``.

Auxiliary mode (``--emit-metadata``):
    Print a JSON metadata dump of every installed dist in the
    current Python's environment. The bash driver runs this once
    per matrix job and feeds the output back as ``--metadata``.

The allowlist and the rejection-glob set are locked by issue #575
triage; do not relitigate during implementation.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Allowlist locked by #575 Agent Brief. Frozen so a callsite cannot
# accidentally mutate it.
ALLOWED_LICENSES: frozenset[str] = frozenset(
    {
        # keep-sorted start
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "MIT",
        "MPL-2.0",
        "Python-2.0",
        # keep-sorted end
    }
)

# Reject globs locked by #575. Matched as case-insensitive prefixes
# against the canonicalised expression component, so ``GPL-2.0-only``,
# ``GPL-3.0-or-later``, ``LGPL-2.1+``, etc. all hit.
REJECTED_PREFIXES: tuple[str, ...] = (
    # keep-sorted start
    "AGPL-",
    "BUSL-",
    "GPL-",
    "LGPL-",
    "SSPL-",
    # keep-sorted end
)

# Common alternate spellings that we normalise to canonical SPDX
# identifiers. Many distributions still ship pre-PEP-639 free-form
# strings or rely on ``License ::`` classifier prose; fold those
# onto canonical SPDX so the allowlist stays SPDX-only.
_LICENSE_ALIASES: dict[str, str] = {
    # keep-sorted start
    "Apache 2.0": "Apache-2.0",
    "Apache License 2.0": "Apache-2.0",
    "Apache License, Version 2.0": "Apache-2.0",
    "Apache Software License": "Apache-2.0",
    "BSD License": "BSD-3-Clause",
    "BSD": "BSD-3-Clause",
    "ISC License (ISCL)": "ISC",
    "MIT License": "MIT",
    "MIT license": "MIT",
    "MIT": "MIT",
    "MPL 2.0": "MPL-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "PSF": "Python-2.0",
    "PSF-2.0": "Python-2.0",
    "PSFL": "Python-2.0",
    "Python Software Foundation License": "Python-2.0",
    # keep-sorted end
}

# Map ``License :: ...`` classifier strings onto canonical SPDX.
# pip-licenses concatenates classifiers with ``;`` separators which
# loses information about whether they are alternatives or
# additions; reading classifiers directly keeps the relationship
# encoded by the dist (one-classifier dists are unambiguous, multi-
# classifier dists are treated as a disjunction of alternatives,
# which is the conventional reading on PyPI).
_CLASSIFIER_TO_SPDX: dict[str, str] = {
    # keep-sorted start
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: MIT No Attribution License (MIT-0)": "MIT",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "Python-2.0",
    # keep-sorted end
}


@dataclass(frozen=True)
class ExceptionEntry:
    """One row from ``licenses.exceptions.yml``."""

    name: str
    version: str
    license: str
    reason: str
    expires: datetime.date


@dataclass(frozen=True)
class Violation:
    """One dep that fails the gate."""

    name: str
    version: str
    license_expression: str
    detail: str


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--emit-metadata",
        action="store_true",
        help="Dump installed-dist license metadata as JSON and exit",
    )
    parser.add_argument("--package")
    parser.add_argument("--closure", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--exceptions", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.emit_metadata:
        missing = [
            flag
            for flag, value in (
                ("--package", args.package),
                ("--closure", args.closure),
                ("--metadata", args.metadata),
            )
            if value is None
        ]
        if missing:
            parser.error(f"missing required arguments: {missing}")
    return args


def emit_installed_metadata() -> str:
    """Walk the active env's installed dists and emit a JSON dump.

    Each entry carries:
        - ``name``     — the dist's reported package name
        - ``version``  — the installed version
        - ``license_expression`` — PEP 639 ``License-Expression`` (or "")
        - ``license``  — legacy free-form ``License`` field (or "")
        - ``classifiers`` — list of ``License :: …`` classifiers

    The bash driver captures stdout into a temp file and feeds it
    back via ``--metadata``. Keeping this in-process avoids
    inheriting pip-licenses's classifier-folding losses.
    """

    import importlib.metadata as importmd

    def _field(meta: Any, key: str) -> str:
        # ``PackageMetadata`` is ``email.message.Message`` at runtime
        # (which has ``.get``), but the typeshed stub elides the
        # ``.get`` method. Use ``__getitem__`` against ``__contains__``
        # to stay typed; this is the fallback shape both mypy and
        # ruff accept.
        return str(meta[key]) if key in meta else ""

    entries: list[dict[str, Any]] = []
    for dist in importmd.distributions():
        meta = dist.metadata
        name = _field(meta, "Name")
        if not name:
            continue
        all_classifiers = meta.get_all("Classifier") or []
        license_classifiers: list[str] = [
            str(classifier)
            for classifier in all_classifiers
            if str(classifier).startswith("License ::")
        ]
        entries.append(
            {
                "name": name,
                "version": _field(meta, "Version"),
                "license_expression": _field(meta, "License-Expression"),
                "license": _field(meta, "License"),
                "classifiers": license_classifiers,
            }
        )
    return json.dumps(entries, sort_keys=True, indent=2)


def read_closure(path: Path) -> set[tuple[str, str]]:
    """Read a ``name==version`` list emitted by ``uv export``.

    Lines that don't match are dropped silently — they are comment
    lines or marker lines (``--hash``, ``# via …``) that ``uv export``
    interleaves into requirements.txt format.
    """

    pin_re = re.compile(r"^([A-Za-z0-9._-]+)==([^\s;]+)")
    pins: set[tuple[str, str]] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = pin_re.match(raw_line.strip())
        if not match:
            continue
        name, version = match.group(1), match.group(2)
        pins.add((normalise_name(name), version))
    return pins


def normalise_name(name: str) -> str:
    """PEP 503 normalisation for cross-tool name comparison.

    ``pip-licenses`` reports ``backports.tarfile`` while
    ``uv export`` writes ``backports-tarfile``; PEP 503 collapses
    both to ``backports-tarfile``.
    """

    return re.sub(r"[-_.]+", "-", name).lower()


def parse_metadata(path: Path) -> dict[tuple[str, str], str]:
    """Read the metadata-JSON dump into a (name, version) -> SPDX map.

    Selection precedence per dist:
      1. PEP 639 ``License-Expression`` (canonical SPDX) when set.
      2. Legacy free-form ``License`` field — many older dists put
         a valid SPDX expression here.
      3. ``License :: ...`` classifier list, joined as a disjunction
         of alternatives (the conventional PyPI reading: a dist
         with both Apache and MIT classifiers is "either is OK").

    Returns an empty string for dists that have none of the above —
    the caller flags those as violations because "no license
    metadata declared" is itself a policy failure.
    """

    raw = json.loads(path.read_text(encoding="utf-8"))
    by_pin: dict[tuple[str, str], str] = {}
    for entry in raw:
        name = normalise_name(entry["name"])
        version = entry["version"]
        expression = _select_license_expression(entry)
        by_pin[(name, version)] = expression
    return by_pin


def _select_license_expression(entry: dict[str, Any]) -> str:
    """Pick the best license expression from one metadata entry."""

    expression = str(entry.get("license_expression") or "").strip()
    if expression:
        return expression
    legacy = str(entry.get("license") or "").strip()
    if legacy and "\n" not in legacy and len(legacy) < 200:
        # Older dists (cryptography, keyring) put a valid SPDX
        # expression in the ``License`` field. Skip the value if it
        # looks like a license text dump (multi-line or very long)
        # — those are common too and never parse as SPDX.
        return legacy
    raw_classifiers = entry.get("classifiers") or []
    classifiers: list[str] = [str(c) for c in raw_classifiers]
    if not classifiers:
        return ""
    # Map each classifier to canonical SPDX where we know it; drop
    # the ones we don't (``License :: DFSG approved`` for instance
    # is not an SPDX identifier on its own — the dist must declare a
    # specific license elsewhere). If every classifier is
    # unrecognised, return the first one verbatim so the violation
    # message tells the operator what was in the metadata.
    mapped = [_CLASSIFIER_TO_SPDX[c] for c in classifiers if c in _CLASSIFIER_TO_SPDX]
    if mapped:
        return " OR ".join(sorted(set(mapped)))
    return classifiers[0]


def split_disjunction(expression: str) -> list[str]:
    """Split an SPDX expression on top-level ``OR``.

    SPDX expressions can include parentheses
    (``(MIT AND Apache-2.0) OR GPL-2.0``); a future requirement may
    extend this. For #575 the only ``OR``-form cases observed in
    Python ecosystem deps are flat alternatives, so a flat split
    is sufficient. Lift to a real parser if a parenthesised
    expression appears in the closure.
    """

    parts = re.split(r"\s+OR\s+", expression.strip(), flags=re.IGNORECASE)
    return [part.strip() for part in parts if part.strip()]


def split_conjunction(expression: str) -> list[str]:
    """Split an SPDX expression on top-level ``AND``.

    Used after ``OR`` splitting: each alternative may itself be a
    conjunction (``Apache-2.0 AND MIT``), in which case every
    component must be on the allowlist for the alternative to pass.
    """

    parts = re.split(r"\s+AND\s+", expression.strip(), flags=re.IGNORECASE)
    return [part.strip() for part in parts if part.strip()]


def canonicalise(expression: str) -> str:
    """Map a free-form license string onto its canonical SPDX id.

    Strips PEP 639 ``+`` and ``-only`` / ``-or-later`` suffixes when
    matching aliases. The full string is preserved as the lookup
    key first; only when that fails do we drop suffixes.
    """

    stripped = expression.strip()
    if stripped in _LICENSE_ALIASES:
        return _LICENSE_ALIASES[stripped]
    return stripped


def is_allowed_alternative(alternative: str) -> bool:
    """Whether one alternative from a disjunction is on the allowlist.

    Each alternative may itself be a conjunction (``A AND B``); in
    that case every conjunct must canonicalise onto the allowlist.
    """

    components = split_conjunction(alternative)
    return all(canonicalise(c) in ALLOWED_LICENSES for c in components)


def is_rejected_alternative(alternative: str) -> bool:
    """Whether an alternative matches the explicit reject list.

    Used only for clearer violation messages — the allowlist itself
    is the source of truth. A license that matches neither
    ``ALLOWED_LICENSES`` nor a ``REJECTED_PREFIXES`` glob is still
    a violation; "anything custom or unrecognised" is the brief's
    explicit policy.
    """

    components = split_conjunction(alternative)
    return any(
        canonicalise(c).upper().startswith(prefix)
        for c in components
        for prefix in REJECTED_PREFIXES
    )


def evaluate_expression(expression: str) -> tuple[bool, str]:
    """Decide if an SPDX expression passes the allowlist.

    Returns ``(allowed, detail)``:

    - ``allowed`` — True if any disjunction alternative is wholly
      allowlisted (every conjunct on the allowlist).
    - ``detail`` — short reason string, used in violation output.
    """

    if not expression:
        return False, "no license metadata declared"
    alternatives = split_disjunction(expression)
    if not alternatives:
        return False, "empty SPDX expression"
    for alternative in alternatives:
        if is_allowed_alternative(alternative):
            canonical = " AND ".join(canonicalise(c) for c in split_conjunction(alternative))
            return True, f"matched allowlist via '{canonical}'"
    if any(is_rejected_alternative(alt) for alt in alternatives):
        return False, "rejected by copyleft / commercial policy"
    return False, "license not on allowlist"


def load_exceptions(path: Path | None) -> tuple[list[ExceptionEntry], list[str]]:
    """Parse ``licenses.exceptions.yml``.

    Returns ``(entries, errors)``. ``errors`` is non-empty if the
    file declares an exception missing ``reason`` or ``expires``,
    or with an unparseable ``expires`` date — those are violations
    in their own right (see Agent Brief).
    """

    if path is None or not path.exists():
        return [], []
    # PyYAML is already a workspace dependency (used by agent-auth's
    # config loader); importing inline keeps this helper independent
    # of which venv it ends up running in.
    import yaml

    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return [], []
    if not isinstance(raw, dict) or "entries" not in raw:
        return [], [f"{path}: top-level shape must be a mapping with an 'entries' list"]
    entries_raw: Any = raw.get("entries") or []
    if not isinstance(entries_raw, list):
        return [], [f"{path}: 'entries' must be a list"]

    entries: list[ExceptionEntry] = []
    errors: list[str] = []
    items: list[Any] = entries_raw
    for index, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            errors.append(f"{path}[{index}]: entry must be a mapping")
            continue
        item: dict[str, Any] = raw_item
        missing = [
            field
            for field in ("name", "version", "license", "reason", "expires")
            if field not in item or item[field] in (None, "")
        ]
        if missing:
            errors.append(
                f"{path}[{index}]: missing required field(s) "
                f"{sorted(missing)}; every exception MUST set "
                "name, version, license, reason, expires"
            )
            continue
        expires_raw: Any = item["expires"]
        expires: datetime.date
        if isinstance(expires_raw, datetime.date):
            expires = expires_raw
        else:
            try:
                expires = datetime.date.fromisoformat(str(expires_raw))
            except ValueError:
                errors.append(
                    f"{path}[{index}]: 'expires' must be ISO-8601 "
                    f"(YYYY-MM-DD); got {expires_raw!r}"
                )
                continue
        entries.append(
            ExceptionEntry(
                name=normalise_name(str(item["name"])),
                version=str(item["version"]),
                license=str(item["license"]),
                reason=str(item["reason"]),
                expires=expires,
            )
        )
    return entries, errors


def find_active_exception(
    name: str,
    version: str,
    exceptions: Iterable[ExceptionEntry],
    today: datetime.date,
) -> ExceptionEntry | None:
    """Return the first non-expired exception matching ``(name, version)``.

    ``today`` is parameterised so unit tests can pin the clock.
    """

    for entry in exceptions:
        if entry.name == name and entry.version == version:
            if entry.expires < today:
                continue
            return entry
    return None


def find_expired_exceptions(
    exceptions: Iterable[ExceptionEntry],
    today: datetime.date,
) -> list[ExceptionEntry]:
    """All exception entries whose ``expires`` date is in the past."""

    return [entry for entry in exceptions if entry.expires < today]


def evaluate_closure(
    package: str,
    closure: set[tuple[str, str]],
    metadata: dict[tuple[str, str], str],
    exceptions: list[ExceptionEntry],
    today: datetime.date,
) -> list[Violation]:
    """Run the gate against one package's closure.

    Deps in the closure that aren't present in the metadata dump
    are silently skipped — they are environment-marker-gated and
    won't enter the deployed artefact on this platform (e.g.
    ``pywin32-ctypes`` on a Linux runner). The CI matrix runs only
    on ``ubuntu-latest`` today; if this changes, expand the matrix
    so each platform's gating runs against its own metadata dump.
    """

    violations: list[Violation] = []
    for name, version in sorted(closure):
        license_expression = metadata.get((name, version))
        if license_expression is None:
            continue
        allowed, detail = evaluate_expression(license_expression)
        if allowed:
            continue
        exception = find_active_exception(name, version, exceptions, today)
        if exception is not None:
            continue
        violations.append(
            Violation(
                name=name,
                version=version,
                license_expression=license_expression,
                detail=detail,
            )
        )
    return violations


def format_violations(package: str, violations: list[Violation]) -> str:
    """Render the violation list as human-readable text."""

    if not violations:
        return ""
    lines = [
        f"check-license-allowlist: package '{package}' has " f"{len(violations)} violation(s):"
    ]
    for violation in violations:
        lines.append(
            f"  - {violation.name}=={violation.version}: "
            f"'{violation.license_expression}' "
            f"({violation.detail})"
        )
    return "\n".join(lines)


def format_exception_errors(errors: list[str]) -> str:
    """Render exception-file shape errors as human-readable text."""

    if not errors:
        return ""
    lines = ["check-license-allowlist: exception file has structural errors:"]
    for err in errors:
        lines.append(f"  - {err}")
    return "\n".join(lines)


def format_expired(expired: list[ExceptionEntry]) -> str:
    """Render the expired-exception list as human-readable text."""

    if not expired:
        return ""
    lines = ["check-license-allowlist: expired exception entries:"]
    for entry in expired:
        lines.append(
            f"  - {entry.name}=={entry.version}: expired "
            f"{entry.expires.isoformat()} (reason was: {entry.reason})"
        )
    return "\n".join(lines)


def main(argv: list[str], today: datetime.date | None = None) -> int:
    args = parse_arguments(argv)
    if args.emit_metadata:
        sys.stdout.write(emit_installed_metadata())
        sys.stdout.write("\n")
        return 0
    today_resolved = today or datetime.date.today()

    closure = read_closure(args.closure)
    metadata = parse_metadata(args.metadata)
    exceptions, exception_errors = load_exceptions(args.exceptions)

    expired = find_expired_exceptions(exceptions, today_resolved)
    active_exceptions = [entry for entry in exceptions if entry.expires >= today_resolved]

    violations = evaluate_closure(
        args.package,
        closure,
        metadata,
        active_exceptions,
        today_resolved,
    )

    failed = bool(violations or exception_errors or expired)
    if failed:
        for block in (
            format_exception_errors(exception_errors),
            format_expired(expired),
            format_violations(args.package, violations),
        ):
            if block:
                print(block, file=sys.stderr)
        return 1

    print(
        f"check-license-allowlist: package '{args.package}' "
        f"clean ({len(closure)} deps, "
        f"{len(active_exceptions)} active exception(s))"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
