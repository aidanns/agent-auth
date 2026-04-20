# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Entrypoint for ``python -m tests.things_client_fake``."""

import sys

from tests.things_client_fake.cli import main

if __name__ == "__main__":
    sys.exit(main())
