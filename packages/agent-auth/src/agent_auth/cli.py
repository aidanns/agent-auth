# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI entrypoint for agent-auth token management and server."""

import argparse
import json
import sys

from agent_auth.audit import AuditLogger, ChainVerificationFailure, verify_audit_chain
from agent_auth.config import Config, load_config
from agent_auth.errors import KeyLossError, KeyringError
from agent_auth.keys import KeyManager, SigningKey, check_key_integrity
from agent_auth.scopes import parse_scope_arg
from agent_auth.store import TokenStore
from agent_auth.tokens import create_token_pair, generate_token_id


def _init_services(
    config_dir: str | None = None,
) -> tuple[Config, SigningKey, TokenStore, AuditLogger, KeyManager]:
    config = load_config(config_dir)
    key_manager = KeyManager()
    # Refuse to regenerate keys when an existing DB would be orphaned
    # by a fresh key pair (see design/DESIGN.md "Key loss and recovery").
    # The check runs before ``get_or_create_*`` so that first-time
    # installs — DB absent, keyring absent — proceed normally.
    check_key_integrity(config.db_path, key_manager)
    signing_key = key_manager.get_or_create_signing_key()
    encryption_key = key_manager.get_or_create_encryption_key()
    audit_chain_key = key_manager.get_or_create_audit_chain_key()
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path, audit_chain_key=audit_chain_key)
    return config, signing_key, store, audit, key_manager


