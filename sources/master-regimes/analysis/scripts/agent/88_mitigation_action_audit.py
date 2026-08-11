#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGE = ROOT / "generated/pressure-raw-runs/_program/pressure-raw-v1"
DEFAULT_EDA = ROOT / "analysis/reports/pressure-raw-v1-exploratory"
DEFAULT_CONTRACT = ROOT / "configs/validation/mitigation_action_audit_v1.yml"
DEFAULT_OUT = ROOT / "analysis/reports/pressure-raw-v1-mitigation-action-audit"
DEFAULT_CORRECTNESS_RECOVERY = (
    ROOT / "analysis/reports/pressure-raw-v1-correctness-recovery"
)

CONFIG_FIELDS = (
    "template_id",
    "dataset_profile_id",
    "dataset_size_class",
    "runtime_config_id",
    "physical_strategy_id",
    "placement_state_id",
    "placement_action",
    "execution_strategy",
    "execution_scope",
    "target_scope",
    "work_mem",
    "regional_pg_options_json",
    "fetch_size",
    "configured_latency_ms",
    "configured_jitter_ms",
    "configured_loss_percent",
    "configured_bandwidth_mbit",
    "network_profile_id",
)
GAC_EXECUTION_STRATEGIES = {"fdw_raw", "multiregion_union", "etl_materialized"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit mitigation actions and counterfactual gain readiness."
    )
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--eda-dir", type=Path, default=DEFAULT_EDA)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--correctness-recovery-dir",
        type=Path,
        default=DEFAULT_CORRECTNESS_RECOVERY,
        help="Optional typed correctness recovery package used to resolve review pairs.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.replace({"": np.nan}), errors="coerce")


def unique_values(series: pd.Series) -> list[str]:
    return sorted({str(value) for value in series if str(value)})


def only_value(series: pd.Series, *, field: str, pair_id: str) -> str:
    values = unique_values(series)
    if len(values) != 1:
        raise ValueError(f"pair {pair_id} has {len(values)} values for {field}: {values}")
    return values[0]


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def variant_config(group: pd.DataFrame, variant: str) -> dict[str, list[str]]:
    source = group[group["variant"].eq(variant)]
    return {
        field: values
        for field in CONFIG_FIELDS
        if field in source.columns and (values := unique_values(source[field]))
    }


def infer_target_scope(group: pd.DataFrame) -> tuple[str, str, str]:
    observed = unique_values(group.get("target_scope", pd.Series(dtype=str)))
    if observed == ["global_query"]:
        return "global_query", "observed", "ok"
    if observed:
        return "|".join(observed), "observed", "scope_mismatch"
    coordinators = unique_values(group.get("coordinator_node", pd.Series(dtype=str)))
    strategies = set(unique_values(group.get("execution_strategy", pd.Series(dtype=str))))
    if (
        coordinators
        and all("analytics" in value or "gac" in value for value in coordinators)
        and strategies
        and strategies.issubset(GAC_EXECUTION_STRATEGIES)
    ):
        return "global_query", "inferred_from_gac_execution", "ok"
    return "unresolved", "unresolved", "scope_unresolved"


def load_execution_design(package_dir: Path) -> pd.DataFrame:
    training = read_csv(package_dir / "training_execution_view.csv")
    execution = read_csv(package_dir / "_index/execution_features.csv")
    observed_fields = [
        "query_run_id",
        "coordinator_node",
        "execution_strategy",
        "execution_scope",
        "target_scope",
        "target_metric",
        "work_mem",
        "regional_pg_options_json",
        "fetch_size",
        "configured_latency_ms",
        "configured_jitter_ms",
        "configured_loss_percent",
        "configured_bandwidth_mbit",
        "network_profile_id",
    ]
    observed = execution[
        [field for field in observed_fields if field in execution.columns]
    ].drop_duplicates("query_run_id")
    merged = training.merge(
        observed,
        on="query_run_id",
        how="left",
        validate="one_to_one",
        suffixes=("", "_observed"),
    )
    for field in observed_fields[1:]:
        observed_name = f"{field}_observed"
        if observed_name not in merged:
            continue
        if field not in merged:
            merged[field] = merged[observed_name]
        else:
            merged[field] = merged[field].where(merged[field].ne(""), merged[observed_name])
        merged = merged.drop(columns=observed_name)
    return merged


