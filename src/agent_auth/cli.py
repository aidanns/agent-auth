"""CLI entrypoint for agent-auth."""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-auth",
        description="Token-based authorization for AI agent access to macOS applications",
    )
    subparsers = parser.add_subparsers(dest="command")

    # token subcommand
    token_parser = subparsers.add_parser("token", help="Manage authorization tokens")
    token_subparsers = token_parser.add_subparsers(dest="token_command")

    # token create
    create_parser = token_subparsers.add_parser("create", help="Create a new token")
    create_parser.add_argument(
        "--scope", action="append", required=True, help="Permission scope (repeatable)"
    )
    create_parser.add_argument(
        "--expires", default="7d", help="Expiration duration (e.g. 1h, 7d, 30d)"
    )

    # token list
    token_subparsers.add_parser("list", help="List active tokens")

    # token revoke
    revoke_parser = token_subparsers.add_parser("revoke", help="Revoke a token")
    revoke_parser.add_argument("token_id", help="Token ID to revoke")

    # token rotate
    rotate_parser = token_subparsers.add_parser(
        "rotate", help="Rotate a token (create new, revoke old)"
    )
    rotate_parser.add_argument("token_id", help="Token ID to rotate")
    rotate_parser.add_argument(
        "--expires", default="7d", help="Expiration duration for new token"
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "token":
        if args.token_command is None:
            token_parser.print_help()
            sys.exit(1)


if __name__ == "__main__":
    main()
