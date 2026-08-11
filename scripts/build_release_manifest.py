#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "generated",
    "tmp",
    "work",
}
MANIFEST_PATH = Path("artifacts/release-manifest.json")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def included(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if relative == MANIFEST_PATH:
        return False
    if path.suffix.lower() in {".pdf", ".tex"}:
        return False
    return not EXCLUDED_PARTS.intersection(relative.parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    return parser.parse_args()


def main() -> int:
    root = parse_args().root.resolve()
    files = []
    candidates = [
        path
        for path in root.rglob("*")
        if path.is_file() and included(path, root)
    ]
    for index, path in enumerate(sorted(candidates), start=1):
        relative = path.relative_to(root).as_posix()
        if index % 500 == 0:
            print(f"[manifest] {index}/{len(candidates)}", flush=True)
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": digest(path),
            }
        )
    payload = {
        "schema_version": 1,
        "hash_algorithm": "sha256",
        "file_count": len(files),
        "files": files,
    }
    destination = root / MANIFEST_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[manifest] files={len(files)} output={destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
