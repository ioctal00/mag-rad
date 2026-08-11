from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import load_yaml, stable_slug, write_yaml
from .corpus_adapter import (
    INSTANCE_FIELDNAMES,
    _apply_execution_policy_to_rows,
    render_corpus,
)
from .corpus_manifest import validate_corpus_manifest

SELECTION_COLUMNS = [
    "experiment_id",
    "state_id",
    "state_name",
    "placement_state_id",
    "placement_action",
    "logical_data_contract_id",
    "execution_condition_id",
    "query_condition_id",
    "pairing_key",
    "logical_question_id",
    "physical_strategy_id",
    "execution_strategy",
    "template_id",
    "param_json",
    "rendered_sql_path",
    "rendered_sql_sha256",
    "dataset_id",
    "runtime_config_id",
    "target_group",
    "source_corpus_cell_id",
    "source_instance_id",
    "planned_repetitions",
]

EXTRA_INSTANCE_COLUMNS = [
    "state_id",
    "state_name",
    "placement_state_id",
    "placement_action",
    "logical_data_contract_id",
    "query_condition_id",
    "pairing_key",
    "physical_strategy_id",
    "rendered_sql_sha256",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def workspace_root() -> Path:
    return repo_root().parent


def resolve_repo_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (repo_root() / path).resolve()


def workspace_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(workspace_root()))
    except ValueError:
        return str(resolved)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def execution_condition_id(
    state_id: str,
    query_condition_id: str,
    *,
    analysis_id: str = "confirm-skew-v1",
) -> str:
    return f"{analysis_id}::{state_id}::{query_condition_id}"


