# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""things-client-cli-applescript — AppleScript-backed Things 3 client CLI.

The shipped Things client invoked as a subprocess by ``things-bridge``.
Reads Things via ``osascript``, emits JSON on stdout. No authentication —
the trust boundary is the local user executing it.
"""
