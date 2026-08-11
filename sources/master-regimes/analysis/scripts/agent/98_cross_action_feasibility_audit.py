#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGE = ROOT / "generated/pressure-raw-runs/_program/pressure-raw-v1"
DEFAULT_ACTION_AUDIT = (
    ROOT / "analysis/reports/pressure-raw-v1-mitigation-action-audit"
)
DEFAULT_CONTRACT = ROOT / "configs/validation/cross_action_feasibility_v1.yml"
DEFAULT_OUT = ROOT / "analysis/reports/pressure-raw-v1-cross-action-feasibility"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit whether existing mitigation pairs support cross-action ranking."
    )
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--action-audit-dir", type=Path, default=DEFAULT_ACTION_AUDIT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def canonical_json(value: str) -> str:
    if not value:
        return "{}"
    return json.dumps(
        json.loads(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def unique_value(series: pd.Series, *, field: str, pair_id: str) -> str:
    values = sorted({str(value) for value in series if str(value)})
    if len(values) != 1:
        raise ValueError(f"pair {pair_id} has {len(values)} values for {field}: {values}")
    return values[0]


def optional_unique_value(series: pd.Series, *, field: str, pair_id: str) -> str:
    values = sorted({str(value) for value in series if str(value)})
    if len(values) > 1:
        raise ValueError(f"pair {pair_id} has {len(values)} values for {field}: {values}")
    return values[0] if values else ""


def stable_id(prefix: str, payload: dict[str, str]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:20]}"


def build_stressed_context(training: pd.DataFrame) -> pd.DataFrame:
    stressed = training[
        training["variant"].astype(str).eq("stressed")
        & training["pair_id"].astype(str).ne("")
    ].copy()
    fields = (
        "logical_question_id",
        "dataset_profile_id",
        "dataset_size_class",
        "param_json",
        "topology_id",
        "execution_scope",
        "template_id",
    )
    rows: list[dict[str, str]] = []
    for pair_id, group in stressed.groupby("pair_id", sort=True):
        row = {"pair_id": str(pair_id)}
        for field in fields:
            value_reader = optional_unique_value if field == "execution_scope" else unique_value
            row[field] = value_reader(group[field], field=field, pair_id=str(pair_id))
        row["param_json"] = canonical_json(row["param_json"])
        row["stressed_template_id_observed"] = row.pop("template_id")
        rows.append(row)
    return pd.DataFrame(rows)


def attach_scenario_ids(
    pairs: pd.DataFrame, stressed_context: pd.DataFrame, contract: dict[str, Any]
) -> pd.DataFrame:
    context_fields = [
        "pair_id",
        "param_json",
        "topology_id",
        "execution_scope",
        "stressed_template_id_observed",
    ]
    source = pairs.merge(
        stressed_context[context_fields], on="pair_id", validate="one_to_one"
    )
    required_status = contract["inputs"]["required_gain_pair_status"]
    source = source[source["gain_pair_status"].astype(str).eq(required_status)].copy()
    template_mismatch = source[
        source["stressed_template_id"].astype(str)
        != source["stressed_template_id_observed"].astype(str)
    ]
    if not template_mismatch.empty:
        raise ValueError("stressed template differs between pair audit and training view")

    for scenario_kind in ("exact", "semantic"):
        fields = contract["scenario_identity"][f"{scenario_kind}_fields"]
        scenario_ids = []
        for row in source.to_dict(orient="records"):
            payload = {field: str(row.get(field, "")) for field in fields}
            scenario_ids.append(stable_id(scenario_kind, payload))
        source[f"{scenario_kind}_scenario_id"] = scenario_ids
    return source


def build_scenario_summary(pairs: pd.DataFrame, scenario_id: str) -> pd.DataFrame:
    rows = []
    for value, group in pairs.groupby(scenario_id, sort=True):
        actions = sorted(set(group["mitigation_action"].astype(str)))
        rows.append(
            {
                scenario_id: value,
                "logical_question_id": "|".join(
                    sorted(set(group["logical_question_id"].astype(str)))
                ),
                "dataset_profile_id": "|".join(
                    sorted(set(group["dataset_profile_id"].astype(str)))
                ),
                "dataset_size_class": "|".join(
                    sorted(set(group["dataset_size_class"].astype(str)))
                ),
                "param_json": "|".join(sorted(set(group["param_json"].astype(str)))),
                "topology_id": "|".join(
                    sorted(set(group["topology_id"].astype(str)))
                ),
                "pair_count": len(group),
                "tested_action_count": len(actions),
                "tested_actions": "|".join(actions),
                "gain_min": pd.to_numeric(
                    group["target_log2_gain_median"], errors="coerce"
                ).min(),
                "gain_max": pd.to_numeric(
                    group["target_log2_gain_median"], errors="coerce"
                ).max(),
            }
        )
    return pd.DataFrame(rows)


def build_action_matrix(
    pairs: pd.DataFrame, action_contract: pd.DataFrame
) -> pd.DataFrame:
    observed_questions = {
        action: set(group["logical_question_id"].astype(str))
        for action, group in pairs.groupby("mitigation_action")
    }
    action_meta = action_contract.set_index("mitigation_action").to_dict(orient="index")
    rows = []
    for scenario_id, group in pairs.groupby("semantic_scenario_id", sort=True):
        question = unique_value(
            group["logical_question_id"],
            field="logical_question_id",
            pair_id=scenario_id,
        )
        tested = set(group["mitigation_action"].astype(str))
        exact_action_max = int(
            group.groupby("exact_scenario_id")["mitigation_action"].nunique().max()
        )
        for action, meta in action_meta.items():
            if action in tested:
                status = "tested"
                basis = "strict_counterfactual_pair"
            elif question in observed_questions.get(action, set()):
                status = "applicable_untested"
                basis = "action_observed_for_same_logical_question"
            elif str(meta["action_kind"]) == "policy_member":
                status = "semantic_rewrite_unavailable"
                basis = "no_implemented_rewrite_for_logical_question"
            else:
                status = "applicability_unresolved"
                basis = "no_explicit_semantic_applicability_contract"
            rows.append(
                {
                    "semantic_scenario_id": scenario_id,
                    "logical_question_id": question,
                    "dataset_profile_id": unique_value(
                        group["dataset_profile_id"],
                        field="dataset_profile_id",
                        pair_id=scenario_id,
                    ),
                    "param_json": unique_value(
                        group["param_json"], field="param_json", pair_id=scenario_id
                    ),
                    "mitigation_action": action,
                    "action_kind": meta["action_kind"],
                    "status": status,
                    "status_basis": basis,
                    "semantic_tested_action_count": len(tested),
                    "exact_shared_tested_action_count": exact_action_max,
                    "ranking_comparable": exact_action_max >= 2,
                }
            )
    return pd.DataFrame(rows)


def build_action_overlap(pairs: pd.DataFrame) -> pd.DataFrame:
    actions = sorted(set(pairs["mitigation_action"].astype(str)))
    semantic_sets = {
        action: set(group["semantic_scenario_id"].astype(str))
        for action, group in pairs.groupby("mitigation_action")
    }
    exact_sets = {
        action: set(group["exact_scenario_id"].astype(str))
        for action, group in pairs.groupby("mitigation_action")
    }
    question_sets = {
        action: set(group["logical_question_id"].astype(str))
        for action, group in pairs.groupby("mitigation_action")
    }
    rows = []
    for action_a, action_b in itertools.combinations(actions, 2):
        rows.append(
            {
                "action_a": action_a,
                "action_b": action_b,
                "shared_logical_question_count": len(
                    question_sets[action_a] & question_sets[action_b]
                ),
                "shared_semantic_scenario_count": len(
                    semantic_sets[action_a] & semantic_sets[action_b]
                ),
                "shared_exact_baseline_count": len(
                    exact_sets[action_a] & exact_sets[action_b]
                ),
            }
        )
    return pd.DataFrame(rows)


def build_pilot_candidates(
    semantic_summary: pd.DataFrame, exact_summary: pd.DataFrame, contract: dict[str, Any]
) -> pd.DataFrame:
    minimum = int(contract["pilot_gate"]["minimum_tested_actions_per_candidate"])
    candidates = semantic_summary[
        semantic_summary["tested_action_count"].astype(int).ge(minimum)
    ].copy()
    exact_lookup = exact_summary.set_index("exact_scenario_id")["tested_action_count"]
    candidates["existing_exact_shared_baseline"] = False
    candidates["pilot_requirement"] = (
        "re-execute actions from one shared stressed baseline"
    )
    candidates["existing_max_exact_action_count"] = 1
    if not exact_lookup.empty:
        candidates["existing_max_exact_action_count"] = int(exact_lookup.max())
    return candidates.sort_values(
        ["tested_action_count", "logical_question_id", "dataset_profile_id"],
        ascending=[False, True, True],
    )


def render_readme(summary: dict[str, Any]) -> str:
    semantic_multi = summary["semantic_multi_action_scenario_count"]
    semantic_three = summary["semantic_three_action_scenario_count"]
    return f"""# Cross-action feasibility audit

## Odluka

**{summary['gate']}**

Postojeći corpus ima {summary['strict_pair_count']} strogo validnih kontrafaktualnih
parova. Međutim, nijedan dokazano identičan stressed baseline trenutno nema dvije
različite testirane akcije. Zbog toga se postojeći gainovi ne smiju koristiti kao
direktan skup za rangiranje akcija nad istim scenarijem.

Na semantičkom nivou pronađeno je {summary['semantic_multi_action_scenario_count']}
ćelija sa najmanje dvije testirane akcije. One služe za izbor pilota, ali ne dokazuju
promjene poretka jer su akcije izvršene iz različitih stressed konfiguracija.

## Brojevi

| Mjera | Vrijednost |
| --- | ---: |
| Strogo validni parovi | {summary['strict_pair_count']} |
| Tačni stressed scenariji | {summary['exact_scenario_count']} |
| Tačni scenariji sa najmanje dvije akcije | {summary['exact_multi_action_scenario_count']} |
| Semantički scenariji | {summary['semantic_scenario_count']} |
| Semantički scenariji sa najmanje dvije akcije | {semantic_multi} |
| Semantički scenariji sa najmanje tri akcije | {semantic_three} |

## Tumačenje statusa

- `tested`: postoji strogo validan kontrafaktualni par.
- `applicable_untested`: ista akcija je već testirana za isto logičko pitanje, ali ne
  za ovu semantičku ćeliju.
- `semantic_rewrite_unavailable`: za logičko pitanje ne postoji implementirana
  varijanta tog rewritea.
- `applicability_unresolved`: postojeći metapodaci nisu dovoljni da se akcija proglasi
  primjenjivom ili neprimjenjivom.

`not_applicable` se namjerno ne izvodi iz odsustva eksperimenta. Za taj status pilot
mora imati eksplicitan semantički ugovor.

## Sljedeći gate

Odabrati 8--12 ćelija iz `pilot_candidate_scenarios.csv`, konstruisati jedan zajednički
stressed baseline po ćeliji i pojedinačno primijeniti 2--3 akcije. Tek taj rezultat
može provjeriti promjene poretka, action-only baseline i feature-aware ranking.
"""


def main() -> int:
    args = parse_args()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    pairs = pd.read_csv(
        args.action_audit_dir / "mitigation_pair_audit.csv", low_memory=False
    )
    training = pd.read_csv(
        args.package_dir / "training_execution_view.csv", low_memory=False
    ).fillna("")
    action_contract = pairs[["mitigation_action", "action_kind"]].drop_duplicates()

    context = build_stressed_context(training)
    pair_scenarios = attach_scenario_ids(pairs, context, contract)
    exact_summary = build_scenario_summary(pair_scenarios, "exact_scenario_id")
    semantic_summary = build_scenario_summary(pair_scenarios, "semantic_scenario_id")
    action_matrix = build_action_matrix(pair_scenarios, action_contract)
    overlap = build_action_overlap(pair_scenarios)
    candidates = build_pilot_candidates(semantic_summary, exact_summary, contract)

    minimum_candidates = int(contract["pilot_gate"]["minimum_candidate_scenarios"])
    exact_multi = int((exact_summary["tested_action_count"] >= 2).sum())
    semantic_multi = int((semantic_summary["tested_action_count"] >= 2).sum())
    summary = {
        "contract_version": contract["contract_version"],
        "program_id": contract["program_id"],
        "strict_pair_count": len(pair_scenarios),
        "exact_scenario_count": len(exact_summary),
        "exact_multi_action_scenario_count": exact_multi,
        "semantic_scenario_count": len(semantic_summary),
        "semantic_multi_action_scenario_count": semantic_multi,
        "semantic_three_action_scenario_count": int(
            (semantic_summary["tested_action_count"] >= 3).sum()
        ),
        "pilot_candidate_count": len(candidates),
        "explicit_not_applicable_contract_available": False,
        "direct_ranking_from_existing_data": False,
        "gate": (
            "PILOT_REQUIRED"
            if exact_multi == 0 and semantic_multi >= minimum_candidates
            else "MANUAL_REVIEW_REQUIRED"
        ),
    }

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pair_scenarios.to_csv(out_dir / "pair_scenarios.csv", index=False)
    exact_summary.to_csv(out_dir / "exact_scenario_summary.csv", index=False)
    semantic_summary.to_csv(out_dir / "semantic_scenario_summary.csv", index=False)
    action_matrix.to_csv(out_dir / "scenario_action_matrix.csv", index=False)
    overlap.to_csv(out_dir / "action_overlap.csv", index=False)
    candidates.to_csv(out_dir / "pilot_candidate_scenarios.csv", index=False)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "README.md").write_text(render_readme(summary), encoding="utf-8")
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
