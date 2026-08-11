from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from master_regimes.config import load_yaml
from master_regimes.confirmatory_skew import build_confirmatory_skew_plan
from master_regimes.corpus_adapter import render_corpus
from master_regimes.corpus_manifest import validate_corpus_manifest

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_PROGRAM = REPO_ROOT / "configs/collection/pressure_raw_program_v1.yml"
DEFAULT_OUTPUT = REPO_ROOT / "generated/corpus/pressure-raw-v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def resolve(base: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def workspace_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path.resolve())


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


DATASET_PROGRESS_WEIGHTS = {
    "small": 1.0,
    "medium": 3.0,
    "large": 8.0,
}

RUNTIME_PROGRESS_MULTIPLIERS = {
    "pressure_remote_bandwidth_10mbit": 4.0,
    "pressure_remote_bandwidth_50mbit": 2.0,
    "pressure_remote_delay_80ms": 4.0,
    "pressure_remote_delay_20ms": 2.0,
    "pressure_remote_fetch_100": 4.0,
    "pressure_remote_fetch_2000": 2.0,
    "pressure_remote_raw_stressed": 2.0,
    "pressure_gac_memory_stressed": 1.5,
    "pressure_regional_memory_stressed": 1.5,
}


def progress_profile(
    *,
    row: dict[str, Any],
    dataset_specs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    dataset_id = str(
        row.get("dataset_profile_id")
        or row.get("dataset_id")
        or ""
    )
    dataset_spec = dataset_specs.get(dataset_id) or {}
    size_class = str(dataset_spec.get("size_class", "medium"))
    dataset_weight = DATASET_PROGRESS_WEIGHTS.get(size_class, 3.0)
    runtime_id = str(row.get("runtime_config_id", "default"))
    runtime_multiplier = RUNTIME_PROGRESS_MULTIPLIERS.get(runtime_id, 1.0)
    repetition_index = int(row.get("repetition_index", 0) or 0)
    planned_query_passes = 2 if repetition_index == 0 else 1
    work_units = (
        dataset_weight
        * runtime_multiplier
        * planned_query_passes
    )
    if work_units >= 24:
        cost_class = "extreme"
    elif work_units >= 8:
        cost_class = "heavy"
    elif work_units >= 3:
        cost_class = "medium"
    else:
        cost_class = "light"
    return {
        "dataset_size_class": size_class,
        "planned_query_passes": planned_query_passes,
        "progress_dataset_weight": dataset_weight,
        "progress_runtime_multiplier": runtime_multiplier,
        "planned_work_units": round(work_units, 3),
        "progress_cost_class": cost_class,
        "progress_weight_basis": (
            f"dataset={size_class}:{dataset_weight:g};"
            f"runtime={runtime_id}:{runtime_multiplier:g};"
            f"passes={planned_query_passes}"
        ),
    }


def add_progress_profiles(
    *,
    rows: list[dict[str, Any]],
    dataset_specs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            **row,
            **progress_profile(
                row=row,
                dataset_specs=dataset_specs,
            ),
        }
        for row in rows
    ]


