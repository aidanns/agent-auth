# SPDX-FileCopyrightText: 2026 Aidan Nagorcka-Smith
#
# SPDX-License-Identifier: MIT

"""CLI entrypoint for agent-auth token management and server."""

import argparse
import json
import sys

from agent_auth.audit import AuditLogger
from agent_auth.config import Config, load_config
from agent_auth.keys import KeyManager, SigningKey
from agent_auth.scopes import parse_scope_arg
from agent_auth.store import TokenStore
from agent_auth.tokens import create_token_pair, generate_token_id


def _init_services(
    config_dir: str | None = None,
) -> tuple[Config, SigningKey, TokenStore, AuditLogger]:
    config = load_config(config_dir)
    key_manager = KeyManager()
    signing_key = key_manager.get_or_create_signing_key()
    encryption_key = key_manager.get_or_create_encryption_key()
    store = TokenStore(config.db_path, encryption_key)
    audit = AuditLogger(config.log_path)
    return config, signing_key, store, audit


def handle_token_create(args, config, signing_key, store, audit):
    """Create a new token family with a token pair."""
    scopes = {}
    for scope_arg in args.scope:
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


def handle_token_list(args, config, signing_key, store, audit):
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


def handle_token_modify(args, config, signing_key, store, audit):
    """Modify scopes on an existing token family."""
    family = store.get_family(args.family_id)
    if family is None:
        print(f"Error: family '{args.family_id}' not found", file=sys.stderr)
        sys.exit(1)
    if family["revoked"]:
        print(f"Error: family '{args.family_id}' is revoked", file=sys.stderr)
        sys.exit(1)

    scopes = dict(family["scopes"])

    for scope_arg in args.add_scope or []:
        name, tier = parse_scope_arg(scope_arg)
        scopes[name] = tier

    for name in args.remove_scope or []:
        scopes.pop(name, None)

    for tier_arg in args.set_tier or []:
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


def handle_token_revoke(args, config, signing_key, store, audit):
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


def handle_token_rotate(args, config, signing_key, store, audit):
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


def handle_serve(args, config, signing_key, store, audit):
    """Start the agent-auth HTTP server."""
    from agent_auth.server import run_server

    run_server(config, signing_key, store, audit)


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

    # serve subcommand — bind address/port are configured in config.json;
    # the CLI has no override flags to keep exactly one source of truth.
    subparsers.add_parser("serve", help="Start the HTTP server")

    return parser


COMMAND_HANDLERS = {
    "create": handle_token_create,
    "list": handle_token_list,
    "modify": handle_token_modify,
    "revoke": handle_token_revoke,
    "rotate": handle_token_rotate,
}


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    config, signing_key, store, audit = _init_services(args.config_dir)

    if args.command == "serve":
        handle_serve(args, config, signing_key, store, audit)
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

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
