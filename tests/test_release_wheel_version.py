# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Regression tests for the per-package wheel version derivation.

`v0.16.0` shipped 70 supply-chain assets every one of which was
versioned ``0.0.0+unknown`` instead of ``0.16.0`` — the
``cosign verify`` recipe in SECURITY.md § Supply-chain artifacts
hardcodes ``${PKG}-${VERSION}-py3-none-any.whl``, so the documented
verification path could not match a single asset on the release page
(issue #408).

The root cause was that each ``packages/<svc>/pyproject.toml`` declared
``[tool.setuptools_scm]`` without setting ``root``. With
``uv build --all-packages``, the build runs from the per-package
directory which is not a git root; setuptools-scm fell back to
``fallback_version = "0.0.0+unknown"`` instead of reading the
workspace's git tags. The fix points each package's setuptools-scm
config at the workspace root via ``root = "../.."``.

These tests guard both halves of the fix:

- ``test_every_package_pins_setuptools_scm_root_to_workspace`` is a
  static assertion on ``[tool.setuptools_scm].root`` for every
  workspace member. A new package added without the right ``root``
  fails here without needing to run ``uv build``.
- ``test_uv_build_derives_version_from_git`` actually shells out to
  ``scripts/build-release-artifacts.sh`` and asserts every produced
  wheel + sdist filename shares one non-fallback version segment. The
  ``release-publish.yml`` workflow gate cross-checks the version
  against the release tag at publish time; this PR-time smoke test
  only needs to assert the build is reading git, not falling back to
  ``0.0.0+unknown`` — which is what would have caught the v0.16.0
  regression at PR time.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = REPO_ROOT / "packages"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build-release-artifacts.sh"


def _every_package_pyproject() -> list[Path]:
    """Return ``pyproject.toml`` for every workspace member."""
    return sorted(PACKAGES_DIR.glob("*/pyproject.toml"))


def test_every_package_pins_setuptools_scm_root_to_workspace() -> None:
    # ``root`` must be ``../..`` (relative to the per-package
    # pyproject.toml) so setuptools-scm walks two levels up to find
    # the workspace's ``.git`` instead of falling back to
    # ``fallback_version`` (issue #408).
    pyprojects = _every_package_pyproject()
    assert pyprojects, "no workspace members found under packages/*"
    misconfigured: list[str] = []
    for path in pyprojects:
        cfg = tomllib.loads(path.read_text())
        scm = cfg.get("tool", {}).get("setuptools_scm")
        if scm is None:
            # Packages can opt out of setuptools-scm entirely (e.g.
            # by switching backend), but the current workspace expects
            # every member to use it. If a package legitimately
            # opts out, update this assertion together with the
            # ``release-dryrun.yml`` filename gate.
            misconfigured.append(f"{path}: missing [tool.setuptools_scm]")
            continue
        if scm.get("root") != "../..":
            misconfigured.append(
                f"{path}: [tool.setuptools_scm].root must be '../..' " f"(got {scm.get('root')!r})"
            )
    assert not misconfigured, "\n".join(misconfigured)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_uv_build_derives_version_from_git(tmp_path: Path) -> None:
    # Build the full workspace into a throwaway dist/ and verify every
    # wheel + sdist filename carries the same non-fallback version
    # segment. The v0.16.0 regression manifested as filenames containing
    # ``0.0.0+unknown``; this assertion would have failed pre-merge.
    out_dir = tmp_path / "dist"
    subprocess.run(
        [str(BUILD_SCRIPT), "--out", str(out_dir)],
        cwd=REPO_ROOT,
        check=True,
    )

    wheels = sorted(out_dir.glob("*.whl"))
    sdists = sorted(out_dir.glob("*.tar.gz"))
    assert wheels, f"no wheels produced under {out_dir}"
    assert sdists, f"no sdists produced under {out_dir}"

    versions = {_extract_version_from_artefact(p.name) for p in (*wheels, *sdists)}
    # Every workspace member shares the same git-derived version, so
    # the set of observed versions must be a singleton. A drift here
    # means one (or more) packages built against a different SCM root
    # — exactly the v0.16.0 failure mode.
    assert (
        len(versions) == 1
    ), f"expected all artefacts to share one version; got {sorted(versions)}"
    (version,) = versions
    # Reject the setuptools-scm fallback verbatim — that string is the
    # signature of the regression this test exists to catch. The
    # ``release-publish.yml`` guard cross-checks the version against
    # the release tag at publish time; this PR-time test only needs
    # to assert the build is reading git, not falling back.
    assert "0.0.0+unknown" not in version, (
        f"artefacts versioned as setuptools-scm fallback ({version!r}); "
        "[tool.setuptools_scm].root is not pointing at the workspace git root"
    )


def _extract_version_from_artefact(filename: str) -> str:
    """Return the PEP-440 version segment of a wheel or sdist filename.

    Wheel: ``{name}-{version}-py3-none-any.whl``.
    Sdist: ``{name}-{version}.tar.gz``.

    PEP 440 versions must not contain ``-``, so splitting the
    pre-suffix stem on the final ``-`` cleanly separates name from
    version even when the project name contains underscores.
    """
    if filename.endswith("-py3-none-any.whl"):
        stem = filename[: -len("-py3-none-any.whl")]
    elif filename.endswith(".tar.gz"):
        stem = filename[: -len(".tar.gz")]
    else:
        pytest.fail(f"unparseable artefact filename: {filename!r}")
    name, sep, version = stem.rpartition("-")
    if not sep or not name:
        pytest.fail(f"unparseable artefact filename: {filename!r}")
    return version


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
