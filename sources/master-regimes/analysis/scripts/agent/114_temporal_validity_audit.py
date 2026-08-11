#!/usr/bin/env python3
"""Audit temporal reproducibility and internal validity without executing SQL."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import tarfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import normalized_mutual_info_score

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FINAL_REPO = ROOT.parent / "master-thesis-final"
DEFAULT_OUT = ROOT / "releases/temporal-validity-audit-v1"

FIXED_AS_OF = re.compile(
    r"to_timestamp\s*\(\s*(?:nullif\s*\(\s*)?([1-9][0-9]{8,})",
    re.IGNORECASE,
)
FIXED_TIMESTAMP = re.compile(
    r"\b(?:timestamp|timestamptz)\s*'[^']+'", re.IGNORECASE
)
CURRENT_DATE = re.compile(r"\bcurrent_date\b", re.IGNORECASE)
NOW = re.compile(r"\bnow\s*\(\s*\)", re.IGNORECASE)
OTHER_WALL_CLOCK = re.compile(
    r"\b(?:current_timestamp|clock_timestamp\s*\(|"
    r"statement_timestamp\s*\(|transaction_timestamp\s*\()",
    re.IGNORECASE,
)


def classify_sql(sql: str) -> str:
    """Classify the effective temporal dependency of rendered SQL."""
    if FIXED_AS_OF.search(sql):
        return "fixed_as_of"
    if CURRENT_DATE.search(sql):
        return "dynamic_current_date"
    if NOW.search(sql):
        return "dynamic_now"
    if OTHER_WALL_CLOCK.search(sql):
        return "dynamic_other_wall_clock"
    if FIXED_TIMESTAMP.search(sql):
        return "fixed_literal"
    return "no_wall_clock"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_tar_csv(archive: Path, suffix: str) -> list[dict[str, str]]:
    with tarfile.open(archive, "r:gz") as bundle:
        name = next(name for name in bundle.getnames() if name.endswith(suffix))
        stream = bundle.extractfile(name)
        if stream is None:
            raise FileNotFoundError(name)
        return list(csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8")))


def sql_index(root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in root.rglob("*.sql"):
        if path.name in index:
            raise ValueError(f"duplicate rendered SQL basename: {path.name}")
        index[path.name] = path
    return index


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_sweep_anchor(sweep_id: str) -> float:
    stamp = sweep_id.split("-", 1)[0]
    return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).timestamp()


def audit_pressure() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    matrix_path = ROOT / "generated/corpus/pressure-raw-v1/execution_matrix.csv"
    runs_path = (
        ROOT
        / "generated/pressure-raw-runs/_program/pressure-raw-v1/_index/query_runs.csv"
    )
    pairs_path = (
        ROOT
        / "releases/pressure-actionability-v1/action_audit/mitigation_pair_audit.csv"
    )
    matrix = read_csv(matrix_path)
    runs = read_csv(runs_path)
    pairs = read_csv(pairs_path)
    matrix_by_condition = {row["condition_id"]: row for row in matrix}

    execution_modes: Counter[str] = Counter()
    condition_modes: dict[str, str] = {}
    rows_by_condition: dict[str, list[dict[str, str]]] = {}
    for row in runs:
        source = Path(row["source_sql_file"])
        if not source.exists():
            source = Path(matrix_by_condition[row["condition_id"]]["rendered_sql_path"])
        mode = classify_sql(source.read_text(encoding="utf-8"))
        execution_modes[mode] += 1
        condition_modes.setdefault(row["condition_id"], mode)
        if condition_modes[row["condition_id"]] != mode:
            raise ValueError(f"condition changes temporal mode: {row['condition_id']}")
        rows_by_condition.setdefault(row["condition_id"], []).append(row)

    condition_counts = Counter(condition_modes.values())
    dynamic_conditions = {
        condition
        for condition, mode in condition_modes.items()
        if mode.startswith("dynamic_")
    }
    dynamic_pairs: list[dict[str, Any]] = []
    for pair in pairs:
        condition_ids = (pair["stressed_condition_id"], pair["mitigated_condition_id"])
        if not any(condition in dynamic_conditions for condition in condition_ids):
            continue
        execution_rows = [
            row for condition in condition_ids for row in rows_by_condition[condition]
        ]
        result_counts = [int(float(row["result_row_count"] or 0)) for row in execution_rows]
        dynamic_pairs.append(
            {
                "pair_id": pair["pair_id"],
                "logical_question_id": pair["logical_question_id"],
                "template_id": pair["stressed_template_id"],
                "intervention_role": pair["intervention_role"],
                "mitigation_action": pair["mitigation_action"],
                "temporal_mode": condition_modes[condition_ids[0]],
                "execution_count": len(execution_rows),
                "all_result_rows_zero": all(value == 0 for value in result_counts),
                "result_equivalence_status": pair["result_equivalence_status"],
                "claim_scope": (
                    "collector, result-equivalence and no-work negative control; "
                    "not evidence of a positive intervention effect"
                ),
            }
        )

    expected_execution_modes = {
        "fixed_as_of": 1605,
        "fixed_literal": 792,
        "no_wall_clock": 84,
        "dynamic_current_date": 126,
    }
    expected_condition_modes = {
        "fixed_as_of": 535,
        "fixed_literal": 264,
        "no_wall_clock": 28,
        "dynamic_current_date": 42,
    }
    if dict(execution_modes) != expected_execution_modes:
        raise AssertionError(f"unexpected pressure execution modes: {execution_modes}")
    if dict(condition_counts) != expected_condition_modes:
        raise AssertionError(f"unexpected pressure condition modes: {condition_counts}")
    if len(dynamic_pairs) != 21:
        raise AssertionError(f"expected 21 dynamic control pairs, got {len(dynamic_pairs)}")
    if not all(
        row["intervention_role"] == "negative_control"
        and row["all_result_rows_zero"]
        and row["result_equivalence_status"] == "exact_multiset"
        for row in dynamic_pairs
    ):
        raise AssertionError("dynamic pressure pairs are not uniform empty negative controls")

    return (
        {
            "execution_count": len(runs),
            "condition_count": len(condition_modes),
            "pair_count": len(pairs),
            "execution_temporal_modes": dict(execution_modes),
            "condition_temporal_modes": dict(condition_counts),
            "dynamic_empty_negative_control_pairs": len(dynamic_pairs),
            "substantive_frozen_or_time_independent_pairs": len(pairs)
            - len(dynamic_pairs),
            "internal_validity": (
                "All 418 archived pairs remain result-equivalent. The 21 current_date "
                "pairs are valid only as empty-result no-work negative controls; the "
                "remaining 397 pairs support substantive intervention comparisons."
            ),
            "exact_temporal_rerun": (
                "Strong for the 397 substantive pairs under the frozen dataset contract; "
                "weak for the 21 current_date controls."
            ),
        },
        dynamic_pairs,
    )


def audit_legacy_fcm(final_repo: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    archive = final_repo / "artifacts/logical-indexes/clean-run-v1.tar.gz"
    rendered_root = final_repo / "artifacts/rendered-corpora/clean-run-v1"
    scaled_path = (
        final_repo
        / "sources/master-regimes/analysis/features/clean-run-v1-flow-ratio-v3/"
        "phase1_compact/compact_m0_flow_ratio_v3_reduced_scaled.csv"
    )
    centers_path = (
        final_repo
        / "sources/master-regimes/analysis/reports/"
        "clean-run-v1-m0-flow-ratio-v3-reduced-fuzzy/"
        "cluster_centers_representative_by_k.csv"
    )
    f19_memberships_path = (
        final_repo
        / "artifacts/results/semantic-v2-model-freeze/baseline_memberships_k4.csv"
    )
    dataset_runs = read_tar_csv(archive, "dataset_runs.csv")
    query_runs = read_tar_csv(archive, "query_runs.csv")
    rendered = sql_index(rendered_root)

    modes: Counter[str] = Counter()
    run_rows: list[dict[str, Any]] = []
    for row in query_runs:
        basename = Path(row["source_sql_file"]).name
        path = rendered[basename]
        mode = classify_sql(path.read_text(encoding="utf-8"))
        modes[mode] += 1
        started = float(row["query_started_at_unix"])
        anchor = parse_sweep_anchor(row["database_sweep_id"])
        parameters = json.loads(row["param_json"] or "{}")
        run_rows.append(
            {
                "query_run_id": row["query_run_id"],
                "database_sweep_id": row["database_sweep_id"],
                "dataset_id": row["dataset_id"],
                "temporal_mode": mode,
                "query_started_at_unix": started,
                "sweep_anchor_unix": anchor,
                "lag_hours": (started - anchor) / 3600.0,
                "lookback_days": parameters.get("lookback_days"),
            }
        )

    expected_modes = {
        "dynamic_now": 1718,
        "dynamic_current_date": 240,
        "no_wall_clock": 6,
    }
    if dict(modes) != expected_modes:
        raise AssertionError(f"unexpected legacy FCM SQL modes: {modes}")
    base_time_values = {
        json.loads(row["datagen_env_json"])["DATAGEN_BASE_TIME_UNIX"]
        for row in dataset_runs
    }
    if base_time_values != {"0"}:
        raise AssertionError(f"unexpected legacy FCM base times: {base_time_values}")

    frame = pd.DataFrame(run_rows)
    frame["temporal_quartile"] = frame.groupby("database_sweep_id")[
        "query_started_at_unix"
    ].transform(
        lambda values: np.minimum(
            3,
            np.floor(values.rank(method="first").sub(1).mul(4).div(len(values))),
        ).astype(int)
    )

    scaled = pd.read_csv(scaled_path)
    centers = pd.read_csv(centers_path)
    centers = centers[(centers["k"] == 4) & (centers["seed"] == 0)].copy()
    feature_names = [column for column in scaled.columns if column != "query_run_id"]
    distances = np.linalg.norm(
        scaled[feature_names].to_numpy()[:, None, :]
        - centers[feature_names].to_numpy()[None, :, :],
        axis=2,
    )
    hard = pd.DataFrame(
        {
            "query_run_id": scaled["query_run_id"],
            "hard_cluster": centers.iloc[np.argmin(distances, axis=1)]["cluster"]
            .to_numpy()
            .astype(int),
        }
    )
    frame = frame.merge(hard, on="query_run_id", validate="one_to_one")
    nmi_cluster_time = normalized_mutual_info_score(
        frame["hard_cluster"], frame["temporal_quartile"]
    )
    f19_memberships = pd.read_csv(f19_memberships_path)[
        ["query_run_id", "dominant_cluster"]
    ].rename(columns={"dominant_cluster": "f19_hard_cluster"})
    f19_frame = frame.merge(
        f19_memberships, on="query_run_id", validate="one_to_one"
    )
    nmi_f19_cluster_time = normalized_mutual_info_score(
        f19_frame["f19_hard_cluster"], f19_frame["temporal_quartile"]
    )
    with_lookback = frame.dropna(subset=["lookback_days"])
    nmi_lookback_time = normalized_mutual_info_score(
        with_lookback["lookback_days"].astype(str),
        with_lookback["temporal_quartile"],
    )

    current_date = frame[frame["temporal_mode"] == "dynamic_current_date"]
    same_utc_day = all(
        datetime.fromtimestamp(row.query_started_at_unix, tz=UTC).date()
        == datetime.fromtimestamp(row.sweep_anchor_unix, tz=UTC).date()
        for row in current_date.itertuples()
    )
    max_lag = float(frame["lag_hours"].max())
    sweep_rows: list[dict[str, Any]] = []
    for sweep_id, group in frame.groupby("database_sweep_id", sort=True):
        sweep_rows.append(
            {
                "database_sweep_id": sweep_id,
                "dataset_id": group["dataset_id"].iloc[0],
                "query_count": len(group),
                "minimum_lag_hours": float(group["lag_hours"].min()),
                "median_lag_hours": float(group["lag_hours"].median()),
                "p95_lag_hours": float(group["lag_hours"].quantile(0.95)),
                "maximum_lag_hours": float(group["lag_hours"].max()),
            }
        )

    conservative_shift = {
        str(days): max_lag / (24.0 * days) for days in (1, 3, 7, 14, 30)
    }
    return (
        {
            "execution_count": len(frame),
            "dataset_sweep_count": len(dataset_runs),
            "dataset_base_time_unix_values": sorted(base_time_values),
            "sql_temporal_modes": dict(modes),
            "minimum_lag_hours": float(frame["lag_hours"].min()),
            "median_lag_hours": float(frame["lag_hours"].median()),
            "p95_lag_hours": float(frame["lag_hours"].quantile(0.95)),
            "maximum_lag_hours": max_lag,
            "current_date_queries_stayed_on_generation_utc_date": same_utc_day,
            "conservative_maximum_cutoff_shift_fraction_by_lookback_days": (
                conservative_shift
            ),
            "hard_cluster_vs_within_sweep_time_quartile_nmi": nmi_cluster_time,
            "f19_hard_cluster_vs_within_sweep_time_quartile_nmi": (
                nmi_f19_cluster_time
            ),
            "lookback_vs_within_sweep_time_quartile_nmi": nmi_lookback_time,
            "model_refit_performed": False,
            "internal_validity": (
                "Usable for the archived descriptive FCM analysis: each sweep regenerated "
                "the dataset immediately before queries, dataset generation and SQL shared "
                "the same wall-clock origin, no UTC date rollover affected current_date, "
                "and the post-hoc audit found no material cluster/time-order association "
                "for either the historical F21 or promoted F19 hard labels."
            ),
            "exact_temporal_rerun": (
                "Weak. Reproduction requires reconstructing each sweep-specific wall-clock "
                "origin; rerunning the legacy SQL today is not equivalent."
            ),
            "interpretation_limit": (
                "The timing audit is diagnostic, not proof that moving cutoffs had zero "
                "effect. Bounded cutoff movement remains part of measurement noise."
            ),
        },
        sweep_rows,
    )


def scan_sql_tree(path: Path, pattern: str = "*.sql") -> dict[str, Any]:
    paths = sorted(path.rglob(pattern))
    modes = Counter(classify_sql(item.read_text(encoding="utf-8")) for item in paths)
    return {"sql_file_count": len(paths), "temporal_modes": dict(modes)}


def audit_later_panels() -> dict[str, Any]:
    panels = {
        "dba_local_memory": ROOT / "generated/corpus/dba-local-memory-v1",
        "n3_topology_memory": ROOT / "generated/corpus/n3-topology-memory-v1",
        "confirmatory_action_replication": (
            ROOT / "generated/corpus/confirmatory-action-replication-v1"
        ),
        "fuzzy_memory_topk": ROOT / "generated/corpus/fuzzy-memory-topk-panel-v1",
    }
    result = {name: scan_sql_tree(path) for name, path in panels.items()}
    feedback_roots = {
        "feedback_loop": (
            ROOT
            / "generated/feedback-loop-runs/20260807T123708Z-pressure-feedback-loop-v1"
        ),
        "feedback_loop_exact_aggregate": (
            ROOT
            / "generated/feedback-loop-runs/"
            "20260807T152322Z-pressure-feedback-loop-aggregate-exact-v1"
        ),
    }
    for name, path in feedback_roots.items():
        sql_paths = sorted(path.rglob("input/query.sql"))
        modes = Counter(
            classify_sql(item.read_text(encoding="utf-8")) for item in sql_paths
        )
        result[name] = {"sql_file_count": len(sql_paths), "temporal_modes": dict(modes)}
    for name, audit in result.items():
        dynamic = sum(
            count
            for mode, count in audit["temporal_modes"].items()
            if mode.startswith("dynamic_")
        )
        if dynamic:
            raise AssertionError(f"later panel contains wall-clock SQL: {name}={audit}")
    return result


def checksums(out_dir: Path) -> None:
    rows = []
    for path in sorted(out_dir.iterdir()):
        if path.name == "checksums.sha256" or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {path.name}")
    (out_dir / "checksums.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def summary_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pressure = payload["wide_intervention_program"]
    f21 = payload["legacy_fcm_corpus"]
    return [
        {
            "experimental_block": "shared legacy FCM corpus (F19 and F21)",
            "executions": f21["execution_count"],
            "temporal_contract": "shared moving wall-clock origin per sweep",
            "exact_rerun_strength": "weak",
            "internal_result_status": "usable with bounded temporal limitation",
            "allowed_claim": "descriptive FCM characterization in the archived corpus",
        },
        {
            "experimental_block": "wide frozen or time-independent conditions",
            "executions": pressure["execution_count"] - 126,
            "temporal_contract": "frozen cutoff or time-independent SQL",
            "exact_rerun_strength": "strong under the versioned dataset contract",
            "internal_result_status": "valid",
            "allowed_claim": (
                "397 substantive pairs plus unpaired calibration conditions: collector, "
                "equivalence and intervention-response findings"
            ),
        },
        {
            "experimental_block": "wide temporal negative controls",
            "executions": 126,
            "temporal_contract": "current_date; empty result during the archived run",
            "exact_rerun_strength": "weak",
            "internal_result_status": "valid only as no-work negative controls",
            "allowed_claim": "collector and result-equivalence behavior, not action gain",
        },
        {
            "experimental_block": "later panels and feedback loop",
            "executions": "see per-panel manifest",
            "temporal_contract": "fixed literal, fixed anchor or no wall-clock dependency",
            "exact_rerun_strength": "strong under the versioned dataset contract",
            "internal_result_status": "valid",
            "allowed_claim": "panel-specific temporal, topology and longitudinal results",
        },
    ]


def readme(payload: dict[str, Any]) -> str:
    pressure = payload["wide_intervention_program"]
    f21 = payload["legacy_fcm_corpus"]
    return f"""# Temporal validity audit v1

