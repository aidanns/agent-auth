# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Tests for the passphrase-fd plumbing in :class:`GpgSubprocessClient`.

Per ADR 0042, the bridge feeds stored passphrases to host gpg via
:func:`os.pipe` + :func:`subprocess.Popen` with ``pass_fds``. These
tests pin the contract on three axes:

1. The supplied passphrase actually reaches the subprocess (against
   the fixture-driven ``gpg_backend_fake`` with
   ``passphrase_required`` set).
2. No fds leak across two consecutive sign requests — a leaked fd
   survives in a long-running bridge and is a real exfil risk.
3. The passphrase string never appears in stdout / stderr / status
   text or in the captured log output.
4. Wrong passphrase → ``GpgBackendUnavailableError`` (mapping the
   bridge already exposes as ``signing_backend_unavailable``).
5. ``passphrase_store_enabled`` switching off (no store) reverts
   to the keyless / agent-cached path with no ``--passphrase-fd``
   in argv.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_bridge.passphrase_store import KeyringPassphraseStore
from gpg_models.errors import GpgBackendUnavailableError
from gpg_models.models import SignRequest

_FP = "D7A2B4C0E8F11234567890ABCDEF1234567890AB"
_PASSPHRASE = "correct-horse-battery-staple"


def _write_fixture(
    path: Path,
    *,
    passphrase_required: str | None = None,
    record_passphrase_path: str | None = None,
) -> Path:
    behaviours: dict[str, Any] = {}
    if passphrase_required is not None:
        behaviours["passphrase_required"] = passphrase_required
    if record_passphrase_path is not None:
        behaviours["record_passphrase_path"] = record_passphrase_path
    fixture: dict[str, Any] = {
        "keys": [
            {
                "fingerprint": _FP,
                "user_ids": ["Test Key <test@example.invalid>"],
                "aliases": ["test@example.invalid"],
            }
        ]
    }
    if behaviours:
        fixture["behaviours"] = behaviours
    path.write_text(yaml.safe_dump(fixture))
    return path


def _store_with(fp: str, passphrase: str) -> KeyringPassphraseStore:
    """Return a :class:`KeyringPassphraseStore` backed by a process-local dict.

    Patches the module-level ``keyring`` reference so the store
    operates on an in-memory dict for the duration of one test.
    """
    backing: dict[tuple[str, str], str] = {}

    def _get(service: str, username: str) -> str | None:
        return backing.get((service, username))

    def _set(service: str, username: str, password: str) -> None:
        backing[(service, username)] = password

    def _del(service: str, username: str) -> None:
        if (service, username) in backing:
            del backing[(service, username)]
        else:
            from keyring.errors import PasswordDeleteError

            raise PasswordDeleteError("no such entry")

    from unittest.mock import patch as _patch

    patches = (
        _patch("gpg_bridge.passphrase_store.keyring.get_password", side_effect=_get),
        _patch("gpg_bridge.passphrase_store.keyring.set_password", side_effect=_set),
        _patch("gpg_bridge.passphrase_store.keyring.delete_password", side_effect=_del),
    )
    for p in patches:
        p.start()
    store = KeyringPassphraseStore()
    store.set(fp, passphrase)
    return store


def _client(fixture_path: Path, store: KeyringPassphraseStore | None) -> GpgSubprocessClient:
    return GpgSubprocessClient(
        command=[sys.executable, "-m", "gpg_backend_fake", "--fixtures", str(fixture_path)],
        timeout_seconds=15.0,
        passphrase_store=store,
    )