def handle_token_create(
    args: argparse.Namespace,
    config: Config,
    signing_key: SigningKey,
    store: TokenStore,
    audit: AuditLogger,
) -> None:
    """Create a new token family with a token pair."""
    scope_args: list[str] = list(args.scope)
    scopes: dict[str, str] = {}
    for scope_arg in scope_args:
        name, tier = parse_scope_arg(scope_arg)
        scopes[name] = tier

    if not scopes:
        print("Error: at least one --scope is required", file=sys.stderr)
        sys.exit(1)

    family_id = generate_token_id()
    store.create_family(family_id, scopes)

    access_token, refresh_token = create_token_pair(signing_key, store, family_id, config)

    audit.log_token_operation("token_created", family_id=family_id, scopes=scopes)

    result = {
        "family_id": family_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "scopes": scopes,
        "expires_in": config.access_token_ttl_seconds,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Token family created: {family_id}")
        print(f"  Access token:  {access_token}")
        print(f"  Refresh token: {refresh_token}")
        print(f"  Scopes:        {scopes}")
        print(f"  Expires in:    {config.access_token_ttl_seconds}s")
        print()
        print("WARNING: Tokens are displayed only once. Store them securely.")


def handle_token_list(
    args: argparse.Namespace,
    config: Config,
    signing_key: SigningKey,
    store: TokenStore,
    audit: AuditLogger,
) -> None:
    """List all token families."""
    families = store.list_families()

    if args.json:
        print(json.dumps(families, indent=2))
        return

    if not families:
        print("No token families found.")
        return

    for family in families:
        status = "REVOKED" if family["revoked"] else "active"
        scopes_str = ", ".join(f"{name}={tier}" for name, tier in family["scopes"].items())
        print(
            f"  {family['id']}  [{status}]  scopes: {scopes_str}  created: {family['created_at']}"
        )


def handle_token_modify(
    args: argparse.Namespace,
    config: Config,
    signing_key: SigningKey,
    store: TokenStore,
    audit: AuditLogger,
) -> None:
    """Modify scopes on an existing token family."""
    family = store.get_family(args.family_id)
    if family is None:
        print(f"Error: family '{args.family_id}' not found", file=sys.stderr)
        sys.exit(1)
    if family["revoked"]:
        print(f"Error: family '{args.family_id}' is revoked", file=sys.stderr)
        sys.exit(1)

    scopes: dict[str, str] = dict(family["scopes"])
    add_scope_args: list[str] = list(args.add_scope or [])
    remove_scope_args: list[str] = list(args.remove_scope or [])
    set_tier_args: list[str] = list(args.set_tier or [])

    for scope_arg in add_scope_args:
        name, tier = parse_scope_arg(scope_arg)
        scopes[name] = tier

    for remove_name in remove_scope_args:
        scopes.pop(remove_name, None)

    for tier_arg in set_tier_args:
        name, tier = parse_scope_arg(tier_arg)
        if name in scopes:
            scopes[name] = tier
        else:
            print(
                f"Warning: scope '{name}' not found on family, skipping --set-tier",
                file=sys.stderr,
            )

    store.update_family_scopes(args.family_id, scopes)
    audit.log_token_operation("scopes_modified", family_id=args.family_id, scopes=scopes)

    if args.json:
        print(json.dumps({"family_id": args.family_id, "scopes": scopes}, indent=2))
    else:
        print(f"Family {args.family_id} scopes updated:")
        for name, tier in scopes.items():
            print(f"  {name}={tier}")


def handle_token_revoke(
    args: argparse.Namespace,
    config: Config,
    signing_key: SigningKey,
    store: TokenStore,
    audit: AuditLogger,
) -> None:
    """Revoke a token family."""
    family = store.get_family(args.family_id)
    if family is None:
        print(f"Error: family '{args.family_id}' not found", file=sys.stderr)
        sys.exit(1)

    store.mark_family_revoked(args.family_id)
    audit.log_token_operation("token_revoked", family_id=args.family_id)

    if args.json:
        print(json.dumps({"family_id": args.family_id, "revoked": True}))
    else:
        print(f"Family {args.family_id} revoked.")


def handle_token_rotate(
    args: argparse.Namespace,
    config: Config,
    signing_key: SigningKey,
    store: TokenStore,
    audit: AuditLogger,
) -> None:
    """Rotate a token family: revoke old, create new with same scopes."""
    old_family = store.get_family(args.family_id)
    if old_family is None:
        print(f"Error: family '{args.family_id}' not found", file=sys.stderr)
        sys.exit(1)

    store.mark_family_revoked(args.family_id)

    new_family_id = generate_token_id()
    scopes = old_family["scopes"]
    store.create_family(new_family_id, scopes)

    access_token, refresh_token = create_token_pair(signing_key, store, new_family_id, config)

    audit.log_token_operation(
        "token_rotated",
        old_family_id=args.family_id,
        new_family_id=new_family_id,
        scopes=scopes,
    )

    result = {
        "old_family_id": args.family_id,
        "new_family_id": new_family_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "scopes": scopes,
        "expires_in": config.access_token_ttl_seconds,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Family {args.family_id} revoked.")
        print(f"New family created: {new_family_id}")
        print(f"  Access token:  {access_token}")
        print(f"  Refresh token: {refresh_token}")
        print(f"  Scopes:        {scopes}")
        print(f"  Expires in:    {config.access_token_ttl_seconds}s")
        print()
        print("WARNING: Tokens are displayed only once. Store them securely.")


def handle_serve(
    args: argparse.Namespace,
    config: Config,
    signing_key: SigningKey,
    store: TokenStore,
    audit: AuditLogger,
    key_manager: KeyManager,
) -> None:
    """Start the agent-auth HTTP server."""
    from agent_auth.server import run_server

    run_server(config, signing_key, store, audit, key_manager)


def handle_verify_audit(
    args: argparse.Namespace,
    config: Config,
    signing_key: SigningKey,
    store: TokenStore,
    audit: AuditLogger,
    key_manager: KeyManager,
) -> None:
    """Replay the HMAC chain of the audit log against the stored key.

    Exit codes:
      0 — chain verified (every v2 entry matches; legacy v1 entries
          counted separately and not verifiable).
      1 — chain mismatch or malformed entry detected; the line number
          of the failure is written to stderr.
      2 — audit-chain key is missing from the keyring or the log file
          cannot be read.
    """
    try:
        chain_key = key_manager.get_audit_chain_key()
    except KeyringError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    if chain_key is None:
        print(
            "Error: audit-chain key not provisioned. "
            "Start the server at least once so it is created in the keyring.",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        counts = verify_audit_chain(config.log_path, chain_key)
    except ChainVerificationFailure as exc:
        print(f"Audit chain verification FAILED at {exc}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        print(json.dumps({"status": "ok", **counts}))
    else:
        print(
            f"Audit chain verified: {counts['verified']} v{2} entries, "
            f"{counts['legacy_skipped']} pre-chain legacy entries skipped."
        )


def handle_management_token_show(
    args: argparse.Namespace,
    config: Config,
    signing_key: SigningKey,
    store: TokenStore,
    audit: AuditLogger,
    key_manager: KeyManager,
) -> None:
    """Print the management refresh token from the keyring."""
    try:
        refresh_token = key_manager.get_management_refresh_token()
    except KeyringError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    if refresh_token is None:
        print(
            "Error: no management token found. Start the server at least once first.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.json:
        print(json.dumps({"refresh_token": refresh_token}))
    else:
        print(refresh_token)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-auth",
        description="Token-based authorization for AI agent access to host applications.",
    )
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument("--config-dir", help="Override configuration directory")

    subparsers = parser.add_subparsers(dest="command")

    # token subcommand
    token_parser = subparsers.add_parser("token", help="Token management")
    token_sub = token_parser.add_subparsers(dest="token_command")

    # token create
    create_parser = token_sub.add_parser("create", help="Create a new token pair")
    create_parser.add_argument(
        "--scope",
        action="append",
        required=True,
        help="Scope in format 'name' or 'name=tier' (e.g. things:read=allow)",
    )

    # token list
    token_sub.add_parser("list", help="List all token families")

    # token modify
    modify_parser = token_sub.add_parser("modify", help="Modify token family scopes")
    modify_parser.add_argument("family_id", help="Token family ID")
    modify_parser.add_argument(
        "--add-scope", action="append", help="Add a scope (name or name=tier)"
    )
    modify_parser.add_argument("--remove-scope", action="append", help="Remove a scope by name")
    modify_parser.add_argument(
        "--set-tier", action="append", help="Change tier on existing scope (name=tier)"
    )

    # token revoke
    revoke_parser = token_sub.add_parser("revoke", help="Revoke a token family")
    revoke_parser.add_argument("family_id", help="Token family ID")

    # token rotate
    rotate_parser = token_sub.add_parser("rotate", help="Rotate a token family")
    rotate_parser.add_argument("family_id", help="Token family ID")

    # serve subcommand — bind address/port are configured in config.yaml;
    # the CLI has no override flags to keep exactly one source of truth.
    subparsers.add_parser("serve", help="Start the HTTP server")

    # management-token subcommand
    mgmt_parser = subparsers.add_parser(
        "management-token", help="Manage the HTTP management credential"
    )
    mgmt_sub = mgmt_parser.add_subparsers(dest="management_token_command")
    mgmt_sub.add_parser("show", help="Print the management refresh token")

    # verify-audit subcommand
    subparsers.add_parser(
        "verify-audit",
        help="Replay the HMAC chain of the audit log to detect tampering",
    )

    return parser


COMMAND_HANDLERS = {
    "create": handle_token_create,
    "list": handle_token_list,
    "modify": handle_token_modify,
    "revoke": handle_token_revoke,
    "rotate": handle_token_rotate,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    try:
        config, signing_key, store, audit, key_manager = _init_services(args.config_dir)
    except KeyLossError as exc:
        # Surface the operator-facing message without a Python traceback —
        # the recovery instructions are in the message itself.
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.command == "serve":
        handle_serve(args, config, signing_key, store, audit, key_manager)
        return

    if args.command == "token":
        if args.token_command is None:
            print(
                "Error: specify a token subcommand (create, list, modify, revoke, rotate)",
                file=sys.stderr,
            )
            sys.exit(1)
        handler = COMMAND_HANDLERS.get(args.token_command)
        if handler:
            handler(args, config, signing_key, store, audit)
        else:
            print(f"Error: unknown token command '{args.token_command}'", file=sys.stderr)
            sys.exit(1)
        return

    if args.command == "management-token":
        if args.management_token_command == "show":
            handle_management_token_show(args, config, signing_key, store, audit, key_manager)
        else:
            print(
                "Error: specify a management-token subcommand (show)",
                file=sys.stderr,
            )
            sys.exit(1)
        return

    if args.command == "verify-audit":
        handle_verify_audit(args, config, signing_key, store, audit, key_manager)
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