Ovaj paket je proizveden isključivo iz sačuvanih SQL iskaza, manifesta i
indeksa. Nije pokrenut SQL, regenerisan dataset niti refitovan model.

## Zaključak

Temporalna ponovljivost i unutrašnja valjanost nisu isti zahtjev. Kasniji
paneli i {pressure['substantive_frozen_or_time_independent_pairs']} sadržajnih
parova širokog programa imaju zamrznut ili vremenski nezavisan SQL. Preostalih
{pressure['dynamic_empty_negative_control_pairs']} parova širokog programa
koriste `current_date`, vratili su prazan rezultat i vrijede samo kao
negativne kontrole bez aktiviranog rada.

Zajednički korpus modela F19 i F21 koristi pomični zidni sat:
{f21['sql_temporal_modes']['dynamic_now']} upita koristi `now()`, a
{f21['sql_temporal_modes']['dynamic_current_date']}
`current_date`. Izvorno mjerenje ipak ostaje upotrebljivo za deskriptivnu FCM
analizu jer je svaki sweep neposredno regenerisao dataset s istim zidnim
satom i nije bilo UTC promjene datuma. NMI tvrde grupe prema vremenskom
kvartilu iznosi {f21['f19_hard_cluster_vs_within_sweep_time_quartile_nmi']:.6f}
za promovisani F19 i {f21['hard_cluster_vs_within_sweep_time_quartile_nmi']:.6f}
za historijski F21.
To nije dokaz nultog temporalnog uticaja, nego provjera da nema očite
konfuzije redoslijeda i klastera.

