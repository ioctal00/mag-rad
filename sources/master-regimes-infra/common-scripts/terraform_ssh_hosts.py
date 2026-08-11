#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shlex
import sys


def main() -> int:
    try:
        commands = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"Failed to parse Terraform ssh_commands JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(commands, list):
        print("Expected Terraform ssh_commands output to be a JSON list.", file=sys.stderr)
        return 1

    for command in commands:
        if not isinstance(command, str) or not command.strip():
            continue
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()
        if not parts:
            continue
        target = parts[-1]
        target = re.sub(r"^.*@", "", target)
        if target:
            print(target)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
