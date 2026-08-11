"""Offline contracts for the pressure feedback-loop experiment.

The module deliberately has no database or infrastructure entry point.  It
validates frozen manifests, builds relative profiles from already extracted
feature rows, validates append-only decision logs, and renders a dry-run plan.
"""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from master_regimes.temporal_contract import (
    validate_cutoff_against_contract,
    validate_dataset_time_contract,
)

DOMAIN_IDS = (
    "remote_fdw_path",
    "regional_reduction",
    "gac_finalization",
    "imbalance",
    "disk_spill",
    "repartition_locality",
)

IDENTITY_MODES = (
    "same_normalized_sql",
    "same_sql_declared_intervention",
    "manual_logical_question_link",
)

OUTCOME_LABELS = {"positive", "negative", "mixed", "indeterminate"}
ALLOWED_DIRECTIONS = {
    "increase_more_pressure_evidence",
    "decrease_more_pressure_evidence",
    "presence_more_pressure_evidence",
    "contextual_not_aggregated",
}
FORBIDDEN_MUTATIONS = {
    "dataset_reload",
    "shard_movement",
    "new_colocation",
    "index_build",
    "destructive_ddl",
}
FORBIDDEN_DECISION_FIELDS = {
    "actual_outcome",
    "delta_outcome",
    "outcome_label",
    "result_after",
    "target_state_id",
}

AUTHORITATIVE_RQS = (
    "Koji normalizovani pokazatelji nakon izvršavanja najdosljednije opisuju "
    "režime izvršavanja globalnih analitičkih SQL upita pri promjeni veličine skupa "
    "podataka, WAN profila, profila neravnomjernosti rada i konfiguracijskih "
    "parametara?",
    "Može li neizrazito grupisanje nad normalizovanim mjernim pokazateljima "
    "izdvojiti interpretabilne režime izvršavanja globalnih analitičkih SQL upita?",
    "Da li raspodijeljeni stepen pripadnosti režimima bolje opisuje mješovite "
    "slučajeve izvršavanja od tvrdog dodjeljivanja jednom režimu?",
    "Koji pokazatelji najviše doprinose razlikovanju dobijenih režima i kako "
    "se ti režimi mogu povezati sa arhitektonskim tumačenjima?",
)

AUTHORITATIVE_HYPOTHESES = (
    "Relativni i normalizovani pokazatelji, kao što su udjeli vremena "
    "izvršavanja, faktor redukcije podataka (DRF), globalni priliv rezultata, faktor "
    "neravnomjernosti rada i spill signal, daju interpretabilnije režime od "
    "apsolutnih metrika kao što su ukupno vrijeme izvršavanja ili apsolutni broj "
    "prenesenih redova.",
    "Neizrazito grupisanje bolje opisuje mješovite režime izvršavanja od "
    "tvrdog grupisanja, jer omogućava da jedno izvršenje SQL upita bude opisano "
    "raspodijeljenim stepenom pripadnosti režimima.",
    "Slični režimi izvršavanja pojavljuju se pri kontrolisanoj promjeni "
    "veličine skupa podataka, WAN profila i profila neravnomjernosti rada, što "
    "ukazuje da režimi nisu samo artefakt jedne eksperimentalne konfiguracije.",
    "U scenarijima sa regionalnom neravnomjernošću rada ili nekolociranim "
    "spajanjima tabela, kompaktan WAN izlaz nije dovoljan indikator ukupnog ponašanja "
    "SQL upita, jer regionalna obrada ili premještanje podataka mogu ostati dominantni "
    "faktori režima izvršavanja.",
)


class ContractError(ValueError):
    """Raised when a frozen feedback-loop contract is invalid."""


def _normalized_prose(value: str) -> str:
    value = re.sub(r"\\cite\{[^}]+\}", "", value)
    value = " ".join(value.split())
    return re.sub(r"\s+([.,;:!?])", r"\1", value)