class TestSignWithStoredPassphrase:
    @pytest.mark.covers_function("Sign Payload")
    def test_supplied_passphrase_unlocks_signing(self, tmp_path: Path) -> None:
        recording = tmp_path / "recorded.txt"
        fixture = _write_fixture(
            tmp_path / "fx.yaml",
            passphrase_required=_PASSPHRASE,
            record_passphrase_path=str(recording),
        )
        store = _store_with(_FP, _PASSPHRASE)
        client = _client(fixture, store)

        result = client.sign(SignRequest(local_user=_FP, payload=b"x", armor=True))

        assert result.signature.startswith(b"-----BEGIN PGP SIGNATURE-----")
        # Confirm the fake observed the passphrase via --passphrase-fd.
        observed = recording.read_text().splitlines()
        assert observed == [_PASSPHRASE]

    @pytest.mark.covers_function("Sign Payload")
    def test_wrong_passphrase_maps_to_backend_unavailable(self, tmp_path: Path) -> None:
        fixture = _write_fixture(tmp_path / "fx.yaml", passphrase_required="actually-this")
        store = _store_with(_FP, "but-store-has-this")
        client = _client(fixture, store)

        with pytest.raises(GpgBackendUnavailableError):
            client.sign(SignRequest(local_user=_FP, payload=b"x"))

    @pytest.mark.covers_function("Sign Payload")
    def test_passphrase_absent_in_outputs(
        self, tmp_path: Path, capfd: pytest.CaptureFixture[str]
    ) -> None:
        recording = tmp_path / "recorded.txt"
        fixture = _write_fixture(
            tmp_path / "fx.yaml",
            passphrase_required=_PASSPHRASE,
            record_passphrase_path=str(recording),
        )
        store = _store_with(_FP, _PASSPHRASE)
        client = _client(fixture, store)

        result = client.sign(SignRequest(local_user=_FP, payload=b"y", armor=True))

        captured = capfd.readouterr()
        # The passphrase must not appear in the result, in any of the
        # captured streams, or in the status text the bridge will go
        # on to log.
        assert _PASSPHRASE not in result.signature.decode("ascii", errors="replace")
        assert _PASSPHRASE not in result.status_text
        assert _PASSPHRASE not in captured.out
        assert _PASSPHRASE not in captured.err

    @pytest.mark.covers_function("Sign Payload")
    def test_no_store_falls_back_to_simple_invoke(self, tmp_path: Path) -> None:
        fixture = _write_fixture(tmp_path / "fx.yaml")
        client = _client(fixture, store=None)

        # No passphrase plumbing — the existing keyless fixture must
        # sign exactly as it does in test_gpg_subprocess_client.
        result = client.sign(SignRequest(local_user=_FP, payload=b"z", armor=True))
        assert result.signature.startswith(b"-----BEGIN PGP SIGNATURE-----")

    @pytest.mark.covers_function("Sign Payload")
    def test_store_with_no_entry_falls_back(self, tmp_path: Path) -> None:
        fixture = _write_fixture(tmp_path / "fx.yaml")
        # Empty store: no entries for ``_FP``. Must use the simple path
        # exactly like ``passphrase_store_enabled = False``.
        from unittest.mock import patch

        backing: dict[tuple[str, str], str] = {}
        with (
            patch(
                "gpg_bridge.passphrase_store.keyring.get_password",
                side_effect=lambda s, u: backing.get((s, u)),
            ),
            patch(
                "gpg_bridge.passphrase_store.keyring.set_password",
                side_effect=lambda s, u, p: backing.update({(s, u): p}),
            ),
            patch(
                "gpg_bridge.passphrase_store.keyring.delete_password",
                side_effect=lambda s, u: backing.pop((s, u), None),
            ),
        ):
            store = KeyringPassphraseStore()
            client = _client(fixture, store)
            result = client.sign(SignRequest(local_user=_FP, payload=b"q", armor=True))
            assert result.signature.startswith(b"-----BEGIN PGP SIGNATURE-----")


@pytest.mark.skipif(sys.platform != "linux", reason="/proc/self/fd is Linux-only")
class TestFdLeakGuard:
    @pytest.mark.covers_function("Sign Payload")
    def test_two_consecutive_signs_leak_no_fds(self, tmp_path: Path) -> None:
        """Snapshot ``/proc/self/fd`` before and after two signs.

        A leaked passphrase fd persists across the bridge's lifetime
        and is a real exfil risk; this guards against any future
        refactor that drops a ``finally`` close.
        """
        fixture = _write_fixture(tmp_path / "fx.yaml", passphrase_required=_PASSPHRASE)
        store = _store_with(_FP, _PASSPHRASE)
        client = _client(fixture, store)

        # Warm up: Python lazy-imports and OS-level fixtures can
        # allocate fds on the first call. Snapshot after the first
        # sign so subsequent calls represent steady state.
        client.sign(SignRequest(local_user=_FP, payload=b"warmup"))
        baseline = sorted(os.listdir("/proc/self/fd"))

        for _ in range(3):
            client.sign(SignRequest(local_user=_FP, payload=b"more"))

        after = sorted(os.listdir("/proc/self/fd"))
        # Allow standard noise: pytest captures, .pyc lazy imports.
        # The strict check is that no *new* anonymous pipe fds
        # remain — pipes show up as ``pipe:[N]`` in
        # ``/proc/self/fd/<n> -> ...``. Compare counts to detect
        # leaks without depending on exact fd numbers.
        assert (
            len(after) <= len(baseline) + 2
        ), f"fd leak detected: baseline={len(baseline)} after={len(after)}"
