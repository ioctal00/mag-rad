#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
TF_BASE_DIR = Path(os.environ.get("TF_BASE_DIR", BASE_DIR / "terraform"))


def terraform_env_dirs() -> dict[str, Path]:
    env_root = TF_BASE_DIR / "envs"
    if not env_root.exists():
        return {}
    return {
        path.name: path
        for path in sorted(env_root.iterdir())
        if path.is_dir() and (path / "main.tf").exists()
    }


def tf_output_json(path: Path) -> dict:
    if not path.exists():
        return {}

    try:
        result = subprocess.run(
            ["terraform", "output", "-json"],
            cwd=str(path),
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return {}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def output_value(outputs: dict, key: str, default=None):
    return outputs.get(key, {}).get("value", default)


def add_host(inventory: dict, name: str, groups: list[str], hostvars: dict):
    for group in groups:
        group_entry = inventory["all"]["children"].setdefault(group, {"hosts": {}})
        group_entry.setdefault("hosts", {})[name] = hostvars


def build_inventory() -> dict:
    env_dirs = terraform_env_dirs()
    groups = [
        *env_dirs,
        "coordinators",
        "workers",
        "backends",
        "web_portals",
        "analytics_clients",
        "db_nodes",
        "citus_nodes",
    ]
    inventory = {
        "all": {
            "children": {group: {"hosts": {}} for group in groups},
        },
    }

    for env_name, env_dir in env_dirs.items():
        outputs = tf_output_json(env_dir)
        if not outputs:
            continue

        region = output_value(outputs, "region", env_name)
        coordinator_public = output_value(outputs, "coordinator_public_ip")
        coordinator_public_ipv6 = output_value(outputs, "coordinator_public_ipv6")
        coordinator_private = output_value(outputs, "coordinator_private_ip")
        worker_public_ips = output_value(outputs, "worker_public_ips", []) or []
        worker_private_ips = output_value(outputs, "worker_private_ips", []) or []
        backend_public_ips = output_value(outputs, "backend_public_ips", []) or []
        web_portal_public = output_value(outputs, "web_portal_public_ip")
        web_portal_private = output_value(outputs, "web_portal_private_ip")
        analytics_client_public = output_value(outputs, "global_analytics_client_public_ip")
        analytics_client_public_ipv6 = output_value(outputs, "global_analytics_client_public_ipv6")
        analytics_client_private = output_value(outputs, "global_analytics_client_private_ip")
        vpc_cidr = output_value(outputs, "vpc_cidr", "")

        if coordinator_public:
            add_host(
                inventory,
                f"{env_name}-coord-1",
                [env_name, "coordinators", "db_nodes", "citus_nodes"],
                {
                    "ansible_host": coordinator_public,
                    "public_ipv6": coordinator_public_ipv6,
                    "private_ip": coordinator_private,
                    "logical_region": env_name,
                    "region_name": region,
                    "citus_node_role": "coordinator",
                    "vpc_cidr": vpc_cidr,
                },
            )

        for idx, public_ip in enumerate(worker_public_ips, start=1):
            private_ip = worker_private_ips[idx - 1] if idx - 1 < len(worker_private_ips) else None
            add_host(
                inventory,
                f"{env_name}-worker-{idx}",
                [env_name, "workers", "db_nodes", "citus_nodes"],
                {
                    "ansible_host": public_ip,
                    "private_ip": private_ip,
                    "logical_region": env_name,
                    "region_name": region,
                    "citus_node_role": "worker",
                    "vpc_cidr": vpc_cidr,
                },
            )

        for idx, public_ip in enumerate(backend_public_ips, start=1):
            add_host(
                inventory,
                f"{env_name}-api-{idx}",
                [env_name, "backends"],
                {
                    "ansible_host": public_ip,
                    "logical_region": env_name,
                    "region_name": region,
                    "service_role": "backend",
                    "vpc_cidr": vpc_cidr,
                },
            )

        if web_portal_public:
            add_host(
                inventory,
                f"{env_name}-web-portal-1",
                [env_name, "web_portals"],
                {
                    "ansible_host": web_portal_public,
                    "private_ip": web_portal_private,
                    "logical_region": env_name,
                    "region_name": region,
                    "service_role": "web_portal",
                    "vpc_cidr": vpc_cidr,
                },
            )

        if analytics_client_public:
            add_host(
                inventory,
                f"{env_name}-analytics-1",
                [env_name, "analytics_clients"],
                {
                    "ansible_host": analytics_client_public,
                    "public_ipv6": analytics_client_public_ipv6,
                    "private_ip": analytics_client_private,
                    "logical_region": env_name,
                    "region_name": region,
                    "service_role": "global_analytics_client",
                    "vpc_cidr": vpc_cidr,
                },
            )

    return inventory


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--host":
        print(json.dumps({}))
        return

    print(json.dumps(build_inventory(), indent=2))


if __name__ == "__main__":
    main()
