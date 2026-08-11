#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_clock() -> str:
    return datetime.now(UTC).strftime("%H:%M:%SZ")


def format_duration(started_at: float) -> str:
    return f"{time.monotonic() - started_at:.1f}s"


def short_path(path_text: str) -> str:
    path = Path(path_text)
    if not path.is_absolute():
        return path_text
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        pass
    try:
        return "../" + str(path.relative_to(REPO_ROOT.parent))
    except ValueError:
        return path_text


def log_event(component: str, message: str) -> None:
    print(f"[{utc_clock()}] [{component}] {message}", flush=True)


def is_prefixed_log_line(value: str) -> bool:
    return value.startswith("[") and "] [" in value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a sequential dataset/config/query collection sweep."
    )
    parser.add_argument("--sweep", type=Path, required=True)
    parser.add_argument("--label", default="")
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "database-sweeps",
    )
    parser.add_argument(
        "--hardware-snapshot-dir",
        type=Path,
        default=None,
        help=(
            "Reuse a hardware snapshot collected by the parent corpus/batch. "
            "Without this option, collect one snapshot for this database sweep."
        ),
    )
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def resolve_path(config_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Path not found: {candidate}")
    for base in (config_path.parent, REPO_ROOT, REPO_ROOT.parent, *config_path.parents):
        resolved = (base / candidate).resolve()
        if resolved.exists():
            return resolved
    raise FileNotFoundError(f"Path not found: {raw_path}")


def run_and_get_path(command: list[str], *, component: str) -> Path:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        output_lines.append(line)
        stripped = line.strip()
        if stripped:
            if stripped.startswith("/"):
                log_event(component, f"artifact -> {short_path(stripped)}")
            elif is_prefixed_log_line(stripped):
                print(stripped, flush=True)
            else:
                log_event(component, stripped)
    returncode = process.wait()
    output = "".join(output_lines)
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, command, output=output)
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped.startswith("/"):
            return Path(stripped)
    raise RuntimeError(f"Unable to parse output path from command: {' '.join(command)}")


def run_and_get_path_allow_failure(
    command: list[str],
    *,
    component: str,
) -> tuple[Path | None, int]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        output_lines.append(line)
        stripped = line.strip()
        if stripped:
            if stripped.startswith("/"):
                log_event(component, f"artifact -> {short_path(stripped)}")
            elif is_prefixed_log_line(stripped):
                print(stripped, flush=True)
            else:
                log_event(component, stripped)
    returncode = process.wait()
    output = "".join(output_lines)
    parsed_path: Path | None = None
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped.startswith("/"):
            parsed_path = Path(stripped)
            break
    return parsed_path, returncode


def index_query_sweep(query_sweep_dir: Path) -> Path:
    master_regimes_project = REPO_ROOT.parent / "master-regimes"
    if not (master_regimes_project / "pyproject.toml").exists():
        raise FileNotFoundError(
            "Cannot index query sweep: sibling master-regimes project not found."
        )
    return run_and_get_path(
        [
            "uv",
            "run",
            "--project",
            str(master_regimes_project),
            "master-regimes",
            "index-query-sweep",
            "--sweep-dir",
            str(query_sweep_dir),
        ],
        component="INDEX",
    )


def index_database_sweep(sweep_dir: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "common-scripts" / "index_database_sweep.py"),
            "--sweep-dir",
            str(sweep_dir),
        ],
        check=True,
    )


def try_index_partial_database_sweep(sweep_dir: Path) -> bool:
    try:
        index_database_sweep(sweep_dir)
    except BaseException as index_error:
        log_event(
            "INDEX",
            f"partial database sweep index failed: {type(index_error).__name__}: {index_error}",
        )
        return False
    log_event(
        "INDEX",
        f"partial database sweep index -> {short_path(str(sweep_dir / '_index'))}",
    )
    return True


def kv_args(flag: str, mapping: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for key, value in mapping.items():
        args.extend([flag, f"{key}={value}"])
    return args


def runtime_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a mapping.")
    return value


def fdw_server_options_for(
    *,
    fdw_bootstrap: dict[str, Any],
    runtime_config: dict[str, Any],
) -> dict[str, Any]:
    base_options = runtime_mapping(
        fdw_bootstrap.get("fdw_server_options", fdw_bootstrap.get("server_options", {})),
        field_name="collection.fdw_bootstrap.fdw_server_options",
    )
    runtime_options = runtime_mapping(
        runtime_config.get("fdw_server_options", {}),
        field_name="runtime_config.fdw_server_options",
    )
    return {**base_options, **runtime_options}


def postgres_fdw_session_options(pg_options: dict[str, Any]) -> str:
    """Encode remote PostgreSQL session settings as a libpq options value."""
    encoded: list[str] = []
    for key, value in sorted(pg_options.items()):
        key_text = str(key).strip()
        value_text = str(value).strip()
        if not key_text or any(char.isspace() for char in key_text):
            raise ValueError(f"Invalid regional PostgreSQL option name: {key!r}")
        if not value_text or any(char.isspace() for char in value_text):
            raise ValueError(
                "Regional PostgreSQL option values used through postgres_fdw "
                f"must not contain whitespace: {key_text}={value_text!r}"
            )
        encoded.extend(["-c", f"{key_text}={value_text}"])
    return " ".join(encoded)


def apply_regional_pg_options_to_fdw(
    fdw_server_options: dict[str, Any],
    regional_pg_options: dict[str, Any],
) -> dict[str, Any]:
    if not regional_pg_options:
        return dict(fdw_server_options)
    result = dict(fdw_server_options)
    remote_options = postgres_fdw_session_options(regional_pg_options)
    existing = str(result.get("options", "")).strip()
    result["options"] = " ".join(value for value in (existing, remote_options) if value)
    return result


def final_database_status(executions: list[dict[str, Any]]) -> str:
    statuses = {str(item.get("query_sweep_status", "")) for item in executions}
    if "completed_with_failures" in statuses or "failed" in statuses:
        return "completed_with_failures"
    if "completed_with_timeouts" in statuses:
        return "completed_with_timeouts"
    return "completed"


def resolve_hardware_snapshot(path: Path) -> tuple[Path, str]:
    snapshot_dir = path.resolve()
    manifest_path = snapshot_dir / "hardware_snapshot_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Shared hardware snapshot manifest not found: {manifest_path}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scope = str(
        (manifest.get("collection_contract") or {}).get("scope")
        or "shared_parent_scope"
    )
    return snapshot_dir, scope


