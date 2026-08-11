from __future__ import annotations

import argparse
import sys

from src.datagen.cli import run_cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="citus-datagen",
        description="Minimal dataset generator for the thesis Citus environment.",
    )
    parser.add_argument(
        "command",
        choices=["generate", "load", "reset-and-load"],
        help="Operation to execute.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_cli(args.command)


if __name__ == "__main__":
    sys.exit(main())
