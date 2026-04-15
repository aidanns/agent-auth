"""Integration tests for the agent-auth CLI."""

import json
import os
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from agent_auth.cli import main
from agent_auth.store import TokenStore


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
    with patch.object(sys, "argv", argv), \
         patch.object(sys, "stdout", stdout), \
         patch.object(sys, "stderr", stderr):
        try:
            main()
        except SystemExit:
            pass
    return stdout.getvalue(), stderr.getvalue()


def _open_store(config_dir):
    """Open the on-disk TokenStore with the same encryption key the CLI used."""
    from agent_auth.keys import KeyManager
    encryption_key = KeyManager().get_or_create_encryption_key()
    return TokenStore(os.path.join(config_dir, "tokens.db"), encryption_key)


@pytest.mark.covers_function("Handle Token Create Command", "Create Token Pair")
def test_token_create(cli_env):
    out, _ = _run_cli("token", "create", "--scope", "things:read=allow", config_dir=cli_env)
    assert "Token family created" in out
    assert "aa_" in out
    assert "rt_" in out

    # The CLI must actually persist the family to the DB — not just print.
    store = _open_store(cli_env)
    families = store.list_families()
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

    store = _open_store(cli_env)
    stored = store.get_family(data["family_id"])
    assert stored is not None
    assert stored["scopes"] == {"things:read": "allow"}
    tokens = store.get_tokens_by_family(data["family_id"])
    types = sorted(t["type"] for t in tokens)
    assert types == ["access", "refresh"]


@pytest.mark.covers_function("Handle Token List Command")
def test_token_list_empty(cli_env):
    out, _ = _run_cli("token", "list", config_dir=cli_env)
    assert "No token families found" in out


@pytest.mark.covers_function("Handle Token List Command")
def test_token_list_after_create(cli_env):
    out1, _ = _run_cli("--json", "token", "create", "--scope", "a:read", config_dir=cli_env)
    data = json.loads(out1)
    family_id = data["family_id"]

    # JSON-mode list returns structured data we can verify without parsing tables.
    out2, _ = _run_cli("--json", "token", "list", config_dir=cli_env)
    families = json.loads(out2)
    assert [f["id"] for f in families] == [family_id]
    assert families[0]["revoked"] is False


@pytest.mark.covers_function("Handle Token Revoke Command", "Revoke Token Family")
def test_token_revoke(cli_env):
    out1, _ = _run_cli("--json", "token", "create", "--scope", "a:read", config_dir=cli_env)
    family_id = json.loads(out1)["family_id"]

    _run_cli("token", "revoke", family_id, config_dir=cli_env)

    store = _open_store(cli_env)
    assert store.get_family(family_id)["revoked"] is True


@pytest.mark.covers_function("Handle Token Rotate Command", "Rotate Token Family")
def test_token_rotate(cli_env):
    out1, _ = _run_cli("--json", "token", "create", "--scope", "a:read=allow", config_dir=cli_env)
    old_family_id = json.loads(out1)["family_id"]

    out2, _ = _run_cli("--json", "token", "rotate", old_family_id, config_dir=cli_env)
    data = json.loads(out2)
    assert data["old_family_id"] == old_family_id
    assert data["new_family_id"] != old_family_id
    assert data["access_token"].startswith("aa_")

    # The old family should be revoked and the new family should carry the same scopes.
    store = _open_store(cli_env)
    assert store.get_family(old_family_id)["revoked"] is True
    new_family = store.get_family(data["new_family_id"])
    assert new_family is not None
    assert new_family["revoked"] is False
    assert new_family["scopes"] == {"a:read": "allow"}


@pytest.mark.covers_function("Handle Token Modify Command", "Modify Token Family Scopes")
def test_token_modify(cli_env):
    out1, _ = _run_cli("--json", "token", "create", "--scope", "a:read=allow", config_dir=cli_env)
    family_id = json.loads(out1)["family_id"]

    _run_cli(
        "--json", "token", "modify", family_id,
        "--add-scope", "b:write=prompt",
        config_dir=cli_env,
    )

    store = _open_store(cli_env)
    assert store.get_family(family_id)["scopes"] == {
        "a:read": "allow",
        "b:write": "prompt",
    }
