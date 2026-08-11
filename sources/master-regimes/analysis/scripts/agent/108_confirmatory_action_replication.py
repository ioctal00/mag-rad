#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from matplotlib import pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
INFRA_ROOT = ROOT.parent / "master-regimes-infra"
DEFAULT_CONTRACT = ROOT / "configs/validation/confirmatory_action_replication_v1.yml"
DEFAULT_SOURCE_DIR = ROOT / "generated/corpus/confirmatory-action-replication-v1-source"
DEFAULT_RENDERED_DIR = ROOT / "generated/corpus/confirmatory-action-replication-v1"
DEFAULT_LOGICAL_RUN_ID = "confirmatory-action-replication-v1"
DEFAULT_INDEX_DIR = (
    INFRA_ROOT
    / "generated/runs/corpus-sweeps/_logical-runs"
    / DEFAULT_LOGICAL_RUN_ID
    / "_index"
)
DEFAULT_OUT_DIR = ROOT / "analysis/reports/confirmatory-action-replication-v1"

ACTIONS = (
    "increase_gac_work_mem",
    "regional_topk_candidates",
    "mitigate_remote_path_bundle",
)
TREATMENTS = ("baseline", *ACTIONS)
WILLIAMS_ROWS = (
    (
        "baseline",
        "increase_gac_work_mem",
        "mitigate_remote_path_bundle",
        "regional_topk_candidates",
    ),
    (
        "increase_gac_work_mem",
        "regional_topk_candidates",
        "baseline",
        "mitigate_remote_path_bundle",
    ),
    (
        "regional_topk_candidates",
        "mitigate_remote_path_bundle",
        "increase_gac_work_mem",
        "baseline",
    ),
    (
        "mitigate_remote_path_bundle",
        "baseline",
        "regional_topk_candidates",
        "increase_gac_work_mem",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare, validate and analyze the locked confirmatory action panel."
    )
    parser.add_argument(
        "command", choices=("prepare", "validate-design", "analyze")
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--rendered-dir", type=Path, default=DEFAULT_RENDERED_DIR)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "Nema dostupnih redova."
    columns = [str(column) for column in frame.columns]
    lines = ["| " + " | ".join(columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for values in frame.itertuples(index=False, name=None):
        rendered: list[str] = []
        for value in values:
            if isinstance(value, float):
                rendered.append("" if not np.isfinite(value) else f"{value:.4f}")
            else:
                rendered.append(str(value))
        lines.append("| " + " | ".join(rendered) + " |")
    return "\n".join(lines)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.parent.resolve()))
    except ValueError:
        return str(path.resolve())


def _write_output_checksums(out_dir: Path) -> None:
    checksum_path = out_dir / "checksums.sha256"
    rows = [
        f"{sha256_file(path)}  {path.relative_to(out_dir)}"
        for path in sorted(out_dir.rglob("*"))
        if path.is_file() and path != checksum_path
    ]
    checksum_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_input_manifest(
    out_dir: Path,
    *,
    contract_path: Path,
    state_contract_path: Path,
    index_dir: Path,
    reference_report: Path,
) -> None:
    candidates = [
        contract_path,
        state_contract_path,
        reference_report / "episodes.csv",
        index_dir.parent / "logical_run_index_manifest.json",
        *[
            index_dir / name
            for name in (
                "query_runs.csv",
                "execution_features.csv",
                "remote_edge_observations.csv",
                "region_fragments.csv",
                "worker_task_fragments.csv",
                "node_artifacts.csv",
                "hardware_nodes.csv",
            )
        ],
    ]
    missing = [_display_path(path) for path in candidates if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing confirmatory inputs: {missing}")
    write_json(
        out_dir / "input_manifest.json",
        {
            "contract": "confirmatory-action-replication-inputs-v1",
            "inputs": [
                {
                    "path": _display_path(path),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in candidates
            ],
        },
    )


def _load_module(path: Path, name: str) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def memory_modules() -> tuple[Any, Any]:
    memory = _load_module(
        ROOT / "analysis/scripts/agent/101_fuzzy_intervention_memory.py",
        "confirmatory_memory_101",
    )
    dba = _load_module(
        ROOT / "analysis/scripts/agent/102_dba_local_memory_panel.py",
        "confirmatory_memory_102",
    )
    return memory, dba


def validate_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    if tuple(contract.get("actions", ())) != ACTIONS:
        raise ValueError("The three frozen actions and their order must not change")
    scenarios = sorted(contract.get("scenarios", []), key=lambda row: int(row["order"]))
    if len(scenarios) != 15:
        raise ValueError(f"Expected 15 new SQL shapes, found {len(scenarios)}")
    if [int(row["order"]) for row in scenarios] != list(range(1, 16)):
        raise ValueError("Scenario order must be the contiguous range 1..15")
    if len({str(row["query_id"]) for row in scenarios}) != 15:
        raise ValueError("query_id values must be unique")
    if len({str(row["query_shape"]) for row in scenarios}) != 15:
        raise ValueError("query_shape values must be unique")
    if any(not str(row["query_id"]).startswith("q") for row in scenarios):
        raise ValueError("Every scenario must have an explicit qNN query identifier")
    execution = contract["execution"]
    repetitions = int(execution["repetitions_per_condition"])
    if repetitions != 5:
        raise ValueError("The confirmatory panel requires exactly five repetitions")
    if int(execution["expected_condition_count"]) != 60:
        raise ValueError("The locked panel must contain 60 conditions")
    if int(execution["expected_execution_count"]) != 300:
        raise ValueError("The locked panel must contain 300 executions")
    freeze = contract["model_freeze"]
    if bool(freeze["refit"]):
        raise ValueError("Refitting on the confirmatory panel is forbidden")
    if (
        int(freeze["pca_components"]) != 6
        or int(freeze["neighbors"]) != 5
        or str(freeze["distance_metric"]) != "euclidean"
        or float(freeze["coverage_quantile"]) != 0.99
    ):
        raise ValueError("R3, PCA=6, k=5, Euclidean and empirical P99 are frozen")
    dataset = contract["dataset"]
    if int(dataset["region_count"]) != 3 or str(dataset["topology_id"]) != "eu_us_apac_gac":
        raise ValueError("The replication panel must use the fixed N=3 topology")
    return scenarios


def treatment_cell_id(query_id: str, treatment: str) -> str:
    return f"{query_id}__{treatment}"


def build_williams_schedule(
    scenarios: list[dict[str, Any]], repetitions: int, seed: int
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    schedule: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for repetition in range(repetitions):
        ordered = list(scenarios)
        random.Random(seed + repetition).shuffle(ordered)
        for scenario_position, scenario in enumerate(ordered):
            row_index = (scenario_position + repetition) % len(WILLIAMS_ROWS)
            for treatment_position, treatment in enumerate(WILLIAMS_ROWS[row_index], start=1):
                entry = {
                    "corpus_cell_id": treatment_cell_id(str(scenario["query_id"]), treatment),
                    "repetition_index": repetition,
                }
                schedule.append(entry)
                audit.append(
                    {
                        "run_order": len(schedule),
                        "repetition_index": repetition,
                        "scenario_position": scenario_position + 1,
                        "query_id": str(scenario["query_id"]),
                        "query_shape": str(scenario["query_shape"]),
                        "williams_row": row_index + 1,
                        "treatment_position": treatment_position,
                        "treatment": treatment,
                        "corpus_cell_id": entry["corpus_cell_id"],
                    }
                )
    return schedule, pd.DataFrame(audit)


def _common_cell(contract: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    dataset = contract["dataset"]
    return {
        "logical_question_id": "dba_local_memory_topk",
        "component_match_id": f"confirmatory_{scenario['query_id']}",
        "dataset_profile_id": [str(dataset["id"])],
        "topology_id": str(dataset["topology_id"]),
        "execution_strategy": "multiregion_union",
        "execution_scope": "gac_multi_edge",
        "target_scope": "global_query",
        "intervention_role": "final_check",
        "intervention_axis": "combined_pressure",
        "pressure_axis": "local_intervention_memory",
        "target_metric": "global_gac_mitigation_gain_log2",
        "dataset_role": "confirmatory_action_replication",
        "scenario_level": "confirmatory_holdout",
        "repeatability_repetitions": int(
            contract["execution"]["repetitions_per_condition"]
        ),
        "parameters": {
            "query_shape": [str(scenario["query_shape"])],
            "cutoff_ts": [str(scenario["cutoff_ts"])],
            "limit_k": [int(scenario["limit_k"])],
            "include_apac": [True],
        },
    }


def build_manifest(
    contract: dict[str, Any], source_dir: Path
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    scenarios = validate_contract(contract)
    runtime = contract["runtime_profile"]
    cells: list[dict[str, Any]] = []
    design: list[dict[str, Any]] = []
    for scenario in scenarios:
        query_id = str(scenario["query_id"])
        common = _common_cell(contract, scenario)
        specifications = {
            "baseline": (
                "gac_fdw_dba_topk_raw",
                str(runtime["baseline"]),
                "gac_raw_topk",
                "stressed",
                "",
            ),
            "increase_gac_work_mem": (
                "gac_fdw_dba_topk_raw",
                str(runtime["gac_memory"]),
                "gac_memory_increase",
                "mitigated",
                "increase_gac_work_mem",
            ),
            "regional_topk_candidates": (
                "gac_fdw_dba_topk_regional",
                str(runtime["baseline"]),
                "regional_topk_candidates",
                "mitigated",
                "regional_topk_candidates",
            ),
            "mitigate_remote_path_bundle": (
                "gac_fdw_dba_topk_raw",
                str(runtime["remote"]),
                "remote_transport_bundle",
                "mitigated",
                "mitigate_remote_path_bundle",
            ),
        }
        for treatment, (template, runtime_id, strategy, variant, action) in specifications.items():
            cell = {
                **common,
                "corpus_cell_id": treatment_cell_id(query_id, treatment),
                "template_id": template,
                "runtime_config_id": runtime_id,
                "pressure_level": variant,
                "variant": variant,
                "physical_strategy_id": strategy,
                "pressure_pair_key": f"{query_id}__{action or 'shared_baseline'}",
            }
            if action:
                cell["mitigation_action"] = action
            cells.append(cell)
            design.append(
                {
                    "query_id": query_id,
                    "query_shape": str(scenario["query_shape"]),
                    "treatment": treatment,
                    "corpus_cell_id": cell["corpus_cell_id"],
                    "template_id": template,
                    "runtime_config_id": runtime_id,
                    "repetitions": int(contract["execution"]["repetitions_per_condition"]),
                }
            )
    execution = contract["execution"]
    schedule, schedule_audit = build_williams_schedule(
        scenarios,
        int(execution["repetitions_per_condition"]),
        int(execution["scenario_order_seed"]),
    )
    dataset = contract["dataset"]
    manifest = {
        "corpus_id": contract["experiment_id"],
        "corpus_version": contract["contract_version"],
        "batch_id": "batch-confirmatory-action-replication-v1",
        "collection_contract_version": "fuzzy-intervention-memory-v1",
        "description": contract["description"],
        "query_groups": "../../../workloads/corpus/query-groups.yml",
        "runtime_catalog": "../../../workloads/corpus/runtime-configs.yml",
        "dataset_profiles": {
            str(dataset["id"]): {
                "profile": f"../../../{dataset['profile']}",
                "load_method": str(dataset["load_method"]),
            }
        },
        "execution_budget": {
            "hard_timeout_seconds": int(execution["hard_timeout_seconds"]),
            "timeout_grace_seconds": int(execution["timeout_grace_seconds"]),
        },
        "execution_policy": {
            "cache_policy": "balanced_williams_confirmatory",
            "order_policy": "explicit_schedule",
            "explicit_schedule": schedule,
            "repetitions_default": 1,
            "record_run_order": True,
            "record_buffer_features": True,
            "preserve_instance_order_across_runtime_configs": True,
            "fdw_auto_explain": True,
            "fdw_auto_explain_regions": ["active_regions"],
            "os_sampler": True,
            "os_sampler_node_groups": ["active_regions"],
            "result_signature": True,
            "result_signature_scope": str(execution["result_signature_scope"]),
            "network_profile_probe": True,
            "remote_edge_context": True,
            "group_runtime_configs_by_active_scope": True,
        },
        "cells": cells,
    }
    return manifest, pd.DataFrame(design), schedule_audit


def prepare(contract_path: Path, source_dir: Path, out_dir: Path) -> None:
    contract = read_yaml(contract_path)
    manifest, design, schedule = build_manifest(contract, source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = source_dir / "corpus_manifest.yml"
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, width=110), encoding="utf-8"
    )
    design.to_csv(source_dir / "design_conditions.csv", index=False)
    schedule.to_csv(source_dir / "williams_execution_schedule.csv", index=False)
    position_counts = (
        schedule.groupby(["treatment", "treatment_position"]).size().rename("count").reset_index()
    )
    carryover = schedule.copy()
    carryover["previous_treatment"] = carryover.groupby(
        ["repetition_index", "scenario_position"]
    )["treatment"].shift(1)
    carryover_counts = (
        carryover.dropna(subset=["previous_treatment"])
        .groupby(["previous_treatment", "treatment"])
        .size()
        .rename("count")
        .reset_index()
    )
    position_counts.to_csv(source_dir / "williams_position_counts.csv", index=False)
    carryover_counts.to_csv(source_dir / "williams_carryover_counts.csv", index=False)
    freeze_files = [
        ROOT / contract["model_freeze"]["state_contract"],
        ROOT / contract["model_freeze"]["reference_report"] / "episodes.csv",
        ROOT / contract["model_freeze"]["reference_report"] / "state_feature_selection.csv",
    ]
    write_json(
        source_dir / "design_freeze.json",
        {
            "contract_sha256": sha256_file(contract_path),
            "manifest_sha256": sha256_file(manifest_path),
            "scenario_count": 15,
            "condition_count": len(design),
            "execution_count": len(schedule),
            "williams_rows": WILLIAMS_ROWS,
            "frozen_input_sha256": {
                str(path.relative_to(ROOT)): sha256_file(path)
                for path in freeze_files
                if path.exists()
            },
            "outcomes_used_for_design": False,
            "refit_allowed": False,
        },
    )
    print(manifest_path)


def _rendered_instances(rendered_dir: Path) -> pd.DataFrame:
    paths = sorted(rendered_dir.glob("groups/*/instance_manifest.csv"))
    if not paths:
        raise FileNotFoundError(f"No rendered instance manifests under {rendered_dir}")
    frames: list[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_csv(path)
        frame["group_id"] = path.parent.name
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def validate_design(contract_path: Path, rendered_dir: Path, out_dir: Path) -> None:
    contract = read_yaml(contract_path)
    scenarios = validate_contract(contract)
    rows = _rendered_instances(rendered_dir).sort_values("run_order")
    expected_schedule, schedule = build_williams_schedule(
        scenarios,
        int(contract["execution"]["repetitions_per_condition"]),
        int(contract["execution"]["scenario_order_seed"]),
    )
    actual = [
        {
            "corpus_cell_id": str(row.corpus_cell_id),
            "repetition_index": int(row.repetition_index),
        }
        for row in rows.itertuples()
    ]
    condition_repeats = rows.groupby("corpus_cell_id")["repetition_index"].nunique()
    treatment_positions = schedule.groupby(["treatment", "treatment_position"]).size()
    per_treatment_spread = treatment_positions.groupby(level=0).agg(
        lambda values: int(values.max() - values.min())
    )
    old_contract = read_yaml(ROOT / "configs/validation/dba_local_memory_panel_v1.yml")
    old_shapes = {str(row["query_shape"]) for row in old_contract["scenarios"]}
    new_shapes = {str(row["query_shape"]) for row in scenarios}
    checks = {
        "single_rendered_group": rows["group_id"].nunique() == 1,
        "execution_count_300": len(rows) == 300,
        "condition_count_60": rows["condition_id"].nunique() == 60,
        "five_repetitions_per_condition": condition_repeats.eq(5).all(),
        "all_n3": set(rows["topology_id"].astype(str)) == {"eu_us_apac_gac"},
        "three_actions": set(
            rows.loc[rows["mitigation_action"].notna(), "mitigation_action"].astype(str)
        )
        == set(ACTIONS),
        "explicit_schedule_exact": actual == expected_schedule,
        "positions_near_balanced": per_treatment_spread.le(1).all(),
        "new_shape_names_do_not_overlap_old_panel": not (old_shapes & new_shapes),
        "total_order_present": all(
            "order by" in Path(path).read_text(encoding="utf-8").lower()
            for path in rows["rendered_sql_path"]
        ),
        "no_result_or_action_outcome_in_schedule": not any(
            key in entry
            for entry in expected_schedule
            for key in ("target_log2_gain", "best_action", "result_hash")
        ),
    }
    summary = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "counts": {
            "scenarios": 15,
            "conditions": int(rows["condition_id"].nunique()),
            "executions": len(rows),
            "groups": int(rows["group_id"].nunique()),
        },
        "treatment_position_counts": {
            f"{treatment}::p{position}": int(count)
            for (treatment, position), count in treatment_positions.items()
        },
    }
    write_json(out_dir / "design_validation.json", summary)
    rows[[
        "run_order",
        "execution_slot_id",
        "corpus_cell_id",
        "condition_id",
        "repetition_index",
        "runtime_config_id",
        "template_id",
    ]].to_csv(out_dir / "rendered_execution_order.csv", index=False)
    if summary["status"] != "PASS":
        raise SystemExit(2)
    print(out_dir / "design_validation.json")


def _reference_memory(
    contract: dict[str, Any], feature_names: list[str], dba: Any
) -> tuple[pd.DataFrame, pd.DataFrame]:
    adapter = {
        "memory": {
            "reference_report": contract["model_freeze"]["reference_report"],
            "state_contract": contract["model_freeze"]["state_contract"],
        }
    }
    return dba._reference_memory(adapter, feature_names)


def _first_nonempty(values: Iterable[Any]) -> str:
    for value in values:
        if pd.notna(value) and str(value).strip():
            return str(value)
    return ""


def _scenario_observations(
    executions: pd.DataFrame,
    contract: dict[str, Any],
    feature_names: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scenarios = validate_contract(contract)
    events: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    repetitions: list[dict[str, Any]] = []
    practical = math.log2(1.0 + float(contract["uncertainty"]["practical_tie_relative_gain"]))
    bootstrap_samples = int(contract["uncertainty"]["bootstrap_samples"])
    bootstrap_seed = int(contract["uncertainty"]["bootstrap_seed"])
    for scenario in scenarios:
        query_id = str(scenario["query_id"])
        component = f"confirmatory_{query_id}"
        group = executions[executions["component_match_id"].astype(str).eq(component)].copy()
        group["repetition_index"] = pd.to_numeric(
            group["repetition_index"], errors="raise"
        ).astype(int)
        group["elapsed_seconds"] = pd.to_numeric(group["elapsed_seconds"], errors="coerce")
        baseline = group[group["variant"].astype(str).eq("stressed")].sort_values(
            "repetition_index"
        )
        if len(baseline) != 5:
            raise ValueError(
                f"{query_id}: expected five baseline repetitions, found {len(baseline)}"
            )
        event = {
            "episode_id": f"confirmatory::{query_id}",
            "query_id": query_id,
            "query_shape": str(scenario["query_shape"]),
            "scenario_order": int(scenario["order"]),
            "topology_id": str(contract["dataset"]["topology_id"]),
            "region_count": int(contract["dataset"]["region_count"]),
            "dataset_profile_id": str(contract["dataset"]["id"]),
            "profile": str(contract["runtime_profile"]["id"]),
            "baseline_median_seconds": float(baseline["elapsed_seconds"].median()),
            "baseline_iqr_seconds": float(
                baseline["elapsed_seconds"].quantile(0.75)
                - baseline["elapsed_seconds"].quantile(0.25)
            ),
            "normalized_sql_hash": _first_nonempty(baseline["sql_normalized_hash"]),
        }
        for feature in feature_names:
            event[f"before__{feature}"] = pd.to_numeric(
                baseline[feature], errors="coerce"
            ).median()
        events.append(event)
        elapsed_by_action: dict[str, np.ndarray] = {}
        gains: dict[str, float] = {}
        for action in ACTIONS:
            action_rows = group[
                group["mitigation_action"].astype(str).eq(action)
            ].sort_values("repetition_index")
            if len(action_rows) != 5:
                raise ValueError(f"{query_id}/{action}: expected five repetitions")
            if set(action_rows["repetition_index"]) != set(baseline["repetition_index"]):
                raise ValueError(f"{query_id}/{action}: repetition identities do not align")
            action_elapsed = action_rows["elapsed_seconds"].to_numpy(dtype=float)
            baseline_elapsed = baseline["elapsed_seconds"].to_numpy(dtype=float)
            elapsed_by_action[action] = action_elapsed
            gain = math.log2(float(np.median(baseline_elapsed)) / float(np.median(action_elapsed)))
            gains[action] = gain
            for repetition_index, baseline_seconds, action_seconds in zip(
                baseline["repetition_index"], baseline_elapsed, action_elapsed, strict=True
            ):
                repetitions.append(
                    {
                        "query_id": query_id,
                        "repetition_index": int(repetition_index),
                        "mitigation_action": action,
                        "baseline_seconds": float(baseline_seconds),
                        "action_seconds": float(action_seconds),
                        "paired_log2_gain": math.log2(
                            float(baseline_seconds) / float(action_seconds)
                        ),
                    }
                )
        strict_best = max(ACTIONS, key=gains.__getitem__)
        rng = np.random.default_rng(bootstrap_seed + int(scenario["order"]))
        indices = rng.integers(0, 5, size=(bootstrap_samples, 5))
        baseline_values = baseline["elapsed_seconds"].to_numpy(dtype=float)
        bootstrap_gains = {
            action: np.log2(
                np.median(baseline_values[indices], axis=1)
                / np.median(elapsed_by_action[action][indices], axis=1)
            )
            for action in ACTIONS
        }
        acceptable: list[str] = []
        for action in ACTIONS:
            delta = bootstrap_gains[strict_best] - bootstrap_gains[action]
            low, high = np.quantile(delta, [0.025, 0.975])
            if gains[strict_best] - gains[action] <= practical or low <= 0.0 <= high:
                acceptable.append(action)
            outcomes.append(
                {
                    "episode_id": event["episode_id"],
                    "query_id": query_id,
                    "mitigation_action": action,
                    "target_log2_gain": gains[action],
                    "action_median_seconds": float(np.median(elapsed_by_action[action])),
                    "action_iqr_seconds": float(
                        np.quantile(elapsed_by_action[action], 0.75)
                        - np.quantile(elapsed_by_action[action], 0.25)
                    ),
                    "strict_best_action": strict_best,
                    "winner_count_of_five": int(
                        sum(
                            action
                            == max(
                                ACTIONS,
                                key=lambda candidate: math.log2(
                                    baseline_values[index]
                                    / elapsed_by_action[candidate][index]
                                ),
                            )
                            for index in range(5)
                        )
                    ),
                    "delta_from_best_ci_low": float(low),
                    "delta_from_best_ci_high": float(high),
                    "tie_acceptable": action in acceptable,
                }
            )
    return pd.DataFrame(events), pd.DataFrame(outcomes), pd.DataFrame(repetitions)


def _signature_rows(query_runs: pd.DataFrame, executions: pd.DataFrame) -> pd.DataFrame:
    signatures = query_runs[query_runs["result_signature_status"].eq("completed")].copy()
    if "component_match_id" not in signatures:
        component_lookup = executions[["query_run_id", "component_match_id"]].drop_duplicates()
        signatures = signatures.merge(
            component_lookup,
            on="query_run_id",
            how="left",
            validate="many_to_one",
        )
    return signatures


def _hardware_snapshots_are_attempt_scoped(hardware: pd.DataFrame) -> bool:
    static_columns = [
        "hostname",
        "kernel",
        "cpu_model",
        "logical_cpus",
        "physical_cores",
        "sockets",
        "cores_per_socket",
        "threads_per_core",
        "hypervisor_vendor",
        "ram_total_bytes",
        "disk_count",
        "disk_total_bytes",
        "storage_classes",
        "root_storage_class",
        "postgres_storage_class",
    ]
    snapshots_per_attempt = hardware.groupby("database_sweep_id")[
        "hardware_snapshot_id"
    ].nunique()
    nodes_per_snapshot = hardware.groupby("hardware_snapshot_id")["node_name"].nunique()
    node_sets = hardware.groupby("hardware_snapshot_id")["node_name"].agg(
        lambda values: tuple(sorted(set(values.astype(str))))
    )
    stable_by_node = all(
        hardware.groupby("node_name")[column].nunique(dropna=False).le(1).all()
        for column in static_columns
    )
    return bool(
        snapshots_per_attempt.eq(1).all()
        and nodes_per_snapshot.eq(10).all()
        and node_sets.nunique() == 1
        and stable_by_node
    )


def _collection_validation(
    index_dir: Path, executions: pd.DataFrame, contract: dict[str, Any]
) -> dict[str, Any]:
    query_runs = pd.read_csv(index_dir / "query_runs.csv", low_memory=False)
    edges = pd.read_csv(index_dir / "remote_edge_observations.csv", low_memory=False)
    regions = pd.read_csv(index_dir / "region_fragments.csv", low_memory=False)
    tasks = pd.read_csv(index_dir / "worker_task_fragments.csv", low_memory=False)
    nodes = pd.read_csv(index_dir / "node_artifacts.csv", low_memory=False)
    hardware = pd.read_csv(index_dir / "hardware_nodes.csv", low_memory=False)
    signatures = _signature_rows(query_runs, executions)
    expected_schedule, _ = build_williams_schedule(
        validate_contract(contract),
        int(contract["execution"]["repetitions_per_condition"]),
        int(contract["execution"]["scenario_order_seed"]),
    )
    actual_order = query_runs.copy()
    actual_order["run_order"] = pd.to_numeric(actual_order["run_order"], errors="raise").astype(int)
    actual_order["repetition_index"] = pd.to_numeric(
        actual_order["repetition_index"], errors="raise"
    ).astype(int)
    actual_order = actual_order.sort_values("run_order")
    actual_order["treatment"] = actual_order["mitigation_action"].fillna("").astype(str)
    actual_order.loc[actual_order["treatment"].eq(""), "treatment"] = "baseline"
    expected_runtime_by_treatment = {
        "baseline": str(contract["runtime_profile"]["baseline"]),
        "increase_gac_work_mem": str(contract["runtime_profile"]["gac_memory"]),
        "regional_topk_candidates": str(contract["runtime_profile"]["baseline"]),
        "mitigate_remote_path_bundle": str(contract["runtime_profile"]["remote"]),
    }
    actual_schedule = [
        {
            "corpus_cell_id": str(row.corpus_cell_id),
            "repetition_index": int(row.repetition_index),
        }
        for row in actual_order.itertuples()
    ]
    signature_equivalence: list[dict[str, Any]] = []
    for scenario in validate_contract(contract):
        component = f"confirmatory_{scenario['query_id']}"
        rows = signatures[signatures["component_match_id"].astype(str).eq(component)]
        multiset = set(rows["result_multiset_sha256"].dropna().astype(str))
        ordered = set(rows["result_ordered_sha256"].dropna().astype(str))
        signature_equivalence.append(
            {
                "query_id": str(scenario["query_id"]),
                "signature_count": len(rows),
                "multiset_equivalent": len(multiset) == 1,
                "ordered_equivalent": len(ordered) == 1,
            }
        )
    signature_frame = pd.DataFrame(signature_equivalence)
    required_telemetry = [
        "os_cpu_busy_pct_mean",
        "os_cpu_busy_pct_max",
        "os_mem_used_peak_bytes_max",
        "os_net_rx_bytes_sum",
        "os_net_tx_bytes_sum",
    ]
    checks = {
        "all_300_completed": len(query_runs) == 300
        and query_runs["execution_status"].eq("completed").all()
        and not query_runs["timed_out"].fillna(False).astype(bool).any(),
        "sixty_conditions_five_repetitions": query_runs["condition_id"].nunique() == 60
        and query_runs.groupby("condition_id")["repetition_index"].nunique().eq(5).all(),
        "actual_order_matches_locked_williams_schedule": actual_schedule == expected_schedule
        and actual_order["run_order"].tolist() == list(range(1, 301)),
        "runtime_profile_matches_every_treatment": all(
            str(row.runtime_config_id) == expected_runtime_by_treatment[str(row.treatment)]
            for row in actual_order.itertuples()
        ),
        "all_n3": set(query_runs["topology_id"].astype(str)) == {"eu_us_apac_gac"},
        "three_edges_per_execution": len(edges) == 900
        and edges["availability_status"].eq("available").all(),
        "three_regions_per_execution": len(regions) == 900,
        "worker_task_evidence_for_every_execution": tasks["query_run_id"].nunique() == 300,
        "ten_aligned_os_nodes_per_execution": executions["os_sampled_node_count"].eq(10).all()
        and executions["os_query_aligned_node_count"].eq(10).all(),
        "required_telemetry_complete": executions[required_telemetry].notna().all().all(),
        "node_artifacts_complete": len(nodes) == 3000,
        "network_apply_and_reset_ok": query_runs["network_intervention_apply_status"].eq("ok").all()
        and query_runs["network_intervention_reset_status"].eq("ok").all(),
        "one_signature_per_condition": len(signatures) == 60
        and signatures["condition_id"].nunique() == 60,
        "ordered_and_multiset_results_equivalent": signature_frame[
            ["multiset_equivalent", "ordered_equivalent"]
        ].all().all(),
        "one_hardware_snapshot_per_attempt_with_stable_ten_nodes": (
            _hardware_snapshots_are_attempt_scoped(hardware)
        ),
        "uniform_zero_warmup_contract": not executions["warmup_run_flag"]
        .fillna(False)
        .astype(bool)
        .any(),
        "no_collection_errors": pd.to_numeric(
            executions["collection_error_count"], errors="coerce"
        ).fillna(0).sum()
        == 0,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "signature_equivalence": signature_equivalence,
        "warmup_contract": "zero explicit warm-up executions for every condition",
        "counts": {
            "executions": len(query_runs),
            "signatures": len(signatures),
            "edges": len(edges),
            "regions": len(regions),
            "worker_task_fragments": len(tasks),
            "node_artifacts": len(nodes),
            "hardware_snapshots": hardware["hardware_snapshot_id"].nunique(),
        },
    }


def _oracle(outcomes: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        str(episode_id): {
            str(row.mitigation_action): float(row.target_log2_gain)
            for row in group.itertuples()
        }
        for episode_id, group in outcomes.groupby("episode_id")
    }


def _prediction_row(
    event: pd.Series,
    predictions: dict[str, float],
    neighbors: list[dict[str, Any]],
    nearest: float,
    memory_count: int,
    threshold: float,
    minimum_history: int,
    dba: Any,
    oracle: dict[str, dict[str, float]],
    mode: str,
) -> dict[str, Any]:
    status = dba._status(
        memory_count=memory_count,
        nearest_distance=nearest,
        coverage_threshold=threshold,
        minimum_history=minimum_history,
    )
    candidate, recommendation = dba._decision_actions(predictions, status, ACTIONS)
    actual = oracle[str(event["episode_id"])]
    best = max(ACTIONS, key=actual.__getitem__)
    action_support = {
        action: sum(action in neighbor.get("action_gains", {}) for neighbor in neighbors)
        for action in ACTIONS
    }
    return {
        "mode": mode,
        "episode_id": str(event["episode_id"]),
        "query_id": str(event["query_id"]),
        "scenario_order": int(event["scenario_order"]),
        "decision_status": status,
        "candidate_action": candidate,
        "recommended_action": recommendation,
        "actual_best_action": best,
        "top1_correct": bool(recommendation and recommendation == best),
        "tie_aware_top1": bool(recommendation),
        "regret_log2": (
            float(actual[best] - actual[recommendation]) if recommendation else float("nan")
        ),
        "nearest_distance": nearest,
        "coverage_threshold": threshold,
        "memory_state_count": memory_count,
        "complete_action_support": all(action_support[action] > 0 for action in ACTIONS),
        "action_support_json": json.dumps(action_support, sort_keys=True),
        "predictions_json": json.dumps(predictions, sort_keys=True),
        "neighbors_json": json.dumps(neighbors, sort_keys=True),
    }


def _static_action_median_replay(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    reference_states: pd.DataFrame,
    reference_outcomes: pd.DataFrame,
    dba: Any,
) -> pd.DataFrame:
    medians = {
        action: float(
            reference_outcomes[
                reference_outcomes["mitigation_action"].astype(str).eq(action)
            ]["target_log2_gain"].median()
        )
        for action in ACTIONS
    }
    oracle = _oracle(outcomes)
    rows: list[dict[str, Any]] = []
    for _, event in events.sort_values("scenario_order").iterrows():
        row = _prediction_row(
            event,
            medians,
            [],
            0.0,
            len(reference_states),
            float("inf"),
            1,
            dba,
            oracle,
            "static_action_median",
        )
        acceptable = set(
            outcomes[
                outcomes["episode_id"].astype(str).eq(str(event["episode_id"]))
                & outcomes["tie_acceptable"].astype(bool)
            ]["mitigation_action"].astype(str)
        )
        row["tie_aware_top1"] = row["recommended_action"] in acceptable
        row["complete_action_support"] = True
        row["action_support_json"] = json.dumps(
            {
                action: int(
                    reference_outcomes["mitigation_action"].astype(str).eq(action).sum()
                )
                for action in ACTIONS
            },
            sort_keys=True,
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _replay(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    reference_states: pd.DataFrame,
    reference_outcomes: pd.DataFrame,
    reference_values: np.ndarray,
    event_values: np.ndarray,
    threshold: float,
    contract: dict[str, Any],
    dba: Any,
    *,
    mode: str,
    reveal_policy: str,
    random_seed: int | None = None,
) -> pd.DataFrame:
    memory_states = reference_states.copy().reset_index(drop=True)
    memory_outcomes = reference_outcomes.copy().reset_index(drop=True)
    memory_values = np.asarray(reference_values, dtype=float).copy()
    oracle = _oracle(outcomes)
    rows: list[dict[str, Any]] = []
    rng = random.Random(random_seed)
    for offset, (_, event) in enumerate(events.sort_values("scenario_order").iterrows()):
        value = event_values[offset]
        predictions, neighbors, nearest, memory_count = dba._estimate_from_memory(
            value,
            memory_values,
            memory_states,
            memory_outcomes,
            neighbors=int(contract["model_freeze"]["neighbors"]),
            epsilon=1e-6,
            distance_metric=str(contract["model_freeze"]["distance_metric"]),
            excluded_query_id=str(event["query_id"]),
            excluded_normalized_sql_hash=str(event["normalized_sql_hash"]),
        )
        row = _prediction_row(
            event,
            predictions,
            neighbors,
            nearest,
            memory_count,
            threshold,
            int(contract["model_freeze"]["minimum_history_for_available"]),
            dba,
            oracle,
            mode,
        )
        acceptable = set(
            outcomes[
                outcomes["episode_id"].astype(str).eq(str(event["episode_id"]))
                & outcomes["tie_acceptable"].astype(bool)
            ]["mitigation_action"].astype(str)
        )
        row["tie_aware_top1"] = bool(
            row["recommended_action"] and row["recommended_action"] in acceptable
        )
        rows.append(row)
        if reveal_policy == "none":
            continue
        new_state = event.to_frame().T.copy()
        memory_states = pd.concat([memory_states, new_state], ignore_index=True)
        memory_values = np.vstack([memory_values, value])
        available = outcomes[
            outcomes["episode_id"].astype(str).eq(str(event["episode_id"]))
        ].copy()
        if reveal_policy == "round_robin":
            action = ACTIONS[offset % len(ACTIONS)]
            available = available[available["mitigation_action"].astype(str).eq(action)]
        elif reveal_policy == "random_one":
            action = rng.choice(ACTIONS)
            available = available[available["mitigation_action"].astype(str).eq(action)]
        elif reveal_policy != "all":
            raise ValueError(f"Unsupported reveal policy: {reveal_policy}")
        memory_outcomes = pd.concat([memory_outcomes, available], ignore_index=True)
    return pd.DataFrame(rows)


def _summary(rows: pd.DataFrame) -> pd.DataFrame:
    summaries: list[dict[str, Any]] = []
    for mode, group in rows.groupby("mode", sort=False):
        issued = group[group["recommended_action"].astype(str).ne("")]
        summaries.append(
            {
                "mode": mode,
                "decision_count": len(group),
                "recommendation_count": len(issued),
                "abstention_count": len(group) - len(issued),
                "coverage": len(issued) / len(group) if len(group) else float("nan"),
                "strict_top1": float(issued["top1_correct"].mean())
                if len(issued)
                else float("nan"),
                "tie_aware_top1": float(issued["tie_aware_top1"].mean())
                if len(issued)
                else float("nan"),
                "mean_regret_log2": float(issued["regret_log2"].mean())
                if len(issued)
                else float("nan"),
                "median_nearest_distance": float(group["nearest_distance"].median()),
            }
        )
    return pd.DataFrame(summaries)


def _bootstrap_summary(
    rows: pd.DataFrame, *, samples: int, seed: int
) -> pd.DataFrame:
    output: list[dict[str, Any]] = []
    for mode_index, (mode, group) in enumerate(rows.groupby("mode", sort=False)):
        group = group.reset_index(drop=True)
        query_ids = group["query_id"].astype(str).unique()
        rng = np.random.default_rng(seed + mode_index)
        cluster_rows = [
            group[group["query_id"].astype(str).eq(query_id)] for query_id in query_ids
        ]
        issued_rows = [
            cluster[cluster["recommended_action"].astype(str).ne("")]
            for cluster in cluster_rows
        ]
        sampled_indices = rng.integers(
            0,
            len(query_ids),
            size=(samples, len(query_ids)),
        )

        def sampled_sums(
            values: Iterable[float],
            indices: np.ndarray = sampled_indices,
        ) -> np.ndarray:
            array = np.asarray(list(values), dtype=float)
            return array[indices].sum(axis=1)

        total_count = sampled_sums(len(cluster) for cluster in cluster_rows)
        issued_count = sampled_sums(len(cluster) for cluster in issued_rows)
        metrics: dict[str, np.ndarray] = {
            "coverage": np.divide(
                issued_count,
                total_count,
                out=np.full(samples, np.nan),
                where=total_count > 0,
            )
        }
        for metric, column in (
            ("strict_top1", "top1_correct"),
            ("tie_aware_top1", "tie_aware_top1"),
            ("mean_regret_log2", "regret_log2"),
        ):
            numerator = sampled_sums(
                pd.to_numeric(cluster[column], errors="coerce").sum()
                for cluster in issued_rows
            )
            denominator = sampled_sums(
                pd.to_numeric(cluster[column], errors="coerce").notna().sum()
                for cluster in issued_rows
            )
            metrics[metric] = np.divide(
                numerator,
                denominator,
                out=np.full(samples, np.nan),
                where=denominator > 0,
            )
        row: dict[str, Any] = {"mode": mode, "bootstrap_clusters": len(query_ids)}
        for metric, values in metrics.items():
            finite = np.asarray(values, dtype=float)
            finite = finite[np.isfinite(finite)]
            row[f"{metric}_ci_low"] = (
                float(np.quantile(finite, 0.025)) if len(finite) else float("nan")
            )
            row[f"{metric}_ci_high"] = (
                float(np.quantile(finite, 0.975)) if len(finite) else float("nan")
            )
        output.append(row)
    return pd.DataFrame(output)


def _write_figures(
    out_dir: Path,
    repetitions: pd.DataFrame,
    summary: pd.DataFrame,
) -> None:
    action_labels = {
        "increase_gac_work_mem": "GAC work_mem",
        "regional_topk_candidates": "Regionalni Top-K",
        "mitigate_remote_path_bundle": "Udaljena putanja",
    }
    colors = {
        "increase_gac_work_mem": "#6C757D",
        "regional_topk_candidates": "#176B61",
        "mitigate_remote_path_bundle": "#B55D35",
    }
    query_ids = list(dict.fromkeys(repetitions["query_id"].astype(str)))
    y_positions = np.arange(len(query_ids))
    offsets = dict(zip(ACTIONS, (-0.22, 0.0, 0.22), strict=True))
    figure, axis = plt.subplots(figsize=(9.2, 7.0))
    for action in ACTIONS:
        action_rows = repetitions[
            repetitions["mitigation_action"].astype(str).eq(action)
        ]
        medians = action_rows.groupby("query_id")["paired_log2_gain"].median()
        for y_index, query_id in enumerate(query_ids):
            values = action_rows[
                action_rows["query_id"].astype(str).eq(query_id)
            ]["paired_log2_gain"].astype(float)
            axis.scatter(
                values,
                np.full(len(values), y_index + offsets[action]),
                color=colors[action],
                alpha=0.22,
                s=16,
                linewidths=0,
            )
        axis.scatter(
            [medians[query_id] for query_id in query_ids],
            y_positions + offsets[action],
            color=colors[action],
            edgecolor="white",
            linewidth=0.5,
            s=38,
            label=action_labels[action],
            zorder=3,
        )
    axis.axvline(0.0, color="#3F4648", linewidth=0.8, linestyle="--")
    axis.set_yticks(y_positions, query_ids)
    axis.invert_yaxis()
    axis.set_xlabel("Upareni dobitak akcije (log2)")
    axis.set_ylabel("Novi SQL oblik")
    axis.grid(axis="x", color="#D9DEDF", linewidth=0.6)
    axis.legend(frameon=False, ncol=3, loc="lower right")
    figure.tight_layout()
    figure.savefig(out_dir / "confirmatory_action_gains.pdf", bbox_inches="tight")
    plt.close(figure)

    selected_modes = [
        "static_action_median",
        "frozen_transfer",
        "prequential_full_feedback",
        "partial_feedback_round_robin",
    ]
    mode_labels = ["Statička", "Zamrznuta", "Prequential", "Djelimična"]
    selected = summary.set_index("mode").loc[selected_modes]
    figure, axes = plt.subplots(1, 3, figsize=(10.0, 3.4))
    x_positions = np.arange(len(selected_modes))
    for axis, column, title in (
        (axes[0], "coverage", "Pokrivenost"),
        (axes[1], "strict_top1", "Top-1 uz preporuku"),
        (axes[2], "mean_regret_log2", "Propušteni dobitak (log2)"),
    ):
        values = selected[column].astype(float).to_numpy()
        axis.bar(x_positions, np.nan_to_num(values, nan=0.0), color="#176B61")
        for index, value in enumerate(values):
            label = "n/a" if not np.isfinite(value) else f"{value:.2f}"
            axis.text(index, 0.02, label, ha="center", va="bottom", fontsize=8)
        axis.set_xticks(x_positions, mode_labels, rotation=28, ha="right")
        axis.set_title(title)
        axis.grid(axis="y", color="#D9DEDF", linewidth=0.6)
        if column != "mean_regret_log2":
            axis.set_ylim(0, 1.05)
    figure.tight_layout()
    figure.savefig(out_dir / "confirmatory_policy_comparison.pdf", bbox_inches="tight")
    plt.close(figure)


def _scenario_outcome_summary(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for episode_id, group in outcomes.groupby("episode_id", sort=False):
        gains = group.set_index("mitigation_action")["target_log2_gain"].astype(float)
        ordered = gains.sort_values(ascending=False)
        strict_best = str(ordered.index[0])
        rows.append(
            {
                "episode_id": str(episode_id),
                "query_id": str(group.iloc[0]["query_id"]),
                "strict_best_action": strict_best,
                "runner_up_action": str(ordered.index[1]),
                "winner_margin_log2": float(ordered.iloc[0] - ordered.iloc[1]),
                "tie_acceptable_actions": ",".join(
                    sorted(
                        group[group["tie_acceptable"].astype(bool)][
                            "mitigation_action"
                        ].astype(str)
                    )
                ),
                "strict_winner_repeat_count": int(
                    group[group["mitigation_action"].astype(str).eq(strict_best)][
                        "winner_count_of_five"
                    ].iloc[0]
                ),
                **{f"gain__{action}": float(gains[action]) for action in ACTIONS},
            }
        )
    return pd.DataFrame(rows)


def _leakage_audit(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    reference_states: pd.DataFrame,
    predictions: pd.DataFrame,
    feature_names: list[str],
) -> dict[str, Any]:
    confirmatory_queries = set(events["query_id"].astype(str))
    confirmatory_hashes = set(events["normalized_sql_hash"].astype(str)) - {""}
    reference_queries = set(reference_states["query_id"].astype(str))
    reference_hashes = (
        set(reference_states["normalized_sql_hash"].astype(str)) - {""}
        if "normalized_sql_hash" in reference_states.columns
        else set()
    )
    forbidden_feature_tokens = (
        "mitigation_action",
        "target_log2_gain",
        "after__",
        "query_id",
        "scenario_id",
    )
    frozen = predictions[predictions["mode"].astype(str).eq("frozen_transfer")]
    frozen_neighbor_queries = {
        str(neighbor.get("query_id", ""))
        for payload in frozen["neighbors_json"]
        for neighbor in json.loads(str(payload))
    }
    checks = {
        "confirmatory_query_ids_absent_from_reference_memory": not bool(
            confirmatory_queries & reference_queries
        ),
        "confirmatory_sql_hashes_absent_from_reference_memory": not bool(
            confirmatory_hashes & reference_hashes
        ),
        "state_features_exclude_actions_outcomes_and_ids": not any(
            token in feature
            for feature in feature_names
            for token in forbidden_feature_tokens
        ),
        "frozen_transfer_neighbors_exclude_confirmatory_queries": not bool(
            frozen_neighbor_queries & confirmatory_queries
        ),
        "frozen_transfer_memory_is_constant": frozen["memory_state_count"].nunique() == 1,
        "all_replays_evaluate_identical_oracle_rows": predictions.groupby("mode")[
            "episode_id"
        ].nunique().eq(events["episode_id"].nunique()).all(),
        "one_outcome_row_per_scenario_action": len(outcomes)
        == len(events) * len(ACTIONS),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "reference_query_count": len(reference_queries),
        "confirmatory_query_count": len(confirmatory_queries),
        "feature_count": len(feature_names),
    }


def analyze(contract_path: Path, index_dir: Path, out_dir: Path) -> None:
    contract = read_yaml(contract_path)
    validate_contract(contract)
    out_dir.mkdir(parents=True, exist_ok=True)
    memory, dba = memory_modules()
    state_contract_path = ROOT / contract["model_freeze"]["state_contract"]
    state_contract = read_yaml(state_contract_path)
    specifications = state_contract["state_representation"]["features"]
    feature_names = list(specifications)
    executions = memory.enrich_executions(index_dir).copy()
    collection = _collection_validation(index_dir, executions, contract)
    write_json(out_dir / "collection_validation.json", collection)
    if collection["status"] != "PASS":
        raise ValueError("Collection validation failed; analysis is blocked")
    events, outcomes, repetitions = _scenario_observations(
        executions, contract, feature_names
    )
    events.to_csv(out_dir / "scenario_states.csv", index=False)
    outcomes.to_csv(out_dir / "action_outcomes.csv", index=False)
    repetitions.to_csv(out_dir / "paired_repetition_outcomes.csv", index=False)
    scenario_summary = _scenario_outcome_summary(outcomes)
    scenario_summary.to_csv(out_dir / "scenario_outcome_summary.csv", index=False)
    reference_states, reference_outcomes = _reference_memory(contract, feature_names, dba)
    processor = memory.StatePreprocessor(
        specifications=specifications,
        pca_components=int(contract["model_freeze"]["pca_components"]),
        minimum_active_features=int(
            state_contract["state_representation"]["minimum_active_features"]
        ),
    )
    reference_values = processor.fit(reference_states)
    event_values = processor.transform(events)
    threshold = dba._nearest_threshold(
        reference_values,
        float(contract["model_freeze"]["coverage_quantile"]),
        str(contract["model_freeze"]["distance_metric"]),
    )
    replays = [
        _static_action_median_replay(
            events,
            outcomes,
            reference_states,
            reference_outcomes,
            dba,
        ),
        _replay(
            events,
            outcomes,
            reference_states,
            reference_outcomes,
            reference_values,
            event_values,
            threshold,
            contract,
            dba,
            mode="frozen_transfer",
            reveal_policy="none",
        ),
        _replay(
            events,
            outcomes,
            reference_states,
            reference_outcomes,
            reference_values,
            event_values,
            threshold,
            contract,
            dba,
            mode="prequential_full_feedback",
            reveal_policy="all",
        ),
        _replay(
            events,
            outcomes,
            reference_states,
            reference_outcomes,
            reference_values,
            event_values,
            threshold,
            contract,
            dba,
            mode="partial_feedback_round_robin",
            reveal_policy="round_robin",
        ),
    ]
    for seed in contract["uncertainty"]["partial_feedback_random_seeds"]:
        replays.append(
            _replay(
                events,
                outcomes,
                reference_states,
                reference_outcomes,
                reference_values,
                event_values,
                threshold,
                contract,
                dba,
                mode=f"partial_feedback_random_seed_{seed}",
                reveal_policy="random_one",
                random_seed=int(seed),
            )
        )
    predictions = pd.concat(replays, ignore_index=True)
    predictions.to_csv(out_dir / "per_scenario_predictions.csv", index=False)
    summary = _summary(predictions)
    confidence = _bootstrap_summary(
        predictions,
        samples=int(contract["uncertainty"]["bootstrap_samples"]),
        seed=int(contract["uncertainty"]["bootstrap_seed"]) + 1000,
    )
    summary = summary.merge(confidence, on="mode", how="left", validate="one_to_one")
    summary.to_csv(out_dir / "evaluation_summary.csv", index=False)
    confidence.to_csv(out_dir / "evaluation_cluster_bootstrap.csv", index=False)
    _write_figures(out_dir, repetitions, summary)
    leakage = _leakage_audit(
        events,
        outcomes,
        reference_states,
        predictions,
        feature_names,
    )
    write_json(out_dir / "leakage_audit.json", leakage)
    if leakage["status"] != "PASS":
        raise ValueError("Leakage audit failed; confirmatory claims are blocked")
    if processor.selection_audit is not None:
        processor.selection_audit.to_csv(out_dir / "state_feature_selection.csv", index=False)
    write_json(
        out_dir / "analysis_manifest.json",
        {
            "status": "PASS",
            "contract_sha256": sha256_file(contract_path),
            "collection_validation": "PASS",
            "reference_state_count": len(reference_states),
            "confirmatory_scenario_count": len(events),
            "action_outcome_count": len(outcomes),
            "paired_repetition_outcome_count": len(repetitions),
            "active_feature_count": len(processor.active_features or []),
            "pca_component_count": int(event_values.shape[1]),
            "coverage_threshold": threshold,
            "refit_on_confirmatory_data": False,
            "confirmatory_outcomes_used_for_transform": False,
            "confirmatory_outcomes_used_for_threshold": False,
            "frozen_transfer_adds_confirmatory_history": False,
            "leakage_audit": "PASS",
            "warmup_contract": "zero explicit warm-up executions for every condition",
            "h1_absolute_relative_contribution_isolated": False,
        },
    )
    action_wins = (
        scenario_summary["strict_best_action"]
        .value_counts()
        .reindex(ACTIONS, fill_value=0)
        .to_dict()
    )
    stable_winners = int(scenario_summary["strict_winner_repeat_count"].eq(5).sum())
    practical_ties = int(
        scenario_summary["tie_acceptable_actions"]
        .astype(str)
        .str.contains(",", regex=False)
        .sum()
    )
    frozen = summary.set_index("mode").loc["frozen_transfer"]
    prequential = summary.set_index("mode").loc["prequential_full_feedback"]
    partial = summary.set_index("mode").loc["partial_feedback_round_robin"]
    static = summary.set_index("mode").loc["static_action_median"]
    lines = [
        "# Potvrdni panel lokalne intervencijske memorije",
        "",
        "Panel sadrzi 15 novih SQL oblika, cetiri uslova i pet ponavljanja po uslovu.",
        "Transformacija R3, k=5, euklidska udaljenost i empirical-P99 pravilo nisu refitovani.",
        "Sva 300 izvrsenja prosla su kolekcijski i rezultatski ugovor.",
        "",
        "## Stabilnost izmjerenih ishoda",
        "",
        f"- ista akcija pobijedila je u svih pet ponavljanja za {stable_winners}/15 scenarija;",
        f"- prakticno izjednacenih pobjednika: {practical_ties}/15;",
        (
            "- broj pobjeda: remote putanja "
            f"{action_wins['mitigate_remote_path_bundle']}/15, regionalni Top-K "
            f"{action_wins['regional_topk_candidates']}/15, GAC work_mem "
            f"{action_wins['increase_gac_work_mem']}/15."
        ),
        "",
        "## Zbirni rezultati",
        "",
        _markdown_table(summary),
        "",
        (
            "Strogi transfer ne dodaje nijedan ishod novog panela u memoriju. "
            "Prequential i partial-feedback replay koriste isti fizicki panel, "
            "ali razlicite unaprijed definisane ugovore otkrivanja ishoda."
        ),
        "",
        "## Tumacenje",
        "",
        (
            "Zamrznuti transfer apstinirao je za "
            f"{int(frozen['abstention_count'])}/15 potpuno novih SQL oblika: "
            "njihova fizicka stanja bila su izvan zamrznute P99 granice."
        ),
        (
            "Nakon prequentialnog dodavanja lokalnih epizoda pokrivenost je bila "
            f"{int(prequential['recommendation_count'])}/15, Top-1 "
            f"{prequential['strict_top1']:.3f}, a srednji regret "
            f"{prequential['mean_regret_log2']:.3f} log2."
        ),
        (
            "Round-robin partial-feedback replay ostvario je pokrivenost "
            f"{int(partial['recommendation_count'])}/15, Top-1 "
            f"{partial['strict_top1']:.3f} i srednji regret "
            f"{partial['mean_regret_log2']:.3f} log2."
        ),
        (
            "Staticki action-median baseline imao je Top-1 "
            f"{static['strict_top1']:.3f} i regret "
            f"{static['mean_regret_log2']:.3f} log2. Lokalna memorija zato je "
            "vratila pokrivenost i smanjila regret u round-robin replayu, ali "
            "nije dala uvjerljiv dokaz robusno boljeg izbora akcije na ovom panelu."
        ),
        "",
        (
            "Zakljucak se odnosi na zamrznuti R3 prostor i tri ispitane akcije. "
            "Panel ne izoluje doprinos apsolutnih naspram relativnih pokazatelja."
        ),
    ]
    (out_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_input_manifest(
        out_dir,
        contract_path=contract_path,
        state_contract_path=state_contract_path,
        index_dir=index_dir,
        reference_report=ROOT / contract["model_freeze"]["reference_report"],
    )
    _write_output_checksums(out_dir)
    print(out_dir)


def main() -> int:
    args = parse_args()
    if args.command == "prepare":
        prepare(args.contract, args.source_dir, args.out_dir)
    elif args.command == "validate-design":
        validate_design(args.contract, args.rendered_dir, args.out_dir)
    elif args.command == "analyze":
        analyze(args.contract, args.index_dir, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
