# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Entrypoint for ``python -m gpg_backend_fake``."""

import sys

from gpg_backend_fake.cli import main

if __name__ == "__main__":
    sys.exit(main())