def slot_id(
    state_id: str,
    query_condition_id: str,
    repetition_index: int,
    *,
    analysis_id: str = "confirm-skew-v1",
) -> str:
    return (
        f"{analysis_id}::{state_id}::{query_condition_id}"
        f"::r{repetition_index}"
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def _source_groups(source_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = {
        str(group["dataset_profile_id"]): group
        for group in source_plan["groups"]
    }
    if len(groups) != len(source_plan["groups"]):
        raise ValueError("Source plan has duplicate dataset execution groups")
    return groups


def _source_rows(group: dict[str, Any]) -> list[dict[str, str]]:
    return _read_csv(workspace_root() / str(group["instance_manifest"]))


def _find_source_row(
    rows: list[dict[str, str]],
    condition: dict[str, Any],
) -> dict[str, str]:
    cell_id = str(condition["corpus_cell_id"])
    template_id = str(condition["template_id"])
    params = stable_json(condition["parameters"])
    matches = [
        row
        for row in rows
        if (
            str(row["corpus_cell_id"]) == cell_id
            or str(row["corpus_cell_id"]).startswith(f"{cell_id}__dataset-")
        )
        and str(row["template_id"]) == template_id
        and stable_json(json.loads(row["param_json"])) == params
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one source row for {cell_id}/{template_id}, got {len(matches)}"
        )
    return matches[0]


def _state_intervention(state_id: str, state: dict[str, Any]) -> dict[str, Any]:
    if state_id == "C":
        return {
            "dataset_transition": "reuse_previous_loaded_dataset",
            "pre_group_action": state["placement_action"],
            "requires_placement_orchestrator": True,
        }
    return {
        "dataset_transition": "clean_load",
        "pre_group_action": state["placement_action"],
        "requires_placement_orchestrator": state_id == "B",
    }


def _build_frozen_contract(config: dict[str, Any]) -> dict[str, Any]:
    frozen = config["frozen_model"]
    paths = {
        key: resolve_repo_path(str(frozen[key]))
        for key in (
            "manifest",
            "scaled_matrix",
            "raw_matrix",
            "candidate_config",
            "centers",
        )
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Frozen model contract paths are missing: " + ", ".join(missing)
        )
    manifest = load_yaml(paths["manifest"])
    features = list(manifest["feature_matrix"]["features"])
    contract = {
        "model_id": str(frozen["model_id"]),
        "manifest_model_id": str(manifest["model_id"]),
        "retrain": bool(frozen["retrain"]),
        "training_rows_include_confirmatory": bool(
            frozen["training_rows_include_confirmatory"]
        ),
        "feature_count": int(frozen["feature_count"]),
        "manifest_feature_count": len(features),
        "features": features,
        "primary_model": {
            "algorithm": manifest["primary_model"]["algorithm"],
            "k": int(manifest["primary_model"]["k"]),
            "fuzzifier": float(manifest["primary_model"]["fuzzifier"]),
        },
        "artifacts": {
            key: {
                "path": workspace_relative(path),
                "sha256": sha256_file(path),
            }
            for key, path in paths.items()
        },
    }
    if contract["model_id"] != contract["manifest_model_id"]:
        raise ValueError("Configured and manifest frozen model IDs differ")
    if contract["retrain"]:
        raise ValueError("Confirmatory protocol must not retrain the model")
    if contract["training_rows_include_confirmatory"]:
        raise ValueError("Confirmatory rows must not enter model training")
    if contract["feature_count"] != contract["manifest_feature_count"]:
        raise ValueError("Frozen model feature count mismatch")
    if contract["primary_model"]["k"] != 4:
        raise ValueError("Confirmatory projection requires the frozen k=4 model")
    return contract


def _selection_and_rows(
    *,
    config: dict[str, Any],
    source_plan: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, list[dict[str, str]]]]:
    groups = _source_groups(source_plan)
    repetitions = int(config["design"]["repetitions"])
    execution_policy = {
        "cache_policy": config["design"]["cache_policy"],
        "order_policy": "deterministic_shuffle",
        "shuffle_seed": int(config["design"]["shuffle_seed"]),
        "repetitions_default": repetitions,
        "sentinel_repetitions": repetitions,
    }
    selection_rows: list[dict[str, Any]] = []
    instance_rows: dict[str, list[dict[str, str]]] = {}

    for state_id in config["design"]["state_order"]:
        state = config["states"][state_id]
        dataset_id = str(state["dataset_profile_id"])
        source_group = groups.get(dataset_id)
        if source_group is None:
            raise ValueError(f"No source execution group for {dataset_id}")
        source_rows = _source_rows(source_group)
        state_source_rows: list[dict[str, str]] = []
        for condition in config["query_conditions"]:
            source = _find_source_row(source_rows, condition)
            query_condition_id = str(condition["condition_id"])
            exec_condition_id = execution_condition_id(
                state_id,
                query_condition_id,
                analysis_id=str(config["analysis_id"]),
            )
            sql_path = Path(source["rendered_sql_path"]).resolve()
            sql_hash = sha256_file(sql_path)
            pairing_key = query_condition_id
            selection_rows.append(
                {
                    "experiment_id": config["analysis_id"],
                    "state_id": state_id,
                    "state_name": state["state_name"],
                    "placement_state_id": state["placement_state_id"],
                    "placement_action": state["placement_action"],
                    "logical_data_contract_id": state[
                        "logical_data_contract_id"
                    ],
                    "execution_condition_id": exec_condition_id,
                    "query_condition_id": query_condition_id,
                    "pairing_key": pairing_key,
                    "logical_question_id": condition[
                        "logical_question_id"
                    ],
                    "physical_strategy_id": condition[
                        "physical_strategy_id"
                    ],
                    "execution_strategy": source["execution_strategy"],
                    "template_id": source["template_id"],
                    "param_json": stable_json(
                        json.loads(source["param_json"])
                    ),
                    "rendered_sql_path": workspace_relative(sql_path),
                    "rendered_sql_sha256": sql_hash,
                    "dataset_id": dataset_id,
                    "runtime_config_id": config["design"][
                        "runtime_config_id"
                    ],
                    "target_group": source_group["target_group"],
                    "source_corpus_cell_id": source["corpus_cell_id"],
                    "source_instance_id": source["instance_id"],
                    "planned_repetitions": repetitions,
                }
            )
            row = dict(source)
            row.update(
                {
                    "condition_id": exec_condition_id,
                    "instance_id": stable_slug(
                        f"{state_id}-{source['instance_id']}"
                    ),
                    "corpus_id": config["analysis_id"],
                    "corpus_cell_id": stable_slug(
                        f"{state_id}-{query_condition_id}"
                    ),
                    "dataset_profile_id": dataset_id,
                    "runtime_config_id": config["design"][
                        "runtime_config_id"
                    ],
                    "intervention_role": "final_check",
                    "intervention_axis": (
                        "shard_placement"
                        if state_id in {"B", "C"}
                        else "dataset_region_balance"
                    ),
                    "rendered_sql_path": workspace_relative(sql_path),
                    "pressure_axis": "worker_data_skew",
                    "pressure_level": (
                        "mitigated" if state_id == "B" else "stressed"
                    ),
                    "variant": (
                        "mitigated" if state_id == "B" else "stressed"
                    ),
                    "mitigation_action": "disperse_hot_shards",
                    "target_metric": "execution_time_seconds",
                    "dataset_role": "pressure_isolated",
                    "state_id": state_id,
                    "state_name": str(state["state_name"]),
                    "placement_state_id": str(
                        state["placement_state_id"]
                    ),
                    "placement_action": str(state["placement_action"]),
                    "logical_data_contract_id": str(
                        state["logical_data_contract_id"]
                    ),
                    "query_condition_id": query_condition_id,
                    "pairing_key": pairing_key,
                    "physical_strategy_id": str(
                        condition["physical_strategy_id"]
                    ),
                    "rendered_sql_sha256": sql_hash,
                    "_repeatability_repetitions": str(repetitions),
                }
            )
            state_source_rows.append(row)
        instance_rows[state_id] = _apply_execution_policy_to_rows(
            state_source_rows,
            group_id=f"{config['analysis_id']}--state-{state_id}",
            execution_policy=execution_policy,
        )

    selection = pd.DataFrame(selection_rows, columns=SELECTION_COLUMNS)
    return selection, instance_rows


def build_confirmatory_skew_plan(
    *,
    config_path: Path,
    source_render_dir: Path | None = None,
    output_dir: Path | None = None,
    selection_path: Path | None = None,
) -> dict[str, Path]:
    config_path = config_path.resolve()
    config = load_yaml(config_path)
    source_manifest = resolve_repo_path(config["source_manifest"])
    manifest_validation = validate_corpus_manifest(source_manifest)
    if manifest_validation["status"] != "ok":
        raise ValueError(
            "Confirmatory source manifest is invalid: "
            + "; ".join(manifest_validation["errors"])
        )
    source_render_dir = (
        source_render_dir.resolve()
        if source_render_dir
        else resolve_repo_path(config["source_render_dir"])
    )
    output_dir = (
        output_dir.resolve()
        if output_dir
        else resolve_repo_path(config["output_dir"])
    )
    selection_path = (
        selection_path.resolve()
        if selection_path
        else resolve_repo_path(config["selection"])
    )

    source_plan_path = render_corpus(
        manifest_path=source_manifest,
        output_dir=source_render_dir,
    )
    source_plan = load_yaml(source_plan_path)
    selection, rows_by_state = _selection_and_rows(
        config=config,
        source_plan=source_plan,
    )
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    selection.to_csv(selection_path, index=False)

    output_dir.mkdir(parents=True, exist_ok=True)
    frozen_contract_path: Path | None = None
    if config.get("frozen_model"):
        frozen_contract = _build_frozen_contract(config)
        frozen_contract_path = output_dir / "frozen_contract.json"
        frozen_contract_path.write_text(
            json.dumps(frozen_contract, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    source_groups = _source_groups(source_plan)
    plan_groups: list[dict[str, Any]] = []
    instance_fieldnames = [
        *INSTANCE_FIELDNAMES,
        *[
            field
            for field in EXTRA_INSTANCE_COLUMNS
            if field not in INSTANCE_FIELDNAMES
        ],
    ]
    for state_id in config["design"]["state_order"]:
        state = config["states"][state_id]
        source_group = source_groups[str(state["dataset_profile_id"])]
        runtime_config_id = str(source_group["runtime_config_id"])
        group_id = stable_slug(
            f"{config['analysis_id']}--state-{state_id}--"
            f"{state['dataset_profile_id']}--{runtime_config_id}--analytics-clients"
        )
        group_dir = output_dir / "groups" / group_id
        manifest_path = group_dir / "instance_manifest.csv"
        rows = rows_by_state[state_id]
        _write_csv(manifest_path, rows, instance_fieldnames)

        source_sweep = load_yaml(
            workspace_root() / str(source_group["sweep_config"])
        )
        source_sweep["sweep_id"] = group_id
        source_sweep["workload"]["instance_manifest"] = workspace_relative(
            manifest_path
        )
        source_sweep["workload"]["order_policy"] = "deterministic_shuffle"
        source_sweep["workload"]["shuffle_seed"] = int(
            config["design"]["shuffle_seed"]
        )
        source_sweep["collection"]["database_result_rows_stored"] = False
        source_sweep["confirmatory_skew"] = {
            "experiment_id": config["analysis_id"],
            "state_id": state_id,
            "placement_state_id": state["placement_state_id"],
            "placement_action": state["placement_action"],
            "logical_data_contract_id": state[
                "logical_data_contract_id"
            ],
            **_state_intervention(state_id, state),
        }
        sweep_path = output_dir / "sweeps" / f"{group_id}.yml"
        write_yaml(sweep_path, source_sweep)

        plan_group = dict(source_group)
        plan_group.update(
            {
                "group_id": group_id,
                "sweep_id": group_id,
                "state_id": state_id,
                "state_name": state["state_name"],
                "placement_state_id": state["placement_state_id"],
                "placement_action": state["placement_action"],
                "logical_data_contract_id": state[
                    "logical_data_contract_id"
                ],
                **_state_intervention(state_id, state),
                "condition_count": len(config["query_conditions"]),
                "instance_count": len(rows),
                "instance_manifest": workspace_relative(manifest_path),
                "sweep_config": workspace_relative(sweep_path),
            }
        )
        plan_groups.append(plan_group)

    design_matrix_rows: list[dict[str, Any]] = []
    for state_id, rows in rows_by_state.items():
        for row in rows:
            design_matrix_rows.append(
                {
                    "slot_id": slot_id(
                        state_id,
                        row["query_condition_id"],
                        int(row["repetition_index"]),
                        analysis_id=str(config["analysis_id"]),
                    ),
                    "state_id": state_id,
                    "state_name": row["state_name"],
                    "placement_state_id": row["placement_state_id"],
                    "placement_action": row["placement_action"],
                    "logical_data_contract_id": row[
                        "logical_data_contract_id"
                    ],
                    "execution_condition_id": row["condition_id"],
                    "query_condition_id": row["query_condition_id"],
                    "pairing_key": row["pairing_key"],
                    "repetition_index": int(row["repetition_index"]),
                    "run_order": int(row["run_order"]),
                    "dataset_id": row["dataset_profile_id"],
                    "template_id": row["template_id"],
                    "physical_strategy_id": row[
                        "physical_strategy_id"
                    ],
                    "param_json": stable_json(
                        json.loads(row["param_json"])
                    ),
                    "rendered_sql_path": row["rendered_sql_path"],
                    "rendered_sql_sha256": row[
                        "rendered_sql_sha256"
                    ],
                }
            )
    design_matrix_path = output_dir / "design_matrix.csv"
    pd.DataFrame(design_matrix_rows).to_csv(
        design_matrix_path,
        index=False,
    )

    plan = {
        "corpus_id": config["analysis_id"],
        "protocol_version": config["protocol_version"],
        "source_manifest": workspace_relative(source_manifest),
        "source_execution_plan": workspace_relative(source_plan_path),
        "source_selection": workspace_relative(selection_path),
        "design_matrix": workspace_relative(design_matrix_path),
        "execution_backend": "master-regimes-infra.database_sweep",
        "placement_aware_runner_required": True,
        "locally_rendered_without_infrastructure": True,
        "dry_run_only_until_capability_gate": True,
        "database_result_rows_stored": False,
        "query_condition_count": len(config["query_conditions"]),
        "state_condition_count": len(selection),
        "execution_condition_count": len(selection),
        "execution_count": sum(len(rows) for rows in rows_by_state.values()),
        "state_count": len(rows_by_state),
        "state_order": config["design"]["state_order"],
        "execution_policy": {
            "cache_policy": config["design"]["cache_policy"],
            "order_policy": config["design"]["order_policy"],
            "shuffle_seed": int(config["design"]["shuffle_seed"]),
            "repetitions": int(config["design"]["repetitions"]),
            "warmup_per_instance": bool(
                config["design"]["warmup_per_instance"]
            ),
            "explicit_cache_reset": bool(
                config["design"]["explicit_cache_reset"]
            ),
        },
        "placement_contract": config["placement"],
        "artifact_contract": config["artifact_contract"],
        "group_count": len(plan_groups),
        "groups": plan_groups,
    }
    if frozen_contract_path is not None:
        plan["frozen_contract"] = workspace_relative(frozen_contract_path)
    plan_path = output_dir / "corpus_execution_plan.yml"
    write_yaml(plan_path, plan)
    outputs = {
        "plan": plan_path,
        "selection": selection_path,
        "design_matrix": design_matrix_path,
        "source_plan": source_plan_path,
    }
    if frozen_contract_path is not None:
        outputs["frozen_contract"] = frozen_contract_path
    return outputs


def read_plan_instance_rows(plan: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for group in plan["groups"]:
        rows.extend(
            _read_csv(workspace_root() / str(group["instance_manifest"]))
        )
    return pd.DataFrame(rows)


def evaluate_local_readiness(
    *,
    config_path: Path,
    plan_path: Path,
    selection_path: Path,
) -> dict[str, Any]:
    config = load_yaml(config_path.resolve())
    plan = load_yaml(plan_path.resolve())
    selection = pd.read_csv(selection_path.resolve(), low_memory=False)
    design_matrix = pd.read_csv(
        workspace_root() / str(plan["design_matrix"]),
        low_memory=False,
    )
    plan_rows = read_plan_instance_rows(plan)
    frozen = json.loads(
        (workspace_root() / str(plan["frozen_contract"])).read_text(
            encoding="utf-8"
        )
    )

    b = selection[selection["state_id"].eq("B")].set_index(
        "query_condition_id"
    )
    c = selection[selection["state_id"].eq("C")].set_index(
        "query_condition_id"
    )
    shared = sorted(set(b.index) & set(c.index))
    bc_differences: list[dict[str, Any]] = []
    for query_condition_id in shared:
        for field in (
            "logical_data_contract_id",
            "template_id",
            "param_json",
            "rendered_sql_sha256",
        ):
            if str(b.loc[query_condition_id, field]) != str(
                c.loc[query_condition_id, field]
            ):
                bc_differences.append(
                    {
                        "query_condition_id": query_condition_id,
                        "field": field,
                        "b_value": b.loc[query_condition_id, field],
                        "c_value": c.loc[query_condition_id, field],
                    }
                )

    query_semantics: list[dict[str, Any]] = []
    for condition in config["query_conditions"]:
        query_id = str(condition["condition_id"])
        rows = selection[selection["query_condition_id"].eq(query_id)]
        sql_path = workspace_root() / str(rows.iloc[0]["rendered_sql_path"])
        sql = sql_path.read_text(encoding="utf-8").lower()
        physical = str(condition["physical_strategy_id"])
        query_semantics.append(
            {
                "query_condition_id": query_id,
                "logical_question_id": condition["logical_question_id"],
                "physical_strategy_id": physical,
                "template_id": condition["template_id"],
                "sql_sha256": sha256_file(sql_path),
                "materialized_raw_boundary_expected": physical
                == "raw_gac_finalize",
                "materialized_raw_boundary_observed": (
                    " as materialized (" in sql
                ),
                "group_by_present": "group by" in sql,
                "fdw_eu_present": "fdw_eu.events" in sql,
                "fdw_us_present": "fdw_us.events" in sql,
            }
        )

    profile_path = resolve_repo_path(
        config["hot_tenant_contract"]["source_profile"]
    )
    profile = load_yaml(profile_path)
    eu_range = profile["regions"]["eu"]["tenant_id_range"]
    us_range = profile["regions"]["us"]["tenant_id_range"]
    hot_pct = float(profile["distribution"]["hot_tenant_pct"])
    expected_eu_count = int(
        ((int(eu_range[1]) - int(eu_range[0]) + 1) * hot_pct / 100.0)
        + 0.5
    )
    expected_us_count = int(
        ((int(us_range[1]) - int(us_range[0]) + 1) * hot_pct / 100.0)
        + 0.5
    )
    configured_eu_hot = list(
        config["hot_tenant_contract"]["eu_hot_tenant_ids"]
    )
    configured_us_hot = list(
        config["hot_tenant_contract"]["us_hot_tenant_ids"]
    )

    dataset_sequence = [str(group["state_id"]) for group in plan["groups"]]
    slot_columns = ["state_id", "query_condition_id", "repetition_index"]
    gates = {
        "source_manifest_valid": validate_corpus_manifest(
            resolve_repo_path(config["source_manifest"])
        )["status"]
        == "ok",
        "state_count_is_4": int(plan["state_count"]) == 4,
        "query_condition_count_is_4": int(plan["query_condition_count"]) == 4,
        "state_condition_count_is_16": len(selection) == 16,
        "execution_count_is_48": int(plan["execution_count"]) == 48
        and len(design_matrix) == 48
        and len(plan_rows) == 48,
        "measurement_slots_unique": not design_matrix[
            ["slot_id"]
        ].duplicated().any()
        and not plan_rows[slot_columns].duplicated().any(),
        "state_order_is_a_b_c_d": dataset_sequence == ["A", "B", "C", "D"],
        "each_state_has_12_slots": bool(
            (design_matrix.groupby("state_id").size() == 12).all()
        ),
        "bc_pair_count_is_12": len(shared)
        * int(config["design"]["repetitions"])
        == 12,
        "bc_sql_params_and_data_contract_equal": not bc_differences,
        "bc_dataset_profile_equal": str(
            config["states"]["B"]["dataset_profile_id"]
        )
        == str(config["states"]["C"]["dataset_profile_id"]),
        "bc_placement_state_differs": str(
            config["states"]["B"]["placement_state_id"]
        )
        != str(config["states"]["C"]["placement_state_id"]),
        "c_reuses_b_dataset": bool(
            next(
                group
                for group in plan["groups"]
                if group["state_id"] == "C"
            )["dataset_transition"]
            == "reuse_previous_loaded_dataset"
        ),
        "placement_move_and_rollback_explicit": (
            config["placement"]["move_function"]
            == "citus_move_shard_placement"
            and config["placement"]["shard_transfer_mode"]
            == "block_writes"
            and bool(config["placement"]["rollback"]["primary"])
            and bool(config["placement"]["rollback"]["fallback"])
        ),
        "hot_tenant_contract_matches_generator_semantics": (
            len(configured_eu_hot) == expected_eu_count
            and len(configured_us_hot) == expected_us_count
            and configured_eu_hot
            == list(range(int(eu_range[0]), int(eu_range[0]) + expected_eu_count))
            and configured_us_hot
            == list(range(int(us_range[0]), int(us_range[0]) + expected_us_count))
        ),
        "all_queries_have_two_regions_and_grouping": all(
            row["fdw_eu_present"]
            and row["fdw_us_present"]
            and row["group_by_present"]
            for row in query_semantics
        ),
        "raw_finalize_boundary_matches_contract": all(
            row["materialized_raw_boundary_expected"]
            == row["materialized_raw_boundary_observed"]
            for row in query_semantics
        ),
        "frozen_model_id_matches": frozen["model_id"]
        == config["frozen_model"]["model_id"],
        "frozen_feature_count_is_21": frozen["feature_count"] == 21
        and frozen["manifest_feature_count"] == 21,
        "frozen_model_retrain_false": frozen["retrain"] is False
        and frozen["training_rows_include_confirmatory"] is False,
        "primary_outcomes_locked": set(config["outcomes"]["primary"])
        == {"worker_rows_cv", "dominant_hot_worker_hot_event_share"},
        "artifact_contract_has_region_and_worker": set(
            config["artifact_contract"]["required_query_scopes"]
        )
        == {"main", "regional_coordinator", "worker_task"},
        "database_result_rows_not_stored": (
            config["design"]["database_result_rows_stored"] is False
            and plan["database_result_rows_stored"] is False
            and config["artifact_contract"]["database_result_rows_stored"]
            is False
            and not any(
                column
                in {
                    "query_result",
                    "result_rows",
                    "row_payload",
                }
                for column in plan_rows.columns
            )
        ),
    }
    gates = {name: bool(value) for name, value in gates.items()}
    return {
        "gate_id": "L0-confirmatory-skew-local-readiness",
        "analysis_id": config["analysis_id"],
        "status": "pass" if all(gates.values()) else "fail",
        "decision": "GO" if all(gates.values()) else "HOLD",
        "gates": gates,
        "bc_differences": bc_differences,
        "query_semantics": query_semantics,
        "profile_contract": {
            "profile": workspace_relative(profile_path),
            "profile_sha256": sha256_file(profile_path),
            "expected_eu_hot_tenant_count": expected_eu_count,
            "expected_us_hot_tenant_count": expected_us_count,
            "configured_eu_hot_tenant_ids": configured_eu_hot,
            "configured_us_hot_tenant_ids": configured_us_hot,
        },
        "frozen_contract": frozen,
    }
