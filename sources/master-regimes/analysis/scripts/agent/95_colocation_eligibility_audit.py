#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGE = ROOT / "generated/pressure-raw-runs/_program/pressure-raw-v1"
DEFAULT_AUDIT = ROOT / "analysis/reports/pressure-raw-v1-mitigation-action-audit"
DEFAULT_CONTRACT = ROOT / "configs/models/colocation_eligibility_v1.yml"
DEFAULT_OUT = ROOT / "analysis/reports/pressure-raw-v1-colocation-eligibility"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit deterministic eligibility for colocation review."
    )
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--action-audit-dir", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path, low_memory=False)


def truthy(value: object) -> bool:
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def present(value: object) -> bool:
    return not pd.isna(value) and str(value).strip() not in {"", "none", "nan"}


def classify(row: pd.Series, contract: dict[str, Any]) -> tuple[str, bool]:
    statuses = contract["statuses"]
    rule = contract["candidate_rule"]
    repartition = truthy(row.get("citus_repartition_observed_v2"))
    map_merge_jobs = pd.to_numeric(
        pd.Series([row.get("remote_citus_map_merge_job_count_sum")]),
        errors="coerce",
    ).fillna(0.0).iloc[0]
    repartition = repartition or map_merge_jobs >= float(rule["minimum_map_merge_jobs"])
    if not repartition:
        return str(statuses["no_repartition"]), False
    if not present(row.get("join_shape_id")) or not present(row.get("distribution_key")):
        return str(statuses["missing_semantics"]), False
    if truthy(row.get("join_uses_distribution_key")):
        return str(statuses["current_distribution_key"]), False
    return str(statuses["candidate"]), True


def build_eligibility(
    training: pd.DataFrame,
    execution: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    required = [
        "query_run_id",
        "join_shape_id",
        "distribution_key",
        "join_uses_distribution_key",
        "citus_repartition_observed_v2",
        "remote_citus_map_merge_job_count_sum",
    ]
    missing = sorted(set(required) - set(execution.columns))
    if missing:
        raise ValueError(f"Execution evidence is missing fields: {missing}")
    metadata = [
        "query_run_id",
        "pair_id",
        "variant",
        "template_id",
        "dataset_profile_id",
        "intervention_role",
        "mitigation_action",
    ]
    available_metadata = [name for name in metadata if name in training.columns]
    rows = training[available_metadata].merge(
        execution[required].drop_duplicates("query_run_id"),
        on="query_run_id",
        how="left",
        validate="one_to_one",
    )
    classified = rows.apply(lambda row: classify(row, contract), axis=1)
    rows["eligibility_status"] = classified.map(lambda value: value[0])
    rows["colocation_review_candidate"] = classified.map(lambda value: value[1])
    rows["decision_scope"] = "query_level_review_candidate"
    rows["workload_wide_redistribution_safe"] = False
    return rows


def controlled_validation(
    eligibility: pd.DataFrame,
    pairs: pd.DataFrame,
    contract: dict[str, Any],
) -> dict[str, Any]:
    validation = contract["controlled_validation"]
    pair_ids = set(
        pairs.loc[
            pairs["mitigation_action"].eq(validation["positive_action"])
            & pairs["intervention_role"].eq("positive_case"),
            "pair_id",
        ].astype(str)
    )
    source = eligibility[eligibility["pair_id"].astype(str).isin(pair_ids)]
    positive = source[source["variant"].eq(validation["positive_variant"])]
    negative = source[source["variant"].eq(validation["negative_variant"])]
    positive_candidates = int(positive["colocation_review_candidate"].sum())
    negative_candidates = int(negative["colocation_review_candidate"].sum())
    passed = (
        positive_candidates == len(positive)
        and negative_candidates == 0
        and len(positive) > 0
        and len(negative) > 0
    )
    return {
        "gate": "GO" if passed else "FAIL",
        "pair_count": len(pair_ids),
        "positive_execution_count": len(positive),
        "positive_candidate_count": positive_candidates,
        "negative_execution_count": len(negative),
        "negative_candidate_count": negative_candidates,
    }


def write_report(
    out_dir: Path,
    eligibility: pd.DataFrame,
    validation: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    counts = eligibility["eligibility_status"].value_counts().to_dict()
    report = f"""# Deterministička podobnost za colocation pregled

## Značenje

Ovaj sloj ne predviđa dobitak i ne mijenja distribuciju tabela. Iz SQL/šema
metapodataka i regionalnog Citus plana utvrđuje samo da li je opažen
repartition join koji ne koristi trenutni distribucijski ključ. Takav upit je
kandidat za DBA pregled akcije `use_colocated_distribution`.

Status kandidata ne dokazuje da je redistribucija sigurna za cijeli workload.
Potrebna je provjera ostalih upita, ograničenja ključeva i troška migracije.

## Pravilo

- opažen `MapMerge` ili verzionisani repartition signal
- poznat oblik spajanja i trenutni distribucijski ključ
- join ne koristi trenutni distribucijski ključ
- sirovi SQL i identifikatori nisu ulaz regresora

## Kontrolisana provjera

- Gate: `{validation["gate"]}`
- Parovi: `{validation["pair_count"]}`
- Opterećena izvršenja označena kao kandidati:
  `{validation["positive_candidate_count"]}/{validation["positive_execution_count"]}`
- Ublažena izvršenja pogrešno označena kao kandidati:
  `{validation["negative_candidate_count"]}/{validation["negative_execution_count"]}`

## Svi primarni redovi

```json
{json.dumps(counts, indent=2, sort_keys=True)}
```

Regresijski model smije se pozvati tek nakon ovog eligibility sloja i dodatne
semantičke provjere promjene distribucije.
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")


def write_checksums(out_dir: Path) -> None:
    paths = sorted(
        path for path in out_dir.iterdir() if path.is_file() and path.name != "checksums.sha256"
    )
    lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in paths]
    (out_dir / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    package_dir = args.package_dir.resolve()
    audit_dir = args.action_audit_dir.resolve()
    out_dir = args.out_dir.resolve()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[ELIGIBILITY 1/4] loading execution and intervention evidence", flush=True)
    training = read_csv(package_dir / "training_execution_view.csv")
    execution = read_csv(package_dir / "_index/execution_features.csv")
    pairs = read_csv(audit_dir / "mitigation_pair_audit.csv")

    print("[ELIGIBILITY 2/4] applying deterministic candidate rule", flush=True)
    eligibility = build_eligibility(training, execution, contract)
    validation = controlled_validation(eligibility, pairs, contract)
    if validation["gate"] != "GO":
        raise ValueError(f"Controlled eligibility validation failed: {validation}")

    print("[ELIGIBILITY 3/4] writing evidence and report", flush=True)
    eligibility.to_csv(out_dir / "execution_eligibility.csv", index=False)
    (out_dir / "eligibility_manifest.json").write_text(
        json.dumps(
            {
                "contract_version": contract["contract_version"],
                "program_id": contract["program_id"],
                "mitigation_action": contract["mitigation_action"],
                "execution_count": len(eligibility),
                "candidate_count": int(eligibility["colocation_review_candidate"].sum()),
                "controlled_validation": validation,
                "model_invocation_requires_candidate": True,
                "workload_wide_safety_proven": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    write_report(out_dir, eligibility, validation, contract)

    print("[ELIGIBILITY 4/4] writing checksums", flush=True)
    write_checksums(out_dir)
    print(out_dir / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
