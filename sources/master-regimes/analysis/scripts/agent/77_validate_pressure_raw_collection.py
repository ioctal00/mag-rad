from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_PROGRAM = REPO_ROOT / "generated/corpus/pressure-raw-v1/pressure_raw_program.yml"


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def resolve(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_checksums(root: Path) -> list[str]:
    errors: list[str] = []
    for raw_line in (root / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        expected, relative = raw_line.split("  ", 1)
        path = root / relative
        if not path.exists():
            errors.append(f"missing checksum artifact: {relative}")
        elif sha256_file(path) != expected:
            errors.append(f"checksum mismatch: {relative}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    program_path = args.program.resolve()
    root = program_path.parent
    program = load_yaml(program_path)
    coverage_gate = program["coverage_gate"]
    errors = validate_checksums(root)

    matrix_path = resolve(str(program["execution_matrix"]))
    with matrix_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required_identity = {
        "corpus_version",
        "batch_id",
        "collection_contract_version",
        "condition_id",
        "execution_slot_id",
        "pair_id",
        "repeat_id",
        "variant",
    }
    required_progress = {
        "dataset_size_class",
        "planned_query_passes",
        "progress_dataset_weight",
        "progress_runtime_multiplier",
        "planned_work_units",
        "progress_cost_class",
        "progress_weight_basis",
    }
    missing_columns = sorted(
        (required_identity | required_progress)
        - set(rows[0] if rows else {})
    )
    if missing_columns:
        errors.append(f"execution matrix missing columns: {missing_columns}")
    expected_executions = int(
        coverage_gate["expected_isolated_execution_count"]
    )
    if len(rows) != expected_executions:
        errors.append(
            f"isolated execution count={len(rows)}, "
            f"expected {expected_executions}"
        )
    unique_slots = {row.get("execution_slot_id", "") for row in rows}
    if len(unique_slots) != len(rows):
        errors.append("execution_slot_id is not unique")
    invalid_work_rows = [
        row.get("execution_slot_id", "")
        for row in rows
        if float(row.get("planned_work_units", 0) or 0) <= 0
    ]
    if invalid_work_rows:
        errors.append(
            "execution matrix has non-positive planned_work_units: "
            f"{invalid_work_rows[:5]}"
        )
    progress_plan = program.get("progress_plan") or {}
    matrix_work_units = sum(
        float(row.get("planned_work_units", 0) or 0)
        for row in rows
    )
    if abs(
        float(progress_plan.get("planned_work_units", 0))
        - matrix_work_units
    ) > 0.001:
        errors.append(
            "program progress plan does not match execution matrix work units"
        )
    if (
        progress_plan.get("eta_policy", {}).get(
            "blocked_batches_excluded_from_eta"
        )
        is not True
    ):
        errors.append("progress ETA must exclude blocked future batches")

    by_pair: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_pair.setdefault(row.get("pair_id", ""), []).append(row)
    planned_pairs = 0
    for pair_id, pair_rows in by_pair.items():
        variants = {row.get("variant", "") for row in pair_rows}
        contexts = {
            (
                row.get("dataset_profile_id", ""),
                row.get("param_json", ""),
                row.get("topology_id", ""),
                row.get("logical_question_id", ""),
            )
            for row in pair_rows
        }
        if {"mitigated", "stressed"} <= variants and len(contexts) == 1:
            planned_pairs += 1
        if not pair_id.startswith("pair-"):
            errors.append(f"invalid pair_id: {pair_id}")
    expected_pairs = int(coverage_gate["expected_planned_pair_count"])
    if planned_pairs != expected_pairs:
        errors.append(
            f"planned pair count={planned_pairs}, expected {expected_pairs}"
        )

    configuration_path = resolve(str(program["configuration_coverage"]))
    with configuration_path.open(newline="", encoding="utf-8") as handle:
        configurations = list(csv.DictReader(handle))
    expected_configurations = int(
        coverage_gate["expected_isolated_configuration_count"]
    )
    if len(configurations) != expected_configurations:
        errors.append(
            f"isolated configuration count={len(configurations)}, "
            f"expected {expected_configurations}"
        )
    if {
        row.get("condition_id", "") for row in configurations
    } != {
        row.get("condition_id", "") for row in rows
    }:
        errors.append("configuration coverage does not match execution matrix")
    axes = {
        "gac_finalization",
        "remote_path",
        "worker_data_skew",
        "repartition_join",
        "regional_finalization",
    }
    for axis in axes:
        axis_rows = [
            row
            for row in configurations
            if row.get("pressure_axis") == axis
        ]
        if not axis_rows:
            errors.append(f"configuration coverage missing axis: {axis}")
        if not any(
            row.get("is_negative_control", "").lower() == "true"
            for row in axis_rows
        ):
            errors.append(f"configuration coverage missing control: {axis}")
    network_blocks = {
        row.get("network_subblock", "")
        for row in configurations
        if row.get("pressure_axis") == "remote_path"
    }
    required_network_blocks = {
        str(value)
        for value in coverage_gate[
            "required_network_calibration_blocks"
        ]
    }
    if not required_network_blocks <= network_blocks:
        errors.append(
            "configuration coverage missing network calibration blocks: "
            f"{sorted(required_network_blocks - network_blocks)}"
        )

    audit_path = resolve(str(program["manifest_coverage_audit"]))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("status") != "ok":
        errors.append(
            "manifest coverage audit failed: "
            + "; ".join(audit.get("errors") or [])
        )
    if int(
        audit.get("isolated", {}).get("combined_configuration_count", -1)
    ) != 0:
        errors.append(
            "rendered isolated matrix must not claim combined configurations"
        )
    combined = (
        audit.get("prepared_not_yet_materialized", {})
        .get("batch-200-combined-holdout", {})
    )
    if int(combined.get("planned_configuration_count", 0)) != 60:
        errors.append("prepared combined holdout must contain 60 configurations")
    if int(combined.get("base_case_count", 0)) < int(
        coverage_gate["minimum_combined_base_cases"]
    ):
        errors.append("prepared combined holdout has too few base cases")
    if int(
        combined.get(
            "fully_one_at_a_time_mitigated_base_case_count",
            0,
        )
    ) < int(
        coverage_gate[
            "minimum_fully_one_at_a_time_mitigated_base_cases"
        ]
    ):
        errors.append(
            "prepared combined holdout lacks full one-at-a-time mitigations"
        )

    smoke = program.get("smoke_batch") or {}
    if int(smoke.get("execution_count", 0)) != 30:
        errors.append("smoke batch must contain exactly 30 executions")
    if len(smoke.get("segments") or []) != 5:
        errors.append("smoke batch must contain five pressure-axis segments")

    prepared = {item["batch_id"]: item for item in program.get("prepared_batches") or []}
    n3 = prepared.get("batch-300-n3-holdout", {})
    if not str(n3.get("status", "")).startswith("blocked"):
        errors.append("N3 holdout must remain blocked before three-region preflight")
    if int(n3.get("required_region_count", 0)) != 3:
        errors.append("N3 holdout must require exactly three regions")
    n3_worker_counts = n3.get("required_worker_count_by_region") or {}
    if set(n3_worker_counts) != {"eu", "us", "apac"}:
        errors.append("N3 holdout lacks an explicit worker map for eu/us/apac")
    if any(int(value) < 2 for value in n3_worker_counts.values()):
        errors.append("N3 holdout requires at least two workers per region")
    if int(n3.get("planned_execution_count", 0)) != 96:
        errors.append("N3 holdout must contain exactly 96 frozen executions")
    if int(n3.get("planned_configuration_count", 0)) != 32:
        errors.append("N3 holdout must contain exactly 32 conditions")
    if program.get("execution_policy", {}).get("database_result_rows_stored") is not False:
        errors.append("database result row storage must be disabled")
    if program.get("execution_policy", {}).get("full_program_auto_run_forbidden") is not True:
        errors.append("full-program auto-run guard is missing")
    consolidation_policy = program.get("consolidation_policy") or {}
    if consolidation_policy.get("training_eligible_roles") != ["primary"]:
        errors.append("only primary rows may be training eligible")
    if consolidation_policy.get("unknown_batch_policy") != "reject":
        errors.append("unknown consolidation batches must be rejected")
    if (
        consolidation_policy.get("duplicate_primary_slot_policy")
        != "reject"
    ):
        errors.append("duplicate primary slots must be rejected")
    topology_policy = program.get("execution_topology_policy") or {}
    topology_generalization = topology_policy.get("topology_generalization") or {}
    topology_invariants = set(topology_generalization.get("invariants") or [])
    required_topology_invariants = {
        "one_query_run_id_per_global_sql_execution",
        "one_remote_edge_child_row_per_active_region",
        "one_region_child_row_per_active_region",
        "variable_worker_task_child_rows_are_allowed",
        "fixed_eu_us_model_columns_are_forbidden",
        "topology_snapshot_id_is_required",
        "execution_features_use_permutation_invariant_aggregations",
    }
    missing_topology_invariants = sorted(
        required_topology_invariants - topology_invariants
    )
    if missing_topology_invariants:
        errors.append(
            "topology generalization invariants missing: "
            f"{missing_topology_invariants}"
        )
    current_topology = (
        topology_generalization.get("current_reference_deployment") or {}
    )
    if int(current_topology.get("region_count", 0)) != 2:
        errors.append("current reference deployment must remain N=2")
    if current_topology.get("worker_count_by_region") != {"eu": 2, "us": 2}:
        errors.append("current N=2 worker map must record two workers per region")
    target_policy = topology_policy.get("target_definition_policy") or {}
    if target_policy.get("primary_target_scope") != "global_query":
        errors.append("primary mitigation target scope must be global_query")
    if (
        target_policy.get("direct_region_targets_must_not_enter_primary_regressors")
        is not True
    ):
        errors.append("direct regional targets are not excluded from primary regressors")
    single_edge_gate = topology_policy.get("gac_single_edge_equivalence_gate") or {}
    if single_edge_gate.get("decision") != "GO_WITH_CONSTRAINTS":
        errors.append("GAC single-edge equivalence gate is not closed")
    lane_target_by_batch: dict[str, str] = {}
    for lane in (topology_policy.get("lanes") or {}).values():
        for batch_id in lane.get("batches") or []:
            lane_target_by_batch[str(batch_id)] = str(lane.get("target_group", ""))
    for batch in program.get("rendered_batches") or []:
        batch_id = str(batch.get("batch_id", ""))
        expected_target = lane_target_by_batch.get(batch_id, "")
        actual_targets = {
            str(group.get("target_group", ""))
            for group in batch.get("groups") or []
        }
        status = str(batch.get("status", ""))
        if (
            status == "ready"
            and expected_target
            and actual_targets
            and actual_targets != {expected_target}
        ):
            errors.append(
                f"{batch_id} ready target groups={sorted(actual_targets)}, "
                f"expected [{expected_target}]"
            )
        if batch_id in {"batch-130-repartition", "batch-140-regional"}:
            converted = actual_targets == {"analytics_clients"}
            blocked = status.startswith(
                "blocked_pending_gac_single_edge_template_conversion"
            )
            if not converted and not blocked:
                errors.append(
                    f"{batch_id} is neither converted to GAC single-edge nor blocked"
                )
    sentinel_policy = (
        program.get("manual_execution_protocol", {})
        .get("sentinel_policy", {})
    )
    if (
        sentinel_policy.get(
            "never_run_all_sentinels_as_one_terminal_block"
        )
        is not True
    ):
        errors.append("distributed sentinel execution policy is missing")

    contract_path = resolve(str(program["collection_contract"]))
    contract = load_yaml(contract_path)
    design_scope = contract.get("design_scope") or {}
    if design_scope.get("model_agnostic") is not True:
        errors.append("collection contract must remain model-agnostic")
    if design_scope.get("feature_set_agnostic") is not True:
        errors.append("collection contract must remain feature-set-agnostic")
    if design_scope.get("target_agnostic") is not False:
        errors.append("collection contract must not claim target-agnostic design")
    evidence_roles = (
        contract.get("future_derived_value_provenance", {})
        .get("evidence_roles", {})
    )
    expected_roles = {
        "label_only",
        "model_eligible",
        "shared_descriptive",
    }
    if set(evidence_roles) != expected_roles:
        errors.append("target-specific evidence role contract is incomplete")

    report = {
        "program_id": program.get("program_id", ""),
        "status": "ok" if not errors else "failed",
        "isolated_execution_count": len(rows),
        "planned_pair_count": planned_pairs,
        "isolated_configuration_count": len(configurations),
        "network_calibration_blocks": sorted(
            network_blocks & required_network_blocks
        ),
        "manifest_coverage_audit_status": audit.get("status", ""),
        "smoke_execution_count": int(smoke.get("execution_count", 0)),
        "rendered_batch_count": len(program.get("rendered_batches") or []),
        "prepared_batch_count": len(program.get("prepared_batches") or []),
        "errors": errors,
    }
    out_path = (
        args.out.resolve()
        if args.out
        else root / "collection_validation_report.json"
    )
    out_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(out_path)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
