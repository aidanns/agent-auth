# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI-surface tests for the ``gpg-bridge`` entrypoint.

Locks in the ``--version`` action and the ADR 0042
``passphrase set / clear / list`` subcommand group. The HTTP server
surface is exercised through ``test_gpg_bridge_server.py``.
"""

from __future__ import annotations

import argparse
import re
import sys
from importlib.metadata import version as _dist_version
from io import StringIO
from unittest.mock import patch

import pytest

from gpg_bridge.cli import _dispatch_passphrase, build_parser, main
from gpg_bridge.config import Config
from gpg_bridge.errors import PassphraseStoreError

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")
_FP = "D7A2B4C0E8F11234567890ABCDEF1234567890AB"


class _StubStore:
    """Stand-in for ``KeyringPassphraseStore`` with assertable state."""

    def __init__(self, *, raise_on: str | None = None) -> None:
        self._entries: dict[str, str] = {}
        self._raise_on = raise_on
        self.set_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []

    def set(self, fingerprint: str, passphrase: str) -> None:
        if self._raise_on == "set":
            raise PassphraseStoreError("backend down")
        self.set_calls.append((fingerprint, passphrase))
        self._entries[fingerprint.upper()] = passphrase

    def delete(self, fingerprint: str) -> None:
        if self._raise_on == "delete":
            raise PassphraseStoreError("backend down")
        self.delete_calls.append(fingerprint)
        self._entries.pop(fingerprint.upper(), None)

    def list_fingerprints(self) -> list[str]:
        if self._raise_on == "list":
            raise PassphraseStoreError("backend down")
        return sorted(self._entries.keys())


def test_version_flag_prints_distribution_version() -> None:
    """``--version`` prints ``gpg-bridge <version>`` and exits 0.

    The version string is the runtime distribution version (see
    ``cli_meta.add_version_flag``); the test asserts the prefix and a
    semver-shaped suffix so a setuptools_scm fallback still matches.
    """
    argv = ["gpg-bridge", "--version"]
    stdout = StringIO()
    with (
        patch.object(sys, "argv", argv),
        patch.object(sys, "stdout", stdout),
        pytest.raises(SystemExit) as excinfo,
    ):
        main()

    assert excinfo.value.code == 0
    line = stdout.getvalue().rstrip("\n")
    assert line.startswith("gpg-bridge "), f"unexpected prefix: {line!r}"
    payload = line[len("gpg-bridge ") :].strip()
    assert _SEMVER_RE.match(payload), f"unexpected version payload: {payload!r}"
    assert payload == _dist_version("gpg-bridge"), (
        f"CLI reported {payload!r} but importlib.metadata reports "
        f"{_dist_version('gpg-bridge')!r}"
    )


# ---------------------------------------------------------------------------
# ``passphrase`` subcommand group (ADR 0042)
# ---------------------------------------------------------------------------


def _parse_passphrase_args(argv: list[str]) -> argparse.Namespace:
    parser = build_parser()
    return parser.parse_args(argv)


class TestPassphraseSet:
    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_rejects_fingerprint_not_in_allowlist(self, capsys) -> None:
        config = Config(allowed_signing_keys=["AAAA1234"])
        store = _StubStore()
        args = _parse_passphrase_args(["passphrase", "set", _FP])

        rc = _dispatch_passphrase(
            args,
            config,
            store_factory=lambda: store,
            prompt_passphrase=lambda _: "ignored",
            resolve_key=lambda _c, _f: True,
        )

        assert rc == 3
        assert store.set_calls == []
        assert "allowed_signing_keys" in capsys.readouterr().err

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_rejects_fingerprint_host_cannot_resolve(self, capsys) -> None:
        config = Config(allowed_signing_keys=[_FP])
        store = _StubStore()
        args = _parse_passphrase_args(["passphrase", "set", _FP])

        rc = _dispatch_passphrase(
            args,
            config,
            store_factory=lambda: store,
            prompt_passphrase=lambda _: "ignored",
            resolve_key=lambda _c, _f: False,
        )

        assert rc == 4
        assert store.set_calls == []
        assert "host gpg cannot resolve" in capsys.readouterr().err

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_persists_when_validation_passes(self, capsys) -> None:
        config = Config(allowed_signing_keys=[_FP])
        store = _StubStore()
        args = _parse_passphrase_args(["passphrase", "set", _FP])

        rc = _dispatch_passphrase(
            args,
            config,
            store_factory=lambda: store,
            prompt_passphrase=lambda _: "topsecret",
            resolve_key=lambda _c, _f: True,
        )

        assert rc == 0
        assert store.set_calls == [(_FP, "topsecret")]
        captured = capsys.readouterr()
        # Confirm the passphrase never reaches stdout / stderr.
        assert "topsecret" not in captured.out
        assert "topsecret" not in captured.err
        assert _FP in captured.out

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_rejects_empty_passphrase(self, capsys) -> None:
        config = Config(allowed_signing_keys=[_FP])
        store = _StubStore()
        args = _parse_passphrase_args(["passphrase", "set", _FP])

        rc = _dispatch_passphrase(
            args,
            config,
            store_factory=lambda: store,
            prompt_passphrase=lambda _: "",
            resolve_key=lambda _c, _f: True,
        )

        assert rc == 1
        assert store.set_calls == []

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_keyring_backend_error_surfaces(self, capsys) -> None:
        config = Config(allowed_signing_keys=[_FP])
        store = _StubStore(raise_on="set")
        args = _parse_passphrase_args(["passphrase", "set", _FP])

        rc = _dispatch_passphrase(
            args,
            config,
            store_factory=lambda: store,
            prompt_passphrase=lambda _: "p",
            resolve_key=lambda _c, _f: True,
        )

        assert rc == 5
        assert "keyring error" in capsys.readouterr().err


class TestPassphraseClear:
    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_clear_invokes_store(self, capsys) -> None:
        store = _StubStore()
        args = _parse_passphrase_args(["passphrase", "clear", _FP])
        rc = _dispatch_passphrase(
            args,
            Config(),
            store_factory=lambda: store,
        )
        assert rc == 0
        assert store.delete_calls == [_FP]
        assert _FP in capsys.readouterr().out

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_clear_keyring_error_surfaces(self, capsys) -> None:
        store = _StubStore(raise_on="delete")
        args = _parse_passphrase_args(["passphrase", "clear", _FP])
        rc = _dispatch_passphrase(args, Config(), store_factory=lambda: store)
        assert rc == 5
        assert "keyring error" in capsys.readouterr().err


class TestPassphraseList:
    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_list_prints_fingerprints_only(self, capsys) -> None:
        store = _StubStore()
        store.set(_FP, "secret-value-must-not-leak")
        args = _parse_passphrase_args(["passphrase", "list"])

        rc = _dispatch_passphrase(args, Config(), store_factory=lambda: store)

        captured = capsys.readouterr()
        assert rc == 0
        assert _FP in captured.out
        assert "secret-value-must-not-leak" not in captured.out
        assert "secret-value-must-not-leak" not in captured.err

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_list_empty_message(self, capsys) -> None:
        store = _StubStore()
        args = _parse_passphrase_args(["passphrase", "list"])
        rc = _dispatch_passphrase(args, Config(), store_factory=lambda: store)
        assert rc == 0
        assert "No passphrases stored" in capsys.readouterr().out

    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_list_keyring_error_surfaces(self, capsys) -> None:
        store = _StubStore(raise_on="list")
        args = _parse_passphrase_args(["passphrase", "list"])
        rc = _dispatch_passphrase(args, Config(), store_factory=lambda: store)
        assert rc == 5
        assert "keyring error" in capsys.readouterr().err


class TestPassphraseUsage:
    @pytest.mark.covers_function("Persist Signing Passphrase")
    def test_passphrase_without_subcommand_returns_usage(self, capsys) -> None:
        # Construct a Namespace as if the user invoked
        # ``gpg-bridge passphrase`` with no further argument.
        args = argparse.Namespace(command="passphrase", passphrase_command=None)
        rc = _dispatch_passphrase(args, Config(), store_factory=lambda: _StubStore())
        assert rc == 1
        assert "missing subcommand" in capsys.readouterr().err
