"""Tests for things-cli credential storage."""

import os
import stat
from unittest.mock import patch

import pytest
import yaml

from things_cli.credentials import (
    Credentials,
    FileStore,
    KeyringStore,
    select_store,
)
from things_cli.errors import CredentialsBackendError, CredentialsNotFoundError


@pytest.fixture
def cli_mock_keyring():
    """Mock keyring for things_cli tests with an in-memory dict."""
    store: dict[tuple[str, str], str] = {}

    def get_password(service, username):
        return store.get((service, username))

    def set_password(service, username, password):
        store[(service, username)] = password

    def delete_password(service, username):
        if (service, username) in store:
            del store[(service, username)]
        else:
            from keyring.errors import PasswordDeleteError
            raise PasswordDeleteError("no such entry")

    with patch("things_cli.credentials.keyring.get_password", side_effect=get_password), \
         patch("things_cli.credentials.keyring.set_password", side_effect=set_password), \
         patch("things_cli.credentials.keyring.delete_password", side_effect=delete_password):
        yield store


def test_keyring_store_save_load_round_trip(cli_mock_keyring):
    store = KeyringStore()
    creds = Credentials(
        access_token="aa_xxx",
        refresh_token="rt_yyy",
        bridge_url="http://127.0.0.1:9200",
        auth_url="http://127.0.0.1:9100",
        family_id="fam-1",
    )
    store.save(creds)
    loaded = store.load()
    assert loaded == creds


def test_keyring_store_load_without_save_raises(cli_mock_keyring):
    store = KeyringStore()
    with pytest.raises(CredentialsNotFoundError):
        store.load()


def test_keyring_store_clear_removes_all_entries(cli_mock_keyring):
    store = KeyringStore()
    creds = Credentials(
        access_token="aa", refresh_token="rt",
        bridge_url="http://x", auth_url="http://y",
    )
    store.save(creds)
    assert store.exists()
    store.clear()
    assert not store.exists()


def test_file_store_save_uses_0600_mode(tmp_path):
    path = str(tmp_path / "creds.json")
    store = FileStore(path)
    creds = Credentials(
        access_token="aa", refresh_token="rt",
        bridge_url="http://x", auth_url="http://y", family_id="fam-1",
    )
    store.save(creds)
    assert os.path.exists(path)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600
    with open(path) as f:
        data = yaml.safe_load(f)
    assert data["access_token"] == "aa"
    assert data["family_id"] == "fam-1"


def test_file_store_load_round_trip(tmp_path):
    path = str(tmp_path / "creds.json")
    store = FileStore(path)
    creds = Credentials(
        access_token="aa", refresh_token="rt",
        bridge_url="http://x", auth_url="http://y",
    )
    store.save(creds)
    loaded = store.load()
    assert loaded == creds


def test_file_store_missing_file_raises_not_found(tmp_path):
    store = FileStore(str(tmp_path / "nope.json"))
    with pytest.raises(CredentialsNotFoundError):
        store.load()


def test_file_store_corrupt_yaml_raises_backend_error(tmp_path):
    path = tmp_path / "creds.yaml"
    path.write_text(":\n  - :\n  bad: [unterminated")
    path.chmod(0o600)
    store = FileStore(str(path))
    with pytest.raises(CredentialsBackendError):
        store.load()


def test_file_store_missing_required_field_raises_not_found(tmp_path):
    path = tmp_path / "creds.yaml"
    path.write_text(yaml.safe_dump({"access_token": "aa"}))
    path.chmod(0o600)
    store = FileStore(str(path))
    with pytest.raises(CredentialsNotFoundError):
        store.load()


def test_file_store_load_rejects_world_readable_file(tmp_path):
    # Credentials files with permissions looser than 0600 must be rejected
    # before reading, similar to how SSH refuses overly-permissive key files.
    path = tmp_path / "creds.yaml"
    path.write_text(yaml.safe_dump({
        "access_token": "aa", "refresh_token": "rt",
        "bridge_url": "http://x", "auth_url": "http://y",
    }))
    path.chmod(0o644)
    store = FileStore(str(path))
    with pytest.raises(CredentialsBackendError, match="too open"):
        store.load()


def test_file_store_clear_is_idempotent(tmp_path):
    path = str(tmp_path / "nope.json")
    store = FileStore(path)
    store.clear()  # no exception when file doesn't exist


def test_select_store_file_requires_path():
    with pytest.raises(ValueError):
        select_store("file")


def test_select_store_file_backend(tmp_path):
    store = select_store("file", file_path=str(tmp_path / "c.json"))
    assert isinstance(store, FileStore)


def test_select_store_keyring_backend(cli_mock_keyring):
    store = select_store("keyring")
    assert isinstance(store, KeyringStore)


def test_select_store_unknown_backend():
    with pytest.raises(ValueError):
        select_store("weird")
