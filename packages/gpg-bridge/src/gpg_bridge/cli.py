# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI entrypoint for gpg-bridge.

Carries two surfaces today: ``serve`` (the long-running HTTP
server, the project's primary deployment shape) and the
``passphrase set / clear / list`` subcommand group introduced by
ADR 0042 for one-shot lifecycle management of stored signing-key
passphrases.
"""

from __future__ import annotations

import argparse
import getpass
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Protocol

from cli_meta import add_version_flag
from gpg_bridge.authz import AgentAuthClient
from gpg_bridge.config import Config, load_config
from gpg_bridge.errors import PassphraseStoreError
from gpg_bridge.gpg_client import GpgSubprocessClient
from gpg_bridge.passphrase_store import KeyringPassphraseStore
from gpg_bridge.server import run_server


class _PassphraseStore(Protocol):
    """Structural type for the keyring-backed passphrase store.

    Lets unit tests substitute an in-memory stand-in (see
    ``tests/test_gpg_bridge_cli.py::_StubStore``) without inheriting
    from :class:`KeyringPassphraseStore`. The production
    ``serve``-time wiring still constructs the concrete class.
    """

    def set(self, fingerprint: str, passphrase: str) -> None: ...

    def delete(self, fingerprint: str) -> None: ...

    def list_fingerprints(self) -> list[str]: ...


# Exit codes for the ``passphrase`` subcommand group. Picked
# deliberately to be distinct from gpg's own (``2`` for generic
# operation failure) so an operator running ``echo $?`` after
# ``gpg-bridge passphrase set`` can tell allowlist rejection
# apart from a genuine keyring-backend failure.
_EXIT_OK = 0
_EXIT_USAGE = 1
_EXIT_KEY_NOT_ALLOWED = 3
_EXIT_KEY_NOT_RESOLVED = 4
_EXIT_BACKEND_ERROR = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpg-bridge",
        description=(
            "HTTP bridge from agent-auth-protected clients to the host gpg binary. "
            "Each request shells out to the configured ``gpg_command`` "
            "(default ``gpg``) per ADR 0033."
        ),
    )
    add_version_flag(parser, "gpg-bridge")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("serve", help="Start the HTTP bridge server")

    passphrase_parser = subparsers.add_parser(
        "passphrase",
        help="Manage signing-key passphrases stored in the system keyring (ADR 0042)",
        description=(
            "Manage the per-fingerprint signing-key passphrases the bridge feeds to "
            "host gpg via --passphrase-fd. Passphrases live in the system keyring "
            "(macOS Keychain / libsecret) under service 'gpg-bridge'. See ADR 0042."
        ),
    )
    passphrase_subparsers = passphrase_parser.add_subparsers(dest="passphrase_command")

    set_parser = passphrase_subparsers.add_parser(
        "set",
        help="Prompt (no-echo) for a passphrase and persist it for the given fingerprint",
    )
    set_parser.add_argument("fingerprint", help="Signing-key fingerprint")

    clear_parser = passphrase_subparsers.add_parser(
        "clear", help="Remove the stored passphrase for the given fingerprint (idempotent)"
    )
    clear_parser.add_argument("fingerprint", help="Signing-key fingerprint")

    passphrase_subparsers.add_parser(
        "list", help="List the fingerprints currently holding a stored passphrase"
    )

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    config = load_config()
    if args.command == "serve":
        passphrase_store: KeyringPassphraseStore | None = (
            KeyringPassphraseStore() if config.passphrase_store_enabled else None
        )
        gpg = GpgSubprocessClient(
            command=config.gpg_command,
            timeout_seconds=config.request_timeout_seconds,
            passphrase_store=passphrase_store,
        )
        authz = AgentAuthClient(
            config.auth_url,
            timeout_seconds=config.request_timeout_seconds,
            ca_cert_path=config.auth_ca_cert_path,
        )
        run_server(config, gpg, authz)
        return

    if args.command == "passphrase":
        sys.exit(_dispatch_passphrase(args, config))

    parser.print_help()
    sys.exit(1)


# ---------------------------------------------------------------------------
# ``passphrase`` subcommand handlers
# ---------------------------------------------------------------------------


def _dispatch_passphrase(
    args: argparse.Namespace,
    config: Config,
    *,
    store_factory: Callable[[], _PassphraseStore] = KeyringPassphraseStore,
    prompt_passphrase: Callable[[str], str] = lambda prompt: getpass.getpass(prompt),
    resolve_key: Callable[[Config, str], bool] | None = None,
) -> int:
    """Dispatch the ``passphrase`` subcommand group.

    ``store_factory``, ``prompt_passphrase``, and ``resolve_key`` are
    test seams so unit tests can substitute the keyring backend, the
    no-echo prompt, and the host-gpg ``--list-secret-keys`` probe
    respectively without touching the real keyring or spawning gpg.
    """
    sub = getattr(args, "passphrase_command", None)
    if sub is None:
        sys.stderr.write("gpg-bridge passphrase: missing subcommand (set / clear / list)\n")
        return _EXIT_USAGE
    store = store_factory()
    resolver = resolve_key if resolve_key is not None else _default_resolve_key
    if sub == "set":
        return _handle_passphrase_set(args.fingerprint, config, store, prompt_passphrase, resolver)
    if sub == "clear":
        return _handle_passphrase_clear(args.fingerprint, store)
    if sub == "list":
        return _handle_passphrase_list(store)
    sys.stderr.write(f"gpg-bridge passphrase: unknown subcommand {sub!r}\n")
    return _EXIT_USAGE


def _handle_passphrase_set(
    fingerprint: str,
    config: Config,
    store: _PassphraseStore,
    prompt_passphrase: Callable[[str], str],
    resolve_key: Callable[[Config, str], bool],
) -> int:
    if not config.key_allowed(fingerprint):
        sys.stderr.write(
            f"gpg-bridge passphrase: fingerprint {fingerprint!r} is not in "
            "allowed_signing_keys; add it to the bridge config first.\n"
        )
        return _EXIT_KEY_NOT_ALLOWED
    if not resolve_key(config, fingerprint):
        sys.stderr.write(
            f"gpg-bridge passphrase: host gpg cannot resolve fingerprint "
            f"{fingerprint!r}; import the secret key into the host's keyring "
            "before storing a passphrase for it.\n"
        )
        return _EXIT_KEY_NOT_RESOLVED
    passphrase = prompt_passphrase(f"Passphrase for {fingerprint}: ")
    if not passphrase:
        sys.stderr.write(
            "gpg-bridge passphrase: empty passphrase rejected; use 'clear' to delete an entry.\n"
        )
        return _EXIT_USAGE
    try:
        store.set(fingerprint, passphrase)
    except PassphraseStoreError as exc:
        sys.stderr.write(f"gpg-bridge passphrase: keyring error: {exc}\n")
        return _EXIT_BACKEND_ERROR
    print(f"Stored passphrase for {fingerprint}.")
    return _EXIT_OK


def _handle_passphrase_clear(fingerprint: str, store: _PassphraseStore) -> int:
    try:
        store.delete(fingerprint)
    except PassphraseStoreError as exc:
        sys.stderr.write(f"gpg-bridge passphrase: keyring error: {exc}\n")
        return _EXIT_BACKEND_ERROR
    print(f"Cleared passphrase for {fingerprint}.")
    return _EXIT_OK


def _handle_passphrase_list(store: _PassphraseStore) -> int:
    try:
        fingerprints = store.list_fingerprints()
    except PassphraseStoreError as exc:
        sys.stderr.write(f"gpg-bridge passphrase: keyring error: {exc}\n")
        return _EXIT_BACKEND_ERROR
    if not fingerprints:
        print("No passphrases stored.")
        return _EXIT_OK
    for fp in fingerprints:
        # Print fingerprints only — never the passphrases themselves
        # (per ADR 0042's never-emit guarantee).
        print(fp)
    return _EXIT_OK


def _default_resolve_key(config: Config, fingerprint: str) -> bool:
    """Run ``gpg --list-secret-keys <FP>`` to confirm the host can find the key.

    Uses the configured ``gpg_command`` so test substitutions of the
    gpg binary (the ``gpg_backend_fake`` fixture) carry through here
    as well. Any non-zero exit, missing binary, or timeout is treated
    as "host can't resolve".
    """
    argv = [*config.gpg_command, "--batch", "--list-secret-keys", fingerprint]
    try:
        result = subprocess.run(argv, capture_output=True, timeout=10.0, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


if __name__ == "__main__":
    main()
