from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
import yaml
from sklearn.decomposition import PCA
from sklearn.metrics import (
    adjusted_rand_score,
    normalized_mutual_info_score,
    silhouette_score,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


DEFAULT_CANDIDATE = Path("configs/features/phase1_clustering_candidate.yml")
DEFAULT_CONTEXT_COLUMNS = [
    "dataset_id",
    "runtime_config_id",
    "runtime_intervention_axis",
    "execution_strategy",
    "logical_question_id",
    "template_id",
    "intervention_axis",
]


class Progress:
    def __init__(self, total: int, label: str) -> None:
        self.total = max(total, 1)
        self.label = label
        self.current = 0
        self._tqdm: Any | None = None
        try:
            from tqdm import tqdm  # type: ignore

            self._tqdm = tqdm(total=total, desc=label, unit="iter")
        except Exception:
            self._print()

    def update(self, step: int = 1) -> None:
        self.current += step
        if self._tqdm is not None:
            self._tqdm.update(step)
            return
        self._print()

    def close(self) -> None:
        if self._tqdm is not None:
            self._tqdm.close()
            return
        print("", file=sys.stderr)

    def _print(self) -> None:
        pct = 100.0 * min(self.current, self.total) / self.total
        print(
            f"\r[{self.label}] {min(self.current, self.total)}/{self.total} ({pct:5.1f}%)",
            end="",
            file=sys.stderr,
            flush=True,
        )


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping in {path}")
    return value


def _parse_seeds(raw: str) -> list[int]:
    if ".." in raw:
        start_text, end_text = raw.split("..", 1)
        start = int(start_text)
        end = int(end_text)
        if end < start:
            raise ValueError("--seeds range end must be >= start")
        return list(range(start, end + 1))
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _parse_k_values(raw: str) -> list[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _load_candidate(path: Path) -> dict[str, Any]:
    candidate = _read_yaml(path)
    inputs = candidate.get("inputs") or {}
    clustering = candidate.get("manual_fuzzy_clustering") or {}
    if not isinstance(inputs, dict) or not isinstance(clustering, dict):
        raise ValueError(f"Invalid candidate manifest: {path}")
    return candidate


def _load_inputs(matrix_path: Path, context_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    matrix = pd.read_csv(matrix_path)
    context = pd.read_csv(context_path)
    if "query_run_id" not in matrix.columns or "query_run_id" not in context.columns:
        raise ValueError("matrix and context must contain query_run_id")
    matrix["query_run_id"] = matrix["query_run_id"].astype(str)
    context["query_run_id"] = context["query_run_id"].astype(str)
    if not matrix["query_run_id"].equals(context["query_run_id"]):
        context = matrix[["query_run_id"]].merge(context, on="query_run_id", how="left")
    return matrix, context


def _feature_columns(matrix: pd.DataFrame, forbidden: list[str]) -> list[str]:
    features = [column for column in matrix.columns if column != "query_run_id"]
    forbidden_set = set(forbidden)
    violations = sorted(
        column
        for column in features
        if column in forbidden_set
        or column.endswith("_id")
        or column.endswith("_json")
        or column.endswith("__is_missing")
    )
    if violations:
        raise ValueError(f"Model matrix contains forbidden/context columns: {violations}")
    return features


def _init_memberships(n_rows: int, k: int, rng: np.random.Generator) -> np.ndarray:
    raw = rng.random((n_rows, k)) + 1e-12
    return raw / raw.sum(axis=1, keepdims=True)


def _update_centers(x: np.ndarray, memberships: np.ndarray, fuzzifier: float) -> np.ndarray:
    weights = memberships**fuzzifier
    denom = weights.sum(axis=0)[:, None]
    return (weights.T @ x) / np.maximum(denom, 1e-12)


def _squared_distances(x: np.ndarray, centers: np.ndarray) -> np.ndarray:
    diff = x[:, None, :] - centers[None, :, :]
    return np.sum(diff * diff, axis=2)


def _update_memberships(distances: np.ndarray, fuzzifier: float) -> np.ndarray:
    n_rows, k = distances.shape
    distances = np.maximum(distances, 1e-12)
    memberships = np.zeros_like(distances)
    zero_mask = distances <= 1e-12
    rows_with_zero = zero_mask.any(axis=1)
    if rows_with_zero.any():
        memberships[rows_with_zero] = zero_mask[rows_with_zero] / zero_mask[
            rows_with_zero
        ].sum(axis=1, keepdims=True)
    normal_rows = ~rows_with_zero
    exponent = 1.0 / (fuzzifier - 1.0)
    inv = distances[normal_rows] ** (-exponent)
    memberships[normal_rows] = inv / inv.sum(axis=1, keepdims=True)
    return memberships


def _objective(distances: np.ndarray, memberships: np.ndarray, fuzzifier: float) -> float:
    return float(np.sum((memberships**fuzzifier) * distances))


def _partition_coefficient(memberships: np.ndarray) -> float:
    return float(np.mean(np.sum(memberships * memberships, axis=1)))


def _partition_entropy(memberships: np.ndarray) -> float:
    safe = np.maximum(memberships, 1e-12)
    return float(-np.mean(np.sum(safe * np.log(safe), axis=1)))


def _fuzzy_c_means(
    x: np.ndarray,
    *,
    k: int,
    seed: int,
    fuzzifier: float,
    max_iter: int,
    tolerance: float,
    progress: Progress,
    progress_events: list[dict[str, Any]],
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    memberships = _init_memberships(x.shape[0], k, rng)
    prev_objective = math.inf
    converged = False
    started = time.time()
    for iteration in range(1, max_iter + 1):
        centers = _update_centers(x, memberships, fuzzifier)
        distances = _squared_distances(x, centers)
        memberships = _update_memberships(distances, fuzzifier)
        objective = _objective(distances, memberships, fuzzifier)
        delta = abs(prev_objective - objective) if math.isfinite(prev_objective) else math.inf
        progress.update()
        if delta < tolerance:
            converged = True
            break
        prev_objective = objective
    if iteration < max_iter:
        progress.update(max_iter - iteration)
    labels = memberships.argmax(axis=1)
    distances = _squared_distances(x, centers)
    max_membership = memberships.max(axis=1)
    top2 = np.sort(memberships, axis=1)[:, -2:]
    result = {
        "k": k,
        "seed": seed,
        "iterations": iteration,
        "converged": converged,
        "objective": objective,
        "centers": centers,
        "memberships": memberships,
        "labels": labels,
        "distances": distances,
        "partition_coefficient": _partition_coefficient(memberships),
        "partition_entropy": _partition_entropy(memberships),
        "avg_max_membership": float(np.mean(max_membership)),
        "median_max_membership": float(np.median(max_membership)),
        "avg_top2_margin": float(np.mean(top2[:, 1] - top2[:, 0])),
        "elapsed_seconds": float(time.time() - started),
    }
    progress_events.append(
        {
            "event": "fit_complete",
            "k": k,
            "seed": seed,
            "iterations": iteration,
            "converged": converged,
            "objective": objective,
            "elapsed_seconds": result["elapsed_seconds"],
        }
    )
    return result


def _cluster_counts(labels: np.ndarray, k: int) -> np.ndarray:
    return np.bincount(labels, minlength=k)


def _score_rows(results: list[dict[str, Any]], x: np.ndarray) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        labels = result["labels"]
        counts = _cluster_counts(labels, int(result["k"]))
        silhouette = float(silhouette_score(x, labels)) if len(set(labels)) > 1 else math.nan
        rows.append(
            {
                "k": int(result["k"]),
                "seed": int(result["seed"]),
                "iterations": int(result["iterations"]),
                "converged": bool(result["converged"]),
                "objective": float(result["objective"]),
                "silhouette_hard_labels": silhouette,
                "partition_coefficient": float(result["partition_coefficient"]),
                "partition_entropy": float(result["partition_entropy"]),
                "avg_max_membership": float(result["avg_max_membership"]),
                "median_max_membership": float(result["median_max_membership"]),
                "avg_top2_margin": float(result["avg_top2_margin"]),
                "cluster_min_size": int(counts.min()),
                "cluster_max_size": int(counts.max()),
                "cluster_min_share": float(counts.min() / len(labels)),
                "cluster_max_share": float(counts.max() / len(labels)),
                "elapsed_seconds": float(result["elapsed_seconds"]),
            }
        )
    return pd.DataFrame(rows)


def _stability_rows(results: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    by_k: dict[int, list[dict[str, Any]]] = {}
    for result in results:
        by_k.setdefault(int(result["k"]), []).append(result)
    for k, k_results in sorted(by_k.items()):
        values: list[float] = []
        for i, left in enumerate(k_results):
            for right in k_results[i + 1 :]:
                values.append(float(adjusted_rand_score(left["labels"], right["labels"])))
        rows.append(
            {
                "k": k,
                "seed_pair_count": len(values),
                "ari_mean": float(np.mean(values)) if values else math.nan,
                "ari_std": float(np.std(values)) if values else math.nan,
                "ari_min": float(np.min(values)) if values else math.nan,
                "ari_max": float(np.max(values)) if values else math.nan,
            }
        )
    return pd.DataFrame(rows)


def _representative_runs(scores: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.Series] = []
    for _, group in scores.groupby("k"):
        ordered = group.sort_values(
            ["partition_coefficient", "avg_max_membership", "objective"],
            ascending=[False, False, True],
        )
        rows.append(ordered.iloc[0])
    return pd.DataFrame(rows).reset_index(drop=True)


def _membership_frame(matrix: pd.DataFrame, result: dict[str, Any]) -> pd.DataFrame:
    memberships = result["memberships"]
    labels = result["labels"]
    top2 = np.sort(memberships, axis=1)[:, -2:]
    entropy = -np.sum(np.maximum(memberships, 1e-12) * np.log(np.maximum(memberships, 1e-12)), axis=1)
    frame = pd.DataFrame({"query_run_id": matrix["query_run_id"].astype(str)})
    frame["k"] = int(result["k"])
    frame["seed"] = int(result["seed"])
    frame["hard_cluster"] = labels
    frame["max_membership"] = memberships.max(axis=1)
    frame["top2_margin"] = top2[:, 1] - top2[:, 0]
    frame["membership_entropy"] = entropy
    for cluster in range(memberships.shape[1]):
        frame[f"membership_c{cluster}"] = memberships[:, cluster]
    return frame


def _centers_frame(result: dict[str, Any], features: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    centers = result["centers"]
    for cluster, values in enumerate(centers):
        row: dict[str, Any] = {"k": int(result["k"]), "seed": int(result["seed"]), "cluster": cluster}
        row.update({feature: float(value) for feature, value in zip(features, values, strict=True)})
        rows.append(row)
    return pd.DataFrame(rows)


def _feature_profiles(
    matrix: pd.DataFrame,
    result: dict[str, Any],
    features: list[str],
    *,
    top_n: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    values = matrix[features].to_numpy(dtype=float)
    memberships = result["memberships"]
    rows: list[dict[str, Any]] = []
    top_rows: list[dict[str, Any]] = []
    for cluster in range(memberships.shape[1]):
        weights = memberships[:, cluster]
        denom = max(float(weights.sum()), 1e-12)
        means = (weights[:, None] * values).sum(axis=0) / denom
        effective_size = float(weights.sum())
        for feature, mean_value in zip(features, means, strict=True):
            rows.append(
                {
                    "k": int(result["k"]),
                    "seed": int(result["seed"]),
                    "cluster": cluster,
                    "feature": feature,
                    "weighted_mean_z": float(mean_value),
                    "abs_weighted_mean_z": float(abs(mean_value)),
                    "effective_membership_size": effective_size,
                }
            )
        ordered = sorted(zip(features, means, strict=True), key=lambda item: abs(item[1]), reverse=True)
        for rank, (feature, mean_value) in enumerate(ordered[:top_n], start=1):
            top_rows.append(
                {
                    "k": int(result["k"]),
                    "seed": int(result["seed"]),
                    "cluster": cluster,
                    "rank": rank,
                    "feature": feature,
                    "weighted_mean_z": float(mean_value),
                    "direction": "high" if mean_value >= 0 else "low",
                    "effective_membership_size": effective_size,
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(top_rows)


def _posthoc_context_association(
    results: list[dict[str, Any]],
    context: pd.DataFrame,
    context_columns: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    aligned = context.reset_index(drop=True)
    for result in results:
        labels = result["labels"]
        for column in context_columns:
            if column not in aligned.columns:
                continue
            values = aligned[column].fillna("__NULL__").astype(str).to_numpy()
            if len(set(values)) <= 1:
                continue
            rows.append(
                {
                    "k": int(result["k"]),
                    "seed": int(result["seed"]),
                    "context_column": column,
                    "nmi": float(normalized_mutual_info_score(values, labels)),
                    "context_distinct_values": int(len(set(values))),
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["k", "nmi"], ascending=[True, False])


def _top_context_values(
    context: pd.DataFrame,
    result: dict[str, Any],
    context_columns: list[str],
    *,
    top_n: int,
) -> pd.DataFrame:
    frame = context.reset_index(drop=True).copy()
    memberships = result["memberships"]
    labels = result["labels"]
    rows: list[dict[str, Any]] = []
    for cluster in range(memberships.shape[1]):
        hard_mask = labels == cluster
        cluster_context = frame.loc[hard_mask]
        if cluster_context.empty:
            continue
        for column in context_columns:
            if column not in cluster_context.columns:
                continue
            counts = cluster_context[column].fillna("__NULL__").astype(str).value_counts().head(top_n)
            for value, count in counts.items():
                rows.append(
                    {
                        "k": int(result["k"]),
                        "seed": int(result["seed"]),
                        "cluster": cluster,
                        "context_column": column,
                        "context_value": value,
                        "count": int(count),
                        "share_within_hard_cluster": float(count / len(cluster_context)),
                        "hard_cluster_size": int(len(cluster_context)),
                    }
                )
    return pd.DataFrame(rows)


def _prototype_runs(
    matrix: pd.DataFrame,
    context: pd.DataFrame,
    result: dict[str, Any],
    *,
    per_cluster: int,
) -> pd.DataFrame:
    frame = context.reset_index(drop=True).copy()
    frame["query_run_id"] = matrix["query_run_id"].astype(str).to_numpy()
    memberships = result["memberships"]
    labels = result["labels"]
    frame["k"] = int(result["k"])
    frame["seed"] = int(result["seed"])
    frame["hard_cluster"] = labels
    frame["max_membership"] = memberships.max(axis=1)
    top2 = np.sort(memberships, axis=1)[:, -2:]
    frame["top2_margin"] = top2[:, 1] - top2[:, 0]
    rows: list[pd.DataFrame] = []
    for cluster in range(memberships.shape[1]):
        cluster_frame = frame[frame["hard_cluster"] == cluster]
        rows.append(
            cluster_frame.sort_values(["max_membership", "top2_margin"], ascending=[False, False]).head(
                per_cluster
            )
        )
        rows.append(
            cluster_frame.sort_values(["top2_margin", "max_membership"], ascending=[True, False]).head(
                per_cluster
            )
        )
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _plot_scores(summary: pd.DataFrame, out: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    metrics = [
        ("partition_coefficient_mean", "Partition coefficient higher is crisper"),
        ("avg_max_membership_mean", "Average max membership higher is crisper"),
        ("ari_mean", "Seed stability ARI higher is better"),
        ("silhouette_hard_labels_mean", "Hard-label silhouette higher is better"),
    ]
    for ax, (metric, title) in zip(axes.flatten(), metrics, strict=True):
        if metric not in summary.columns:
            ax.axis("off")
            continue
        ax.plot(summary["k"], summary[metric], marker="o")
        ax.set_title(title)
        ax.set_xlabel("k")
        ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160)
    plt.close(fig)


def _plot_pca(matrix: pd.DataFrame, features: list[str], result: dict[str, Any], out: Path) -> None:
    x = matrix[features].to_numpy(dtype=float)
    reduced = PCA(n_components=2, random_state=0).fit_transform(x)
    labels = result["labels"]
    max_membership = result["memberships"].max(axis=1)
    plt.figure(figsize=(9, 7))
    scatter = plt.scatter(
        reduced[:, 0],
        reduced[:, 1],
        c=labels,
        s=12 + 28 * max_membership,
        cmap="tab10",
        alpha=0.75,
    )
    plt.colorbar(scatter, label="hard cluster")
    plt.xlabel("PCA 1")
    plt.ylabel("PCA 2")
    plt.title(f"Fuzzy C-means k={result['k']} seed={result['seed']}")
    plt.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, dpi=160)
    plt.close()


def _markdown_table(frame: pd.DataFrame, columns: list[str], limit: int = 20) -> str:
    if frame.empty:
        return "_No rows._\n"
    subset = frame.loc[:, [column for column in columns if column in frame.columns]].head(limit)
    lines = [
        "| " + " | ".join(subset.columns) + " |",
        "| " + " | ".join("---" for _ in subset.columns) + " |",
    ]
    for _, row in subset.iterrows():
        values = []
        for value in row:
            if isinstance(value, float):
                values.append("" if math.isnan(value) else f"{value:.5g}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def _write_progress(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    enriched = {"timestamp_unix": time.time(), **event}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(enriched, sort_keys=True) + "\n")


def run_fuzzy_clustering(
    *,
    candidate_path: Path,
    matrix_path: Path | None,
    context_path: Path | None,
    out_dir: Path | None,
    k_values: list[int] | None,
    seeds: list[int] | None,
    fuzzifier: float | None,
    max_iter: int | None,
    tolerance: float | None,
    top_n: int,
    prototype_count: int,
    context_columns: list[str],
    make_plots: bool,
) -> Path:
    candidate = _load_candidate(candidate_path)
    inputs = candidate["inputs"]
    clustering = candidate["manual_fuzzy_clustering"]
    matrix_path = matrix_path or Path(str(inputs["matrix"]))
    context_path = context_path or Path(str(inputs["context"]))
    out_dir = out_dir or Path(str(clustering["output_dir"]))
    k_values = k_values or [int(value) for value in clustering.get("k_values", [4, 5])]
    seeds = seeds or _parse_seeds(str(clustering.get("seeds", "0..9")))
    fuzzifier = float(fuzzifier if fuzzifier is not None else clustering.get("fuzzifier", 1.7))
    max_iter = int(max_iter if max_iter is not None else clustering.get("max_iter", 300))
    tolerance = float(tolerance if tolerance is not None else clustering.get("tolerance", 1e-5))

    if fuzzifier <= 1.0:
        raise ValueError("fuzzifier must be > 1")
    if not k_values:
        raise ValueError("at least one k value is required")
    if not seeds:
        raise ValueError("at least one seed is required")

    matrix, context = _load_inputs(matrix_path, context_path)
    forbidden = list((candidate.get("model_input_contract") or {}).get("forbidden_feature_columns", []))
    features = _feature_columns(matrix, forbidden)
    expected_feature_count = (candidate.get("model_input_contract") or {}).get(
        "expected_feature_count"
    )
    if expected_feature_count is not None and int(expected_feature_count) != len(features):
        raise ValueError(
            f"feature count mismatch: expected {expected_feature_count}, got {len(features)}"
        )
    x = matrix[features].to_numpy(dtype=float)
    if not np.isfinite(x).all():
        raise ValueError("model matrix contains non-finite values")

    out_dir.mkdir(parents=True, exist_ok=True)
    progress_path = out_dir / str(clustering.get("progress_log", "progress.jsonl"))
    progress_path.write_text("", encoding="utf-8")
    progress_events: list[dict[str, Any]] = []
    _write_progress(
        progress_path,
        {
            "event": "start",
            "matrix": str(matrix_path),
            "context": str(context_path),
            "rows": int(len(matrix)),
            "features": int(len(features)),
            "k_values": k_values,
            "seeds": seeds,
            "fuzzifier": fuzzifier,
            "max_iter": max_iter,
            "tolerance": tolerance,
        },
    )

    progress = Progress(total=len(k_values) * len(seeds) * max_iter, label="m0-reduced-fuzzy")
    started = time.time()
    results: list[dict[str, Any]] = []
    try:
        for k in k_values:
            for seed in seeds:
                _write_progress(progress_path, {"event": "fit_start", "k": k, "seed": seed})
                result = _fuzzy_c_means(
                    x,
                    k=k,
                    seed=seed,
                    fuzzifier=fuzzifier,
                    max_iter=max_iter,
                    tolerance=tolerance,
                    progress=progress,
                    progress_events=progress_events,
                )
                results.append(result)
                _write_progress(progress_path, progress_events[-1])
    finally:
        progress.close()

    scores = _score_rows(results, x)
    stability = _stability_rows(results)
    representatives = _representative_runs(scores)
    summary = (
        scores.groupby("k", as_index=False)
        .agg(
            objective_mean=("objective", "mean"),
            objective_std=("objective", "std"),
            silhouette_hard_labels_mean=("silhouette_hard_labels", "mean"),
            partition_coefficient_mean=("partition_coefficient", "mean"),
            partition_entropy_mean=("partition_entropy", "mean"),
            avg_max_membership_mean=("avg_max_membership", "mean"),
            avg_top2_margin_mean=("avg_top2_margin", "mean"),
            cluster_min_share_mean=("cluster_min_share", "mean"),
            cluster_max_share_mean=("cluster_max_share", "mean"),
            converged_count=("converged", "sum"),
            iterations_mean=("iterations", "mean"),
        )
        .merge(stability, on="k", how="left")
        .merge(
            representatives[["k", "seed"]].rename(columns={"seed": "representative_seed"}),
            on="k",
            how="left",
        )
    )

    association = _posthoc_context_association(results, context, context_columns)
    selected_results = {
        int(row["k"]): next(
            result
            for result in results
            if int(result["k"]) == int(row["k"]) and int(result["seed"]) == int(row["seed"])
        )
        for _, row in representatives.iterrows()
    }

    all_memberships: list[pd.DataFrame] = []
    all_centers: list[pd.DataFrame] = []
    all_profiles: list[pd.DataFrame] = []
    all_top_profiles: list[pd.DataFrame] = []
    all_context_values: list[pd.DataFrame] = []
    all_prototypes: list[pd.DataFrame] = []
    for result in selected_results.values():
        all_memberships.append(_membership_frame(matrix, result))
        all_centers.append(_centers_frame(result, features))
        profiles, top_profiles = _feature_profiles(matrix, result, features, top_n=top_n)
        all_profiles.append(profiles)
        all_top_profiles.append(top_profiles)
        all_context_values.append(
            _top_context_values(context, result, context_columns, top_n=top_n)
        )
        all_prototypes.append(
            _prototype_runs(matrix, context, result, per_cluster=prototype_count)
        )

    memberships = pd.concat(all_memberships, ignore_index=True)
    centers = pd.concat(all_centers, ignore_index=True)
    profiles = pd.concat(all_profiles, ignore_index=True)
    top_profiles = pd.concat(all_top_profiles, ignore_index=True)
    context_values = pd.concat(all_context_values, ignore_index=True)
    prototypes = pd.concat(all_prototypes, ignore_index=True)

    scores.to_csv(out_dir / "fuzzy_seed_scores.csv", index=False)
    stability.to_csv(out_dir / "seed_stability.csv", index=False)
    summary.to_csv(out_dir / "k_summary.csv", index=False)
    representatives.to_csv(out_dir / "representative_runs_by_k.csv", index=False)
    association.to_csv(out_dir / "posthoc_context_association.csv", index=False)
    memberships.to_csv(out_dir / "memberships_representative_by_k.csv", index=False)
    centers.to_csv(out_dir / "cluster_centers_representative_by_k.csv", index=False)
    profiles.to_csv(out_dir / "cluster_feature_profiles.csv", index=False)
    top_profiles.to_csv(out_dir / "cluster_top_feature_deviations.csv", index=False)
    context_values.to_csv(out_dir / "cluster_context_top_values.csv", index=False)
    prototypes.to_csv(out_dir / "prototype_and_ambiguous_runs.csv", index=False)

    if make_plots:
        figure_dir = out_dir / "figures"
        _plot_scores(summary, figure_dir / "fuzzy_k_scores.png")
        for k, result in selected_results.items():
            _plot_pca(matrix, features, result, figure_dir / f"fuzzy_k{k}_pca_projection.png")

    elapsed = time.time() - started
    _write_progress(progress_path, {"event": "complete", "elapsed_seconds": elapsed})

    manifest = {
        "contract": "phase1_m0_reduced_fuzzy_clustering_v1",
        "candidate": str(candidate_path),
        "matrix": str(matrix_path),
        "context": str(context_path),
        "output_dir": str(out_dir),
        "row_count": int(len(matrix)),
        "feature_count": int(len(features)),
        "features": features,
        "k_values": k_values,
        "seeds": seeds,
        "fuzzifier": fuzzifier,
        "max_iter": max_iter,
        "tolerance": tolerance,
        "elapsed_seconds": elapsed,
        "representative_runs_by_k": representatives.to_dict(orient="records"),
        "outputs": {
            "scores": "fuzzy_seed_scores.csv",
            "summary": "k_summary.csv",
            "stability": "seed_stability.csv",
            "association": "posthoc_context_association.csv",
            "memberships": "memberships_representative_by_k.csv",
            "centers": "cluster_centers_representative_by_k.csv",
            "profiles": "cluster_feature_profiles.csv",
            "top_profiles": "cluster_top_feature_deviations.csv",
            "context_values": "cluster_context_top_values.csv",
            "prototypes": "prototype_and_ambiguous_runs.csv",
            "progress_log": str(progress_path.name),
        },
    }
    (out_dir / "fuzzy_clustering_manifest.yml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    association_top = association.sort_values(["k", "nmi"], ascending=[True, False])
    report = f"""# Phase 1 M0 Reduced Fuzzy Clustering

Candidate: `{candidate_path}`

Matrix: `{matrix_path}`

Context: `{context_path}`

Rows: {len(matrix)}

Features: {len(features)}

This is the manual fuzzy clustering run for the first candidate input. Context
columns are used only for post-hoc association audit and interpretation.

## K Summary

{_markdown_table(summary, ["k", "representative_seed", "partition_coefficient_mean", "partition_entropy_mean", "avg_max_membership_mean", "avg_top2_margin_mean", "ari_mean", "cluster_min_share_mean", "cluster_max_share_mean", "silhouette_hard_labels_mean"], limit=20)}

## Post-Hoc Context Association

{_markdown_table(association_top, ["k", "seed", "context_column", "nmi", "context_distinct_values"], limit=60)}

## Top Cluster Feature Deviations

{_markdown_table(top_profiles, ["k", "cluster", "rank", "feature", "weighted_mean_z", "direction", "effective_membership_size"], limit=100)}

## Cluster Context Top Values

{_markdown_table(context_values, ["k", "cluster", "context_column", "context_value", "count", "share_within_hard_cluster", "hard_cluster_size"], limit=120)}

## Progress

- Progress log: `{progress_path.name}`
- Total elapsed seconds: {elapsed:.2f}

## Outputs

- `fuzzy_seed_scores.csv`
- `k_summary.csv`
- `seed_stability.csv`
- `posthoc_context_association.csv`
- `memberships_representative_by_k.csv`
- `cluster_centers_representative_by_k.csv`
- `cluster_feature_profiles.csv`
- `cluster_top_feature_deviations.csv`
- `cluster_context_top_values.csv`
- `prototype_and_ambiguous_runs.csv`
- `fuzzy_clustering_manifest.yml`
- `progress.jsonl`
- `progress_report.md`
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")

    progress_report = f"""# Fuzzy Clustering Progress Report

Status: complete

Candidate: `{candidate_path}`

Matrix: `{matrix_path}`

Rows: {len(matrix)}

Features: {len(features)}

K values: {k_values}

Seeds: {seeds}

Fuzzifier: {fuzzifier}

Max iterations: {max_iter}

Tolerance: {tolerance}

Elapsed seconds: {elapsed:.2f}

Representative runs:

{_markdown_table(representatives, ["k", "seed", "partition_coefficient", "avg_max_membership", "avg_top2_margin", "cluster_min_share", "cluster_max_share"], limit=20)}
"""
    (out_dir / str(clustering.get("progress_report", "progress_report.md"))).write_text(
        progress_report,
        encoding="utf-8",
    )
    print(out_dir / "README.md")
    return out_dir / "README.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manual fuzzy C-means clustering for the Phase 1 M0 reduced candidate."
    )
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--matrix", type=Path, default=None)
    parser.add_argument("--context", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--k-values", default=None, help="Comma list, e.g. 4,5")
    parser.add_argument("--seeds", default=None, help="Comma list or inclusive range, e.g. 0..9")
    parser.add_argument("--fuzzifier", type=float, default=None)
    parser.add_argument("--max-iter", type=int, default=None)
    parser.add_argument("--tolerance", type=float, default=None)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--prototype-count", type=int, default=5)
    parser.add_argument(
        "--context-columns",
        default=",".join(DEFAULT_CONTEXT_COLUMNS),
        help="Comma-separated context columns for post-hoc association audit.",
    )
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()

    run_fuzzy_clustering(
        candidate_path=args.candidate,
        matrix_path=args.matrix,
        context_path=args.context,
        out_dir=args.out_dir,
        k_values=_parse_k_values(args.k_values) if args.k_values else None,
        seeds=_parse_seeds(args.seeds) if args.seeds else None,
        fuzzifier=args.fuzzifier,
        max_iter=args.max_iter,
        tolerance=args.tolerance,
        top_n=args.top_n,
        prototype_count=args.prototype_count,
        context_columns=[value.strip() for value in args.context_columns.split(",") if value.strip()],
        make_plots=not args.no_plots,
    )


if __name__ == "__main__":
    main()
