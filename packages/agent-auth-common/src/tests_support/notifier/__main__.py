# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""``python -m tests_support.notifier {approve|deny}`` entrypoint."""

from __future__ import annotations

import argparse
import sys

from tests_support.notifier.server import run_fixed_notifier


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tests_support.notifier")
    parser.add_argument("mode", choices=("approve", "deny"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9150)
    args = parser.parse_args()
    # ``install_signal_handlers=True`` is critical here: the integration
    # compose stack runs this entrypoint as PID 1 inside the notifier
    # container, where the kernel ignores SIGTERM unless the process
    # explicitly handles it. See the docstring in ``server.py`` and #294
    # for the diagnostic chain.
    run_fixed_notifier(
        args.host,
        args.port,
        approved=(args.mode == "approve"),
        install_signal_handlers=True,
    )


if __name__ == "__main__":
    main()
    sys.exit(0)