def validate_authoritative_rq_h_text(text: str) -> list[str]:
    """Ensure a document contains the fixed application formulations verbatim."""

    normalized = _normalized_prose(text)
    errors: list[str] = []
    for index, formulation in enumerate(AUTHORITATIVE_RQS, start=1):
        if _normalized_prose(formulation) not in normalized:
            errors.append(f"missing or changed authoritative RQ{index}")
    for index, formulation in enumerate(AUTHORITATIVE_HYPOTHESES, start=1):
        if _normalized_prose(formulation) not in normalized:
            errors.append(f"missing or changed authoritative H{index}")
    return errors


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ContractError(f"{path} must contain a YAML mapping")
    return data


def _numeric(values: Iterable[Any]) -> list[float]:
    result: list[float] = []
    for value in values:
        if value is None or value == "":
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            result.append(numeric)
    return result


def robust_center(values: Iterable[Any]) -> float | None:
    """Return the median of finite values, preserving unavailable evidence."""

    numeric = _numeric(values)
    return statistics.median(numeric) if numeric else None


def robust_scale(values: Iterable[Any], *, floor: float = 1e-9) -> float | None:
    """Return a MAD scale for local uncertainty, never a global threshold."""

    numeric = _numeric(values)
    if not numeric:
        return None
    center = statistics.median(numeric)
    mad = statistics.median(abs(value - center) for value in numeric)
    return max(1.4826 * mad, floor)


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    if not values or len(values) != len(weights):
        raise ContractError("weighted_median requires equally sized non-empty inputs")
    ordered = sorted(zip(values, weights, strict=True), key=lambda item: item[0])
    total = sum(max(weight, 0.0) for _, weight in ordered)
    if total <= 0:
        raise ContractError("weighted_median requires a positive total weight")
    threshold = total / 2.0
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += max(weight, 0.0)
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def directed_relative_change(
    current: float,
    reference: float,
    *,
    direction: str,
    local_scale: float,
) -> float | None:
    """Compute a bounded, signed local change without corpus-wide cutoffs.

    The symmetric denominator handles zero-valued signals and keeps the result
    bounded. Positive values always mean *more evidence* in the named domain;
    they do not mean a proven cause or a universally severe condition.
    """

    if direction == "contextual_not_aggregated":
        return None
    sign = -1.0 if direction == "decrease_more_pressure_evidence" else 1.0
    denominator = abs(current) + abs(reference) + max(local_scale, 1e-12)
    return sign * 2.0 * (current - reference) / denominator