def database_manifest_payload(
    *,
    sweep_id: str,
    timestamp: str,
    status: str,
    sweep_path: Path,
    region: str,
    instance_manifest: Path,
    hardware_snapshot_dir: Path | None,
    hardware_snapshot_scope: str,
    hardware_snapshot_reused: bool,
    execution_policy: dict[str, Any],
    global_stats_scope: str,
    target_group: str,
    target_host: str,
    cache_policy: str,
    order_policy: str,
    shuffle_seed: str,
    hard_timeout_seconds: int,
    citus_explain_all_tasks: bool,
    fdw_auto_explain: bool,
    fdw_bootstrap: dict[str, Any],
    gac_etl_bootstrap: dict[str, Any],
    executions: list[dict[str, Any]],
    error: BaseException | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sweep_id": sweep_id,
        "created_at_utc": timestamp,
        "status": status,
        "source_sweep": str(sweep_path),
        "region": region,
        "instance_manifest": str(instance_manifest),
        "hardware_snapshot_dir": None
        if hardware_snapshot_dir is None
        else str(hardware_snapshot_dir),
        "execution_policy": {
            "dataset_order": "sequential",
            "runtime_config_order": "sequential",
            "query_execution": "sequential",
            "parallel_queries": False,
            "feature_contract": "core_v1",
            "hardware_snapshot_scope": hardware_snapshot_scope,
            "hardware_snapshot_reused": hardware_snapshot_reused,
            "query_level_os_sampling": False,
            "global_stats_scope": global_stats_scope,
            "target_group": target_group,
            "target_host": target_host,
            "cache_policy": cache_policy,
            "order_policy": order_policy,
            "shuffle_seed": shuffle_seed,
            "warmup_per_instance": bool(
                execution_policy.get("warmup_per_instance", False)
            ),
            "explicit_cache_reset": bool(
                execution_policy.get("explicit_cache_reset", False)
            ),
            "repetitions_default": int(
                execution_policy.get("repetitions_default", 1) or 1
            ),
            "cache_features_in_default_model": bool(
                execution_policy.get("cache_features_in_default_model", False)
            ),
            "record_run_order": bool(execution_policy.get("record_run_order", True)),
            "record_buffer_features": bool(
                execution_policy.get("record_buffer_features", True)
            ),
            "preserve_instance_order_across_runtime_configs": bool(
                execution_policy.get(
                    "preserve_instance_order_across_runtime_configs",
                    False,
                )
            ),
            "result_signature": bool(execution_policy.get("result_signature", False)),
            "result_signature_scope": str(
                execution_policy.get(
                    "result_signature_scope",
                    "every_execution",
                )
            ),
            "hard_timeout_seconds": hard_timeout_seconds,
            "timeout_status_policy": (
                "record_and_continue" if hard_timeout_seconds > 0 else "disabled"
            ),
            "citus_explain_all_tasks": citus_explain_all_tasks,
            "fdw_auto_explain": fdw_auto_explain,
            "fdw_bootstrap": fdw_bootstrap,
            "gac_etl_bootstrap": gac_etl_bootstrap,
        },
        "executions": executions,
    }
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)
    return payload


def run_fdw_bootstrap(
    *,
    region: str,
    sweep_label: str,
    dataset_id: str,
    profile_path: Path,
    out_root: Path,
    fdw_bootstrap: dict[str, Any],
    runtime_id: str | None = None,
    fdw_server_options: dict[str, Any] | None = None,
) -> Path:
    effective_region = str(fdw_bootstrap.get("region", region))
    label_parts = [sweep_label, dataset_id]
    if runtime_id:
        label_parts.append(runtime_id)
    label_parts.append(effective_region)
    label_parts.append("fdw")
    default_label = "__".join(label_parts)
    configured_label = str(fdw_bootstrap.get("label", ""))
    adapter = str(fdw_bootstrap.get("adapter", "citus_datagen"))
    if adapter not in {"citus_datagen", "stats_ceb"}:
        raise ValueError(f"Unsupported FDW bootstrap adapter: {adapter}")
    script_name = (
        "run_stats_ceb_fdw_bootstrap.py"
        if adapter == "stats_ceb"
        else "run_gac_fdw_bootstrap.py"
    )
    command = [
        sys.executable,
        str(REPO_ROOT / "common-scripts" / script_name),
        "--label",
        configured_label if configured_label and runtime_id is None else default_label,
        "--region",
        effective_region,
        "--out-root",
        str(out_root),
        *kv_args("--fdw-server-option", fdw_server_options or {}),
    ]
    if adapter == "stats_ceb":
        command.extend(["--profile", str(profile_path)])
    target_host = str(fdw_bootstrap.get("target_host", ""))
    if target_host:
        command.extend(["--target-host", target_host])
    return run_and_get_path(command, component="FDW")


def run_correctness_validation(
    *,
    sweep_path: Path,
    profile_path: Path,
    sweep_label: str,
    dataset_id: str,
    out_root: Path,
    config: dict[str, Any],
) -> Path:
    adapter = str(config.get("adapter", ""))
    if adapter != "stats_ceb":
        raise ValueError(f"Unsupported correctness validation adapter: {adapter}")
    selection_path = resolve_path(sweep_path, str(config["selection"]))
    timeout_seconds = int(config.get("timeout_seconds", 300) or 300)
    return run_and_get_path(
        [
            sys.executable,
            str(REPO_ROOT / "common-scripts" / "validate_stats_ceb_correctness.py"),
            "--profile",
            str(profile_path),
            "--selection",
            str(selection_path),
            "--timeout-seconds",
            str(timeout_seconds),
            "--label",
            f"{sweep_label}__{dataset_id}__correctness",
            "--out-root",
            str(out_root),
        ],
        component="CORRECTNESS",
    )


def filter_instance_manifest_by_correctness(
    *,
    instance_manifest: Path,
    correctness_dir: Path,
    out_path: Path,
) -> tuple[Path, int]:
    result_path = correctness_dir / "result_equivalence.csv"
    with result_path.open("r", encoding="utf-8", newline="") as handle:
        result_rows = list(csv.DictReader(handle))
    passed_ids = {
        int(row["query_id"])
        for row in result_rows
        if row.get("comparison_status") == "passed"
    }
    with instance_manifest.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    selected_rows = []
    for row in rows:
        parameters = json.loads(row.get("param_json") or "{}")
        if int(parameters.get("query_id", -1)) in passed_ids:
            selected_rows.append(row)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected_rows)
    if not selected_rows:
        raise RuntimeError(
            "Correctness filtering left no query instances eligible for collection."
        )
    return out_path, len(selected_rows)


