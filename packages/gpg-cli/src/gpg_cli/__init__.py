# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Devcontainer-side gpg replacement.

Git invokes this CLI via ``git config gpg.program gpg-cli``. It parses
the subset of the gpg command line git drives (sign + verify), forwards
the request to gpg-bridge over HTTPS, and writes gpg-shaped output
(signature bytes to stdout, status-fd lines to the configured fd).
"""
