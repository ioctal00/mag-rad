from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from master_regimes.confirmatory_skew import build_confirmatory_skew_plan
from master_regimes.corpus_adapter import render_corpus
from master_regimes.corpus_manifest import validate_corpus_manifest

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_CONFIG = REPO_ROOT / "configs/validation/pressure_intervention_program_v1.yml"
DEFAULT_OUTPUT = REPO_ROOT / "generated/corpus/pressure-intervention-v1"


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


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


def relative_to(path: Path, base: Path) -> str:
    return os.path.relpath(path.resolve(), base.resolve())


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


def runtime(
    *,
    axis: str,
    description: str,
    pg_options: dict[str, Any] | None = None,
    regional_pg_options: dict[str, Any] | None = None,
    psql_variables: dict[str, Any] | None = None,
    fdw_server_options: dict[str, Any] | None = None,
    network_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "description": description,
        "enabled": True,
        "intervention_axis": axis,
        "pg_options": pg_options or {},
        "regional_pg_options": regional_pg_options or {},
        "psql_variables": psql_variables or {},
        "fdw_server_options": fdw_server_options or {},
        "network_profile": network_profile or {},
        "applies_when": {},
        "negative_control_when": {},
        "expected_effect": description,
    }


def remote_options(
    *,
    profile_id: str,
    fetch_size: int,
    delay_ms: int,
    bandwidth_mbit: int,
) -> dict[str, Any]:
    return {
        "psql_variables": {"FETCH_COUNT": str(fetch_size)},
        "fdw_server_options": {"fetch_size": str(fetch_size)},
        "network_profile": {
            "id": profile_id,
            "enabled": True,
            "scope": "region_egress_to_analytics",
            "target_region_ids": ["eu", "us"],
            "configured_delay_ms": delay_ms,
            "configured_jitter_ms": 0,
            "configured_loss_percent": 0,
            "configured_bandwidth_mbit": bandwidth_mbit,
        },
    }


