from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "master-regimes-infra" / "env"
WORKSPACE_ROOT = REPO_ROOT.parent


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def load_shell_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
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
            if "=" in assignment:
                key, value = assignment.split("=", 1)
                values[key] = value
    return {**values, **os.environ}


def private_key(env_values: dict[str, str]) -> Path | None:
    raw_value = env_values.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", "")
    if not raw_value:
        return None
    path = Path(raw_value).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"SSH private key not found: {path}")
    return path


def inventory_data(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_group_host(
    path: Path,
    *,
    group: str,
    region: str = "",
    target_host: str = "",
) -> tuple[str, dict[str, Any]]:
    data = inventory_data(path)
    hosts = data["all"]["children"].get(group, {}).get("hosts", {})
    if not hosts:
        raise RuntimeError(f"No hosts found in inventory group {group}")
    if target_host:
        if target_host not in hosts:
            raise RuntimeError(f"Host {target_host} not found in inventory group {group}")
        return target_host, hosts[target_host]
    candidates = sorted(hosts)
    if region:
        regional = [
            name
            for name in candidates
            if name.startswith(f"{region}-")
            or name
            in data["all"]["children"].get(region, {}).get("hosts", {})
        ]
        if not regional:
            raise RuntimeError(f"No {group} host found for region {region}")
        candidates = regional
    name = candidates[0]
    return name, hosts[name]


def ssh_base(host: str, user: str, key_file: Path | None) -> list[str]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=4",
    ]
    if key_file is not None:
        command.extend(["-i", str(key_file), "-o", "IdentitiesOnly=yes"])
    command.append(f"{user}@{host}")
    return command


def ssh_run(
    *,
    host: str,
    user: str,
    key_file: Path | None,
    remote_script: str,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [*ssh_base(host, user, key_file), f"bash -lc {shlex.quote(remote_script)}"],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        details = []
        if stdout:
            details.append(f"stdout:\n{stdout[-8000:]}")
        if stderr:
            details.append(f"stderr:\n{stderr[-8000:]}")
        detail_text = "\n".join(details) or "(no remote output)"
        raise RuntimeError(
            f"Remote command failed on {host} with exit code "
            f"{result.returncode}:\n{detail_text}"
        )
    return result


def scp_file(
    *,
    source: Path,
    host: str,
    user: str,
    key_file: Path | None,
    destination: str,
) -> None:
    command = [
        "scp",
        "-q",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
    ]
    if key_file is not None:
        command.extend(["-i", str(key_file), "-o", "IdentitiesOnly=yes"])
    command.extend([str(source), f"{user}@{host}:{destination}"])
    subprocess.run(command, check=True)


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_dump(source_lock_path: Path, cache_dir: Path) -> tuple[Path, dict[str, Any]]:
    source_lock = load_yaml(source_lock_path)
    dump = (source_lock.get("resources") or {}).get("dump")
    if not isinstance(dump, dict):
        raise ValueError("source lock has no resources.dump mapping")
    filename = str(dump["filename"])
    destination = cache_dir / filename
    expected_md5 = str(dump["md5"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or file_digest(destination, "md5") != expected_md5:
        temporary = destination.with_suffix(destination.suffix + ".part")
        request = urllib.request.Request(
            str(dump["url"]),
            headers={"User-Agent": "master-regimes-stats-ceb-adapter/1.0"},
        )
        with urllib.request.urlopen(request, timeout=180) as response, temporary.open(
            "wb"
        ) as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        temporary.replace(destination)
    actual_md5 = file_digest(destination, "md5")
    if actual_md5 != expected_md5:
        raise ValueError(f"STATS-CEB dump MD5 mismatch: {actual_md5} != {expected_md5}")
    return destination.resolve(), {
        "source_lock": str(source_lock_path.resolve()),
        "record_url": source_lock.get("record_url", ""),
        "doi": source_lock.get("doi", ""),
        "license": source_lock.get("license", ""),
        "dump_path": str(destination.resolve()),
        "dump_size_bytes": destination.stat().st_size,
        "dump_md5": actual_md5,
    }


def ensure_remote_file(
    *,
    local_path: Path,
    expected_md5: str,
    host: str,
    user: str,
    key_file: Path | None,
    remote_dir: str,
) -> str:
    remote_path = f"{remote_dir.rstrip('/')}/{local_path.name}"
    check_script = (
        f"mkdir -p {shlex.quote(remote_dir)}; "
        f"if [ -f {shlex.quote(remote_path)} ]; then "
        f"md5sum {shlex.quote(remote_path)} | awk '{{print $1}}'; fi"
    )
    current = ssh_run(
        host=host,
        user=user,
        key_file=key_file,
        remote_script=check_script,
    ).stdout.strip()
    if current != expected_md5:
        scp_file(
            source=local_path,
            host=host,
            user=user,
            key_file=key_file,
            destination=remote_path,
        )
        verified = ssh_run(
            host=host,
            user=user,
            key_file=key_file,
            remote_script=f"md5sum {shlex.quote(remote_path)} | awk '{{print $1}}'",
        ).stdout.strip()
        if verified != expected_md5:
            raise RuntimeError(
                f"Remote file checksum mismatch on {host}: {verified} != {expected_md5}"
            )
    return remote_path


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
