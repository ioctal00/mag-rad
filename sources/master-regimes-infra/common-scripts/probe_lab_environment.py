#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
ANSIBLE_WRAPPER = REPO_ROOT / "common-scripts" / "run_ansible.sh"
SETTING_NAMES = (
    "server_version",
    "work_mem",
    "join_collapse_limit",
    "from_collapse_limit",
    "enable_hashagg",
    "max_parallel_workers_per_gather",
    "max_parallel_workers",
    "jit",
    "shared_buffers",
    "effective_cache_size",
)
INTERVENTION_FDW_OPTIONS = {
    "fetch_size",
    "use_remote_estimate",
    "async_capable",
    "batch_size",
    "parallel_commit",
    "options",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read PostgreSQL, Citus, FDW and qdisc state on every lab node."
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "lab-environment-probes",
    )
    return parser.parse_args()


def load_nodes(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    children = data["all"]["children"]
    groups = (
        ("analytics_clients", "gac", "analytics"),
        ("coordinators", "regional_coordinator", "app"),
        ("workers", "worker", "app"),
    )
    nodes: list[dict[str, str]] = []
    seen: set[str] = set()
    for group, layer, database in groups:
        for host_name, host_vars in sorted(children.get(group, {}).get("hosts", {}).items()):
            if host_name in seen:
                continue
            seen.add(host_name)
            nodes.append(
                {
                    "node_id": host_name,
                    "layer": layer,
                    "region": str(host_vars.get("logical_region") or "unknown"),
                    "database": database,
                }
            )
    if not nodes:
        raise RuntimeError("No analytics, coordinator or worker nodes found in inventory.")
    return nodes


def psql_command(database: str, sql: str) -> str:
    escaped_sql = sql.replace("'", "'\"'\"'")
    return f"sudo -u postgres psql -X -A -t -d {database} -c '{escaped_sql}'"


def probe_command(database: str) -> str:
    names = ",".join(f"'{name}'" for name in SETTING_NAMES)
    settings_sql = (
        "select coalesce(json_agg(json_build_object("
        "'name',name,'setting',setting,'unit',coalesce(unit,''),"
        "'source',source,'boot_value',boot_val,'reset_value',reset_val) order by name)::text,'[]') "
        f"from pg_settings where name in ({names});"
    )
    citus_sql = "select coalesce((select extversion from pg_extension where extname='citus'),'not_installed');"
    fdw_sql = (
        "select coalesce(json_agg(json_build_object('server',srvname,'options',"
        "coalesce(srvoptions,array[]::text[])) order by srvname)::text,'[]') "
        "from pg_foreign_server;"
    )
    return "\n".join(
        [
            "set -e",
            f"printf 'SETTINGS|' && {psql_command(database, settings_sql)}",
            f"printf 'CITUS|' && {psql_command(database, citus_sql)}",
            f"printf 'FDW|' && {psql_command(database, fdw_sql)}",
            "printf 'TC|' && (tc qdisc show || true) | base64 -w0 && printf '\\n'",
        ]
    )


def run_ansible(host_name: str, command: str) -> str:
    result = subprocess.run(
        [str(ANSIBLE_WRAPPER), "ansible", host_name, "-m", "ansible.builtin.shell", "-a", command],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout


def parse_ansible_payload(stdout: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    capture = False
    for raw in stdout.splitlines():
        line = raw.strip()
        if ">>" in line:
            capture = True
            line = line.split(">>", 1)[1].strip()
        if not capture or not line:
            continue
        if line.startswith("PLAY RECAP") or line.startswith("TASK "):
            break
        if "|" not in line:
            continue
        key, value = line.split("|", 1)
        if key in {"SETTINGS", "CITUS", "FDW", "TC"}:
            payload[key] = value
    return payload


def parse_fdw_servers(raw: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in json.loads(raw or "[]"):
        options: dict[str, str] = {}
        for option in row.get("options") or []:
            if "=" not in option:
                continue
            key, value = option.split("=", 1)
            if key in INTERVENTION_FDW_OPTIONS:
                options[key] = value
        result.append({"server": row.get("server", ""), "options": options})
    return result


def classify_node(node: dict[str, str], payload: dict[str, str]) -> dict[str, Any]:
    settings_rows = json.loads(payload.get("SETTINGS", "[]"))
    settings = {
        row["name"]: {
            "value": row["setting"],
            "unit": row["unit"],
            "source": row["source"],
            "bootValue": row["boot_value"],
            "resetValue": row["reset_value"],
        }
        for row in settings_rows
    }
    fdw_servers = parse_fdw_servers(payload.get("FDW", "[]"))
    tc_text = base64.b64decode(payload.get("TC", "")).decode("utf-8", errors="replace")
    deviations: list[str] = []
    if "netem" in tc_text.lower():
        deviations.append("Aktivno je tc/netem mrežno pravilo.")
    for server in fdw_servers:
        active = sorted(set(server["options"]) & INTERVENTION_FDW_OPTIONS)
        if active:
            deviations.append(
                f"FDW server {server['server']} ima trajne eksperimentalne opcije: {', '.join(active)}."
            )
    return {
        **node,
        "reachable": True,
        "status": "attention" if deviations else "verified",
        "postgresqlSettings": settings,
        "citusVersion": payload.get("CITUS") or "unknown",
        "fdwServers": fdw_servers,
        "network": {"netemActive": "netem" in tc_text.lower(), "summary": tc_text.strip() or "Nema qdisc izlaza."},
        "deviations": deviations,
    }


def probe_node(node: dict[str, str]) -> dict[str, Any]:
    try:
        payload = parse_ansible_payload(run_ansible(node["node_id"], probe_command(node["database"])))
        missing = sorted({"SETTINGS", "CITUS", "FDW", "TC"} - set(payload))
        if missing:
            raise RuntimeError(f"Probe output is incomplete: {', '.join(missing)}")
        return classify_node(node, payload)
    except Exception as exc:  # Preserve a failed node in the audit instead of hiding it.
        return {
            **node,
            "reachable": False,
            "status": "failed",
            "postgresqlSettings": {},
            "citusVersion": "unknown",
            "fdwServers": [],
            "network": {"netemActive": None, "summary": "Nije dostupno."},
            "deviations": [f"Čvor nije potvrđen: {exc}"],
        }


def build_audit(nodes: list[dict[str, Any]], created_at: datetime) -> dict[str, Any]:
    failed = sum(node["status"] == "failed" for node in nodes)
    attention = sum(node["status"] == "attention" for node in nodes)
    status = "failed" if failed else "attention" if attention else "verified"
    regions = sorted({node["region"] for node in nodes if node["layer"] != "gac"})
    return {
        "auditId": created_at.strftime("%Y%m%dT%H%M%SZ"),
        "createdAtUtc": created_at.isoformat().replace("+00:00", "Z"),
        "status": status,
        "topologyLabel": f"GAC + {', '.join(region.upper() for region in regions)}",
        "summary": {
            "nodeCount": len(nodes),
            "verifiedCount": len(nodes) - failed,
            "attentionCount": attention,
            "failedCount": failed,
        },
        "nodes": nodes,
        "interpretation": (
            "Audit je read-only. PostgreSQL vrijednosti prikazuju efektivno stanje i izvor; "
            "odstupanje označava nedostupan čvor, aktivan tc/netem ili trajnu eksperimentalnu FDW opciju."
        ),
    }


def main() -> int:
    args = parse_args()
    created_at = datetime.now(UTC)
    out_dir = (args.out_root / f"{created_at.strftime('%Y%m%dT%H%M%SZ')}-lab-environment").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    audit = build_audit([probe_node(node) for node in load_nodes(args.inventory)], created_at)
    output_path = out_dir / "lab_environment_audit.json"
    output_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output_path)
    return 0 if audit["status"] != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
