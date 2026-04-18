"""Test-only Things client backed by an in-memory YAML store.

Packaged under ``tests/`` so it is never shipped in the production
sdist / wheel. Invoked in integration and end-to-end tests as:

.. code-block:: text

    [sys.executable, "-m", "tests.things_client_fake", "--fixtures", PATH, ...]

The CLI's argument surface and JSON contract match
``things-client-cli-applescript`` byte-for-byte on the read path — that
equivalence is what lets the bridge under test treat the two as
interchangeable.
"""

from tests.things_client_fake.store import (
    FakeThingsClient,
    FakeThingsStore,
    load_fake_store,
)

__all__ = ["FakeThingsClient", "FakeThingsStore", "load_fake_store"]
