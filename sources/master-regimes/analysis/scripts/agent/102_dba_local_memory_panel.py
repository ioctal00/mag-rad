#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT = ROOT / "configs/validation/dba_local_memory_panel_v1.yml"
DEFAULT_SOURCE_DIR = ROOT / "generated/corpus/dba-local-memory-v1-source"
DEFAULT_RENDERED_DIR = ROOT / "generated/corpus/dba-local-memory-v1"
DEFAULT_INDEX_DIR = (
    ROOT.parent
    / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs"
    / "dba-local-memory-panel-v1/_index"
)
DEFAULT_OUT_DIR = ROOT / "analysis/reports/dba-local-memory-panel-v1"
ACTIONS = (
    "increase_gac_work_mem",
    "regional_topk_candidates",
    "mitigate_remote_path_bundle",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and analyze the DBA local-memory episode panel."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "validate-design", "analyze"):
        child = subparsers.add_parser(command)
        child.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
        child.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
        child.add_argument("--rendered-dir", type=Path, default=DEFAULT_RENDERED_DIR)
        child.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
        child.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _json_default(value: Any) -> Any:
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _validate_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = sorted(contract["scenarios"], key=lambda item: int(item["order"]))
    if len(scenarios) != 15:
        raise ValueError(f"Expected 15 scenarios, found {len(scenarios)}")
    if tuple(contract["actions"]) != ACTIONS:
        raise ValueError("The panel must use the three frozen known actions")
    orders = [int(row["order"]) for row in scenarios]
    if orders != list(range(1, 16)):
        raise ValueError("Scenario order must be the contiguous range 1..15")
    query_ids = [str(row["query_id"]) for row in scenarios]
    shapes = [str(row["query_shape"]) for row in scenarios]
    if len(set(query_ids)) != 15 or len(set(shapes)) != 15:
        raise ValueError("All query IDs and SQL shapes must be distinct")
    repeat_counts = pd.Series([int(row["repetitions"]) for row in scenarios])
    if not repeat_counts.between(1, 5).all():
        raise ValueError("Every scenario must have between one and five episodes")
    if repeat_counts.value_counts().sort_index().to_dict() != {
        1: 3,
        2: 3,
        3: 3,
        4: 3,
        5: 3,
    }:
        raise ValueError("Each repetition count from 1 through 5 must occur three times")
    datasets = contract["datasets"]
    region_counts = [int(datasets[row["dataset"]]["region_count"]) for row in scenarios]
    if set(region_counts) != {2, 3}:
        raise ValueError("Both N=2 and N=3 scenarios are required")
    applicability = contract["action_applicability"]
    if set(applicability["applicable_actions"]) != set(ACTIONS):
        raise ValueError("The Top-K panel must declare all measured actions applicable")
    context_fields = tuple(contract["memory"]["exact_context_fields"])
    required_context_fields = {
        "topology_id",
        "region_count",
        "dataset_profile_id",
        "profile",
    }
    if set(context_fields) != required_context_fields:
        raise ValueError(
            "Exact-query context must include topology, region count, dataset, and runtime profile"
        )
    return scenarios


def _cell_common(
    scenario: dict[str, Any],
    dataset: dict[str, Any],
) -> dict[str, Any]:
    query_id = str(scenario["query_id"])
    region_count = int(dataset["region_count"])
    return {
        "logical_question_id": "dba_local_memory_topk",
        "component_match_id": f"dba_memory_{query_id}",
        "dataset_profile_id": [str(scenario["dataset"])],
        "topology_id": str(dataset["topology_id"]),
        "execution_strategy": "multiregion_union",
        "execution_scope": "gac_multi_edge",
        "target_scope": "global_query",
        "intervention_role": "calibration",
        "intervention_axis": "combined_pressure",
        "pressure_axis": "local_intervention_memory",
        "target_metric": "global_gac_mitigation_gain_log2",
        "dataset_role": "dba_local_memory_panel",
        "scenario_level": "new_query_timeline",
        "repeatability_repetitions": int(scenario["repetitions"]),
        "parameters": {
            "query_shape": [str(scenario["query_shape"])],
            "cutoff_ts": [str(scenario["cutoff_ts"])],
            "limit_k": [int(scenario["limit_k"])],
            "include_apac": [region_count == 3],
        },
    }


def build_manifest(contract: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    scenarios = _validate_contract(contract)
    datasets = contract["datasets"]
    runtime_profiles = contract["runtime_profiles"]
    cells: list[dict[str, Any]] = []
    design_rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        query_id = str(scenario["query_id"])
        dataset = datasets[scenario["dataset"]]
        runtime = runtime_profiles[scenario["profile"]]
        common = _cell_common(scenario, dataset)
        baseline_id = f"{query_id}__baseline"
        cells.append(
            {
                **common,
                "corpus_cell_id": baseline_id,
                "template_id": "gac_fdw_dba_topk_raw",
                "runtime_config_id": str(runtime["baseline"]),
                "pressure_level": "stressed",
                "variant": "stressed",
                "physical_strategy_id": "gac_raw_topk",
                "pressure_pair_key": f"{query_id}__shared_baseline",
            }
        )
        action_specs = {
            "increase_gac_work_mem": (
                "gac_fdw_dba_topk_raw",
                str(runtime["gac_memory"]),
                "gac_memory_increase",
            ),
            "regional_topk_candidates": (
                "gac_fdw_dba_topk_regional",
                str(runtime["baseline"]),
                "regional_topk_candidates",
            ),
            "mitigate_remote_path_bundle": (
                "gac_fdw_dba_topk_raw",
                str(runtime["remote"]),
                "remote_transport_bundle",
            ),
        }
        for action, (template_id, runtime_id, strategy_id) in action_specs.items():
            cells.append(
                {
                    **common,
                    "corpus_cell_id": f"{query_id}__{action}",
                    "template_id": template_id,
                    "runtime_config_id": runtime_id,
                    "pressure_level": "mitigated",
                    "variant": "mitigated",
                    "physical_strategy_id": strategy_id,
                    "pressure_pair_key": f"{query_id}__{action}",
                    "mitigation_action": action,
                }
            )
        design_rows.append(
            {
                **scenario,
                "topology_id": dataset["topology_id"],
                "region_count": int(dataset["region_count"]),
                "condition_count": 4,
                "physical_execution_count": int(scenario["repetitions"]) * 4,
            }
        )
    execution = contract["execution"]
    manifest = {
        "corpus_id": contract["corpus_id"],
        "corpus_version": contract["contract_version"],
        "batch_id": "batch-dba-local-memory-v1",
        "collection_contract_version": "fuzzy-intervention-memory-v1",
        "description": contract["description"],
        "query_groups": "../../../workloads/corpus/query-groups.yml",
        "runtime_catalog": "../../../workloads/corpus/runtime-configs.yml",
        "dataset_profiles": {
            dataset_id: {
                "profile": f"../../../{specification['profile']}",
                "load_method": specification["load_method"],
            }
            for dataset_id, specification in datasets.items()
        },
        "execution_budget": {
            "hard_timeout_seconds": int(execution["hard_timeout_seconds"]),
            "timeout_grace_seconds": int(execution["timeout_grace_seconds"]),
        },
        "execution_policy": {
            "cache_policy": "mixed_cache_dba_local_memory",
            "order_policy": "deterministic_interleaved_shuffle",
            "shuffle_seed": int(execution["shuffle_seed"]),
            "repetitions_default": 1,
            "record_run_order": True,
            "record_buffer_features": True,
            "fdw_auto_explain": True,
            "fdw_auto_explain_regions": ["active_regions"],
            "os_sampler": True,
            "os_sampler_node_groups": ["active_regions"],
            "result_signature": True,
            "result_signature_scope": execution["result_signature_scope"],
            "network_profile_probe": True,
            "remote_edge_context": True,
            "group_runtime_configs_by_active_scope": True,
        },
        "cells": cells,
    }
    return manifest, pd.DataFrame(design_rows)


def prepare(contract_path: Path, source_dir: Path) -> Path:
    contract = read_yaml(contract_path)
    manifest, design = build_manifest(contract)
    source_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = source_dir / "corpus_manifest.yml"
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, width=100),
        encoding="utf-8",
    )
    design.to_csv(source_dir / "design_scenarios.csv", index=False)
    summary = {
        "contract_version": contract["contract_version"],
        "scenario_count": int(len(design)),
        "distinct_sql_shape_count": int(design["query_shape"].nunique()),
        "condition_count": int(design["condition_count"].sum()),
        "intervention_episode_count": int(design["repetitions"].sum()),
        "physical_execution_count": int(design["physical_execution_count"].sum()),
        "scenario_count_by_region_count": {
            str(key): int(value)
            for key, value in design["region_count"].value_counts().sort_index().items()
        },
        "scenario_count_by_repetitions": {
            str(key): int(value)
            for key, value in design["repetitions"].value_counts().sort_index().items()
        },
    }
    write_json(source_dir / "design_summary.json", summary)
    return manifest_path


def _rendered_instances(rendered_dir: Path) -> pd.DataFrame:
    paths = sorted(rendered_dir.glob("groups/*/instance_manifest.csv"))
    if not paths:
        raise FileNotFoundError(f"No rendered instance manifests under {rendered_dir}")
    return pd.concat((pd.read_csv(path) for path in paths), ignore_index=True)


