# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Test-only ``gpg``-argv-compatible fake.

Substitutes for the host ``gpg`` binary in bridge tests so the
``GpgSubprocessClient`` can be exercised without a real keyring or
the unbounded variance of real-key cryptography. Reads a YAML
fixture describing the in-memory keyring and synthesises
deterministic signature bytes from
``(key_fingerprint, payload_sha256)``.

Per ADR 0033's 2026-04-25 amendment (issue #316) the fake speaks
the ``gpg`` argv subset the bridge actually invokes — it replaced
the JSON-envelope subprocess contract used while
``gpg-backend-cli-host`` was a separate package. Invocation shape::

    python -m gpg_backend_fake --fixtures PATH \\
        --batch --no-tty --pinentry-mode loopback --status-fd 2 \\
        --keyid-format long --local-user <key> --detach-sign [--armor]

    python -m gpg_backend_fake --fixtures PATH \\
        --batch --no-tty --status-fd 2 --keyid-format long \\
        --verify <sigfile> <datafile>

Not shipped in any wheel; see ``packages/gpg-bridge/pyproject.toml``
``[tool.setuptools.packages.find]`` exclusion of ``tests*`` for
precedent.
"""
