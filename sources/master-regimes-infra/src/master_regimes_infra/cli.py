from __future__ import annotations

import argparse
from pathlib import Path

from .render import render_config, validate_config


def _cmd_render(args: argparse.Namespace) -> int:
    written = render_config(system_path=args.system, out_dir=args.out)
    for path in written:
        print(path)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    code, messages = validate_config(args.system)
    for message in messages:
        print(message)
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="master-regimes-infra")
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render-config")
    render.add_argument("--system", type=Path, required=True)
    render.add_argument("--out", type=Path, default=Path("generated/systems/eu-us-gac-vps"))
    render.set_defaults(func=_cmd_render)

    validate = sub.add_parser("validate-config")
    validate.add_argument("--system", type=Path, required=True)
    validate.set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
