#!/usr/bin/env python3
"""Offline audit of rendered corpora and sweep execution contracts.

The script reads only the curated master-thesis-final package. It does not
connect to PostgreSQL, Terraform, Ansible, or any live host. Upstream source
files are cited in report.md; this validator checks the package that a reader
actually receives.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tarfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = Path(__file__).resolve().parent
CHECKS: list[dict[str, Any]] = []
CORPORA: dict[str, Any] = {}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(item) for item in value]
    return value


def as_int(value: str | int | None) -> int:
    if value in (None, ""):
        return 0
    return int(value)


def check(
    check_id: str,
    condition: bool,
    evidence: Any,
    *,
    severity: str = "error",
    note: str = "",
) -> None:
    CHECKS.append(
        {
            "id": check_id,
            "status": "PASS" if condition else ("WARN" if severity == "warning" else "FAIL"),
            "evidence": evidence,
            "note": note,
        }
    )


def all_rows(pattern: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(ROOT.glob(pattern)):
        rows.extend(read_csv(path))
    return rows


def contiguous(values: Iterable[str | int], start: int = 1) -> bool:
    ints = sorted(as_int(value) for value in values)
    return ints == list(range(start, start + len(ints)))


def catalog_rows(name: str) -> list[dict[str, str]]:
    return [row for row in QUERY_CATALOG if row["rendered_corpus"] == name]


def validate_catalog_hashes() -> None:
    missing: list[str] = []
    mismatched: list[str] = []
    for row in QUERY_CATALOG:
        path = ROOT / row["sql_path"]
        if not path.is_file():
            missing.append(row["sql_path"])
        elif sha256(path) != row["sql_sha256"]:
            mismatched.append(row["sql_path"])
    check(
        "catalog.sql_files_exist",
        not missing,
        {"catalog_rows": len(QUERY_CATALOG), "missing_count": len(missing), "examples": missing[:5]},
    )
    check(
        "catalog.sql_hashes_match",
        not mismatched,
        {"checked": len(QUERY_CATALOG) - len(missing), "mismatch_count": len(mismatched), "examples": mismatched[:5]},
    )


def validate_clean() -> None:
    rows = all_rows("artifacts/rendered-corpora/clean-run-v1/groups/*/instance_manifest.csv")
    paths = {row["rendered_sql_path"] for row in rows}
    groups = Counter(row["dataset_profile_id"] for row in rows)
    check("clean.execution_count", len(rows) == 1964, len(rows))
    check("clean.distinct_rendered_sql", len(paths) == 1964, len(paths))
    check("clean.single_execution_per_condition", all(row["repetition_index"] == "0" for row in rows), Counter(row["repetition_index"] for row in rows))
    check("clean.order_policy", all(row["order_policy"] == "deterministic_shuffle" for row in rows), Counter(row["order_policy"] for row in rows))
    check("clean.shuffle_seed", all(row["shuffle_seed"] == "20260626" for row in rows), Counter(row["shuffle_seed"] for row in rows))
    check("clean.catalog_count", len(catalog_rows("clean-run-v1")) == 1964, len(catalog_rows("clean-run-v1")))

    archive = ROOT / "artifacts/logical-indexes/clean-run-v1.tar.gz"
    logical_rows = -1
    logical_manifest: dict[str, Any] = {}
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        query_members = [item for item in members if item.isfile() and item.name.endswith("/query_runs.csv")]
        manifest_members = [item for item in members if item.isfile() and item.name.endswith("/logical_run_index_manifest.json")]
        if len(query_members) == 1:
            extracted = bundle.extractfile(query_members[0])
            assert extracted is not None
            logical_rows = sum(1 for _ in csv.DictReader(io.TextIOWrapper(extracted, encoding="utf-8")))
        if len(manifest_members) == 1:
            extracted = bundle.extractfile(manifest_members[0])
            assert extracted is not None
            logical_manifest = json.load(extracted)
    check("clean.logical_index_single_table", logical_rows == 1964, {"query_runs": logical_rows})
    manifest_counts = {
        key: logical_manifest.get(key)
        for key in ("attempt_count", "group_attempt_count", "needs_rerun_count", "query_attempt_count", "resolved_query_count")
    }
    check(
        "clean.logical_index_resolution",
        manifest_counts.get("query_attempt_count") == 1964
        and manifest_counts.get("resolved_query_count") == 1964
        and manifest_counts.get("needs_rerun_count") == 0,
        manifest_counts,
    )

    temporal = TEMPORAL["legacy_fcm_corpus"]
    check("clean.temporal_audit_count", temporal["execution_count"] == 1964, temporal["execution_count"])
    check(
        "clean.legacy_moving_time_detected",
        temporal["sql_temporal_modes"] == {"dynamic_current_date": 240, "dynamic_now": 1718, "no_wall_clock": 6},
        temporal["sql_temporal_modes"],
        severity="warning",
        note="The archived F19 and F21 analyses are internally auditable, but rerunning their SQL today is not temporally equivalent.",
    )
    CORPORA["clean_fcm"] = {
        "rendered_executions": len(rows),
        "rendered_sql_files": len(paths),
        "logical_index_rows": logical_rows,
        "dataset_split": groups,
        "order": "deterministic_shuffle(seed=20260626)",
        "repetitions_per_condition": 1,
        "temporal_contract": "legacy moving wall clock; eight sweeps regenerated their datasets immediately before collection",
        "max_sweep_lag_hours": temporal["maximum_lag_hours"],
    }


def validate_pressure() -> None:
    base = ROOT / "artifacts/rendered-corpora/pressure-raw-v1"
    rows = read_csv(base / "execution_matrix.csv")
    conditions: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        conditions[row["condition_id"]].append(row)
    paths = {row["rendered_sql_path"] for row in rows}
    pair_rows = read_csv(base / "pair_coverage.csv")
    check("pressure.execution_count", len(rows) == 2607, len(rows))
    check("pressure.condition_count", len(conditions) == 869, len(conditions))
    check("pressure.three_repetitions", all({as_int(row["repetition_index"]) for row in group} == {0, 1, 2} for group in conditions.values()), {"condition_count": len(conditions)})
    check("pressure.execution_slot_unique", len({row["execution_slot_id"] for row in rows}) == 2607, len({row["execution_slot_id"] for row in rows}))
    check("pressure.rendered_sql_file_count", len(paths) == 799, len(paths))
    check("pressure.catalog_count", len(catalog_rows("pressure-raw-v1")) == 799, len(catalog_rows("pressure-raw-v1")))
    check("pressure.pair_count", len(pair_rows) == 418, len(pair_rows))
    pair_shapes = Counter((row["condition_count"], row["physical_execution_count"]) for row in pair_rows)
    check(
        "pressure.pair_contract",
        pair_shapes == {("2", "6"): 385, ("3", "9"): 33}
        and all(row["structurally_complete_stressed_mitigated_pair"] == "True" for row in pair_rows),
        pair_shapes,
        note="All 418 groups contain the stressed/mitigated contrast; 33 additionally retain an intermediate condition.",
    )
    fixed_as_of = 0
    for row in rows:
        try:
            if json.loads(row["param_json"]).get("as_of_unix") == 1782864000:
                fixed_as_of += 1
        except json.JSONDecodeError:
            pass
    check("pressure.fixed_as_of_parameter", fixed_as_of == 2607, {"matching_rows": fixed_as_of, "expected": 2607})

    standard_lanes: dict[str, list[str]] = defaultdict(list)
    placement_lanes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        if row["backend"] == "placement_aware_worker":
            placement_lanes[(row["segment_id"], row["state_id"])].append(row["run_order"])
        else:
            standard_lanes[row["group_id"]].append(row["run_order"])
    check("pressure.standard_lane_order", all(contiguous(values) for values in standard_lanes.values()), {"lane_count": len(standard_lanes)})
    check("pressure.placement_lane_order", len(placement_lanes) == 14 and all(len(values) == 30 and contiguous(values) for values in placement_lanes.values()), {"lane_count": len(placement_lanes), "sizes": sorted(Counter(len(v) for v in placement_lanes.values()).items())})

    summary = read_json(base / "program_summary.json")
    check(
        "pressure.program_summary",
        summary["distinct_configuration_count"] == 869
        and summary["physical_execution_count"] == 2607
        and summary["planned_counterfactual_pair_count"] == 418,
        {key: summary[key] for key in ("distinct_configuration_count", "physical_execution_count", "planned_counterfactual_pair_count", "distinct_sql_shape_count")},
    )
    check(
        "pressure.signature_scope",
        summary["execution_optimization"]["result_signature_scope"] == "first_repetition_per_condition"
        and summary["execution_optimization"]["stream_only_result_signature_query_count"] == 869,
        summary["execution_optimization"],
    )
    consolidation = read_json(ROOT / "artifacts/results/pressure-actionability-v1/corpus/consolidation_manifest.json")
    check(
        "pressure.canonical_attempt_resolution",
        consolidation["gate"] == "GO"
        and consolidation["attempt_candidate_count"] == 3027
        and consolidation["resolved_primary_slot_count"] == 2607
        and consolidation["missing_primary_slot_count"] == 0
        and consolidation["duplicate_issue_count"] == 0,
        {key: consolidation[key] for key in ("gate", "attempt_candidate_count", "resolved_primary_slot_count", "excluded_execution_count", "identity_alias_count", "missing_primary_slot_count", "duplicate_issue_count")},
    )
    temporal = TEMPORAL["wide_intervention_program"]
    check("pressure.temporal_pair_split", temporal["substantive_frozen_or_time_independent_pairs"] == 397 and temporal["dynamic_empty_negative_control_pairs"] == 21, {"substantive": temporal["substantive_frozen_or_time_independent_pairs"], "dynamic_empty_controls": temporal["dynamic_empty_negative_control_pairs"]})
    CORPORA["pressure_869x3"] = {
        "conditions": len(conditions),
        "physical_executions": len(rows),
        "counterfactual_pairs": len(pair_rows),
        "rendered_sql_files": len(paths),
        "backend_counts": Counter(row["backend"] for row in rows),
        "axis_counts": Counter(row["pressure_axis"] for row in rows),
        "dataset_profile_count": len({row["dataset_profile_id"] for row in rows}),
        "order": "deterministic interleaving for standard lanes; explicit 30-slot placement-state lanes for skew interventions",
        "attempt_policy": consolidation["training_policy"]["attempt_resolution"],
        "attempt_candidates": consolidation["attempt_candidate_count"],
        "temporal_contract": "397 frozen/time-independent substantive pairs; 21 current_date empty-result negative controls",
    }


def query_number(row: dict[str, str]) -> int:
    match = re.search(r"q(\d+)", row.get("component_match_id", "") or row.get("instance_id", ""))
    if not match:
        raise ValueError(f"Cannot derive query number from {row}")
    return int(match.group(1))


def validate_dba() -> None:
    rows = all_rows("artifacts/rendered-corpora/dba-local-memory-v1/groups/*/instance_manifest.csv")
    paths = {row["rendered_sql_path"] for row in rows}
    conditions: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        conditions[row["condition_id"]].append(row)
    per_query_conditions = Counter(query_number(group[0]) for group in conditions.values())
    repetition_contract_ok = all(
        len(group) == ((query_number(group[0]) - 1) % 5 + 1)
        and {as_int(row["repetition_index"]) for row in group} == set(range((query_number(group[0]) - 1) % 5 + 1))
        for group in conditions.values()
    )
    lanes: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        lanes[row["dataset_profile_id"]].append(row["run_order"])
    check("dba.execution_count", len(rows) == 180, len(rows))
    check("dba.condition_count", len(conditions) == 60, len(conditions))
    check("dba.rendered_sql_file_count", len(paths) == 60, len(paths))
    check("dba.catalog_count", len(catalog_rows("dba-local-memory-v1")) == 60, len(catalog_rows("dba-local-memory-v1")))
    check("dba.query_shapes", len(per_query_conditions) == 15 and set(per_query_conditions.values()) == {4}, per_query_conditions)
    check("dba.temporal_appearance_contract", repetition_contract_ok, {"appearance_pattern": [((number - 1) % 5 + 1) for number in range(1, 16)]})
    check("dba.group_order", len(lanes) == 4 and all(contiguous(values) for values in lanes.values()), {key: len(value) for key, value in lanes.items()})
    provenance = read_csv(ROOT / "releases/consolidated-evaluation-v1/dataset_provenance.csv")
    dba_provenance = [row for row in provenance if row.get("dataset_id") == "final_dba_panel" or "DBA" in row.get("dataset_name", "")]
    check("dba.provenance_present", bool(dba_provenance), {"matching_rows": len(dba_provenance)})
    CORPORA["dba_180"] = {
        "query_shapes": 15,
        "conditions": len(conditions),
        "decision_points": sum((number - 1) % 5 + 1 for number in range(1, 16)),
        "physical_executions": len(rows),
        "rendered_sql_files": len(paths),
        "order": "deterministic_interleaved_shuffle(seed=20260805) within four dataset groups",
        "sql_reuse": "one rendered SQL file per condition is referenced by every temporal repetition; runtime/network treatments are applied outside SQL",
    }


def validate_n3() -> None:
    base = ROOT / "artifacts/rendered-corpora/n3-topology-memory-v1"
    manifest = read_json(base / "experiment_manifest.json")
    expected = {block["block_id"]: block["expected_executions"] for block in manifest["blocks"]}
    observed: dict[str, int] = {}
    seeds: dict[str, list[str]] = {}
    for block, expected_count in expected.items():
        rows = all_rows(f"artifacts/rendered-corpora/n3-topology-memory-v1/rendered/{block}/groups/*/instance_manifest.csv")
        observed[block] = len(rows)
        seeds[block] = sorted({row["shuffle_seed"] for row in rows})
        lanes: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            lanes[row["dataset_profile_id"]].append(row["run_order"])
        check(f"n3.{block}.count", len(rows) == expected_count, {"observed": len(rows), "expected": expected_count})
        check(f"n3.{block}.single_execution", all(row["repetition_index"] == "0" for row in rows), Counter(row["repetition_index"] for row in rows))
        check(f"n3.{block}.group_order", all(contiguous(values) for values in lanes.values()), {key: len(value) for key, value in lanes.items()})
    check("n3.total_count", sum(observed.values()) == 180 and manifest["total_execution_count"] == 180, {"observed": observed, "manifest_total": manifest["total_execution_count"]})
    check("n3.catalog_count", len(catalog_rows("n3-topology-memory-v1")) == 180, len(catalog_rows("n3-topology-memory-v1")))
    CORPORA["controlled_n2_n3_180"] = {
        "scenario_count": manifest["scenario_count"],
        "action_count": manifest["action_count"],
        "block_counts": observed,
        "physical_executions": sum(observed.values()),
        "shuffle_seeds": seeds,
        "repetitions_per_condition": 1,
        "interpretation": "each 60-execution round is 15 scenarios x baseline/three actions, not repeated measurements",
    }


def validate_confirmatory() -> None:
    rows = all_rows("artifacts/rendered-corpora/confirmatory-action-replication-v1/groups/*/instance_manifest.csv")
    conditions: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        conditions[row["condition_id"]].append(row)
    paths = {row["rendered_sql_path"] for row in rows}
    check("confirmatory.execution_count", len(rows) == 300, len(rows))
    check("confirmatory.condition_count", len(conditions) == 60, len(conditions))
    check("confirmatory.five_repetitions", all(len(group) == 5 and {as_int(row["repetition_index"]) for row in group} == {0, 1, 2, 3, 4} for group in conditions.values()), {"condition_count": len(conditions)})
    check("confirmatory.rendered_sql_file_count", len(paths) == 60, len(paths))
    check("confirmatory.catalog_count", len(catalog_rows("confirmatory-action-replication-v1")) == 60, len(catalog_rows("confirmatory-action-replication-v1")))
    check("confirmatory.total_order", contiguous(row["run_order"] for row in rows), {"min": min(as_int(row["run_order"]) for row in rows), "max": max(as_int(row["run_order"]) for row in rows)})
    design = read_json(ROOT / "releases/confirmatory-action-replication-v1/design_validation.json")
    collection = read_json(ROOT / "releases/confirmatory-action-replication-v1/collection_validation.json")
    check("confirmatory.design_validation", design["status"] == "PASS" and all(design["checks"].values()), design)
    check("confirmatory.collection_validation", collection["status"] == "PASS" and all(collection["checks"].values()), {"status": collection["status"], "counts": collection["counts"], "failed_checks": [key for key, value in collection["checks"].items() if not value]})
    position_counts = design["treatment_position_counts"]
    check("confirmatory.williams_balance", set(position_counts.values()) == {18, 19} and sum(position_counts.values()) == 300, position_counts)
    CORPORA["confirmatory_300"] = {
        "query_shapes": 15,
        "conditions": len(conditions),
        "repetitions_per_condition": 5,
        "physical_executions": len(rows),
        "rendered_sql_files": len(paths),
        "order": "locked explicit Williams schedule",
        "position_count_range": [min(position_counts.values()), max(position_counts.values())],
        "collection_validation_counts": collection["counts"],
    }


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_decision_log(path: Path, expected: int, prefix: str) -> None:
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    decisions = {entry["decision_id"]: entry for entry in entries if entry["record_type"] == "decision"}
    outcomes = {entry["decision_id"]: entry for entry in entries if entry["record_type"] == "outcome"}
    ordered = all(
        decision_id in outcomes
        and parse_time(decision["recorded_at_utc"]) < parse_time(outcomes[decision_id]["recorded_at_utc"])
        for decision_id, decision in decisions.items()
    )
    check(f"{prefix}.decision_count", len(decisions) == expected and len(outcomes) == expected, {"decisions": len(decisions), "outcomes": len(outcomes)})
    check(f"{prefix}.pre_outcome_order", ordered, {"matched_decisions": len(decisions)})


def validate_feedback() -> None:
    base = ROOT / "releases/feedback-loop-execution-v1"
    main = read_csv(base / "main/execution_manifest.csv")
    completion = read_json(base / "main/completion_manifest.json")
    final = read_json(base / "main/final_validation.json")
    phase_counts = Counter(row["phase"] for row in main)
    status_counts = Counter(row["status"] for row in main)
    check("feedback.main_total", len(main) == 85, len(main))
    check("feedback.main_phase_counts", phase_counts == {"A_smoke": 1, "B_origin": 15, "B_correctness_only": 5, "C_adaptive": 15, "D_rollback": 9, "E_frozen_replay": 40}, phase_counts)
    check("feedback.main_status_counts", status_counts == {"completed": 65, "superseded_invalid_configuration": 20} and all(row["execution_status"] == "completed" for row in main), status_counts)
    check("feedback.completion_manifest", completion["validation_status"] == "PASS" and completion["execution_counts"] == {"correctness_only_execution_count": 5, "instrumented_execution_count": 60, "superseded_instrumented_execution_count": 20, "total_execution_count": 85}, completion)
    check("feedback.final_validation", final["status"] == "PASS" and all(value["status"] == "PASS" for value in final["checks"].values()), final)
    validate_decision_log(base / "main/decision_log.jsonl", 5, "feedback.main")
    replay = [row for row in main if row["phase"] == "E_frozen_replay"]
    check("feedback.replay_split", Counter(row["status"] for row in replay) == {"completed": 20, "superseded_invalid_configuration": 20}, Counter(row["status"] for row in replay))

    aggregate_plan = read_csv(base / "aggregate-exact/frozen_execution_plan.csv")
    aggregate_states = read_csv(base / "aggregate-exact/trajectory_states.csv")
    check("feedback.aggregate_plan_count", len(aggregate_plan) == 25 and all(row["status"] == "completed" for row in aggregate_plan), {"rows": len(aggregate_plan), "states": Counter(row["state_id"] for row in aggregate_plan)})
    check("feedback.aggregate_state_repetitions", len(aggregate_states) == 5 and all(row["repetition_count"] == "5" for row in aggregate_states), {row["state_id"]: row["repetition_count"] for row in aggregate_states})
    validate_decision_log(base / "aggregate-exact/decision_log.jsonl", 3, "feedback.aggregate")
    check("feedback.catalog_sql_states", len(catalog_rows("feedback-loop-v1")) == 9, len(catalog_rows("feedback-loop-v1")))
    CORPORA["feedback_loop"] = {
        "main_manifest_rows": len(main),
        "canonical_instrumented_executions": completion["execution_counts"]["instrumented_execution_count"],
        "correctness_only_executions": completion["execution_counts"]["correctness_only_execution_count"],
        "superseded_replay_executions": completion["execution_counts"]["superseded_instrumented_execution_count"],
        "main_frozen_replay": {"canonical": 20, "superseded": 20},
        "aggregate_exact_executions": len(aggregate_plan),
        "canonical_sql_state_files": len(catalog_rows("feedback-loop-v1")),
        "decision_logs": {"main": 5, "aggregate_exact": 3},
        "temporal_contract": TEMPORAL["later_panels"]["feedback_loop"],
    }


def validate_portability() -> None:
    manifest_paths = list(ROOT.glob("artifacts/rendered-corpora/**/instance_manifest.csv"))
    absolute = 0
    total = 0
    examples: list[str] = []
    for path in manifest_paths:
        for row in read_csv(path):
            rendered = row.get("rendered_sql_path", "")
            if rendered:
                total += 1
                if Path(rendered).is_absolute():
                    absolute += 1
                    if len(examples) < 3:
                        examples.append(rendered)
    for row in read_csv(ROOT / "artifacts/rendered-corpora/pressure-raw-v1/execution_matrix.csv"):
        rendered = row.get("rendered_sql_path", "")
        total += 1
        if Path(rendered).is_absolute():
            absolute += 1
            if len(examples) < 3:
                examples.append(rendered)
    check(
        "package.rendered_paths_portable",
        absolute == 0,
        {"manifest_path_references": total, "absolute_paths": absolute, "examples": examples},
        severity="warning",
        note="SQL files are present and cataloged by package-relative paths, but original manifests need path rewriting before a live rerun.",
    )


LIMITATIONS = [
    {
        "id": "L1_path_rewrite",
        "statement": "Public manifests have no local home prefix, but some historical path fields retain their source-repository-relative generated layout. The query catalog is portable; a live rerun should regenerate manifests from the packaged corpus contract instead of treating archived path fields as executable inputs.",
    },
    {
        "id": "L2_no_database_snapshot",
        "statement": "The package contains dataset profiles, generator inputs, seeds and temporal anchors, but no database dump and no full row-level checksum after reload. Dataset identity is reproducible by construction rather than independently proven byte-for-byte after a fresh load.",
    },
    {
        "id": "L3_partial_raw_indexes",
        "statement": "The shared clean/F19-F21 corpus includes raw and logical index archives. Pressure, DBA, N2/N3, confirmatory and feedback-loop releases mainly contain rendered designs and consolidated validations; their complete raw query-run indexes or collection directories are not all packaged.",
    },
    {
        "id": "L4_historical_source_state",
        "statement": "Curated source snapshots are current package copies. Several run provenance records refer to older commits or dirty worktrees, so the exact historical executable source state is not embedded for every run.",
    },
    {
        "id": "L5_clean_temporal",
        "statement": "The shared legacy F19/F21 corpus used now()/current_date and cannot be rerun today as an identical temporal experiment. Its archived descriptive analyses remain internally usable under the documented short sweep-lag and no-time-cluster-association audits for both hard-label models.",
    },
    {
        "id": "L6_pressure_dynamic_controls",
        "statement": "Twenty-one pressure pairs use current_date and produced empty no-work controls. They validate collection and equivalence only, not intervention effectiveness; 397 substantive pairs use frozen or time-independent contracts.",
    },
    {
        "id": "L7_feedback_dataset_profile",
        "statement": "The aggregate exact feedback-loop addendum records base_time and audited counts, but not the exact locked dataset profile name, preventing guaranteed regeneration of that snapshot from the release alone.",
    },
    {
        "id": "L8_live_environment",
        "statement": "No credentials, Terraform state, provider account, generated Ansible inventory or live VPS snapshot is included. This audit proves offline design consistency, not current infrastructure deployability.",
    },
    {
        "id": "L9_timing_equivalence",
        "statement": "Even with identical SQL and generated data, exact plans and runtimes depend on PostgreSQL/Citus versions, statistics, cache state, VPS scheduling and emulated network state. The package supports design replay, not a guarantee of identical latency values.",
    },
]


def main() -> int:
    validate_catalog_hashes()
    validate_clean()
    validate_pressure()
    validate_dba()
    validate_n3()
    validate_confirmatory()
    validate_feedback()
    validate_portability()

    failures = [item for item in CHECKS if item["status"] == "FAIL"]
    warnings = [item for item in CHECKS if item["status"] == "WARN"]
    status = "FAIL" if failures else ("PASS_WITH_LIMITATIONS" if warnings or LIMITATIONS else "PASS")
    output = {
        "audit": {
            "id": "sweep-construction-reproducibility-audit-v1",
            "mode": "offline_read_only",
            "package_root": ".",
            "live_sql_executed": False,
            "upstream_repositories_modified": False,
            "status": status,
        },
        "summary": {
            "check_count": len(CHECKS),
            "pass_count": sum(item["status"] == "PASS" for item in CHECKS),
            "warning_count": len(warnings),
            "failure_count": len(failures),
            "catalog_sql_rows": len(QUERY_CATALOG),
        },
        "corpora": CORPORA,
        "checks": CHECKS,
        "limitations": LIMITATIONS,
    }
    output_path = OUT_DIR / "findings.json"
    output_path.write_text(json.dumps(json_ready(output), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{status}: {len(CHECKS)} checks, {len(failures)} failures, {len(warnings)} warnings")
    print(output_path)
    return 1 if failures else 0


QUERY_CATALOG = read_csv(ROOT / "reproducibility/query-catalog.csv")
TEMPORAL = read_json(ROOT / "releases/temporal-validity-audit-v1/temporal_validity_audit.json")


if __name__ == "__main__":
    raise SystemExit(main())
