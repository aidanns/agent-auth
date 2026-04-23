# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Reference out-of-process notifier for agent-auth.

Ships the ``terminal`` mode used for local smoke-testing. The
package is deliberately separate from ``agent_auth`` so the server
process can stay minimal — an operator who wants a GUI notifier
should replace this package entirely rather than loading plugin
code inside the server.
"""
