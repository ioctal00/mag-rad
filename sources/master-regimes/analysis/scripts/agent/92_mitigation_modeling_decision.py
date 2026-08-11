#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ACTION_AUDIT = ROOT / "analysis/reports/pressure-raw-v1-mitigation-action-audit"
DEFAULT_COLOCATION = ROOT / "analysis/reports/pressure-raw-v1-colocation-gain-model"
DEFAULT_OUT = ROOT / "analysis/reports/pressure-raw-v1-mitigation-modeling-decision"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze the bounded mitigation-modeling decision after grouped evaluation."
    )
    parser.add_argument("--action-audit-dir", type=Path, default=DEFAULT_ACTION_AUDIT)
    parser.add_argument("--colocation-model-dir", type=Path, default=DEFAULT_COLOCATION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def row_for(
    frame: pd.DataFrame,
    field: str,
    value: str,
    role: str,
) -> pd.Series:
    selected = frame[frame[field].eq(value) & frame["intervention_role"].eq(role)]
    if len(selected) != 1:
        raise ValueError(f"Expected one row for {field}={value}, role={role}")
    return selected.iloc[0]


def decision_row(
    *,
    entity_type: str,
    entity_id: str,
    source: pd.Series,
    category: str,
    model_status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "intervention_role": source["intervention_role"],
        "strict_pair_count": int(source["strict_pair_count"]),
        "stressed_template_count": int(source["stressed_template_count"]),
        "dataset_count": int(source["dataset_count"]),
        "median_log2_gain": float(source["median_log2_gain"]),
        "median_speedup": float(source["median_speedup"]),
        "category": category,
        "model_status": model_status,
        "decision_reason": reason,
    }


def build_decisions(
    actions: pd.DataFrame,
    policies: pd.DataFrame,
    model_manifest: dict[str, Any],
) -> pd.DataFrame:
    rows = []
    colocated = row_for(actions, "mitigation_action", "use_colocated_distribution", "positive_case")
    rows.append(
        decision_row(
            entity_type="action",
            entity_id="use_colocated_distribution",
            source=colocated,
            category="primary_predictive_result",
            model_status=str(model_manifest["gate"]),
            reason=(
                "strong template/dataset transfer; unseen scenario-level extrapolation "
                "does not beat median baseline"
            ),
        )
    )
    remote = row_for(actions, "mitigation_action", "mitigate_remote_path_bundle", "positive_case")
    rows.append(
        decision_row(
            entity_type="action",
            entity_id="mitigate_remote_path_bundle",
            source=remote,
            category="bounded_intervention_study",
            model_status="model_deferred",
            reason=(
                f"{int(remote['strict_pair_count'])} strict pairs remain below "
                "the action-audit minimum of 40"
            ),
        )
    )
    gac = row_for(policies, "policy_id", "gac_regional_reduction", "positive_case")
    rows.append(
        decision_row(
            entity_type="policy",
            entity_id="gac_regional_reduction",
            source=gac,
            category="deterministically_routed_policy",
            model_status="limited_prediction_only",
            reason="four actions are confounded with four stressed SQL templates",
        )
    )
    for action_id, reason in (
        (
            "disperse_hot_shards",
            "placement changes physical imbalance but median end-to-end gain is near zero",
        ),
        (
            "increase_regional_work_mem",
            "spill mitigation has weak and template-specific end-to-end gain",
        ),
    ):
        source = row_for(actions, "mitigation_action", action_id, "positive_case")
        rows.append(
            decision_row(
                entity_type="action",
                entity_id=action_id,
                source=source,
                category="negative_end_to_end_result",
                model_status="no_positive_gain_model",
                reason=reason,
            )
        )
    gac_memory = row_for(actions, "mitigation_action", "increase_gac_work_mem", "positive_case")
    rows.append(
        decision_row(
            entity_type="action",
            entity_id="increase_gac_work_mem",
            source=gac_memory,
            category="bounded_intervention_study",
            model_status="model_deferred",
            reason=(
                "one stressed SQL template and "
                f"{int(gac_memory['strict_pair_count'])} strict pairs"
            ),
        )
    )
    remote_calibration = row_for(
        policies, "policy_id", "remote_transport_calibration", "calibration"
    )
    rows.append(
        decision_row(
            entity_type="policy",
            entity_id="remote_transport_calibration",
            source=remote_calibration,
            category="mechanism_calibration",
            model_status="not_a_general_model",
            reason="isolates fetch, delay and bandwidth effects on two datasets",
        )
    )
    return pd.DataFrame(rows)


def markdown_table(frame: pd.DataFrame) -> str:
    columns = [
        "entity_id",
        "strict_pair_count",
        "stressed_template_count",
        "dataset_count",
        "median_speedup",
        "category",
        "model_status",
    ]
    view = frame[columns].copy()
    view["median_speedup"] = view["median_speedup"].map(lambda value: f"{value:.3f}")
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    lines.extend(
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in view.itertuples(index=False, name=None)
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    action_dir = args.action_audit_dir.resolve()
    model_dir = args.colocation_model_dir.resolve()
    out_dir = args.out_dir.resolve()
    action_manifest = json.loads((action_dir / "summary.json").read_text(encoding="utf-8"))
    model_manifest = json.loads((model_dir / "model_manifest.json").read_text(encoding="utf-8"))
    if action_manifest.get("gate") != "GO" or action_manifest.get("review_pair_count") != 0:
        raise ValueError("Final action audit is not ready")
    if model_manifest.get("mitigation_action") != "use_colocated_distribution":
        raise ValueError("Unexpected primary model action")

    decisions = build_decisions(
        pd.read_csv(action_dir / "mitigation_action_summary.csv"),
        pd.read_csv(action_dir / "mitigation_policy_summary.csv"),
        model_manifest,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(out_dir / "mitigation_modeling_decisions.csv", index=False)
    report = f"""# Zakljucana odluka o modeliranju mitigacijskih akcija

## Odluke

{markdown_table(decisions)}

## Granica između dokaza, akcije i modela

Collector direktno prikazuje fizičke signale. Kontrafaktualni parovi mjere
end-to-end korist konkretne akcije. Regresijski model se opravdava tek kada ista
akcija ima dovoljno raznovrsnih i rezultatski ekvivalentnih parova.

`use_colocated_distribution` je jedina akcija za koju je izveden puni prediktivni
postupak. Rezultat je mješovit: prijenos na neviđeni SQL template i dataset je jak,
ali model ne kalibrira dobro potpuno neviđen nivo intenziteta scenarija. Zato se ne
objavljuje kao univerzalni actionability model.

Remote bundle ostaje jaka intervencijska studija sa 24 stroga para, ali novi model
nije treniran ispod unaprijed definisanog minimuma od 40. Četiri GAC rewrite akcije
ostaju semantički routana politika jer je svaka vezana za vlastiti SQL oblik.

Hot-shard placement i regionalni `work_mem` ostaju važni negativni rezultati:
uklanjanje fizičkog simptoma nije automatski donijelo značajno ubrzanje globalnog
upita. FCM ostaje nenadzirani komparativni sažetak kompozitnih režima, a ne finalni
izlaz za nezavisnu korist akcija.
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")
    manifest = {
        "decision_contract": "mitigation-modeling-decision-v1",
        "action_audit_gate": action_manifest["gate"],
        "strict_pair_count": action_manifest["strict_pair_count"],
        "review_pair_count": action_manifest["review_pair_count"],
        "primary_model_gate": model_manifest["gate"],
        "decision_count": len(decisions),
        "research_scope": "bounded_action_specific_gain_evaluation",
        "fcm_role": "unsupervised_comparative_regime_summary",
    }
    (out_dir / "decision_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    outputs = sorted(path for path in out_dir.iterdir() if path.name != "checksums.sha256")
    lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in outputs]
    (out_dir / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out_dir / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
