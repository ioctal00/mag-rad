#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path


TEXT_SUFFIXES = {".csv", ".json", ".sql", ".txt", ".yaml", ".yml"}
WORKSPACE_PATH = re.compile(r"/(?:home|Users)/[^/\s]+/eldin/")
HOME_PATH = re.compile(r"/(?:home|Users)/[^/\s]+/")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def parse_checksums(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        checksum, relative = line.split("  ", maxsplit=1)
        rows[relative] = checksum
    return rows


def verify_source(source: Path) -> None:
    expected = parse_checksums(source / "checksums.sha256")
    for relative, checksum in expected.items():
        path = source / relative
        if not path.is_file() or digest(path) != checksum:
            raise ValueError(f"Invalid source release file: {relative}")


def included(relative: Path) -> bool:
    return (
        relative.suffix.lower() != ".md"
        and relative.name not in {"checksums.sha256", "release_manifest.json"}
    )


def sanitize_local_paths(path: Path) -> None:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return
    text = path.read_text(encoding="utf-8")
    text = WORKSPACE_PATH.sub("", text)
    text = HOME_PATH.sub("<home>/", text)
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Curate the public Plan 41 actionability artifact package."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("../master-regimes/releases/pressure-actionability-v1"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/results/pressure-actionability-v1"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    destination = args.out_dir.resolve()
    verify_source(source)
    source_manifest = json.loads(
        (source / "release_manifest.json").read_text(encoding="utf-8")
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="pressure-actionability-v1-", dir=destination.parent
    ) as temporary:
        staged = Path(temporary) / destination.name
        staged.mkdir()
        copied: list[dict[str, object]] = []
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            if not included(relative):
                continue
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            sanitize_local_paths(target)
            copied.append(
                {
                    "path": relative.as_posix(),
                    "sha256": digest(target),
                    "bytes": target.stat().st_size,
                }
            )

        source_manifest_path = staged / "source_release_manifest.json"
        source_manifest_path.write_text(
            json.dumps(source_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        copied.append(
            {
                "path": source_manifest_path.name,
                "sha256": digest(source_manifest_path),
                "bytes": source_manifest_path.stat().st_size,
            }
        )
        curation_manifest = {
            "curation_contract": "public-pressure-actionability-v1",
            "source_evidence_generation_commit": source_manifest[
                "evidence_generation_commit"
            ],
            "excluded": [
                "narrative_markdown_reports",
                "source_package_checksum_index",
                "source_package_top_level_readme",
            ],
            "path_policy": "local workspace prefixes replaced with repo-relative paths",
            "evidence": source_manifest["evidence"],
            "files": sorted(copied, key=lambda row: str(row["path"])),
        }
        curation_path = staged / "curation_manifest.json"
        curation_path.write_text(
            json.dumps(curation_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        checksum_paths = sorted(
            path for path in staged.rglob("*") if path.is_file()
        )
        (staged / "checksums.sha256").write_text(
            "".join(
                f"{digest(path)}  {path.relative_to(staged).as_posix()}\n"
                for path in checksum_paths
            ),
            encoding="utf-8",
        )

        if destination.exists():
            shutil.rmtree(destination)
        staged.rename(destination)

    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
