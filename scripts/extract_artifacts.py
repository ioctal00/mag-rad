#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def safe_members(archive: tarfile.TarFile, destination: Path):
    root = destination.resolve()
    for member in archive.getmembers():
        if member.issym() or member.islnk():
            raise ValueError(f"Link nije dozvoljen u arhivi: {member.name}")
        target = (destination / member.name).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"Nesigurna putanja u arhivi: {member.name}")
        yield member


def extract_kind(root: Path, kind: str) -> None:
    source = root / "artifacts" / kind
    destination = (
        root / "work" / ("logical-runs" if kind == "logical-indexes" else "raw")
    )
    destination.mkdir(parents=True, exist_ok=True)
    archives = sorted(source.glob("*.tar.gz"))
    if not archives:
        raise SystemExit(f"Nema arhiva u {source}")
    for index, archive_path in enumerate(archives, start=1):
        print(
            f"[extract] {index}/{len(archives)} {archive_path.name}",
            flush=True,
        )
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(
                destination,
                members=safe_members(archive, destination),
                filter="data",
            )
    print(f"[extract] output={destination}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--kind",
        choices=("logical-indexes", "raw-attempts"),
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    extract_kind(args.root.resolve(), args.kind)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