def validate_design(contract_path: Path, rendered_dir: Path, out_dir: Path) -> None:
    contract = read_yaml(contract_path)
    scenarios = _validate_contract(contract)
    rows = _rendered_instances(rendered_dir)
    expected_executions = sum(int(row["repetitions"]) * 4 for row in scenarios)
    checks = {
        "scenario_count": len(scenarios) == 15,
        "rendered_execution_count": len(rows) == expected_executions == 180,
        "condition_count": rows["condition_id"].nunique() == 60,
        "query_count": rows["component_match_id"].nunique() == 15,
        "n2_and_n3_present": set(rows["topology_id"].astype(str))
        == {"eu_us_gac", "eu_us_apac_gac"},
        "three_actions_present": set(
            rows.loc[rows["mitigation_action"].notna(), "mitigation_action"].astype(str)
        )
        == set(ACTIONS),
    }
    expected_by_query = {
        f"dba_memory_{row['query_id']}": int(row["repetitions"]) * 4 for row in scenarios
    }
    observed_by_query = rows["component_match_id"].astype(str).value_counts().to_dict()
    checks["per_query_repetition_contract"] = observed_by_query == expected_by_query
    status = "PASS" if all(checks.values()) else "FAIL"
    summary = {
        "status": status,
        "checks": checks,
        "rendered_execution_count": int(len(rows)),
        "expected_execution_count": expected_executions,
        "condition_count": int(rows["condition_id"].nunique()),
    }
    write_json(out_dir / "design_validation.json", summary)
    if status != "PASS":
        raise SystemExit(2)


def _load_memory_module() -> Any:
    path = ROOT / "analysis/scripts/agent/101_fuzzy_intervention_memory.py"
    module_name = "memory_analysis_101"
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    try:
        specification.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _first_signature(rows: pd.DataFrame) -> str:
    values = [
        str(value)
        for value in rows.get("result_multiset_sha256", pd.Series(dtype=str))
        if pd.notna(value) and str(value).strip()
    ]
    return values[0] if values else ""


def _collection_validation(
    index_dir: Path,
    executions: pd.DataFrame,
    contract: dict[str, Any],
) -> dict[str, Any]:
    scenarios = _validate_contract(contract)
    expected_execution_count = sum(int(row["repetitions"]) * 4 for row in scenarios)
    expected_condition_count = len(scenarios) * 4
    expected_by_topology: dict[str, int] = {}
    datasets = contract["datasets"]
    for row in scenarios:
        topology = str(datasets[row["dataset"]]["topology_id"])
        expected_by_topology[topology] = expected_by_topology.get(topology, 0) + (
            int(row["repetitions"]) * 4
        )
    validation = contract["collection_validation"]
    workers_per_region = int(validation["workers_per_region"])
    gac_node_count = int(validation["gac_node_count"])
    expected_os_nodes = {
        str(specification["topology_id"]): gac_node_count
        + int(specification["region_count"]) * (workers_per_region + 1)
        for specification in datasets.values()
    }
    query_runs = pd.read_csv(index_dir / "query_runs.csv", low_memory=False)
    edges = pd.read_csv(index_dir / "remote_edge_observations.csv", low_memory=False)
    regions = pd.read_csv(index_dir / "region_fragments.csv", low_memory=False)
    tasks = pd.read_csv(index_dir / "worker_task_fragments.csv", low_memory=False)
    node_artifacts = pd.read_csv(index_dir / "node_artifacts.csv", low_memory=False)
    hardware = pd.read_csv(index_dir / "hardware_nodes.csv", low_memory=False)
    fdw_plans = pd.read_csv(index_dir / "fdw_remote_plans.csv", low_memory=False)
    expected_edge_count = int(
        sum(
            count
            * int(
                next(
                    specification["region_count"]
                    for specification in datasets.values()
                    if str(specification["topology_id"]) == topology
                )
            )
            for topology, count in expected_by_topology.items()
        )
    )
    required_telemetry = [
        "os_cpu_busy_pct_mean",
        "os_cpu_busy_pct_max",
        "os_mem_used_peak_bytes_max",
        "os_mem_available_bytes_min",
        "os_net_rx_bytes_sum",
        "os_net_tx_bytes_sum",
    ]
    signature_counts = query_runs["result_signature_status"].value_counts().to_dict()
    completed_signatures = query_runs[query_runs["result_signature_status"].eq("completed")]
    expected_region_sets = {
        "eu_us_gac": {"eu", "us"},
        "eu_us_apac_gac": {"apac", "eu", "us"},
    }
    observed_regions_match = all(
        {
            value.strip()
            for value in str(row.fdw_auto_explain_observed_regions).split(",")
            if value.strip()
        }
        == expected_region_sets[str(row.topology_id)]
        for row in executions.itertuples()
    )
    logical_manifest_path = index_dir.parent / "logical_run_index_manifest.json"
    logical_manifest = (
        json.loads(logical_manifest_path.read_text(encoding="utf-8"))
        if logical_manifest_path.exists()
        else {}
    )
    checks = {
        "logical_resolver_selected_all": logical_manifest.get("resolved_query_count")
        == expected_execution_count
        and logical_manifest.get("needs_rerun_count") == 0,
        "all_executions_completed": len(query_runs) == expected_execution_count
        and query_runs["execution_status"].eq("completed").all()
        and not query_runs["timed_out"].fillna(False).astype(bool).any(),
        "topology_execution_counts_match": executions["topology_id"].value_counts().to_dict()
        == expected_by_topology,
        "edge_rows_complete": len(edges) == expected_edge_count
        and edges["availability_status"].eq("available").all(),
        "regional_rows_complete": len(regions) == expected_edge_count
        and regions["parse_status"].isin(["ok", "partial"]).all(),
        "worker_task_evidence_complete": tasks["query_run_id"].nunique() == expected_execution_count
        and tasks["parse_status"].isin(["ok", "partial"]).all(),
        "fdw_plans_complete": len(fdw_plans) == expected_edge_count
        and fdw_plans["status"].eq("ok").all()
        and observed_regions_match,
        "os_sampler_node_counts_match": all(
            group["os_sampled_node_count"].eq(expected_os_nodes[topology]).all()
            and group["os_query_aligned_node_count"].eq(expected_os_nodes[topology]).all()
            for topology, group in executions.groupby("topology_id")
        ),
        "os_sampler_alignment_high": executions["os_query_alignment_worst_status"].eq("high").all(),
        "required_os_telemetry_complete": executions[required_telemetry].notna().all().all(),
        "node_artifact_rows_complete": len(node_artifacts)
        == int(executions["os_sampled_node_count"].sum()),
        "network_profiles_applied_and_reset": query_runs["network_intervention_apply_status"]
        .eq("ok")
        .all()
        and query_runs["network_intervention_reset_status"].eq("ok").all(),
        "one_signature_per_condition": len(completed_signatures) == expected_condition_count
        and completed_signatures["condition_id"].nunique() == expected_condition_count
        and signature_counts.get("disabled", 0)
        == expected_execution_count - expected_condition_count,
        "single_hardware_snapshot": hardware["hardware_snapshot_id"].nunique() == 1
        and hardware["node_name"].nunique() == int(validation["provisioned_node_count"]),
        "no_collector_errors": pd.to_numeric(executions["collection_error_count"], errors="coerce")
        .fillna(0)
        .sum()
        == 0
        and pd.to_numeric(executions["remote_error_count"], errors="coerce").fillna(0).sum() == 0,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "counts": {
            "executions": len(query_runs),
            "conditions_with_correctness_signature": len(completed_signatures),
            "remote_edges": len(edges),
            "regional_fragments": len(regions),
            "worker_task_fragments": len(tasks),
            "node_artifacts": len(node_artifacts),
            "hardware_snapshot_ids": int(hardware["hardware_snapshot_id"].nunique()),
            "unique_hardware_nodes": int(hardware["node_name"].nunique()),
        },
        "expected_execution_count_by_topology": expected_by_topology,
        "expected_os_sampled_node_count_by_topology": expected_os_nodes,
        "worker_task_parse_status": tasks["parse_status"].value_counts().to_dict(),
        "fdw_plan_status": fdw_plans["status"].value_counts().to_dict(),
        "result_signature_status": signature_counts,
    }


