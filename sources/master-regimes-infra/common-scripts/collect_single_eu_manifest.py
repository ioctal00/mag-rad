#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_json(command: list[str], *, cwd: Path) -> object | None:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def git_rev(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", required=True, type=Path)
    parser.add_argument("--tf-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--label", default="single-eu")
    args = parser.parse_args()

    repo_root = Path.cwd()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{args.label}-{created_at}.json"

    sibling_repos = {
        "master-regimes-infra": repo_root,
        "citus-datagen": repo_root.parent / "citus-datagen",
        "psql-benchmarks": repo_root.parent / "psql-benchmarks",
        "analytics-client": repo_root.parent / "analytics-client",
    }

    manifest = {
        "label": args.label,
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "system_config": str(args.system),
        "system_config_sha256": sha256_file(args.system),
        "installed_files": {
            "terraform_tfvars": {
                "path": str(args.tf_dir / "terraform.tfvars"),
                "sha256": sha256_file(args.tf_dir / "terraform.tfvars"),
            },
            "ansible_group_vars": {
                "path": "ansible/group_vars/all.yml",
                "sha256": sha256_file(Path("ansible/group_vars/all.yml")),
            },
        },
        "terraform_outputs": run_json(["terraform", "output", "-json"], cwd=args.tf_dir),
        "git_revisions": {
            name: git_rev(path) for name, path in sibling_repos.items() if path.exists()
        },
    }

    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