def filter_instance_manifest_by_runtime(
    *,
    instance_manifest: Path,
    runtime_config_id: str,
    out_path: Path,
) -> tuple[Path, int]:
    with instance_manifest.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if "runtime_config_id" not in fieldnames:
        raise ValueError(
            "Runtime-filtered workload requires runtime_config_id in instance manifest"
        )
    selected_rows = [
        row
        for row in rows
        if str(row.get("runtime_config_id", "")) == runtime_config_id
    ]
    if not selected_rows:
        raise RuntimeError(
            f"No query instances selected for runtime_config_id={runtime_config_id}"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected_rows)
    return out_path, len(selected_rows)


def runtime_order_segments(
    *,
    instance_manifest: Path,
    runtime_configs: list[dict[str, Any]],
    out_dir: Path,
    max_instances: int | None = None,
) -> list[tuple[dict[str, Any], Path, int]]:
    """Split a manifest into contiguous runtime segments without reordering rows."""
    with instance_manifest.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if max_instances is not None:
        rows = rows[: int(max_instances)]
    if "runtime_config_id" not in fieldnames:
        raise ValueError(
            "Order-preserving runtime execution requires runtime_config_id in "
            "the instance manifest"
        )
    runtime_by_id = {
        str(runtime.get("id", "runtime")): runtime for runtime in runtime_configs
    }
    if len(runtime_by_id) != len(runtime_configs):
        raise ValueError("Runtime config IDs must be unique")
    segments: list[list[dict[str, str]]] = []
    for row in rows:
        runtime_id = str(row.get("runtime_config_id", ""))
        if runtime_id not in runtime_by_id:
            raise ValueError(
                f"Instance references unknown runtime_config_id={runtime_id!r}"
            )
        if not segments or str(segments[-1][0]["runtime_config_id"]) != runtime_id:
            segments.append([])
        segments[-1].append(row)
    if not segments:
        raise ValueError("Order-preserving runtime execution received an empty manifest")

    out_dir.mkdir(parents=True, exist_ok=True)
    result: list[tuple[dict[str, Any], Path, int]] = []
    for index, segment in enumerate(segments, start=1):
        runtime_id = str(segment[0]["runtime_config_id"])
        path = out_dir / f"segment-{index:04d}__{runtime_id}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(segment)
        result.append((runtime_by_id[runtime_id], path, len(segment)))
    return result


def fdw_bootstrap_regions(*, fdw_bootstrap: dict[str, Any], default_region: str) -> list[str]:
    raw_regions = fdw_bootstrap.get("regions")
    if isinstance(raw_regions, list):
        return [str(region) for region in raw_regions if str(region)]
    if isinstance(raw_regions, str) and raw_regions.strip():
        return [part.strip() for part in raw_regions.split(",") if part.strip()]
    return [str(fdw_bootstrap.get("region", default_region))]


def fdw_bootstrap_for_region(fdw_bootstrap: dict[str, Any], region: str) -> dict[str, Any]:
    result = dict(fdw_bootstrap)
    result["region"] = region
    result.pop("regions", None)
    return result


def dataset_regions(*, dataset: dict[str, Any], default_region: str) -> list[str]:
    raw_regions = dataset.get("regions")
    if isinstance(raw_regions, list):
        return [str(region) for region in raw_regions if str(region)]
    if isinstance(raw_regions, str) and raw_regions.strip():
        return [part.strip() for part in raw_regions.split(",") if part.strip()]
    return [default_region]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_combined_dataset_snapshot(
    *,
    dataset_id: str,
    profile_path: Path,
    load_dirs: list[Path],
    out_path: Path,
) -> Path:
    regional_manifests: list[dict[str, Any]] = []
    for load_dir in load_dirs:
        manifest_path = load_dir / "dataset_load_manifest.json"
        manifest = maybe_load_json(manifest_path)
        regional_manifests.append(
            {
                "manifest_path": str(manifest_path),
                "region": manifest.get("region", ""),
                "dataset_snapshot_id": manifest.get("dataset_snapshot_id", ""),
                "profile_sha256": manifest.get("profile_sha256", ""),
                "datagen_commit": manifest.get("datagen_commit", ""),
                "dataset_seed": manifest.get("dataset_seed", ""),
                "table_counts": manifest.get("table_counts", {}),
                "snapshot_component_hashes": manifest.get(
                    "snapshot_component_hashes",
                    {},
                ),
                "dataset_snapshot_contract": manifest.get(
                    "dataset_snapshot_contract",
                    {
                        "contract_version": "legacy-unspecified",
                        "row_level_checksum_included": False,
                    },
                ),
            }
        )
    payload = {
        "contract_version": "combined-dataset-snapshot-v1",
        "dataset_id": dataset_id,
        "profile": str(profile_path),
        "row_level_checksum_included": False,
        "regions": regional_manifests,
    }
    payload["combined_dataset_snapshot_id"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    write_json(out_path, payload)
    return out_path


def maybe_load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def network_intervention_status(intervention_dir: Path | None) -> str:
    manifest = maybe_load_json(
        None
        if intervention_dir is None
        else intervention_dir / "network_intervention_manifest.json"
    )
    return str(manifest.get("status", ""))


def network_profile_latency(profile: dict[str, Any], key: str) -> Any:
    return profile.get(key, "")


def network_profile_cache_key(profile: dict[str, Any]) -> str:
    measurement_contract = {
        key: value for key, value in profile.items() if key != "id"
    }
    return json.dumps(measurement_contract, sort_keys=True, separators=(",", ":"))


def run_network_intervention(
    *,
    action: str,
    sweep_label: str,
    dataset_id: str,
    runtime_id: str,
    network_profile: dict[str, Any],
    out_root: Path,
    target_host: str,
    allow_failure: bool = False,
) -> Path | None:
    if not network_profile:
        return None
    profile_id = str(network_profile.get("id", "network-profile"))
    label = f"{sweep_label}__{dataset_id}__{runtime_id}__{profile_id}__{action}"
    network_script = (
        "manage_network_pressure.py"
        if network_profile.get("scope") == "region_egress_to_analytics"
        else "manage_network_latency.py"
    )
    command = [
        sys.executable,
        str(REPO_ROOT / "common-scripts" / network_script),
        "--action",
        action,
        "--profile-json",
        json.dumps(network_profile, sort_keys=True),
        "--label",
        label,
        "--out-dir",
        str(out_root),
    ]
    if target_host:
        command.extend(["--target-host", target_host])
    path, returncode = run_and_get_path_allow_failure(command, component="NET")
    if returncode != 0 and not allow_failure:
        raise subprocess.CalledProcessError(returncode, command)
    return path


def run_network_profile_measurement(
    *,
    sweep_label: str,
    dataset_id: str,
    runtime_id: str,
    network_profile: dict[str, Any],
    out_root: Path,
    target_host: str,
) -> Path:
    label = f"{sweep_label}__{dataset_id}__{runtime_id}__measured-network"
    command = [
        sys.executable,
        str(REPO_ROOT / "common-scripts" / "measure_network_profile.py"),
        "--profile-json",
        json.dumps(network_profile, sort_keys=True),
        "--label",
        label,
        "--out-root",
        str(out_root),
    ]
    if target_host:
        command.extend(["--target-host", target_host])
    return run_and_get_path(command, component="NET")


def status_payload(
    *,
    sweep_id: str,
    timestamp: str,
    status: str,
    sweep_path: Path,
    executions: list[dict[str, Any]],
    error: BaseException | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sweep_id": sweep_id,
        "created_at_utc": timestamp,
        "updated_at_utc": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "source_sweep": str(sweep_path),
        "status": status,
        "completed_execution_count": len(executions),
    }
    if executions:
        payload["completed_executions"] = executions
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)
    return payload


