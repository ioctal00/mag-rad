from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .config import stable_slug, write_yaml
from .corpus_adapter import (
    STRATEGY_TARGET_GROUP,
    _apply_execution_policy_to_rows,
    _write_instance_manifest,
)

SELECTION_COLUMNS = [
    "condition_id",
    "source_query_run_id",
    "source_logical_run_id",
    "source_plan_id",
    "logical_question_id",
    "execution_strategy",
    "dataset_id",
    "runtime_config_id",
    "network_profile_id",
    "target_group",
    "corpus_cell_id",
    "instance_id",
    "template_id",
    "param_json",
    "expected_shape_tags",
    "source_sql_file",
    "topology_id",
    "intervention_role",
    "intervention_axis",
    "expected_regime_targets",
    "execution_class",
    "hard_cluster",
    "max_membership",
    "top2_margin",
    "membership_entropy",
    "display_state",
    "sentinel_flag",
    "planned_repetitions",
    "selection_seed",
    "selection_score",
]


def stable_hash(seed: int | str, *parts: Any) -> str:
    payload = "\x1f".join([str(seed), *(str(part) for part in parts)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def condition_id(row: pd.Series) -> str:
    return "cond-" + stable_hash(
        "repeatability-condition-v1",
        row.get("logical_question_id", ""),
        row.get("execution_strategy", ""),
        row.get("dataset_id", ""),
        row.get("runtime_config_id", ""),
        row.get("network_profile_id", ""),
        row.get("instance_id", ""),
        row.get("param_json", ""),
    )[:20]


def display_state(row: pd.Series) -> str:
    maximum = float(row.get("max_membership", math.nan))
    margin = float(row.get("top2_margin", math.nan))
    entropy = float(row.get("membership_entropy", math.nan))
    if (
        not math.isnan(maximum)
        and maximum >= 0.50
        and margin >= 0.15
        and (math.isnan(entropy) or entropy < 1.05)
    ):
        return "clear_prototype"
    if not math.isnan(maximum) and maximum >= 0.35:
        return "mixed_boundary"
    return "weak_prototype_coverage"


def _round_robin_select(
    frame: pd.DataFrame,
    group_columns: list[str],
    count: int,
) -> list[int]:
    groups = [
        group.sort_values("selection_score").index.tolist()
        for _, group in frame.groupby(group_columns, dropna=False, sort=True)
    ]
    selected: list[int] = []
    depth = 0
    while len(selected) < count:
        progressed = False
        for group in groups:
            if depth < len(group):
                selected.append(group[depth])
                progressed = True
                if len(selected) == count:
                    break
        if not progressed:
            break
        depth += 1
    return selected


def build_selection(
    query_runs: pd.DataFrame,
    memberships: pd.DataFrame,
    *,
    condition_count: int = 96,
    sentinel_count: int = 20,
    repetitions_default: int = 3,
    sentinel_repetitions: int = 5,
    seed: int = 20260724,
) -> pd.DataFrame:
    candidates = query_runs[
        query_runs["execution_status"].astype(str).eq("completed")
    ].copy()
    candidates = candidates.drop_duplicates("query_run_id")
    candidates["source_sql_file"] = candidates["source_sql_file"].astype(str)
    candidates = candidates[
        candidates["source_sql_file"].map(lambda value: Path(value).exists())
    ].copy()
    if len(candidates) < condition_count:
        raise ValueError(
            f"Only {len(candidates)} eligible conditions for target {condition_count}"
        )

    membership = memberships[memberships["k"].astype(int).eq(4)].copy()
    membership = membership.drop_duplicates("query_run_id")
    candidates = candidates.merge(
        membership[
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
        validate="one_to_one",
    )
    candidates["target_group"] = candidates["execution_strategy"].map(
        STRATEGY_TARGET_GROUP
    )
    if candidates["target_group"].isna().any():
        unknown = sorted(
            candidates.loc[
                candidates["target_group"].isna(), "execution_strategy"
            ].unique()
        )
        raise ValueError(f"Unmapped execution strategies: {unknown}")
    candidates["selection_score"] = candidates.apply(
        lambda row: stable_hash(seed, row["query_run_id"]), axis=1
    )
    selected_indexes: list[int] = []

    def require_each(column: str) -> None:
        for _, group in candidates.groupby(column, dropna=False, sort=True):
            available = group.loc[~group.index.isin(selected_indexes)]
            if not available.empty:
                selected_indexes.append(
                    available.sort_values("selection_score").index[0]
                )

    for required_dimension in [
        "source_plan_id",
        "logical_question_id",
        "execution_strategy",
        "dataset_id",
        "runtime_config_id",
        "hard_cluster",
    ]:
        require_each(required_dimension)
    remaining = candidates.loc[~candidates.index.isin(selected_indexes)]
    selected_indexes.extend(
        _round_robin_select(
            remaining,
            [
                "logical_question_id",
                "execution_strategy",
                "dataset_id",
                "runtime_config_id",
            ],
            condition_count - len(selected_indexes),
        )
    )
    if len(selected_indexes) != condition_count:
        raise ValueError("Unable to select requested unique condition count")
    selected = candidates.loc[selected_indexes].copy()
    selected["display_state"] = selected.apply(display_state, axis=1)

    sentinel_indexes: list[int] = []

    def take(group: pd.DataFrame) -> None:
        available = group.loc[~group.index.isin(sentinel_indexes)]
        if not available.empty:
            sentinel_indexes.append(
                available.sort_values("selection_score").index[0]
            )

    for _, group in selected.groupby("hard_cluster", dropna=False, sort=True):
        take(group)
    for _, group in selected.groupby("display_state", sort=True):
        take(group)
    for _, group in selected.groupby("logical_question_id", sort=True):
        take(group)
    remaining = selected.loc[~selected.index.isin(sentinel_indexes)].sort_values(
        "selection_score"
    )
    sentinel_indexes.extend(
        remaining.head(max(0, sentinel_count - len(sentinel_indexes))).index.tolist()
    )
    sentinel_indexes = sentinel_indexes[:sentinel_count]

    selected["sentinel_flag"] = selected.index.isin(sentinel_indexes)
    selected["planned_repetitions"] = np.where(
        selected["sentinel_flag"], sentinel_repetitions, repetitions_default
    )
    selected["condition_id"] = selected.apply(condition_id, axis=1)
    selected["source_query_run_id"] = selected["query_run_id"]
    selected["selection_seed"] = seed
    result = selected.rename(columns={"dataset_profile_id": "dataset_id"})
    # query_runs already carries dataset_id; keep it when both aliases exist.
    result = selected.copy()
    result["source_query_run_id"] = result["query_run_id"]
    for column in SELECTION_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    result = result[SELECTION_COLUMNS].sort_values(
        ["dataset_id", "runtime_config_id", "target_group", "selection_score"]
    )
    if result["condition_id"].duplicated().any():
        raise ValueError("condition_id collision in repeatability selection")
    if int(result["planned_repetitions"].sum()) != (
        condition_count * repetitions_default
        + sentinel_count * (sentinel_repetitions - repetitions_default)
    ):
        raise ValueError("Unexpected repeatability execution count")
    return result.reset_index(drop=True)


def _workspace_relative(path: Path, workspace_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace_root.resolve()))
    except ValueError:
        return str(path.resolve())


def build_smoke_selection(
    selection: pd.DataFrame,
    *,
    condition_count: int = 6,
) -> pd.DataFrame:
    candidates = selection.copy()
    chosen: list[int] = []

    def take(frame: pd.DataFrame) -> None:
        available = frame.loc[~frame.index.isin(chosen)]
        if not available.empty:
            chosen.append(available.sort_values("selection_score").index[0])

    wan = candidates[
        candidates["network_profile_id"].fillna("").astype(str).eq("wan_100ms")
    ]
    multiregion_wan = wan[
        wan["execution_strategy"].astype(str).eq("multiregion_union")
    ]
    take(multiregion_wan)
    skew_or_imbalanced = candidates[
        candidates["dataset_id"]
        .astype(str)
        .str.contains("skew|imbalanced", case=False, regex=True)
    ]
    take(
        skew_or_imbalanced[
            skew_or_imbalanced["execution_strategy"]
            .astype(str)
            .eq("fdw_raw")
        ]
    )
    for strategy in ["single_region_citus", "etl_materialized"]:
        take(
            candidates[
                candidates["execution_strategy"].astype(str).eq(strategy)
            ]
        )
    take(
        candidates[
            candidates["runtime_config_id"].astype(str).eq("work_mem_low")
        ]
    )
    take(candidates[candidates["sentinel_flag"].astype(bool)])
    take(skew_or_imbalanced)
    for index in candidates.sort_values("selection_score").index:
        if len(chosen) >= condition_count:
            break
        if index not in chosen:
            chosen.append(index)

    result = candidates.loc[chosen[:condition_count]].copy()
    result["planned_repetitions"] = 1
    if len(result) != condition_count:
        raise ValueError("Unable to construct repeatability smoke selection")
    if result["execution_strategy"].nunique() != 4:
        raise ValueError("Repeatability smoke does not cover all strategies")
    if not result["network_profile_id"].fillna("").astype(str).ne("").any():
        raise ValueError("Repeatability smoke does not cover WAN intervention")
    if not result["runtime_config_id"].astype(str).eq("work_mem_low").any():
        raise ValueError("Repeatability smoke does not cover work_mem_low")
    if not result["dataset_id"].isin(skew_or_imbalanced["dataset_id"]).any():
        raise ValueError("Repeatability smoke does not cover skew/asymmetry")
    return result.sort_values("selection_score").reset_index(drop=True)


def build_dry_run_plan(
    selection: pd.DataFrame,
    *,
    source_plan_paths: dict[str, Path],
    output_dir: Path,
    analysis_config: dict[str, Any],
    workspace_root: Path,
    corpus_id: str = "repeatability-v1",
) -> Path:
    source_groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for source_plan_id, source_plan_path in source_plan_paths.items():
        source_plan = yaml.safe_load(
            source_plan_path.read_text(encoding="utf-8")
        )
        for group in source_plan["groups"]:
            key = (
                source_plan_id,
                str(group["dataset_profile_id"]),
                str(group["runtime_config_id"]),
                str(group["target_group"]),
            )
            if key in source_groups:
                raise ValueError(f"Duplicate source execution group: {key}")
            source_groups[key] = group
    execution_config = analysis_config["execution"]
    execution_policy = {
        "cache_policy": execution_config["cache_policy"],
        "order_policy": execution_config["order_policy"],
        "shuffle_seed": int(execution_config["shuffle_seed"]),
        "repetitions_default": int(analysis_config["repetitions_default"]),
        "sentinel_repetitions": int(analysis_config["sentinel_repetitions"]),
        "record_run_order": True,
        "record_buffer_features": True,
        "fdw_auto_explain": True,
        "warmup_per_instance": False,
        "explicit_cache_reset": False,
        "cache_features_in_default_model": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    selection.to_csv(output_dir / "repeatability_selection.csv", index=False)
    plan_groups: list[dict[str, Any]] = []

    group_columns = [
        "dataset_id",
        "runtime_config_id",
        "target_group",
    ]
    for keys, group in selection.groupby(group_columns, sort=True):
        dataset_id, runtime_config_id, target_group = map(str, keys)
        source_plan_ids = sorted(group["source_plan_id"].astype(str).unique())
        source_plan_id = next(
            (
                candidate
                for candidate in source_plan_ids
                if (
                    candidate,
                    dataset_id,
                    runtime_config_id,
                    target_group,
                )
                in source_groups
            ),
            "",
        )
        source = source_groups.get(
            (source_plan_id, dataset_id, runtime_config_id, target_group)
        )
        if source is None:
            raise ValueError(
                "No baseline execution group for "
                f"{source_plan_id}/{dataset_id}/{runtime_config_id}/"
                f"{target_group}"
            )
        group_id = stable_slug(
            f"{corpus_id}__{dataset_id}__{runtime_config_id}__"
            f"{target_group}"
        )
        rows: list[dict[str, str]] = []
        for _, selected in group.iterrows():
            rows.append(
                {
                    "condition_id": str(selected["condition_id"]),
                    "instance_id": str(selected["instance_id"]),
                    "template_id": str(selected["template_id"]),
                    "param_json": str(selected["param_json"]),
                    "rendered_sql_path": str(selected["source_sql_file"]),
                    "expected_shape_tags": str(selected["expected_shape_tags"]),
                    "corpus_id": corpus_id,
                    "corpus_cell_id": str(selected["corpus_cell_id"]),
                    "logical_question_id": str(
                        selected["logical_question_id"]
                    ),
                    "execution_strategy": str(
                        selected["execution_strategy"]
                    ),
                    "dataset_profile_id": dataset_id,
                    "runtime_config_id": runtime_config_id,
                    "topology_id": str(selected["topology_id"]),
                    "intervention_role": str(
                        selected["intervention_role"]
                    ),
                    "intervention_axis": str(
                        selected["intervention_axis"]
                    ),
                    "expected_regime_targets": str(
                        selected["expected_regime_targets"]
                    ),
                    "execution_class": "repeatability",
                    "runtime_sensitivity": "",
                    "required_dataset_capabilities": "",
                    "distribution_key_usage": "",
                    "intervention_roles": "",
                    "sentinel_flag": str(
                        bool(selected["sentinel_flag"])
                    ).lower(),
                    "_repeatability_repetitions": str(
                        int(selected["planned_repetitions"])
                    ),
                }
            )
        expanded = _apply_execution_policy_to_rows(
            rows, group_id=group_id, execution_policy=execution_policy
        )
        group_dir = output_dir / "groups" / group_id
        manifest_path = group_dir / "instance_manifest.csv"
        _write_instance_manifest(manifest_path, expanded)

        source_sweep_path = workspace_root / str(source["sweep_config"])
        source_sweep = yaml.safe_load(
            source_sweep_path.read_text(encoding="utf-8")
        )
        source_sweep["sweep_id"] = group_id
        source_sweep["workload"]["instance_manifest"] = _workspace_relative(
            manifest_path, workspace_root
        )
        source_sweep["workload"]["order_policy"] = execution_policy[
            "order_policy"
        ]
        source_sweep["workload"]["shuffle_seed"] = execution_policy[
            "shuffle_seed"
        ]
        source_sweep["execution_policy"] = execution_policy
        source_sweep["collection"]["cache_policy"] = execution_policy[
            "cache_policy"
        ]
        source_sweep["collection"]["database_result_rows_stored"] = False
        source_sweep["repeatability"] = {
            "enabled": True,
            "condition_count": int(group["condition_id"].nunique()),
            "execution_count": len(expanded),
        }
        sweep_path = output_dir / "sweeps" / f"{group_id}.yml"
        write_yaml(sweep_path, source_sweep)
        plan_group = dict(source)
        plan_group.update(
            {
                "group_id": group_id,
                "sweep_id": group_id,
                "source_plan_id": source_plan_id,
                "source_plan_ids": source_plan_ids,
                "dataset_profile_id": dataset_id,
                "runtime_config_id": runtime_config_id,
                "target_group": target_group,
                "condition_count": int(group["condition_id"].nunique()),
                "sentinel_condition_count": int(
                    group["sentinel_flag"].astype(bool).sum()
                ),
                "instance_count": len(expanded),
                "instance_manifest": _workspace_relative(
                    manifest_path, workspace_root
                ),
                "sweep_config": _workspace_relative(
                    sweep_path, workspace_root
                ),
            }
        )
        plan_groups.append(plan_group)

    plan = {
        "corpus_id": corpus_id,
        "source_selection": _workspace_relative(
            output_dir / "repeatability_selection.csv", workspace_root
        ),
        "source_execution_plans": {
            source_plan_id: _workspace_relative(path, workspace_root)
            for source_plan_id, path in sorted(source_plan_paths.items())
        },
        "execution_backend": "master-regimes-infra.database_sweep",
        "locally_rendered_without_infrastructure": True,
        "dry_run_only": False,
        "database_result_rows_stored": False,
        "condition_count": int(selection["condition_id"].nunique()),
        "sentinel_condition_count": int(
            selection["sentinel_flag"].astype(bool).sum()
        ),
        "execution_count": int(
            sum(group["instance_count"] for group in plan_groups)
        ),
        "execution_policy": execution_policy,
        "group_count": len(plan_groups),
        "groups": plan_groups,
    }
    plan_path = output_dir / "corpus_execution_plan.yml"
    write_yaml(plan_path, plan)
    return plan_path


def read_instance_rows(plan: dict[str, Any], workspace_root: Path) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for group in plan["groups"]:
        path = workspace_root / str(group["instance_manifest"])
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    return pd.DataFrame(rows)
