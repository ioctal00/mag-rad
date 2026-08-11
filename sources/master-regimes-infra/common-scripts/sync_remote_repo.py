#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "master-regimes-infra" / "env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rsync a local repo to matching remote nodes.")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--remote-dir", required=True)
    parser.add_argument("--group", default="db_nodes")
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--delete", action="store_true")
    parser.add_argument(
        "--git-branch",
        help="Remote Git branch to align before rsync; defaults to the local branch.",
    )
    return parser.parse_args()


def load_shell_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if not parts:
            continue
        assignment = parts[1] if parts[0] == "export" and len(parts) >= 2 else parts[0]
        if "=" not in assignment:
            continue
        key, value = assignment.split("=", 1)
        values[key] = value
    return values


def load_group(path: Path, group: str) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    hosts = data["all"]["children"].get(group, {}).get("hosts", {})
    if not hosts:
        raise RuntimeError(f"No hosts found in inventory group: {group}")
    return hosts


def git_output(repo_dir: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo_dir), *args],
        text=True,
    ).strip()


def local_git_identity(
    local_dir: Path,
    requested_branch: str | None,
) -> tuple[str, str] | None:
    if not (local_dir / ".git").exists():
        if requested_branch:
            raise RuntimeError(
                f"--git-branch requires a Git worktree: {local_dir}"
            )
        return None
    branch = requested_branch or git_output(
        local_dir,
        "branch",
        "--show-current",
    )
    if not branch:
        raise RuntimeError(
            f"Local repository is in detached HEAD state: {local_dir}"
        )
    head = git_output(local_dir, "rev-parse", "HEAD")
    return branch, head


def remote_branch_setup_command(
    *,
    remote_dir: str,
    remote_bundle: str,
    branch: str,
    head: str,
) -> str:
    repo = shlex.quote(remote_dir)
    bundle = shlex.quote(remote_bundle)
    branch_value = shlex.quote(branch)
    head_value = shlex.quote(head)
    remote_ref = shlex.quote(f"refs/remotes/local-sync/{branch}")
    source_ref = shlex.quote(f"refs/heads/{branch}")
    return " && ".join(
        [
            f"test -d {repo}/.git",
            f"test -f {bundle}",
            (
                f"git -C {repo} fetch --force --quiet {bundle} "
                f"{source_ref}:{remote_ref}"
            ),
            (
                f"git -C {repo} checkout --force -B "
                f"{branch_value} {remote_ref}"
            ),
            f"test \"$(git -C {repo} rev-parse HEAD)\" = {head_value}",
            f"rm -f {bundle}",
        ]
    )


def main() -> int:
    args = parse_args()
    local_dir = args.local_dir.resolve()
    if not local_dir.is_dir():
        raise FileNotFoundError(f"Local directory not found: {local_dir}")
    git_identity = local_git_identity(local_dir, args.git_branch)
    git_bundle: Path | None = None
    if git_identity is not None:
        branch, _ = git_identity
        descriptor, bundle_name = tempfile.mkstemp(
            prefix="master-regimes-repo-sync-",
            suffix=".bundle",
        )
        os.close(descriptor)
        git_bundle = Path(bundle_name)
        git_bundle.unlink()
        atexit.register(git_bundle.unlink, missing_ok=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(local_dir),
                "bundle",
                "create",
                str(git_bundle),
                f"refs/heads/{branch}",
            ],
            check=True,
        )

    env_values = {**load_shell_env(args.env_file), **os.environ}
    key_value = env_values.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", "")
    key_file = Path(key_value).expanduser() if key_value else None
    ssh_command = "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
    if key_file is not None:
        ssh_command += f" -i {shlex.quote(str(key_file))} -o IdentitiesOnly=yes"

    hosts = load_group(args.inventory, args.group)
    for host_name, host_info in sorted(hosts.items()):
        host = host_info["ansible_host"]
        print(f"Syncing {local_dir} to {host_name}:{args.remote_dir}", flush=True)
        subprocess.run(
            [
                "ssh",
                *(["-i", str(key_file), "-o", "IdentitiesOnly=yes"] if key_file else []),
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                f"{args.ssh_user}@{host}",
                f"mkdir -p {shlex.quote(args.remote_dir)}",
            ],
            check=True,
        )
        if git_identity is not None:
            branch, head = git_identity
            assert git_bundle is not None
            remote_bundle = (
                f"/tmp/master-regimes-repo-sync-{head[:12]}.bundle"
            )
            print(
                f"Aligning {host_name}:{args.remote_dir} "
                f"to {branch}@{head[:12]}",
                flush=True,
            )
            subprocess.run(
                [
                    "scp",
                    *(
                        ["-i", str(key_file), "-o", "IdentitiesOnly=yes"]
                        if key_file
                        else []
                    ),
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    str(git_bundle),
                    f"{args.ssh_user}@{host}:{remote_bundle}",
                ],
                check=True,
            )
            subprocess.run(
                [
                    "ssh",
                    *(
                        ["-i", str(key_file), "-o", "IdentitiesOnly=yes"]
                        if key_file
                        else []
                    ),
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    f"{args.ssh_user}@{host}",
                    remote_branch_setup_command(
                        remote_dir=args.remote_dir,
                        remote_bundle=remote_bundle,
                        branch=branch,
                        head=head,
                    ),
                ],
                check=True,
            )
        command = [
            "rsync",
            "-az",
            "--exclude",
            ".git/",
            "--exclude",
            ".venv/",
            "--exclude",
            ".env",
            "--exclude",
            "runs/",
            "--exclude",
            "generated/",
            "--exclude",
            "__pycache__/",
            "--exclude",
            ".ruff_cache/",
            "-e",
            ssh_command,
        ]
        if args.delete:
            command.append("--delete")
        command.extend(
            [
                f"{local_dir}/",
                f"{args.ssh_user}@{host}:{args.remote_dir}/",
            ]
        )
        subprocess.run(command, check=True)
        if git_identity is not None:
            branch, head = git_identity
            verify_command = (
                f"test \"$(git -C {shlex.quote(args.remote_dir)} "
                f"branch --show-current)\" = {shlex.quote(branch)} && "
                f"test \"$(git -C {shlex.quote(args.remote_dir)} "
                f"rev-parse HEAD)\" = {shlex.quote(head)}"
            )
            subprocess.run(
                [
                    "ssh",
                    *(
                        ["-i", str(key_file), "-o", "IdentitiesOnly=yes"]
                        if key_file
                        else []
                    ),
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    f"{args.ssh_user}@{host}",
                    verify_command,
                ],
                check=True,
            )
    if git_bundle is not None:
        git_bundle.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
