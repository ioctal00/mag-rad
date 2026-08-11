#!/usr/bin/env python3
"""Audit action-selection denominators without executing SQL.

The audit separates physical executions, measured conditions, temporal decision
points, SQL-shape clusters, and issued recommendations. Treating these units as
interchangeable would create pseudoreplication in the Top-1 evaluation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = ROOT / "releases/action-selection-sample-size-audit-v1"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wilson_interval(
    successes: int,
    trials: int,
    z: float = 1.959963984540054,
) -> tuple[float, float]:
    if trials == 0:
        return (math.nan, math.nan)
    rate = successes / trials
    denominator = 1.0 + z * z / trials
    center = (rate + z * z / (2.0 * trials)) / denominator
    radius = z * math.sqrt(
        rate * (1.0 - rate) / trials + z * z / (4.0 * trials * trials)
    ) / denominator
    return (max(0.0, center - radius), min(1.0, center + radius))


def exact_mcnemar_two_sided(static_only: int, prequential_only: int) -> float:
    discordant = static_only + prequential_only
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, value)
        for value in range(0, min(static_only, prequential_only) + 1)
    ) / (2**discordant)
    return min(1.0, 2.0 * tail)


def audit_units() -> list[dict[str, Any]]:
    provenance = {
        row["dataset_id"]: row
        for row in read_csv(
            ROOT / "releases/consolidated-evaluation-v1/dataset_provenance.csv"
        )
    }

    pressure = read_csv(ROOT / "generated/corpus/pressure-raw-v1/execution_matrix.csv")
    pressure_pairs: dict[str, set[str]] = defaultdict(set)
    for row in pressure:
        pressure_pairs[row["pair_id"]].add(row["mitigation_action"])
    if len(pressure) != 2607 or len(pressure_pairs) != 418:
        raise AssertionError("unexpected broad-corpus dimensions")
    if Counter(len(actions) for actions in pressure_pairs.values()) != {1: 418}:
        raise AssertionError("a broad-corpus pair unexpectedly contains multiple actions")

    development = read_csv(
        ROOT / "analysis/reports/fuzzy-intervention-memory-v1/episodes.csv"
    )
    ranked_actions = {
        "increase_gac_work_mem",
        "mitigate_remote_path_bundle",
        "regional_topk_candidates",
    }
    development_by_state: dict[str, set[str]] = defaultdict(set)
    for row in development:
        if row["mitigation_action"] not in ranked_actions:
            continue
        development_by_state[row["scenario_id"]].add(row["mitigation_action"])
    complete_development_states = {
        state for state, actions in development_by_state.items() if actions == ranked_actions
    }
    development_logical_questions = {
        row["logical_question_id"]
        for row in development
        if row["scenario_id"] in complete_development_states
    }
    if len(complete_development_states) != 26:
        raise AssertionError("unexpected development reference-state count")

    final_timeline = read_csv(
        ROOT / "analysis/reports/dba-local-memory-panel-v1/dba_episode_timeline.csv"
    )
    final_base = [row for row in final_timeline if row["memory_mode"] == "cold_start"]
    if len(final_base) != 45 or len({row["query_id"] for row in final_base}) != 15:
        raise AssertionError("unexpected final DBA panel dimensions")

    topology = read_csv(
        ROOT / "analysis/reports/n3-topology-memory-v1/episode_states.csv"
    )
    if len(topology) != 45 or len({row["query_id"] for row in topology}) != 15:
        raise AssertionError("unexpected topology-panel dimensions")

    confirm_order = read_csv(
        ROOT / "releases/confirmatory-action-replication-v1/rendered_execution_order.csv"
    )
    confirm_outcomes = read_csv(
        ROOT / "releases/confirmatory-action-replication-v1/scenario_outcome_summary.csv"
    )
    if len(confirm_order) != 300 or len(confirm_outcomes) != 15:
        raise AssertionError("unexpected confirmatory-panel dimensions")

    rows = [
        {
            "evidence_block": "F19 characterization corpus",
            "physical_executions": 1964,
            "measured_conditions_or_states": 1964,
            "before_after_pairs": "",
            "temporal_decisions": "",
            "distinct_sql_units": "not an action-ranking unit",
            "repetitions_per_condition": "archived execution states",
            "complete_competing_action_matrix": "no",
            "valid_primary_use": "descriptive FCM characterization for RQ1-RQ4",
            "invalid_use": "Top-1 action-selection accuracy",
        },
        {
            "evidence_block": "broad intervention corpus",
            "physical_executions": len(pressure),
            "measured_conditions_or_states": len({row["condition_id"] for row in pressure}),
            "before_after_pairs": len(pressure_pairs),
            "temporal_decisions": "",
            "distinct_sql_units": (
                f"{len({row['template_id'] for row in pressure})} templates; "
                f"{len({row['logical_question_id'] for row in pressure})} logical questions"
            ),
            "repetitions_per_condition": 3,
            "complete_competing_action_matrix": "no; one measured action per pair",
            "valid_primary_use": "collector, equivalence, physical response, intervention contract",
            "invalid_use": "best-of-three Top-1 ranking",
        },
        {
            "evidence_block": "development/reference ranking panel",
            "physical_executions": int(
                provenance["development_reference_panel"]["execution_count"]
            ),
            "measured_conditions_or_states": len(complete_development_states),
            "before_after_pairs": 78,
            "temporal_decisions": 26,
            "distinct_sql_units": (
                f"{provenance['development_reference_panel']['sql_shape_count']} templates; "
                f"{len(development_logical_questions)} logical question"
            ),
            "repetitions_per_condition": 3,
            "complete_competing_action_matrix": "yes, three actions",
            "valid_primary_use": "development of P64->6, k, distance, P99 and comparators",
            "invalid_use": "final independent holdout claim",
        },
        {
            "evidence_block": "final temporal DBA panel",
            "physical_executions": int(provenance["final_dba_panel"]["execution_count"]),
            "measured_conditions_or_states": len(final_base),
            "before_after_pairs": 135,
            "temporal_decisions": len(final_base),
            "distinct_sql_units": len({row["query_id"] for row in final_base}),
            "repetitions_per_condition": 1,
            "complete_competing_action_matrix": "yes, three actions",
            "valid_primary_use": "temporal first occurrence and repeated-query behavior",
            "invalid_use": "45 independent new-query generalization cases",
        },
        {
            "evidence_block": "controlled topology-memory panel",
            "physical_executions": int(
                provenance["controlled_topology_memory_panel"]["execution_count"]
            ),
            "measured_conditions_or_states": len(topology),
            "before_after_pairs": 135,
            "temporal_decisions": len(topology),
            "distinct_sql_units": len({row["query_id"] for row in topology}),
            "repetitions_per_condition": 1,
            "complete_competing_action_matrix": "yes, three actions",
            "valid_primary_use": "controlled N2/N3 shift and local adaptation",
            "invalid_use": "independent 45-query action-selection sample",
        },
        {
            "evidence_block": "confirmatory new-query panel",
            "physical_executions": len(confirm_order),
            "measured_conditions_or_states": len(confirm_outcomes),
            "before_after_pairs": 45,
            "temporal_decisions": len(confirm_outcomes),
            "distinct_sql_units": len({row["query_id"] for row in confirm_outcomes}),
            "repetitions_per_condition": 5,
            "complete_competing_action_matrix": "yes, three actions plus baseline",
            "valid_primary_use": "stability of winners and bounded new-query transfer test",
            "invalid_use": "300 independent Top-1 decisions or universal accuracy",
        },
    ]
    return rows


def audit_confirmatory() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    summary = read_csv(
        ROOT / "releases/confirmatory-action-replication-v1/evaluation_summary.csv"
    )
    predictions = read_csv(
        ROOT / "releases/confirmatory-action-replication-v1/per_scenario_predictions.csv"
    )
    by_mode = {row["mode"]: row for row in summary}

    metrics: list[dict[str, Any]] = []
    for mode in ("static_action_median", "frozen_transfer", "prequential_full_feedback"):
        row = by_mode[mode]
        decisions = int(row["decision_count"])
        recommendations = int(row["recommendation_count"])
        correct = round(float(row["strict_top1"]) * recommendations) if recommendations else 0
        coverage_interval = wilson_interval(recommendations, decisions)
        top1_interval = wilson_interval(correct, recommendations)
        metrics.append(
            {
                "mode": mode,
                "decision_count": decisions,
                "recommendation_count": recommendations,
                "correct_recommendation_count": correct,
                "coverage": recommendations / decisions,
                "coverage_wilson_95_low": coverage_interval[0],
                "coverage_wilson_95_high": coverage_interval[1],
                "top1": correct / recommendations if recommendations else "",
                "top1_wilson_95_low": top1_interval[0] if recommendations else "",
                "top1_wilson_95_high": top1_interval[1] if recommendations else "",
                "one_decision_top1_step": 1 / recommendations if recommendations else "",
            }
        )

    static = {
        row["query_id"]: row
        for row in predictions
        if row["mode"] == "static_action_median"
    }
    prequential = {
        row["query_id"]: row
        for row in predictions
        if row["mode"] == "prequential_full_feedback"
    }
    common = [
        query_id
        for query_id, row in prequential.items()
        if row["decision_status"] == "available"
        and row["complete_action_support"].lower() == "true"
    ]
    paired = Counter(
        (static[query_id]["top1_correct"], prequential[query_id]["top1_correct"])
        for query_id in common
    )
    static_only = paired[("True", "False")]
    prequential_only = paired[("False", "True")]

    random_rows = [
        row for row in summary if row["mode"].startswith("partial_feedback_random_seed_")
    ]
    paired_summary = {
        "confirmatory_sql_shapes": 15,
        "confirmatory_physical_executions": 300,
        "common_recommended_sql_shapes": len(common),
        "both_correct": paired[("True", "True")],
        "both_wrong": paired[("False", "False")],
        "static_only_correct": static_only,
        "prequential_only_correct": prequential_only,
        "exact_mcnemar_two_sided_p": exact_mcnemar_two_sided(
            static_only, prequential_only
        ),
        "static_total_correct": round(
            float(by_mode["static_action_median"]["strict_top1"])
            * int(by_mode["static_action_median"]["recommendation_count"])
        ),
        "prequential_total_correct": round(
            float(by_mode["prequential_full_feedback"]["strict_top1"])
            * int(by_mode["prequential_full_feedback"]["recommendation_count"])
        ),
        "random_partial_feedback_coverage_min": min(
            float(row["coverage"]) for row in random_rows
        ),
        "random_partial_feedback_coverage_max": max(
            float(row["coverage"]) for row in random_rows
        ),
        "random_partial_feedback_top1_min": min(
            float(row["strict_top1"]) for row in random_rows
        ),
        "random_partial_feedback_top1_max": max(
            float(row["strict_top1"]) for row in random_rows
        ),
        "interpretation": (
            "The prequential method and the static baseline each made eight correct "
            "decisions. On the 14 SQL shapes where both issued a recommendation, the "
            "prequential method changed only one baseline error into a correct result. "
            "This is not evidence of a robust improvement."
        ),
    }
    return metrics, paired_summary


def render_report(
    units: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    paired: dict[str, Any],
) -> str:
    lines = [
        "# Audit veličine uzorka za izbor intervencije",
        "",
        "Ovaj audit ne izvršava SQL. Razdvaja fizička izvršenja od jedinica "
        "procjene na kojima se računaju pokrivenost i Top-1.",
        "",
        "## Eksperimentalne jedinice",
        "",
        "| Blok | Fizička izvršenja | Stanja/odluke | SQL jedinice | Dopuštena upotreba |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for row in units:
        states = row["temporal_decisions"] or row["measured_conditions_or_states"]
        lines.append(
            f"| {row['evidence_block']} | {row['physical_executions']} | {states} | "
            f"{row['distinct_sql_units']} | {row['valid_primary_use']} |"
        )
    lines.extend(
        [
            "",
            "## Potvrdni panel",
            "",
            "| Postupak | Odluke | Preporuke | Tačno | Top-1 | Wilson 95% |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in metrics:
        interval = (
            f"[{row['top1_wilson_95_low']:.3f}, {row['top1_wilson_95_high']:.3f}]"
            if row["recommendation_count"]
            else "nije primjenjivo"
        )
        top1 = f"{row['top1']:.3f}" if row["recommendation_count"] else "nije primjenjivo"
        lines.append(
            f"| {row['mode']} | {row['decision_count']} | "
            f"{row['recommendation_count']} | {row['correct_recommendation_count']} | "
            f"{top1} | {interval} |"
        )
    lines.extend(
        [
            "",
            "Top-1 od 0,571 predstavlja 8 tačnih preporuka među 14 izdatih. "
            "Statički poredak predstavlja 8 tačnih odluka među svih 15 SQL oblika. "
            "Na 14 zajedničkih preporuka oba postupka su bila tačna sedam puta i "
            "pogrešna šest puta; vremensko dopunjavanje ispravilo je samo jednu "
            "grešku statičkog poretka. Egzaktni dvostrani McNemarov test daje "
            f"p={paired['exact_mcnemar_two_sided_p']:.3f}.",
            "",
            "Pet ponavljanja svakog uslova stabilizuje mjerenje stvarnog pobjednika, "
            "ali ne povećava broj SQL jedinica procjene sa 15 na 300. "
            "Jedna odluka mijenja Top-1 8/14 za približno 0,071. Zato panel ne "
            "procjenjuje univerzalnu tačnost; podržava ograničeni negativni zaključak "
            "da robustan prenos nije potvrđen u ovom skupu.",
            "",
            "Široki korpus ne može povećati nazivnik Top-1 jer svaki njegov "
            "prije/poslije par sadrži ishod samo jedne intervencije. Nedostajući ishodi "
            "ostalih intervencija ne smiju se tretirati kao nule ili kao porazi.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    units = audit_units()
    metrics, paired = audit_confirmatory()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "experimental_units.csv", units)
    write_csv(args.out_dir / "confirmatory_top1_uncertainty.csv", metrics)
    (args.out_dir / "paired_comparison.json").write_text(
        json.dumps(paired, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.out_dir / "REPORT.md").write_text(
        render_report(units, metrics, paired), encoding="utf-8"
    )
    output_names = (
        "REPORT.md",
        "confirmatory_top1_uncertainty.csv",
        "experimental_units.csv",
        "paired_comparison.json",
    )
    (args.out_dir / "checksums.sha256").write_text(
        "".join(
            f"{sha256(args.out_dir / name)}  {name}\n" for name in output_names
        ),
        encoding="utf-8",
    )
    print(f"wrote action-selection sample-size audit to {args.out_dir}")


if __name__ == "__main__":
    main()
