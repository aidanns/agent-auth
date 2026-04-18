"""Entrypoint for ``python -m tests.things_client_fake``."""

import sys

from tests.things_client_fake.cli import main

if __name__ == "__main__":
    sys.exit(main())