def standard_runtime_configs() -> dict[str, dict[str, Any]]:
    configs: dict[str, dict[str, Any]] = {
        "default": runtime(
            axis="none",
            description="No targeted runtime intervention.",
        )
    }
    for axis, prefix, option_field in (
        ("gac_finalization", "gac", "pg_options"),
        ("regional_finalization", "regional", "regional_pg_options"),
    ):
        for level, work_mem in (
            ("mitigated", "256MB"),
            ("intermediate", "4MB"),
            ("stressed", "64kB"),
        ):
            options = {option_field: {"work_mem": work_mem}}
            if axis == "regional_finalization":
                options["pg_options"] = {"work_mem": work_mem}
            configs[f"pressure_{prefix}_{level}"] = runtime(
                axis=axis,
                description=f"{axis} {level}: work_mem={work_mem}.",
                **options,
            )

    remote_levels = {
        "mitigated": (10000, 0, 0),
        "intermediate": (2000, 10, 50),
        "stressed": (1000, 20, 20),
    }
    for level, (fetch_size, delay_ms, bandwidth_mbit) in remote_levels.items():
        configs[f"pressure_remote_{level}"] = runtime(
            axis="remote_path",
            description=(
                f"remote_path {level}: fetch={fetch_size}, delay={delay_ms}ms, "
                f"bandwidth={bandwidth_mbit or 'unlimited'}Mbit."
            ),
            **remote_options(
                profile_id=f"pressure_remote_{level}",
                fetch_size=fetch_size,
                delay_ms=delay_ms,
                bandwidth_mbit=bandwidth_mbit,
            ),
        )

    def combined(
        config_id: str,
        *,
        gac_mem: str | None = None,
        regional_mem: str | None = None,
        remote_level: str | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {}
        if gac_mem:
            kwargs["pg_options"] = {"work_mem": gac_mem}
        if regional_mem:
            kwargs["regional_pg_options"] = {"work_mem": regional_mem}
            kwargs.setdefault("pg_options", {"work_mem": regional_mem})
        if remote_level:
            fetch_size, delay_ms, bandwidth_mbit = remote_levels[remote_level]
            kwargs.update(
                remote_options(
                    profile_id=config_id,
                    fetch_size=fetch_size,
                    delay_ms=delay_ms,
                    bandwidth_mbit=bandwidth_mbit,
                )
            )
        configs[config_id] = runtime(
            axis="combined_pressure",
            description=f"Combined holdout runtime {config_id}.",
            **kwargs,
        )

    for secondary in ("intermediate", "stressed"):
        combined(
            f"combo_gac_under_remote_{secondary}_mitigated",
            gac_mem="256MB",
            remote_level=secondary,
        )
        combined(
            f"combo_gac_under_remote_{secondary}_stressed",
            gac_mem="64kB",
            remote_level=secondary,
        )
    for gac_level, gac_mem in (("intermediate", "4MB"), ("stressed", "64kB")):
        combined(
            f"combo_remote_under_gac_{gac_level}_mitigated",
            gac_mem=gac_mem,
            remote_level="mitigated",
        )
        combined(
            f"combo_remote_under_gac_{gac_level}_stressed",
            gac_mem=gac_mem,
            remote_level="stressed",
        )
    combined(
        "combo_regional_under_repartition_mitigated",
        regional_mem="256MB",
    )
    combined(
        "combo_regional_under_repartition_stressed",
        regional_mem="64kB",
    )
    combined(
        "combo_repartition_under_regional_stressed",
        regional_mem="64kB",
    )
    return configs


def cell(
    *,
    cell_id: str,
    shape: dict[str, Any],
    dataset: str,
    runtime_config_id: str,
    axis: str,
    level: str,
    pair_key: str,
    dataset_role: str,
    parameters: dict[str, Any] | None = None,
    template_id: str | None = None,
    sentinel: bool = False,
) -> dict[str, Any]:
    return {
        "corpus_cell_id": cell_id,
        "logical_question_id": shape["logical_question_id"],
        "execution_strategy": shape["execution_strategy"],
        "template_id": template_id or shape["template_id"],
        "dataset_profile_id": dataset,
        "runtime_config_id": runtime_config_id,
        "topology_id": "eu_us_gac",
        "intervention_role": "calibration" if sentinel else "final_check",
        "intervention_axis": (
            axis if not runtime_config_id.startswith("combo_") else "combined_pressure"
        ),
        "pressure_axis": axis,
        "pressure_level": level,
        "pressure_pair_key": pair_key,
        "mitigation_action": f"mitigate_{axis}",
        "target_metric": "execution_time_seconds",
        "dataset_role": dataset_role,
        "expected_regime_targets": [],
        "execution_class": "pilot",
        "sentinel_flag": sentinel,
        "parameters": parameters or shape["parameters"],
    }


def build_standard_cells(config: dict[str, Any]) -> list[dict[str, Any]]:
    shapes = config["shape_grids"]
    datasets = config["design"]["datasets"]
    cells: list[dict[str, Any]] = []
    runtime_prefix = {
        "gac_finalization": "gac",
        "remote_path": "remote",
        "regional_finalization": "regional",
    }
    for axis in ("gac_finalization", "remote_path", "regional_finalization"):
        for dataset in datasets:
            for level in ("mitigated", "intermediate", "stressed"):
                cells.append(
                    cell(
                        cell_id=f"isolated_{axis}_{dataset}_{level}",
                        shape=shapes[axis],
                        dataset=dataset,
                        runtime_config_id=(
                            f"pressure_{runtime_prefix[axis]}_{level}"
                        ),
                        axis=axis,
                        level=level,
                        pair_key=f"isolated_{axis}_{dataset}",
                        dataset_role="pressure_isolated",
                    )
                )

    join_shape = shapes["repartition_join"]
    for dataset in datasets:
        for level, template_key in (
            ("mitigated", "mitigated_template_id"),
            ("stressed", "stressed_template_id"),
        ):
            cells.append(
                cell(
                    cell_id=f"isolated_repartition_join_{dataset}_{level}",
                    shape=join_shape,
                    dataset=dataset,
                    runtime_config_id="default",
                    axis="repartition_join",
                    level=level,
                    pair_key=f"isolated_repartition_join_{dataset}",
                    dataset_role="pressure_isolated",
                    template_id=join_shape[template_key],
                )
            )

    combo_shape = {
        **shapes["gac_finalization"],
        "parameters": {
            "lookback_days": [14, 30],
            "limit_k": [100000],
            "amplification_factor": [4, 8],
        },
    }
    for secondary in ("intermediate", "stressed"):
        block = f"gac_under_remote_{secondary}"
        for level in ("mitigated", "stressed"):
            cells.append(
                cell(
                    cell_id=f"combined_{block}_{level}",
                    shape=combo_shape,
                    dataset="pilot-balanced-v1",
                    runtime_config_id=f"combo_{block}_{level}",
                    axis="gac_finalization",
                    level=level,
                    pair_key=f"combined_{block}",
                    dataset_role="pressure_combined_holdout",
                )
            )
    for gac_level in ("intermediate", "stressed"):
        block = f"remote_under_gac_{gac_level}"
        for level in ("mitigated", "stressed"):
            cells.append(
                cell(
                    cell_id=f"combined_{block}_{level}",
                    shape=combo_shape,
                    dataset="pilot-balanced-v1",
                    runtime_config_id=f"combo_{block}_{level}",
                    axis="remote_path",
                    level=level,
                    pair_key=f"combined_{block}",
                    dataset_role="pressure_combined_holdout",
                )
            )

    combo_join_parameters = {
        "lookback_days": [7, 30],
        "limit_k": [25, 100],
    }
    for level in ("mitigated", "stressed"):
        cells.append(
            cell(
                cell_id=f"combined_regional_under_repartition_{level}",
                shape=join_shape,
                dataset="pilot-balanced-v1",
                runtime_config_id=f"combo_regional_under_repartition_{level}",
                axis="regional_finalization",
                level=level,
                pair_key="combined_regional_under_repartition",
                dataset_role="pressure_combined_holdout",
                parameters=combo_join_parameters,
                template_id=join_shape["stressed_template_id"],
            )
        )
    for level, template_key in (
        ("mitigated", "mitigated_template_id"),
        ("stressed", "stressed_template_id"),
    ):
        cells.append(
            cell(
                cell_id=f"combined_repartition_under_regional_stressed_{level}",
                shape=join_shape,
                dataset="pilot-balanced-v1",
                runtime_config_id="combo_repartition_under_regional_stressed",
                axis="repartition_join",
                level=level,
                pair_key="combined_repartition_under_regional_stressed",
                dataset_role="pressure_combined_holdout",
                parameters=combo_join_parameters,
                template_id=join_shape[template_key],
            )
        )

    sentinel_specs = (
        (
            "gac_finalization",
            shapes["gac_finalization"],
            "pressure_gac",
            {
                "lookback_days": [30],
                "limit_k": [100000, 200000],
                "amplification_factor": [8],
            },
        ),
        (
            "remote_path",
            shapes["remote_path"],
            "pressure_remote",
            {"lookback_days": [3, 30]},
        ),
        (
            "regional_finalization",
            shapes["regional_finalization"],
            "pressure_regional",
            {
                "lookback_days": [30],
                "limit_k": [50000, 100000],
                "amplification_factor": [16],
                "payload_repeat": [16],
            },
        ),
    )
    for axis, shape, runtime_base, parameters in sentinel_specs:
        for level in ("mitigated", "stressed"):
            cells.append(
                cell(
                    cell_id=f"sentinel_{axis}_{level}",
                    shape=shape,
                    dataset="pilot-balanced-v1",
                    runtime_config_id=f"{runtime_base}_{level}",
                    axis=axis,
                    level=level,
                    pair_key=f"sentinel_{axis}",
                    dataset_role="pressure_sentinel",
                    parameters=parameters,
                    sentinel=True,
                )
            )
    return cells


def build_standard_manifest(
    config: dict[str, Any],
    *,
    output_dir: Path,
) -> tuple[Path, Path]:
    source_dir = output_dir / "source/standard"
    manifest_path = source_dir / "corpus_manifest.yml"
    manifest = {
        "corpus_id": f"{config['program_id']}-standard",
        "description": "Standard backend segments of the pressure intervention corpus.",
        "query_groups": relative_to(
            REPO_ROOT / "workloads/corpus/query-groups.yml",
            manifest_path.parent,
        ),
        "dataset_profiles": {
            "pilot-balanced-v1": {
                "profile": relative_to(
                    REPO_ROOT / "datasets/profiles/pilot-balanced.yml",
                    manifest_path.parent,
                ),
                "load_method": "copy_pipe",
            },
            "pilot-skew-heavy-v1": {
                "profile": relative_to(
                    REPO_ROOT / "datasets/profiles/pilot-skew-heavy.yml",
                    manifest_path.parent,
                ),
                "load_method": "copy_pipe",
            },
        },
        "runtime_configs": standard_runtime_configs(),
        "execution_budget": {
            "hard_timeout_seconds": config["design"]["hard_timeout_seconds"],
            "timeout_grace_seconds": config["design"]["timeout_grace_seconds"],
        },
        "execution_policy": {
            "cache_policy": config["design"]["cache_policy"],
            "order_policy": config["design"]["order_policy"],
            "shuffle_seed": config["design"]["shuffle_seed"],
            "repetitions_default": config["design"]["repetitions"],
            "sentinel_repetitions": config["design"]["repetitions"],
            "record_run_order": True,
            "record_buffer_features": True,
            "fdw_auto_explain": True,
            "os_sampler": True,
        },
        "cells": build_standard_cells(config),
    }
    write_yaml(manifest_path, manifest)
    validation = validate_corpus_manifest(manifest_path)
    if validation["status"] != "ok":
        raise ValueError("; ".join(validation["errors"]))
    plan_path = render_corpus(
        manifest_path=manifest_path,
        output_dir=output_dir / "standard",
    )
    return manifest_path, plan_path


def product_rows(parameters: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = list(parameters)
    return [
        dict(zip(keys, values, strict=True))
        for values in itertools.product(*(parameters[key] for key in keys))
    ]


def worker_runtime_configs() -> dict[str, dict[str, Any]]:
    configs = standard_runtime_configs()
    return {
        "default": configs["default"],
        "worker_fixed_gac_intermediate": runtime(
            axis="combined_pressure",
            description="Worker placement contrast under intermediate GAC work_mem.",
            pg_options={"work_mem": "4MB"},
        ),
        "worker_fixed_gac_stressed": runtime(
            axis="combined_pressure",
            description="Worker placement contrast under low GAC work_mem.",
            pg_options={"work_mem": "64kB"},
        ),
        "worker_fixed_remote_intermediate": runtime(
            axis="combined_pressure",
            description="Worker placement contrast under intermediate remote stress.",
            **remote_options(
                profile_id="worker_fixed_remote_intermediate",
                fetch_size=2000,
                delay_ms=10,
                bandwidth_mbit=50,
            ),
        ),
        "worker_fixed_remote_stressed": runtime(
            axis="combined_pressure",
            description="Worker placement contrast under strong remote stress.",
            **remote_options(
                profile_id="worker_fixed_remote_stressed",
                fetch_size=1000,
                delay_ms=20,
                bandwidth_mbit=20,
            ),
        ),
    }


def worker_config(
    config: dict[str, Any],
    *,
    segment_id: str,
    runtime_config_id: str,
    parameter_rows: list[dict[str, Any]],
    source_manifest: Path,
    output_dir: Path,
) -> dict[str, Any]:
    query_conditions = []
    for index, parameters in enumerate(parameter_rows, start=1):
        query_conditions.append(
            {
                "condition_id": f"worker_shape_{index:02d}",
                "corpus_cell_id": "worker_hot_scan",
                "logical_question_id": "top_tenants",
                "physical_strategy_id": "hot_worker_cpu_probe",
                "template_id": "gac_fdw_multiregion_hot_worker_probe",
                "parameters": parameters,
            }
        )
    return {
        "analysis_id": segment_id,
        "protocol_version": config["protocol_version"],
        "source_manifest": repo_relative(source_manifest),
        "source_render_dir": repo_relative(output_dir / "source-render"),
        "output_dir": repo_relative(output_dir / "plan"),
        "selection": repo_relative(output_dir / "selection.csv"),
        "design": {
            "topology_id": "eu_us_gac",
            "runtime_config_id": runtime_config_id,
            "repetitions": config["design"]["repetitions"],
            "state_order": ["B", "C"],
            "order_policy": "deterministic_shuffle_within_state",
            "shuffle_seed": config["design"]["shuffle_seed"],
            "cache_policy": "mixed_cache_worker_skew_target",
            "warmup_per_instance": False,
            "explicit_cache_reset": False,
            "database_result_rows_stored": False,
        },
        "states": {
            "B": {
                "state_name": "skew_dispersed",
                "dataset_profile_id": "pilot-skew-heavy-v1",
                "placement_state_id": "hot_shards_dispersed",
                "logical_data_contract_id": "pilot-skew-heavy-v1-seed-42",
                "placement_action": "disperse_hot_shards",
            },
            "C": {
                "state_name": "skew_concentrated",
                "dataset_profile_id": "pilot-skew-heavy-v1",
                "placement_state_id": "hot_shards_concentrated",
                "logical_data_contract_id": "pilot-skew-heavy-v1-seed-42",
                "placement_action": "concentrate_hot_shards",
            },
        },
        "query_conditions": query_conditions,
        "capability_smoke": {
            "condition_ids": [row["condition_id"] for row in query_conditions],
            "repetition_indices": list(range(config["design"]["repetitions"])),
            "require_checkpoint": False,
        },
        "hot_tenant_contract": {
            "source_profile": "datasets/profiles/pilot-skew-heavy.yml",
            "eu_hot_tenant_ids": list(range(1, 11)),
            "us_hot_tenant_ids": list(range(10001, 10011)),
        },
        "placement": {
            "metadata_source": "citus_shards",
            "move_function": "citus_move_shard_placement",
            "shard_transfer_mode": "block_writes",
            "dispersed": {"dominant_hot_event_share_max": 0.65},
            "concentrated": {"dominant_hot_event_share_min": 0.80},
            "rollback": {
                "primary": "replay_inverse_moves_from_placement_intervention_manifest",
                "fallback": "clean_reload_same_dataset_profile_and_seed",
            },
        },
        "artifact_contract": {
            "required_query_scopes": [
                "main",
                "regional_coordinator",
                "worker_task",
            ],
            "database_result_rows_stored": False,
        },
    }


def build_worker_segment(
    config: dict[str, Any],
    *,
    output_root: Path,
    segment_id: str,
    runtime_config_id: str,
    parameter_rows: list[dict[str, Any]],
) -> tuple[Path, Path]:
    segment_dir = output_root / "worker-segments" / segment_id
    source_manifest = segment_dir / "source_manifest.yml"
    params: dict[str, list[Any]] = {
        "eu_hot_tenant_min": [1],
        "eu_hot_tenant_max": sorted(
            {int(row["eu_hot_tenant_max"]) for row in parameter_rows}
        ),
        "us_hot_tenant_min": [10001],
        "us_hot_tenant_max": sorted(
            {int(row["us_hot_tenant_max"]) for row in parameter_rows}
        ),
        "cpu_terms": sorted({int(row["cpu_terms"]) for row in parameter_rows}),
    }
    manifest = {
        "corpus_id": f"{segment_id}-source",
        "query_groups": relative_to(
            REPO_ROOT / "workloads/corpus/query-groups.yml",
            source_manifest.parent,
        ),
        "dataset_profiles": {
            "pilot-skew-heavy-v1": {
                "profile": relative_to(
                    REPO_ROOT / "datasets/profiles/pilot-skew-heavy.yml",
                    source_manifest.parent,
                ),
                "load_method": "copy_pipe",
            }
        },
        "runtime_configs": {
            runtime_config_id: worker_runtime_configs()[runtime_config_id],
            **(
                {"default": worker_runtime_configs()["default"]}
                if runtime_config_id != "default"
                else {}
            ),
        },
        "execution_budget": {
            "hard_timeout_seconds": config["design"]["hard_timeout_seconds"],
            "timeout_grace_seconds": config["design"]["timeout_grace_seconds"],
        },
        "execution_policy": {
            "cache_policy": "mixed_cache_worker_skew_target",
            "order_policy": "deterministic_shuffle",
            "shuffle_seed": config["design"]["shuffle_seed"],
            "repetitions_default": 1,
            "record_run_order": True,
            "record_buffer_features": True,
            "fdw_auto_explain": True,
            "os_sampler": True,
        },
        "cells": [
            {
                "corpus_cell_id": "worker_hot_scan",
                "logical_question_id": "top_tenants",
                "execution_strategy": "multiregion_union",
                "template_id": "gac_fdw_multiregion_hot_worker_probe",
                "dataset_profile_id": "pilot-skew-heavy-v1",
                "runtime_config_id": runtime_config_id,
                "topology_id": "eu_us_gac",
                "intervention_role": "final_check",
                "intervention_axis": (
                    "dataset_and_shard_placement"
                    if runtime_config_id == "default"
                    else "combined_pressure"
                ),
                "pressure_axis": "worker_data_skew",
                "pressure_level": "combined",
                "pressure_pair_key": segment_id,
                "mitigation_action": "disperse_hot_shards",
                "target_metric": "execution_time_seconds",
                "dataset_role": (
                    "pressure_isolated"
                    if runtime_config_id == "default"
                    else "pressure_combined_holdout"
                ),
                "parameters": params,
            }
        ],
    }
    write_yaml(source_manifest, manifest)
    config_path = segment_dir / "config.yml"
    segment_config = worker_config(
        config,
        segment_id=segment_id,
        runtime_config_id=runtime_config_id,
        parameter_rows=parameter_rows,
        source_manifest=source_manifest,
        output_dir=segment_dir,
    )
    write_yaml(config_path, segment_config)
    outputs = build_confirmatory_skew_plan(config_path=config_path)
    return config_path, outputs["plan"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_program(config_path: Path, output_dir: Path) -> dict[str, Path]:
    config = load_yaml(config_path.resolve())
    output_dir.mkdir(parents=True, exist_ok=True)
    standard_manifest, standard_plan_path = build_standard_manifest(
        config,
        output_dir=output_dir,
    )
    standard_plan = load_yaml(standard_plan_path)

    worker_grid = config["shape_grids"]["worker_data_skew"]["parameters"]
    isolated_worker_rows = [
        {
            "eu_hot_tenant_min": 1,
            "eu_hot_tenant_max": row["eu_hot_tenant_max"],
            "us_hot_tenant_min": 10001,
            "us_hot_tenant_max": row["us_hot_tenant_max"],
            "cpu_terms": row["cpu_terms"],
        }
        for row in product_rows(worker_grid)
    ]
    worker_segments: list[dict[str, Any]] = []
    worker_specs = [
        (
            "pressure-worker-isolated",
            "default",
            isolated_worker_rows,
            "pressure_isolated",
        )
    ]
    combined_worker_rows = [
        {
            "eu_hot_tenant_min": 1,
            "eu_hot_tenant_max": hot_max,
            "us_hot_tenant_min": 10001,
            "us_hot_tenant_max": 10000 + hot_max,
            "cpu_terms": cpu_terms,
        }
        for hot_max, cpu_terms in itertools.product((5, 10), (64, 128))
    ]
    for block in config["combined_holdout"]["worker_blocks"]:
        worker_specs.append(
            (
                str(block["id"]),
                str(block["secondary_runtime"]),
                combined_worker_rows,
                "pressure_combined_holdout",
            )
        )
    for segment_id, runtime_id, rows, role in worker_specs:
        worker_config_path, worker_plan_path = build_worker_segment(
            config,
            output_root=output_dir,
            segment_id=segment_id,
            runtime_config_id=runtime_id,
            parameter_rows=rows,
        )
        worker_plan = load_yaml(worker_plan_path)
        worker_segments.append(
            {
                "segment_id": segment_id,
                "backend": "placement_aware_worker",
                "dataset_role": role,
                "config": workspace_relative(worker_config_path),
                "plan": workspace_relative(worker_plan_path),
                "execution_count": int(worker_plan["execution_count"]),
                "status": "ready",
            }
        )

    segments: list[dict[str, Any]] = []
    for group in standard_plan["groups"]:
        segments.append(
            {
                "segment_id": str(group["group_id"]),
                "backend": "standard_corpus",
                "dataset_role": "mixed_standard_group",
                "plan": workspace_relative(standard_plan_path),
                "group_id": str(group["group_id"]),
                "execution_count": int(group["instance_count"]),
                "status": "ready",
            }
        )
    segments.extend(worker_segments)
    segments.append(
        {
            "segment_id": "topology-holdout-n3",
            "backend": "three_region_topology",
            "dataset_role": "pressure_topology_holdout",
            "execution_count": 96,
            "required_region_count": 3,
            "status": "blocked_until_three_region_inventory",
        }
    )

    matrix_rows: list[dict[str, Any]] = []
    group_by_manifest = {
        workspace_relative(
            WORKSPACE_ROOT / str(group["instance_manifest"])
        ): group
        for group in standard_plan["groups"]
    }
    for manifest_ref, group in group_by_manifest.items():
        for row in read_csv(WORKSPACE_ROOT / manifest_ref):
            matrix_rows.append(
                {
                    "segment_id": group["group_id"],
                    "backend": "standard_corpus",
                    "execution_slot_id": (
                        f"{row['condition_id']}::r{row['repetition_index']}"
                    ),
                    "dataset_role": row["dataset_role"],
                    "pressure_axis": row["pressure_axis"],
                    "pressure_level": row["pressure_level"],
                    "pressure_pair_key": row["pressure_pair_key"],
                    "dataset_profile_id": row["dataset_profile_id"],
                    "runtime_config_id": row["runtime_config_id"],
                    "template_id": row["template_id"],
                    "param_json": row["param_json"],
                    "repetition_index": int(row["repetition_index"]),
                    "execution_status": "planned",
                }
            )
    for segment in worker_segments:
        plan = load_yaml(WORKSPACE_ROOT / str(segment["plan"]))
        for row in pd.read_csv(
            WORKSPACE_ROOT / str(plan["design_matrix"]),
            low_memory=False,
        ).to_dict(orient="records"):
            state_id = str(row["state_id"])
            matrix_rows.append(
                {
                    "segment_id": segment["segment_id"],
                    "backend": segment["backend"],
                    "execution_slot_id": (
                        f"{segment['segment_id']}::{row['slot_id']}"
                    ),
                    "dataset_role": segment["dataset_role"],
                    "pressure_axis": "worker_data_skew",
                    "pressure_level": (
                        "mitigated" if state_id == "B" else "stressed"
                    ),
                    "pressure_pair_key": (
                        f"{segment['segment_id']}::{row['query_condition_id']}"
                    ),
                    "dataset_profile_id": row["dataset_id"],
                    "runtime_config_id": (
                        plan["groups"][0]["runtime_config_id"]
                    ),
                    "template_id": row["template_id"],
                    "param_json": row["param_json"],
                    "repetition_index": int(row["repetition_index"]),
                    "execution_status": "planned",
                }
            )
    topology_shapes = (
        (
            "segment_aggregate",
            "gac_fdw_n3_colocated_user_join",
            "gac_fdw_n3_repartition_user_join",
        ),
        (
            "user_value_topk",
            "gac_fdw_n3_colocated_user_value_topk",
            "gac_fdw_n3_repartition_user_value_topk",
        ),
        (
            "joined_row_sample",
            "gac_fdw_n3_colocated_joined_event_sample",
            "gac_fdw_n3_repartition_joined_event_sample",
        ),
        (
            "scalar_summary",
            "gac_fdw_n3_colocated_join_summary",
            "gac_fdw_n3_repartition_join_summary",
        ),
    )
    topology_datasets = (
        "n3-medium-balanced-wide-global-dim-v1",
        "n3-medium-apac-dominant-wide-global-dim-v1",
        "n3-large-balanced-wide-global-dim-v1",
        "n3-large-apac-dominant-wide-global-dim-v1",
    )
    for shape_id, mitigated_template, stressed_template in topology_shapes:
        for dataset_id in topology_datasets:
            for variant, template_id in (
                ("mitigated", mitigated_template),
                ("stressed", stressed_template),
            ):
                for repetition_index in range(3):
                    condition_id = f"n3-{shape_id}-{dataset_id}-{variant}"
                    pair_key = f"n3-colocation-{shape_id}"
                    matrix_rows.append(
                        {
                            "segment_id": "topology-holdout-n3",
                            "backend": "three_region_topology",
                            "execution_slot_id": (
                                f"{condition_id}::r{repetition_index}"
                            ),
                            "dataset_role": "pressure_topology_holdout",
                            "pressure_axis": "repartition_join",
                            "pressure_level": variant,
                            "pressure_pair_key": pair_key,
                            "dataset_profile_id": dataset_id,
                            "runtime_config_id": "gac_force_remote_join",
                            "template_id": template_id,
                            "param_json": "{}",
                            "repetition_index": repetition_index,
                            "execution_status": "blocked",
                        }
                    )

    matrix = pd.DataFrame(matrix_rows)
    expected_total = int(config["planned_blocks"]["planned_total"])
    if len(matrix) != expected_total:
        raise ValueError(
            f"Execution matrix has {len(matrix)} rows, expected {expected_total}"
        )
    matrix_path = output_dir / "execution_matrix.csv"
    matrix.to_csv(matrix_path, index=False)

    role_counts = {
        str(key): int(value)
        for key, value in matrix["dataset_role"].value_counts().items()
    }
    backend_counts = {
        str(key): int(value)
        for key, value in matrix["backend"].value_counts().items()
    }
    program_plan = {
        "program_id": config["program_id"],
        "protocol_version": config["protocol_version"],
        "source_config": workspace_relative(config_path),
        "standard_manifest": workspace_relative(standard_manifest),
        "standard_plan": workspace_relative(standard_plan_path),
        "execution_matrix": workspace_relative(matrix_path),
        "smoke_gate": config["smoke_gate"],
        "target_contract": config["target_contract"],
        "planned_execution_count": len(matrix),
        "ready_execution_count": int(
            matrix["execution_status"].eq("planned").sum()
        ),
        "blocked_execution_count": int(
            matrix["execution_status"].eq("blocked").sum()
        ),
        "counts_by_dataset_role": role_counts,
        "counts_by_backend": backend_counts,
        "segments": segments,
        "execution_policy": {
            "resume_unit": "segment",
            "successful_raw_artifacts_are_never_deleted": True,
            "database_result_rows_stored": False,
            "network_reset_in_finally": True,
            "placement_restore_in_finally": True,
            "topology_holdout_requires_explicit_enable": True,
        },
    }
    program_plan_path = output_dir / "pressure_intervention_program.yml"
    write_yaml(program_plan_path, program_plan)
    summary = {
        "planned_execution_count": len(matrix),
        "ready_execution_count": program_plan["ready_execution_count"],
        "blocked_execution_count": program_plan["blocked_execution_count"],
        "counts_by_dataset_role": role_counts,
        "counts_by_backend": backend_counts,
        "standard_group_count": len(standard_plan["groups"]),
        "worker_segment_count": len(worker_segments),
    }
    write_json(output_dir / "program_summary.json", summary)
    (output_dir / "README.md").write_text(
        "# Pressure Intervention V1\n\n"
        "This directory is generated from "
        "`configs/validation/pressure_intervention_program_v1.yml`.\n\n"
        f"- Planned executions: **{len(matrix)}**\n"
        f"- Ready on the current EU+US+GAC topology: "
        f"**{program_plan['ready_execution_count']}**\n"
        f"- Explicitly blocked N=3 topology slots: "
        f"**{program_plan['blocked_execution_count']}**\n\n"
        "The execution count is methodologically derived: "
        "repartition and shard placement are binary interventions and are not "
        "given artificial intermediate levels. Run the manual orchestrator; "
        "do not execute generated sweep files ad hoc.\n",
        encoding="utf-8",
    )
    return {
        "program_plan": program_plan_path,
        "execution_matrix": matrix_path,
        "summary": output_dir / "program_summary.json",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    outputs = build_program(args.config.resolve(), args.out_dir.resolve())
    for key, path in outputs.items():
        print(f"{key}={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
