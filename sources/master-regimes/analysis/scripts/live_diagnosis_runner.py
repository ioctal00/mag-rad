from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from master_regimes.pressure_evidence import build_pressure_evidence, build_pressure_thresholds
from master_regimes.regime_interpretation import (
    REGIME_COLORS,
    assess_ambiguity,
    macro_family_summary,
    mechanism_tags,
    pushdown_component_statuses,
    regime_meta_for_cluster,
    semantic_v2_membership_rows,
    semantic_v2_prototype_meta_for_cluster,
    spill_location_evidence,
)
from master_regimes.representation_audit import (
    memberships_from_centers,
    semantic_transform,
)
from master_regimes.runtime_config import load_runtime_config_specs, validate_runtime_config_specs

ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ROOT.parent / "master-regimes-infra"
TRAINING_FEATURE_DIR = ROOT / "analysis/features/clean-run-v1-flow-ratio-v3/phase1_compact"
FUZZY_DIR = ROOT / "analysis/reports/clean-run-v1-m0-flow-ratio-v3-reduced-fuzzy"
FINAL_MODEL_MANIFEST = ROOT / "analysis/reports/clean-run-v1-final-model/final_model_manifest.yml"
SEMANTIC_CONTRACT = ROOT / "configs/features/feature_semantic_contract_v2.yml"
SEMANTIC_AUDIT_DIR = ROOT / "analysis/reports/feature-semantic-contract-v2"
SEMANTIC_MODEL_DIR = ROOT / "analysis/reports/semantic-v2-model-freeze"
OUT_ROOT = ROOT / "generated/live-diagnosis"
UV_BIN = os.environ.get("UV_BIN", "uv")
RUNTIME_CATALOG_MANIFEST = ROOT / "workloads" / "corpus" / "runtime-configs.yml"
LIVE_SUPPORTED_RUNTIME_AXES = {
    "none",
    "work_mem",
    "join_order",
    "planner_operator",
    "parallelism",
    "jit",
}
DEFAULT_LIVE_DATASET_ID = "pilot-region-local-skew-asymmetric-medium-v1"

STEP_TEMPLATE = [
    ("sql_capture", "SQL prihvaćen"),
    ("query_collection", "EXPLAIN ANALYZE i artefakti izvršenja"),
    ("remote_plan_collection", "regionalni FDW/auto_explain planovi"),
    ("indexing", "normalizovani _index"),
    ("feature_extraction", "izdvajanje pokazatelja"),
    ("inference", "fuzzy poređenje s prototipima"),
]


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.parent.resolve()))
    except ValueError:
        return path.name


def log(message: str) -> None:
    print(f"[live-diagnosis] {message}", file=sys.stderr, flush=True)


def elapsed_since(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 3)


def seconds_label(seconds: float | int | None) -> str:
    if seconds is None:
        return "n/a"
    numeric = float(seconds)
    if numeric < 1:
        return f"{numeric:.2f}s"
    if numeric < 10:
        return f"{numeric:.1f}s"
    return f"{numeric:.0f}s"


def read_only_sql(sql: str) -> bool:
    stripped = re.sub(r";+\s*$", "", sql.strip())
    if not re.match(r"^(select|with|explain)\b", stripped, flags=re.IGNORECASE):
        return False
    forbidden = (
        r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|"
        r"vacuum|analyze)\b"
    )
    return re.search(forbidden, stripped, flags=re.IGNORECASE) is None


