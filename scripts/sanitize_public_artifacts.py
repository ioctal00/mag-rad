#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import ipaddress
import os
import re
import tarfile
import tempfile
from pathlib import Path


TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".md", ".sql", ".txt", ".yaml", ".yml"}
WORKSPACE_PATH = re.compile(r"/(?:home|Users)/[^/\s]+/eldin/")
HOME_PATH = re.compile(r"/(?:home|Users)/[^/\s]+/")
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")

# Runtime addresses are not needed to reproduce the measurements. Logical node
# names remain in the same records and preserve the experimental topology.
SENSITIVE_REPLACEMENTS = (
    ("78.141." + "220.152", "<eu-coord-1-public-ip>"),
    ("209.250." + "246.140", "<us-coord-1-public-ip>"),
    ("10.7." + "144.3", "<eu-analytics-1-private-ip>"),
    ("10.7." + "144.6", "<eu-coord-1-private-ip>"),
    ("10.7." + "144.9", "<us-coord-1-private-ip>"),
    ("ptfdemo." + "eldinhelja.com", "thesis-demo.example.org"),
)


def redact_runtime_address(match: re.Match[str]) -> str:
    value = match.group(0)
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return value
    if address.is_loopback or address.is_unspecified:
        return value
    if address in ipaddress.ip_network("0.0.0.0/8"):
        return value
    if address in ipaddress.ip_network("192.0.2.0/24"):
        return value
    if address in ipaddress.ip_network("198.51.100.0/24"):
        return value
    if address in ipaddress.ip_network("203.0.113.0/24"):
        return value
    if address.is_private or address.is_global:
        return "<runtime-ip>"
    return value


def sanitize_file(path: Path, redact_addresses: bool = False) -> None:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return
    text = path.read_text(encoding="utf-8")
    text = WORKSPACE_PATH.sub("", text)
    text = HOME_PATH.sub("<home>/", text)
    for private, public in SENSITIVE_REPLACEMENTS:
        text = text.replace(private, public)
    if redact_addresses:
        text = IPV4.sub(redact_runtime_address, text)
    path.write_text(text, encoding="utf-8")


def sanitize_tree(root: Path, redact_addresses: bool = False) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            sanitize_file(path, redact_addresses=redact_addresses)


def safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    for member in members:
        path = Path(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe archive member: {member.name}")
    return members


def add_tree(archive: tarfile.TarFile, root: Path) -> None:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = archive.gettarinfo(str(path), arcname=relative)
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        info.mtime = 0
        if path.is_file():
            with path.open("rb") as handle:
                archive.addfile(info, handle)
        else:
            archive.addfile(info)


def sanitize_archive(path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="public-artifact-") as temporary:
        extracted = Path(temporary) / "content"
        extracted.mkdir()
        with tarfile.open(path, "r:gz") as archive:
            archive.extractall(extracted, members=safe_members(archive), filter="data")
        sanitize_tree(extracted, redact_addresses=True)

        replacement = Path(temporary) / path.name
        with replacement.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode="w") as archive:
                    add_tree(archive, extracted)
        os.replace(replacement, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove local workspace prefixes from public artifact files."
    )
    parser.add_argument("paths", type=Path, nargs="+")
    return parser.parse_args()


def main() -> int:
    for path in parse_args().paths:
        target = path.resolve()
        if target.is_dir():
            sanitize_tree(target)
        elif target.name.endswith(".tar.gz"):
            sanitize_archive(target)
        else:
            sanitize_file(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
