# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the gpg-cli argv parser (git's gpg surface)."""

from __future__ import annotations

import re
from importlib.metadata import version as _dist_version
from io import StringIO

import pytest

from gpg_cli.cli import (
    EXIT_OK,
    UsageError,
    _handle_gpg_cli_version,  # pyright: ignore[reportPrivateUsage]
    _handle_version,  # pyright: ignore[reportPrivateUsage]
    _parse_argv,  # pyright: ignore[reportPrivateUsage]
    main,
)

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")


class TestVersion:
    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_version_flag(self) -> None:
        parsed = _parse_argv(["--version"])
        assert parsed.action == "version"

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_version_flag_emits_gpg_shaped_banner(self) -> None:
        """``gpg-cli --version`` keeps the GnuPG-shaped banner.

        Regression guard: git probes ``gpg --version`` to identify the
        binary, so the leading ``gpg (GnuPG) ...`` line and the
        algorithm-table format are part of the contract with git. The
        package-version flag is exposed under ``--gpg-cli-version`` to
        avoid clobbering this output (see ADR 0030 and issue #318).
        """
        stdout = StringIO()
        rc = _handle_version(stdout=stdout)
        assert rc == EXIT_OK
        body = stdout.getvalue()
        assert body.startswith("gpg (GnuPG) "), f"unexpected banner: {body!r}"
        assert "Pubkey:" in body
        assert "Cipher:" in body
        # Sanity: the gpg-shaped banner must NOT look like the
        # ``--gpg-cli-version`` output (``gpg-cli <semver>``).
        assert "\ngpg-cli " not in body
        assert not body.startswith("gpg-cli ")

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_gpg_cli_version_flag_parsed(self) -> None:
        parsed = _parse_argv(["--gpg-cli-version"])
        assert parsed.action == "gpg_cli_version"
        assert parsed.gpg_cli_version is True

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_gpg_cli_version_takes_precedence_over_version(self) -> None:
        """If both flags are passed, the package-version intent wins.

        ``--gpg-cli-version`` is the more specific flag; this avoids a
        case where someone scripts ``gpg-cli --version --gpg-cli-version``
        expecting the package version and instead gets the gpg banner.
        """
        parsed = _parse_argv(["--version", "--gpg-cli-version"])
        assert parsed.action == "gpg_cli_version"

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_gpg_cli_version_emits_package_version(self) -> None:
        """``_handle_gpg_cli_version`` writes ``gpg-cli <version>\\n``."""
        stdout = StringIO()
        rc = _handle_gpg_cli_version(stdout=stdout)
        assert rc == EXIT_OK
        line = stdout.getvalue().rstrip("\n")
        assert line.startswith("gpg-cli "), f"unexpected prefix: {line!r}"
        payload = line[len("gpg-cli ") :].strip()
        assert _SEMVER_RE.match(payload), f"unexpected version payload: {payload!r}"
        assert payload == _dist_version("gpg-cli"), (
            f"emitted {payload!r} but importlib.metadata reports " f"{_dist_version('gpg-cli')!r}"
        )

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_main_dispatches_gpg_cli_version(self, capsys) -> None:
        """``main(['--gpg-cli-version'])`` exits 0 with the package banner.

        End-to-end through ``main`` (rather than ``_handle_*`` directly)
        to lock in the dispatch wiring — this is what
        ``gpg-cli --gpg-cli-version`` actually executes from the shell.
        """
        rc = main(["--gpg-cli-version"])
        assert rc == EXIT_OK
        captured = capsys.readouterr()
        line = captured.out.rstrip("\n")
        assert line.startswith("gpg-cli "), f"unexpected output: {line!r}"
        assert _SEMVER_RE.match(line[len("gpg-cli ") :].strip())


class TestShortClusterSign:
    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_bsau_cluster(self) -> None:
        parsed = _parse_argv(["--status-fd", "2", "--keyid-format", "long", "-bsau", "0xABCD1234"])
        assert parsed.action == "sign"
        assert parsed.status_fd == 2
        assert parsed.keyid_format == "long"
        assert parsed.local_user == "0xABCD1234"
        assert parsed.armor
        assert parsed.detach_sign
        assert parsed.sign

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_status_fd_equal_form(self) -> None:
        parsed = _parse_argv(["--status-fd=3", "-bsau", "K"])
        assert parsed.status_fd == 3

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_long_form_matches_short(self) -> None:
        parsed = _parse_argv(
            [
                "--status-fd",
                "2",
                "--detach-sign",
                "--sign",
                "--armor",
                "--local-user",
                "K",
            ]
        )
        assert parsed.action == "sign"
        assert parsed.local_user == "K"


class TestVerify:
    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_verify_with_detached_sig_and_stdin(self) -> None:
        parsed = _parse_argv(["--verify", "sig.asc", "-"])
        assert parsed.action == "verify"
        assert parsed.positional == ["sig.asc", "-"]

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_verify_with_two_files(self) -> None:
        parsed = _parse_argv(["--verify", "sig.asc", "data.txt"])
        assert parsed.action == "verify"
        assert parsed.positional == ["sig.asc", "data.txt"]

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_verify_with_keyid_format(self) -> None:
        parsed = _parse_argv(
            ["--status-fd=2", "--keyid-format", "0xlong", "--verify", "sig.asc", "-"]
        )
        assert parsed.keyid_format == "0xlong"


class TestRejectedArgvShapes:
    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_unknown_long_option_raises(self) -> None:
        with pytest.raises(UsageError, match="unsupported long option"):
            _parse_argv(["--encrypt"])

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_unknown_short_option_raises(self) -> None:
        with pytest.raises(UsageError, match="unsupported short option"):
            _parse_argv(["-X"])

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_empty_argv_raises(self) -> None:
        with pytest.raises(UsageError):
            _parse_argv([])

    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_status_fd_non_integer(self) -> None:
        with pytest.raises(UsageError, match="integer"):
            _parse_argv(["--status-fd", "abc", "-bsau", "k"])