def build_observed_episodes(
    executions: pd.DataFrame,
    contract: dict[str, Any],
    feature_names: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    design = {f"dba_memory_{row['query_id']}": row for row in _validate_contract(contract)}
    selected = executions[executions["component_match_id"].astype(str).isin(design)].copy()
    selected["repetition_index"] = pd.to_numeric(
        selected["repetition_index"], errors="raise"
    ).astype(int)
    selected["elapsed_seconds"] = pd.to_numeric(selected["elapsed_seconds"], errors="coerce")
    rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    for component_id, specification in sorted(
        design.items(), key=lambda item: int(item[1]["order"])
    ):
        query_id = str(specification["query_id"])
        query_rows = selected[selected["component_match_id"].astype(str).eq(component_id)]
        baseline_all = query_rows[query_rows["variant"].astype(str).eq("stressed")]
        action_all = query_rows[query_rows["mitigation_action"].astype(str).isin(ACTIONS)]
        signatures = {"baseline": _first_signature(baseline_all)}
        for action in ACTIONS:
            signatures[action] = _first_signature(
                action_all[action_all["mitigation_action"].astype(str).eq(action)]
            )
        for repetition in range(int(specification["repetitions"])):
            baseline = baseline_all[baseline_all["repetition_index"].eq(repetition)]
            if len(baseline) != 1:
                continue
            before = baseline.iloc[0]
            action_members: list[pd.Series] = []
            for action in ACTIONS:
                member = action_all[
                    action_all["mitigation_action"].astype(str).eq(action)
                    & action_all["repetition_index"].eq(repetition)
                ]
                if len(member) == 1:
                    action_members.append(member.iloc[0])
            if len(action_members) != len(ACTIONS):
                continue
            episode_id = f"{query_id}::run-{repetition + 1}"
            event = {
                "episode_id": episode_id,
                "episode_order": sum(
                    int(item["repetitions"])
                    for item in contract["scenarios"]
                    if int(item["order"]) < int(specification["order"])
                )
                + repetition
                + 1,
                "query_id": query_id,
                "query_shape": specification["query_shape"],
                "query_order": int(specification["order"]),
                "query_occurrence": repetition + 1,
                "planned_query_occurrences": int(specification["repetitions"]),
                "dataset_profile_id": specification["dataset"],
                "topology_id": str(before["topology_id"]),
                "region_count": int(contract["datasets"][specification["dataset"]]["region_count"]),
                "profile": specification["profile"],
                "baseline_query_run_id": str(before["query_run_id"]),
                "baseline_elapsed_seconds": float(before["elapsed_seconds"]),
                "source_sql_file": str(before.get("source_sql_file", "")),
                "normalized_sql_hash": str(before.get("sql_normalized_hash", "")),
                "applicable_actions_json": json.dumps(
                    contract["action_applicability"]["applicable_actions"],
                    separators=(",", ":"),
                ),
                "applicability_source": contract["action_applicability"]["policy"],
            }
            for feature in feature_names:
                event[f"before__{feature}"] = pd.to_numeric(
                    pd.Series([before.get(feature, np.nan)]), errors="coerce"
                ).iloc[0]
            event_rows.append(event)
            for member in action_members:
                action = str(member["mitigation_action"])
                action_elapsed = float(member["elapsed_seconds"])
                gain = (
                    math.log2(float(before["elapsed_seconds"]) / action_elapsed)
                    if float(before["elapsed_seconds"]) > 0 and action_elapsed > 0
                    else float("nan")
                )
                rows.append(
                    {
                        **{key: event[key] for key in event if not key.startswith("before__")},
                        "mitigation_action": action,
                        "action_query_run_id": str(member["query_run_id"]),
                        "action_elapsed_seconds": action_elapsed,
                        "target_log2_gain": gain,
                        "action_applicable": True,
                        "applicability_source": contract["action_applicability"]["policy"],
                        "result_equal": bool(
                            signatures["baseline"]
                            and signatures[action]
                            and signatures["baseline"] == signatures[action]
                        ),
                    }
                )
    return pd.DataFrame(event_rows), pd.DataFrame(rows)


def _reference_memory(
    contract: dict[str, Any],
    feature_names: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    report = ROOT / contract["memory"]["reference_report"]
    episodes = pd.read_csv(report / "episodes.csv", low_memory=False)
    state_contract = read_yaml(ROOT / contract["memory"]["state_contract"])
    components = set(state_contract["panels"]["gac_topk"]["component_match_ids"])
    episodes = episodes[
        episodes["component_match_id"].astype(str).isin(components)
        & episodes["completed"].astype(bool)
        & episodes["result_equal"].astype(bool)
    ].copy()
    states = episodes[
        ["scenario_id", *[f"before__{name}" for name in feature_names]]
    ].drop_duplicates("scenario_id")
    states["episode_id"] = "reference::" + states["scenario_id"].astype(str)
    states["query_id"] = states["scenario_id"].astype(str)
    states["topology_id"] = "eu_us_gac"
    episodes = episodes.rename(columns={"scenario_id": "memory_state_id"})
    episodes["episode_id"] = "reference::" + episodes["memory_state_id"].astype(str)
    return states, episodes


def _distance_matrix(
    left: np.ndarray,
    right: np.ndarray,
    metric: str,
) -> np.ndarray:
    if metric == "euclidean":
        return np.sqrt(np.sum((left[:, None, :] - right[None, :, :]) ** 2, axis=2))
    if metric == "manhattan":
        return np.sum(np.abs(left[:, None, :] - right[None, :, :]), axis=2)
    if metric == "cosine":
        numerator = left @ right.T
        left_norm = np.linalg.norm(left, axis=1)
        right_norm = np.linalg.norm(right, axis=1)
        denominator = left_norm[:, None] * right_norm[None, :]
        similarity = np.divide(
            numerator,
            denominator,
            out=np.zeros_like(numerator, dtype=float),
            where=denominator > 0,
        )
        both_zero = (left_norm[:, None] == 0) & (right_norm[None, :] == 0)
        similarity[both_zero] = 1.0
        return 1.0 - np.clip(similarity, -1.0, 1.0)
    raise ValueError(f"Unsupported distance metric: {metric}")


def _nearest_threshold(
    values: np.ndarray,
    quantile: float,
    metric: str = "euclidean",
) -> float:
    distances = _distance_matrix(values, values, metric)
    np.fill_diagonal(distances, np.inf)
    nearest = distances.min(axis=1)
    return float(np.quantile(nearest[np.isfinite(nearest)], quantile))


def _estimate_from_memory(
    test_value: np.ndarray,
    memory_values: np.ndarray,
    memory_states: pd.DataFrame,
    memory_outcomes: pd.DataFrame,
    *,
    neighbors: int,
    epsilon: float,
    distance_metric: str = "euclidean",
    excluded_query_id: str = "",
    excluded_normalized_sql_hash: str = "",
) -> tuple[dict[str, float], list[dict[str, Any]], float, int]:
    eligible = pd.Series(True, index=memory_states.index)
    if excluded_query_id:
        eligible &= ~memory_states["query_id"].astype(str).eq(excluded_query_id)
    if excluded_normalized_sql_hash and "normalized_sql_hash" in memory_states.columns:
        eligible &= ~memory_states["normalized_sql_hash"].astype(str).eq(
            excluded_normalized_sql_hash
        )
    memory_states = memory_states.loc[eligible].reset_index(drop=True)
    memory_values = memory_values[eligible.to_numpy()]
    if len(memory_states) == 0:
        return (
            {action: float("nan") for action in ACTIONS},
            [],
            float("nan"),
            0,
        )
    distances = _distance_matrix(test_value[None, :], memory_values, distance_metric)[0]
    order = np.argsort(distances)[: min(neighbors, len(distances))]
    neighbor_rows: list[dict[str, Any]] = []
    weights_by_episode: dict[str, float] = {}
    for index in order:
        state = memory_states.iloc[int(index)]
        episode_id = str(state["episode_id"])
        weight = 1.0 / (float(distances[index]) + epsilon)
        weights_by_episode[episode_id] = weight
        gains = memory_outcomes[memory_outcomes["episode_id"].astype(str).eq(episode_id)].set_index(
            "mitigation_action"
        )["target_log2_gain"]
        neighbor_rows.append(
            {
                "episode_id": episode_id,
                "query_id": str(state["query_id"]),
                "normalized_sql_hash": str(state.get("normalized_sql_hash", "")),
                "topology_id": str(state["topology_id"]),
                "distance": float(distances[index]),
                "weight": weight,
                "action_gains": {
                    action: float(gains[action]) for action in ACTIONS if action in gains
                },
            }
        )
    predictions: dict[str, float] = {}
    for action in ACTIONS:
        rows = memory_outcomes[
            memory_outcomes["mitigation_action"].astype(str).eq(action)
            & memory_outcomes["episode_id"].astype(str).isin(weights_by_episode)
        ]
        weights = np.asarray(
            [weights_by_episode[str(value)] for value in rows["episode_id"]],
            dtype=float,
        )
        values = rows["target_log2_gain"].to_numpy(dtype=float)
        predictions[action] = (
            float(np.average(values, weights=weights)) if len(values) else float("nan")
        )
    return predictions, neighbor_rows, float(distances[order[0]]), len(memory_states)


def _status(
    *,
    memory_count: int,
    nearest_distance: float,
    coverage_threshold: float,
    minimum_history: int,
) -> str:
    if memory_count == 0:
        return "cold_start_abstention"
    if not np.isfinite(nearest_distance) or nearest_distance > coverage_threshold:
        return "outside_reference_coverage"
    if memory_count < minimum_history:
        return "provisional_local_evidence"
    return "available"


def _decision_actions(
    predictions: dict[str, float],
    decision_status: str,
    applicable_actions: tuple[str, ...] = ACTIONS,
) -> tuple[str, str]:
    if not applicable_actions:
        return "", ""
    candidate = (
        max(applicable_actions, key=lambda action: predictions[action])
        if all(np.isfinite(predictions[action]) for action in applicable_actions)
        else ""
    )
    recommendation = candidate if decision_status == "available" else ""
    return candidate, recommendation


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "Nema dostupnih redova."
    view = frame[columns]
    lines = ["| " + " | ".join(columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in view.itertuples(index=False, name=None):
        values: list[str] = []
        for value in row:
            if pd.isna(value):
                rendered = ""
            elif isinstance(value, (float, np.floating)):
                rendered = f"{float(value):.3f}"
            else:
                rendered = str(value)
            values.append(rendered.replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def replay_memory(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    reference_states: pd.DataFrame,
    reference_outcomes: pd.DataFrame,
    reference_values: np.ndarray,
    new_values: np.ndarray,
    *,
    mode: str,
    neighbors: int,
    epsilon: float,
    coverage_threshold: float,
    minimum_history: int,
    exclude_same_query: bool = False,
    distance_metric: str = "euclidean",
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if mode == "warm_start":
        memory_states = reference_states.copy().reset_index(drop=True)
        memory_values = reference_values.copy()
        memory_outcomes = reference_outcomes.copy().reset_index(drop=True)
    else:
        memory_states = pd.DataFrame(columns=reference_states.columns)
        memory_values = np.empty((0, new_values.shape[1]), dtype=float)
        memory_outcomes = pd.DataFrame(columns=reference_outcomes.columns)
    timeline_rows: list[dict[str, Any]] = []
    episode_documents: list[dict[str, Any]] = []
    timeline_mode = f"{mode}_cross_query" if exclude_same_query else mode
    ordered = events.sort_values("episode_order").reset_index(drop=True)
    for index, event in ordered.iterrows():
        event_id = str(event["episode_id"])
        actual = outcomes[outcomes["episode_id"].astype(str).eq(event_id)].copy()
        applicable_actions = tuple(json.loads(str(event["applicable_actions_json"])))
        predictions, neighbor_rows, nearest, eligible_memory_count = _estimate_from_memory(
            new_values[index],
            memory_values,
            memory_states,
            memory_outcomes,
            neighbors=neighbors,
            epsilon=epsilon,
            distance_metric=distance_metric,
            excluded_query_id=(str(event["query_id"]) if exclude_same_query else ""),
            excluded_normalized_sql_hash=(
                str(event["normalized_sql_hash"]) if exclude_same_query else ""
            ),
        )
        status = _status(
            memory_count=eligible_memory_count,
            nearest_distance=nearest,
            coverage_threshold=coverage_threshold,
            minimum_history=minimum_history,
        )
        candidate_action, predicted_action = _decision_actions(
            predictions, status, applicable_actions
        )
        actual_by_action = actual.set_index("mitigation_action")["target_log2_gain"]
        actual_action = str(actual_by_action.loc[list(applicable_actions)].idxmax())
        regret = (
            float(actual_by_action.max() - actual_by_action[predicted_action])
            if predicted_action
            else float("nan")
        )
        top1 = bool(predicted_action and predicted_action == actual_action)
        candidate_regret = (
            float(actual_by_action.max() - actual_by_action[candidate_action])
            if candidate_action
            else float("nan")
        )
        candidate_top1 = bool(candidate_action and candidate_action == actual_action)
        if "normalized_sql_hash" in memory_states.columns:
            same_query_history = int(
                memory_states["normalized_sql_hash"]
                .astype(str)
                .eq(str(event["normalized_sql_hash"]))
                .sum()
            )
        else:
            same_query_history = int(
                memory_states["query_id"].astype(str).eq(str(event["query_id"])).sum()
            )
        row = {
            "memory_mode": timeline_mode,
            "episode_order": int(event["episode_order"]),
            "episode_id": event_id,
            "query_id": event["query_id"],
            "normalized_sql_hash": event["normalized_sql_hash"],
            "query_shape": event["query_shape"],
            "query_occurrence": int(event["query_occurrence"]),
            "planned_query_occurrences": int(event["planned_query_occurrences"]),
            "topology_id": event["topology_id"],
            "region_count": int(event["region_count"]),
            "dataset_profile_id": event["dataset_profile_id"],
            "profile": event["profile"],
            "applicable_actions_json": event["applicable_actions_json"],
            "applicability_source": event["applicability_source"],
            "baseline_elapsed_seconds": float(event["baseline_elapsed_seconds"]),
            "history_state_count_before": int(len(memory_states)),
            "eligible_history_state_count_before": eligible_memory_count,
            "same_query_history_count_before": same_query_history,
            "nearest_distance": nearest,
            "coverage_threshold": coverage_threshold,
            "distance_metric": distance_metric,
            "decision_status": status,
            "candidate_action": candidate_action,
            "predicted_action": predicted_action,
            "actual_best_action": actual_action,
            "top1_correct": top1,
            "regret_log2": regret,
            "candidate_top1_correct": candidate_top1,
            "candidate_regret_log2": candidate_regret,
            "evidence_gac_fanin_rows": event.get("before__coordinator_fanin_rows"),
            "evidence_gac_temp_blocks": event.get("before__coordinator_temp_written_blocks"),
            "evidence_remote_bytes": event.get("before__edge_remote_bytes_sum"),
            "evidence_remote_boundary_wait_ms": event.get("before__edge_boundary_wait_ms_sum"),
            "evidence_remote_rtt_ms": event.get("before__edge_rtt_context_median_ms_mean"),
            "evidence_cpu_busy_max_pct": event.get("before__os_cpu_busy_pct_max"),
            **{f"predicted_gain__{action}": predictions[action] for action in ACTIONS},
            **{f"actual_gain__{action}": float(actual_by_action[action]) for action in ACTIONS},
            "neighbor_evidence_json": json.dumps(
                neighbor_rows, sort_keys=True, separators=(",", ":")
            ),
        }
        timeline_rows.append(row)
        evidence = {
            "elapsed_seconds": float(event["baseline_elapsed_seconds"]),
            "gac_fanin_rows": event.get("before__coordinator_fanin_rows"),
            "gac_non_foreign_time_share": event.get(
                "before__coordinator_non_foreign_time_share_proxy"
            ),
            "gac_temp_blocks": event.get("before__coordinator_temp_written_blocks"),
            "remote_edge_count": event.get("before__edge_count"),
            "remote_bytes": event.get("before__edge_remote_bytes_sum"),
            "remote_boundary_wait_ms": event.get("before__edge_boundary_wait_ms_sum"),
            "remote_rtt_ms": event.get("before__edge_rtt_context_median_ms_mean"),
            "regional_rows_cv": event.get("before__remote_region_actual_rows_cv"),
            "worker_rows_cv": event.get("before__worker_task_actual_rows_cv"),
            "cpu_busy_max_pct": event.get("before__os_cpu_busy_pct_max"),
        }
        episode_documents.append(
            {
                "memory_mode": timeline_mode,
                "episode": {key: row[key] for key in row if not key.endswith("_json")},
                "state_evidence": evidence,
                "neighbors_used_before_decision": neighbor_rows,
                "observed_action_outcomes": actual[
                    [
                        "mitigation_action",
                        "action_elapsed_seconds",
                        "target_log2_gain",
                        "result_equal",
                    ]
                ].to_dict(orient="records"),
                "memory_state_count_after": int(len(memory_states) + 1),
            }
        )
        state_row = event.to_frame().T.copy()
        memory_states = pd.concat([memory_states, state_row], ignore_index=True)
        memory_values = np.vstack([memory_values, new_values[index]])
        memory_outcomes = pd.concat([memory_outcomes, actual], ignore_index=True)
    return pd.DataFrame(timeline_rows), episode_documents


def _knn_sensitivity(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    reference_states: pd.DataFrame,
    reference_outcomes: pd.DataFrame,
    reference_values: np.ndarray,
    new_values: np.ndarray,
    *,
    epsilon: float,
    minimum_history: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for metric in ("euclidean", "manhattan", "cosine"):
        for neighbors in (1, 3, 5, 7):
            for quantile in (0.90, 0.95, 0.99, 1.00):
                threshold = _nearest_threshold(reference_values, quantile, metric)
                timeline, _ = replay_memory(
                    events,
                    outcomes,
                    reference_states,
                    reference_outcomes,
                    reference_values,
                    new_values,
                    mode="warm_start",
                    neighbors=neighbors,
                    epsilon=epsilon,
                    coverage_threshold=threshold,
                    minimum_history=minimum_history,
                    exclude_same_query=True,
                    distance_metric=metric,
                )
                predicted = timeline[timeline["predicted_action"].astype(str).ne("")]
                rows.append(
                    {
                        "distance_metric": metric,
                        "neighbors": neighbors,
                        "coverage_quantile": quantile,
                        "coverage_threshold": threshold,
                        "episode_count": len(timeline),
                        "recommendation_count": len(predicted),
                        "coverage": len(predicted) / len(timeline),
                        "top1_accuracy": (
                            float(predicted["top1_correct"].mean())
                            if not predicted.empty
                            else float("nan")
                        ),
                        "mean_regret_log2": (
                            float(predicted["regret_log2"].mean())
                            if not predicted.empty
                            else float("nan")
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _coverage_regret_curve(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    reference_states: pd.DataFrame,
    reference_outcomes: pd.DataFrame,
    reference_values: np.ndarray,
    new_values: np.ndarray,
    *,
    neighbors: int,
    epsilon: float,
    minimum_history: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for quantile in (0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.99, 1.00):
        threshold = _nearest_threshold(reference_values, quantile, "euclidean")
        timeline, _ = replay_memory(
            events,
            outcomes,
            reference_states,
            reference_outcomes,
            reference_values,
            new_values,
            mode="warm_start",
            neighbors=neighbors,
            epsilon=epsilon,
            coverage_threshold=threshold,
            minimum_history=minimum_history,
            exclude_same_query=True,
            distance_metric="euclidean",
        )
        predicted = timeline[timeline["predicted_action"].astype(str).ne("")]
        rows.append(
            {
                "coverage_quantile": quantile,
                "coverage_threshold": threshold,
                "episode_count": len(timeline),
                "recommendation_count": len(predicted),
                "coverage": len(predicted) / len(timeline),
                "top1_accuracy": (
                    float(predicted["top1_correct"].mean())
                    if not predicted.empty
                    else float("nan")
                ),
                "mean_regret_log2": (
                    float(predicted["regret_log2"].mean())
                    if not predicted.empty
                    else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows)


def _retrieval_timing(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    reference_states: pd.DataFrame,
    reference_outcomes: pd.DataFrame,
    reference_values: np.ndarray,
    new_values: np.ndarray,
    *,
    neighbors: int,
    epsilon: float,
    repetitions: int = 500,
) -> dict[str, Any]:
    ordered = events.sort_values("episode_order").reset_index(drop=True)
    query = ordered.iloc[-1]
    query_value = new_values[-1]
    prior_states = pd.concat([reference_states, ordered.iloc[:-1]], ignore_index=True)
    prior_values = np.vstack([reference_values, new_values[:-1]])
    prior_outcomes = pd.concat(
        [
            reference_outcomes,
            outcomes[outcomes["episode_id"].isin(ordered.iloc[:-1]["episode_id"])],
        ],
        ignore_index=True,
    )
    context_fields = ("topology_id", "region_count", "dataset_profile_id", "profile")
    exact_key = (
        str(query["normalized_sql_hash"]),
        tuple(str(query[field]) for field in context_fields),
    )
    exact_index = {
        (
            str(row["normalized_sql_hash"]),
            tuple(str(row[field]) for field in context_fields),
        ): str(row["episode_id"])
        for _, row in ordered.iloc[:-1].iterrows()
    }

    def measure(operation: Any) -> tuple[float, float]:
        durations: list[int] = []
        for _ in range(repetitions):
            started = time.perf_counter_ns()
            operation()
            durations.append(time.perf_counter_ns() - started)
        return (
            float(np.median(durations) / 1_000),
            float(np.quantile(durations, 0.95) / 1_000),
        )

    exact_median, exact_p95 = measure(lambda: exact_index.get(exact_key))
    knn_median, knn_p95 = measure(
        lambda: _estimate_from_memory(
            query_value,
            prior_values,
            prior_states,
            prior_outcomes,
            neighbors=neighbors,
            epsilon=epsilon,
            excluded_query_id=str(query["query_id"]),
            excluded_normalized_sql_hash=str(query["normalized_sql_hash"]),
        )
    )
    return {
        "scope": "single_process_offline_microbenchmark",
        "timing_repetitions": repetitions,
        "case_base_state_count": len(prior_states),
        "exact_lookup_median_us": exact_median,
        "exact_lookup_p95_us": exact_p95,
        "knn_retrieval_median_us": knn_median,
        "knn_retrieval_p95_us": knn_p95,
        "interpretation": (
            "Implementation timing at the current small case-base size; not a scalability claim."
        ),
    }


def replay_exact_query_memory(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    context_fields: tuple[str, ...] = (
        "topology_id",
        "region_count",
        "dataset_profile_id",
        "profile",
    ),
) -> pd.DataFrame:
    """Replay exact SQL memory only within an explicitly compatible context."""
    missing_fields = [field for field in context_fields if field not in events.columns]
    if missing_fields:
        raise ValueError(f"Missing exact-query context fields: {missing_fields}")
    history: dict[tuple[str, tuple[str, ...]], list[pd.DataFrame]] = {}
    rows: list[dict[str, Any]] = []
    for _, event in events.sort_values("episode_order").iterrows():
        event_id = str(event["episode_id"])
        sql_hash = str(event["normalized_sql_hash"])
        if not sql_hash:
            raise ValueError(f"Missing normalized SQL hash for {event_id}")
        context_key = tuple(str(event[field]) for field in context_fields)
        if any(not value for value in context_key):
            raise ValueError(f"Incomplete exact-query context for {event_id}: {context_key}")
        memory_key = (sql_hash, context_key)
        actual = outcomes[outcomes["episode_id"].astype(str).eq(event_id)].copy()
        applicable_actions = tuple(
            json.loads(str(event.get("applicable_actions_json", json.dumps(ACTIONS))))
        )
        prior = history.get(memory_key, [])
        same_sql_history_count = sum(
            len(value) for (known_sql, _), value in history.items() if known_sql == sql_hash
        )
        actual_by_action = actual.set_index("mitigation_action")["target_log2_gain"]
        actual_action = str(actual_by_action.loc[list(applicable_actions)].idxmax())
        if prior:
            prior_outcomes = pd.concat(prior, ignore_index=True)
            predictions = {
                action: float(
                    prior_outcomes[prior_outcomes["mitigation_action"].astype(str).eq(action)][
                        "target_log2_gain"
                    ].median()
                )
                for action in ACTIONS
            }
            status = "available"
            candidate_action, predicted_action = _decision_actions(
                predictions, status, applicable_actions
            )
        else:
            predictions = {action: float("nan") for action in ACTIONS}
            status = (
                "exact_query_context_unseen"
                if same_sql_history_count
                else "exact_query_unseen"
            )
            candidate_action = ""
            predicted_action = ""
        regret = (
            float(actual_by_action.max() - actual_by_action[predicted_action])
            if predicted_action
            else float("nan")
        )
        rows.append(
            {
                "memory_mode": "exact_query_memory",
                "episode_order": int(event["episode_order"]),
                "episode_id": event_id,
                "query_id": event["query_id"],
                "normalized_sql_hash": event["normalized_sql_hash"],
                "query_shape": event["query_shape"],
                "query_occurrence": int(event["query_occurrence"]),
                "planned_query_occurrences": int(event["planned_query_occurrences"]),
                "topology_id": event["topology_id"],
                "region_count": int(event["region_count"]),
                "dataset_profile_id": event["dataset_profile_id"],
                "profile": event["profile"],
                "applicable_actions_json": event.get(
                    "applicable_actions_json", json.dumps(ACTIONS, separators=(",", ":"))
                ),
                "applicability_source": event.get(
                    "applicability_source", "legacy_all_actions"
                ),
                "exact_context_fields": ",".join(context_fields),
                "exact_context_key": json.dumps(context_key, separators=(",", ":")),
                "baseline_elapsed_seconds": float(event["baseline_elapsed_seconds"]),
                "history_state_count_before": sum(len(value) for value in history.values()),
                "eligible_history_state_count_before": len(prior),
                "same_query_history_count_before": len(prior),
                "same_sql_history_count_before": same_sql_history_count,
                "nearest_distance": float("nan"),
                "coverage_threshold": float("nan"),
                "decision_status": status,
                "candidate_action": candidate_action,
                "predicted_action": predicted_action,
                "actual_best_action": actual_action,
                "top1_correct": bool(predicted_action and predicted_action == actual_action),
                "regret_log2": regret,
                "candidate_top1_correct": bool(
                    candidate_action and candidate_action == actual_action
                ),
                "candidate_regret_log2": regret,
                "evidence_gac_fanin_rows": event.get("before__coordinator_fanin_rows"),
                "evidence_gac_temp_blocks": event.get("before__coordinator_temp_written_blocks"),
                "evidence_remote_bytes": event.get("before__edge_remote_bytes_sum"),
                "evidence_remote_boundary_wait_ms": event.get("before__edge_boundary_wait_ms_sum"),
                "evidence_remote_rtt_ms": event.get("before__edge_rtt_context_median_ms_mean"),
                "evidence_cpu_busy_max_pct": event.get("before__os_cpu_busy_pct_max"),
                **{f"predicted_gain__{action}": predictions[action] for action in ACTIONS},
                **{f"actual_gain__{action}": float(actual_by_action[action]) for action in ACTIONS},
                "neighbor_evidence_json": json.dumps(
                    [
                        {
                            "episode_id": str(frame.iloc[0]["episode_id"]),
                            "normalized_sql_hash": sql_hash,
                            "exact_context_key": context_key,
                            "action_gains": {
                                action: float(
                                    frame.set_index("mitigation_action").loc[
                                        action, "target_log2_gain"
                                    ]
                                )
                                for action in ACTIONS
                            },
                        }
                        for frame in prior
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
        history.setdefault(memory_key, []).append(actual)
    return pd.DataFrame(rows)


def build_hierarchical_timeline(
    timeline: pd.DataFrame,
    *,
    cross_query_mode: str,
    output_mode: str,
) -> pd.DataFrame:
    """Route known SQL to exact memory and unseen SQL to cross-query kNN."""
    exact = timeline[timeline["memory_mode"].eq("exact_query_memory")].set_index(
        "episode_id", drop=False
    )
    cross_query = timeline[timeline["memory_mode"].eq(cross_query_mode)].set_index(
        "episode_id", drop=False
    )
    if set(exact.index) != set(cross_query.index):
        raise ValueError("Exact-query and cross-query timelines do not align")
    rows: list[dict[str, Any]] = []
    for episode_id in cross_query.sort_values("episode_order").index:
        exact_row = exact.loc[episode_id]
        if str(exact_row["predicted_action"]):
            selected = exact_row.copy()
            route = "exact_query_memory"
        else:
            selected = cross_query.loc[episode_id].copy()
            route = "cross_query_knn"
        selected["memory_mode"] = output_mode
        selected["decision_route"] = route
        rows.append(selected.to_dict())
    return pd.DataFrame(rows)


def _summary(timeline: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in timeline.groupby(["memory_mode", "region_count"], sort=True):
        evaluated = group[group["predicted_action"].astype(str).ne("")]
        candidates = group[group["candidate_action"].astype(str).ne("")]
        rows.append(
            {
                "memory_mode": keys[0],
                "region_count": keys[1],
                "episode_count": len(group),
                "prediction_count": len(evaluated),
                "candidate_count": len(candidates),
                "available_count": int(group["decision_status"].eq("available").sum()),
                "outside_coverage_count": int(
                    group["decision_status"].eq("outside_reference_coverage").sum()
                ),
                "top1_accuracy": (
                    float(evaluated["top1_correct"].mean()) if not evaluated.empty else float("nan")
                ),
                "mean_regret_log2": (
                    float(evaluated["regret_log2"].mean()) if not evaluated.empty else float("nan")
                ),
                "candidate_top1_accuracy": (
                    float(candidates["candidate_top1_correct"].mean())
                    if not candidates.empty
                    else float("nan")
                ),
                "candidate_mean_regret_log2": (
                    float(candidates["candidate_regret_log2"].mean())
                    if not candidates.empty
                    else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows)


def _occurrence_summary(timeline: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in timeline.groupby(["memory_mode", "query_occurrence"], sort=True):
        evaluated = group[group["predicted_action"].astype(str).ne("")]
        candidates = group[group["candidate_action"].astype(str).ne("")]
        rows.append(
            {
                "memory_mode": keys[0],
                "query_occurrence": keys[1],
                "query_count": len(group),
                "available_count": int(group["decision_status"].eq("available").sum()),
                "recommendation_count": len(evaluated),
                "top1_accuracy": (
                    float(evaluated["top1_correct"].mean()) if not evaluated.empty else float("nan")
                ),
                "mean_regret_log2": (
                    float(evaluated["regret_log2"].mean()) if not evaluated.empty else float("nan")
                ),
                "candidate_top1_accuracy": (
                    float(candidates["candidate_top1_correct"].mean())
                    if not candidates.empty
                    else float("nan")
                ),
                "candidate_mean_regret_log2": (
                    float(candidates["candidate_regret_log2"].mean())
                    if not candidates.empty
                    else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows)


def _method_comparison(
    timeline: pd.DataFrame,
    reference_outcomes: pd.DataFrame,
    observed_outcomes: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    action_medians = reference_outcomes.groupby("mitigation_action")["target_log2_gain"].median()
    static_action = str(action_medians.idxmax())
    observed = observed_outcomes.pivot(
        index="episode_id", columns="mitigation_action", values="target_log2_gain"
    )
    actual_best = observed.idxmax(axis=1)
    rows.append(
        {
            "method": "static_action_median",
            "episode_count": len(observed),
            "recommendation_count": len(observed),
            "coverage": 1.0,
            "top1_accuracy": float(actual_best.eq(static_action).mean()),
            "mean_regret_log2": float((observed.max(axis=1) - observed[static_action]).mean()),
            "fixed_action": static_action,
        }
    )
    method_names = {
        "cold_start": "knn_cold_start",
        "warm_start": "knn_warm_start",
        "cold_start_cross_query": "knn_cold_start_excluding_same_query",
        "warm_start_cross_query": "knn_warm_start_excluding_same_query",
        "exact_query_memory": "exact_query_memory",
        "hierarchical_cold_start": "hierarchical_cold_start",
        "hierarchical_warm_start": "hierarchical_warm_start",
    }
    for mode, group in timeline.groupby("memory_mode", sort=True):
        evaluated = group[group["predicted_action"].astype(str).ne("")]
        rows.append(
            {
                "method": method_names.get(mode, mode),
                "episode_count": len(group),
                "recommendation_count": len(evaluated),
                "coverage": len(evaluated) / len(group),
                "top1_accuracy": float(evaluated["top1_correct"].mean()),
                "mean_regret_log2": float(evaluated["regret_log2"].mean()),
                "fixed_action": "",
            }
        )
    return pd.DataFrame(rows)


def _first_occurrence_comparison(
    timeline: pd.DataFrame,
    reference_outcomes: pd.DataFrame,
    observed_outcomes: pd.DataFrame,
) -> pd.DataFrame:
    first = timeline[timeline["query_occurrence"].eq(1)].copy()
    first_ids = set(first["episode_id"].astype(str))
    first_outcomes = observed_outcomes[observed_outcomes["episode_id"].astype(str).isin(first_ids)]
    result = _method_comparison(first, reference_outcomes, first_outcomes)
    result.insert(0, "evaluation_scope", "first_occurrence_per_query")
    return result


def _matched_first_occurrence_comparison(
    timeline: pd.DataFrame,
    reference_outcomes: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compare warm cross-query kNN and its static baseline on identical episodes."""
    warm = timeline[
        timeline["memory_mode"].eq("warm_start_cross_query")
        & timeline["query_occurrence"].eq(1)
        & timeline["predicted_action"].astype(str).ne("")
    ].copy()
    action_medians = reference_outcomes.groupby("mitigation_action")[
        "target_log2_gain"
    ].median()
    static_action = str(action_medians.idxmax())
    gain_columns = [f"actual_gain__{action}" for action in ACTIONS]
    warm["static_top1_correct"] = warm["actual_best_action"].astype(str).eq(
        static_action
    )
    warm["static_regret_log2"] = (
        warm[gain_columns].max(axis=1) - warm[f"actual_gain__{static_action}"]
    )
    rows = [
        {
            "evaluation_scope": "matched_warm_first_occurrences",
            "method": "static_action_median",
            "episode_count": int(len(warm)),
            "top1_correct_count": int(warm["static_top1_correct"].sum()),
            "top1_accuracy": float(warm["static_top1_correct"].mean()),
            "mean_regret_log2": float(warm["static_regret_log2"].mean()),
            "fixed_action": static_action,
        },
        {
            "evaluation_scope": "matched_warm_first_occurrences",
            "method": "knn_warm_start_excluding_same_query",
            "episode_count": int(len(warm)),
            "top1_correct_count": int(warm["top1_correct"].sum()),
            "top1_accuracy": float(warm["top1_correct"].mean()),
            "mean_regret_log2": float(warm["regret_log2"].mean()),
            "fixed_action": "",
        },
    ]
    details = {
        "evaluation_scope": "matched_warm_first_occurrences",
        "episode_count": int(len(warm)),
        "knn_only_correct_count": int(
            (warm["top1_correct"] & ~warm["static_top1_correct"]).sum()
        ),
        "static_only_correct_count": int(
            (~warm["top1_correct"] & warm["static_top1_correct"]).sum()
        ),
        "both_correct_count": int(
            (warm["top1_correct"] & warm["static_top1_correct"]).sum()
        ),
        "both_incorrect_count": int(
            (~warm["top1_correct"] & ~warm["static_top1_correct"]).sum()
        ),
        "mean_regret_improvement_log2": float(
            (warm["static_regret_log2"] - warm["regret_log2"]).mean()
        ),
        "interpretation": (
            "Descriptive paired comparison on the purposively selected panel; "
            "not a population confidence statement."
        ),
    }
    return pd.DataFrame(rows), details


def _action_outcome_summary(observed_outcomes: pd.DataFrame) -> pd.DataFrame:
    matrix = observed_outcomes.pivot(
        index="episode_id", columns="mitigation_action", values="target_log2_gain"
    )
    best = matrix.idxmax(axis=1)
    rows = []
    for action in ACTIONS:
        values = matrix[action]
        rows.append(
            {
                "mitigation_action": action,
                "episode_count": len(values),
                "median_log2_gain": float(values.median()),
                "best_action_count": int(best.eq(action).sum()),
                "best_action_share": float(best.eq(action).mean()),
            }
        )
    return pd.DataFrame(rows)


def _write_generalization_checks(
    out_dir: Path,
    methods: pd.DataFrame,
    first_occurrences: pd.DataFrame,
    matched_first_occurrences: pd.DataFrame,
    matched_details: dict[str, Any],
    action_summary: pd.DataFrame,
) -> None:
    report = f"""# Offline provjere lokalne memorije

## Pitanja

1. Moze li obicno pamcenje identicnog normalizovanog SQL-a objasniti rezultat?
2. Prenosi li kNN iskustvo kada su susjedi istog normalizovanog SQL-a zabranjeni?
3. Sta sistem zna pri prvom susretu sa svakim od 15 SQL oblika?

Sve odluke koriste samo epizode dostupne prije posmatrane epizode. Nije izveden
novi infrastrukturni run.

## Ukupni rezultat

{_markdown_table(methods, list(methods.columns))}

Exact-query memorija je namjerno stroga: prije prve epizode identicnog
normalizovanog SQL-a apstinira, a zatim koristi medijanu njegovih ranijih
izmjerenih ishoda po akciji. Cross-query kNN iz svakog susjedstva uklanja sva
ranija izvrsenja istog normalizovanog SQL-a.

`hierarchical_cold_start` i `hierarchical_warm_start` predstavljaju stvarni
operativni algoritam: poznat normalizovani SQL ide kroz direktnu memoriju, a
nepoznat SQL kroz cross-query fizicku slicnost i provjeru pokrivenosti.

## Samo prvo pojavljivanje SQL oblika

{_markdown_table(first_occurrences, list(first_occurrences.columns))}

Ovaj presjek ne moze imati korist od ranijeg izvrsavanja istog SQL-a. Zato je
primarna provjera prenosa fizicke reprezentacije izmedju razlicitih upita.

## Upareno poredjenje na istim prvim pojavama

{_markdown_table(matched_first_occurrences, list(matched_first_occurrences.columns))}

Warm-start kNN i staticka akcija ovdje se porede samo na istih
{matched_details['episode_count']} epizoda koje je kNN pokrio. kNN je bio
jedini tacan u {matched_details['knn_only_correct_count']} slucaja, staticka
akcija ni u jednom, a prosjecno smanjenje propustenog dobitka iznosilo je
{matched_details['mean_regret_improvement_log2']:.3f} na logaritamskoj skali.
Ovo je deskriptivna provjera namjerno odabranog panela, a ne populacijski
interval pouzdanosti.

## Uloga tri akcije

{_markdown_table(action_summary, list(action_summary.columns))}

`increase_gac_work_mem` je negativna kontrola, a ne treca ravnopravno uspjesna
akcija. Panel zato prvenstveno provjerava razlikovanje remote mitigacije i
regionalnog Top-K rewritea uz odbacivanje neproduktivne memorijske akcije.

## Granice tumacenja

- Savrsen exact-query rezultat vrijedi samo nakon prvog izmjerenog ishoda istog
  normalizovanog SQL-a i predstavlja memoizaciju lokalnog iskustva.
- Cross-query rezultat testira prenos iz drugih SQL oblika, ali samo unutar
  posmatranog GAC Top-K panela i tri unaprijed poznate akcije.
- N=3 epizode dolaze kasnije i koriste druge SQL oblike. Zato ovaj eksperiment
  pokazuje apstinenciju i naknadnu lokalnu adaptaciju, a ne izolovanu kauzalnu
  generalizaciju sa N=2 na N=3.
"""
    (out_dir / "GENERALIZATION_CHECKS.md").write_text(report, encoding="utf-8")


def _write_report(
    out_dir: Path,
    timeline: pd.DataFrame,
    summary: pd.DataFrame,
    occurrences: pd.DataFrame,
    methods: pd.DataFrame,
    first_occurrences: pd.DataFrame,
    coverage_threshold: float,
    reference_episode_count: int,
) -> None:
    warm = timeline[timeline["memory_mode"].eq("warm_start")].copy()
    columns = [
        "episode_order",
        "query_id",
        "query_occurrence",
        "region_count",
        "decision_status",
        "candidate_action",
        "predicted_action",
        "actual_best_action",
        "top1_correct",
        "regret_log2",
    ]
    report = f"""# DBA prikaz lokalne intervencijske memorije

Panel sadrzi 15 novih SQL oblika i 45 vremenski uredjenih intervencijskih
epizoda. Jedna epizoda obuhvata pocetno izvrsenje i tri pojedinacno primijenjene
poznate akcije. Procjena se pravi prije nego sto se ishodi te epizode dodaju u
memoriju. Nema pristupa buducim epizodama.

## Ugovor prikaza

- `cold_start` pocinje bez ranijih ishoda i eksplicitno apstinira.
- `warm_start` koristi {reference_episode_count} ranijih lokalnih GAC Top-K epizoda
  kao pocetnu memoriju.
- `exact_query_memory` koristi samo ranije ishode identicnog normalizovanog SQL-a.
- `*_cross_query` kNN varijante izbacuju sva ranija ponavljanja istog
  normalizovanog SQL hasha, uz `query_id` kao dodatni sigurnosni identitet.
- `hierarchical_*` prvo koristi exact-query memoriju, a za nepoznat SQL koristi
  odgovarajuci cross-query kNN ili apstinira.
- udaljenost veca od P99 lokalne referentne udaljenosti ({coverage_threshold:.3f})
  daje status `outside_reference_coverage`.
- `candidate_action` prikazuje najvisi trenutni skor i kada dokaz jos nije dovoljan.
- `predicted_action` je stvarna preporuka i ostaje prazna dok status nije `available`.
- izlaz rangira samo tri ranije poznate akcije i ne generise novu optimizaciju.

## Ukupni rezultat

{_markdown_table(summary, list(summary.columns))}

## Poredjenje sa statickim poretkom akcija

{_markdown_table(methods, list(methods.columns))}

Staticki baseline uvijek bira akciju sa najvecim medijanom u ranijem lokalnom
panelu. kNN koristi iste historijske ishode, ali odluku uslovljava fizickom
slicnoscu trenutnog post-execution stanja i apstinira izvan pokrivenosti.

## Prvo pojavljivanje svakog od 15 SQL oblika

{_markdown_table(first_occurrences, list(first_occurrences.columns))}

Ovaj presjek uklanja korist od ranijeg izvrsavanja istog upita. Exact-query
memorija po definiciji tada apstinira, dok cross-query kNN moze koristiti samo
druge SQL oblike. N=3 upiti dolaze kasnije u vremenskom redoslijedu i koriste
druge SQL oblike, pa ovaj panel ne daje cist kauzalni N=2/N=3 kontrast.

`increase_gac_work_mem` je namjerno zadrzan kao negativna kontrola. Njegov slab
izmjereni dobitak provjerava hoce li metoda bez fizickog opravdanja preporucivati
akciju samo zato sto je dostupna u skupu kandidata.

## Promjena od prvog do petog susreta sa istim upitom

{_markdown_table(occurrences, list(occurrences.columns))}

## Ono sto DBA vidi prije i poslije svake epizode

{_markdown_table(warm, columns)}

Detaljni fizicki dokaz, svih pet susjeda i izmjereni ishod svake akcije nalaze
se u `episodes/*.json`. `dba_episode_timeline.csv` je masinski citljiv prikaz
istog vremenskog toka.
"""
    (out_dir / "DBA_TIMELINE.md").write_text(report, encoding="utf-8")


def _write_walkthrough(out_dir: Path, timeline: pd.DataFrame) -> None:
    decision_columns = [
        "query_occurrence",
        "same_query_history_count_before",
        "nearest_distance",
        "decision_status",
        "candidate_action",
        "predicted_action",
        "actual_best_action",
        "regret_log2",
    ]
    gain_columns = [
        "query_occurrence",
        "predicted_gain__increase_gac_work_mem",
        "actual_gain__increase_gac_work_mem",
        "predicted_gain__regional_topk_candidates",
        "actual_gain__regional_topk_candidates",
        "predicted_gain__mitigate_remote_path_bundle",
        "actual_gain__mitigate_remote_path_bundle",
    ]
    evidence_columns = [
        "query_occurrence",
        "baseline_elapsed_seconds",
        "evidence_gac_fanin_rows",
        "evidence_gac_temp_blocks",
        "evidence_remote_bytes",
        "evidence_remote_boundary_wait_ms",
        "evidence_remote_rtt_ms",
        "evidence_cpu_busy_max_pct",
    ]
    cold = timeline[timeline["memory_mode"].eq("cold_start")]
    warm = timeline[timeline["memory_mode"].eq("warm_start")]
    cold_q05 = cold[cold["query_id"].eq("q05_event_deviation")]
    warm_q05 = warm[warm["query_id"].eq("q05_event_deviation")]
    cold_q09 = cold[cold["query_id"].eq("q09_tenant_max")].head(2)
    initial = cold.head(3)
    report = f"""# DBA walkthrough: kako lokalna memorija sazrijeva

Ovaj prikaz koristi samo informacije dostupne prije odluke u datoj epizodi.
Nakon sto se stvarni ishodi tri poznate akcije izmjere, epizoda se dodaje u
memoriju. Dobitak `g` je `log2(T_before / T_after)`, pa `g=1` znaci priblizno
dvostruko ubrzanje. Prazna `predicted_action` znaci namjernu apstinenciju.

## Potpuni cold start

Prva epizoda nema historiju, druga ima samo jedan raniji slucaj, a druga pojava
istog upita prvi put prelazi minimalni prag od dvije historijske epizode.

{_markdown_table(initial, ["episode_order", "query_id", *decision_columns])}

## Pet uzastopnih pojava novog N=2 upita

`q05_event_deviation` je koristan primjer zato sto se najbolja akcija razlikuje
od ranijih raw-event upita. Sistem prvo apstinira, zatim uci iz vlastitih ishoda
i mijenja preporuku kada isti lokalni obrazac postane dovoljno zastupljen.

### Odluka prije svake epizode

{_markdown_table(cold_q05, decision_columns)}

### Predvidjeni i naknadno izmjereni dobici

{_markdown_table(cold_q05, gain_columns)}

### Fizicki dokaz pocetnog izvrsenja

{_markdown_table(cold_q05, evidence_columns)}

## Isti upit kada DBA vec ima lokalnu referentnu memoriju

Raniji GAC Top-K panel omogucava ispravnu preporuku od prve nove pojave. Kako
se dodaju vlastite epizode, najblizi susjedi postaju prethodna izvrsenja istog
upita i procijenjeni dobici se priblizavaju izmjerenim vrijednostima.

{_markdown_table(warm_q05, decision_columns)}

## Prelazak sa N=2 na N=3

Prva N=3 epizoda je daleko izvan N=2 referentne pokrivenosti, pa sistem ne daje
preporuku iako prikazuje kandidata. Nakon sto se taj ishod doda u memoriju,
druga pojava istog upita postaje lokalno pokrivena.

{_markdown_table(cold_q09, decision_columns)}

## Kako ovo pomaze DBA-u

- Sistem ne tvrdi da poznaje univerzalno najbolju PostgreSQL optimizaciju.
- Prikazuje najblize ranije slucajeve i stvarne ishode poznatih akcija.
- Novi ili topoloski udaljen slucaj zadrzava fizicki dokaz, ali bez preporuke.
- Ponavljanjem i mjerenjem lokalna memorija moze promijeniti raniji pogresan rang.
- `episodes/*.json` cuva pet susjeda, njihove udaljenosti i sve izmjerene ishode.
"""
    (out_dir / "DBA_WALKTHROUGH.md").write_text(report, encoding="utf-8")


def analyze(contract_path: Path, index_dir: Path, out_dir: Path) -> None:
    contract = read_yaml(contract_path)
    _validate_contract(contract)
    out_dir.mkdir(parents=True, exist_ok=True)
    memory_module = _load_memory_module()
    state_contract = read_yaml(ROOT / contract["memory"]["state_contract"])
    specifications = state_contract["state_representation"]["features"]
    feature_names = list(specifications)
    executions = memory_module.enrich_executions(index_dir)
    collection_validation = _collection_validation(index_dir, executions, contract)
    write_json(out_dir / "collection_validation.json", collection_validation)
    if collection_validation["status"] != "PASS":
        raise ValueError("Collection validation failed; see collection_validation.json")
    events, outcomes = build_observed_episodes(executions, contract, feature_names)
    expected_events = sum(int(row["repetitions"]) for row in contract["scenarios"])
    if len(events) != expected_events or len(outcomes) != expected_events * len(ACTIONS):
        raise ValueError(
            f"Incomplete episode panel: events={len(events)}/{expected_events}, "
            f"outcomes={len(outcomes)}/{expected_events * len(ACTIONS)}"
        )
    if not outcomes["result_equal"].all():
        mismatches = outcomes[~outcomes["result_equal"]]
        mismatches.to_csv(out_dir / "result_mismatches.csv", index=False)
        raise ValueError(f"Found {len(mismatches)} non-equivalent action outcomes")
    reference_states, reference_outcomes = _reference_memory(contract, feature_names)
    processor = memory_module.StatePreprocessor(
        specifications=specifications,
        pca_components=int(state_contract["state_representation"]["pca_components"]),
        minimum_active_features=int(
            state_contract["state_representation"]["minimum_active_features"]
        ),
    )
    reference_values = processor.fit(reference_states)
    new_values = processor.transform(events)
    coverage_threshold = _nearest_threshold(
        reference_values, float(contract["memory"]["coverage_quantile"])
    )
    timelines: list[pd.DataFrame] = []
    documents: list[dict[str, Any]] = []
    for mode in ("cold_start", "warm_start"):
        for exclude_same_query in (False, True):
            timeline, episode_documents = replay_memory(
                events,
                outcomes,
                reference_states,
                reference_outcomes,
                reference_values,
                new_values,
                mode=mode,
                neighbors=int(contract["memory"]["neighbors"]),
                epsilon=float(contract["memory"]["distance_epsilon"]),
                coverage_threshold=coverage_threshold,
                minimum_history=int(contract["memory"]["minimum_history_for_available"]),
                exclude_same_query=exclude_same_query,
            )
            timelines.append(timeline)
            documents.extend(episode_documents)
    timelines.append(
        replay_exact_query_memory(
            events,
            outcomes,
            context_fields=tuple(contract["memory"]["exact_context_fields"]),
        )
    )
    base_timeline = pd.concat(timelines, ignore_index=True)
    hierarchical = [
        build_hierarchical_timeline(
            base_timeline,
            cross_query_mode="cold_start_cross_query",
            output_mode="hierarchical_cold_start",
        ),
        build_hierarchical_timeline(
            base_timeline,
            cross_query_mode="warm_start_cross_query",
            output_mode="hierarchical_warm_start",
        ),
    ]
    timeline = pd.concat([base_timeline, *hierarchical], ignore_index=True)
    summary = _summary(timeline)
    occurrences = _occurrence_summary(timeline)
    methods = _method_comparison(timeline, reference_outcomes, outcomes)
    first_occurrences = _first_occurrence_comparison(timeline, reference_outcomes, outcomes)
    matched_first_occurrences, matched_details = _matched_first_occurrence_comparison(
        timeline, reference_outcomes
    )
    action_summary = _action_outcome_summary(outcomes)
    sensitivity = _knn_sensitivity(
        events,
        outcomes,
        reference_states,
        reference_outcomes,
        reference_values,
        new_values,
        epsilon=float(contract["memory"]["distance_epsilon"]),
        minimum_history=int(contract["memory"]["minimum_history_for_available"]),
    )
    coverage_regret = _coverage_regret_curve(
        events,
        outcomes,
        reference_states,
        reference_outcomes,
        reference_values,
        new_values,
        neighbors=int(contract["memory"]["neighbors"]),
        epsilon=float(contract["memory"]["distance_epsilon"]),
        minimum_history=int(contract["memory"]["minimum_history_for_available"]),
    )
    retrieval_timing = _retrieval_timing(
        events,
        outcomes,
        reference_states,
        reference_outcomes,
        reference_values,
        new_values,
        neighbors=int(contract["memory"]["neighbors"]),
        epsilon=float(contract["memory"]["distance_epsilon"]),
    )
    timeline.to_csv(out_dir / "dba_episode_timeline.csv", index=False)
    timeline[timeline["memory_mode"].str.startswith("hierarchical_")].to_csv(
        out_dir / "hierarchical_policy_timeline.csv", index=False
    )
    events.to_csv(out_dir / "observed_episode_states.csv", index=False)
    outcomes.to_csv(out_dir / "observed_action_outcomes.csv", index=False)
    summary.to_csv(out_dir / "memory_summary.csv", index=False)
    occurrences.to_csv(out_dir / "occurrence_learning_curve.csv", index=False)
    methods.to_csv(out_dir / "method_comparison.csv", index=False)
    first_occurrences.to_csv(out_dir / "first_occurrence_comparison.csv", index=False)
    matched_first_occurrences.to_csv(
        out_dir / "first_occurrence_matched_comparison.csv", index=False
    )
    write_json(out_dir / "first_occurrence_matched_details.json", matched_details)
    action_summary.to_csv(out_dir / "action_outcome_summary.csv", index=False)
    sensitivity.to_csv(out_dir / "knn_sensitivity.csv", index=False)
    coverage_regret.to_csv(out_dir / "coverage_regret_curve.csv", index=False)
    write_json(out_dir / "retrieval_timing.json", retrieval_timing)
    episode_dir = out_dir / "episodes"
    for document in documents:
        episode = document["episode"]
        filename = (
            f"{episode['memory_mode']}__{int(episode['episode_order']):03d}__"
            f"{episode['query_id']}__run-{episode['query_occurrence']}.json"
        )
        write_json(episode_dir / filename, document)
    write_json(
        out_dir / "analysis_summary.json",
        {
            "status": "PASS",
            "collection_validation_status": collection_validation["status"],
            "query_count": int(events["query_id"].nunique()),
            "episode_count": int(len(events)),
            "action_outcome_count": int(len(outcomes)),
            "reference_episode_count": int(len(reference_states)),
            "n2_episode_count": int(events["region_count"].eq(2).sum()),
            "n3_episode_count": int(events["region_count"].eq(3).sum()),
            "active_feature_count": len(processor.active_features or []),
            "pca_component_count": int(reference_values.shape[1]),
            "reference_coverage_threshold": coverage_threshold,
            "all_results_equivalent": bool(outcomes["result_equal"].all()),
            "exact_context_fields": contract["memory"]["exact_context_fields"],
            "action_applicability_policy": contract["action_applicability"]["policy"],
            "retrieval_timing": retrieval_timing,
            "method_comparison": methods.to_dict(orient="records"),
            "first_occurrence_comparison": first_occurrences.to_dict(orient="records"),
            "first_occurrence_matched_comparison": matched_first_occurrences.to_dict(
                orient="records"
            ),
            "first_occurrence_matched_details": matched_details,
        },
    )
    _write_report(
        out_dir,
        timeline,
        summary,
        occurrences,
        methods,
        first_occurrences,
        coverage_threshold,
        len(reference_states),
    )
    _write_walkthrough(out_dir, timeline)
    _write_generalization_checks(
        out_dir,
        methods,
        first_occurrences,
        matched_first_occurrences,
        matched_details,
        action_summary,
    )


def main() -> int:
    args = parse_args()
    if args.command == "prepare":
        print(prepare(args.contract.resolve(), args.source_dir.resolve()))
    elif args.command == "validate-design":
        validate_design(
            args.contract.resolve(), args.rendered_dir.resolve(), args.out_dir.resolve()
        )
        print(args.out_dir.resolve() / "design_validation.json")
    else:
        analyze(args.contract.resolve(), args.index_dir.resolve(), args.out_dir.resolve())
        print(args.out_dir.resolve() / "DBA_TIMELINE.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
