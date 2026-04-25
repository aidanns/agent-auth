# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the gpg-cli argv parser (git's gpg surface)."""

from __future__ import annotations

import io

import pytest

from gpg_cli.cli import (
    EXIT_UNAVAILABLE,
    UsageError,
    _parse_argv,  # pyright: ignore[reportPrivateUsage]
    main,
)
from gpg_cli.errors import (
    BridgeSigningBackendUnavailableError,
    BridgeUnavailableError,
)
from gpg_models.models import SignRequest, SignResult


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


class _BytesStdinStub:
    """Mimics ``sys.stdin``: text-stream-shaped object exposing a binary ``.buffer``."""

    def __init__(self, payload: bytes) -> None:
        self.buffer = io.BytesIO(payload)


class _StubBridgeClient:
    """Minimal ``BridgeClient`` stand-in for unit-testing the main loop.

    Keeps the test independent of the HTTP layer; the wire mapping
    from a 503 response to ``BridgeSigningBackendUnavailableError`` is
    covered in
    ``packages/gpg-bridge/tests/fault/test_backend_subprocess_hang.py``.
    """

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def sign(self, request: SignRequest) -> SignResult:
        if self._error is not None:
            raise self._error
        raise AssertionError("test did not configure a sign error")

    def verify(self, request: object) -> object:  # pragma: no cover - not exercised
        raise AssertionError("verify path not exercised by these tests")


class TestSigningBackendUnavailableSurface:
    @pytest.mark.covers_function("Send Bridge Sign Request")
    def test_main_prints_directed_message_and_exits_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """End-to-end ``main`` exits with the directed remediation, not "bridge unreachable"."""
        from gpg_cli import cli as cli_module
        from gpg_cli.config import GpgCliConfig

        monkeypatch.setattr(
            cli_module,
            "load_config",
            lambda: GpgCliConfig(bridge_url="http://test", token="t"),
        )

        directed_detail = (
            "host gpg-agent likely needs allow-loopback-pinentry "
            "and a primed passphrase cache; see "
            "docs/operations/gpg-bridge-host-setup.md"
        )

        def _fake_client(**_kwargs: object) -> _StubBridgeClient:
            return _StubBridgeClient(error=BridgeSigningBackendUnavailableError(directed_detail))

        monkeypatch.setattr(cli_module, "BridgeClient", _fake_client)
        monkeypatch.setattr("sys.stdin", _BytesStdinStub(b"payload"))

        rc = main(["--detach-sign", "--sign", "--armor", "--local-user", "0xABCD1234"])
        captured = capsys.readouterr()

        assert rc == EXIT_UNAVAILABLE
        assert "signing backend unavailable" in captured.err
        assert "allow-loopback-pinentry" in captured.err
        assert "gpg-bridge-host-setup.md" in captured.err
        assert "bridge unreachable" not in captured.err

    @pytest.mark.covers_function("Send Bridge Sign Request")
    def test_main_still_uses_bridge_unreachable_for_plain_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Regression guard: the generic 5xx path still says ``bridge unavailable``.

        Avoids accidentally folding the wedge-specific path into the
        generic one and re-introducing the misdirection from #331.
        """
        from gpg_cli import cli as cli_module
        from gpg_cli.config import GpgCliConfig

        monkeypatch.setattr(
            cli_module,
            "load_config",
            lambda: GpgCliConfig(bridge_url="http://test", token="t"),
        )

        def _fake_client(**_kwargs: object) -> _StubBridgeClient:
            return _StubBridgeClient(error=BridgeUnavailableError("connection refused"))

        monkeypatch.setattr(cli_module, "BridgeClient", _fake_client)
        monkeypatch.setattr("sys.stdin", _BytesStdinStub(b"payload"))

        rc = main(["--detach-sign", "--sign", "--armor", "--local-user", "0xABCD1234"])
        captured = capsys.readouterr()

        assert rc == EXIT_UNAVAILABLE
        assert "bridge unavailable" in captured.err
        assert "signing backend unavailable" not in captured.err