def build_pair_design(executions: pd.DataFrame) -> pd.DataFrame:
    source = executions[executions["variant"].isin(["stressed", "mitigated"])].copy()
    rows: list[dict[str, Any]] = []
    for pair_id, group in source.groupby("pair_id", sort=True):
        action = only_value(group["mitigation_action"], field="mitigation_action", pair_id=pair_id)
        pressure_axis = only_value(group["pressure_axis"], field="pressure_axis", pair_id=pair_id)
        role = only_value(group["intervention_role"], field="intervention_role", pair_id=pair_id)
        stressed = group[group["variant"].eq("stressed")]
        mitigated = group[group["variant"].eq("mitigated")]
        stressed_config = variant_config(group, "stressed")
        mitigated_config = variant_config(group, "mitigated")
        changed_fields = sorted(
            field
            for field in set(stressed_config) | set(mitigated_config)
            if stressed_config.get(field, []) != mitigated_config.get(field, [])
        )
        scope, scope_source, scope_status = infer_target_scope(group)
        rows.append(
            {
                "pair_id": pair_id,
                "pressure_axis": pressure_axis,
                "intervention_role": role,
                "mitigation_action": action,
                "target_scope_canonical": scope,
                "target_scope_source": scope_source,
                "target_scope_status": scope_status,
                "stressed_template_id": "|".join(unique_values(stressed["template_id"])),
                "mitigated_template_id": "|".join(unique_values(mitigated["template_id"])),
                "logical_question_id": "|".join(unique_values(group["logical_question_id"])),
                "dataset_profile_id": "|".join(unique_values(group["dataset_profile_id"])),
                "dataset_size_class": "|".join(unique_values(group["dataset_size_class"])),
                "stressed_condition_id": "|".join(unique_values(stressed["condition_id"])),
                "mitigated_condition_id": "|".join(unique_values(mitigated["condition_id"])),
                "stressed_execution_count": len(stressed),
                "mitigated_execution_count": len(mitigated),
                "changed_fields": "|".join(changed_fields),
                "stressed_config_json": compact_json(stressed_config),
                "mitigated_config_json": compact_json(mitigated_config),
            }
        )
    return pd.DataFrame(rows)


def action_contract_frame(contract: dict[str, Any]) -> pd.DataFrame:
    rows = []
    policies = contract["policies"]
    for action, values in contract["actions"].items():
        policy_id = values["policy_id"]
        rows.append(
            {
                "mitigation_action": action,
                "policy_id": policy_id,
                "action_display_name": values["display_name"],
                "action_kind": values["action_kind"],
                "policy_display_name": policies[policy_id]["display_name"],
                "policy_intended_use": policies[policy_id]["intended_use"],
                "expected_changed_fields": "|".join(values.get("expected_changed_fields_any", [])),
                "expected_no_change": bool(values.get("expected_no_change", False)),
            }
        )
    return pd.DataFrame(rows)


