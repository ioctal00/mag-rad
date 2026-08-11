#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import subprocess
import tarfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("reproducibility/public-release-audit.json")
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
TEXT_SUFFIXES = {
    ".cfg",
    ".csv",
    ".ini",
    ".j2",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".sh",
    ".sql",
    ".tf",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
DATA_ROOTS = {
    "analysis",
    "artifacts",
    "corpora",
    "datasets",
    "examples",
    "experiments",
    "queries",
    "releases",
    "reproducibility",
}
LOCAL_PATH = re.compile(
    rb"(?:/(?:home|Users)/[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\[^\\\s]+\\)"
)
IPV4 = re.compile(rb"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
CREDENTIAL_URI = re.compile(
    rb"(?i)(?:postgres(?:ql)?|https?|ssh)://[^\s/:]+:[^\s/@]+@"
)
AWS_KEY = re.compile(rb"AKIA[0-9A-Z]{16}")
GITHUB_TOKEN = re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}")
PRIVATE_KEY_MARKERS = tuple(
    ("-----BEGIN " + prefix + "PRIVATE KEY-----").encode()
    for prefix in ("", "RSA ", "OPENSSH ", "EC ", "DSA ")
)
PRIVATE_DOMAIN = ("eldinhelja" + ".com").encode()
CHUNK_SIZE = 1024 * 1024
OVERLAP = 512


def included(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if EXCLUDED_PARTS.intersection(relative.parts):
        return False
    return path.is_file() and path.suffix.lower() != ".pdf"


def is_runtime_address(value: str, relative: Path) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if relative.parts[0] not in DATA_ROOTS:
        return False
    if address.is_loopback or address.is_unspecified:
        return False
    if address in ipaddress.ip_network("0.0.0.0/8"):
        return False
    if address in ipaddress.ip_network("192.0.2.0/24"):
        return False
    if address in ipaddress.ip_network("198.51.100.0/24"):
        return False
    if address in ipaddress.ip_network("203.0.113.0/24"):
        return False
    return address.is_private or address.is_global


def scan_chunk(data: bytes, relative: Path) -> set[str]:
    findings: set[str] = set()
    if (b"/home/" in data or b"/Users/" in data or b"\\Users\\" in data) and LOCAL_PATH.search(data):
        findings.add("local_path")
    if b"://" in data and b"@" in data and CREDENTIAL_URI.search(data):
        findings.add("credential_uri")
    if b"AKIA" in data and AWS_KEY.search(data):
        findings.add("aws_access_key")
    if b"gh" in data and GITHUB_TOKEN.search(data):
        findings.add("github_token")
    if relative.parts[0] != "scripts" and PRIVATE_DOMAIN in data.lower():
        findings.add("private_domain")
    if relative.parts[0] != "scripts" and any(marker in data for marker in PRIVATE_KEY_MARKERS):
        findings.add("private_key")
    if relative.parts[0] in DATA_ROOTS and b"." in data:
        addresses = (value.decode("ascii") for value in IPV4.findall(data))
        if any(is_runtime_address(value, relative) for value in addresses):
            findings.add("runtime_ip_address")
    return findings


def scan_stream(handle: object, relative: Path) -> list[dict[str, str]]:
    kinds: set[str] = set()
    tail = b""
    while True:
        chunk = handle.read(CHUNK_SIZE)
        if not chunk:
            break
        data = tail + chunk
        kinds.update(scan_chunk(data, relative))
        tail = data[-OVERLAP:]
    return [{"path": relative.as_posix(), "kind": kind} for kind in sorted(kinds)]


def scan_file(path: Path, root: Path, scan_archives: bool) -> list[dict[str, str]]:
    relative = path.relative_to(root)
    findings: list[dict[str, str]] = []
    if path.name.endswith(".tar.gz"):
        if not scan_archives:
            return findings
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or Path(member.name).suffix.lower() not in TEXT_SUFFIXES:
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                nested = relative / member.name
                findings.extend(scan_stream(handle, nested))
        return findings
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return findings
    with path.open("rb") as handle:
        findings.extend(scan_stream(handle, relative))
    return findings


def history_summary(root: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            "git",
            "log",
            "--all",
            "-G",
            r"/home/|eldinhelja[.]com",
            "--format=%H",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    commits = sorted(set(completed.stdout.splitlines()))
    return {
        "historical_commits_with_local_identifiers": len(commits),
        "history_rewrite_performed": False,
        "note": (
            "Current release files are sanitized. Removing old local-path references "
            "from already published commits requires an explicit history rewrite."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit the public release tree for high-confidence data leaks."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--archives", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    findings: list[dict[str, str]] = []
    files = [path for path in root.rglob("*") if included(path, root)]
    for path in sorted(files):
        findings.extend(scan_file(path, root, args.archives))
    counts = Counter(row["kind"] for row in findings)
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": "PASS" if not findings else "FAIL",
        "files_scanned": len(files),
        "archives_scanned": args.archives,
        "finding_counts": dict(sorted(counts.items())),
        "findings": findings,
    }
    if args.history:
        payload["git_history"] = history_summary(root)
    destination = root / (
        Path("reproducibility/public-release-audit-full.json")
        if args.archives or args.history
        else OUTPUT
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        f"[public-audit] status={payload['status']} files={len(files)} "
        f"findings={len(findings)}"
    )
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
