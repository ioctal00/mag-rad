from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = ROOT.parent
DEFAULT_ACTION_AUDIT = ROOT / "analysis/reports/pressure-raw-v1-mitigation-action-audit"
DEFAULT_MATRIX = ROOT / "generated/corpus/pressure-raw-v1/execution_matrix.csv"
DEFAULT_CONTRACT = ROOT / "configs/validation/mitigation_correctness_recovery_v1.yml"
DEFAULT_OUT = ROOT / "analysis/reports/pressure-raw-v1-correctness-recovery"


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_source_path(value: Any) -> Path:
    path = Path(str(value))
    candidates = [path] if path.is_absolute() else [ROOT / path, WORKSPACE_ROOT / path]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            return resolved
    return candidates[-1].resolve()


def _normalized(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def build_selection(
    pair_audit: pd.DataFrame,
    execution_matrix: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    selection_contract = contract["selection"]
    required_status = str(selection_contract["required_pair_status"])
    selected_pairs = pair_audit[
        pair_audit["gain_pair_status"].astype(str).eq(required_status)
    ].copy()
    expected_pairs = int(selection_contract["expected_pair_count"])
    if len(selected_pairs) != expected_pairs:
        raise ValueError(f"Expected {expected_pairs} review pairs, found {len(selected_pairs)}")

    matrix = execution_matrix.copy()
    matrix["repetition_index_numeric"] = pd.to_numeric(
        matrix["repetition_index"], errors="coerce"
    ).fillna(0)
    first_by_condition = (
        matrix.sort_values(["condition_id", "repetition_index_numeric"])
        .drop_duplicates("condition_id", keep="first")
        .set_index("condition_id", drop=False)
    )
    condition_counts = matrix.groupby("condition_id").size().to_dict()
    rows: list[dict[str, Any]] = []
    violations: list[str] = []
    invariant_fields = {
        "dataset_profile_id": "require_same_dataset",
        "logical_question_id": "require_same_logical_question",
        "template_id": "require_same_template",
        "param_json": "require_same_parameters",
    }
    for pair in selected_pairs.itertuples(index=False):
        members: dict[str, pd.Series[Any]] = {}
        for member in ("stressed", "mitigated"):
            condition_id = str(getattr(pair, f"{member}_condition_id"))
            if condition_id not in first_by_condition.index:
                violations.append(f"{pair.pair_id}:{member}:missing_condition")
                continue
            members[member] = first_by_condition.loc[condition_id]
        if len(members) != 2:
            continue
        stressed = members["stressed"]
        mitigated = members["mitigated"]
        for field, flag in invariant_fields.items():
            if bool(selection_contract.get(flag, False)) and _normalized(
                stressed.get(field)
            ) != _normalized(mitigated.get(field)):
                violations.append(f"{pair.pair_id}:{field}:member_mismatch")
        if str(pair.target_scope_canonical) != str(selection_contract["target_scope"]):
            violations.append(f"{pair.pair_id}:target_scope")
        for member, matrix_row in members.items():
            sql_path = resolve_source_path(matrix_row["rendered_sql_path"])
            if not sql_path.is_file():
                violations.append(f"{pair.pair_id}:{member}:missing_sql")
                continue
            condition_id = str(matrix_row["condition_id"])
            rows.append(
                {
                    "pair_id": str(pair.pair_id),
                    "member": member,
                    "mitigation_action": str(pair.mitigation_action),
                    "intervention_role": str(pair.intervention_role),
                    "pressure_axis": str(pair.pressure_axis),
                    "condition_id": condition_id,
                    "source_execution_slot_id": str(matrix_row["execution_slot_id"]),
                    "source_instance_id": _normalized(matrix_row.get("instance_id")),
                    "batch_id": str(matrix_row["batch_id"]),
                    "group_id": _normalized(matrix_row.get("group_id")),
                    "group_plan": _normalized(matrix_row.get("group_plan")),
                    "backend": str(matrix_row["backend"]),
                    "dataset_profile_id": str(matrix_row["dataset_profile_id"]),
                    "dataset_size_class": str(matrix_row["dataset_size_class"]),
                    "runtime_config_id": str(matrix_row["runtime_config_id"]),
                    "execution_strategy": str(matrix_row["execution_strategy"]),
                    "physical_strategy_id": str(matrix_row["physical_strategy_id"]),
                    "placement_state_id": _normalized(matrix_row.get("placement_state_id")),
                    "placement_action": _normalized(matrix_row.get("placement_action")),
                    "template_id": str(matrix_row["template_id"]),
                    "logical_question_id": str(matrix_row["logical_question_id"]),
                    "param_json": str(matrix_row["param_json"]),
                    "rendered_sql_path": str(sql_path),
                    "rendered_sql_sha256_actual": sha256_file(sql_path),
                    "source_condition_repetition_count": int(condition_counts.get(condition_id, 0)),
                    "recovery_id": f"{pair.pair_id}::{member}",
                }
            )
    if violations:
        raise ValueError("Selection contract violations: " + ", ".join(violations[:20]))
    selection = pd.DataFrame(rows).sort_values(["batch_id", "group_id", "pair_id", "member"])
    expected_members = expected_pairs * int(selection_contract["members_per_pair"])
    if len(selection) != expected_members:
        raise ValueError(f"Expected {expected_members} members, found {len(selection)}")
    if selection["recovery_id"].duplicated().any():
        raise ValueError("Duplicate recovery_id values")
    return selection.reset_index(drop=True)


def normalize_postgres_type(value: str) -> str:
    return " ".join(value.strip().lower().split())


def read_snapshot(
    snapshot_dir: Path,
) -> tuple[list[dict[str, Any]], list[list[str]], dict[str, Any]]:
    manifest_path = snapshot_dir / "results/result_snapshot.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows_path = snapshot_dir / str(manifest["result_rows_file"])
    with rows_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    columns = list(manifest.get("columns") or [])
    if any(len(row) != len(columns) for row in rows):
        raise ValueError(f"CSV column count does not match schema in {snapshot_dir}")
    return columns, rows, manifest


@dataclass(frozen=True)
class CellDifference:
    absolute: float
    relative: float


def compare_cell(
    left: str,
    right: str,
    postgres_type: str,
    *,
    null_token: str,
    floating_types: set[str],
    absolute_tolerance: float,
    relative_tolerance: float,
) -> tuple[bool, CellDifference | None]:
    if left == null_token or right == null_token:
        return left == right, None
    normalized_type = normalize_postgres_type(postgres_type)
    if normalized_type not in floating_types:
        if normalized_type in {"numeric", "decimal"}:
            try:
                return Decimal(left) == Decimal(right), None
            except InvalidOperation:
                return False, None
        return left == right, None
    try:
        left_value = float(left)
        right_value = float(right)
    except ValueError:
        return False, None
    absolute = abs(left_value - right_value)
    denominator = max(abs(left_value), abs(right_value), absolute_tolerance)
    relative = absolute / denominator
    return (
        math.isclose(
            left_value,
            right_value,
            abs_tol=absolute_tolerance,
            rel_tol=relative_tolerance,
        ),
        CellDifference(absolute=absolute, relative=relative),
    )


def compare_row(
    left: list[str],
    right: list[str],
    columns: list[dict[str, Any]],
    comparison: dict[str, Any],
) -> tuple[bool, list[CellDifference]]:
    differences: list[CellDifference] = []
    for index, column in enumerate(columns):
        equal, difference = compare_cell(
            left[index],
            right[index],
            str(column["postgres_type"]),
            null_token=str(comparison["null_token"]),
            floating_types={
                normalize_postgres_type(value) for value in comparison["floating_types"]
            },
            absolute_tolerance=float(comparison["floating_absolute_tolerance"]),
            relative_tolerance=float(comparison["floating_relative_tolerance"]),
        )
        if not equal:
            return False, []
        if difference is not None:
            differences.append(difference)
    return True, differences


def match_multiset(
    left_rows: list[list[str]],
    right_rows: list[list[str]],
    columns: list[dict[str, Any]],
    comparison: dict[str, Any],
) -> tuple[bool, list[tuple[int, int]], float, float]:
    if len(left_rows) != len(right_rows):
        return False, [], math.nan, math.nan
    adjacency: list[list[tuple[int, list[CellDifference]]]] = []
    for left in left_rows:
        candidates: list[tuple[int, list[CellDifference]]] = []
        for right_index, right in enumerate(right_rows):
            equal, differences = compare_row(left, right, columns, comparison)
            if equal:
                candidates.append((right_index, differences))
        adjacency.append(candidates)
    matched_left_by_right: dict[int, int] = {}
    differences_by_pair: dict[tuple[int, int], list[CellDifference]] = {}

    def augment(left_index: int, seen_right: set[int]) -> bool:
        for right_index, differences in adjacency[left_index]:
            if right_index in seen_right:
                continue
            seen_right.add(right_index)
            previous_left = matched_left_by_right.get(right_index)
            if previous_left is None or augment(previous_left, seen_right):
                matched_left_by_right[right_index] = left_index
                differences_by_pair[(left_index, right_index)] = differences
                return True
        return False

    if not all(augment(index, set()) for index in range(len(left_rows))):
        return False, [], math.nan, math.nan
    matches = sorted((left, right) for right, left in matched_left_by_right.items())
    differences = [
        difference for pair in matches for difference in differences_by_pair.get(pair, [])
    ]
    max_absolute = max((item.absolute for item in differences), default=0.0)
    max_relative = max((item.relative for item in differences), default=0.0)
    return True, matches, max_absolute, max_relative


def compare_pair_snapshots(
    pair_id: str,
    snapshots_root: Path,
    contract: dict[str, Any],
    snapshot_dirs: dict[tuple[str, str], Path] | None = None,
) -> dict[str, Any]:
    member_data: dict[str, tuple[list[dict[str, Any]], list[list[str]], dict[str, Any]]] = {}
    for member in ("stressed", "mitigated"):
        snapshot_dir = (
            snapshot_dirs[(pair_id, member)]
            if snapshot_dirs is not None and (pair_id, member) in snapshot_dirs
            else snapshots_root / pair_id / member
        )
        try:
            member_data[member] = read_snapshot(snapshot_dir)
        except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError) as error:
            return {
                "pair_id": pair_id,
                "correctness_recovery_status": "missing_or_invalid_snapshot",
                "error": str(error),
            }
    stressed_columns, stressed_rows, stressed_manifest = member_data["stressed"]
    mitigated_columns, mitigated_rows, mitigated_manifest = member_data["mitigated"]
    schema_equal = [
        (column.get("name"), normalize_postgres_type(str(column.get("postgres_type", ""))))
        for column in stressed_columns
    ] == [
        (column.get("name"), normalize_postgres_type(str(column.get("postgres_type", ""))))
        for column in mitigated_columns
    ]
    if not schema_equal:
        return {
            "pair_id": pair_id,
            "correctness_recovery_status": "schema_mismatch",
            "stressed_row_count": len(stressed_rows),
            "mitigated_row_count": len(mitigated_rows),
            "schema_equal": False,
        }
    equivalent, matches, max_absolute, max_relative = match_multiset(
        stressed_rows,
        mitigated_rows,
        stressed_columns,
        contract["comparison"],
    )
    exact = bool(
        stressed_manifest.get("multiset_sha256")
        and stressed_manifest.get("multiset_sha256") == mitigated_manifest.get("multiset_sha256")
    )
    status = "value_mismatch"
    if exact:
        status = "exact_snapshot"
    elif equivalent:
        status = "tolerance_equivalent"
    return {
        "pair_id": pair_id,
        "correctness_recovery_status": status,
        "stressed_row_count": len(stressed_rows),
        "mitigated_row_count": len(mitigated_rows),
        "schema_equal": True,
        "matched_row_count": len(matches),
        "exact_multiset_hash": exact,
        "max_floating_absolute_difference": max_absolute,
        "max_floating_relative_difference": max_relative,
        "error": "",
    }


def safe_component(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in {"-", "_"} else "-" for character in value
    ).strip("-_")


def source_sweep_for_group(group_plan: str, group_id: str) -> Path:
    plan_path = resolve_source_path(group_plan)
    plan = load_yaml(plan_path)
    groups = [
        group for group in plan.get("groups", []) if str(group.get("group_id", "")) == group_id
    ]
    if len(groups) != 1:
        raise ValueError(
            f"Expected one source group {group_id!r} in {plan_path}, found {len(groups)}"
        )
    raw_path = str(groups[0].get("sweep_config", ""))
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    for base in (plan_path.parent, ROOT, WORKSPACE_ROOT, *plan_path.parents):
        candidate = (base / path).resolve()
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(raw_path)


def prepare_standard_execution_plan(
    selection: pd.DataFrame,
    contract: dict[str, Any],
    out_dir: Path,
) -> Path:
    standard = selection[selection["backend"].eq("standard_corpus")].copy()
    prepared_root = out_dir / "prepared/standard"
    plan_groups: list[dict[str, Any]] = []
    for (batch_id, dataset_id), rows in standard.groupby(
        ["batch_id", "dataset_profile_id"], sort=True
    ):
        source_sweeps = [
            source_sweep_for_group(str(row.group_plan), str(row.group_id))
            for row in rows.drop_duplicates("group_id").itertuples(index=False)
        ]
        source_configs = [load_yaml(path) for path in source_sweeps]
        base = deepcopy(source_configs[0])
        datasets = base.get("datasets") or []
        if len(datasets) != 1 or str(datasets[0].get("id", "")) != dataset_id:
            raise ValueError(f"Unexpected dataset definition for {batch_id}/{dataset_id}")
        runtime_by_id: dict[str, dict[str, Any]] = {}
        for source in source_configs:
            source_datasets = source.get("datasets") or []
            if len(source_datasets) != 1 or str(source_datasets[0].get("id", "")) != dataset_id:
                raise ValueError(f"Mixed datasets in recovery group {batch_id}/{dataset_id}")
            for runtime in source.get("runtime_configs") or []:
                runtime_id = str(runtime.get("id", ""))
                if runtime_id in runtime_by_id and runtime_by_id[runtime_id] != runtime:
                    raise ValueError(f"Conflicting runtime config {runtime_id}")
                runtime_by_id[runtime_id] = runtime
        expected_runtime_ids = set(rows["runtime_config_id"].astype(str))
        if expected_runtime_ids != set(runtime_by_id):
            runtime_by_id = {
                key: value for key, value in runtime_by_id.items() if key in expected_runtime_ids
            }
        if expected_runtime_ids != set(runtime_by_id):
            raise ValueError(f"Runtime config resolution failed for {batch_id}/{dataset_id}")

        group_key = safe_component(f"{batch_id}--{dataset_id}")
        group_dir = prepared_root / group_key
        group_dir.mkdir(parents=True, exist_ok=True)
        instance_rows = rows.copy()
        instance_rows["instance_id"] = instance_rows["source_instance_id"]
        instance_rows["execution_slot_id"] = instance_rows["recovery_id"]
        instance_rows["repeat_id"] = instance_rows["recovery_id"]
        instance_rows["repetition_index"] = 0
        instance_rows["planned_work_units"] = 1.0
        instance_manifest = group_dir / "instance_manifest.csv"
        instance_rows.to_csv(instance_manifest, index=False)

        base["sweep_id"] = f"correctness-recovery--{group_key}"
        base["runtime_configs"] = [runtime_by_id[key] for key in sorted(runtime_by_id)]
        workload = base.setdefault("workload", {})
        workload.update(
            {
                "instance_manifest": str(instance_manifest.resolve()),
                "filter_instances_by_runtime_config": True,
                "order_policy": "deterministic_pair_member_order",
                "shuffle_seed": 0,
            }
        )
        execution_contract = contract["execution"]
        collection = base.setdefault("collection", {})
        collection.update(
            {
                "global_stats_scope": "none",
                "os_sampler": False,
                "os_sampler_node_groups": [],
                "result_signature": False,
                "fdw_auto_explain": False,
                "fdw_auto_explain_regions": [],
                "network_profile_probe": False,
                "remote_edge_context": False,
                "result_snapshot_only": True,
                "result_snapshot_max_rows": int(execution_contract["max_result_rows"]),
                "result_snapshot_max_bytes": int(execution_contract["max_result_bytes"]),
                "hard_timeout_seconds": int(execution_contract["hard_timeout_seconds"]),
            }
        )
        execution_policy = base.setdefault("execution_policy", {})
        execution_policy.update(
            {
                "measurement_lane": "correctness_only_serial",
                "query_concurrency": 1,
                "repetitions_default": 1,
                "os_sampler": False,
                "result_signature": False,
                "fdw_auto_explain": False,
                "result_snapshot_only": True,
            }
        )
        sweep_path = group_dir / "sweep.yml"
        sweep_path.write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")
        plan_groups.append(
            {
                "group_id": f"correctness-recovery--{group_key}",
                "sweep_id": base["sweep_id"],
                "dataset_profile_id": dataset_id,
                "runtime_config_id": "multiple_filtered",
                "target_group": collection.get("target_group", "analytics_clients"),
                "cell_count": len(runtime_by_id),
                "instance_count": len(rows),
                "sweep_config": str(sweep_path.resolve()),
            }
        )
    plan = {
        "corpus_id": "pressure-raw-v1-correctness-recovery-standard",
        "execution_backend": "standard_corpus",
        "contract_version": contract["contract_version"],
        "groups": plan_groups,
    }
    plan_path = prepared_root / "corpus_execution_plan.yml"
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    return plan_path


def placement_query_condition(condition_id: str, state_id: str) -> str:
    marker = f"::{state_id}::"
    if marker not in condition_id:
        raise ValueError(f"Unable to derive placement query condition from {condition_id}")
    return condition_id.split(marker, maxsplit=1)[1]


def prepare_placement_execution_plan(
    selection: pd.DataFrame,
    contract: dict[str, Any],
    out_dir: Path,
) -> Path:
    placement = selection[selection["backend"].eq("placement_aware_worker")].copy()
    prepared_root = out_dir / "prepared/placement"
    groups: list[dict[str, Any]] = []
    for dataset_id, rows in placement.groupby("dataset_profile_id", sort=True):
        source_plans = rows["group_plan"].drop_duplicates().tolist()
        if len(source_plans) != 1:
            raise ValueError(f"Expected one placement plan for {dataset_id}")
        source_plan = resolve_source_path(source_plans[0])
        source_config = source_plan.parent.parent / "config.yml"
        if not source_config.is_file():
            raise FileNotFoundError(source_config)
        config = deepcopy(load_yaml(source_config))
        members: list[dict[str, str]] = []
        conditions: set[str] = set()
        state_counts: dict[str, int] = {}
        for row in rows.itertuples(index=False):
            state_id = "B" if str(row.placement_state_id) == "hot_shards_dispersed" else "C"
            query_condition_id = placement_query_condition(str(row.condition_id), state_id)
            conditions.add(query_condition_id)
            state_counts[state_id] = state_counts.get(state_id, 0) + 1
            members.append(
                {
                    "state_id": state_id,
                    "query_condition_id": query_condition_id,
                    "condition_id": str(row.condition_id),
                    "recovery_id": str(row.recovery_id),
                    "pair_id": str(row.pair_id),
                    "member": str(row.member),
                }
            )
        if state_counts.get("B") != state_counts.get("C"):
            raise ValueError(f"Unbalanced B/C correctness members for {dataset_id}")
        if len(members) != len(conditions) * 2:
            raise ValueError(f"Placement member identity is not bijective for {dataset_id}")

        config["analysis_id"] = f"correctness-recovery-{safe_component(dataset_id)}"
        capability = config.setdefault("capability_smoke", {})
        capability.update(
            {
                "condition_ids": sorted(conditions),
                "repetition_indices": [0],
                "require_checkpoint": False,
            }
        )
        artifact = config.setdefault("artifact_contract", {})
        artifact.update(
            {
                "database_result_rows_stored": True,
                "result_signature_required": False,
                "os_sampler_required": False,
                "collection_mode": "correctness_only_result_snapshot",
            }
        )
        config["correctness_recovery"] = {
            "enabled": True,
            "contract_version": contract["contract_version"],
            "members": sorted(
                members,
                key=lambda item: (item["state_id"], item["query_condition_id"]),
            ),
        }
        group_dir = prepared_root / safe_component(dataset_id)
        group_dir.mkdir(parents=True, exist_ok=True)
        config_path = group_dir / "config.yml"
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        groups.append(
            {
                "dataset_profile_id": dataset_id,
                "config": str(config_path.resolve()),
                "plan": str(source_plan.resolve()),
                "condition_count": len(conditions),
                "member_count": len(members),
                "pair_count": int(rows["pair_id"].nunique()),
            }
        )
    execution_plan = {
        "program_id": "pressure-raw-v1-correctness-recovery-placement",
        "execution_backend": "placement_aware_worker",
        "contract_version": contract["contract_version"],
        "groups": groups,
    }
    plan_path = prepared_root / "placement_execution_plan.yml"
    plan_path.write_text(yaml.safe_dump(execution_plan, sort_keys=False), encoding="utf-8")
    return plan_path


def prepare(args: argparse.Namespace, contract: dict[str, Any]) -> int:
    pair_audit = pd.read_csv(args.action_audit_dir / "mitigation_pair_audit.csv", low_memory=False)
    execution_matrix = pd.read_csv(args.execution_matrix, low_memory=False)
    selection = build_selection(pair_audit, execution_matrix, contract)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    selection_path = args.out_dir / "correctness_recovery_selection.csv"
    selection.to_csv(selection_path, index=False)
    group_summary = (
        selection.groupby(
            ["batch_id", "backend", "dataset_profile_id", "group_id"],
            dropna=False,
        )
        .agg(
            member_count=("recovery_id", "count"),
            pair_count=("pair_id", "nunique"),
            action_count=("mitigation_action", "nunique"),
        )
        .reset_index()
    )
    group_summary.to_csv(args.out_dir / "correctness_recovery_groups.csv", index=False)
    standard_plan = prepare_standard_execution_plan(selection, contract, args.out_dir)
    placement_plan = prepare_placement_execution_plan(selection, contract, args.out_dir)
    summary = {
        "contract_version": contract["contract_version"],
        "status": "READY_FOR_EXECUTION",
        "pair_count": int(selection["pair_id"].nunique()),
        "member_count": int(len(selection)),
        "batch_count": int(selection["batch_id"].nunique()),
        "source_group_count": int(selection["group_id"].nunique()),
        "execution_group_count": int(
            len(load_yaml(standard_plan).get("groups") or [])
            + len(load_yaml(placement_plan).get("groups") or [])
        ),
        "dataset_count": int(selection["dataset_profile_id"].nunique()),
        "action_count": int(selection["mitigation_action"].nunique()),
        "selection_sha256": sha256_file(selection_path),
        "standard_execution_plan": str(standard_plan),
        "standard_execution_plan_sha256": sha256_file(standard_plan),
        "placement_execution_plan": str(placement_plan),
        "placement_execution_plan_sha256": sha256_file(placement_plan),
    }
    write_json(args.out_dir / "preparation_summary.json", summary)
    print(selection_path)
    return 0


def analyze(args: argparse.Namespace, contract: dict[str, Any]) -> int:
    selection = pd.read_csv(args.out_dir / "correctness_recovery_selection.csv", low_memory=False)
    snapshot_dirs: dict[tuple[str, str], Path] | None = None
    if args.snapshot_locator.is_file():
        locator = pd.read_csv(args.snapshot_locator, low_memory=False)
        duplicate = locator.duplicated(["pair_id", "member"], keep=False)
        if duplicate.any():
            raise ValueError("Snapshot locator has duplicate pair/member rows")
        snapshot_dirs = {
            (str(row.pair_id), str(row.member)): Path(str(row.snapshot_dir)).resolve()
            for row in locator.itertuples(index=False)
        }
    rows: list[dict[str, Any]] = []
    for pair_id in sorted(selection["pair_id"].unique()):
        result = compare_pair_snapshots(
            str(pair_id),
            args.snapshots_root,
            contract,
            snapshot_dirs=snapshot_dirs,
        )
        metadata = selection[selection["pair_id"].eq(pair_id)].iloc[0]
        rows.append(
            {
                **result,
                "mitigation_action": metadata["mitigation_action"],
                "intervention_role": metadata["intervention_role"],
                "pressure_axis": metadata["pressure_axis"],
                "dataset_profile_id": metadata["dataset_profile_id"],
                "template_id": metadata["template_id"],
            }
        )
    results = pd.DataFrame(rows)
    results.to_csv(args.out_dir / "correctness_recovery_results.csv", index=False)
    accepted = set(contract["comparison"]["accepted_statuses"])
    results["accepted"] = results["correctness_recovery_status"].isin(accepted)
    by_action = (
        results.groupby(["mitigation_action", "intervention_role"], dropna=False)
        .agg(
            pair_count=("pair_id", "count"),
            accepted_pair_count=("accepted", "sum"),
            exact_pair_count=(
                "correctness_recovery_status",
                lambda values: int((values == "exact_snapshot").sum()),
            ),
            tolerance_pair_count=(
                "correctness_recovery_status",
                lambda values: int((values == "tolerance_equivalent").sum()),
            ),
        )
        .reset_index()
    )
    by_action.to_csv(args.out_dir / "correctness_recovery_by_action.csv", index=False)
    accepted_count = int(results["accepted"].sum())
    summary = {
        "contract_version": contract["contract_version"],
        "pair_count": int(len(results)),
        "accepted_pair_count": accepted_count,
        "unresolved_pair_count": int(len(results) - accepted_count),
        "status_counts": {
            str(key): int(value)
            for key, value in results["correctness_recovery_status"]
            .value_counts()
            .sort_index()
            .items()
        },
        "gate": "GO" if accepted_count == len(results) else "HOLD",
    }
    write_json(args.out_dir / "correctness_recovery_summary.json", summary)
    print(args.out_dir / "correctness_recovery_summary.json")
    return 0 if summary["gate"] == "GO" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare or analyze the bounded 83-pair correctness recovery."
    )
    parser.add_argument("mode", choices=["prepare", "analyze"])
    parser.add_argument("--action-audit-dir", type=Path, default=DEFAULT_ACTION_AUDIT)
    parser.add_argument("--execution-matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--snapshots-root",
        type=Path,
        default=DEFAULT_OUT / "snapshots",
    )
    parser.add_argument(
        "--snapshot-locator",
        type=Path,
        default=DEFAULT_OUT / "execution/snapshot_locator.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = load_yaml(args.contract)
    if args.mode == "prepare":
        return prepare(args, contract)
    return analyze(args, contract)


if __name__ == "__main__":
    raise SystemExit(main())
