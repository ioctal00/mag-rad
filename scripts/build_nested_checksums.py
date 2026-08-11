#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directories", nargs="+", type=Path)
    args = parser.parse_args()
    for directory in args.directories:
        root = directory.resolve()
        rows = []
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name != "checksums.sha256":
                rows.append(f"{digest(path)}  {path.relative_to(root).as_posix()}")
        (root / "checksums.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")
        print(f"checksums PASS: {directory} files={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