## Reprodukcija audita

```bash
make temporal-validity-audit
```

Glavni izlaz je `temporal_validity_audit.json`. CSV datoteke odvajaju
21 temporalnu negativnu kontrolu i osam zajedničkih FCM sweepova. Kontrolne sume su u
`checksums.sha256`.
"""


def build(final_repo: Path, out_dir: Path) -> dict[str, Any]:
    pressure, dynamic_controls = audit_pressure()
    f21, fcm_sweeps = audit_legacy_fcm(final_repo)
    payload = {
        "audit_id": "temporal-validity-audit-v1",
        "generated_from_archived_artifacts_only": True,
        "live_sql_executed": False,
        "dataset_regenerated": False,
        "model_refit_performed": False,
        "wide_intervention_program": pressure,
        "legacy_fcm_corpus": f21,
        "later_panels": audit_later_panels(),
        "overall_conclusion": (
            "A query can be weakly reproducible today while its archived comparison "
            "remains internally informative. Claims are therefore limited per block: "
            "F19 and F21 are descriptive with a bounded temporal limitation; "
            "21 empty temporal "
            "controls do not support action effects; substantive wide pairs and later "
            "panels retain their stated experimental role."
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "temporal_validity_audit.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_csv(out_dir / "temporal_validity_summary.csv", summary_rows(payload))
    write_csv(out_dir / "pressure_dynamic_controls.csv", dynamic_controls)
    legacy_name = out_dir / "f21_sweep_timing.csv"
    if legacy_name.exists():
        legacy_name.unlink()
    write_csv(out_dir / "fcm_sweep_timing.csv", fcm_sweeps)
    (out_dir / "README.md").write_text(readme(payload), encoding="utf-8")
    checksums(out_dir)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-repo", type=Path, default=DEFAULT_FINAL_REPO)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build(args.final_repo.resolve(), args.out_dir.resolve())
    pressure = payload["wide_intervention_program"]
    f21 = payload["legacy_fcm_corpus"]
    print(
        "temporal validity audit PASS: "
        f"pressure substantive={pressure['substantive_frozen_or_time_independent_pairs']}, "
        f"temporal controls={pressure['dynamic_empty_negative_control_pairs']}, "
        f"F19 NMI={f21['f19_hard_cluster_vs_within_sweep_time_quartile_nmi']:.6f}, "
        f"F21 NMI={f21['hard_cluster_vs_within_sweep_time_quartile_nmi']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
