"""Smoke tests for the things-cli argparse entrypoint."""

import json
import os

import pytest

from things_cli.cli import main


def _args(tmp_path, *extra: str) -> list[str]:
    creds_file = str(tmp_path / "creds.json")
    return ["--credential-store", "file", "--credentials-file", creds_file, *extra]


def test_help_without_command_exits_nonzero(capsys):
    assert main([]) == 1


def test_login_saves_credentials(tmp_path, capsys):
    creds_path = str(tmp_path / "creds.json")
    rc = main([
        "--credential-store", "file", "--credentials-file", creds_path,
        "login",
        "--bridge-url", "http://127.0.0.1:9200",
        "--auth-url", "http://127.0.0.1:9100",
        "--access-token", "aa_abc",
        "--refresh-token", "rt_def",
        "--family-id", "fam-1",
    ])
    assert rc == 0
    data = json.loads(open(creds_path).read())
    assert data["access_token"] == "aa_abc"
    assert data["family_id"] == "fam-1"


def test_status_without_credentials(tmp_path):
    rc = main(_args(tmp_path, "status"))
    assert rc == 1


def test_status_prints_redacted_values(tmp_path, capsys):
    # login first
    main(_args(tmp_path,
               "login",
               "--bridge-url", "http://127.0.0.1:9200",
               "--auth-url", "http://127.0.0.1:9100",
               "--access-token", "aa_secret",
               "--refresh-token", "rt_secret"))
    capsys.readouterr()
    rc = main(_args(tmp_path, "status"))
    captured = capsys.readouterr()
    assert rc == 0
    assert "aa_secret" not in captured.out
    assert "rt_secret" not in captured.out
    assert "<set>" in captured.out


def test_logout_clears_file(tmp_path):
    creds_path = str(tmp_path / "creds.json")
    main([
        "--credential-store", "file", "--credentials-file", creds_path,
        "login",
        "--bridge-url", "http://127.0.0.1:9200",
        "--auth-url", "http://127.0.0.1:9100",
        "--access-token", "aa", "--refresh-token", "rt",
    ])
    assert os.path.exists(creds_path)
    main(_args(tmp_path, "logout"))
    assert not os.path.exists(creds_path)


def test_todos_list_without_credentials_exits_cleanly(tmp_path, capsys):
    rc = main(_args(tmp_path, "todos", "list"))
    captured = capsys.readouterr()
    assert rc == 2
    assert "credentials" in captured.err.lower()


@pytest.mark.parametrize("sub", ["todos", "projects", "areas"])
def test_bare_subcommand_prints_help(tmp_path, sub):
    # `things-cli todos` with no action falls through to help — exit 1.
    rc = main(_args(tmp_path, sub))
    assert rc == 1


@pytest.mark.parametrize("command,expected_path", [
    (["todos", "show", "id with spaces"], "/things-bridge/todos/id%20with%20spaces"),
    (["projects", "show", "p/slash"], "/things-bridge/projects/p%2Fslash"),
    (["areas", "show", "a#frag"], "/things-bridge/areas/a%23frag"),
])
def test_show_commands_url_encode_id(tmp_path, command, expected_path, monkeypatch):
    # Ids supplied on the command line must reach the bridge URL-encoded, so
    # that spaces, slashes, and fragment markers survive the request line.
    # Previously the id was interpolated raw and a space would produce a
    # malformed HTTP request.
    main(_args(tmp_path,
               "login",
               "--bridge-url", "http://127.0.0.1:9200",
               "--auth-url", "http://127.0.0.1:9100",
               "--access-token", "aa", "--refresh-token", "rt"))

    captured_paths: list[str] = []

    class _StubClient:
        def __init__(self, *a, **k):
            pass

        def get(self, path, params=None):
            captured_paths.append(path)
            # Return whatever shape the caller expects — keyed by endpoint.
            if "/todos/" in path:
                return {"todo": {"id": "x", "name": "n", "status": "open"}}
            if "/projects/" in path:
                return {"project": {"id": "x", "name": "n", "status": "open"}}
            return {"area": {"id": "x", "name": "n"}}

    monkeypatch.setattr("things_cli.cli.BridgeClient", _StubClient)
    rc = main(_args(tmp_path, *command))
    assert rc == 0
    assert captured_paths == [expected_path]
