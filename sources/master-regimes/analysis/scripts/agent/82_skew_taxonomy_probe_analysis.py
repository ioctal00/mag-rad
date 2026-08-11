from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(float("nan"), index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def condition_id(value: Any) -> str:
    text = str(value)
    for prefix in ("B-", "C-"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.split("__dataset-", maxsplit=1)[0]


def read_query_rows(index_dir: Path) -> pd.DataFrame:
    path = index_dir / "execution_features.csv"
    if not path.exists():
        path = index_dir / "query_runs.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, low_memory=False).copy()
    if not frame["execution_status"].astype(str).eq("completed").all():
        incomplete = frame.loc[
            ~frame["execution_status"].astype(str).eq("completed"),
            ["query_run_id", "execution_status"],
        ]
        raise ValueError(f"Incomplete probe rows:\n{incomplete.to_string(index=False)}")
    return frame.assign(
        probe_condition_id=frame["corpus_cell_id"].map(condition_id)
    )


def select_evidence(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "probe_source",
        "placement_state",
        "dataset_id",
        "probe_condition_id",
        "query_run_id",
        "elapsed_seconds",
        "task_count",
        "worker_task_plan_count",
        "worker_task_nonzero_scan_count",
        "worker_task_nonzero_scan_share",
        "worker_task_scan_skew_applicable",
        "worker_task_scan_skew_applicable_region_count",
        "worker_task_active_scan_rows_isf_normalized",
        "worker_task_active_scan_skew_applicable",
        "worker_task_within_region_active_scan_rows_isf_normalized_max",
        "worker_task_tuple_bytes_sum",
        "worker_task_tuple_bytes_cv",
        "worker_task_tuple_bytes_isf_normalized",
        "worker_task_tuple_bytes_skew_applicable",
        "worker_task_within_region_tuple_bytes_isf_normalized_max",
        "worker_task_within_region_scan_rows_cv_max",
        "worker_task_within_region_scan_rows_isf_max",
        "worker_task_within_region_scan_rows_isf_normalized_max",
        "worker_scan_rows_skew_applicable",
        "worker_scan_rows_skew_applicable_region_count",
        "worker_task_within_region_worker_scan_rows_cv_max",
        "worker_task_within_region_worker_scan_rows_isf_max",
        "worker_task_within_region_worker_scan_rows_isf_normalized_max",
        "worker_task_count_cv",
        "worker_task_count_isf",
        "worker_scan_rows_cv",
        "worker_scan_rows_isf",
        "worker_task_actual_time_isf",
        "result_multiset_sha256",
    ]
    result = frame.copy()
    for column in columns:
        if column not in result:
            result[column] = ""
    return result[columns]


def data_probe_rows(index_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    queries = read_query_rows(index_dir)
    queries = queries.assign(
        probe_source="data_frequency_calibration",
        placement_state="default_uncontrolled_for_worker_claim",
    )
    audits_path = index_dir / "dataset_capability_audits.csv"
    audits = pd.read_csv(audits_path, low_memory=False)
    for column in (
        "events_cv",
        "max_to_mean_ratio",
        "top1_event_share",
        "top5_event_share",
    ):
        audits[column] = numeric(audits, column)
    dataset_summary = (
        audits.groupby("dataset_id", as_index=False)
        .agg(
            region_count=("region", "nunique"),
            events_cv_mean=("events_cv", "mean"),
            events_cv_max=("events_cv", "max"),
            max_to_mean_ratio_max=("max_to_mean_ratio", "max"),
            top1_event_share_max=("top1_event_share", "max"),
            top5_event_share_max=("top5_event_share", "max"),
        )
        .sort_values("dataset_id")
    )
    return select_evidence(queries), dataset_summary


def data_activation_matrix(rows: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "dataset_id",
        "probe_condition_id",
        "worker_task_nonzero_scan_share",
        "worker_task_within_region_scan_rows_isf_normalized_max",
        "worker_task_within_region_active_scan_rows_isf_normalized_max",
        "worker_task_within_region_tuple_bytes_isf_normalized_max",
        "worker_task_within_region_worker_scan_rows_isf_normalized_max",
        "worker_task_scan_skew_applicable",
        "worker_scan_rows_skew_applicable",
    ]
    return rows[columns].sort_values(["probe_condition_id", "dataset_id"])


def placement_probe_rows(run_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest_path = run_dir / "capability_smoke_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames: list[pd.DataFrame] = []
    for state in ("B", "C"):
        index_dir = Path(manifest["query_sweeps"][state]["index_dir"])
        frame = read_query_rows(index_dir)
        frames.append(
            frame.assign(
                probe_source="same_data_placement_intervention",
                placement_state=state,
            )
        )
    return select_evidence(pd.concat(frames, ignore_index=True)), manifest


def paired_placement(rows: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        "elapsed_seconds",
        "worker_task_within_region_scan_rows_isf_normalized_max",
        "worker_task_within_region_active_scan_rows_isf_normalized_max",
        "worker_task_within_region_tuple_bytes_isf_normalized_max",
        "worker_task_within_region_worker_scan_rows_isf_normalized_max",
        "worker_task_count_isf",
        "worker_scan_rows_isf",
    ]
    paired_rows: list[dict[str, Any]] = []
    for condition, group in rows.groupby("probe_condition_id"):
        by_state = {
            state: group[group["placement_state"].eq(state)].iloc[0]
            for state in ("B", "C")
        }
        row: dict[str, Any] = {
            "probe_condition_id": condition,
            "result_signature_equal": (
                str(by_state["B"]["result_multiset_sha256"])
                == str(by_state["C"]["result_multiset_sha256"])
            ),
            "task_skew_applicable_b": truthy(
                by_state["B"]["worker_task_scan_skew_applicable"]
            ),
            "task_skew_applicable_c": truthy(
                by_state["C"]["worker_task_scan_skew_applicable"]
            ),
            "worker_skew_applicable_b": truthy(
                by_state["B"]["worker_scan_rows_skew_applicable"]
            ),
            "worker_skew_applicable_c": truthy(
                by_state["C"]["worker_scan_rows_skew_applicable"]
            ),
            "task_time_available_b": pd.notna(
                pd.to_numeric(
                    by_state["B"]["worker_task_actual_time_isf"],
                    errors="coerce",
                )
            ),
            "task_time_available_c": pd.notna(
                pd.to_numeric(
                    by_state["C"]["worker_task_actual_time_isf"],
                    errors="coerce",
                )
            ),
        }
        for metric in metrics:
            b_value = pd.to_numeric(by_state["B"][metric], errors="coerce")
            c_value = pd.to_numeric(by_state["C"][metric], errors="coerce")
            row[f"b_{metric}"] = b_value
            row[f"c_{metric}"] = c_value
            row[f"delta_{metric}"] = c_value - b_value
        paired_rows.append(row)
    return pd.DataFrame(paired_rows).sort_values("probe_condition_id")


def fmt(value: Any, digits: int = 3) -> str:
    number = pd.to_numeric(value, errors="coerce")
    return "N/A" if pd.isna(number) else f"{float(number):.{digits}f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze bounded data/task/worker skew probes."
    )
    parser.add_argument("--data-index", type=Path, required=True)
    parser.add_argument("--placement-run", type=Path, required=True)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("analysis/reports/skew-taxonomy-probe-v1"),
    )
    args = parser.parse_args()

    data_rows, dataset_summary = data_probe_rows(args.data_index.resolve())
    data_activation = data_activation_matrix(data_rows)
    placement_rows, placement_manifest = placement_probe_rows(
        args.placement_run.resolve()
    )
    all_rows = pd.concat([data_rows, placement_rows], ignore_index=True)
    pairs = paired_placement(placement_rows)

    broad = pairs[pairs["probe_condition_id"].eq("broad_all_shards")]
    hot = pairs[pairs["probe_condition_id"].eq("hot_key_range")]
    pruning = pairs[
        pairs["probe_condition_id"].str.contains("pruning_control", regex=False)
    ]
    positive = pd.concat([broad, hot], ignore_index=True)
    placement_worker_delta = numeric(
        positive,
        "delta_worker_task_within_region_worker_scan_rows_isf_normalized_max",
    )
    placement_confirmed = (
        not positive.empty
        and positive["result_signature_equal"].all()
        and (placement_worker_delta > 0).all()
    )
    pruning_not_applicable = (
        not pruning.empty
        and not pruning[
            [
                "task_skew_applicable_b",
                "task_skew_applicable_c",
                "worker_skew_applicable_b",
                "worker_skew_applicable_c",
            ]
        ]
        .to_numpy()
        .any()
    )
    task_time_structurally_missing = not pairs[
        ["task_time_available_b", "task_time_available_c"]
    ].to_numpy().any()
    status = (
        "confirmed"
        if placement_confirmed and pruning_not_applicable
        else "needs_review"
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    all_rows.to_csv(args.out_dir / "skew_probe_observations.csv", index=False)
    dataset_summary.to_csv(
        args.out_dir / "dataset_skew_calibration.csv",
        index=False,
    )
    data_activation.to_csv(
        args.out_dir / "data_activation_matrix.csv",
        index=False,
    )
    pairs.to_csv(args.out_dir / "placement_contrasts.csv", index=False)
    summary = {
        "status": status,
        "data_probe_rows": len(data_rows),
        "placement_probe_rows": len(placement_rows),
        "placement_restore_status": placement_manifest.get("restore_status"),
        "placement_positive_cases_confirmed": bool(placement_confirmed),
        "pruning_controls_not_applicable": bool(pruning_not_applicable),
        "task_time_structurally_missing": bool(task_time_structurally_missing),
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Bounded skew taxonomy probe",
        "",
        f"- Status: `{status}`",
        f"- Data-frequency kalibracija: {len(data_rows)} izvršenja.",
        f"- B/C placement intervencija: {len(placement_rows)} izvršenja.",
        f"- Placement restore: `{placement_manifest.get('restore_status', '')}`.",
        "",
        "## Operativne definicije",
        "",
        "- **Data skew** je neravnomjerna frekvencija redova po logičkim "
        "ključevima/tenantima. Dataset audit ga mjeri prije SQL izvršenja.",
        "- **Task skew** je neravnomjeran broj obrađenih redova ili izlaznih "
        "bajtova među Citus taskovima jednog regiona.",
        "- **Worker skew** nastaje tek kada zbir rada taskova po workeru postane "
        "neravnomjeran. Task skew može postojati bez worker skewa.",
        "- Kod shard-pruned upita sa jednim aktivnim taskom/workerom po regionu "
        "skew nije nula, nego nije primjenjiv.",
        "",
        "## Dataset kalibracija",
        "",
        "| dataset | events CV (max) | max/mean | top-5 udio |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in dataset_summary.itertuples(index=False):
        lines.append(
            f"| `{row.dataset_id}` | {fmt(row.events_cv_max)} | "
            f"{fmt(row.max_to_mean_ratio_max)} | "
            f"{fmt(row.top5_event_share_max)} |"
        )
    lines.extend(
        [
            "",
            "## Aktivacija skewa kroz SQL",
            "",
            "| dataset | SQL uslov | aktivni taskovi | all-task rows | "
            "active-task rows | task output bytes | worker rows |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in data_activation.itertuples(index=False):
        lines.append(
            f"| `{row.dataset_id}` | `{row.probe_condition_id}` | "
            f"{fmt(row.worker_task_nonzero_scan_share)} | "
            f"{fmt(row.worker_task_within_region_scan_rows_isf_normalized_max)}"
            f" | "
            f"{fmt(row.worker_task_within_region_active_scan_rows_isf_normalized_max)}"
            f" | "
            f"{fmt(row.worker_task_within_region_tuple_bytes_isf_normalized_max)}"
            f" | "
            f"{fmt(row.worker_task_within_region_worker_scan_rows_isf_normalized_max)}"
            f" |"
        )
    lines.extend(
        [
            "",
            "## Placement kontrast",
            "",
            "| SQL uslov | all-task rows B -> C | active-task rows B -> C | "
            "task output bytes B -> C | "
            "worker rows B -> C | "
            "task primjenjiv | worker primjenjiv | rezultat isti |",
            "| --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in pairs.itertuples(index=False):
        lines.append(
            f"| `{row.probe_condition_id}` | "
            f"{fmt(row.b_worker_task_within_region_scan_rows_isf_normalized_max)}"
            f" -> "
            f"{fmt(row.c_worker_task_within_region_scan_rows_isf_normalized_max)}"
            f" | "
            f"{fmt(row.b_worker_task_within_region_active_scan_rows_isf_normalized_max)}"
            f" -> "
            f"{fmt(row.c_worker_task_within_region_active_scan_rows_isf_normalized_max)}"
            f" | "
            f"{fmt(row.b_worker_task_within_region_tuple_bytes_isf_normalized_max)}"
            f" -> "
            f"{fmt(row.c_worker_task_within_region_tuple_bytes_isf_normalized_max)}"
            f" | "
            f"{fmt(row.b_worker_task_within_region_worker_scan_rows_isf_normalized_max)}"
            f" -> "
            f"{fmt(row.c_worker_task_within_region_worker_scan_rows_isf_normalized_max)}"
            f" | {row.task_skew_applicable_b}/{row.task_skew_applicable_c}"
            f" | {row.worker_skew_applicable_b}/{row.worker_skew_applicable_c}"
            f" | {row.result_signature_equal} |"
        )
    lines.extend(
        [
            "",
            "## Zaključak za budući regresor",
            "",
            "Jedan zajednički `skew` target nije dovoljan. Raw corpus mora "
            "sačuvati najmanje tri odvojena targeta:",
            "",
            "1. dataset-level data-skew intenzitet iz capability audita",
            "2. task-level intenzitet iz raspodjele scan redova/bajtova",
            "3. worker-level intenzitet nakon agregacije taskova po workeru "
            "unutar regiona",
            "",
            "Dataset labela sama nije modelski target. SQL mora aktivirati "
            "neravnomjernost, a applicability mora biti istinita. "
            "Tenant-point kontrole zato ne proizvode lažni nulti skew.",
            "",
            "Task vrijeme u trenutnom coordinator auto_explain obliku nije "
            "dostupno po tasku. Ono ostaje missing, a ne nula. Regresor zato "
            "može koristiti row/byte intenzitete, dok time-based worker skew "
            "zahtijeva poseban worker-side vremenski ugovor.",
            "",
        ]
    )
    (args.out_dir / "README.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    print(args.out_dir / "README.md")
    return 0 if status == "confirmed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