def main() -> int:
    args = parse_args()
    sweep_path = args.sweep.resolve()
    sweep = load_yaml(sweep_path)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    sweep_label = args.label or str(sweep.get("sweep_id", "database-sweep"))
    sweep_id = f"{timestamp}-{sweep_label}"
    sweep_dir = (args.out_root / sweep_id).resolve()
    region = str(sweep.get("region", "eu"))
    datasets = sweep.get("datasets", [])
    runtime_configs = sweep.get("runtime_configs", [])
    workload = sweep.get("workload", {})
    collection = sweep.get("collection", {})
    execution_policy = sweep.get("execution_policy", {}) or {}
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("Sweep must define non-empty datasets list.")
    if not isinstance(runtime_configs, list) or not runtime_configs:
        raise ValueError("Sweep must define non-empty runtime_configs list.")
    if not isinstance(workload, dict) or "instance_manifest" not in workload:
        raise ValueError("Sweep must define workload.instance_manifest.")
    if not isinstance(collection, dict):
        raise ValueError("Sweep collection section must be a mapping when provided.")
    if not isinstance(execution_policy, dict):
        raise ValueError("Sweep execution_policy section must be a mapping when provided.")

    instance_manifest = resolve_path(sweep_path, str(workload["instance_manifest"]))
    max_instances = workload.get("max_instances")
    global_stats_scope = str(collection.get("global_stats_scope", "none"))
    if global_stats_scope not in {"sweep", "query", "none"}:
        raise ValueError("collection.global_stats_scope must be one of: sweep, query, none.")
    target_group = str(collection.get("target_group", "coordinators"))
    target_host = str(collection.get("target_host", ""))
    cache_policy = str(
        collection.get("cache_policy")
        or execution_policy.get("cache_policy")
        or "mixed_cache_first_observed"
    )
    order_policy = str(workload.get("order_policy") or execution_policy.get("order_policy") or "")
    shuffle_seed = str(workload.get("shuffle_seed") or execution_policy.get("shuffle_seed") or "")
    hard_timeout_seconds = int(collection.get("hard_timeout_seconds", 0) or 0)
    timeout_grace_seconds = int(collection.get("timeout_grace_seconds", 30) or 30)
    citus_explain_all_tasks = bool(collection.get("citus_explain_all_tasks", True))
    fdw_auto_explain = bool(collection.get("fdw_auto_explain", False))
    fdw_auto_explain_regions_raw = collection.get("fdw_auto_explain_regions", []) or []
    if not isinstance(fdw_auto_explain_regions_raw, list):
        raise ValueError("collection.fdw_auto_explain_regions must be a list.")
    fdw_auto_explain_regions = [
        str(fdw_region).strip().lower()
        for fdw_region in fdw_auto_explain_regions_raw
        if str(fdw_region).strip()
    ]
    os_sampler = bool(collection.get("os_sampler", False))
    os_sampler_node_groups_raw = collection.get("os_sampler_node_groups", []) or []
    if not isinstance(os_sampler_node_groups_raw, list):
        raise ValueError("collection.os_sampler_node_groups must be a list.")
    os_sampler_node_groups = [
        str(group).strip()
        for group in os_sampler_node_groups_raw
        if str(group).strip()
    ]
    result_signature = bool(collection.get("result_signature", False))
    result_snapshot_only = bool(collection.get("result_snapshot_only", False))
    result_snapshot_max_rows = int(
        collection.get("result_snapshot_max_rows", 100) or 100
    )
    result_snapshot_max_bytes = int(
        collection.get("result_snapshot_max_bytes", 10 * 1024 * 1024)
        or 10 * 1024 * 1024
    )
    result_signature_scope = str(
        collection.get("result_signature_scope", "every_execution")
    )
    if result_signature_scope not in {
        "every_execution",
        "first_repetition_per_condition",
    }:
        raise ValueError(
            "collection.result_signature_scope must be every_execution or "
            "first_repetition_per_condition."
        )
    network_profile_probe = bool(collection.get("network_profile_probe", False))
    remote_edge_context = bool(collection.get("remote_edge_context", False))
    if result_snapshot_only and any(
        (result_signature, fdw_auto_explain, os_sampler, remote_edge_context)
    ):
        raise ValueError(
            "collection.result_snapshot_only cannot be combined with collector instrumentation"
        )
    if result_snapshot_only and global_stats_scope != "none":
        raise ValueError(
            "collection.result_snapshot_only requires global_stats_scope=none"
        )
    fdw_bootstrap = collection.get("fdw_bootstrap", {}) or {}
    gac_etl_bootstrap = collection.get("gac_etl_bootstrap", {}) or {}
    correctness_validation = collection.get("correctness_validation", {}) or {}
    if (
        not isinstance(fdw_bootstrap, dict)
        or not isinstance(gac_etl_bootstrap, dict)
        or not isinstance(correctness_validation, dict)
    ):
        raise ValueError(
            "collection fdw_bootstrap, gac_etl_bootstrap and "
            "correctness_validation must be mappings."
        )
    executions: list[dict[str, Any]] = []
    network_measurement_cache: dict[str, Path] = {}
    hardware_snapshot_dir: Path | None = None
    hardware_snapshot_scope = "database_sweep_global"
    hardware_snapshot_reused = False
    status_file = sweep_dir / "database_sweep_status.json"
    log_event(
        "DB",
        (
            f"start sweep_id={sweep_id} datasets={len(datasets)} "
            f"runtime_configs={len(runtime_configs)} target_group={target_group}"
        ),
    )
    log_event("DB", f"artifacts -> {short_path(str(sweep_dir))}")
    write_json(
        status_file,
        status_payload(
            sweep_id=sweep_id,
            timestamp=timestamp,
            status="running",
            sweep_path=sweep_path,
            executions=executions,
        ),
    )

    try:
        if args.hardware_snapshot_dir is not None:
            hardware_snapshot_dir, hardware_snapshot_scope = (
                resolve_hardware_snapshot(args.hardware_snapshot_dir)
            )
            hardware_snapshot_reused = True
            log_event(
                "DB",
                (
                    "hardware snapshot reused "
                    f"scope={hardware_snapshot_scope} "
                    f"artifact={short_path(str(hardware_snapshot_dir))}"
                ),
            )
        else:
            hardware_started_at = time.monotonic()
            log_event("DB", "hardware snapshot start scope=database_sweep_global")
            hardware_snapshot_dir = run_and_get_path(
                [
                    sys.executable,
                    str(REPO_ROOT / "common-scripts" / "collect_hardware_snapshot.py"),
                    "--label",
                    f"{sweep_id}-hardware",
                    "--scope",
                    "database_sweep_global",
                    "--out-root",
                    str(sweep_dir / "hardware-snapshots"),
                ],
                component="HW",
            )
            log_event(
                "DB",
                f"hardware snapshot done in {format_duration(hardware_started_at)}",
            )

        for dataset_index, dataset in enumerate(datasets, start=1):
            if not isinstance(dataset, dict):
                raise ValueError("Each dataset entry must be a mapping.")
            dataset_id = str(dataset.get("id", "dataset"))
            profile_path = resolve_path(sweep_path, str(dataset["profile"]))
            dataset_adapter = str(dataset.get("adapter", "citus_datagen"))
            if dataset_adapter not in {"citus_datagen", "stats_ceb"}:
                raise ValueError(f"Unsupported dataset adapter: {dataset_adapter}")
            log_event(
                "DB",
                f"dataset {dataset_index}/{len(datasets)} start id={dataset_id}",
            )
            dataset_load_dirs: list[Path] = []
            regions_for_dataset = dataset_regions(dataset=dataset, default_region=region)
            for region_index, dataset_region in enumerate(regions_for_dataset, start=1):
                load_started_at = time.monotonic()
                log_event(
                    "DATASET",
                    (
                        f"load {region_index}/{len(regions_for_dataset)} "
                        f"dataset={dataset_id} region={dataset_region}"
                    ),
                )
                dataset_command = [
                    sys.executable,
                    str(
                        REPO_ROOT
                        / "common-scripts"
                        / (
                            "apply_stats_ceb_profile.py"
                            if dataset_adapter == "stats_ceb"
                            else "apply_dataset_profile.py"
                        )
                    ),
                    "--profile",
                    str(profile_path),
                    "--region",
                    dataset_region,
                    "--out-root",
                    str(sweep_dir / "dataset-loads"),
                ]
                if dataset_adapter == "citus_datagen":
                    dataset_command.extend(
                        ["--load-method", str(dataset.get("load_method", "sql"))]
                    )
                dataset_load_dirs.append(
                    run_and_get_path(dataset_command, component="DATASET")
                )
                log_event(
                    "DATASET",
                    (
                        f"done dataset={dataset_id} region={dataset_region} "
                        f"in {format_duration(load_started_at)}"
                    ),
                )
            dataset_snapshot_manifest = write_combined_dataset_snapshot(
                dataset_id=dataset_id,
                profile_path=profile_path,
                load_dirs=dataset_load_dirs,
                out_path=(
                    sweep_dir
                    / "dataset-snapshots"
                    / f"{dataset_id}.dataset-snapshot.json"
                ),
            )
            fdw_bootstrap_dirs: list[Path] = []
            gac_etl_bootstrap_dir: Path | None = None
            if fdw_bootstrap.get("enabled", False):
                fdw_regions = fdw_bootstrap_regions(
                    fdw_bootstrap=fdw_bootstrap,
                    default_region=region,
                )
                for fdw_index, fdw_region in enumerate(fdw_regions, start=1):
                    log_event(
                        "FDW",
                        (
                            f"bootstrap {fdw_index}/{len(fdw_regions)} "
                            f"dataset={dataset_id} region={fdw_region}"
                        ),
                    )
                    regional_fdw_bootstrap = fdw_bootstrap_for_region(
                        fdw_bootstrap,
                        fdw_region,
                    )
                    fdw_bootstrap_dirs.append(
                        run_fdw_bootstrap(
                            region=fdw_region,
                            sweep_label=sweep_label,
                            dataset_id=dataset_id,
                            profile_path=profile_path,
                            out_root=sweep_dir / "fdw-bootstrap",
                            fdw_bootstrap=regional_fdw_bootstrap,
                            fdw_server_options=fdw_server_options_for(
                                fdw_bootstrap=regional_fdw_bootstrap,
                                runtime_config={},
                            ),
                        )
                    )
            correctness_validation_dir: Path | None = None
            effective_instance_manifest = instance_manifest
            if correctness_validation.get("enabled", False):
                validation_started_at = time.monotonic()
                log_event("CORRECTNESS", f"validation start dataset={dataset_id}")
                correctness_validation_dir = run_correctness_validation(
                    sweep_path=sweep_path,
                    profile_path=profile_path,
                    sweep_label=sweep_label,
                    dataset_id=dataset_id,
                    out_root=sweep_dir / "result-validation",
                    config=correctness_validation,
                )
                log_event(
                    "CORRECTNESS",
                    (
                        f"validation done dataset={dataset_id} "
                        f"in {format_duration(validation_started_at)}"
                    ),
                )
                if correctness_validation.get("filter_workload_to_passed", False):
                    effective_instance_manifest, eligible_count = (
                        filter_instance_manifest_by_correctness(
                            instance_manifest=instance_manifest,
                            correctness_dir=correctness_validation_dir,
                            out_path=(
                                correctness_validation_dir
                                / "eligible_instance_manifest.csv"
                            ),
                        )
                    )
                    log_event(
                        "CORRECTNESS",
                        (
                            f"collector eligibility dataset={dataset_id} "
                            f"passed={eligible_count}"
                        ),
                    )
            if gac_etl_bootstrap.get("enabled", False):
                etl_started_at = time.monotonic()
                log_event("ETL", f"bootstrap start dataset={dataset_id}")
                gac_etl_bootstrap_dir = run_and_get_path(
                    [
                        sys.executable,
                        str(REPO_ROOT / "common-scripts" / "run_gac_etl_bootstrap.py"),
                        "--label",
                        str(
                            gac_etl_bootstrap.get(
                                "label", f"{sweep_label}__{dataset_id}__gac-etl"
                            )
                        ),
                        "--region",
                        str(gac_etl_bootstrap.get("region", region)),
                        "--lookback-days",
                        str(gac_etl_bootstrap.get("lookback_days", 30)),
                        *(
                            ["--timeout-seconds", str(gac_etl_bootstrap.get("timeout_seconds"))]
                            if int(gac_etl_bootstrap.get("timeout_seconds", 0) or 0) > 0
                            else []
                        ),
                        *(
                            [
                                "--timeout-grace-seconds",
                                str(gac_etl_bootstrap.get("timeout_grace_seconds", 30)),
                            ]
                            if int(gac_etl_bootstrap.get("timeout_seconds", 0) or 0) > 0
                            else []
                        ),
                        "--out-root",
                        str(sweep_dir / "gac-etl-bootstrap"),
                    ],
                    component="ETL",
                )
                log_event("ETL", f"bootstrap done in {format_duration(etl_started_at)}")

            preserve_runtime_order = bool(
                execution_policy.get(
                    "preserve_instance_order_across_runtime_configs",
                    False,
                )
            )
            if preserve_runtime_order:
                runtime_steps = runtime_order_segments(
                    instance_manifest=effective_instance_manifest,
                    runtime_configs=runtime_configs,
                    out_dir=(
                        sweep_dir
                        / "runtime-instance-manifests"
                        / dataset_id
                        / "ordered-segments"
                    ),
                    max_instances=(int(max_instances) if max_instances is not None else None),
                )
                log_event(
                    "QUERY",
                    (
                        f"preserving global instance order across "
                        f"runtime_segments={len(runtime_steps)}"
                    ),
                )
            else:
                runtime_steps = [
                    (runtime_config, effective_instance_manifest, -1)
                    for runtime_config in runtime_configs
                ]

            for runtime_index, (
                runtime_config,
                ordered_runtime_manifest,
                ordered_runtime_count,
            ) in enumerate(runtime_steps, start=1):
                if not isinstance(runtime_config, dict):
                    raise ValueError("Each runtime_config entry must be a mapping.")
                runtime_id = str(runtime_config.get("id", "runtime"))
                runtime_instance_manifest = ordered_runtime_manifest
                if preserve_runtime_order:
                    runtime_instance_count = ordered_runtime_count
                    log_event(
                        "QUERY",
                        (
                            f"runtime segment {runtime_index}/{len(runtime_steps)} "
                            f"dataset={dataset_id} runtime={runtime_id} "
                            f"instances={runtime_instance_count}"
                        ),
                    )
                elif bool(workload.get("filter_instances_by_runtime_config", False)):
                    runtime_instance_manifest, runtime_instance_count = (
                        filter_instance_manifest_by_runtime(
                            instance_manifest=effective_instance_manifest,
                            runtime_config_id=runtime_id,
                            out_path=(
                                sweep_dir
                                / "runtime-instance-manifests"
                                / dataset_id
                                / f"{runtime_id}.csv"
                            ),
                        )
                    )
                    log_event(
                        "QUERY",
                        (
                            f"runtime selection dataset={dataset_id} "
                            f"runtime={runtime_id} instances={runtime_instance_count}"
                        ),
                    )
                runtime_started_at = time.monotonic()
                log_event(
                    "DB",
                    (
                        f"runtime {runtime_index}/{len(runtime_steps)} start "
                        f"dataset={dataset_id} runtime={runtime_id}"
                    ),
                )
                pg_options = runtime_mapping(
                    runtime_config.get("pg_options", {}),
                    field_name="runtime_config.pg_options",
                )
                regional_pg_options = runtime_mapping(
                    runtime_config.get("regional_pg_options", {}),
                    field_name="runtime_config.regional_pg_options",
                )
                if target_group != "analytics_clients" and regional_pg_options:
                    pg_options = {**pg_options, **regional_pg_options}
                psql_variables = runtime_mapping(
                    runtime_config.get("psql_variables", {}),
                    field_name="runtime_config.psql_variables",
                )
                fdw_server_options = fdw_server_options_for(
                    fdw_bootstrap=fdw_bootstrap,
                    runtime_config=runtime_config,
                )
                if target_group == "analytics_clients":
                    fdw_server_options = apply_regional_pg_options_to_fdw(
                        fdw_server_options,
                        regional_pg_options,
                    )
                network_profile = runtime_mapping(
                    runtime_config.get("network_profile", {}),
                    field_name="runtime_config.network_profile",
                )
                runtime_intervention_axis = str(runtime_config.get("intervention_axis", ""))
                runtime_expected_effect = str(runtime_config.get("expected_effect", ""))
                effective_fdw_bootstrap_dirs = list(fdw_bootstrap_dirs)
                if fdw_bootstrap.get("enabled", False) and (
                    runtime_config.get("fdw_server_options")
                    or (
                        target_group == "analytics_clients"
                        and regional_pg_options
                    )
                ):
                    effective_fdw_bootstrap_dirs = []
                    fdw_regions = fdw_bootstrap_regions(
                        fdw_bootstrap=fdw_bootstrap,
                        default_region=region,
                    )
                    for fdw_index, fdw_region in enumerate(fdw_regions, start=1):
                        log_event(
                            "FDW",
                            (
                                f"runtime bootstrap {fdw_index}/{len(fdw_regions)} "
                                f"dataset={dataset_id} runtime={runtime_id} "
                                f"region={fdw_region}"
                            ),
                        )
                        regional_fdw_bootstrap = fdw_bootstrap_for_region(
                            fdw_bootstrap,
                            fdw_region,
                        )
                        effective_fdw_bootstrap_dirs.append(
                            run_fdw_bootstrap(
                                region=fdw_region,
                                sweep_label=sweep_label,
                                dataset_id=dataset_id,
                                profile_path=profile_path,
                                runtime_id=runtime_id,
                                out_root=sweep_dir / "fdw-bootstrap",
                                fdw_bootstrap=regional_fdw_bootstrap,
                                fdw_server_options=fdw_server_options,
                            )
                        )
                network_apply_dir: Path | None = None
                network_reset_dir: Path | None = None
                network_apply_status = ""
                network_reset_status = ""
                network_measurement_dir: Path | None = None
                network_measurement_reused = False
                try:
                    if network_profile:
                        net_started_at = time.monotonic()
                        log_event(
                            "NET",
                            (
                                f"apply start dataset={dataset_id} runtime={runtime_id} "
                                f"profile={network_profile.get('id', '')}"
                            ),
                        )
                        network_apply_dir = run_network_intervention(
                            action="apply",
                            sweep_label=sweep_label,
                            dataset_id=dataset_id,
                            runtime_id=runtime_id,
                            network_profile=network_profile,
                            out_root=sweep_dir / "network-interventions",
                            target_host=target_host,
                        )
                        network_apply_status = network_intervention_status(
                            network_apply_dir
                        )
                        if network_profile_probe:
                            measurement_key = network_profile_cache_key(network_profile)
                            network_measurement_dir = network_measurement_cache.get(
                                measurement_key
                            )
                            if network_measurement_dir is None:
                                network_measurement_dir = run_network_profile_measurement(
                                    sweep_label=sweep_label,
                                    dataset_id=dataset_id,
                                    runtime_id=runtime_id,
                                    network_profile=network_profile,
                                    out_root=sweep_dir / "network-measurements",
                                    target_host=target_host,
                                )
                                network_measurement_cache[measurement_key] = (
                                    network_measurement_dir
                                )
                            else:
                                network_measurement_reused = True
                                log_event(
                                    "NET",
                                    (
                                        f"measurement reused runtime={runtime_id} "
                                        f"profile={network_profile.get('id', '')}"
                                    ),
                                )
                        log_event(
                            "NET",
                            (
                                f"apply done dataset={dataset_id} runtime={runtime_id} "
                                f"status={network_apply_status} "
                                f"in {format_duration(net_started_at)}"
                            ),
                        )
                    log_event(
                        "QUERY",
                        f"sweep start dataset={dataset_id} runtime={runtime_id}",
                    )
                    query_sweep_dir = run_and_get_path(
                        [
                            sys.executable,
                            str(REPO_ROOT / "common-scripts" / "run_query_collection_sweep.py"),
                            "--instance-manifest",
                            str(runtime_instance_manifest),
                            "--label",
                            f"{sweep_label}__{dataset_id}__{runtime_id}",
                            "--out-root",
                            str(sweep_dir / "query-sweeps"),
                            *(
                                ["--max-instances", str(max_instances)]
                                if max_instances is not None and not preserve_runtime_order
                                else []
                            ),
                            "--global-stats-scope",
                            global_stats_scope,
                            "--target-group",
                            target_group,
                            "--cache-policy",
                            cache_policy,
                            *(["--order-policy", order_policy] if order_policy else []),
                            *(["--shuffle-seed", shuffle_seed] if shuffle_seed else []),
                            *(["--target-host", target_host] if target_host else []),
                            *(
                                ["--hard-timeout-seconds", str(hard_timeout_seconds)]
                                if hard_timeout_seconds > 0
                                else []
                            ),
                            *(
                                ["--timeout-grace-seconds", str(timeout_grace_seconds)]
                                if hard_timeout_seconds > 0
                                else []
                            ),
                            *(["--fdw-auto-explain"] if fdw_auto_explain else []),
                            *(
                                item
                                for fdw_region in fdw_auto_explain_regions
                                for item in ("--fdw-auto-explain-region", fdw_region)
                            ),
                            *(["--os-sampler"] if os_sampler else []),
                            *(
                                item
                                for group in os_sampler_node_groups
                                for item in ("--os-sampler-node-group", group)
                            ),
                            *(["--result-signature"] if result_signature else []),
                            *(
                                ["--result-signature-scope", result_signature_scope]
                                if result_signature
                                else []
                            ),
                            *(
                                [
                                    "--result-snapshot-only",
                                    "--result-snapshot-max-rows",
                                    str(result_snapshot_max_rows),
                                    "--result-snapshot-max-bytes",
                                    str(result_snapshot_max_bytes),
                                ]
                                if result_snapshot_only
                                else []
                            ),
                            *(["--remote-edge-context"] if remote_edge_context else []),
                            "--execution-metadata-json",
                            json.dumps(
                                {
                                    "runtime_expected_effect": runtime_expected_effect,
                                    "work_mem": pg_options.get("work_mem", ""),
                                    "fetch_size": fdw_server_options.get(
                                        "fetch_size", ""
                                    ),
                                    "pg_options_json": json.dumps(
                                        pg_options, sort_keys=True
                                    ),
                                    "regional_pg_options_json": json.dumps(
                                        regional_pg_options, sort_keys=True
                                    ),
                                    "psql_variables_json": json.dumps(
                                        psql_variables, sort_keys=True
                                    ),
                                    "fdw_server_options_json": json.dumps(
                                        fdw_server_options, sort_keys=True
                                    ),
                                    "network_profile_json": json.dumps(
                                        network_profile, sort_keys=True
                                    ),
                                    "network_profile_id": network_profile.get(
                                        "id", ""
                                    ),
                                    "configured_latency_ms": network_profile_latency(
                                        network_profile, "configured_delay_ms"
                                    ),
                                    "configured_jitter_ms": network_profile_latency(
                                        network_profile, "configured_jitter_ms"
                                    ),
                                    "configured_loss_percent": network_profile_latency(
                                        network_profile,
                                        "configured_loss_percent",
                                    ),
                                    "configured_bandwidth_mbit": network_profile_latency(
                                        network_profile,
                                        "configured_bandwidth_mbit",
                                    ),
                                },
                                sort_keys=True,
                            ),
                            *(
                                [
                                    "--checkpoint-file",
                                    os.environ["PRESSURE_RAW_CHECKPOINT_FILE"],
                                ]
                                if os.environ.get("PRESSURE_RAW_CHECKPOINT_FILE")
                                else []
                            ),
                            *(
                                []
                                if citus_explain_all_tasks
                                else ["--no-citus-explain-all-tasks"]
                            ),
                            *kv_args("--pg-option", pg_options),
                            *kv_args("--var", psql_variables),
                        ],
                        component="QUERY",
                    )
                finally:
                    if network_profile:
                        reset_started_at = time.monotonic()
                        log_event(
                            "NET",
                            (
                                f"reset start dataset={dataset_id} runtime={runtime_id} "
                                f"profile={network_profile.get('id', '')}"
                            ),
                        )
                        network_reset_dir = run_network_intervention(
                            action="reset",
                            sweep_label=sweep_label,
                            dataset_id=dataset_id,
                            runtime_id=runtime_id,
                            network_profile=network_profile,
                            out_root=sweep_dir / "network-interventions",
                            target_host=target_host,
                            allow_failure=True,
                        )
                        network_reset_status = network_intervention_status(
                            network_reset_dir
                        )
                        log_event(
                            "NET",
                            (
                                f"reset done dataset={dataset_id} runtime={runtime_id} "
                                f"status={network_reset_status} "
                                f"in {format_duration(reset_started_at)}"
                            ),
                        )
                query_sweep_manifest = load_yaml(
                    query_sweep_dir / "query_sweep_manifest.json"
                )
                query_sweep_index_dir: Path | None = None
                if not result_snapshot_only:
                    log_event(
                        "INDEX",
                        f"query sweep index start {short_path(str(query_sweep_dir))}",
                    )
                    query_sweep_index_dir = index_query_sweep(query_sweep_dir)
                log_event(
                    "DB",
                    (
                        f"runtime {runtime_index}/{len(runtime_steps)} done "
                        f"dataset={dataset_id} runtime={runtime_id} "
                        f"status={query_sweep_manifest.get('status', '')} "
                        f"in {format_duration(runtime_started_at)}"
                    ),
                )
                executions.append(
                    {
                        "dataset_id": dataset_id,
                        "dataset_profile": str(profile_path),
                        "dataset_adapter": dataset_adapter,
                        "dataset_regions": dataset_regions(
                            dataset=dataset,
                            default_region=region,
                        ),
                        "dataset_load_dir": (
                            None if not dataset_load_dirs else str(dataset_load_dirs[0])
                        ),
                        "dataset_load_dirs": [str(path) for path in dataset_load_dirs],
                        "dataset_snapshot_manifest": str(dataset_snapshot_manifest),
                        "fdw_bootstrap_dir": (
                            None
                            if not effective_fdw_bootstrap_dirs
                            else str(effective_fdw_bootstrap_dirs[0])
                        ),
                        "fdw_bootstrap_dirs": [
                            str(path) for path in effective_fdw_bootstrap_dirs
                        ],
                        "gac_etl_bootstrap_dir": (
                            None
                            if gac_etl_bootstrap_dir is None
                            else str(gac_etl_bootstrap_dir)
                        ),
                        "correctness_validation_dir": (
                            None
                            if correctness_validation_dir is None
                            else str(correctness_validation_dir)
                        ),
                        "effective_instance_manifest": str(
                            runtime_instance_manifest
                        ),
                        "runtime_config_id": runtime_id,
                        "runtime_intervention_axis": runtime_intervention_axis,
                        "runtime_expected_effect": runtime_expected_effect,
                        "pg_options": pg_options,
                        "regional_pg_options": regional_pg_options,
                        "psql_variables": psql_variables,
                        "fdw_server_options": fdw_server_options,
                        "network_profile": network_profile,
                        "network_profile_id": network_profile.get("id", ""),
                        "network_intervention_scope": network_profile.get("scope", ""),
                        "configured_latency_ms": network_profile_latency(
                            network_profile, "configured_delay_ms"
                        ),
                        "configured_jitter_ms": network_profile_latency(
                            network_profile, "configured_jitter_ms"
                        ),
                        "configured_loss_percent": network_profile_latency(
                            network_profile, "configured_loss_percent"
                        ),
                        "configured_bandwidth_mbit": network_profile_latency(
                            network_profile, "configured_bandwidth_mbit"
                        ),
                        "network_intervention_apply_dir": (
                            None if network_apply_dir is None else str(network_apply_dir)
                        ),
                        "network_intervention_reset_dir": (
                            None if network_reset_dir is None else str(network_reset_dir)
                        ),
                        "network_measurement_dir": (
                            "" if network_measurement_dir is None else str(network_measurement_dir)
                        ),
                        "network_measurement_reused": network_measurement_reused,
                        "network_intervention_apply_status": network_apply_status,
                        "network_intervention_reset_status": network_reset_status,
                        "query_sweep_dir": str(query_sweep_dir),
                        "query_sweep_index_dir": (
                            ""
                            if query_sweep_index_dir is None
                            else str(query_sweep_index_dir)
                        ),
                        "query_sweep_status": query_sweep_manifest.get("status", ""),
                        "query_count_by_status": query_sweep_manifest.get(
                            "query_count_by_status", {}
                        ),
                    }
                )
                write_json(
                    status_file,
                    status_payload(
                        sweep_id=sweep_id,
                        timestamp=timestamp,
                        status="running",
                        sweep_path=sweep_path,
                        executions=executions,
                    ),
                )

        write_json(
            sweep_dir / "database_sweep_manifest.json",
            database_manifest_payload(
                sweep_id=sweep_id,
                timestamp=timestamp,
                status=final_database_status(executions),
                sweep_path=sweep_path,
                region=region,
                instance_manifest=instance_manifest,
                hardware_snapshot_dir=hardware_snapshot_dir,
                hardware_snapshot_scope=hardware_snapshot_scope,
                hardware_snapshot_reused=hardware_snapshot_reused,
                execution_policy=execution_policy,
                global_stats_scope=global_stats_scope,
                target_group=target_group,
                target_host=target_host,
                cache_policy=cache_policy,
                order_policy=order_policy,
                shuffle_seed=shuffle_seed,
                hard_timeout_seconds=hard_timeout_seconds,
                citus_explain_all_tasks=citus_explain_all_tasks,
                fdw_auto_explain=fdw_auto_explain,
                fdw_bootstrap=fdw_bootstrap,
                gac_etl_bootstrap=gac_etl_bootstrap,
                executions=executions,
            ),
        )
        if not result_snapshot_only:
            index_database_sweep(sweep_dir)
    except BaseException as exc:
        write_json(
            status_file,
            status_payload(
                sweep_id=sweep_id,
                timestamp=timestamp,
                status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                sweep_path=sweep_path,
                executions=executions,
                error=exc,
            ),
        )
        write_json(
            sweep_dir / "database_sweep_manifest.json",
            database_manifest_payload(
                sweep_id=sweep_id,
                timestamp=timestamp,
                status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                sweep_path=sweep_path,
                region=region,
                instance_manifest=instance_manifest,
                hardware_snapshot_dir=hardware_snapshot_dir,
                hardware_snapshot_scope=hardware_snapshot_scope,
                hardware_snapshot_reused=hardware_snapshot_reused,
                execution_policy=execution_policy,
                global_stats_scope=global_stats_scope,
                target_group=target_group,
                target_host=target_host,
                cache_policy=cache_policy,
                order_policy=order_policy,
                shuffle_seed=shuffle_seed,
                hard_timeout_seconds=hard_timeout_seconds,
                citus_explain_all_tasks=citus_explain_all_tasks,
                fdw_auto_explain=fdw_auto_explain,
                fdw_bootstrap=fdw_bootstrap,
                gac_etl_bootstrap=gac_etl_bootstrap,
                executions=executions,
                error=exc,
            ),
        )
        if executions and not result_snapshot_only:
            try_index_partial_database_sweep(sweep_dir)
        raise

    write_json(
        status_file,
        status_payload(
            sweep_id=sweep_id,
            timestamp=timestamp,
            status=(
                final_database_status(executions)
            ),
            sweep_path=sweep_path,
            executions=executions,
        ),
    )
    print(str(sweep_dir), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
