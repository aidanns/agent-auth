# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Host-side GPG backend CLI.

Runs on the same host as the user's gpg keyring. Invoked as a
subprocess by :mod:`gpg_bridge` per request; speaks the shared
backend subprocess contract defined in :mod:`gpg_backend_common.cli`.
No HTTP, no authorization — the trust boundary is that the local user
ran it.
"""
