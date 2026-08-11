#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import numpy as np
import pandas as pd
from scipy.stats import kendalltau, spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error, ndcg_score, r2_score
from sklearn.neighbors import NearestNeighbors

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FREEZE = ROOT / "generated/model-freezes/colocation-ranking-before-n3-v1"
DEFAULT_INDEX = (
    ROOT.parent
    / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs"
    / "pressure-raw-v1-n3-colocation-holdout/_index"
)
DEFAULT_OUT = ROOT / "analysis/reports/pressure-raw-v1-n3-colocation-no-refit"
EXPECTED_REGIONS = {"eu", "us", "apac"}
FREEZE_FILES = {
    "ranking_contract": "colocation_ranking_v1.yml",
    "batch_contract": "batch-300-n3-holdout.yml",
    "corpus_manifest": "batch-300-n3-colocation-holdout.yml",
    "rendered_execution_plan": "corpus_execution_plan.yml",
    "model": "colocation_ranking_model.joblib",
    "benchmark_manifest": "benchmark_manifest.json",
    "training_pair_reference": "training_pair_reference.csv",
    "expected_executions": "expected_executions.csv",
}
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 41_003
BOOTSTRAP_CONFIDENCE = 0.95


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the frozen colocation ranker on the N=3 holdout."
    )
    parser.add_argument("--freeze-dir", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path, low_memory=False)


def verify_freeze(freeze_dir: Path) -> tuple[dict[str, Any], Any]:
    manifest_path = freeze_dir / "freeze_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("no_refit") is not True:
        raise ValueError("Freeze manifest does not enforce no-refit evaluation")
    if manifest.get("freeze_contract") != "colocation-ranking-before-n3-v1":
        raise ValueError("Unexpected freeze contract")
    for key, file_name in FREEZE_FILES.items():
        path = freeze_dir / file_name
        if not path.is_file():
            raise FileNotFoundError(path)
        expected_hash = str(manifest["source_sha256"][key])
        if sha256_file(path) != expected_hash:
            raise ValueError(f"Frozen input checksum mismatch: {file_name}")
    model = joblib.load(freeze_dir / FREEZE_FILES["model"])
    selected = [str(value) for value in manifest["selected_feature_names"]]
    if [str(value) for value in model.feature_names_in_] != selected:
        raise ValueError("Frozen model feature order differs from freeze manifest")
    return manifest, model


def normalized_set(values: pd.Series) -> set[str]:
    return {
        str(value).strip()
        for value in values.dropna()
        if str(value).strip() and str(value).strip().lower() != "nan"
    }


def validate_edge_topology(
    edge_rows: pd.DataFrame,
    coordinator_values: pd.Series,
) -> dict[str, Any]:
    source_set = normalized_set(edge_rows["source_cluster_id"])
    destination_set = normalized_set(edge_rows["destination_gac_id"])
    coordinator_set = normalized_set(coordinator_values)
    edge_set = normalized_set(edge_rows["edge_id"])
    expected_edge_set = {
        f"{source}->{destination}"
        for source in EXPECTED_REGIONS
        for destination in coordinator_set
    }
    complete = (
        len(edge_rows) == len(EXPECTED_REGIONS)
        and source_set == EXPECTED_REGIONS
        and len(destination_set) == 1
        and destination_set == coordinator_set
        and edge_set == expected_edge_set
    )
    return {
        "edge_ids": "|".join(sorted(edge_set)),
        "edge_source_region_ids": "|".join(sorted(source_set)),
        "edge_destination_gac_ids": "|".join(sorted(destination_set)),
        "edge_count": len(edge_set),
        "edges_complete": complete,
    }


def validate_sql_freeze(expected: pd.DataFrame) -> None:
    for row in expected.itertuples(index=False):
        path = Path(str(row.rendered_sql_path))
        if not path.is_file():
            raise FileNotFoundError(path)
        if sha256_file(path) != str(row.rendered_sql_sha256):
            raise ValueError(f"Rendered SQL changed after freeze: {path}")


