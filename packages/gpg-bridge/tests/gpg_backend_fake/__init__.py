# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Test-only GPG backend fake.

Reads a YAML fixture from disk and synthesises deterministic signature
bytes from ``(key_fingerprint, payload_sha256)`` without touching a
real GPG keyring. Not shipped in the wheel; see
``pyproject.toml`` ``[tool.setuptools.packages.find]`` exclusion of
``tests_support*`` for precedent. Invoke as
``python -m gpg_backend_fake --fixtures PATH``.
"""
