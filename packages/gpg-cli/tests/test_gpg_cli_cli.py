# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the gpg-cli argv parser (git's gpg surface)."""

from __future__ import annotations

import pytest

from gpg_cli.cli import UsageError, _parse_argv  # pyright: ignore[reportPrivateUsage]


class TestVersion:
    @pytest.mark.covers_function("Parse Git GPG Argv")
    def test_version_flag(self) -> None:
        parsed = _parse_argv(["--version"])
        assert parsed.action == "version"


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