def safe_component(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-_")
    return result[:120] or "manual-sql"


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def json_text(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True, ensure_ascii=False)


def kv_args(flag: str, values: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for key, value in sorted((values or {}).items()):
        args.extend([flag, f"{key}={value}"])
    return args


def resolve_runtime_config(runtime_config_id: str) -> tuple[str, dict[str, Any]]:
    requested_id = "default" if runtime_config_id in {"", "live-default"} else runtime_config_id
    manifest = {"runtime_catalog": "runtime-configs.yml"}
    specs = load_runtime_config_specs(
        manifest_path=RUNTIME_CATALOG_MANIFEST,
        manifest=manifest,
    )
    errors = validate_runtime_config_specs(specs)
    if errors:
        raise ValueError("Katalog konfiguracija izvršavanja nije validan: " + ", ".join(errors))
    if requested_id not in specs:
        known = ", ".join(sorted(specs))
        raise ValueError(f"Nepoznat runtime_config_id={runtime_config_id}. Poznato: {known}")
    spec = specs[requested_id]
    if not spec.get("enabled", True):
        raise ValueError(f"Runtime config nije omogućen: {requested_id}")
    axis = str(spec.get("intervention_axis", "none"))
    if axis not in LIVE_SUPPORTED_RUNTIME_AXES:
        raise ValueError(
            f"Runtime config {requested_id} nije podržan u live dijagnostici. "
            "Live trenutno može primijeniti samo allowlisted session PostgreSQL opcije. "
            "fetch_size zahtijeva FDW rebootstrap/ALTER SERVER, a WAN "
            "profili zahtijevaju tc/netem segment u corpus sweep-u."
        )
    if spec.get("fdw_server_options"):
        raise ValueError(
            f"Runtime config {requested_id} sadrži fdw_server_options i zato nije "
            "siguran za live dijagnostiku bez rebootstrap-a FDW servera."
        )
    if spec.get("network_profile"):
        raise ValueError(
            f"Runtime config {requested_id} sadrži network_profile i zato nije "
            "siguran za live dijagnostiku bez kontrolisanog tc/netem segmenta."
        )
    return requested_id, spec


def runtime_context_fields(runtime_config: dict[str, Any]) -> dict[str, str]:
    network_profile = runtime_config.get("network_profile", {}) or {}
    pg_options = runtime_config.get("pg_options", {}) or {}
    fdw_server_options = runtime_config.get("fdw_server_options", {}) or {}
    return {
        "intervention_axis": str(runtime_config.get("intervention_axis", "none")),
        "runtime_expected_effect": str(runtime_config.get("expected_effect", "")),
        "work_mem": str(pg_options.get("work_mem", "")),
        "fetch_size": str(fdw_server_options.get("fetch_size", "")),
        "pg_options_json": json_text(pg_options),
        "psql_variables_json": json_text(runtime_config.get("psql_variables", {})),
        "fdw_server_options_json": json_text(fdw_server_options),
        "network_profile_json": json_text(network_profile),
        "network_profile_id": str(network_profile.get("id", "")),
        "configured_latency_ms": str(network_profile.get("configured_delay_ms", "")),
        "configured_jitter_ms": str(network_profile.get("configured_jitter_ms", "")),
        "configured_loss_percent": str(network_profile.get("configured_loss_percent", "")),
    }


def run_command(
    command: list[str],
    *,
    cwd: Path,
    step_id: str,
    timeout_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    log(f"{step_id}: {' '.join(command)}")
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if result.stdout.strip():
        log(f"{step_id} stdout:\n{result.stdout.strip()[-4000:]}")
    if result.stderr.strip():
        log(f"{step_id} stderr:\n{result.stderr.strip()[-4000:]}")
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            command,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def inventory_has_target(path: Path, *, target_group: str, target_host: str) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        hosts = data["all"]["children"].get(target_group, {}).get("hosts", {})
    except Exception:
        return False
    if target_host:
        return target_host in hosts
    return bool(hosts)


def parse_last_path(output: str) -> Path:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped.startswith("/"):
            return Path(stripped)
    raise RuntimeError(f"Ne mogu pronaći izlazni folder u outputu:\n{output[-2000:]}")


def write_instance_manifest(
    *,
    path: Path,
    sql_file: Path,
    run_id: str,
    dataset_id: str,
    runtime_config_id: str,
    runtime_config: dict[str, Any],
    target: str,
) -> None:
    columns = [
        "instance_id",
        "template_id",
        "rendered_sql_path",
        "param_json",
        "expected_shape_tags",
        "corpus_id",
        "corpus_cell_id",
        "logical_question_id",
        "execution_strategy",
        "dataset_profile_id",
        "runtime_config_id",
        "topology_id",
        "intervention_role",
        "intervention_axis",
        "runtime_expected_effect",
        "work_mem",
        "fetch_size",
        "pg_options_json",
        "psql_variables_json",
        "fdw_server_options_json",
        "network_profile_json",
        "network_profile_id",
        "configured_latency_ms",
        "configured_jitter_ms",
        "configured_loss_percent",
        "expected_regime_targets",
        "execution_class",
        "runtime_sensitivity",
        "required_dataset_capabilities",
        "intervention_roles",
        "cache_policy",
        "order_policy",
        "shuffle_seed",
        "repetition_index",
        "run_order",
        "warmup_run_flag",
    ]
    runtime_fields = runtime_context_fields(runtime_config)
    param_payload = {
        "target": target,
        "runtime_config_id": runtime_config_id,
        "pg_options": runtime_config.get("pg_options", {}),
        "psql_variables": runtime_config.get("psql_variables", {}),
        "fdw_server_options": runtime_config.get("fdw_server_options", {}),
        "network_profile": runtime_config.get("network_profile", {}),
    }
    row = {
        "instance_id": run_id,
        "template_id": "manual_sql",
        "rendered_sql_path": str(sql_file),
        "param_json": json.dumps(param_payload, sort_keys=True),
        "expected_shape_tags": "manual,live",
        "corpus_id": "live-diagnosis",
        "corpus_cell_id": f"live__{dataset_id}__{runtime_config_id}__{target}",
        "logical_question_id": "manual_sql",
        "execution_strategy": f"manual_sql_{target}",
        "dataset_profile_id": dataset_id,
        "runtime_config_id": runtime_config_id,
        "topology_id": "eu_us_gac",
        "intervention_role": "manual",
        **runtime_fields,
        "expected_regime_targets": "",
        "execution_class": "live",
        "runtime_sensitivity": "",
        "required_dataset_capabilities": "",
        "intervention_roles": "",
        "cache_policy": "mixed_cache_first_observed",
        "order_policy": "manual",
        "shuffle_seed": "",
        "repetition_index": "0",
        "run_order": "1",
        "warmup_run_flag": "false",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(row)


def load_inference_module() -> Any:
    module_path = ROOT / "analysis/scripts/agent/21_query_run_inference_rehearsal.py"
    spec = importlib.util.spec_from_file_location("query_run_inference_rehearsal", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Ne mogu učitati inference modul: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Očekivao YAML mapu u {path}")
    return value


def latest_dataset_load_context(*, infra_root: Path, dataset_id: str) -> dict[str, Any]:
    load_root = infra_root / "generated" / "runs" / "dataset-loads"
    if not dataset_id or not load_root.exists():
        return {}
    candidates: list[tuple[str, str, Path, dict[str, Any]]] = []
    for manifest_path in load_root.glob("*/dataset_load_manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(manifest.get("dataset_id", "")) != dataset_id:
            continue
        region = str(manifest.get("region", "")).strip().lower()
        if not region:
            load_id = str(manifest.get("load_id", manifest_path.parent.name))
            region = next(
                (
                    candidate
                    for candidate in ("eu", "us")
                    if load_id.lower().endswith(f"-{candidate}")
                ),
                "unknown",
            )
        candidates.append(
            (
                region,
                str(manifest.get("created_at_utc", "")),
                manifest_path,
                manifest,
            )
        )
    if not candidates:
        return {}

    latest_by_region: dict[str, tuple[str, Path, dict[str, Any]]] = {}
    for region, created_at, manifest_path, manifest in candidates:
        current = latest_by_region.get(region)
        if current is None or created_at > current[0]:
            latest_by_region[region] = (created_at, manifest_path, manifest)

    region_contexts = [
        _dataset_load_region_context(
            region=region,
            manifest_path=manifest_path,
            manifest=manifest,
        )
        for region, (_created_at, manifest_path, manifest) in sorted(
            latest_by_region.items()
        )
    ]
    latest_context = max(
        region_contexts,
        key=lambda item: str(item.get("createdAtUtc", "")),
    )
    result: dict[str, Any] = {
        "datasetId": dataset_id,
        "loadId": latest_context["loadId"],
        "loadPath": latest_context["loadPath"],
        "regionCount": len(region_contexts),
        "regions": region_contexts,
    }
    if len(region_contexts) == 1:
        result.update(
            {
                "tenantSkew": latest_context["tenantSkew"],
                "placement": latest_context["placement"],
                "parameterValues": latest_context["parameterValues"],
                "artifacts": latest_context["artifacts"],
            }
        )
    return result


def _dataset_load_region_context(
    *,
    region: str,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    load_dir = manifest_path.parent
    audit_path = load_dir / "capability_audit.json"
    params_path = load_dir / "dataset_parameter_values.json"
    audit = {}
    params = {}
    if audit_path.exists():
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            audit = {}
    if params_path.exists():
        try:
            params = json.loads(params_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            params = {}
    tenant_placement = audit.get("tenant_placement", {}) if isinstance(audit, dict) else {}
    tenant_skew = audit.get("tenant_skew", {}) if isinstance(audit, dict) else {}
    parameter_values = params.get("parameter_values", {}) if isinstance(params, dict) else {}
    datagen_env = manifest.get("datagen_env", {})
    if not isinstance(datagen_env, dict):
        datagen_env = {}
    effective_distribution = manifest.get("effective_distribution", {})
    if not isinstance(effective_distribution, dict):
        effective_distribution = {}
    tenant_start = _metadata_integer(datagen_env.get("DATAGEN_TENANT_START"))
    tenant_end = _metadata_integer(datagen_env.get("DATAGEN_TENANT_END"))
    tenant_count = (
        tenant_end - tenant_start + 1
        if tenant_start is not None
        and tenant_end is not None
        and tenant_end >= tenant_start
        else None
    )
    events_per_tenant = _metadata_integer(
        datagen_env.get("DATAGEN_EVENTS_PER_TENANT")
    )
    users_per_tenant = _metadata_integer(
        datagen_env.get("DATAGEN_GLOBAL_USERS_PER_TENANT")
    )
    return {
        "regionId": region,
        "createdAtUtc": str(manifest.get("created_at_utc", "")),
        "loadId": load_dir.name,
        "loadPath": relative_path(load_dir),
        "generation": {
            "tenantStart": tenant_start,
            "tenantEnd": tenant_end,
            "tenantCount": tenant_count,
            "eventsPerTenantAvg": events_per_tenant,
            "estimatedEventRows": (
                tenant_count * events_per_tenant
                if tenant_count is not None and events_per_tenant is not None
                else None
            ),
            "usersPerTenantAvg": users_per_tenant,
            "estimatedUserRows": (
                tenant_count * users_per_tenant
                if tenant_count is not None and users_per_tenant is not None
                else None
            ),
            "lookbackDays": _metadata_integer(
                datagen_env.get("DATAGEN_LOOKBACK_DAYS")
            ),
            "randomSeed": _metadata_integer(
                datagen_env.get("DATAGEN_RANDOM_SEED")
            ),
            "distributionKey": recorded_metadata_value(
                effective_distribution.get("distribution_key")
            ),
            "shardCount": _metadata_integer(
                effective_distribution.get("shard_count")
            ),
            "skewProfile": recorded_metadata_value(
                effective_distribution.get("skew_profile")
            ),
            "hotTenantPct": recorded_metadata_value(
                effective_distribution.get("hot_tenant_pct")
            ),
            "hotEventPct": recorded_metadata_value(
                effective_distribution.get("hot_event_pct")
            ),
        },
        "tenantSkew": {
            "hotTenantCount": recorded_metadata_value(
                tenant_skew.get("hot_tenant_count")
            ),
            "hotEventShare": recorded_metadata_value(
                tenant_skew.get("hot_event_share")
            ),
            "eventsCv": recorded_metadata_value(tenant_skew.get("events_cv")),
            "maxToMeanRatio": recorded_metadata_value(
                tenant_skew.get("max_to_mean_ratio")
            ),
        },
        "placement": {
            "dominantHotWorker": recorded_metadata_value(
                tenant_placement.get("dominant_hot_worker")
            ),
            "dominantHotWorkerHotTenantCount": recorded_metadata_value(
                tenant_placement.get("dominant_hot_worker_hot_tenant_count")
            ),
            "dominantHotWorkerHotEventShare": recorded_metadata_value(
                tenant_placement.get("dominant_hot_worker_hot_event_share")
            ),
            "dominantHotWorkerProbeIds": tenant_placement.get(
                "dominant_hot_worker_probe_ids", []
            ),
        },
        "parameterValues": {
            "hotTenantProbeIds": parameter_values.get("hot_tenant_probe_ids", []),
            "coldTenantProbeIds": parameter_values.get("cold_tenant_probe_ids", []),
            "dominantHotWorkerProbeIds": parameter_values.get(
                "dominant_hot_worker_probe_ids", []
            ),
        },
        "artifacts": {
            "capabilityAudit": relative_path(audit_path) if audit_path.exists() else "",
            "datasetParameterValues": relative_path(params_path) if params_path.exists() else "",
            "hotTenantWorkerMapping": relative_path(
                load_dir / "hot_tenant_worker_mapping.csv"
            )
            if (load_dir / "hot_tenant_worker_mapping.csv").exists()
            else "",
            "hotTenantWorkerSummary": relative_path(
                load_dir / "hot_tenant_worker_summary.csv"
            )
            if (load_dir / "hot_tenant_worker_summary.csv").exists()
            else "",
        },
    }


def _metadata_integer(value: Any) -> int | None:
    cleaned = recorded_metadata_value(value)
    if cleaned is None:
        return None
    try:
        return int(cleaned)
    except (TypeError, ValueError):
        return None


def recorded_metadata_value(value: Any) -> Any:
    cleaned = clean_value(value)
    if isinstance(cleaned, str) and not cleaned.strip():
        return None
    return cleaned


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


SEVERITY_COMPONENT_LABELS = {
    "deployment_relative_intensity_score": "ukupni indeks pritiska u ovoj topologiji",
    "wan_fetch_intensity_score": "FDW/WAN prenos prema GAC-u",
    "memory_spill_intensity_score": "memorijski/spill pritisak",
    "imbalance_intensity_score": "neravnoteža i repni task pritisak",
    "capacity_intensity_score": "Citus task/slot pritisak",
    "timeout_relative_severity_score": "potrošnja timeout budžeta",
}

ACTIVE_PRESSURE_THRESHOLD = 0.10
ACTIVE_PRESSURE_DETAIL_THRESHOLD = 0.01
PRIMARY_SEVERITY_COMPONENT_IDS = {
    "wan_fetch_intensity_score",
    "memory_spill_intensity_score",
    "imbalance_intensity_score",
    "capacity_intensity_score",
    "timeout_relative_severity_score",
}
SEVERITY_BASIS_COMPONENT_IDS = {
    "timeout_utilization": "timeout_relative_severity_score",
    "wan_fetch_intensity": "wan_fetch_intensity_score",
    "memory_spill_intensity": "memory_spill_intensity_score",
    "imbalance_intensity": "imbalance_intensity_score",
    "capacity_intensity": "capacity_intensity_score",
}
PRESENTATION_FEATURE_FAMILY_OVERRIDES = {
    # In the model this contributes to the FDW/WAN transfer axis, but in the UI it is
    # safer to present it as regional data reduction. For pushdowned aggregates,
    # high DRF means "many regional rows reduced before WAN", not bad fan-in.
    "drf_bytes_proxy": "regional_reduction",
}

SEVERITY_METRIC_LABELS = {
    "execution_time_seconds": "trajanje izvršenja",
    "wan_output_mb": "WAN izlaz",
    "regional_reduction_input_mb_proxy": "procjena regionalnog ulaza",
    "temp_mb": "privremeni blokovi",
    "remote_region_rows_isf": "regionalni ISF redova",
    "worker_task_scan_rows_isf": "ISF scan redova po Citus tasku",
    "active_task_share": "udio aktivnih Citus taskova",
    "tasks_per_worker_ratio": "taskovi po workeru",
    "timeout_utilization_ratio": "iskorištenost timeouta",
}

SEVERITY_BAND_LABELS = {
    "low": "nizak",
    "medium": "srednji",
    "high": "visok",
    "critical": "kritičan",
}

PUSHDOWN_METRIC_LABELS = {
    "fdw_foreign_scan_count": "Foreign Scan čvorovi",
    "foreign_scan_filter_present_count": "lokalni FDW filteri",
    "foreign_scan_filter_pushdown_match_count": "filteri pronađeni u udaljenom SQL-u",
    "remote_sql_where_present_count": "WHERE u udaljenom SQL-u",
    "remote_sql_group_by_present_count": "GROUP BY u udaljenom SQL-u",
    "remote_sql_order_by_present_count": "ORDER BY u udaljenom SQL-u",
    "remote_sql_limit_present_count": "LIMIT u udaljenom SQL-u",
    "remote_sql_pushdown_filter_ratio": "omjer filtera prenesenih u udaljeni SQL",
    "aggregate_above_foreign_scan_count": "agregacija iznad FDW granice",
    "sort_above_foreign_scan_count": "sortiranje iznad FDW granice",
    "limit_above_foreign_scan_count": "ograničenje iznad FDW granice",
    "aggregate_pushdown_missed_flag": "agregacija nije pushdownana",
    "sort_pushdown_missed_flag": "sort nije pushdownan",
    "limit_pushdown_missed_flag": "limit nije pushdownan",
    "remote_to_foreign_scan_rows_ratio": "udaljeni redovi prema redovima Foreign Scan-a",
    "foreign_scan_to_final_rows_ratio": "redovi Foreign Scan-a prema finalnim redovima",
    "post_fdw_filter_reduction_ratio": "redukcija filterom nakon FDW-a",
    "projection_width_expansion_ratio": "proširenje širine projekcije",
    "main_spill_blocks_sum": "spill blokovi na GAC sloju",
    "remote_spill_blocks_sum": "regionalni spill blokovi",
    "async_remote_scan_present": "opaženo asinhrono udaljeno skeniranje",
    "serial_remote_region_scan_count": "sekvencijalna regionalna skeniranja",
}

PUSHDOWN_REASON_LABELS = {
    "local_filter_after_remote": "lokalni filter nakon udaljenog dohvata",
    "aggregate_not_pushdowned": "agregacija ostaje iznad FDW granice",
    "sort_not_pushdowned": "sortiranje ostaje iznad FDW granice",
    "limit_not_pushdowned": "ograničenje ostaje iznad FDW granice",
    "projection_width_expansion": "širina reda ili projekcije raste iznad udaljenog plana",
}

PUSHDOWN_STATUS_LABELS = {
    "not_applicable_no_fdw": "nije primjenjivo: nema FDW granice",
    "complete": "potpun audit dokaz",
    "partial": "djelimičan audit dokaz",
    "available": "audit dokaz dostupan",
    "missing": "audit dokaz nije dostupan",
}

CROSS_REGION_METRIC_LABELS = {
    "configured_region_count": "konfigurisani regioni",
    "remote_region_count": "očekivani udaljeni regioni",
    "remote_region_observed_count": "opaženi udaljeni regioni",
    "remote_region_missing_count": "regioni bez dokaza",
    "remote_region_evidence_completeness": "kompletnost regionalnog dokaza",
    "remote_region_actual_rows_imbalance_ratio": "omjer neravnoteže redova između regiona",
    "remote_region_tuple_bytes_imbalance_ratio": "omjer neravnoteže bajtova između regiona",
    "remote_region_task_count_imbalance_ratio": (
        "omjer neravnoteže broja Citus taskova između regiona"
    ),
    "remote_region_actual_time_imbalance_ratio": "omjer neravnoteže vremena između regiona",
    "remote_region_rows_isf": "regionalni ISF redova",
    "worker_task_scan_rows_isf": "ISF scan redova po Citus tasku",
    "worker_scan_rows_isf": "worker-agregirani ISF scan redova",
    "worker_scan_rows_cv": "worker-agregirani CV scan redova",
    "worker_task_scan_actual_rows_max_share": "udio najvećeg pojedinačnog scan taska",
    "worker_task_within_region_scan_rows_isf_max": "maksimalni ISF Citus taskova unutar regiona",
    "worker_task_within_region_scan_rows_cv_max": "maksimalni CV Citus taskova unutar regiona",
    "worker_task_tuple_bytes_cv": "CV bajtova slogova po Citus tasku",
    "worker_task_tuple_bytes_max_share": "udio bajtova najvećeg pojedinačnog Citus taska",
    "configured_region_shard_slots": "konfigurisani region-shard slotovi",
    "observed_region_shard_slots": "opaženi region-shard slotovi",
}


def severity_payload(severity_row: pd.DataFrame) -> dict[str, Any]:
    if severity_row.empty:
        return {
            "available": False,
            "score": None,
            "band": None,
            "label": "nije dostupno",
            "basis": [],
            "components": [],
            "metrics": [],
            "explanation": ["indeks pritiska nije izračunat za ovaj query_run_id"],
        }

    row = severity_row.iloc[0].to_dict()
    band = clean_value(row.get("severity_band"))
    basis_value = clean_value(row.get("severity_basis")) or ""
    basis = [item for item in str(basis_value).split(",") if item]

    components = []
    for key, label in SEVERITY_COMPONENT_LABELS.items():
        value = clean_value(row.get(key))
        if value is not None:
            components.append({"id": key, "label": label, "value": value})

    metrics = []
    for key, label in SEVERITY_METRIC_LABELS.items():
        value = clean_value(row.get(key))
        if value is not None:
            metrics.append({"id": key, "label": label, "value": value})

    explanation = []
    primary_components = [
        component for component in components if component["id"] in PRIMARY_SEVERITY_COMPONENT_IDS
    ]
    strongest = sorted(
        primary_components,
        key=lambda item: float(item["value"]) if item["value"] is not None else -1.0,
        reverse=True,
    )
    if strongest:
        strongest_value = float(strongest[0]["value"]) if strongest[0]["value"] is not None else 0.0
        if strongest_value >= ACTIVE_PRESSURE_THRESHOLD:
            explanation.append(
                f"Dominantna komponenta indeksa pritiska: {strongest[0]['label']}."
            )
        else:
            explanation.append("Nema aktivne komponente indeksa pritiska.")
    component_values = {str(component["id"]): component.get("value") for component in components}
    if _active_component(component_values, SEVERITY_BASIS_COMPONENT_IDS["timeout_utilization"]):
        explanation.append("Indeks pritiska uključuje potrošnju timeout budžeta.")
    if _active_component(component_values, SEVERITY_BASIS_COMPONENT_IDS["wan_fetch_intensity"]):
        explanation.append("Indeks pritiska uključuje FDW/WAN prenos prema GAC-u.")
    if _active_component(component_values, SEVERITY_BASIS_COMPONENT_IDS["memory_spill_intensity"]):
        explanation.append("Indeks pritiska uključuje privremene blokove i spill pritisak.")
    if _active_component(component_values, SEVERITY_BASIS_COMPONENT_IDS["imbalance_intensity"]):
        explanation.append("Indeks pritiska uključuje region/task neravnotežu.")
    if _active_component(component_values, SEVERITY_BASIS_COMPONENT_IDS["capacity_intensity"]):
        explanation.append("Indeks pritiska uključuje Citus task/slot odnos prema topologiji.")

    return {
        "available": True,
        "score": clean_value(row.get("severity_score")),
        "band": band,
        "label": SEVERITY_BAND_LABELS.get(str(band), str(band) if band else "nije dostupno"),
        "basis": basis,
        "components": components,
        "metrics": metrics,
        "explanation": explanation,
        "modelRole": clean_value(row.get("severity_model_role")),
        "contract": clean_value(row.get("severity_contract")),
    }


def _active_component(component_values: dict[str, Any], component_id: str) -> bool:
    value = clean_value(component_values.get(component_id))
    if value is None:
        return False
    try:
        return float(value) >= ACTIVE_PRESSURE_DETAIL_THRESHOLD
    except (TypeError, ValueError):
        return False


def presentation_family_map(family_map: dict[str, str]) -> dict[str, str]:
    result = dict(family_map)
    for feature, family in PRESENTATION_FEATURE_FAMILY_OVERRIDES.items():
        if feature in result:
            result[feature] = family
    return result


def _number(row: dict[str, Any], key: str) -> float | None:
    value = clean_value(row.get(key))
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _metric_rows(row: dict[str, Any], labels: dict[str, str]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for key, label in labels.items():
        value = clean_value(row.get(key))
        if value is not None:
            metrics.append({"id": key, "label": label, "value": value})
    return metrics


def pressure_evidence_payload(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    assessments: list[dict[str, Any]] = []
    focus: list[str] = []
    for row in rows:
        try:
            feature_items = json.loads(str(row.get("feature_evidence_json") or "[]"))
        except json.JSONDecodeError:
            feature_items = []
        feature_values = {
            str(item.get("feature")): clean_value(item.get("raw_value"))
            for item in feature_items
            if item.get("feature")
        }
        status = str(row.get("pressure_status") or "not_measured")
        recommended_focus = clean_value(row.get("recommended_focus"))
        if recommended_focus and status in {"confirmed", "partially_confirmed"}:
            focus.append(str(recommended_focus))
        assessments.append(
            {
                "id": clean_value(row.get("pressure_id")),
                "label": clean_value(row.get("pressure_label")),
                "status": status,
                "score": clean_value(row.get("pressure_score")),
                "band": clean_value(row.get("pressure_band")),
                "reason": clean_value(row.get("reason")),
                "features": feature_values,
                "dominantFeature": clean_value(row.get("dominant_feature")),
                "dominantFeatureScore": clean_value(row.get("dominant_feature_score")),
                "contract": clean_value(row.get("pressure_contract")),
            }
        )
    return assessments, list(dict.fromkeys(focus))


def _split_codes(value: Any) -> list[str]:
    cleaned = clean_value(value)
    if cleaned is None:
        return []
    return [
        code.strip()
        for code in str(cleaned).replace(";", ",").split(",")
        if code.strip() and code.strip().lower() not in {"nan", "none", "null"}
    ]


def pushdown_payload(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "available": False,
            "evidenceStatus": "missing",
            "evidenceLabel": "FDW pushdown audit nije izračunat",
            "components": pushdown_component_statuses({}),
            "metrics": [],
            "reasons": [],
            "explanation": ["FDW pushdown fidelity v1 nije dostupan za ovaj query_run_id."],
            "heuristic": True,
            "modelRole": "posthoc_audit_not_clustering_input",
        }

    metrics = _metric_rows(row, PUSHDOWN_METRIC_LABELS)
    status = clean_value(row.get("pushdown_fidelity_evidence_status"))
    reason_codes = _split_codes(row.get("pushdown_miss_reason_codes"))
    has_fdw = bool(clean_value(row.get("main_has_foreign_scan")))
    available = bool(
        status is not None
        or reason_codes
        or _number(row, "pushdown_miss_score") is not None
        or _number(row, "fdw_foreign_scan_count") is not None
    )

    if not available:
        explanation = (
            ["FDW je opažen, ali pushdown fidelity kolone nisu izračunate u ovom snapshotu."]
            if has_fdw
            else ["Nema opažene FDW granice ili audit sloj nije izračunat."]
        )
        return {
            "available": False,
            "evidenceStatus": "missing",
            "evidenceLabel": "audit nije dostupan",
            "components": pushdown_component_statuses(row),
            "metrics": metrics,
            "reasons": [],
            "explanation": explanation,
            "heuristic": True,
            "modelRole": "posthoc_audit_not_clustering_input",
        }

    reasons = [
        {"id": code, "label": PUSHDOWN_REASON_LABELS.get(code, code)}
        for code in reason_codes
    ]
    explanation = []
    miss_score = _number(row, "pushdown_miss_score")
    if miss_score is not None:
        if miss_score >= 0.75:
            explanation.append(
                "FDW/GAC granica pokazuje da većina elemenata nije prenesena "
                "u udaljeni SQL."
            )
        elif miss_score >= 0.35:
            explanation.append(
                "FDW/GAC granica pokazuje da dio elemenata nije prenesen "
                "u udaljeni SQL."
            )
        else:
            explanation.append("Dostupni artefakti ne pokazuju značajno propuštanje pushdowna.")
    if reasons:
        explanation.append(
            "Glavni razlozi: "
            + ", ".join(item["label"] for item in reasons[:4])
            + "."
        )
    component_count = _number(row, "pushdown_fidelity_component_count")
    if component_count is not None and component_count <= 1:
        explanation.append(
            "Ocjena je zasnovana na malom broju komponenti. "
            "Treba je tumačiti oprezno."
        )

    return {
        "available": True,
        "score": clean_value(row.get("pushdown_fidelity_score")),
        "missScore": clean_value(row.get("pushdown_miss_score")),
        "componentCount": clean_value(row.get("pushdown_fidelity_component_count")),
        "evidenceStatus": status,
        "evidenceLabel": PUSHDOWN_STATUS_LABELS.get(
            str(status),
            str(status) if status else "dostupno",
        ),
        "contract": clean_value(row.get("fdw_pushdown_fidelity_contract")),
        "components": pushdown_component_statuses(row),
        "reasons": reasons,
        "metrics": metrics,
        "explanation": explanation,
        "heuristic": True,
        "modelRole": "posthoc_audit_not_clustering_input",
    }


def cross_region_payload(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "available": False,
            "metrics": [],
            "regionStats": [],
            "explanation": ["Regionalni/worker audit nije dostupan za ovaj query_run_id."],
            "modelRole": "posthoc_audit_not_clustering_input",
        }

    metrics = _metric_rows(row, CROSS_REGION_METRIC_LABELS)
    region_stats = []
    for prefix, label in [
        ("remote_region_actual_rows", "izlazni redovi po regionu"),
        ("remote_region_tuple_bytes", "bajtovi slogova po regionu"),
        ("remote_region_task_count", "broj Citus taskova po regionu"),
        ("remote_region_actual_time", "stvarno vrijeme po regionu"),
    ]:
        stat = {
            "id": prefix,
            "label": label,
            "min": clean_value(row.get(f"{prefix}_min")),
            "max": clean_value(row.get(f"{prefix}_max")),
            "mean": clean_value(row.get(f"{prefix}_mean")),
            "imbalanceRatio": clean_value(row.get(f"{prefix}_imbalance_ratio")),
        }
        if any(stat[key] is not None for key in ["min", "max", "mean", "imbalanceRatio"]):
            region_stats.append(stat)

    available = bool(metrics or region_stats)
    if not available:
        return {
            "available": False,
            "metrics": [],
            "regionStats": [],
            "explanation": ["Nema regionalnih/worker agregata za ovaj query_run_id."],
            "modelRole": "posthoc_audit_not_clustering_input",
        }

    explanation = []
    completeness = _number(row, "remote_region_evidence_completeness")
    if completeness is not None:
        explanation.append(
            "Regionalni dokaz je kompletan za očekivani broj regiona."
            if completeness >= 0.99
            else "Regionalni dokaz je djelimičan. Neke regione treba tumačiti oprezno."
        )
    region_isf = _number(row, "remote_region_rows_isf") or _number(
        row, "remote_region_actual_rows_imbalance_ratio"
    )
    if region_isf is not None:
        if region_isf >= 2:
            explanation.append("Jedan region dominira izlaznim redovima prema GAC-u.")
        elif region_isf >= 1.25:
            explanation.append("Postoji umjerena regionalna neravnoteža u izlazu prema GAC-u.")
        else:
            explanation.append("Izlazni redovi prema GAC-u su približno balansirani kroz regione.")
    worker_isf = _number(row, "worker_task_scan_rows_isf")
    if worker_isf is not None:
        if worker_isf >= 4:
            explanation.append("Neravnomjernost scan redova između Citus taskova je jaka.")
        elif worker_isf >= 1.5:
            explanation.append(
                "Neravnomjernost scan redova između Citus taskova je prisutna, ali nije ekstremna."
            )
        else:
            explanation.append(
                "Scan redovi približno su ravnomjerno raspoređeni između "
                "Citus taskova."
            )
    byte_cv = _number(row, "worker_task_tuple_bytes_cv")
    if byte_cv is not None and byte_cv >= 0.75:
        explanation.append("Neravnoteža bajtova između Citus taskova je povišena.")

    return {
        "available": True,
        "metrics": metrics,
        "regionStats": region_stats,
        "explanation": explanation,
        "modelRole": "posthoc_audit_not_clustering_input",
    }


def public_context(context: dict[str, Any]) -> dict[str, Any]:
    hidden_key_names = {"file", "path", "dir", "artifact"}
    hidden_key_suffixes = ("_file", "_path", "_dir", "_artifact")
    hidden_value_fragments = ("/workspace/", "/home/", "/opt/master", "/root/")
    public: dict[str, Any] = {}
    for key, value in context.items():
        key_text = str(key)
        lowered_key = key_text.lower()
        if lowered_key in hidden_key_names or lowered_key.endswith(hidden_key_suffixes):
            continue
        if isinstance(value, str) and any(fragment in value for fragment in hidden_value_fragments):
            continue
        public[key_text] = value
    return public


def output_path(value: Path) -> str:
    try:
        return str(value.resolve().relative_to(ROOT))
    except ValueError:
        try:
            return "../" + str(value.resolve().relative_to(ROOT.parent))
        except ValueError:
            return str(value)


def regime_meta(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    cluster = int(row["cluster"])
    source = regime_meta_for_cluster(cluster)
    regime_id = str(source["regime_id"])
    return {
        "cluster": cluster,
        "regimeId": regime_id,
        "name": str(source["regime_name"]),
        "macroFamily": source["macro_family"],
        "macroFamilyName": source["macro_family_name"],
        "variant": source["variant"],
        "color": REGIME_COLORS.get(regime_id, "#475569"),
        "membership": float(row["membership"]),
    }


def confidence_label(top: float, gap: float, entropy: float) -> tuple[str, str]:
    if top >= 0.7 and gap >= 0.25:
        return "high", "vodeća fuzzy sličnost i razmak do drugog prototipa su jaki"
    if top >= 0.5 and gap >= 0.12:
        return "medium", "vodeća fuzzy sličnost je umjerena, a konkurentski prototip nije zanemariv"
    if entropy >= 1.05:
        return "mixed", "entropija fuzzy sličnosti je visoka. Izvršenje je između prototipa"
    return "low", "vodeća fuzzy sličnost ili razmak do drugog prototipa su slabi"


def entropy(values: list[float]) -> float:
    return float(-sum(value * math.log(value) for value in values if value > 0))


def quality_payload(
    *,
    transform_audit: pd.DataFrame,
    raw_row: pd.Series,
    features: list[str],
    quality: pd.DataFrame,
    distance: float,
    training_distances: pd.Series,
    context: dict[str, Any],
) -> dict[str, Any]:
    missing_count = int(transform_audit["was_missing"].sum())
    quality_rows = quality[
        quality["matrix"].eq("m0_flow_ratio_v3_reduced") & quality["feature"].isin(features)
    ].copy()
    by_feature = {str(row["feature"]): row for _, row in quality_rows.iterrows()}
    out_minmax = 0
    out_p01p99 = 0
    for feature in features:
        spec = by_feature.get(feature)
        raw_value = pd.to_numeric(pd.Series([raw_row.get(feature, np.nan)]), errors="coerce").iloc[
            0
        ]
        if spec is None or pd.isna(raw_value):
            continue
        min_value = pd.to_numeric(pd.Series([spec.get("min")]), errors="coerce").iloc[0]
        max_value = pd.to_numeric(pd.Series([spec.get("max")]), errors="coerce").iloc[0]
        if pd.notna(min_value) and pd.notna(max_value) and (
            raw_value < min_value or raw_value > max_value
        ):
            out_minmax += 1
        # compact_feature_quality does not store p01/p99. Use min/max as the
        # conservative OOD bound and keep p01/p99 unavailable as zero.
    percentile = (
        float((training_distances <= distance).mean())
        if not training_distances.empty and pd.notna(distance)
        else 0.0
    )
    if percentile >= 0.99 or out_minmax:
        ood = "high"
    elif percentile >= 0.95:
        ood = "medium"
    else:
        ood = "low"
    return {
        "featureCoverage": len(features) - missing_count,
        "featureTotal": len(features),
        "missingImputedFeatures": missing_count,
        "outOfMinMaxFeatureCount": out_minmax,
        "outOfP01P99FeatureCount": out_p01p99,
        "nearestCenterDistance": distance,
        "nearestCenterDistancePercentile": percentile,
        "oodLevel": ood,
        "contextAvailable": {
            "fetchSize": bool(context.get("fetch_size")),
            "workMem": bool(context.get("work_mem")),
            "wanProfile": bool(context.get("network_profile_id")),
        },
    }


def prototype_matches(
    *,
    centers_membership: pd.DataFrame,
    context: pd.DataFrame,
    scaled_vector: pd.Series,
    features: list[str],
    matrix_name: str,
) -> list[dict[str, Any]]:
    matrix_path = TRAINING_FEATURE_DIR / f"compact_{matrix_name}_scaled.csv"
    if not matrix_path.exists():
        return []
    training = read_csv(matrix_path)
    if training.empty or "query_run_id" not in training.columns:
        return []
    missing_features = [feature for feature in features if feature not in training.columns]
    if missing_features:
        return []
    values = training[features].apply(pd.to_numeric, errors="coerce")
    values = values.dropna(how="any")
    if values.empty:
        return []
    query_ids = training.loc[values.index, "query_run_id"].astype(str)
    live = scaled_vector[features].to_numpy(dtype=float)
    distances = np.linalg.norm(values.to_numpy(dtype=float) - live.reshape(1, -1), axis=1)
    rows = pd.DataFrame({"query_run_id": query_ids.to_numpy(), "prototype_distance": distances})
    rows = rows.sort_values("prototype_distance", ascending=True).head(4)

    memberships = centers_membership[centers_membership["k"].eq(4)].copy()
    memberships["query_run_id"] = memberships["query_run_id"].astype(str)
    rows = rows.merge(
        memberships[
            [
                "query_run_id",
                "hard_cluster",
                "max_membership",
                "top2_margin",
                "membership_entropy",
            ]
        ],
        on="query_run_id",
        how="left",
    )
    context = context.copy()
    context["query_run_id"] = context["query_run_id"].astype(str)
    merged = rows.merge(context, on="query_run_id", how="left")
    result: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        cluster = int(row["hard_cluster"]) if pd.notna(row.get("hard_cluster")) else -1
        if cluster >= 0:
            meta = regime_meta_for_cluster(cluster)
            regime_id = regime_meta(
                {
                    "cluster": cluster,
                    "regime_id": meta["regime_id"],
                    "regime_name": meta["regime_name"],
                    "membership": row.get("max_membership", 0.0),
                }
            )["regimeId"]
        else:
            regime_id = "n/a"
        result.append(
            {
                "regimeId": regime_id,
                "queryRunId": str(row["query_run_id"]),
                "distance": float(row["prototype_distance"]),
                "maxMembership": clean_value(row.get("max_membership")),
                "top2Margin": clean_value(row.get("top2_margin")),
                "membershipEntropy": clean_value(row.get("membership_entropy")),
                "templateId": clean_value(row.get("template_id")),
                "logicalQuestionId": clean_value(row.get("logical_question_id")),
                "executionStrategy": clean_value(row.get("execution_strategy")),
            }
        )
    return result


def training_nearest_center_distances(
    *,
    centers: pd.DataFrame,
    features: list[str],
    matrix_name: str,
) -> pd.Series:
    matrix_path = TRAINING_FEATURE_DIR / f"compact_{matrix_name}_scaled.csv"
    if not matrix_path.exists():
        return pd.Series(dtype=float)
    training = read_csv(matrix_path)
    if training.empty:
        return pd.Series(dtype=float)
    missing_features = [feature for feature in features if feature not in training.columns]
    if missing_features:
        return pd.Series(dtype=float)
    values = training[features].apply(pd.to_numeric, errors="coerce").dropna(how="any")
    if values.empty:
        return pd.Series(dtype=float)
    center_matrix = centers[features].to_numpy(dtype=float)
    distances = np.linalg.norm(
        values.to_numpy(dtype=float)[:, None, :] - center_matrix[None, :, :],
        axis=2,
    ).min(axis=1)
    return pd.Series(distances)


def build_diagnosis_json(
    *,
    sql_text: str,
    sql_file: Path,
    query_run_id: str,
    live_run_id: str,
    features_dir: Path,
    inference_dir: Path,
    runtime_context: dict[str, Any] | None = None,
    dataset_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inference = load_inference_module()
    matrix_name = "m0_flow_ratio_v3_reduced"
    raw = read_csv(features_dir / "execution_features_m0.csv")
    raw["query_run_id"] = raw["query_run_id"].astype(str)
    raw_row_frame = raw[raw["query_run_id"].eq(query_run_id)]
    if raw_row_frame.empty:
        raise ValueError(f"Nema live raw feature reda za query_run_id={query_run_id}")
    raw_row = raw_row_frame.iloc[0]

    model_context = read_csv(features_dir / "model_context.csv")
    model_context["query_run_id"] = model_context["query_run_id"].astype(str)
    context_row = model_context[model_context["query_run_id"].eq(query_run_id)].head(1)
    context = (
        {key: clean_value(value) for key, value in context_row.iloc[0].to_dict().items()}
        if not context_row.empty
        else {"query_run_id": query_run_id}
    )
    if runtime_context:
        context.update(
            {
                key: clean_value(value)
                for key, value in runtime_context.items()
                if value not in (None, "")
            }
        )

    training_preprocess = read_csv(TRAINING_FEATURE_DIR / "compact_preprocessing_report.csv")
    training_quality = read_csv(TRAINING_FEATURE_DIR / "compact_feature_quality.csv")
    centers, features = inference._load_centers(FUZZY_DIR)
    final_manifest = read_yaml(FINAL_MODEL_MANIFEST)
    fuzzifier = float(final_manifest.get("primary_model", {}).get("fuzzifier", 1.7))

    scaled_vector, transform_audit = inference._transform_raw_row(
        raw_row,
        training_preprocess,
        training_quality,
        features,
        matrix_name,
    )
    membership = inference._fcm_membership(
        scaled_vector[features].to_numpy(dtype=float),
        centers,
        features,
        fuzzifier,
    )
    family_map = presentation_family_map(
        inference._load_family_map(TRAINING_FEATURE_DIR, features, matrix_name)
    )
    evidence, family = inference._feature_evidence(
        scaled_vector,
        membership,
        centers,
        features,
        family_map,
    )

    severity = read_csv(features_dir / "execution_severity.csv")
    severity["query_run_id"] = severity["query_run_id"].astype(str)
    severity_row = severity[severity["query_run_id"].eq(query_run_id)].head(1)

    inference_dir.mkdir(parents=True, exist_ok=True)
    raw_export = {"query_run_id": query_run_id}
    for feature in features:
        raw_export[feature] = raw_row.get(feature, pd.NA)
    pd.DataFrame([raw_export]).to_csv(inference_dir / "input_raw_features.csv", index=False)
    pd.DataFrame([{**{"query_run_id": query_run_id}, **scaled_vector.to_dict()}]).to_csv(
        inference_dir / "input_scaled_features.csv", index=False
    )
    transform_audit.to_csv(inference_dir / "preprocessing_audit.csv", index=False)
    membership.to_csv(inference_dir / "inferred_membership.csv", index=False)
    evidence.to_csv(inference_dir / "feature_evidence.csv", index=False)
    family.to_csv(inference_dir / "family_pressure.csv", index=False)
    if not severity_row.empty:
        severity_row.to_csv(inference_dir / "execution_severity.csv", index=False)
    severity_context = (
        {key: clean_value(value) for key, value in severity_row.iloc[0].to_dict().items()}
        if not severity_row.empty
        else {}
    )

    pressure_rows = pd.DataFrame()
    training_raw_path = TRAINING_FEATURE_DIR / f"compact_{matrix_name}_raw.csv"
    if training_raw_path.exists():
        training_raw = read_csv(training_raw_path)
        pressure_thresholds = build_pressure_thresholds(training_raw)
        pressure_rows, _pressure_wide = build_pressure_evidence(
            pd.DataFrame([raw_row.to_dict()]),
            thresholds=pressure_thresholds,
        )
        pressure_rows.to_csv(inference_dir / "pressure_evidence.csv", index=False)
    assessment_rows, pressure_focus = pressure_evidence_payload(
        pressure_rows.to_dict(orient="records") if not pressure_rows.empty else []
    )

    audit_row = {
        **context,
        **{key: clean_value(value) for key, value in raw_row.to_dict().items()},
        **severity_context,
    }

    top = membership.iloc[0]
    competitor = membership.iloc[1]
    memberships = [regime_meta(row) for _, row in membership.iterrows()]
    top_membership = float(top["membership"])
    competitor_membership = float(competitor["membership"])
    top2_margin = top_membership - competitor_membership
    ent = entropy([float(row["membership"]) for _, row in membership.iterrows()])
    conf_label, conf_reason = confidence_label(top_membership, top2_margin, ent)
    ambiguity = assess_ambiguity(
        top_membership=top_membership,
        top2_margin=top2_margin,
        entropy=ent,
    )

    stored_memberships = read_csv(FUZZY_DIR / "memberships_representative_by_k.csv")
    training_distances = training_nearest_center_distances(
        centers=centers,
        features=features,
        matrix_name=matrix_name,
    )
    quality = quality_payload(
        transform_audit=transform_audit,
        raw_row=raw_row,
        features=features,
        quality=training_quality,
        distance=float(top["distance_to_center"]),
        training_distances=training_distances,
        context=context,
    )

    positive = evidence[evidence["margin_support"].gt(0)].sort_values(
        "margin_support", ascending=False
    )
    negative = evidence[evidence["margin_support"].lt(0)].sort_values(
        "margin_support", ascending=True
    )

    def evidence_json(frame: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for _, row in frame.head(limit).iterrows():
            feature = str(row["feature"])
            rows.append(
                {
                    "feature": feature,
                    "family": str(row["feature_family"]),
                    "rawValue": clean_value(raw_row.get(feature)),
                    "scaledValue": float(row["x_z"]),
                    "topCenter": float(row["top_center_z"]),
                    "competitorCenter": float(row["competitor_center_z"]),
                    "support": float(row["margin_support"]),
                    "direction": (
                        "podržava vodeći režim"
                        if float(row["margin_support"]) >= 0
                        else "vuče prema konkurentskom režimu"
                    ),
                }
            )
        return rows

    family_rows = []
    for _, row in family.iterrows():
        family_rows.append(
            {
                "family": str(row["feature_family"]),
                "support": float(row["family_positive_support"]),
                "competingPressure": float(row["family_competing_pressure"]),
                "share": clean_value(row["family_support_share"]) or 0,
            }
        )

    raw_values = {feature: clean_value(raw_row.get(feature)) for feature in features}
    raw_values_for_tags = {feature: raw_row.get(feature) for feature in features}
    consistency_score = int(round(100 * min(max(top_membership + top2_margin / 2.0, 0.0), 1.0)))
    if consistency_score >= 75:
        consistency_label = "konzistentno"
    elif consistency_score >= 50:
        consistency_label = "djelimično konzistentno"
    else:
        consistency_label = "miješano"
    warnings: list[str] = []
    if quality["missingImputedFeatures"] != 0:
        warnings.append("neki pokazatelji su imputirani iz trening medijana")
    if quality["oodLevel"] == "high":
        warnings.append(
            "ulaz je daleko od trening korpusa. Fuzzy vrijednosti treba tumačiti kao "
            "sličnost prototipima, ne kao siguran režim"
        )
    if ambiguity.mixed:
        warnings.append(
            "postotke pripadnosti treba tumačiti kao prototipsku sličnost. Konkretni "
            "mehanizam treba čitati iz oznaka mehanizma i dokaza pokazatelja"
        )

    training_context = read_csv(TRAINING_FEATURE_DIR / "compact_context.csv")
    diagnosis = {
        "queryRunId": query_run_id,
        "shortId": live_run_id,
        "context": {
            **public_context(context),
            "query_run_id": query_run_id,
            "live_run_id": live_run_id,
            "live_execution_mode": "real_infra_pipeline",
        },
        "sql": {
            "path": None,
            "text": sql_text,
            "available": True,
            "querySqlFile": None,
            "bindingsFile": None,
            "paramJson": json.dumps({"live_run_id": live_run_id}, sort_keys=True),
        },
        "topRegime": regime_meta(top),
        "competitorRegime": regime_meta(competitor),
        "memberships": memberships,
        "macroFamilies": macro_family_summary(memberships),
        "mechanismTags": mechanism_tags(raw_values_for_tags),
        "ambiguityPolicy": {
            "label": ambiguity.label,
            "mixed": ambiguity.mixed,
            "explainClusterAsContextOnly": ambiguity.explain_cluster_as_context_only,
            "reason": ambiguity.reason,
        },
        "confidence": {
            "label": conf_label,
            "reason": ambiguity.reason if ambiguity.mixed else conf_reason,
            "topMembership": top_membership,
            "secondMembership": competitor_membership,
            "topTwoMargin": top2_margin,
            "entropy": ent,
            "mixed": ambiguity.mixed,
        },
        "quality": quality,
        "severity": severity_payload(severity_row),
        "pushdown": pushdown_payload(audit_row),
        "spill": spill_location_evidence(audit_row),
        "crossRegion": cross_region_payload(audit_row),
        "datasetPlacement": dataset_context or {},
        "diagnosticConsistency": {
            "score": consistency_score,
            "label": consistency_label,
            "expectedRegimes": [],
            "heuristicReasons": [
                "live SQL je klasifikovan direktno iz prikupljenih plan/flow pokazatelja"
            ],
            "warnings": warnings,
        },
        "pressureFamilies": family_rows,
        "pressureAssessments": assessment_rows,
        "recommendedFocus": pressure_focus
        or [str(row["feature_family"]) for _, row in family.head(3).iterrows()],
        "topFeatureSupport": evidence_json(positive, 10),
        "contradictoryEvidence": evidence_json(negative, 8),
        "prototypeComparison": prototype_matches(
            centers_membership=stored_memberships,
            context=training_context,
            scaled_vector=scaled_vector,
            features=features,
            matrix_name=matrix_name,
        ),
        "rawFeatureValues": raw_values,
    }
    (inference_dir / "diagnosis.json").write_text(
        json.dumps(diagnosis, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return diagnosis


def semantic_display_state(
    *,
    top_membership: float,
    top2_margin: float,
    membership_entropy: float,
) -> str:
    if (
        top_membership >= 0.50
        and top2_margin >= 0.15
        and membership_entropy < 1.05
    ):
        return "clear_prototype"
    if (
        top_membership < 0.50
        and top2_margin < 0.15
        and membership_entropy >= 1.05
    ):
        return "weak_prototype_coverage"
    return "mixed_boundary"


def _index_rows(index_dir: Path, filename: str, query_run_id: str) -> pd.DataFrame:
    path = index_dir / filename
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, low_memory=False)
    if "query_run_id" not in frame:
        return pd.DataFrame()
    return frame[frame["query_run_id"].astype(str).eq(query_run_id)].copy()


def evidence_lineage_payload(
    *,
    index_dir: Path,
    query_run_id: str,
    feature_row: pd.Series,
) -> dict[str, Any]:
    plan_files = _index_rows(index_dir, "plan_files.csv", query_run_id)
    plan_nodes = _index_rows(index_dir, "plan_nodes.csv", query_run_id)
    regions = _index_rows(index_dir, "region_fragments.csv", query_run_id)
    tasks = _index_rows(index_dir, "worker_task_fragments.csv", query_run_id)
    query_runs = _index_rows(index_dir, "query_runs.csv", query_run_id)

    def integer(value: Any, default: int = 0) -> int:
        numeric_value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        return int(numeric_value) if pd.notna(numeric_value) else default

    main_plans = (
        plan_files[plan_files["plan_scope"].astype(str).eq("main")]
        if not plan_files.empty and "plan_scope" in plan_files
        else pd.DataFrame()
    )
    main_fingerprint = (
        clean_value(main_plans.iloc[0].get("plan_fingerprint"))
        if not main_plans.empty
        else None
    )
    execution_status = (
        clean_value(query_runs.iloc[0].get("execution_status"))
        if not query_runs.empty
        else None
    )
    elapsed_seconds = (
        clean_value(query_runs.iloc[0].get("elapsed_seconds"))
        if not query_runs.empty
        else None
    )
    observed_regions = (
        sorted(regions["region_id"].dropna().astype(str).unique().tolist())
        if not regions.empty and "region_id" in regions
        else []
    )
    expected_regions = integer(
        feature_row.get("remote_region_count"),
        len(observed_regions),
    )
    expected_regions = max(expected_regions, len(observed_regions))

    region_layers: list[dict[str, Any]] = []
    if not regions.empty:
        for region_id, group in regions.groupby("region_id", dropna=False):
            first = group.iloc[0]
            region_layers.append(
                {
                    "regionId": str(region_id),
                    "planCount": int(len(group)),
                    "rootNodeType": clean_value(first.get("remote_root_node_type")),
                    "taskCount": clean_value(
                        pd.to_numeric(
                            group.get("remote_citus_task_count", pd.Series(dtype=float)),
                            errors="coerce",
                        ).max()
                    ),
                    "actualRows": clean_value(
                        pd.to_numeric(
                            group.get("remote_actual_rows", pd.Series(dtype=float)),
                            errors="coerce",
                        ).sum(min_count=1)
                    ),
                    "remoteHasAggregate": _observed_flag(
                        group,
                        "remote_has_aggregate",
                    ),
                    "remoteHasSort": _observed_flag(
                        group,
                        "remote_has_sort",
                    ),
                    "remoteHasJoin": _observed_flag(
                        group,
                        "remote_has_join",
                    ),
                    "parseStatus": clean_value(first.get("parse_status")),
                    "fingerprint": clean_value(first.get("remote_plan_fingerprint")),
                }
            )

    worker_layers: list[dict[str, Any]] = []
    if not tasks.empty:
        group_columns = [
            column
            for column in ("fdw_region", "worker_node")
            if column in tasks.columns
        ]
        grouped = (
            tasks.groupby(group_columns, dropna=False)
            if group_columns
            else [("all", tasks)]
        )
        for group_key, group in grouped:
            if isinstance(group_key, tuple):
                region_id, worker_node = group_key
            elif group_columns == ["fdw_region"]:
                region_id, worker_node = group_key, None
            elif group_columns == ["worker_node"]:
                region_id, worker_node = None, group_key
            else:
                region_id, worker_node = None, None
            worker_layers.append(
                {
                    "regionId": clean_value(region_id),
                    "workerNode": clean_value(worker_node),
                    "taskCount": int(len(group)),
                    "scanRows": clean_value(
                        pd.to_numeric(
                            group.get(
                                "worker_task_scan_actual_rows_sum",
                                pd.Series(dtype=float),
                            ),
                            errors="coerce",
                        ).sum(min_count=1)
                    ),
                    "tupleBytes": clean_value(
                        pd.to_numeric(
                            group.get(
                                "tuple_data_received_bytes",
                                pd.Series(dtype=float),
                            ),
                            errors="coerce",
                        ).sum(min_count=1)
                    ),
                    "parseStatuses": sorted(
                        group.get("parse_status", pd.Series(dtype=str))
                        .dropna()
                        .astype(str)
                        .unique()
                        .tolist()
                    ),
                }
            )

    component_checks = {
        "mainPlan": not main_plans.empty,
        "regionalPlans": (
            len(observed_regions) >= expected_regions
            if expected_regions
            else True
        ),
        "workerTasks": not tasks.empty or not observed_regions,
    }
    completeness = sum(component_checks.values()) / len(component_checks)
    plan_scopes = (
        plan_files["plan_scope"].fillna("unknown").astype(str).value_counts().to_dict()
        if not plan_files.empty and "plan_scope" in plan_files
        else {}
    )
    artifact_references = [
        {
            "planId": clean_value(plan.get("plan_id")),
            "scope": clean_value(plan.get("plan_scope")),
            "status": clean_value(plan.get("status")),
            "jsonFile": clean_value(plan.get("plan_json_file")),
            "textFile": clean_value(plan.get("explain_text_file")),
        }
        for _, plan in plan_files.iterrows()
    ]
    return {
        "executionStatus": execution_status,
        "elapsedSeconds": elapsed_seconds,
        "planFingerprint": main_fingerprint,
        "evidenceCompleteness": completeness,
        "componentChecks": component_checks,
        "counts": {
            "planFiles": int(len(plan_files)),
            "planNodes": int(len(plan_nodes)),
            "regionsObserved": int(len(observed_regions)),
            "regionsExpected": int(expected_regions),
            "workerTaskFragments": int(len(tasks)),
        },
        "planScopes": {str(key): int(value) for key, value in plan_scopes.items()},
        "regions": region_layers,
        "workers": worker_layers,
        "artifacts": artifact_references,
    }


def _observed_flag(frame: pd.DataFrame, column: str) -> bool:
    if column not in frame:
        return False
    return any(
        str(value).strip().lower() in {"1", "true", "t", "yes"}
        for value in frame[column].dropna()
    )


def semantic_prototype_matches(
    *,
    weighted_vector: pd.Series,
    features: list[str],
) -> list[dict[str, Any]]:
    training = read_csv(SEMANTIC_AUDIT_DIR / "semantic_v2_weighted.csv")
    memberships = read_csv(SEMANTIC_MODEL_DIR / "baseline_memberships_k4.csv")
    context = read_csv(TRAINING_FEATURE_DIR / "compact_context.csv")
    merged = (
        training.merge(
            memberships[["query_run_id", "dominant_cluster", "max_membership"]],
            on="query_run_id",
            validate="one_to_one",
        )
        .merge(context, on="query_run_id", how="left", validate="one_to_one")
    )
    live = weighted_vector[features].to_numpy(dtype=float)
    rows: list[dict[str, Any]] = []
    for cluster, group in merged.groupby("dominant_cluster"):
        distances = np.linalg.norm(
            group[features].to_numpy(dtype=float) - live.reshape(1, -1),
            axis=1,
        )
        row = group.iloc[int(np.argmin(distances))]
        meta = semantic_v2_prototype_meta_for_cluster(int(cluster))
        rows.append(
            {
                "regimeId": meta["regime_id"],
                "queryRunId": str(row["query_run_id"]),
                "distance": float(np.min(distances)),
                "maxMembership": clean_value(row.get("max_membership")),
                "templateId": clean_value(row.get("template_id")),
                "logicalQuestionId": clean_value(row.get("logical_question_id")),
                "executionStrategy": clean_value(row.get("execution_strategy")),
            }
        )
    return sorted(rows, key=lambda row: float(row["distance"]))


def build_semantic_diagnosis_json(
    *,
    sql_text: str,
    query_run_id: str,
    live_run_id: str,
    features_dir: Path,
    index_dir: Path,
    inference_dir: Path,
    runtime_context: dict[str, Any] | None = None,
    dataset_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = read_yaml(SEMANTIC_CONTRACT)
    manifest = read_yaml(SEMANTIC_MODEL_DIR / "semantic_v2_model_manifest.yml")
    features = [str(feature) for feature in manifest["features"]]
    all_features = read_csv(features_dir / "execution_features_all.csv")
    all_features["query_run_id"] = all_features["query_run_id"].astype(str)
    support_row = all_features[all_features["query_run_id"].eq(query_run_id)].head(1)
    if support_row.empty:
        raise ValueError(f"Nema live feature reda za query_run_id={query_run_id}")
    missing_columns = [feature for feature in features if feature not in support_row]
    if missing_columns:
        raise ValueError(
            "Live feature sloj ne podržava finalni semantički ugovor: "
            + ", ".join(missing_columns)
        )

    raw = support_row[["query_run_id", *features]].copy()
    transformed, weighted, transform_audit = semantic_transform(
        raw,
        support_row,
        contract,
    )
    centers = read_csv(SEMANTIC_MODEL_DIR / "cluster_centers_k4.csv")
    centers = centers.sort_values("cluster").reset_index(drop=True)
    center_values = centers[features].to_numpy(dtype=float)
    fuzzifier = float(manifest["fuzzifier"])
    membership_values, distance_values = memberships_from_centers(
        weighted[features].to_numpy(dtype=float),
        center_values,
        fuzzifier=fuzzifier,
    )
    membership_vector = membership_values[0]
    distance_vector = distance_values[0]

    memberships = semantic_v2_membership_rows(
        membership_vector.tolist(),
        distance_values=distance_vector.tolist(),
    )
    top = memberships[0]
    competitor = memberships[1]
    top_cluster = int(top["cluster"])
    competitor_cluster = int(competitor["cluster"])
    top_membership = float(top["membership"])
    competitor_membership = float(competitor["membership"])
    top2_margin = top_membership - competitor_membership
    membership_entropy = entropy(
        [float(row["membership"]) for row in memberships]
    )
    display_state = semantic_display_state(
        top_membership=top_membership,
        top2_margin=top2_margin,
        membership_entropy=membership_entropy,
    )

    raw_row = raw.iloc[0]
    semantic_row = transformed.iloc[0]
    weighted_row = weighted.iloc[0]
    top_center = centers.loc[top_cluster]
    competitor_center = centers.loc[competitor_cluster]
    top_squared = np.square(
        weighted_row[features].to_numpy(dtype=float)
        - top_center[features].to_numpy(dtype=float)
    )
    competitor_squared = np.square(
        weighted_row[features].to_numpy(dtype=float)
        - competitor_center[features].to_numpy(dtype=float)
    )
    total_squared = float(top_squared.sum())
    contract_features = contract["features"]
    evidence_rows: list[dict[str, Any]] = []
    family_distance: dict[str, float] = {}
    for index, feature in enumerate(features):
        specification = contract_features[feature]
        family = str(specification["family"])
        distance_share = (
            float(top_squared[index] / total_squared)
            if total_squared > 0
            else 0.0
        )
        family_distance[family] = family_distance.get(family, 0.0) + distance_share
        discriminating_margin = float(
            competitor_squared[index] - top_squared[index]
        )
        evidence_rows.append(
            {
                "feature": feature,
                "family": family,
                "rawValue": clean_value(raw_row.get(feature)),
                "semanticValue": float(semantic_row[feature]),
                "weightedValue": float(weighted_row[feature]),
                "scaledValue": float(weighted_row[feature]),
                "topCenter": float(top_center[feature]),
                "competitorCenter": float(competitor_center[feature]),
                "squaredDistance": float(top_squared[index]),
                "distanceShare": distance_share,
                "discriminatingMargin": discriminating_margin,
                "support": discriminating_margin,
                "direction": (
                    "bliže vodećem prototipu"
                    if discriminating_margin >= 0
                    else "bliže drugom prototipu"
                ),
                "applicable": pd.notna(raw_row.get(feature)),
                "unit": specification.get("unit"),
                "transform": specification.get("transform"),
                "applicability": specification.get("applicability"),
                "nullSemantics": specification.get("null_semantics"),
                "caveat": specification.get("dataset_dependence"),
            }
        )
    distance_ranked = sorted(
        evidence_rows,
        key=lambda row: float(row["distanceShare"]),
        reverse=True,
    )
    discriminating_ranked = sorted(
        evidence_rows,
        key=lambda row: abs(float(row["discriminatingMargin"])),
        reverse=True,
    )
    family_rows = [
        {
            "family": family,
            "distanceShare": share,
            "share": share,
            "support": share,
            "competingPressure": 0.0,
        }
        for family, share in sorted(
            family_distance.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]

    model_context = read_csv(features_dir / "model_context.csv")
    model_context["query_run_id"] = model_context["query_run_id"].astype(str)
    context_row = model_context[
        model_context["query_run_id"].eq(query_run_id)
    ].head(1)
    context = (
        {
            key: clean_value(value)
            for key, value in context_row.iloc[0].to_dict().items()
        }
        if not context_row.empty
        else {"query_run_id": query_run_id}
    )
    if runtime_context:
        context.update(
            {
                key: clean_value(value)
                for key, value in runtime_context.items()
                if value not in (None, "")
            }
        )

    nearest_distance = float(distance_vector.min())
    p99_threshold = float(
        manifest["models"]["k4"]["ood_p99_threshold"]
    )
    baseline_memberships = read_csv(
        SEMANTIC_MODEL_DIR / "baseline_memberships_k4.csv"
    )
    training_distances = pd.to_numeric(
        baseline_memberships["nearest_center_distance"],
        errors="coerce",
    ).dropna()
    distance_percentile = float(
        (training_distances <= nearest_distance).mean()
    )
    distance_over_p99 = nearest_distance / p99_threshold
    missing_count = int(raw[features].isna().sum(axis=1).iloc[0])
    confidence, confidence_reason = confidence_label(
        top_membership,
        top2_margin,
        membership_entropy,
    )
    lineage = evidence_lineage_payload(
        index_dir=index_dir,
        query_run_id=query_run_id,
        feature_row=support_row.iloc[0],
    )

    inference_dir.mkdir(parents=True, exist_ok=True)
    raw.to_csv(inference_dir / "input_raw_features.csv", index=False)
    transformed.to_csv(
        inference_dir / "input_semantic_features.csv",
        index=False,
    )
    weighted.to_csv(
        inference_dir / "input_weighted_features.csv",
        index=False,
    )
    transform_audit.to_csv(
        inference_dir / "semantic_transform_audit.csv",
        index=False,
    )
    pd.DataFrame(evidence_rows).to_csv(
        inference_dir / "distance_contributions.csv",
        index=False,
    )
    pd.DataFrame(
        [
            {
                "query_run_id": query_run_id,
                "dominant_cluster": top_cluster,
                "max_membership": top_membership,
                "top2_margin": top2_margin,
                "membership_entropy": membership_entropy,
                "nearest_center_distance": nearest_distance,
                "ood_p99_threshold": p99_threshold,
                "distance_over_p99": distance_over_p99,
                **{
                    f"membership_c{cluster}": float(
                        membership_vector[cluster]
                    )
                    for cluster in range(len(membership_vector))
                },
            }
        ]
    ).to_csv(inference_dir / "inferred_membership.csv", index=False)

    audit_context = {
        **support_row.iloc[0].to_dict(),
        **context,
    }
    diagnosis = {
        "schemaVersion": "diagnosis_index_v3",
        "queryRunId": query_run_id,
        "shortId": live_run_id,
        "context": {
            **public_context(context),
            "query_run_id": query_run_id,
            "live_run_id": live_run_id,
            "live_execution_mode": "real_infra_pipeline",
        },
        "sql": {
            "path": None,
            "text": sql_text,
            "available": True,
            "querySqlFile": None,
            "bindingsFile": None,
            "paramJson": json.dumps(
                {"live_run_id": live_run_id},
                sort_keys=True,
            ),
        },
        "lineage": lineage,
        "topRegime": top,
        "competitorRegime": competitor,
        "memberships": memberships,
        "confidence": {
            "label": confidence,
            "displayState": display_state,
            "reason": confidence_reason,
            "topMembership": top_membership,
            "secondMembership": competitor_membership,
            "topTwoMargin": top2_margin,
            "entropy": membership_entropy,
            "mixed": display_state != "clear_prototype",
        },
        "quality": {
            "featureCoverage": len(features) - missing_count,
            "featureTotal": len(features),
            "missingImputedFeatures": missing_count,
            "outOfMinMaxFeatureCount": 0,
            "outOfP01P99FeatureCount": 0,
            "nearestCenterDistance": nearest_distance,
            "nearestCenterDistancePercentile": distance_percentile,
            "oodP99Threshold": p99_threshold,
            "distanceOverP99": distance_over_p99,
            "insideFrozenP99": nearest_distance <= p99_threshold,
            "oodLevel": (
                "high" if nearest_distance > p99_threshold else "low"
            ),
            "contextAvailable": {
                "fetchSize": bool(context.get("fetch_size")),
                "workMem": bool(context.get("work_mem")),
                "wanProfile": bool(context.get("network_profile_id")),
            },
        },
        "pushdown": pushdown_payload(audit_context),
        "spill": spill_location_evidence(audit_context),
        "crossRegion": cross_region_payload(audit_context),
        "datasetPlacement": dataset_context or {},
        "pressureFamilies": family_rows,
        "topFeatureSupport": distance_ranked,
        "contradictoryEvidence": discriminating_ranked,
        "prototypeComparison": semantic_prototype_matches(
            weighted_vector=weighted_row,
            features=features,
        ),
        "rawFeatureValues": {
            feature: clean_value(raw_row.get(feature))
            for feature in features
        },
        "semanticFeatureValues": {
            feature: float(semantic_row[feature])
            for feature in features
        },
        "weightedFeatureValues": {
            feature: float(weighted_row[feature])
            for feature in features
        },
        "featureTransforms": distance_ranked,
        "modelContract": {
            "modelId": manifest["model_id"],
            "representation": "final_semantic_19",
            "featureCount": len(features),
            "fuzzifier": fuzzifier,
            "prototypeCount": 4,
            "membershipInterpretation": (
                "relativna sličnost korpusom uslovljenim prototipima"
            ),
        },
    }
    (inference_dir / "diagnosis.json").write_text(
        json.dumps(
            diagnosis,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return diagnosis


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one live SQL diagnosis through real infra.")
    parser.add_argument("--sql-file", type=Path, required=True)
    parser.add_argument("--label", default="manual-sql")
    parser.add_argument("--target", choices=("gac", "eu", "us"), default="gac")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--timeout-grace-seconds", type=int, default=20)
    parser.add_argument("--dataset-id", default=DEFAULT_LIVE_DATASET_ID)
    parser.add_argument("--runtime-config-id", default="live-default")
    parser.add_argument("--out-root", type=Path, default=OUT_ROOT)
    parser.add_argument("--infra-root", type=Path, default=INFRA_ROOT)
    parser.add_argument("--no-fdw-auto-explain", action="store_true")
    parser.add_argument("--no-citus-explain-all-tasks", action="store_true")
    return parser.parse_args()


def main() -> int:
    pipeline_started_at = time.perf_counter()
    args = parse_args()
    sql_file = args.sql_file.resolve()
    sql_text = sql_file.read_text(encoding="utf-8")
    if not read_only_sql(sql_text):
        raise SystemExit("Live dijagnostika prihvata samo read-only SELECT/WITH/EXPLAIN SQL.")
    runtime_config_id, runtime_config = resolve_runtime_config(args.runtime_config_id)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = safe_component(f"{timestamp}-{args.label}-{short_hash(sql_text)}")
    work_dir = (args.out_root / run_id).resolve()
    input_dir = work_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    canonical_sql = input_dir / "query.sql"
    canonical_sql.write_text(sql_text, encoding="utf-8")
    manifest_path = input_dir / "instance_manifest.csv"
    write_instance_manifest(
        path=manifest_path,
        sql_file=canonical_sql,
        run_id=run_id,
        dataset_id=args.dataset_id,
        runtime_config_id=runtime_config_id,
        runtime_config=runtime_config,
        target=args.target,
    )

    target_group = "analytics_clients" if args.target == "gac" else "coordinators"
    target_host = "" if args.target == "gac" else f"{args.target}-coord-1"
    query_pg_options = {
        **runtime_config.get("pg_options", {}),
        "default_transaction_read_only": "on",
        "statement_timeout": f"{args.timeout_seconds}s",
    }
    steps: list[dict[str, Any]] = []
    phase_started_at = time.perf_counter()
    steps.append(
        {
            "id": "sql_capture",
            "label": "SQL prihvaćen",
            "status": "completed",
            "detail": "upit je prihvaćen i pripremljen za izvršenje",
            "durationSeconds": elapsed_since(phase_started_at),
        }
    )

    phase_started_at = time.perf_counter()
    inventory_path = args.infra_root / "ansible/inventory/generated.json"
    inventory_policy = os.environ.get("LIVE_DIAGNOSIS_REFRESH_INVENTORY", "auto").strip().lower()
    refresh_inventory = inventory_policy in {"1", "true", "yes", "always"}
    if inventory_policy in {"", "auto"}:
        refresh_inventory = not inventory_has_target(
            inventory_path,
            target_group=target_group,
            target_host=target_host,
        )
    if refresh_inventory:
        run_command(
            ["make", "single-eu-inventory", "TOPOLOGY=eu-us-gac-vps"],
            cwd=args.infra_root,
            step_id="inventory",
            timeout_seconds=120,
        )
    else:
        log(f"inventory: using existing {inventory_path}")
    if not inventory_has_target(
        inventory_path,
        target_group=target_group,
        target_host=target_host,
    ):
        raise RuntimeError(
            "Live inventar ne sadrži traženi target. "
            f"group={target_group}, host={target_host or '<first>'}"
        )

    query_collection_started_at = time.perf_counter()
    sweep_command = [
        sys.executable,
        "common-scripts/run_query_collection_sweep.py",
        "--instance-manifest",
        str(manifest_path),
        "--label",
        f"live-diagnosis__{run_id}",
        "--out-root",
        str(args.infra_root / "generated/runs/live-diagnosis/query-sweeps"),
        "--max-instances",
        "1",
        "--global-stats-scope",
        "none",
        "--target-group",
        target_group,
        "--hard-timeout-seconds",
        str(args.timeout_seconds),
        "--timeout-grace-seconds",
        str(args.timeout_grace_seconds),
        *kv_args("--pg-option", query_pg_options),
        *kv_args("--var", runtime_config.get("psql_variables", {})),
    ]
    if target_host:
        sweep_command.extend(["--target-host", target_host])
    if not args.no_fdw_auto_explain and args.target == "gac":
        sweep_command.append("--fdw-auto-explain")
    if args.no_citus_explain_all_tasks:
        sweep_command.append("--no-citus-explain-all-tasks")

    sweep_result = run_command(
        sweep_command,
        cwd=args.infra_root,
        step_id="query_collection",
        timeout_seconds=max(args.timeout_seconds + 180, 300),
    )
    query_collection_duration = elapsed_since(query_collection_started_at)
    sweep_dir = parse_last_path(sweep_result.stdout)
    sweep_status_path = sweep_dir / "query_sweep_status.json"
    sweep_status = read_yaml(sweep_status_path) if sweep_status_path.exists() else {}
    query_count_by_status = sweep_status.get("query_count_by_status", {})
    if query_count_by_status.get("failed") or query_count_by_status.get("timeout"):
        raise RuntimeError(
            "Prikupljanje artefakata live upita nije uspješno završeno. "
            f"artefakti su u {sweep_dir}, status je {query_count_by_status}."
        )
    query_collection_step = {
        "id": "query_collection",
        "label": "EXPLAIN ANALYZE i artefakti izvršenja",
        "status": "completed",
        "detail": f"collector faza završena za {seconds_label(query_collection_duration)}",
        "durationSeconds": query_collection_duration,
    }
    steps.append(query_collection_step)
    remote_plan_detail = (
        "auto_explain je uključen"
        if args.target == "gac" and not args.no_fdw_auto_explain
        else "nije primjenjivo za ovaj cilj"
    )
    steps.append(
        {
            "id": "remote_plan_collection",
            "label": "regionalni FDW/auto_explain planovi",
            "status": "completed",
            "detail": remote_plan_detail,
        }
    )

    indexing_started_at = time.perf_counter()
    index_result = run_command(
        [UV_BIN, "run", "master-regimes", "index-query-sweep", "--sweep-dir", str(sweep_dir)],
        cwd=ROOT,
        step_id="indexing",
        timeout_seconds=180,
    )
    indexing_duration = elapsed_since(indexing_started_at)
    index_dir = parse_last_path(index_result.stdout)
    query_runs = read_csv(index_dir / "query_runs.csv")
    query_elapsed_seconds: float | None = None
    if not query_runs.empty and "elapsed_seconds" in query_runs.columns:
        query_elapsed_value = query_runs.iloc[0].get("elapsed_seconds")
        try:
            query_elapsed_seconds = float(query_elapsed_value)
        except (TypeError, ValueError):
            query_elapsed_seconds = None
    if query_elapsed_seconds is not None:
        query_collection_step["detail"] = (
            f"SQL/EXPLAIN trajanje: {seconds_label(query_elapsed_seconds)}. "
            f"collector faza: {seconds_label(query_collection_duration)}"
        )
        query_collection_step["queryElapsedSeconds"] = round(query_elapsed_seconds, 6)
    steps.append(
        {
            "id": "indexing",
            "label": "normalizovani _index",
            "status": "completed",
            "detail": f"_index je izgrađen za {seconds_label(indexing_duration)}",
            "durationSeconds": indexing_duration,
        }
    )

    features_dir = work_dir / "features"
    feature_started_at = time.perf_counter()
    run_command(
        [
            UV_BIN,
            "run",
            "master-regimes",
            "build-feature-matrix",
            "--index-dir",
            str(index_dir),
            "--out-dir",
            str(features_dir),
            "--topology",
            "multi_region",
        ],
        cwd=ROOT,
        step_id="feature_extraction",
        timeout_seconds=180,
    )
    feature_duration = elapsed_since(feature_started_at)
    steps.append(
        {
            "id": "feature_extraction",
            "label": "izdvajanje pokazatelja",
            "status": "completed",
            "detail": (
                "pokazatelji i indeks pritiska u odnosu na topologiju su izračunati za "
                f"{seconds_label(feature_duration)}"
            ),
            "durationSeconds": feature_duration,
        }
    )

    extracted_features = read_csv(features_dir / "execution_features_all.csv")
    if extracted_features.empty:
        raise RuntimeError("Feature matrix nema nijedan query_run_id.")
    query_run_id = str(extracted_features.iloc[0]["query_run_id"])
    inference_dir = work_dir / "inference"
    inference_started_at = time.perf_counter()
    diagnosis = build_semantic_diagnosis_json(
        sql_text=sql_text,
        query_run_id=query_run_id,
        live_run_id=run_id,
        features_dir=features_dir,
        index_dir=index_dir,
        inference_dir=inference_dir,
        runtime_context=runtime_context_fields(runtime_config),
        dataset_context=latest_dataset_load_context(
            infra_root=args.infra_root,
            dataset_id=args.dataset_id,
        ),
    )
    inference_duration = elapsed_since(inference_started_at)
    steps.append(
        {
            "id": "inference",
            "label": "fuzzy dijagnoza režima",
            "status": "completed",
            "detail": f"dijagnoza je izračunata za {seconds_label(inference_duration)}",
            "durationSeconds": inference_duration,
        }
    )

    response = {
        "liveRunId": run_id,
        "executionMode": "real_infra_pipeline",
        "pipelineDurationSeconds": elapsed_since(pipeline_started_at),
        "message": (
            "Live SQL je izvršen kroz stvarni collector, indeksiran i "
            "projektovan u finalnu 19-dimenzionalnu semantičku reprezentaciju."
        ),
        "steps": steps,
        "artifacts": {
            "status": "server_side",
            "message": "artefakti su sačuvani na serveru i nisu izloženi u produkcijskom odgovoru",
        },
        "diagnosis": diagnosis,
    }
    (work_dir / "live_response.json").write_text(
        json.dumps(response, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