def validate_execution_index(
    index_dir: Path,
    expected: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    query_runs = read_csv(index_dir / "query_runs.csv")
    execution = read_csv(index_dir / "execution_features.csv")
    regions = read_csv(index_dir / "region_fragments.csv")
    edges = read_csv(index_dir / "remote_edge_observations.csv")
    worker_tasks = read_csv(index_dir / "worker_task_fragments.csv")

    expected_slots = set(expected["execution_slot_id"].astype(str))
    query_runs["execution_slot_id"] = query_runs["execution_slot_id"].astype(str)
    observed_slots = set(query_runs["execution_slot_id"])
    if observed_slots != expected_slots:
        missing = sorted(expected_slots - observed_slots)
        extra = sorted(observed_slots - expected_slots)
        raise ValueError(f"N=3 slot mismatch; missing={missing}, extra={extra}")
    if len(query_runs) != 96 or query_runs["execution_slot_id"].duplicated().any():
        raise ValueError("Logical index must contain exactly 96 unique N=3 slots")
    if normalized_set(query_runs["execution_status"]) != {"completed"}:
        raise ValueError("All N=3 query runs must be completed")
    if query_runs["query_run_id"].duplicated().any():
        raise ValueError("Logical index contains duplicate query_run_id values")
    if len(execution) != 96 or execution["query_run_id"].duplicated().any():
        raise ValueError("Execution feature table must contain 96 unique rows")

    expected_metadata = expected[
        [
            "execution_slot_id",
            "pair_id",
            "condition_id",
            "variant",
            "repetition_index",
            "dataset_profile_id",
            "logical_question_id",
            "scenario_level",
        ]
    ].copy()
    observed = query_runs.merge(
        expected_metadata,
        on="execution_slot_id",
        how="inner",
        suffixes=("", "_frozen"),
        validate="one_to_one",
    )
    for column in ("pair_id", "condition_id", "variant", "dataset_profile_id"):
        if not observed[column].astype(str).eq(observed[f"{column}_frozen"].astype(str)).all():
            raise ValueError(f"Observed metadata differs from frozen {column}")

    topology_rows: list[dict[str, Any]] = []
    for query_run_id in observed["query_run_id"]:
        region_set = normalized_set(
            regions.loc[regions["query_run_id"].eq(query_run_id), "region_id"]
        )
        edge_status = validate_edge_topology(
            edges.loc[edges["query_run_id"].eq(query_run_id)],
            observed.loc[
                observed["query_run_id"].eq(query_run_id), "coordinator_node"
            ],
        )
        worker_region_set = normalized_set(
            worker_tasks.loc[
                worker_tasks["query_run_id"].eq(query_run_id), "fdw_region"
            ]
        )
        topology_rows.append(
            {
                "query_run_id": query_run_id,
                "region_ids": "|".join(sorted(region_set)),
                "worker_task_region_ids": "|".join(sorted(worker_region_set)),
                "region_count": len(region_set),
                "worker_task_region_count": len(worker_region_set),
                "regions_complete": region_set == EXPECTED_REGIONS,
                "worker_regions_complete": worker_region_set == EXPECTED_REGIONS,
                **edge_status,
            }
        )
    topology = pd.DataFrame(topology_rows)
    complete_columns = [
        "regions_complete",
        "edges_complete",
        "worker_regions_complete",
    ]
    if not topology[complete_columns].all().all():
        failed = topology.loc[~topology[complete_columns].all(axis=1), "query_run_id"]
        raise ValueError(f"Incomplete N=3 child evidence: {failed.tolist()}")
    return observed, execution, topology


def validate_result_equivalence(observed: pd.DataFrame) -> pd.DataFrame:
    signed = observed.dropna(subset=["result_multiset_sha256"]).copy()
    rows: list[dict[str, Any]] = []
    for pair_id, _group in observed.groupby("pair_id", sort=True):
        pair_signed = signed[signed["pair_id"].eq(pair_id)]
        hashes = {
            variant: normalized_set(
                pair_signed.loc[
                    pair_signed["variant"].eq(variant), "result_multiset_sha256"
                ]
            )
            for variant in ("stressed", "mitigated")
        }
        comparable = all(len(value) == 1 for value in hashes.values())
        equivalent = comparable and hashes["stressed"] == hashes["mitigated"]
        rows.append(
            {
                "pair_id": pair_id,
                "stressed_signature_count": len(hashes["stressed"]),
                "mitigated_signature_count": len(hashes["mitigated"]),
                "comparable": comparable,
                "equivalent": equivalent,
            }
        )
    result = pd.DataFrame(rows)
    if len(result) != 16 or not result["equivalent"].all():
        raise ValueError("All 16 N=3 pairs must have equivalent result signatures")
    return result


def build_pair_matrix(
    observed: pd.DataFrame,
    execution: pd.DataFrame,
    feature_names: list[str],
) -> pd.DataFrame:
    missing = sorted(set(feature_names) - set(execution.columns))
    if missing:
        raise ValueError(f"N=3 execution table is missing model features: {missing}")
    elapsed = pd.to_numeric(observed["elapsed_seconds"], errors="coerce")
    if elapsed.isna().any() or elapsed.le(0).any():
        raise ValueError("N=3 elapsed times must be positive and complete")
    observed = observed.copy()
    observed["elapsed_seconds_numeric"] = elapsed.to_numpy()
    variant_counts = observed.groupby(["pair_id", "variant"]).size()
    if len(variant_counts) != 32 or not variant_counts.eq(3).all():
        raise ValueError("Each N=3 pair must have three runs per variant")

    medians = (
        observed.groupby(["pair_id", "variant"], sort=True)[
            "elapsed_seconds_numeric"
        ]
        .median()
        .unstack("variant")
    )
    medians["target_log2_gain"] = np.log2(
        medians["stressed"] / medians["mitigated"]
    )
    stressed = observed[observed["variant"].eq("stressed")].copy()
    feature_rows = stressed[["pair_id", "query_run_id"]].merge(
        execution[["query_run_id", *feature_names]],
        on="query_run_id",
        how="left",
        validate="one_to_one",
    )
    for name in feature_names:
        feature_rows[name] = pd.to_numeric(feature_rows[name], errors="coerce")
    features = feature_rows.groupby("pair_id", sort=True)[feature_names].median()
    metadata = (
        stressed.groupby("pair_id", sort=True)
        .agg(
            dataset_profile_id=("dataset_profile_id", "first"),
            logical_question_id=("logical_question_id_frozen", "first"),
            scenario_level=("scenario_level_frozen", "first"),
            dataset_profile_count=("dataset_profile_id", "nunique"),
            question_count=("logical_question_id_frozen", "nunique"),
        )
        .drop(columns=["dataset_profile_count", "question_count"])
    )
    result = features.join(metadata).join(medians).reset_index()
    result["size_class"] = result["dataset_profile_id"].str.extract(
        r"n3-(medium|large)-", expand=False
    )
    result["placement_profile"] = np.where(
        result["dataset_profile_id"].str.contains("apac-dominant"),
        "apac_dominant",
        "balanced",
    )
    if len(result) != 16:
        raise ValueError("N=3 pair matrix must contain exactly 16 pairs")
    return result


def safe_correlation(actual: np.ndarray, predicted: np.ndarray, kind: str) -> float:
    if len(actual) < 2 or len(np.unique(actual)) < 2 or len(np.unique(predicted)) < 2:
        return math.nan
    value = spearmanr(actual, predicted) if kind == "spearman" else kendalltau(actual, predicted)
    return float(value.statistic)


def top_k_recall(actual: np.ndarray, predicted: np.ndarray, k: int) -> float:
    effective_k = min(k, len(actual))
    actual_top = set(np.argsort(actual)[-effective_k:])
    predicted_top = set(np.argsort(predicted)[-effective_k:])
    return len(actual_top & predicted_top) / effective_k


def ranking_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    relevance = np.maximum(np.exp2(actual) - 1.0, 0.0)
    return {
        "pair_count": float(len(actual)),
        "spearman": safe_correlation(actual, predicted, "spearman"),
        "kendall": safe_correlation(actual, predicted, "kendall"),
        "ndcg_at_5": float(
            ndcg_score(relevance.reshape(1, -1), predicted.reshape(1, -1), k=5)
        ),
        "top3_recall": top_k_recall(actual, predicted, 3),
        "top5_recall": top_k_recall(actual, predicted, 5),
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(math.sqrt(mean_squared_error(actual, predicted))),
        "r2": float(r2_score(actual, predicted)),
        "mean_bias": float(np.mean(predicted - actual)),
    }


def bootstrap_ranking_intervals(
    matrix: pd.DataFrame,
    metrics: dict[str, float],
) -> pd.DataFrame:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    strata = [
        group.index.to_numpy(dtype=int)
        for _, group in matrix.reset_index(drop=True).groupby(
            "placement_profile", sort=True
        )
    ]
    sampled: dict[str, list[float]] = {"spearman": [], "ndcg_at_5": []}
    actual = matrix["target_log2_gain"].to_numpy(dtype=float)
    predicted = matrix["predicted_log2_gain"].to_numpy(dtype=float)
    for _ in range(BOOTSTRAP_RESAMPLES):
        indexes = np.concatenate(
            [rng.choice(stratum, size=len(stratum), replace=True) for stratum in strata]
        )
        current = ranking_metrics(actual[indexes], predicted[indexes])
        for name in sampled:
            if math.isfinite(current[name]):
                sampled[name].append(current[name])

    alpha = 1.0 - BOOTSTRAP_CONFIDENCE
    rows = []
    for name, values in sampled.items():
        if not values:
            raise ValueError(f"Bootstrap produced no finite values for {name}")
        rows.append(
            {
                "metric": name,
                "estimate": metrics[name],
                "lower": float(np.quantile(values, alpha / 2.0)),
                "upper": float(np.quantile(values, 1.0 - alpha / 2.0)),
                "confidence": BOOTSTRAP_CONFIDENCE,
                "valid_resamples": len(values),
                "planned_resamples": BOOTSTRAP_RESAMPLES,
                "seed": BOOTSTRAP_SEED,
                "method": "placement_stratified_pair_bootstrap_percentile",
            }
        )
    return pd.DataFrame(rows)


def placement_metrics(matrix: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for placement_profile, group in matrix.groupby("placement_profile", sort=True):
        current = ranking_metrics(
            group["target_log2_gain"].to_numpy(dtype=float),
            group["predicted_log2_gain"].to_numpy(dtype=float),
        )
        rows.append({"placement_profile": placement_profile, **current})
    return pd.DataFrame(rows)


def pair_ranking(matrix: pd.DataFrame) -> pd.DataFrame:
    ranked = matrix.copy()
    ranked["actual_rank"] = ranked["target_log2_gain"].rank(
        ascending=False, method="min"
    ).astype(int)
    ranked["predicted_rank"] = ranked["predicted_log2_gain"].rank(
        ascending=False, method="min"
    ).astype(int)
    ranked["rank_error"] = ranked["predicted_rank"] - ranked["actual_rank"]
    ranked["absolute_rank_error"] = ranked["rank_error"].abs()
    columns = [
        "actual_rank",
        "predicted_rank",
        "rank_error",
        "absolute_rank_error",
        "pair_id",
        "placement_profile",
        "size_class",
        "logical_question_id",
        "dataset_profile_id",
        "target_log2_gain",
        "predicted_log2_gain",
        "actual_speedup",
        "predicted_speedup",
        "distance_to_p99_ratio",
        "outside_training_p99",
    ]
    return ranked.sort_values("actual_rank")[columns]


def add_predictions_and_coverage(
    matrix: pd.DataFrame,
    training: pd.DataFrame,
    manifest: dict[str, Any],
    model: Any,
) -> tuple[pd.DataFrame, float]:
    names = [str(value) for value in manifest["selected_feature_names"]]
    matrix = matrix.copy()
    matrix["predicted_log2_gain"] = np.asarray(model.predict(matrix[names]), dtype=float)
    matrix["actual_speedup"] = np.exp2(matrix["target_log2_gain"])
    matrix["predicted_speedup"] = np.exp2(matrix["predicted_log2_gain"])

    preprocessor = model.named_steps["preprocess"]
    training_values = np.asarray(preprocessor.transform(training[names]), dtype=float)
    holdout_values = np.asarray(preprocessor.transform(matrix[names]), dtype=float)
    neighbors = NearestNeighbors(n_neighbors=2, metric="euclidean").fit(training_values)
    training_distances = neighbors.kneighbors(
        training_values, return_distance=True
    )[0][:, 1]
    quantile = float(manifest["coverage_reference"]["quantile"])
    threshold = float(np.quantile(training_distances, quantile, method="linear"))
    frozen_threshold = float(manifest["coverage_reference"]["threshold"])
    if not math.isclose(threshold, frozen_threshold, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("Recomputed training P99 differs from frozen threshold")
    holdout_distances = neighbors.kneighbors(
        holdout_values, n_neighbors=1, return_distance=True
    )[0][:, 0]
    matrix["distance_to_nearest_training"] = holdout_distances
    matrix["coverage_threshold_p99"] = threshold
    matrix["distance_to_p99_ratio"] = holdout_distances / threshold
    matrix["outside_training_p99"] = holdout_distances > threshold
    return matrix, threshold


def evaluate_support(metrics: dict[str, float], rule: dict[str, Any]) -> tuple[str, list[str]]:
    failures = []
    checks = {
        "spearman": "minimum_spearman",
        "kendall": "minimum_kendall",
        "ndcg_at_5": "minimum_ndcg_at_5",
        "top5_recall": "minimum_top5_recall",
    }
    for metric, threshold_name in checks.items():
        if metrics[metric] < float(rule[threshold_name]):
            failures.append(f"{metric}_below_{threshold_name}")
    return ("SUPPORTED", []) if not failures else ("NOT_SUPPORTED", failures)


def write_figure(matrix: pd.DataFrame, path: Path) -> None:
    ordered = matrix.sort_values("target_log2_gain", ascending=False).reset_index(drop=True)
    positions = np.arange(1, len(ordered) + 1)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    axes[0].scatter(
        ordered["target_log2_gain"],
        ordered["predicted_log2_gain"],
        c=ordered["distance_to_p99_ratio"],
        cmap="viridis",
        edgecolor="#222222",
    )
    low = min(ordered["target_log2_gain"].min(), ordered["predicted_log2_gain"].min())
    high = max(ordered["target_log2_gain"].max(), ordered["predicted_log2_gain"].max())
    axes[0].plot([low, high], [low, high], color="#777777", linewidth=1)
    axes[0].set_xlabel("Izmjereni log2 dobitak")
    axes[0].set_ylabel("Predviđeni log2 dobitak")
    axes[0].set_title("Kalibracija kao sekundarni rezultat")
    axes[1].plot(positions, ordered["target_log2_gain"], marker="o", label="izmjereno")
    axes[1].plot(
        positions,
        ordered["predicted_log2_gain"],
        marker="s",
        label="predviđeno",
    )
    axes[1].set_xlabel("Rang prema izmjerenom dobitku")
    axes[1].set_ylabel("log2 dobitak")
    axes[1].set_title("No-refit rangiranje N=3 parova")
    axes[1].legend()
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def markdown_metrics(metrics: dict[str, float]) -> str:
    names = [
        "spearman",
        "kendall",
        "ndcg_at_5",
        "top3_recall",
        "top5_recall",
        "mae",
        "rmse",
        "r2",
        "mean_bias",
    ]
    lines = ["| Metrika | Vrijednost |", "| --- | ---: |"]
    lines.extend(f"| `{name}` | {metrics[name]:.4f} |" for name in names)
    return "\n".join(lines)


def write_report(
    out_dir: Path,
    matrix: pd.DataFrame,
    metrics: dict[str, float],
    bootstrap: pd.DataFrame,
    by_placement: pd.DataFrame,
    support: str,
    failures: list[str],
) -> None:
    outside_count = int(matrix["outside_training_p99"].sum())
    calibration_factor = float(np.exp2(abs(metrics["mean_bias"])))
    intervals = bootstrap.set_index("metric")
    bootstrap_rows = "\n".join(
        f"| {label} | {intervals.loc[name, 'estimate']:.4f} | "
        f"{intervals.loc[name, 'lower']:.4f} | "
        f"{intervals.loc[name, 'upper']:.4f} |"
        for name, label in (("spearman", "Spearman"), ("ndcg_at_5", "NDCG@5"))
    )
    placement_rows = "\n".join(
        f"| `{row.placement_profile}` | {int(row.pair_count)} | "
        f"{row.spearman:.4f} | {row.ndcg_at_5:.4f} | {row.mae:.4f} |"
        for row in by_placement.itertuples(index=False)
    )
    report = f"""# N=3 no-refit provjera rangiranja colocation akcije

## Ugovor

- Izvršeno je 96 unaprijed zamrznutih globalnih SQL izvršenja.
- Jedinicu evaluacije čini 16 stressed-mitigated parova sa po tri ponavljanja.
- Model, preprocessing, 19 pokazatelja i P99 referenca nisu refitovani.
- Primarni rezultat je rangiranje koristi akcije `use_colocated_distribution`.
- MAE i tačan speedup su sekundarni kalibracijski rezultati.

## Tehnička provjera

- kompletna izvršenja: `96/96`
- semantički ekvivalentni parovi: `16/16`
- tri regionalna plana po izvršenju: `96/96`
- tri remote edge zapisa po izvršenju: `96/96`
- worker/task dokaz iz sva tri regiona: `96/96`
- parovi izvan trening P99 upozorenja: `{outside_count}/16`

## Rang rezultat

Deskriptivni status unaprijed zaključanog pravila na testiranih 16 parova:
`{support}`.

{markdown_metrics(metrics)}

Stratifikovani bootstrap parova daje sljedeće 95% percentile intervale:

| Metrika | Procjena | Donja granica | Gornja granica |
| --- | ---: | ---: | ---: |
{bootstrap_rows}

Rezultat po placement profilu:

| Placement profil | Parovi | Spearman | NDCG@5 | MAE |
| --- | ---: | ---: | ---: | ---: |
{placement_rows}

Razlozi neispunjenog pravila: `{', '.join(failures) if failures else 'nema'}`.

P99 je upozorenje o udaljenosti od poznatog trening prostora. Nije formalni OOD
detektor i ne određuje prolaz rang-provjere.

## Tumačenje

Na 16 testiranih N=3 parova zamrznuti model zadržao je dobro relativno
rangiranje, iako su svi parovi izvan pokrivenosti trening prostora i apsolutna
kalibracija nije upotrebljiva. Srednja pristrasnost od
`{metrics['mean_bias']:.4f}` log2 jedinica znači sistematsko potcjenjivanje
izmjerenog dobitka za približno `{calibration_factor:.2f}x`, a negativni R2
potvrđuje da predviđeni speedup nije pouzdan broj za ovu topologiju. Rezultat je
opis ponašanja zamrznutog modela na malom OOD skupu, a ne validacija njegove
produkcijske primjene na N=3.

## Granica tvrdnje

Ovaj test potvrđuje da collector i fiksnodimenzionalni sažetak tehnički rade sa
tri regiona bez promjene sheme. Rang rezultat je deskriptivan za prikazanih 16
parova. Ne dokazuje opću generalizaciju rangiranja na N=3, novi DBMS, hardver ili
proizvoljan broj regiona.
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")


def write_checksums(out_dir: Path) -> None:
    files = sorted(
        path for path in out_dir.iterdir() if path.is_file() and path.name != "checksums.sha256"
    )
    (out_dir / "checksums.sha256").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    freeze_dir = args.freeze_dir.resolve()
    index_dir = args.index_dir.resolve()
    out_dir = args.out_dir.resolve()
    print("[N3 1/6] verifying immutable freeze", flush=True)
    manifest, model = verify_freeze(freeze_dir)
    model_path = freeze_dir / FREEZE_FILES["model"]
    model_hash_before = sha256_file(model_path)
    expected = read_csv(freeze_dir / FREEZE_FILES["expected_executions"])
    validate_sql_freeze(expected)

    print("[N3 2/6] validating logical index and N=3 child evidence", flush=True)
    observed, execution, topology = validate_execution_index(index_dir, expected)
    equivalence = validate_result_equivalence(observed)

    print("[N3 3/6] constructing 16 frozen holdout pairs", flush=True)
    feature_names = [str(value) for value in manifest["selected_feature_names"]]
    matrix = build_pair_matrix(observed, execution, feature_names)
    training = read_csv(freeze_dir / FREEZE_FILES["training_pair_reference"])

    print("[N3 4/6] applying frozen model without refit", flush=True)
    matrix, coverage_threshold = add_predictions_and_coverage(
        matrix, training, manifest, model
    )
    if sha256_file(model_path) != model_hash_before:
        raise ValueError("Frozen model changed during N=3 evaluation")
    actual = matrix["target_log2_gain"].to_numpy(dtype=float)
    predicted = matrix["predicted_log2_gain"].to_numpy(dtype=float)
    metrics = ranking_metrics(actual, predicted)
    bootstrap = bootstrap_ranking_intervals(matrix, metrics)
    by_placement = placement_metrics(matrix)
    ranking = pair_ranking(matrix)
    support, failures = evaluate_support(metrics, manifest["ranking_support_rule"])

    print("[N3 5/6] writing evidence package", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix.sort_values("predicted_log2_gain", ascending=False).to_csv(
        out_dir / "n3_pair_predictions.csv", index=False
    )
    topology.to_csv(out_dir / "n3_topology_completeness.csv", index=False)
    equivalence.to_csv(out_dir / "n3_result_equivalence.csv", index=False)
    pd.DataFrame([metrics]).to_csv(out_dir / "n3_ranking_metrics.csv", index=False)
    bootstrap.to_csv(out_dir / "n3_bootstrap_intervals.csv", index=False)
    by_placement.to_csv(out_dir / "n3_metrics_by_placement.csv", index=False)
    ranking.to_csv(out_dir / "n3_pair_ranking.csv", index=False)
    stressed_query_ids = set(
        observed.loc[observed["variant"].eq("stressed"), "query_run_id"].astype(str)
    )
    stressed_execution = execution[
        execution["query_run_id"].astype(str).isin(stressed_query_ids)
    ]
    feature_missingness = pd.DataFrame(
        {
            "all_execution_missing_share": execution[feature_names].isna().mean(),
            "stressed_model_input_missing_share": stressed_execution[feature_names]
            .isna()
            .mean(),
        }
    ).rename_axis("feature").reset_index()
    feature_missingness.to_csv(out_dir / "n3_feature_missingness.csv", index=False)
    write_figure(matrix, out_dir / "n3_no_refit_ranking.png")
    write_report(
        out_dir,
        matrix,
        metrics,
        bootstrap,
        by_placement,
        support,
        failures,
    )

    print("[N3 6/6] sealing manifest and checksums", flush=True)
    result_manifest = {
        "contract": "n3-colocation-no-refit-v1",
        "technical_gate": "GO",
        "ranking_support": support,
        "ranking_support_failures": failures,
        "no_refit_verified": True,
        "model_sha256_before": model_hash_before,
        "model_sha256_after": sha256_file(model_path),
        "freeze_manifest_sha256": sha256_file(freeze_dir / "freeze_manifest.json"),
        "execution_count": len(observed),
        "pair_count": len(matrix),
        "condition_count": int(observed["condition_id"].nunique()),
        "regions": sorted(EXPECTED_REGIONS),
        "coverage_threshold_p99": coverage_threshold,
        "outside_training_p99_count": int(matrix["outside_training_p99"].sum()),
        "ranking_metrics": metrics,
        "bootstrap": {
            "confidence": BOOTSTRAP_CONFIDENCE,
            "method": "placement_stratified_pair_bootstrap_percentile",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "intervals": bootstrap.to_dict(orient="records"),
        },
        "placement_metrics": by_placement.to_dict(orient="records"),
        "interpretation_scope": (
            "descriptive_ranking_on_16_out_of_coverage_n3_pairs_not_"
            "production_generalization"
        ),
        "ranking_support_rule": manifest["ranking_support_rule"],
    }
    (out_dir / "analysis_manifest.json").write_text(
        json.dumps(result_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_checksums(out_dir)
    print(out_dir / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