def build_pair_audit(
    pair_design: pd.DataFrame,
    pair_summary: pd.DataFrame,
    action_contract: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    summary_fields = [
        "pair_id",
        "pressure_axis",
        "intervention_role",
        "target_metric",
        "repeat_count",
        "complete_repeat_count",
        "elapsed_ratio_median",
        "elapsed_ratio_min",
        "elapsed_ratio_max",
        "target_log2_gain_median",
        "target_log2_gain_std",
        "positive_repeat_share",
        "result_equivalence_status",
        "same_row_count",
        "exact_multiset_hash",
    ]
    pairs = pair_design.merge(
        pair_summary[summary_fields],
        on=["pair_id", "pressure_axis", "intervention_role"],
        validate="one_to_one",
    )
    pairs = pairs.merge(action_contract, on="mitigation_action", how="left", validate="many_to_one")
    strict = set(contract["result_equivalence"]["strict_statuses"])
    review = set(contract["result_equivalence"]["review_statuses"])
    invalid = set(contract["result_equivalence"]["invalid_statuses"])

    def status(row: pd.Series) -> str:
        equivalence = row["result_equivalence_status"]
        if int(row["complete_repeat_count"]) != int(
            contract["canonical_gain_target"]["repetitions_per_condition"]
        ):
            return "incomplete_repetitions"
        if row["target_scope_status"] != "ok":
            return row["target_scope_status"]
        if equivalence in strict:
            return "strict_eligible"
        if equivalence in review:
            return "review_only"
        if equivalence in invalid:
            return "invalid_result_equivalence"
        return "unknown_result_equivalence"

    pairs["gain_pair_status"] = pairs.apply(status, axis=1)
    pairs["strict_gain_eligible"] = pairs["gain_pair_status"].eq("strict_eligible")
    pairs["review_gain_eligible"] = pairs["gain_pair_status"].isin(
        ["strict_eligible", "review_only"]
    )

    def change_status(row: pd.Series) -> str:
        changed = {value for value in str(row["changed_fields"]).split("|") if value}
        expected = {value for value in str(row["expected_changed_fields"]).split("|") if value}
        if bool(row["expected_no_change"]):
            return "ok_expected_no_change" if not changed else "unexpected_change"
        return "ok_expected_change" if changed & expected else "expected_change_missing"

    pairs["change_contract_status"] = pairs.apply(change_status, axis=1)
    return pairs.sort_values(["policy_id", "mitigation_action", "pair_id"])


def apply_correctness_recovery(
    pairs: pd.DataFrame,
    recovery: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    required = {"pair_id", "correctness_recovery_status"}
    missing = sorted(required - set(recovery.columns))
    if missing:
        raise ValueError(f"Correctness recovery is missing columns: {missing}")
    if recovery["pair_id"].duplicated().any():
        raise ValueError("Correctness recovery contains duplicate pair_id values")

    accepted = set(contract["correctness_recovery"]["accepted_statuses"])
    unknown = sorted(set(recovery["correctness_recovery_status"]) - accepted)
    if unknown:
        raise ValueError(f"Correctness recovery contains unaccepted statuses: {unknown}")

    result = pairs.copy()
    result["original_result_equivalence_status"] = result["result_equivalence_status"]
    result = result.merge(
        recovery[["pair_id", "correctness_recovery_status"]],
        on="pair_id",
        how="left",
        validate="one_to_one",
    )
    recovered = result["correctness_recovery_status"].isin(accepted)
    result["correctness_recovery_applied"] = recovered
    result.loc[recovered, "result_equivalence_status"] = result.loc[
        recovered, "correctness_recovery_status"
    ].map(lambda value: f"recovery_{value}")
    result.loc[recovered, "gain_pair_status"] = "strict_eligible"
    result.loc[recovered, "strict_gain_eligible"] = True
    result.loc[recovered, "review_gain_eligible"] = True
    return result.sort_values(["policy_id", "mitigation_action", "pair_id"])


def signal_status(median_gain: float, positive_share: float, thresholds: dict[str, Any]) -> str:
    if math.isnan(median_gain) or math.isnan(positive_share):
        return "not_available"
    if median_gain >= float(thresholds["strong_gain_log2_median"]) and positive_share >= float(
        thresholds["strong_positive_pair_share"]
    ):
        return "strong_positive_global_gain"
    if median_gain >= float(thresholds["moderate_gain_log2_median"]) and positive_share >= float(
        thresholds["moderate_positive_pair_share"]
    ):
        return "moderate_positive_global_gain"
    return "weak_or_inconsistent_global_gain"


def holdout_stats(group: pd.DataFrame, field: str, thresholds: dict[str, Any]) -> dict[str, Any]:
    counts = group.groupby(field, dropna=False).size()
    strict_counts = group[group["strict_gain_eligible"]].groupby(field, dropna=False).size()
    group_count = len(counts)
    strict_group_count = len(strict_counts)
    min_pairs = int(counts.min()) if not counts.empty else 0
    min_strict = int(strict_counts.min()) if not strict_counts.empty else 0
    enough_groups = group_count >= int(thresholds["minimum_groups_for_holdout"])
    enough_pairs = min_pairs >= int(thresholds["minimum_pairs_per_holdout_group"])
    if enough_groups and enough_pairs and strict_group_count == group_count and min_strict >= 1:
        status = "feasible_strict"
    elif enough_groups and enough_pairs:
        status = "feasible_review_inclusive"
    else:
        status = "not_feasible"
    return {
        "group_count": group_count,
        "minimum_pair_count": min_pairs,
        "strict_group_count": strict_group_count,
        "minimum_strict_pair_count": min_strict,
        "holdout_status": status,
    }


def readiness_status(
    *,
    group: pd.DataFrame,
    signal: str,
    thresholds: dict[str, Any],
    intended_use: str,
) -> tuple[str, str]:
    if intended_use == "calibration_only":
        return "calibration_only", "contract_marks_policy_as_calibration_only"
    pair_count = len(group)
    strict_count = int(group["strict_gain_eligible"].sum())
    template_count = group["stressed_template_id"].nunique()
    dataset_count = group["dataset_profile_id"].nunique()
    reasons = []
    if pair_count < int(thresholds["minimum_pairs"]):
        reasons.append("fewer_than_minimum_pairs")
    if strict_count < int(thresholds["minimum_strict_pairs"]):
        reasons.append("fewer_than_minimum_strict_pairs")
    if template_count < int(thresholds["minimum_stressed_templates"]):
        reasons.append("insufficient_stressed_template_diversity")
    if dataset_count < int(thresholds["minimum_datasets"]):
        reasons.append("insufficient_dataset_diversity")
    if signal == "weak_or_inconsistent_global_gain":
        reasons.append("weak_or_inconsistent_global_gain")
    if reasons:
        if reasons == ["weak_or_inconsistent_global_gain"]:
            status = "candidate_null_result_test"
        else:
            status = "limited_gain_model"
        return status, "|".join(reasons)
    return "candidate_grouped_gain_model", "meets_configured_readiness_thresholds"


def summarize_entity(
    pairs: pd.DataFrame,
    *,
    entity_field: str,
    contract: dict[str, Any],
) -> pd.DataFrame:
    thresholds = contract["readiness_thresholds"]
    rows: list[dict[str, Any]] = []
    for (entity, role), group in pairs.groupby([entity_field, "intervention_role"], sort=True):
        gains = numeric(group["target_log2_gain_median"]).dropna()
        median_gain = float(gains.median()) if not gains.empty else math.nan
        positive_share = float((gains > 0).mean()) if not gains.empty else math.nan
        signal = (
            "negative_control"
            if role == "negative_control"
            else signal_status(median_gain, positive_share, thresholds)
        )
        intended_use = only_value(
            group["policy_intended_use"], field="policy_intended_use", pair_id=str(entity)
        )
        readiness, reasons = readiness_status(
            group=group,
            signal=signal,
            thresholds=thresholds,
            intended_use=intended_use,
        )
        action_template = group[["mitigation_action", "stressed_template_id"]].drop_duplicates()
        template_action_count = action_template.groupby("stressed_template_id")[
            "mitigation_action"
        ].nunique()
        action_template_confounded = (
            action_template["mitigation_action"].nunique() > 1
            and not template_action_count.empty
            and bool(template_action_count.eq(1).all())
        )
        rows.append(
            {
                entity_field: entity,
                "intervention_role": role,
                "pair_count": len(group),
                "strict_pair_count": int(group["strict_gain_eligible"].sum()),
                "review_pair_count": int(group["gain_pair_status"].eq("review_only").sum()),
                "invalid_pair_count": int(
                    (~group["gain_pair_status"].isin(["strict_eligible", "review_only"])).sum()
                ),
                "action_count": group["mitigation_action"].nunique(),
                "stressed_template_count": group["stressed_template_id"].nunique(),
                "mitigated_template_count": group["mitigated_template_id"].nunique(),
                "logical_question_count": group["logical_question_id"].nunique(),
                "dataset_count": group["dataset_profile_id"].nunique(),
                "dataset_size_class_count": group["dataset_size_class"].nunique(),
                "configuration_transition_count": group["changed_fields"].nunique(),
                "target_scope_all_global": bool(group["target_scope_status"].eq("ok").all()),
                "median_log2_gain": median_gain,
                "median_speedup": (
                    float(2**median_gain) if not math.isnan(median_gain) else math.nan
                ),
                "q10_log2_gain": float(gains.quantile(0.10)) if not gains.empty else math.nan,
                "q90_log2_gain": float(gains.quantile(0.90)) if not gains.empty else math.nan,
                "positive_gain_pair_share": positive_share,
                "median_within_pair_log2_std": float(
                    numeric(group["target_log2_gain_std"]).median()
                ),
                "global_gain_signal": signal,
                "action_template_confounded": action_template_confounded,
                "model_readiness": readiness,
                "model_readiness_reasons": reasons,
            }
        )
    return pd.DataFrame(rows).sort_values([entity_field, "intervention_role"])


def build_holdout_feasibility(
    pairs: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    rows = []
    thresholds = contract["readiness_thresholds"]
    group_fields = {
        "leave_stressed_template_out": "stressed_template_id",
        "leave_logical_question_out": "logical_question_id",
        "leave_dataset_out": "dataset_profile_id",
        "leave_size_class_out": "dataset_size_class",
    }
    for entity_type, entity_field in (("action", "mitigation_action"), ("policy", "policy_id")):
        for (entity_id, role), group in pairs.groupby(
            [entity_field, "intervention_role"], sort=True
        ):
            if role == "negative_control":
                continue
            for holdout_name, field in group_fields.items():
                rows.append(
                    {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "intervention_role": role,
                        "holdout_type": holdout_name,
                        "group_field": field,
                        **holdout_stats(group, field, thresholds),
                    }
                )
    result = pd.DataFrame(rows)
    policy_template_map = (
        pairs.groupby(["policy_id", "intervention_role"])
        .apply(
            lambda group: (
                group["mitigation_action"].nunique() > 1
                and group[["mitigation_action", "stressed_template_id"]]
                .drop_duplicates()
                .groupby("stressed_template_id")["mitigation_action"]
                .nunique()
                .eq(1)
                .all()
            ),
            include_groups=False,
        )
        .to_dict()
    )
    confounded = (
        result["entity_type"].eq("policy")
        & result["holdout_type"].eq("leave_stressed_template_out")
        & result.apply(
            lambda row: bool(
                policy_template_map.get((row["entity_id"], row["intervention_role"]), False)
            ),
            axis=1,
        )
        & ~result["holdout_status"].eq("not_feasible")
    )
    result.loc[confounded, "holdout_status"] = "structurally_feasible_action_confounded"
    return result


def build_transition_summary(pairs: pd.DataFrame) -> pd.DataFrame:
    return (
        pairs.groupby(
            [
                "policy_id",
                "mitigation_action",
                "intervention_role",
                "changed_fields",
                "stressed_config_json",
                "mitigated_config_json",
            ],
            dropna=False,
        )
        .agg(
            pair_count=("pair_id", "size"),
            strict_pair_count=("strict_gain_eligible", "sum"),
            stressed_template_count=("stressed_template_id", "nunique"),
            dataset_count=("dataset_profile_id", "nunique"),
        )
        .reset_index()
        .sort_values(["policy_id", "mitigation_action", "intervention_role"])
    )


def build_learning_curve_checkpoints(policy_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    source = policy_summary[~policy_summary["intervention_role"].eq("negative_control")]
    for row in source.itertuples(index=False):
        for fraction in (0.25, 0.50, 0.75, 1.00):
            rows.append(
                {
                    "policy_id": row.policy_id,
                    "intervention_role": row.intervention_role,
                    "fraction": fraction,
                    "target_pair_count": max(1, math.ceil(row.pair_count * fraction)),
                    "full_pair_count": row.pair_count,
                    "full_strict_pair_count": row.strict_pair_count,
                    "evaluation_status": "planned_not_fitted",
                    "grouping_contract": (
                        "pair_id+scenario_family, report template and dataset holdouts"
                    ),
                }
            )
    return pd.DataFrame(rows)


def write_gain_figure(action_summary: pd.DataFrame, path: Path) -> None:
    source = action_summary[
        action_summary["intervention_role"].isin(["positive_case", "calibration"])
    ].copy()
    source = source.sort_values("median_log2_gain")
    lower = source["median_log2_gain"] - source["q10_log2_gain"]
    upper = source["q90_log2_gain"] - source["median_log2_gain"]
    fig, ax = plt.subplots(figsize=(11, 7))
    ax.errorbar(
        source["median_log2_gain"],
        source["mitigation_action"],
        xerr=np.vstack([lower.clip(lower=0), upper.clip(lower=0)]),
        fmt="o",
        color="#174a5b",
        ecolor="#75939b",
        capsize=3,
    )
    ax.axvline(0, color="#6f6f6f", linewidth=1)
    ax.set_xlabel("Medijanski log2 stressed/mitigated gain (Q10-Q90)")
    ax.set_ylabel("Mitigacijska akcija")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    view = frame[columns].copy()
    for column in view.columns:
        if pd.api.types.is_float_dtype(view[column]):
            view[column] = view[column].map(lambda value: f"{value:.3f}")
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in view.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])


def write_report(
    *,
    out_dir: Path,
    pair_audit: pd.DataFrame,
    action_summary: pd.DataFrame,
    policy_summary: pd.DataFrame,
    holdouts: pd.DataFrame,
    fatal_issues: list[str],
    recovery_applied_count: int,
) -> None:
    action_view = action_summary[
        action_summary["intervention_role"].isin(["positive_case", "calibration"])
    ]
    policy_view = policy_summary[
        policy_summary["intervention_role"].isin(["positive_case", "calibration"])
    ]
    holdout_view = holdouts[
        holdouts["entity_type"].eq("policy")
        & holdouts["holdout_type"].isin(["leave_stressed_template_out", "leave_dataset_out"])
    ]
    report = f"""# Pressure raw v1 - autoritativni audit mitigacijskih akcija

## Ugovor i gate

- Kontrafaktualna jedinica: `{len(pair_audit)}` parova.
- Strogo rezultatski ekvivalentni parovi: `{int(pair_audit["strict_gain_eligible"].sum())}`.
- Parovi razrijeseni typed correctness recovery provjerom: `{recovery_applied_count}`.
- Nerazrijeseni review parovi sa istim brojem redova i razlicitim hashom:
  `{int(pair_audit["gain_pair_status"].eq("review_only").sum())}`.
- Target je medijanski end-to-end GAC gain kroz tri ponavljanja:
  `log2(T_stressed / T_mitigated)`.
- Scope gate: `{"GO" if not fatal_issues else "FAIL"}`.
- Fatalne nepravilnosti: `{", ".join(fatal_issues) or "nema"}`.

Pet ranijih pressure osa tretiraju se kao domene dokaza. Modelski targeti se
vezuju za eksplicitne mitigacijske akcije ili unaprijed definisane operativne
politike, ne za pretpostavljene fizicke uzroke.

## Akcije

{
        markdown_table(
            action_view,
            [
                "mitigation_action",
                "intervention_role",
                "pair_count",
                "strict_pair_count",
                "stressed_template_count",
                "dataset_count",
                "median_speedup",
                "global_gain_signal",
                "model_readiness",
            ],
        )
    }

## Operativne politike

{
        markdown_table(
            policy_view,
            [
                "policy_id",
                "intervention_role",
                "pair_count",
                "strict_pair_count",
                "action_count",
                "stressed_template_count",
                "dataset_count",
                "median_speedup",
                "action_template_confounded",
                "model_readiness",
            ],
        )
    }

`action_template_confounded=true` znaci da je svaka akcija u posmatranoj politici
vezana za vlastiti stressed SQL template. Takav skup moze evaluirati vrijednost
postojecih action-selection pravila, ali ne dokazuje action-specific prenos na
nevidjeni SQL oblik.

## Grupisani holdouti

{
        markdown_table(
            holdout_view,
            [
                "entity_id",
                "intervention_role",
                "holdout_type",
                "group_count",
                "minimum_pair_count",
                "strict_group_count",
                "holdout_status",
            ],
        )
    }

Holdout status opisuje samo strukturnu izvodljivost podjele. Ne predstavlja
rezultat modela. Ponavljanja, oba clana para i varijante istog scenarija moraju
ostati u istom foldu.

## Autoritativna odluka

1. `use_colocated_distribution` ima najjaci action-specific skup za grouped gain
   model.
2. GAC regionalni rewrite ima dovoljno parova tek kao politika od cetiri akcije,
   ali akcija i stressed template su konfendirani.
3. Remote bundle ima jak target i svi raniji review parovi sada prolaze typed
   correctness gate. Fetch, delay i bandwidth blokovi ostaju kalibracijski.
4. `disperse_hot_shards` i `increase_regional_work_mem` imaju slab globalni gain.
   Njih treba evaluirati protiv null baselinea, bez obecanja pozitivnog modela.
5. Individualni GAC rewrite regresori i GAC memory regresor nemaju dovoljnu
   stressed-template raznovrsnost za opstu leave-template-out tvrdnju.

## Izlazi

- `mitigation_pair_audit.csv`
- `mitigation_action_summary.csv`
- `mitigation_policy_summary.csv`
- `configuration_transition_summary.csv`
- `holdout_feasibility.csv`
- `learning_curve_checkpoints.csv`
- `mitigation_gain_by_action.png`
- `summary.json`
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")


def main() -> int:
    args = parse_args()
    package_dir = args.package_dir.resolve()
    eda_dir = args.eda_dir.resolve()
    out_dir = args.out_dir.resolve()
    recovery_dir = args.correctness_recovery_dir.resolve()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    manifest = json.loads((package_dir / "consolidation_manifest.json").read_text())
    if manifest.get("gate") != "GO":
        raise ValueError("Consolidated pressure package gate is not GO")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[ACTION AUDIT 1/6] loading pair and execution contracts", flush=True)
    executions = load_execution_design(package_dir)
    pair_summary = read_csv(eda_dir / "counterfactual_pair_summary.csv")
    pair_summary["complete_repeat_count"] = numeric(pair_summary["complete_repeat_count"])
    pair_summary["target_log2_gain_median"] = numeric(pair_summary["target_log2_gain_median"])
    pair_summary["target_log2_gain_std"] = numeric(pair_summary["target_log2_gain_std"])
    pair_summary["elapsed_ratio_median"] = numeric(pair_summary["elapsed_ratio_median"])
    pair_summary["positive_repeat_share"] = numeric(pair_summary["positive_repeat_share"])

    print("[ACTION AUDIT 2/6] resolving one action and target scope per pair", flush=True)
    pair_design = build_pair_design(executions)
    action_contract = action_contract_frame(contract)
    observed_actions = set(pair_design["mitigation_action"])
    contracted_actions = set(action_contract["mitigation_action"])
    unknown_actions = sorted(observed_actions - contracted_actions)
    missing_actions = sorted(contracted_actions - observed_actions)
    pair_audit = build_pair_audit(pair_design, pair_summary, action_contract, contract)
    recovery_applied_count = 0
    recovery_results_path = recovery_dir / "correctness_recovery_results.csv"
    recovery_summary_path = recovery_dir / "correctness_recovery_summary.json"
    if recovery_results_path.is_file() or recovery_summary_path.is_file():
        if not recovery_results_path.is_file() or not recovery_summary_path.is_file():
            raise ValueError("Correctness recovery package is incomplete")
        recovery_summary = json.loads(recovery_summary_path.read_text(encoding="utf-8"))
        if recovery_summary.get("gate") != "GO":
            raise ValueError("Correctness recovery gate is not GO")
        pair_audit = apply_correctness_recovery(
            pair_audit,
            read_csv(recovery_results_path),
            contract,
        )
        recovery_applied_count = int(pair_audit["correctness_recovery_applied"].sum())
    else:
        pair_audit["original_result_equivalence_status"] = pair_audit[
            "result_equivalence_status"
        ]
        pair_audit["correctness_recovery_status"] = ""
        pair_audit["correctness_recovery_applied"] = False

    print("[ACTION AUDIT 3/6] summarizing action and policy evidence", flush=True)
    action_summary = summarize_entity(
        pair_audit, entity_field="mitigation_action", contract=contract
    )
    policy_summary = summarize_entity(pair_audit, entity_field="policy_id", contract=contract)
    transitions = build_transition_summary(pair_audit)

    print("[ACTION AUDIT 4/6] checking grouped holdout feasibility", flush=True)
    holdouts = build_holdout_feasibility(pair_audit, contract)
    checkpoints = build_learning_curve_checkpoints(policy_summary)

    fatal_issues = []
    if unknown_actions:
        fatal_issues.append(f"unknown_actions:{','.join(unknown_actions)}")
    if missing_actions:
        fatal_issues.append(f"contract_actions_without_evidence:{','.join(missing_actions)}")
    if pair_audit["policy_id"].eq("").any() or pair_audit["policy_id"].isna().any():
        fatal_issues.append("missing_policy_mapping")
    bad_scope = int((~pair_audit["target_scope_status"].eq("ok")).sum())
    if bad_scope:
        fatal_issues.append(f"non_global_or_unresolved_scope_pairs:{bad_scope}")
    invalid = int((~pair_audit["gain_pair_status"].isin(["strict_eligible", "review_only"])).sum())
    if invalid:
        fatal_issues.append(f"invalid_pair_count:{invalid}")
    bad_changes = int(
        (
            ~pair_audit["change_contract_status"].isin(
                ["ok_expected_change", "ok_expected_no_change"]
            )
        ).sum()
    )
    if bad_changes:
        fatal_issues.append(f"action_change_contract_violations:{bad_changes}")

    print("[ACTION AUDIT 5/6] writing authoritative tables and figure", flush=True)
    pair_audit.to_csv(out_dir / "mitigation_pair_audit.csv", index=False)
    action_summary.to_csv(out_dir / "mitigation_action_summary.csv", index=False)
    policy_summary.to_csv(out_dir / "mitigation_policy_summary.csv", index=False)
    transitions.to_csv(out_dir / "configuration_transition_summary.csv", index=False)
    holdouts.to_csv(out_dir / "holdout_feasibility.csv", index=False)
    checkpoints.to_csv(out_dir / "learning_curve_checkpoints.csv", index=False)
    write_gain_figure(action_summary, out_dir / "mitigation_gain_by_action.png")

    print("[ACTION AUDIT 6/6] writing decision and checksums", flush=True)
    write_report(
        out_dir=out_dir,
        pair_audit=pair_audit,
        action_summary=action_summary,
        policy_summary=policy_summary,
        holdouts=holdouts,
        fatal_issues=fatal_issues,
        recovery_applied_count=recovery_applied_count,
    )
    outputs = sorted(path for path in out_dir.iterdir() if path.is_file())
    checksums = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in outputs
        if path.name not in {"checksums.sha256", "summary.json"}
    }
    summary = {
        "audit_contract": contract["contract_version"],
        "program_id": contract["program_id"],
        "gate": "GO" if not fatal_issues else "FAIL",
        "fatal_issues": fatal_issues,
        "pair_count": len(pair_audit),
        "strict_pair_count": int(pair_audit["strict_gain_eligible"].sum()),
        "review_pair_count": int(pair_audit["gain_pair_status"].eq("review_only").sum()),
        "correctness_recovery_applied_pair_count": recovery_applied_count,
        "action_count": pair_audit["mitigation_action"].nunique(),
        "policy_count": pair_audit["policy_id"].nunique(),
        "target_scope": contract["canonical_gain_target"]["target_scope"],
        "modeling_decision": "MIXED_ACTION_READINESS",
        "next_gate": "fit_grouped_action_and_policy_gain_baselines",
        "checksums": checksums,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checksum_lines = [f"{digest}  {name}" for name, digest in sorted(checksums.items())]
    (out_dir / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    print(out_dir / "README.md")
    return 0 if not fatal_issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
