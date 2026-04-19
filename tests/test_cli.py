"""Integration tests for the agent-auth CLI.

These tests exercise only the CLI's public surface — its argv inputs and its
stdout (human and ``--json``) outputs. They deliberately avoid reaching into
the on-disk token store, because the DB schema is an internal implementation
detail the CLI may change without notice. If a behaviour is not observable
through the CLI, it is not worth locking in with a test here.
"""

import contextlib
import json
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from agent_auth.cli import main


@pytest.fixture
def cli_env(tmp_dir, mock_keyring):
    """Set up a CLI environment with a temp config dir and mock keyring."""
    return tmp_dir


def _run_cli(*args, config_dir=None):
    """Run the CLI with the given arguments and capture output."""
    argv = ["agent-auth"]
    if config_dir:
        argv.extend(["--config-dir", config_dir])
    argv.extend(args)

    stdout = StringIO()
    stderr = StringIO()
    with (
        patch.object(sys, "argv", argv),
        patch.object(sys, "stdout", stdout),
        patch.object(sys, "stderr", stderr),
        contextlib.suppress(SystemExit),
    ):
        main()
    return stdout.getvalue(), stderr.getvalue()


def _list_families(config_dir):
    out, _ = _run_cli("--json", "token", "list", config_dir=config_dir)
    return json.loads(out)


@pytest.mark.covers_function("Handle Token Create Command", "Create Token Pair")
def test_token_create(cli_env):
    out, _ = _run_cli("token", "create", "--scope", "things:read=allow", config_dir=cli_env)
    assert "Token family created" in out
    assert "aa_" in out
    assert "rt_" in out

    # The family must be observable via ``token list`` — otherwise the CLI
    # printed tokens it never persisted.
    families = _list_families(cli_env)
    assert len(families) == 1
    assert families[0]["scopes"] == {"things:read": "allow"}
    assert families[0]["revoked"] is False


@pytest.mark.covers_function("Handle Token Create Command", "Create Token Pair")
def test_token_create_json(cli_env):
    out, _ = _run_cli("--json", "token", "create", "--scope", "things:read", config_dir=cli_env)
    data = json.loads(out)
    assert "family_id" in data
    assert data["access_token"].startswith("aa_")
    assert data["refresh_token"].startswith("rt_")
    assert data["scopes"] == {"things:read": "allow"}

    families = _list_families(cli_env)
    assert [f["id"] for f in families] == [data["family_id"]]
    assert families[0]["scopes"] == {"things:read": "allow"}


@pytest.mark.covers_function("Handle Token List Command")
def test_token_list_empty(cli_env):
    out, _ = _run_cli("token", "list", config_dir=cli_env)
    assert "No token families found" in out


@pytest.mark.covers_function("Handle Token List Command")
def test_token_list_after_create(cli_env):
    out1, _ = _run_cli("--json", "token", "create", "--scope", "a:read", config_dir=cli_env)
    data = json.loads(out1)
    family_id = data["family_id"]

    families = _list_families(cli_env)
    assert [f["id"] for f in families] == [family_id]
    assert families[0]["revoked"] is False


@pytest.mark.covers_function("Handle Token Revoke Command", "Revoke Token Family")
def test_token_revoke(cli_env):
    out1, _ = _run_cli("--json", "token", "create", "--scope", "a:read", config_dir=cli_env)
    family_id = json.loads(out1)["family_id"]

    _run_cli("token", "revoke", family_id, config_dir=cli_env)

    families = _list_families(cli_env)
    assert len(families) == 1
    assert families[0]["id"] == family_id
    assert families[0]["revoked"] is True


@pytest.mark.covers_function("Handle Token Rotate Command", "Rotate Token Family")
def test_token_rotate(cli_env):
    out1, _ = _run_cli("--json", "token", "create", "--scope", "a:read=allow", config_dir=cli_env)
    old_family_id = json.loads(out1)["family_id"]

    out2, _ = _run_cli("--json", "token", "rotate", old_family_id, config_dir=cli_env)
    data = json.loads(out2)
    assert data["old_family_id"] == old_family_id
    assert data["new_family_id"] != old_family_id
    assert data["access_token"].startswith("aa_")
    assert data["refresh_token"].startswith("rt_")

    # The old family should be revoked and the new family should be active
    # with the same scopes — all observable via ``token list``.
    families = {f["id"]: f for f in _list_families(cli_env)}
    assert families[old_family_id]["revoked"] is True
    assert families[data["new_family_id"]]["revoked"] is False
    assert families[data["new_family_id"]]["scopes"] == {"a:read": "allow"}


@pytest.mark.covers_function("Handle Token Modify Command", "Modify Token Family Scopes")
def test_token_modify(cli_env):
    out1, _ = _run_cli("--json", "token", "create", "--scope", "a:read=allow", config_dir=cli_env)
    family_id = json.loads(out1)["family_id"]

    _run_cli(
        "--json",
        "token",
        "modify",
        family_id,
        "--add-scope",
        "b:write=prompt",
        config_dir=cli_env,
    )

    families = _list_families(cli_env)
    assert families[0]["id"] == family_id
    assert families[0]["scopes"] == {
        "a:read": "allow",
        "b:write": "prompt",
    }
