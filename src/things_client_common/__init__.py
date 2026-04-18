"""Shared argparse surface and JSON contract for Things client CLIs.

Both ``things-client-cli-applescript`` and ``tests/things_client_fake``
run the same argparse shape — ``todos`` / ``projects`` / ``areas``
sub-commands mirroring the read surface of ``things-cli`` — and emit the
same JSON envelopes. Factored here so the two implementations cannot
drift from each other on the subprocess contract the bridge relies on.
"""
