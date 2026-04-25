# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Shared argparse surface and dispatcher for GPG backend CLIs.

Both backend CLIs (``gpg-backend-cli-host`` and the in-tree fake
``python -m gpg_backend_fake``) build their own backend, then
hand off to :func:`run_cli` here so the subprocess contract has a
single source of truth.

## Subprocess contract

- argv: ``<program> sign   --local-user <keyid> [--armor] [--keyid-format <fmt>]``
         ``<program> verify [--keyid-format <fmt>]``.
- stdin for ``sign``: raw payload bytes.
- stdin for ``verify``: 4-byte big-endian signature length, the
  signature bytes, then the payload bytes until end-of-stream.
- stdout: JSON envelope (see :mod:`gpg_models.models`). On success the
  body is ``{"signature_b64": ..., "status_text": ..., "exit_code": 0}``
  for sign or ``{"status_text": ..., "exit_code": 0}`` for verify; on
  error it is ``{"error": "<code>", "detail": "..."}``.
- exit code: 0 on success, non-zero on error.
- stderr: operator diagnostics only. The bridge forwards it to its own
  stderr and never surfaces it in HTTP responses.
"""
