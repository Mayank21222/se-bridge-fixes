"""Command-line interface entry points for the Standard Ebooks bridge."""

from __future__ import annotations

import sys
from typing import NoReturn


def main(argv: list[str] | None = None) -> NoReturn:
    """Run the CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="se-bridge",
        description="Standard Ebooks HTTP bridge (offline-safe validation).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="se-bridge/1.0.0",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate environment configuration only; does not start the server.",
    )
    args = parser.parse_args(argv)

    if args.check_config:
        from app.config import get_settings  # local import to avoid heavy deps

        get_settings()
        print("Configuration is valid.")
        sys.exit(0)

    parser.print_help()
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