def build_domain_view(
    domain: Mapping[str, Any],
    current_repetitions: Sequence[Mapping[str, Any]],
    reference_repetitions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one auditable domain coordinate and all component deltas."""

    components: list[dict[str, Any]] = []
    coordinate_values: list[float] = []
    coordinate_weights: list[float] = []
    positive = 0
    negative = 0

    for feature in domain["features"]:
        feature_id = feature["id"]
        current_values = [row.get(feature_id) for row in current_repetitions]
        reference_values = [row.get(feature_id) for row in reference_repetitions]
        current = robust_center(current_values)
        reference = robust_center(reference_values)
        status = "observed"
        delta: float | None = None
        if current is None or reference is None:
            status = "unavailable"
        else:
            pooled = [*current_values, *reference_values]
            scale = robust_scale(pooled, floor=float(feature.get("scale_floor", 1e-9)))
            assert scale is not None
            delta = directed_relative_change(
                current,
                reference,
                direction=feature["direction"],
                local_scale=scale,
            )
            if delta is None:
                status = "contextual"
            elif feature.get("aggregate", True):
                coordinate_values.append(delta)
                coordinate_weights.append(float(feature.get("weight", 1.0)))
                positive += delta > 0
                negative += delta < 0
        components.append(
            {
                "feature_id": feature_id,
                "current_raw_median": current,
                "reference_raw_median": reference,
                "relative_change": delta,
                "status": status,
                "direction": feature["direction"],
            }
        )

    required = int(domain.get("minimum_aggregated_components", 1))
    coordinate = (
        weighted_median(coordinate_values, coordinate_weights)
        if len(coordinate_values) >= required
        else None
    )
    return {
        "domain_id": domain["id"],
        "relative_pressure_evidence": coordinate,
        "status": "available" if coordinate is not None else "insufficient_evidence",
        "available_component_count": len(coordinate_values),
        "component_count": len(components),
        "conflicting_component_signs": positive > 0 and negative > 0,
        "positive_component_count": positive,
        "negative_component_count": negative,
        "components": components,
    }


def build_relative_profile(
    manifest: Mapping[str, Any],
    current_repetitions: Sequence[Mapping[str, Any]],
    references: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Build origin, previous-state and prior-history six-domain views."""

    domains = manifest["domains"]
    views: dict[str, Any] = {}
    for reference_name in (
        "trajectory_origin",
        "previous_accepted_state",
        "prior_logical_question_history",
    ):
        rows = references.get(reference_name, ())
        if not rows:
            views[reference_name] = {
                "status": "insufficient_history",
                "coordinates": [],
            }
            continue
        coordinates = [build_domain_view(domain, current_repetitions, rows) for domain in domains]
        views[reference_name] = {"status": "available", "coordinates": coordinates}
    return {"contract_version": manifest["contract_version"], "views": views}


def validate_pressure_domain_manifest(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    domains = manifest.get("domains")
    if not isinstance(domains, list):
        return ["domains must be a list"]
    ids = tuple(domain.get("id") for domain in domains)
    if ids != DOMAIN_IDS:
        errors.append(f"domain order must be exactly {DOMAIN_IDS}, got {ids}")
    if manifest.get("universal_high_low_thresholds") is not False:
        errors.append("universal_high_low_thresholds must be false")
    references = manifest.get("relative_references", [])
    expected_references = {
        "trajectory_origin",
        "previous_accepted_state",
        "prior_logical_question_history",
    }
    if set(references) != expected_references:
        errors.append("all three required relative references must be declared")
    for domain in domains:
        if not domain.get("display_name") or not domain.get("rationale"):
            errors.append(f"{domain.get('id')}: display_name and rationale are required")
        features = domain.get("features")
        if not isinstance(features, list) or not features:
            errors.append(f"{domain.get('id')}: at least one feature is required")
            continue
        for feature in features:
            feature_id = feature.get("id", "<missing>")
            for field in ("source", "direction", "na_rule", "relative_comparison", "rationale"):
                if not feature.get(field):
                    errors.append(f"{domain.get('id')}.{feature_id}: missing {field}")
            if feature.get("direction") not in ALLOWED_DIRECTIONS:
                errors.append(f"{domain.get('id')}.{feature_id}: invalid direction")
    return errors


def validate_intervention_catalog(catalog: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    forbidden = set(catalog.get("forbidden_mutations", []))
    if forbidden != FORBIDDEN_MUTATIONS:
        errors.append("forbidden mutation set is incomplete or changed")
    actions = catalog.get("interventions")
    if not isinstance(actions, list) or not actions:
        return [*errors, "interventions must be a non-empty list"]
    seen: set[str] = set()
    for action in actions:
        action_id = str(action.get("id", ""))
        if not action_id or action_id in seen:
            errors.append(f"duplicate or missing action id: {action_id!r}")
        seen.add(action_id)
        for field in (
            "layer",
            "expected_mechanism",
            "relevant_domains",
            "apply",
            "rollback",
            "applicability",
            "not_applicable_when",
        ):
            if not action.get(field):
                errors.append(f"{action_id}: missing {field}")
        for phase in ("apply", "rollback"):
            spec = action.get(phase) or {}
            if not spec.get("command") or not spec.get("verify_command"):
                errors.append(f"{action_id}: {phase} needs command and verify_command")
        if action.get("requires_dataset_reload"):
            errors.append(f"{action_id}: dataset reload is forbidden")
        if action.get("changes_colocation") or action.get("changes_shard_placement"):
            errors.append(f"{action_id}: topology/data placement mutation is forbidden")
        unknown_domains = set(action.get("relevant_domains", [])) - set(DOMAIN_IDS)
        if unknown_domains:
            errors.append(f"{action_id}: unknown domains {sorted(unknown_domains)}")
    return errors


def validate_query_trajectory_manifest(
    manifest: Mapping[str, Any], catalog: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    if manifest.get("automatic_sql_semantic_similarity") is not False:
        errors.append("automatic SQL semantic similarity must be disabled")
    if tuple(manifest.get("identity_modes", ())) != IDENTITY_MODES:
        errors.append("the three identity modes must remain ordered and explicit")
    experiment = manifest.get("experiment", {})
    if experiment.get("dataset_reload_allowed") is not False:
        errors.append("dataset reload must be forbidden")
    if experiment.get("colocation_change_allowed") is not False:
        errors.append("colocation changes must be forbidden")
    if experiment.get("shard_placement_change_allowed") is not False:
        errors.append("shard placement changes must be forbidden")
    time_contract = manifest.get("dataset_time_contract")
    if not isinstance(time_contract, Mapping):
        errors.append("dataset_time_contract is required")
        time_contract = {}
    else:
        errors.extend(validate_dataset_time_contract(time_contract))
    trajectories = manifest.get("trajectories")
    if not isinstance(trajectories, list) or len(trajectories) != 3:
        return [*errors, "exactly three trajectories are required"]
    shapes = {item.get("physical_shape") for item in trajectories}
    expected_shapes = {"aggregate_full_flow", "join_pushdown", "sort_order_topk_window"}
    if shapes != expected_shapes:
        errors.append(f"physical shapes must be {sorted(expected_shapes)}")
    action_ids = {item["id"] for item in catalog["interventions"]}
    for trajectory in trajectories:
        if not trajectory.get("logical_question_id") or not trajectory.get("baseline_template_id"):
            errors.append(f"{trajectory.get('id')}: identity and baseline template are required")
        if not trajectory.get("result_contract"):
            errors.append(f"{trajectory.get('id')}: result_contract is required")
        unknown = set(trajectory.get("allowed_actions", [])) - action_ids
        if unknown:
            errors.append(f"{trajectory.get('id')}: unknown actions {sorted(unknown)}")
        cutoff_ts = trajectory.get("parameter_bindings", {}).get("cutoff_ts")
        if cutoff_ts and time_contract:
            errors.extend(
                f"{trajectory.get('id')}: {error}"
                for error in validate_cutoff_against_contract(str(cutoff_ts), time_contract)
            )
    return errors


def render_dry_run_plan(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    experiment = manifest["experiment"]
    repeats = int(experiment["repetitions_per_state"])
    expected_steps = int(experiment["expected_adaptive_steps"])
    max_steps = int(experiment["maximum_adaptive_steps"])
    timeout = int(experiment["hard_timeout_seconds_per_execution"])
    rows: list[dict[str, Any]] = []
    global_index = 0
    for trajectory in manifest["trajectories"]:
        for step in range(0, max_steps + 1):
            for repeat in range(1, repeats + 1):
                global_index += 1
                rows.append(
                    {
                        "global_slot": global_index,
                        "trajectory_id": trajectory["id"],
                        "logical_question_id": trajectory["logical_question_id"],
                        "physical_shape": trajectory["physical_shape"],
                        "step_index": step,
                        "repeat_index": repeat,
                        "slot_role": "origin_baseline" if step == 0 else "adaptive_state",
                        "action_binding": (
                            "none" if step == 0 else "decision_log_action_locked_before_execution"
                        ),
                        "included_in_expected_count": step <= expected_steps,
                        "included_in_maximum_count": True,
                        "requires_pre_outcome_decision": step > 0,
                        "dataset_binding": trajectory["dataset_binding"],
                        "topology_binding": trajectory["topology_binding"],
                        "hard_timeout_seconds": timeout,
                        "live_execution": False,
                    }
                )
    return rows


def write_dry_run_plan(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    if not rows:
        raise ContractError("dry-run plan has no rows")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate_dry_run_plan(
    rows: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    experiment = manifest["experiment"]
    expected_count = int(experiment["expected_execution_count"])
    maximum_count = int(experiment["maximum_execution_count"])
    observed_expected = sum(
        str(row["included_in_expected_count"]).lower() == "true" for row in rows
    )
    if len(rows) != maximum_count:
        errors.append(f"maximum execution count is {len(rows)}, expected {maximum_count}")
    if observed_expected != expected_count:
        errors.append(f"expected execution count is {observed_expected}, expected {expected_count}")
    if any(str(row.get("live_execution")).lower() != "false" for row in rows):
        errors.append("dry-run plan must not contain live execution slots")
    if any(
        int(row["step_index"]) > 0 and str(row["requires_pre_outcome_decision"]).lower() != "true"
        for row in rows
    ):
        errors.append("every adaptive slot needs a pre-outcome decision")
    total_timeout = sum(int(row["hard_timeout_seconds"]) for row in rows)
    if total_timeout > int(experiment["maximum_query_runtime_budget_seconds"]):
        errors.append("query timeout sum exceeds the frozen maximum query budget")
    return errors


def _parse_time(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def validate_decision_log(records: Sequence[Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    decisions: dict[str, Mapping[str, Any]] = {}
    outcomes: set[str] = set()
    for index, record in enumerate(records, start=1):
        record_type = record.get("record_type")
        decision_id = str(record.get("decision_id", ""))
        if not decision_id:
            errors.append(f"record {index}: decision_id is required")
            continue
        if record_type == "decision":
            leaked = FORBIDDEN_DECISION_FIELDS.intersection(record)
            if leaked:
                errors.append(f"{decision_id}: decision leaks outcome fields {sorted(leaked)}")
            if decision_id in decisions:
                errors.append(f"{decision_id}: duplicate decision")
            decisions[decision_id] = record
            if record.get("status") != "locked_pre_execution":
                errors.append(f"{decision_id}: decision must be locked_pre_execution")
            cutoff = record.get("history_cutoff_utc")
            recorded = record.get("recorded_at_utc")
            if cutoff and recorded and _parse_time(str(cutoff)) > _parse_time(str(recorded)):
                errors.append(f"{decision_id}: history cutoff is in the future")
        elif record_type == "outcome":
            if decision_id not in decisions:
                errors.append(f"{decision_id}: outcome precedes its decision")
                continue
            if decision_id in outcomes:
                errors.append(f"{decision_id}: duplicate outcome")
            outcomes.add(decision_id)
            decision = decisions[decision_id]
            if _parse_time(str(record["recorded_at_utc"])) <= _parse_time(
                str(decision["recorded_at_utc"])
            ):
                errors.append(f"{decision_id}: outcome timestamp must follow decision")
            if record.get("outcome_label") not in OUTCOME_LABELS:
                errors.append(f"{decision_id}: invalid outcome label")
        else:
            errors.append(f"record {index}: unknown record_type {record_type!r}")
    return errors


def identity_matches(before: Mapping[str, Any], after: Mapping[str, Any], mode: str) -> bool:
    """Evaluate one of the three explicit identity contracts.

    The function intentionally contains no SQL embedding, parser similarity or
    inferred semantic matching.
    """

    if mode not in IDENTITY_MODES:
        raise ContractError(f"unknown identity mode: {mode}")
    same_dataset = bool(before.get("dataset_snapshot_id")) and before.get(
        "dataset_snapshot_id"
    ) == after.get("dataset_snapshot_id")
    if not same_dataset:
        return False
    if mode == "same_normalized_sql":
        return (
            bool(before.get("sql_normalized_hash"))
            and before.get("sql_normalized_hash") == after.get("sql_normalized_hash")
            and before.get("topology_id") == after.get("topology_id")
        )
    if mode == "same_sql_declared_intervention":
        return (
            bool(before.get("sql_normalized_hash"))
            and before.get("sql_normalized_hash") == after.get("sql_normalized_hash")
            and bool(before.get("logical_question_id"))
            and before.get("logical_question_id") == after.get("logical_question_id")
            and bool(before.get("pair_id"))
            and before.get("pair_id") == after.get("pair_id")
            and bool(after.get("action_id"))
        )
    return (
        bool(before.get("logical_question_id"))
        and before.get("logical_question_id") == after.get("logical_question_id")
        and bool(before.get("pair_id"))
        and before.get("pair_id") == after.get("pair_id")
        and bool(before.get("result_contract_id"))
        and before.get("result_contract_id") == after.get("result_contract_id")
    )


def results_equivalent(
    before: Mapping[str, Any], after: Mapping[str, Any], contract: Mapping[str, Any]
) -> bool:
    """Apply the frozen result-comparison contract to stored result evidence."""

    mode = contract["mode"]
    if mode == "ordered_sequence_hash":
        return bool(before.get("ordered_sha256")) and before.get("ordered_sha256") == after.get(
            "ordered_sha256"
        )
    if mode == "multiset_hash":
        return bool(before.get("multiset_sha256")) and before.get("multiset_sha256") == after.get(
            "multiset_sha256"
        )
    if mode == "typed_scalar_tolerance":
        before_value = float(before["value"])
        after_value = float(after["value"])
        return math.isclose(
            before_value,
            after_value,
            rel_tol=float(contract.get("relative_tolerance", 0.0)),
            abs_tol=float(contract.get("absolute_tolerance", 0.0)),
        )
    raise ContractError(f"unknown result contract mode: {mode}")


def classify_outcome(
    *,
    result_valid: bool,
    outcome_direction: str,
    adverse_domain_change: bool,
    beneficial_domain_change: bool,
    conflicting_domain_components: bool,
) -> str:
    """Classify an outcome after local noise handling has resolved direction."""

    if not result_valid or outcome_direction == "within_noise_or_unavailable":
        return "indeterminate"
    if conflicting_domain_components:
        return "mixed"
    if outcome_direction == "improved":
        return "mixed" if adverse_domain_change else "positive"
    if outcome_direction == "worsened":
        return "mixed" if beneficial_domain_change else "negative"
    raise ContractError(f"unknown outcome direction: {outcome_direction}")


def classify_end_to_end_effect(
    *, result_valid: bool, interval_low: float | None, interval_high: float | None
) -> str:
    """Classify runtime direction independently from the physical profile."""

    if not result_valid or interval_low is None or interval_high is None:
        return "indeterminate"
    if interval_low > 0:
        return "positive"
    if interval_high < 0:
        return "negative"
    return "no_material_change"


def classify_physical_transition(coordinates: Sequence[Mapping[str, Any]]) -> str:
    """Summarize domain movement without replacing component-level evidence."""

    available = [
        row
        for row in coordinates
        if row.get("relative_pressure_evidence") is not None
        and str(row.get("status")) not in {"unavailable", "insufficient_evidence"}
    ]
    if not available:
        return "unavailable"
    values = [float(row["relative_pressure_evidence"]) for row in available]
    changed = [value for value in values if abs(value) > 1.0e-9]
    if not changed or len(changed) == 1:
        return "sparse"
    has_conflict = any(bool(row.get("conflicting_component_signs")) for row in available)
    has_adverse = any(value > 0 for value in changed)
    has_favorable = any(value < 0 for value in changed)
    if has_conflict or (has_adverse and has_favorable):
        return "mixed"
    if has_favorable:
        return "predominantly_favorable"
    return "predominantly_adverse"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ContractError(f"{path}:{line_number} must be a JSON object")
        records.append(value)
    return records