def standard_batch(
    *,
    batch: dict[str, Any],
    source_path: Path,
    dataset_specs: dict[str, dict[str, Any]],
    output_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validation = validate_corpus_manifest(source_path)
    if validation["status"] != "ok":
        raise ValueError(f"{batch['batch_id']} invalid: " + "; ".join(validation["errors"]))
    batch_dir = output_root / "batches" / str(batch["batch_id"])
    rendered_dir = batch_dir / "rendered"
    if rendered_dir.exists():
        shutil.rmtree(rendered_dir)
    plan_path = render_corpus(
        manifest_path=source_path,
        output_dir=rendered_dir,
    )
    plan = load_yaml(plan_path)
    matrix_rows: list[dict[str, Any]] = []
    for group in plan["groups"]:
        instance_manifest = WORKSPACE_ROOT / str(group["instance_manifest"])
        instance_rows = add_progress_profiles(
            rows=read_csv(instance_manifest),
            dataset_specs=dataset_specs,
        )
        write_csv(instance_manifest, instance_rows)
        for row in instance_rows:
            matrix_rows.append(
                {
                    **row,
                    "backend": "standard_corpus",
                    "group_id": str(group["group_id"]),
                    "group_plan": workspace_relative(plan_path),
                    "execution_status": "planned",
                }
            )
    batch_manifest = {
        "batch_id": batch["batch_id"],
        "kind": batch["kind"],
        "pressure_axis": batch.get("pressure_axis", ""),
        "backend": "standard_corpus",
        "status": batch["status"],
        "source_manifest": workspace_relative(source_path),
        "source_manifest_sha256": sha256_file(source_path),
        "rendered_plan": workspace_relative(plan_path),
        "rendered_execution_count": len(matrix_rows),
        "rendered_group_count": len(plan["groups"]),
        "groups": [
            {
                "group_id": str(group["group_id"]),
                "instance_count": int(group["instance_count"]),
                "target_group": str(group["target_group"]),
                "target_host": str(
                    load_yaml(
                        resolve(
                            WORKSPACE_ROOT,
                            str(group["sweep_config"]),
                        )
                    )
                    .get("collection", {})
                    .get("target_host", "")
                ),
                "measurement_lane": str(
                    load_yaml(
                        resolve(
                            WORKSPACE_ROOT,
                            str(group["sweep_config"]),
                        )
                    )
                    .get("execution_policy", {})
                    .get("measurement_lane", "")
                ),
                "dataset_profile_id": str(group["dataset_profile_id"]),
                "dataset_size_class": str(
                    dataset_specs.get(
                        str(group["dataset_profile_id"]),
                        {},
                    ).get("size_class", "medium")
                ),
                "planned_work_units": round(
                    sum(
                        float(row.get("planned_work_units", 1) or 1)
                        for row in read_csv(
                            WORKSPACE_ROOT
                            / str(group["instance_manifest"])
                        )
                    ),
                    3,
                ),
                "instance_manifest": str(group["instance_manifest"]),
            }
            for group in plan["groups"]
        ],
    }
    manifest_path = batch_dir / "batch_manifest.yml"
    write_yaml(manifest_path, batch_manifest)
    batch_manifest["batch_manifest"] = workspace_relative(manifest_path)
    return batch_manifest, matrix_rows


def dataset_profile_map(
    dataset_sweep_path: Path,
) -> dict[str, dict[str, Any]]:
    sweep = load_yaml(dataset_sweep_path)
    result: dict[str, dict[str, Any]] = {}
    for dataset_id, spec in (sweep.get("profiles") or {}).items():
        profile_path = resolve(dataset_sweep_path.parent, str(spec["profile"]))
        result[str(dataset_id)] = {
            **spec,
            "profile_path": profile_path,
        }
    return result


def list_parameters(parameters: dict[str, Any]) -> dict[str, list[Any]]:
    return {
        str(key): value if isinstance(value, list) else [value] for key, value in parameters.items()
    }


def skew_logical_question_id(condition_id: str) -> str:
    if "tenant_point" in condition_id:
        return "tenant_point_rollup"
    if "filter" in condition_id:
        return "event_filter_summary"
    if "rollup" in condition_id:
        return "event_full_scan_summary"
    return "top_tenants"


def hot_ids(profile: dict[str, Any], region: str) -> list[int]:
    regions = profile.get("regions") or {}
    region_spec = regions.get(region) or {}
    start, end = region_spec["tenant_id_range"]
    distribution = {
        **(profile.get("distribution") or {}),
        **(region_spec.get("distribution") or {}),
    }
    if str(distribution.get("skew_profile", "balanced")).lower() == "balanced":
        return []
    hot_pct = float(distribution.get("hot_tenant_pct", 1) or 1)
    count = max(1, round((int(end) - int(start) + 1) * hot_pct / 100))
    return list(range(int(start), min(int(end), int(start) + count - 1) + 1))


def skew_condition_parameters(
    condition: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    parameters = dict(condition["parameters"])
    if str(condition["template_id"]) != "gac_fdw_multiregion_hot_worker_probe":
        return parameters
    regions = profile.get("regions") or {}
    for region, prefix in (("eu", "eu"), ("us", "us")):
        region_hot_ids = hot_ids(profile, region)
        start, end = regions[region]["tenant_id_range"]
        selected = region_hot_ids or list(
            range(int(start), min(int(end), int(start) + 9) + 1)
        )
        parameters[f"{prefix}_hot_tenant_min"] = min(selected)
        parameters[f"{prefix}_hot_tenant_max"] = max(selected)
    return parameters


def skew_source_manifest(
    *,
    batch: dict[str, Any],
    batch_source: dict[str, Any],
    dataset_id: str,
    profile_path: Path,
    segment_dir: Path,
) -> Path:
    source_path = segment_dir / "source_manifest.yml"
    profile = load_yaml(profile_path)
    expected_hot_regions = [
        region for region in ("eu", "us") if hot_ids(profile, region)
    ]
    cells: list[dict[str, Any]] = []
    for condition in batch_source["query_conditions"]:
        parameters = skew_condition_parameters(condition, profile)
        signature_role = str(condition.get("skew_signature_role", ""))
        is_positive_case = signature_role == "task_and_worker_positive"
        cells.append(
            {
                "corpus_cell_id": str(condition["id"]),
                "logical_question_id": skew_logical_question_id(str(condition["id"])),
                "execution_strategy": "multiregion_union",
                "template_id": str(condition["template_id"]),
                "dataset_profile_id": dataset_id,
                "runtime_config_id": "default",
                "topology_id": "eu_us_gac",
                "intervention_role": (
                    "positive_case" if is_positive_case else "negative_control"
                ),
                "intervention_axis": "dataset_and_shard_placement",
                "pressure_axis": "worker_data_skew",
                "pressure_level": "combined",
                "variant": "combined",
                "pressure_pair_key": f"skew__{condition['id']}",
                "mitigation_action": "disperse_hot_shards",
                "target_metric": "skew_multidimensional_reserved_for_phase_2",
                "dataset_role": (
                    "pressure_isolated"
                    if is_positive_case
                    else "pressure_negative_control"
                ),
                "activates_hot_data": bool(condition["activates_hot_data"]),
                "task_skew_expected": bool(
                    condition.get("task_skew_expected", False)
                ),
                "worker_skew_placement_sensitive": bool(
                    condition.get("worker_skew_placement_sensitive", False)
                ),
                "shard_pruning_expected": bool(
                    condition.get("shard_pruning_expected", False)
                ),
                "skew_signature_role": signature_role,
                "expected_hot_regions": expected_hot_regions,
                "parameters": list_parameters(parameters),
            }
        )
    manifest = {
        "corpus_id": f"{batch['batch_id']}-{dataset_id}-source",
        "corpus_version": batch_source["corpus_version"],
        "batch_id": batch["batch_id"],
        "collection_contract_version": batch_source["collection_contract_version"],
        "parameter_defaults": {
            str(key): value if isinstance(value, list) else [value]
            for key, value in (batch_source.get("parameter_defaults") or {}).items()
        },
        "query_groups": os.path.relpath(
            REPO_ROOT / "workloads/corpus/query-groups.yml",
            source_path.parent,
        ),
        "runtime_catalog": os.path.relpath(
            REPO_ROOT / "workloads/corpus/runtime-configs.yml",
            source_path.parent,
        ),
        "dataset_profiles": {
            dataset_id: {
                "profile": os.path.relpath(profile_path, source_path.parent),
                "load_method": "copy_pipe",
            }
        },
        "execution_budget": {
            "hard_timeout_seconds": int(batch_source["execution_policy"]["hard_timeout_seconds"]),
            "timeout_grace_seconds": int(batch_source["execution_policy"]["timeout_grace_seconds"]),
        },
        "execution_policy": {
            "cache_policy": "mixed_cache_worker_skew_raw",
            "order_policy": "deterministic_shuffle",
            "shuffle_seed": 20260730,
            "repetitions_default": 1,
            "record_run_order": True,
            "record_buffer_features": True,
            "fdw_auto_explain": True,
            "os_sampler": True,
            "result_signature": True,
            "result_signature_scope": str(
                batch_source["execution_policy"].get(
                    "result_signature_scope",
                    "every_execution",
                )
            ),
        },
        "cells": cells,
    }
    write_yaml(source_path, manifest)
    return source_path


def skew_config(
    *,
    batch: dict[str, Any],
    batch_source: dict[str, Any],
    dataset_id: str,
    profile_path: Path,
    source_manifest: Path,
    segment_dir: Path,
) -> Path:
    profile = load_yaml(profile_path)
    expected_hot_regions = [
        region for region in ("eu", "us") if hot_ids(profile, region)
    ]
    query_conditions = []
    for condition in batch_source["query_conditions"]:
        parameters = skew_condition_parameters(condition, profile)
        query_conditions.append(
            {
                "condition_id": str(condition["id"]),
                "corpus_cell_id": str(condition["id"]),
                "logical_question_id": (
                    "tenant_point_rollup"
                    if "tenant_point" in str(condition["id"])
                    else (
                        "event_filter_summary"
                        if "filter" in str(condition["id"])
                        else (
                            "event_full_scan_summary"
                            if "rollup" in str(condition["id"])
                            else "top_tenants"
                        )
                    )
                ),
                "physical_strategy_id": (
                    "hot_data_activation"
                    if condition["activates_hot_data"]
                    else "cold_or_selective_control"
                ),
                "activates_hot_data": bool(condition["activates_hot_data"]),
                "task_skew_expected": bool(
                    condition.get("task_skew_expected", False)
                ),
                "worker_skew_placement_sensitive": bool(
                    condition.get("worker_skew_placement_sensitive", False)
                ),
                "shard_pruning_expected": bool(
                    condition.get("shard_pruning_expected", False)
                ),
                "skew_signature_role": str(
                    condition.get("skew_signature_role", "")
                ),
                "expected_hot_regions": expected_hot_regions,
                "template_id": str(condition["template_id"]),
                "parameters": {
                    **(batch_source.get("parameter_defaults") or {}),
                    **parameters,
                },
            }
        )
    analysis_id = f"{batch['batch_id']}-{dataset_id}"
    config = {
        "analysis_id": analysis_id,
        "protocol_version": 1,
        "source_manifest": repo_relative(source_manifest),
        "source_render_dir": repo_relative(segment_dir / "source-render"),
        "output_dir": repo_relative(segment_dir / "plan"),
        "selection": repo_relative(segment_dir / "selection.csv"),
        "design": {
            "topology_id": "eu_us_gac",
            "runtime_config_id": "default",
            "repetitions": int(batch_source["repetitions"]),
            "state_order": ["B", "C"],
            "order_policy": "deterministic_shuffle_within_state",
            "shuffle_seed": 20260730,
            "cache_policy": "mixed_cache_worker_skew_raw",
            "warmup_per_instance": False,
            "explicit_cache_reset": False,
            "database_result_rows_stored": False,
        },
        "states": {
            "B": {
                "state_name": "skew_dispersed",
                "dataset_profile_id": dataset_id,
                "placement_state_id": "hot_shards_dispersed",
                "logical_data_contract_id": (f"{dataset_id}-seed-{profile.get('seed', 42)}"),
                "placement_action": "disperse_hot_shards",
            },
            "C": {
                "state_name": "skew_concentrated",
                "dataset_profile_id": dataset_id,
                "placement_state_id": "hot_shards_concentrated",
                "logical_data_contract_id": (f"{dataset_id}-seed-{profile.get('seed', 42)}"),
                "placement_action": "concentrate_hot_shards",
            },
        },
        "query_conditions": query_conditions,
        "capability_smoke": {
            "condition_ids": [str(condition["condition_id"]) for condition in query_conditions],
            "repetition_indices": list(range(int(batch_source["repetitions"]))),
            "require_checkpoint": False,
        },
        "hot_tenant_contract": {
            "source_profile": repo_relative(profile_path),
            "eu_hot_tenant_ids": hot_ids(profile, "eu"),
            "us_hot_tenant_ids": hot_ids(profile, "us"),
        },
        "placement": {
            "metadata_source": "citus_shards",
            "move_function": "citus_move_shard_placement",
            "shard_transfer_mode": "block_writes",
            "dispersed": {"dominant_hot_event_share_max": 0.65},
            "concentrated": {"dominant_hot_event_share_min": 0.80},
            "rollback": {
                "primary": ("replay_inverse_moves_from_placement_intervention_manifest"),
                "fallback": "clean_reload_same_dataset_profile_and_seed",
            },
        },
        "artifact_contract": {
            "collection_contract_version": batch_source["collection_contract_version"],
            "required_query_scopes": [
                "main",
                "regional_coordinator",
                "worker_task",
            ],
            "database_result_rows_stored": False,
            "result_signature_required": True,
            "result_signature_scope": str(
                batch_source["execution_policy"].get(
                    "result_signature_scope",
                    "every_execution",
                )
            ),
            "os_sampler_required": True,
        },
    }
    config_path = segment_dir / "config.yml"
    write_yaml(config_path, config)
    return config_path


def skew_batch(
    *,
    batch: dict[str, Any],
    source_path: Path,
    dataset_specs: dict[str, dict[str, Any]],
    output_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = load_yaml(source_path)
    condition_contracts = {
        str(item["id"]): item for item in source["query_conditions"]
    }
    segments: list[dict[str, Any]] = []
    matrix_rows: list[dict[str, Any]] = []
    batch_dir = output_root / "batches" / str(batch["batch_id"])
    for dataset_id in source["datasets"]:
        dataset_spec = dataset_specs[str(dataset_id)]
        dataset_profile = load_yaml(dataset_spec["profile_path"])
        expected_hot_regions = [
            region
            for region in ("eu", "us")
            if hot_ids(dataset_profile, region)
        ]
        segment_id = f"{batch['batch_id']}-{dataset_id}"
        segment_dir = batch_dir / "segments" / str(dataset_id)
        source_manifest = skew_source_manifest(
            batch=batch,
            batch_source=source,
            dataset_id=str(dataset_id),
            profile_path=dataset_spec["profile_path"],
            segment_dir=segment_dir,
        )
        validation = validate_corpus_manifest(source_manifest)
        if validation["status"] != "ok":
            raise ValueError(f"{segment_id} invalid: " + "; ".join(validation["errors"]))
        config_path = skew_config(
            batch=batch,
            batch_source=source,
            dataset_id=str(dataset_id),
            profile_path=dataset_spec["profile_path"],
            source_manifest=source_manifest,
            segment_dir=segment_dir,
        )
        outputs = build_confirmatory_skew_plan(config_path=config_path)
        plan = load_yaml(outputs["plan"])
        for plan_group in plan["groups"]:
            group_manifest = WORKSPACE_ROOT / str(
                plan_group["instance_manifest"]
            )
            group_rows = add_progress_profiles(
                rows=read_csv(group_manifest),
                dataset_specs=dataset_specs,
            )
            write_csv(group_manifest, group_rows)
        design = pd.read_csv(outputs["design_matrix"], low_memory=False)
        for row in design.to_dict(orient="records"):
            condition_contract = condition_contracts[
                str(row["query_condition_id"])
            ]
            activates_hot_data = bool(
                condition_contract["activates_hot_data"]
            )
            signature_role = str(
                condition_contract.get("skew_signature_role", "")
            )
            is_positive_case = signature_role == "task_and_worker_positive"
            variant = "mitigated" if str(row["state_id"]) == "B" else "stressed"
            pair_payload = "::".join(
                (
                    str(source["corpus_version"]),
                    str(batch["batch_id"]),
                    f"skew__{row['query_condition_id']}",
                    str(row["dataset_id"]),
                    "eu_us_gac",
                    str(row["param_json"]),
                )
            )
            pair_id = "pair-" + hashlib.sha256(pair_payload.encode("utf-8")).hexdigest()[:24]
            repetition_index = int(row["repetition_index"])
            matrix_rows.append(
                {
                    **row,
                    "batch_id": batch["batch_id"],
                    "corpus_version": source["corpus_version"],
                    "collection_contract_version": source["collection_contract_version"],
                    "backend": "placement_aware_worker",
                    "segment_id": segment_id,
                    "group_plan": workspace_relative(outputs["plan"]),
                    "condition_id": row["execution_condition_id"],
                    "execution_slot_id": row["slot_id"],
                    "pair_id": pair_id,
                    "repeat_id": f"{pair_id}::r{repetition_index}",
                    "pressure_axis": "worker_data_skew",
                    "pressure_level": variant,
                    "variant": variant,
                    "intervention_role": (
                        "positive_case"
                        if is_positive_case
                        else "negative_control"
                    ),
                    "intervention_axis": "dataset_and_shard_placement",
                    "pressure_pair_key": (f"skew__{row['query_condition_id']}"),
                    "activates_hot_data": activates_hot_data,
                    "task_skew_expected": bool(
                        condition_contract.get("task_skew_expected", False)
                    ),
                    "worker_skew_placement_sensitive": bool(
                        condition_contract.get(
                            "worker_skew_placement_sensitive",
                            False,
                        )
                    ),
                    "shard_pruning_expected": bool(
                        condition_contract.get("shard_pruning_expected", False)
                    ),
                    "skew_signature_role": signature_role,
                    "expected_hot_regions": ",".join(expected_hot_regions),
                    "logical_question_id": skew_logical_question_id(str(row["query_condition_id"])),
                    "mitigation_action": "disperse_hot_shards",
                    "target_metric": "skew_multidimensional_reserved_for_phase_2",
                    "dataset_role": (
                        "pressure_isolated"
                        if is_positive_case
                        else "pressure_negative_control"
                    ),
                    "topology_id": "eu_us_gac",
                    "dataset_profile_id": row["dataset_id"],
                    "runtime_config_id": "default",
                    "execution_status": "planned",
                    **progress_profile(
                        row={
                            **row,
                            "dataset_profile_id": row["dataset_id"],
                            "runtime_config_id": "default",
                        },
                        dataset_specs=dataset_specs,
                    ),
                }
            )
        segments.append(
            {
                "segment_id": segment_id,
                "dataset_profile_id": dataset_id,
                "backend": "placement_aware_worker",
                "config": workspace_relative(config_path),
                "plan": workspace_relative(outputs["plan"]),
                "execution_count": int(len(design)),
                "group_count": int(len(plan["groups"])),
                "dataset_size_class": str(
                    dataset_specs.get(str(dataset_id), {}).get(
                        "size_class",
                        "medium",
                    )
                ),
                "planned_work_units": round(
                    sum(
                        float(
                            progress_profile(
                                row={
                                    **row,
                                    "dataset_profile_id": row["dataset_id"],
                                    "runtime_config_id": "default",
                                },
                                dataset_specs=dataset_specs,
                            )["planned_work_units"]
                        )
                        for row in design.to_dict(orient="records")
                    ),
                    3,
                ),
            }
        )
    batch_manifest = {
        "batch_id": batch["batch_id"],
        "kind": batch["kind"],
        "pressure_axis": batch["pressure_axis"],
        "backend": "placement_aware_worker",
        "status": batch["status"],
        "source_manifest": workspace_relative(source_path),
        "source_manifest_sha256": sha256_file(source_path),
        "rendered_execution_count": len(matrix_rows),
        "rendered_segment_count": len(segments),
        "segments": segments,
    }
    manifest_path = batch_dir / "batch_manifest.yml"
    write_yaml(manifest_path, batch_manifest)
    batch_manifest["batch_manifest"] = workspace_relative(manifest_path)
    return batch_manifest, matrix_rows


def pair_coverage(matrix: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    if matrix.empty:
        return pd.DataFrame(), {}
    records: list[dict[str, Any]] = []
    for (axis, pair_id), group in matrix.groupby(
        ["pressure_axis", "pair_id"],
        dropna=False,
    ):
        variants = sorted({str(value) for value in group["variant"].dropna() if str(value)})
        records.append(
            {
                "pressure_axis": axis,
                "pair_id": pair_id,
                "variants": ",".join(variants),
                "condition_count": int(group["condition_id"].nunique()),
                "physical_execution_count": int(len(group)),
                "dataset_profile_id": ",".join(
                    sorted(
                        str(value)
                        for value in set(group["dataset_profile_id"].dropna().astype(str))
                    )
                ),
                "template_id": ",".join(
                    sorted(str(value) for value in set(group["template_id"].dropna().astype(str)))
                ),
                "variant_execution_counts": stable_json(
                    {
                        str(variant): int(count)
                        for variant, count in group.groupby(
                            "variant",
                            dropna=False,
                        )
                        .size()
                        .items()
                    }
                ),
                "pair_context_contract_valid": all(
                    group[column].dropna().astype(str).nunique() == 1
                    for column in (
                        "dataset_profile_id",
                        "param_json",
                        "topology_id",
                        "logical_question_id",
                    )
                    if column in group
                ),
                "result_equivalence_status": "pending_execution",
                "structurally_complete_stressed_mitigated_pair": (
                    "mitigated" in variants and "stressed" in variants
                ),
            }
        )
    frame = pd.DataFrame(records)
    frame["planned_counterfactual_pair"] = frame[
        "structurally_complete_stressed_mitigated_pair"
    ].eq(True) & frame["pair_context_contract_valid"].eq(True)
    planned = frame[frame["planned_counterfactual_pair"].eq(True)]
    counts = {
        str(axis): int(count) for axis, count in planned.groupby("pressure_axis").size().items()
    }
    return frame, counts


def coverage_summary(matrix: pd.DataFrame) -> dict[str, Any]:
    pair_frame, planned_pairs = pair_coverage(matrix)
    return {
        "physical_execution_count": int(len(matrix)),
        "distinct_configuration_count": int(matrix["condition_id"].nunique()),
        "planned_counterfactual_pair_count": int(pair_frame["planned_counterfactual_pair"].sum()),
        "distinct_sql_shape_count": int(
            matrix[["template_id", "param_json"]].drop_duplicates().shape[0]
        ),
        "dataset_profile_count": int(matrix["dataset_profile_id"].nunique()),
        "intervention_level_count": int(matrix["variant"].nunique()),
        "planned_pairs_by_axis": planned_pairs,
    }


def _single_text(group: pd.DataFrame, column: str) -> str:
    if column not in group:
        return ""
    values = sorted(
        {
            str(value)
            for value in group[column].dropna()
            if str(value) and str(value).lower() != "nan"
        }
    )
    return values[0] if len(values) == 1 else ",".join(values)


def _network_subblock(pair_key: str, axis: str) -> str:
    if pair_key.startswith("remote_cal_bandwidth"):
        return "bandwidth_only"
    if pair_key.startswith("remote_cal_delay"):
        return "delay_only"
    if pair_key.startswith("remote_cal_fetch"):
        return "fetch_only"
    if axis == "remote_path":
        return "bundled_remote"
    return "not_applicable"


def configuration_coverage(
    matrix: pd.DataFrame,
    dataset_specs: dict[str, dict[str, Any]],
    pair_frame: pd.DataFrame,
) -> pd.DataFrame:
    planned_pair_status = {
        str(row["pair_id"]): bool(row["planned_counterfactual_pair"])
        for row in pair_frame.to_dict(orient="records")
    }
    records: list[dict[str, Any]] = []
    for condition_id, group in matrix.groupby("condition_id", sort=True):
        axis = _single_text(group, "pressure_axis")
        role = _single_text(group, "intervention_role")
        pair_id = _single_text(group, "pair_id")
        pair_key = _single_text(group, "pressure_pair_key")
        dataset_id = _single_text(group, "dataset_profile_id")
        dataset = dataset_specs.get(dataset_id, {})
        negative_control = role == "negative_control"
        calibration = role == "calibration"
        identity_columns = ("condition_id", "pair_id", "batch_id")
        identity_valid = all(
            _single_text(group, column) and group[column].dropna().astype(str).nunique() == 1
            for column in identity_columns
        )
        template_id = _single_text(group, "template_id")
        param_json = _single_text(group, "param_json")
        sql_shape_id = (
            "sql-" + hashlib.sha256(f"{template_id}::{param_json}".encode()).hexdigest()[:16]
        )
        records.append(
            {
                "condition_id": condition_id,
                "batch_id": _single_text(group, "batch_id"),
                "pressure_axis": axis,
                "expected_pressure_axes": ("" if negative_control else axis),
                "expected_pressure_count": 0 if negative_control else 1,
                "intervention_role": role,
                "variant": _single_text(group, "variant"),
                "pressure_level": _single_text(group, "pressure_level"),
                "pair_id": pair_id,
                "pressure_pair_key": pair_key,
                "physical_strategy_id": _single_text(
                    group,
                    "physical_strategy_id",
                ),
                "coordinator_pressure_kind": _single_text(
                    group,
                    "coordinator_pressure_kind",
                ),
                "coordinator_shape_id": _single_text(
                    group,
                    "coordinator_shape_id",
                ),
                "scenario_level": _single_text(group, "scenario_level"),
                "join_shape_id": _single_text(group, "join_shape_id"),
                "planned_counterfactual_pair": planned_pair_status.get(
                    pair_id,
                    False,
                ),
                "result_equivalence_status": "pending_execution",
                "is_negative_control": negative_control,
                "is_calibration": calibration,
                "network_subblock": _network_subblock(pair_key, axis),
                "template_id": template_id,
                "logical_question_id": _single_text(
                    group,
                    "logical_question_id",
                ),
                "sql_shape_id": sql_shape_id,
                "param_json": param_json,
                "dataset_profile_id": dataset_id,
                "dataset_size_class": str(dataset.get("size_class", "")),
                "dataset_skew_level": str(dataset.get("skew_level", "")),
                "regional_distribution": str(dataset.get("regional_distribution", "")),
                "runtime_config_id": _single_text(
                    group,
                    "runtime_config_id",
                ),
                "topology_id": _single_text(group, "topology_id"),
                "execution_strategy": _single_text(
                    group,
                    "execution_strategy",
                ),
                "physical_execution_count": int(len(group)),
                "repetition_count": int(group["repetition_index"].nunique()),
                "stable_identity_valid": identity_valid,
                "sentinel_flag": _single_text(group, "sentinel_flag"),
            }
        )
    return pd.DataFrame(records)


def _prepared_batch_audit(
    prepared_batches: list[dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for batch in prepared_batches:
        source_path = resolve(WORKSPACE_ROOT, str(batch["source"]))
        source = load_yaml(source_path)
        repetitions = int(source.get("repetitions", 1))
        executions = int(source.get("planned_execution_count", 0))
        configurations = executions // repetitions if repetitions else 0
        item: dict[str, Any] = {
            "status": str(source.get("status", batch.get("status", ""))),
            "planned_execution_count": executions,
            "planned_configuration_count": configurations,
            "repetitions": repetitions,
            "source": workspace_relative(source_path),
        }
        if batch["kind"] == "combined_holdout":
            shapes = int(source["sql_shapes_per_base_case_group"])
            cardinalities: dict[str, int] = {}
            fully_mitigated_base_cases = 0
            computed_configurations = 0
            for block in source["base_case_groups"]:
                active = set(block["active_pressures"])
                mitigations = set(block["mitigation_axes"])
                pressure_count = len(active)
                key = str(pressure_count)
                cardinalities[key] = cardinalities.get(key, 0) + shapes
                computed_configurations += shapes * (1 + len(mitigations))
                if mitigations == active:
                    fully_mitigated_base_cases += shapes
            item.update(
                {
                    "base_case_group_count": len(source["base_case_groups"]),
                    "base_case_count_by_expected_pressure_count": (cardinalities),
                    "base_case_count": sum(cardinalities.values()),
                    "fully_one_at_a_time_mitigated_base_case_count": (fully_mitigated_base_cases),
                    "computed_configuration_count": computed_configurations,
                    "one_target_axis_changes_per_pair": bool(
                        source["pair_policy"]["one_target_axis_changes_per_pair"]
                    ),
                }
            )
        elif batch["kind"] == "sentinel":
            item["sentinel_axis_count"] = len(source["sentinels"])
            item["distributed_schedule_required"] = True
        elif batch["kind"] == "topology_holdout":
            item["required_region_count"] = int(source["required_topology"]["region_count"])
            worker_counts = (
                source["required_topology"].get("worker_count_by_region") or {}
            )
            item["required_worker_count_by_region"] = {
                str(region_id): int(worker_count)
                for region_id, worker_count in worker_counts.items()
            }
            item["minimum_worker_count_per_region"] = int(
                source["required_topology"].get(
                    "minimum_worker_count_per_region",
                    1,
                )
            )
        result[str(batch["batch_id"])] = item
    return result


def manifest_coverage_audit(
    *,
    matrix: pd.DataFrame,
    configurations: pd.DataFrame,
    pair_frame: pd.DataFrame,
    prepared_batches: list[dict[str, Any]],
    program: dict[str, Any],
) -> dict[str, Any]:
    gate = program["coverage_gate"]
    errors: list[str] = []
    warnings: list[str] = []
    expected_configurations = int(gate["expected_isolated_configuration_count"])
    expected_executions = int(gate["expected_isolated_execution_count"])
    expected_repetitions = int(gate["expected_repetitions_per_configuration"])
    expected_pairs = int(gate["expected_planned_pair_count"])

    if len(configurations) != expected_configurations:
        errors.append(
            f"isolated configuration count={len(configurations)}, "
            f"expected {expected_configurations}"
        )
    if len(matrix) != expected_executions:
        errors.append(f"isolated execution count={len(matrix)}, expected {expected_executions}")
    if not configurations["repetition_count"].eq(expected_repetitions).all():
        errors.append("not every isolated configuration has N=3 repetitions")
    if not configurations["stable_identity_valid"].all():
        errors.append("one or more additive identities are invalid")

    physical_condition_key = [
        "execution_strategy",
        "dataset_profile_id",
        "runtime_config_id",
        "topology_id",
        "template_id",
        "param_json",
    ]
    physical_condition_groups = (
        configurations.groupby(physical_condition_key, dropna=False)
        .agg(
            condition_count=("condition_id", "nunique"),
            batch_count=("batch_id", "nunique"),
            batches=("batch_id", lambda values: ",".join(sorted(set(values)))),
        )
        .reset_index()
    )
    cross_batch_duplicates = physical_condition_groups[
        physical_condition_groups["condition_count"].gt(1)
        & physical_condition_groups["batch_count"].gt(1)
    ]
    if not cross_batch_duplicates.empty:
        errors.append(
            "one or more exact SQL/dataset/runtime conditions are duplicated "
            "across isolated batches"
        )

    planned_pairs = pair_frame["planned_counterfactual_pair"].eq(True)
    if int(planned_pairs.sum()) != expected_pairs:
        errors.append(
            f"planned counterfactual pair count={int(planned_pairs.sum())}, "
            f"expected {expected_pairs}"
        )
    for axis, group in configurations.groupby("pressure_axis"):
        if not group["is_negative_control"].any():
            errors.append(f"{axis} has no negative control")

    network_blocks: dict[str, Any] = {}
    for block in gate["required_network_calibration_blocks"]:
        subset = configurations[configurations["network_subblock"].eq(str(block))]
        network_blocks[str(block)] = {
            "configuration_count": int(len(subset)),
            "pair_count": int(subset["pair_id"].nunique()),
            "sql_shape_count": int(subset["sql_shape_id"].nunique()),
            "dataset_count": int(subset["dataset_profile_id"].nunique()),
        }
        if subset.empty:
            errors.append(f"missing network calibration block: {block}")
        elif subset["sql_shape_id"].nunique() < int(gate["minimum_network_calibration_sql_shapes"]):
            errors.append(
                f"{block} calibration has "
                f"{subset['sql_shape_id'].nunique()} SQL shapes, expected at "
                f"least {gate['minimum_network_calibration_sql_shapes']}"
            )
        if subset["dataset_profile_id"].nunique() < int(
            gate["minimum_network_calibration_datasets"]
        ):
            errors.append(
                f"{block} calibration has "
                f"{subset['dataset_profile_id'].nunique()} datasets, expected "
                f"at least {gate['minimum_network_calibration_datasets']}"
            )

    by_axis: dict[str, Any] = {}
    for axis, group in configurations.groupby("pressure_axis", sort=True):
        axis_pairs = pair_frame[
            pair_frame["pressure_axis"].astype(str).eq(str(axis))
            & pair_frame["planned_counterfactual_pair"].eq(True)
        ]
        by_axis[str(axis)] = {
            "configuration_count": int(len(group)),
            "physical_execution_count": int(group["physical_execution_count"].sum()),
            "planned_counterfactual_pair_count": int(len(axis_pairs)),
            "negative_control_configuration_count": int(group["is_negative_control"].sum()),
            "calibration_configuration_count": int(group["is_calibration"].sum()),
            "template_count": int(group["template_id"].nunique()),
            "sql_shape_count": int(group["sql_shape_id"].nunique()),
            "dataset_count": int(group["dataset_profile_id"].nunique()),
            "datasets": sorted(group["dataset_profile_id"].unique()),
            "templates": sorted(group["template_id"].unique()),
            "configurations_by_variant": {
                str(key): int(value) for key, value in group.groupby("variant").size().items()
            },
        }
        expected_axis_pairs = int(gate["planned_pairs_by_axis"][str(axis)])
        if len(axis_pairs) != expected_axis_pairs:
            errors.append(
                f"{axis} planned pair count={len(axis_pairs)}, expected {expected_axis_pairs}"
            )
        controls = int(group["is_negative_control"].sum())
        minimum_controls = int(gate["minimum_negative_control_configurations_by_axis"])
        if controls < minimum_controls:
            errors.append(
                f"{axis} has {controls} negative-control configurations, "
                f"expected at least {minimum_controls}"
            )

    prepared = _prepared_batch_audit(prepared_batches)
    combined = prepared.get("batch-200-combined-holdout", {})
    if combined.get("planned_configuration_count", 0) <= 0:
        errors.append("combined holdout has no prepared configurations")
    if int(combined.get("base_case_count", 0)) < int(gate["minimum_combined_base_cases"]):
        errors.append("combined holdout has too few base cases")
    if int(
        combined.get(
            "fully_one_at_a_time_mitigated_base_case_count",
            0,
        )
    ) < int(gate["minimum_fully_one_at_a_time_mitigated_base_cases"]):
        errors.append("combined holdout has too few fully mitigated base cases")
    if int(combined.get("computed_configuration_count", -1)) != int(
        combined.get("planned_configuration_count", -2)
    ):
        errors.append("combined holdout computed configuration count does not match plan")

    return {
        "status": "ok" if not errors else "failed",
        "scope_note": (
            f"The {len(configurations)} configurations are rendered isolated "
            "conditions. Combined holdout, sentinels and N=3 remain "
            "separately prepared."
        ),
        "isolated": {
            "configuration_count": int(len(configurations)),
            "physical_execution_count": int(len(matrix)),
            "repetitions_per_configuration": expected_repetitions,
            "expected_pressure_count_distribution": {
                str(key): int(value)
                for key, value in configurations.groupby("expected_pressure_count").size().items()
            },
            "by_axis": by_axis,
            "distinct_sql_shape_count": int(configurations["sql_shape_id"].nunique()),
            "distinct_dataset_count": int(configurations["dataset_profile_id"].nunique()),
            "planned_counterfactual_pair_count": int(planned_pairs.sum()),
            "result_equivalence_status": ("pending_execution_and_result_signature_validation"),
            "combined_configuration_count": 0,
        },
        "network_calibration_blocks": network_blocks,
        "prepared_not_yet_materialized": prepared,
        "identity": {
            "condition_id_unique_count": int(configurations["condition_id"].nunique()),
            "pair_id_count": int(configurations["pair_id"].nunique()),
            "batch_id_count": int(configurations["batch_id"].nunique()),
            "execution_slot_id_unique_count": int(matrix["execution_slot_id"].nunique()),
            "all_stable_identity_checks_pass": bool(configurations["stable_identity_valid"].all()),
        },
        "execution_deduplication": {
            "physical_condition_key": physical_condition_key,
            "cross_batch_exact_duplicate_count": int(len(cross_batch_duplicates)),
            "status": "ok" if cross_batch_duplicates.empty else "failed",
            "repetitions_are_intentional": True,
            "placement_state_pairs_are_intentional": True,
        },
        "manual_execution_protocol": program["manual_execution_protocol"],
        "errors": errors,
        "warnings": warnings,
    }


def _params_match(raw: Any, selector: dict[str, Any]) -> bool:
    try:
        params = json.loads(str(raw))
    except json.JSONDecodeError:
        return False
    return all(str(params.get(key)) == str(value) for key, value in selector.items())


def materialize_smoke_batch(
    *,
    smoke_path: Path,
    matrix: pd.DataFrame,
    batch_manifests: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    config = load_yaml(smoke_path)
    smoke_dir = output_dir / "batches" / str(config["batch_id"])
    if smoke_dir.exists():
        shutil.rmtree(smoke_dir)
    source_batches = {str(item["batch_id"]): item for item in batch_manifests}
    segments: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    for axis, selector in config["pair_selection"].items():
        source_batch_id = str(selector["source_batch"])
        selected = matrix[
            matrix["batch_id"].astype(str).eq(source_batch_id)
            & matrix["pressure_axis"].astype(str).eq(str(axis))
            & matrix["dataset_profile_id"].astype(str).eq(str(selector["dataset_profile_id"]))
            & matrix["variant"].astype(str).isin([str(value) for value in selector["variants"]])
        ].copy()
        if selector.get("pressure_pair_key"):
            selected = selected[
                selected["pressure_pair_key"].astype(str).eq(str(selector["pressure_pair_key"]))
            ]
        if selector.get("query_condition_id"):
            selected = selected[
                selected["query_condition_id"].astype(str).eq(str(selector["query_condition_id"]))
            ]
        parameter_selector = selector.get("parameter_selector") or {}
        if parameter_selector:
            selected = selected[
                selected["param_json"].map(
                    lambda value, expected=parameter_selector: _params_match(
                        value,
                        expected,
                    )
                )
            ]
        expected = int(config["repetitions"]) * len(selector["variants"])
        if len(selected) != expected:
            raise ValueError(
                f"Smoke selector {axis} resolved {len(selected)} rows, expected {expected}"
            )
        selected_rows.extend(selected.to_dict(orient="records"))
        source_batch = source_batches[source_batch_id]
        if str(source_batch["backend"]) == "placement_aware_worker":
            source_segment = next(
                item
                for item in source_batch["segments"]
                if str(item["dataset_profile_id"]) == str(selector["dataset_profile_id"])
            )
            source_config = load_yaml(resolve(WORKSPACE_ROOT, str(source_segment["config"])))
            source_config["analysis_id"] = f"{config['batch_id']}-{axis}"
            source_config["capability_smoke"] = {
                "condition_ids": [str(selector["query_condition_id"])],
                "repetition_indices": list(range(int(config["repetitions"]))),
                "require_checkpoint": False,
            }
            config_path = smoke_dir / str(axis) / "config.yml"
            write_yaml(config_path, source_config)
            segments.append(
                {
                    "segment_id": f"{config['batch_id']}-{axis}",
                    "pressure_axis": axis,
                    "backend": "placement_aware_worker",
                    "status": "ready",
                    "config": workspace_relative(config_path),
                    "plan": source_segment["plan"],
                    "execution_count": expected,
                }
            )
            continue

        source_plan_path = resolve(
            WORKSPACE_ROOT,
            str(source_batch["rendered_plan"]),
        )
        source_plan = load_yaml(source_plan_path)
        smoke_groups: list[dict[str, Any]] = []
        axis_dir = smoke_dir / str(axis)
        for group_id, group_rows in selected.groupby("group_id", sort=True):
            source_group = next(
                item for item in source_plan["groups"] if str(item["group_id"]) == str(group_id)
            )
            selection_path = axis_dir / f"{group_id}.instance_manifest.csv"
            write_csv(selection_path, group_rows.to_dict(orient="records"))
            source_sweep_path = resolve(
                WORKSPACE_ROOT,
                str(source_group["sweep_config"]),
            )
            sweep = load_yaml(source_sweep_path)
            sweep["sweep_id"] = f"{config['batch_id']}__{axis}__{group_id}"
            sweep["workload"]["instance_manifest"] = workspace_relative(selection_path)
            sweep_path = axis_dir / f"{group_id}.sweep.yml"
            write_yaml(sweep_path, sweep)
            smoke_groups.append(
                {
                    **source_group,
                    "group_id": f"{config['batch_id']}__{axis}__{group_id}",
                    "sweep_id": sweep["sweep_id"],
                    "instance_count": int(len(group_rows)),
                    "instance_manifest": workspace_relative(selection_path),
                    "sweep_config": workspace_relative(sweep_path),
                }
            )
        plan = {
            "corpus_id": f"{config['batch_id']}-{axis}",
            "source_manifest": workspace_relative(smoke_path),
            "corpus_version": config["corpus_version"],
            "collection_contract_version": config["collection_contract_version"],
            "execution_backend": "master-regimes-infra.database_sweep",
            "group_count": len(smoke_groups),
            "groups": smoke_groups,
        }
        plan_path = axis_dir / "corpus_execution_plan.yml"
        write_yaml(plan_path, plan)
        segments.append(
            {
                "segment_id": f"{config['batch_id']}-{axis}",
                "pressure_axis": axis,
                "backend": "standard_corpus",
                "status": "ready",
                "plan": workspace_relative(plan_path),
                "execution_count": expected,
            }
        )
    selected_frame = pd.DataFrame(selected_rows)
    selected_frame.to_csv(smoke_dir / "execution_matrix.csv", index=False)
    manifest = {
        "batch_id": config["batch_id"],
        "kind": "collection_smoke",
        "status": "ready",
        "source": workspace_relative(smoke_path),
        "source_sha256": sha256_file(smoke_path),
        "execution_count": int(len(selected_frame)),
        "segments": segments,
        "gate": config["gate"],
    }
    manifest_path = smoke_dir / "batch_manifest.yml"
    write_yaml(manifest_path, manifest)
    manifest["batch_manifest"] = workspace_relative(manifest_path)
    return manifest


def build_program(program_path: Path, output_dir: Path) -> dict[str, Path]:
    program_path = program_path.resolve()
    program = load_yaml(program_path)
    contract_path = resolve(
        program_path.parent,
        str(program["collection_contract"]),
    )
    dataset_sweep_path = resolve(
        program_path.parent,
        str(program["dataset_sweep"]),
    )
    dataset_specs = dataset_profile_map(dataset_sweep_path)
    for spec in dataset_specs.values():
        if not spec["profile_path"].exists():
            raise FileNotFoundError(spec["profile_path"])

    batch_manifests: list[dict[str, Any]] = []
    matrix_rows: list[dict[str, Any]] = []
    prepared_batches: list[dict[str, Any]] = []
    for batch in program["batches"]:
        source_path = resolve(program_path.parent, str(batch["source"]))
        if batch.get("backend") == "standard_corpus":
            manifest, rows = standard_batch(
                batch=batch,
                source_path=source_path,
                dataset_specs=dataset_specs,
                output_root=output_dir,
            )
            batch_manifests.append(manifest)
            matrix_rows.extend(rows)
        elif batch.get("backend") == "placement_aware_worker":
            manifest, rows = skew_batch(
                batch=batch,
                source_path=source_path,
                dataset_specs=dataset_specs,
                output_root=output_dir,
            )
            batch_manifests.append(manifest)
            matrix_rows.extend(rows)
        elif batch.get("kind") == "smoke":
            continue
        else:
            prepared_item = {
                **batch,
                "source": workspace_relative(source_path),
                "source_sha256": sha256_file(source_path),
            }
            if batch.get("kind") == "topology_holdout":
                source = load_yaml(source_path)
                required_topology = source.get("required_topology") or {}
                repetitions = int(source.get("repetitions", 1))
                planned_execution_count = int(
                    source.get("planned_execution_count", 0)
                )
                prepared_item.update(
                    {
                        "planned_execution_count": planned_execution_count,
                        "planned_configuration_count": (
                            planned_execution_count // repetitions
                            if repetitions
                            else 0
                        ),
                        "repetitions": repetitions,
                        "design": source.get("design") or {},
                        "required_region_count": int(
                            required_topology.get("region_count", 0)
                        ),
                        "required_worker_count_by_region": {
                            str(region_id): int(worker_count)
                            for region_id, worker_count in (
                                required_topology.get(
                                    "worker_count_by_region"
                                )
                                or {}
                            ).items()
                        },
                        "minimum_worker_count_per_region": int(
                            required_topology.get(
                                "minimum_worker_count_per_region",
                                1,
                            )
                        ),
                    }
                )
            prepared_batches.append(prepared_item)

    matrix = pd.DataFrame(matrix_rows)
    matrix_path = output_dir / "execution_matrix.csv"
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    matrix.to_csv(matrix_path, index=False)
    pair_frame, _ = pair_coverage(matrix)
    pair_path = output_dir / "pair_coverage.csv"
    pair_frame.to_csv(pair_path, index=False)
    configuration_frame = configuration_coverage(
        matrix,
        dataset_specs,
        pair_frame,
    )
    configuration_path = output_dir / "configuration_coverage.csv"
    configuration_frame.to_csv(configuration_path, index=False)

    smoke_batch = next(
        batch
        for batch in program["batches"]
        if str(batch["batch_id"]) == "batch-000-collection-smoke"
    )
    smoke_path = resolve(program_path.parent, str(smoke_batch["source"]))
    smoke_manifest = materialize_smoke_batch(
        smoke_path=smoke_path,
        matrix=matrix,
        batch_manifests=batch_manifests,
        output_dir=output_dir,
    )

    summary = coverage_summary(matrix)
    summary["prepared_batch_count"] = len(prepared_batches)
    summary["rendered_batch_count"] = len(batch_manifests)
    summary["collection_contract_sha256"] = sha256_file(contract_path)
    summary["dataset_sweep_sha256"] = sha256_file(dataset_sweep_path)
    summary["original_plan_reference"] = {
        "isolated": 624,
        "combined_holdout": 240,
        "sentinels": 36,
        "n3_holdout": 72,
        "total": 972,
    }
    summary["revised_plan"] = {
        "rendered_isolated": int(len(matrix)),
        "collection_smoke": 30,
        "prepared_combined_holdout": 180,
        "prepared_sentinels": 30,
        "blocked_n3_holdout": 96,
        "total_if_all_prepared_batches_are_later_materialized": (
            int(len(matrix)) + 30 + 180 + 30 + 96
        ),
    }
    result_signature_scope = str(
        program["execution_policy"].get(
            "result_signature_scope",
            "every_execution",
        )
    )
    result_signature_query_count = (
        len(configuration_frame)
        if result_signature_scope == "first_repetition_per_condition"
        else len(matrix)
    )
    summary["execution_optimization"] = {
        "instrumented_execution_count": int(len(matrix)),
        "stream_only_result_signature_query_count": int(
            result_signature_query_count
        ),
        "result_signature_scope": result_signature_scope,
        "avoided_redundant_signature_queries": int(
            len(matrix) - result_signature_query_count
        ),
        "query_level_concurrency": 1,
    }
    summary["progress_plan"] = {
        "slot_count": int(len(matrix)),
        "planned_work_units": float(
            matrix["planned_work_units"].astype(float).sum()
        ),
        "dataset_weights": DATASET_PROGRESS_WEIGHTS,
        "runtime_multipliers": RUNTIME_PROGRESS_MULTIPLIERS,
        "cost_class_counts": {
            str(key): int(value)
            for key, value in matrix["progress_cost_class"]
            .value_counts()
            .sort_index()
            .items()
        },
        "dataset_size_counts": {
            str(key): int(value)
            for key, value in matrix["dataset_size_class"]
            .value_counts()
            .sort_index()
            .items()
        },
        "eta_policy": {
            "initial_estimate": "planned_work_units",
            "dynamic_rate": "median_elapsed_seconds_per_work_unit",
            "low_confidence_sample_count_lt": 5,
            "high_confidence_sample_count_gte": 20,
            "blocked_batches_excluded_from_eta": True,
        },
    }
    summary_path = output_dir / "program_summary.json"
    write_json(summary_path, summary)

    coverage_audit = manifest_coverage_audit(
        matrix=matrix,
        configurations=configuration_frame,
        pair_frame=pair_frame,
        prepared_batches=prepared_batches,
        program=program,
    )
    coverage_audit_path = output_dir / "manifest_coverage_audit.json"
    write_json(coverage_audit_path, coverage_audit)

    program_manifest = {
        "program_id": program["program_id"],
        "corpus_version": program["corpus_version"],
        "collection_contract_version": program["collection_contract_version"],
        "source_program": workspace_relative(program_path),
        "source_program_sha256": sha256_file(program_path),
        "collection_contract": workspace_relative(contract_path),
        "collection_contract_sha256": sha256_file(contract_path),
        "dataset_sweep": workspace_relative(dataset_sweep_path),
        "dataset_sweep_sha256": sha256_file(dataset_sweep_path),
        "execution_matrix": workspace_relative(matrix_path),
        "pair_coverage": workspace_relative(pair_path),
        "configuration_coverage": workspace_relative(configuration_path),
        "manifest_coverage_audit": workspace_relative(coverage_audit_path),
        "program_summary": workspace_relative(summary_path),
        "execution_policy": program["execution_policy"],
        "consolidation_policy": program["consolidation_policy"],
        "progress_plan": summary["progress_plan"],
        "execution_topology_policy": program["execution_topology_policy"],
        "manual_execution_protocol": program["manual_execution_protocol"],
        "coverage_gate": program["coverage_gate"],
        "rendered_batches": batch_manifests,
        "smoke_batch": smoke_manifest,
        "prepared_batches": prepared_batches,
    }
    program_manifest_path = output_dir / "pressure_raw_program.yml"
    write_yaml(program_manifest_path, program_manifest)

    checksums: list[dict[str, str]] = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name not in {
            "checksums.sha256",
            "collection_validation_report.json",
        }:
            checksums.append(
                {
                    "sha256": sha256_file(path),
                    "path": str(path.relative_to(output_dir)),
                }
            )
    checksums_path = output_dir / "checksums.sha256"
    checksums_path.write_text(
        "".join(f"{row['sha256']}  {row['path']}\n" for row in checksums),
        encoding="utf-8",
    )
    return {
        "program": program_manifest_path,
        "matrix": matrix_path,
        "pairs": pair_path,
        "configurations": configuration_path,
        "coverage_audit": coverage_audit_path,
        "summary": summary_path,
        "checksums": checksums_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    outputs = build_program(args.program.resolve(), args.out_dir.resolve())
    for key, path in outputs.items():
        print(f"{key}={path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
