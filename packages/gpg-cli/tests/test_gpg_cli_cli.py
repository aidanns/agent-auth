# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""Unit tests for the gpg-cli argv parser (git's gpg surface)."""

from __future__ import annotations

import io
import re
from importlib.metadata import version as _dist_version
from io import StringIO

import pytest

from gpg_cli.cli import (
    EXIT_OK,
    EXIT_UNAVAILABLE,
    UsageError,
    _handle_gpg_cli_version,  # pyright: ignore[reportPrivateUsage]
    _handle_version,  # pyright: ignore[reportPrivateUsage]
    _parse_argv,  # pyright: ignore[reportPrivateUsage]
    main,
)
from gpg_cli.errors import (
    BridgeSigningBackendUnavailableError,
    BridgeUnavailableError,
)
from gpg_models.models import SignRequest, SignResult

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


def _make_config(config_path: str) -> object:
    """Build a fully-validated ``GpgCliConfig`` for the unit tests.

    Materialises the credentials shape introduced in PR #335 so the
    test exercises the same loading codepath the production CLI does.
    """
    from gpg_cli.config import Credentials, GpgCliConfig

    return GpgCliConfig(
        bridge_url="http://test",
        credentials=Credentials(
            access_token="access",
            refresh_token="refresh",
            auth_url="http://auth",
            family_id="family-id",
        ),
        config_path=config_path,
    )


class TestSigningBackendUnavailableSurface:
    @pytest.mark.covers_function("Send Bridge Sign Request")
    def test_main_prints_directed_message_and_exits_unavailable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path,
    ) -> None:
        """End-to-end ``main`` exits with the directed remediation, not "bridge unreachable"."""
        from gpg_cli import cli as cli_module

        config = _make_config(str(tmp_path / "config.yaml"))
        monkeypatch.setattr(cli_module, "load_config", lambda: config)

        directed_detail = (
            "host gpg-agent likely needs allow-loopback-pinentry "
            "and a primed passphrase cache; see "
            "docs/operations/gpg-bridge-host-setup.md"
        )

        def _fake_client(*_args: object, **_kwargs: object) -> _StubBridgeClient:
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
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path,
    ) -> None:
        """Regression guard: the generic 5xx path still says ``bridge unavailable``.

        Avoids accidentally folding the wedge-specific path into the
        generic one and re-introducing the misdirection from #331.
        """
        from gpg_cli import cli as cli_module

        config = _make_config(str(tmp_path / "config.yaml"))
        monkeypatch.setattr(cli_module, "load_config", lambda: config)

        def _fake_client(*_args: object, **_kwargs: object) -> _StubBridgeClient:
            return _StubBridgeClient(error=BridgeUnavailableError("connection refused"))

        monkeypatch.setattr(cli_module, "BridgeClient", _fake_client)
        monkeypatch.setattr("sys.stdin", _BytesStdinStub(b"payload"))

        rc = main(["--detach-sign", "--sign", "--armor", "--local-user", "0xABCD1234"])
        captured = capsys.readouterr()

        assert rc == EXIT_UNAVAILABLE
        assert "bridge unavailable" in captured.err
        assert "signing backend unavailable" not in captured.err
