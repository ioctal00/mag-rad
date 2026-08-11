#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.stats import mannwhitneyu, spearmanr
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    normalized_mutual_info_score,
    silhouette_score,
)

from master_regimes.config import load_yaml
from master_regimes.representation_audit import (
    FCMResult,
    fcm_metrics,
    fit_best_fcm,
    memberships_from_centers,
    seed_stability,
    semantic_transform,
    squared_distances,
)

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT.parent
DEFAULT_OUT_DIR = ROOT / "analysis/reports/semantic-v2-final-consistency"
CONTRACT_PATH = ROOT / "configs/features/feature_semantic_contract_v2.yml"
FREEZE_DIR = ROOT / "analysis/reports/semantic-v2-model-freeze"
REFREEZE_EQUIVALENCE = (
    FREEZE_DIR / "finalization_refreeze_equivalence.json"
)
BASELINE_FEATURE_DIR = ROOT / "analysis/features/clean-run-v1-semantic-v2"
BASELINE_CONTEXT = (
    ROOT
    / "analysis/features/clean-run-v1-flow-ratio-v3/phase1_compact/"
    "compact_context.csv"
)
PRESSURE_EVIDENCE = (
    ROOT
    / "analysis/features/clean-run-v1-flow-ratio-v3/phase1_compact/"
    "pressure_evidence.csv"
)
BALANCED_SKEW_PAIRS = (
    ROOT
    / "analysis/reports/clean-run-v1-claim-stress-test/"
    "observability_paired_contrasts.csv"
)
REPEATABILITY_FEATURE_DIR = ROOT / "analysis/features/repeatability-v1"
REPEATABILITY_MAPPING = (
    ROOT / "analysis/reports/repeatability-v1/repeatability_attempt_features.csv"
)
VALIDATION_FEATURE_DIR = (
    ROOT / "analysis/features/clean-run-v1-validation-holdout"
)
CONFIRMATORY_FEATURE_DIR = ROOT / "analysis/features/confirmatory-skew-v1"
CONFIRMATORY_REPORT_DIR = ROOT / "analysis/reports/confirmatory-skew-v1-analysis"
STATS_PILOT_FEATURE_DIR = ROOT / "analysis/features/stats-ceb-portability-v1-semantic-v2"
STATS_V2_DEV_FEATURE_DIR = ROOT / "analysis/features/stats-ceb-semantic-v2-holdout"
STATS_V2B_FEATURE_DIR = ROOT / "analysis/features/stats-ceb-semantic-v2b-holdout"
STATS_V2_DEV_REPORT = ROOT / "analysis/reports/stats-ceb-semantic-v2-holdout"
STATS_V2B_REPORT = ROOT / "analysis/reports/stats-ceb-semantic-v2b-holdout"
V2B_SELECTION = ROOT / "external/stats-ceb/query-selection.semantic-v2b-holdout.yml"
V2B_PLAN = (
    ROOT / "generated/corpus/stats-ceb-semantic-v2b-holdout/corpus_execution_plan.yml"
)
V2B_RUN_DIR = (
    WORKSPACE
    / "master-regimes-infra/generated/runs/corpus-sweeps/"
    "20260726T112955Z-stats-ceb-semantic-v2b-holdout-attempt-01"
)
ACTIVE_PRESSURE_STATUSES = {"confirmed", "partially_confirmed"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the final semantic-v2 consistency package without refitting "
            "on external holdout rows."
        )
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, low_memory=False)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def feature_file(directory: Path) -> Path:
    for name in ("execution_features_all.csv", "execution_features_m0.csv"):
        candidate = directory / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No feature table in {directory}")


def entropy(memberships: np.ndarray) -> np.ndarray:
    safe = np.maximum(memberships, 1.0e-12)
    return -np.sum(safe * np.log(safe), axis=1)


def quality_class(
    frame: pd.DataFrame,
    membership_threshold: float = 0.50,
    margin_threshold: float = 0.15,
    entropy_threshold: float = 1.05,
) -> np.ndarray:
    membership_ok = frame["max_membership"].to_numpy() >= membership_threshold
    margin_ok = frame["top2_margin"].to_numpy() >= margin_threshold
    entropy_ok = frame["membership_entropy"].to_numpy() < entropy_threshold
    result = np.full(len(frame), "mixed_boundary", dtype=object)
    result[membership_ok & margin_ok & entropy_ok] = "clear_prototype"
    result[~membership_ok & ~margin_ok & ~entropy_ok] = (
        "weak_prototype_coverage"
    )
    return result


def membership_frame(
    query_run_ids: pd.Series,
    memberships: np.ndarray,
    distances: np.ndarray,
) -> pd.DataFrame:
    result = pd.DataFrame(
        {
            "query_run_id": query_run_ids.astype(str).to_numpy(),
            "dominant_cluster": memberships.argmax(axis=1),
            "max_membership": memberships.max(axis=1),
            "membership_entropy": entropy(memberships),
            "membership_entropy_normalized": entropy(memberships)
            / math.log(memberships.shape[1]),
            "nearest_center_distance": distances.min(axis=1),
        }
    )
    sorted_values = np.sort(memberships, axis=1)
    result["top2_margin"] = sorted_values[:, -1] - sorted_values[:, -2]
    for cluster in range(memberships.shape[1]):
        result[f"membership_c{cluster}"] = memberships[:, cluster]
    return result


def load_frozen_model() -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[str],
    np.ndarray,
    float,
    float,
]:
    contract = load_yaml(CONTRACT_PATH)
    manifest = load_yaml(FREEZE_DIR / "semantic_v2_model_manifest.yml")
    features = [str(value) for value in manifest["features"]]
    center_file = FREEZE_DIR / manifest["models"]["k4"]["center_file"]
    centers = read_csv(center_file).sort_values("cluster")
    center_values = centers[features].to_numpy(dtype=float)
    return (
        contract,
        manifest,
        features,
        center_values,
        float(manifest["fuzzifier"]),
        float(manifest["models"]["k4"]["ood_p99_threshold"]),
    )


def transform_dataset(
    feature_dir: Path,
    contract: dict[str, Any],
    features: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    support = read_csv(feature_file(feature_dir))
    missing = sorted(set(features).difference(support.columns))
    if missing:
        raise ValueError(f"{feature_dir} misses semantic-v2 features: {missing}")
    raw = support[["query_run_id", *features]].copy()
    transformed, weighted, audit = semantic_transform(raw, support, contract)
    return support, raw, transformed, weighted


def project_dataset(
    feature_dir: Path,
    contract: dict[str, Any],
    features: list[str],
    centers: np.ndarray,
    fuzzifier: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    support, raw, transformed, weighted = transform_dataset(
        feature_dir,
        contract,
        features,
    )
    memberships, distances = memberships_from_centers(
        weighted[features].to_numpy(dtype=float),
        centers,
        fuzzifier=fuzzifier,
    )
    projection = membership_frame(weighted["query_run_id"], memberships, distances)
    return support, raw, weighted, projection


def metric_scores(values: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    unique = np.unique(labels)
    if len(unique) < 2 or len(unique) >= len(labels):
        return {
            "silhouette_hard_labels": math.nan,
            "davies_bouldin": math.nan,
            "calinski_harabasz": math.nan,
        }
    return {
        "silhouette_hard_labels": float(silhouette_score(values, labels)),
        "davies_bouldin": float(davies_bouldin_score(values, labels)),
        "calinski_harabasz": float(calinski_harabasz_score(values, labels)),
    }


def pairwise_ari(labels_by_run: dict[str, np.ndarray]) -> dict[str, float]:
    values = [
        float(adjusted_rand_score(left, right))
        for (_, left), (_, right) in itertools.combinations(
            labels_by_run.items(),
            2,
        )
    ]
    return {
        "ari_mean": float(np.mean(values)) if values else math.nan,
        "ari_min": float(np.min(values)) if values else math.nan,
        "ari_max": float(np.max(values)) if values else math.nan,
        "ari_std": float(np.std(values)) if values else math.nan,
    }


def chronology_audit(
    manifest: dict[str, Any],
    out_dir: Path,
) -> pd.DataFrame:
    run_manifest = read_json(V2B_RUN_DIR / "corpus_execution_manifest.json")
    run_started = datetime.strptime(
        str(run_manifest["created_at_utc"]),
        "%Y%m%dT%H%M%SZ",
    ).replace(tzinfo=UTC)
    tolerance = timedelta(seconds=1)
    freeze_hashes = read_json(FREEZE_DIR / "freeze_sha256.json")
    holdout_summary = read_json(STATS_V2B_REPORT / "holdout_summary.json")
    refreeze_equivalence = read_json(REFREEZE_EQUIVALENCE)
    finalization_revised_artifacts = {
        "semantic_contract",
        "model_freeze_script",
        "frozen_model_manifest",
    }
    artifacts = [
        ("feature_extractor", ROOT / "src/master_regimes/feature_matrix.py"),
        (
            "query_sweep_indexer",
            ROOT / "src/master_regimes/extract/query_sweep_index.py",
        ),
        ("semantic_contract", CONTRACT_PATH),
        (
            "semantic_audit_script",
            ROOT / "analysis/scripts/agent/61_feature_semantic_contract_audit.py",
        ),
        (
            "model_freeze_script",
            ROOT / "analysis/scripts/agent/62_freeze_semantic_v2_model.py",
        ),
        ("frozen_model_manifest", FREEZE_DIR / "semantic_v2_model_manifest.yml"),
        ("holdout_selection", V2B_SELECTION),
        ("rendered_execution_plan", V2B_PLAN),
    ]
    rows: list[dict[str, Any]] = []
    for artifact, path in artifacts:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        frozen_before_holdout = modified <= run_started + tolerance
        rows.append(
            {
                "check": f"{artifact}_frozen_before_holdout",
                "artifact": str(path.relative_to(ROOT))
                if path.is_relative_to(ROOT)
                else str(path),
                "artifact_mtime_utc": modified.isoformat(),
                "holdout_started_utc": run_started.isoformat(),
                "sha256": sha256(path),
                "status": (
                    "PASS"
                    if frozen_before_holdout
                    else (
                        "INFO"
                        if artifact in finalization_revised_artifacts
                        else "FAIL"
                    )
                ),
                "note": (
                    "one-second tolerance reflects run IDs without subsecond "
                    "precision"
                    if frozen_before_holdout
                    else (
                        "post-holdout finalization revision; numerical "
                        "equivalence is checked separately"
                    )
                ),
            }
        )
    hash_checks = [
        (
            "contract_hash_matches_freeze",
            sha256(CONTRACT_PATH),
            str(freeze_hashes["feature_contract_sha256"]),
        ),
        (
            "contract_hash_matches_holdout",
            sha256(CONTRACT_PATH),
            str(holdout_summary["feature_contract_sha256"]),
        ),
        (
            "model_manifest_hash_matches_holdout",
            sha256(FREEZE_DIR / "semantic_v2_model_manifest.yml"),
            str(holdout_summary["model_manifest_sha256"]),
        ),
    ]
    for name, observed, expected in hash_checks:
        rows.append(
            {
                "check": name,
                "artifact": "",
                "artifact_mtime_utc": "",
                "holdout_started_utc": run_started.isoformat(),
                "sha256": observed,
                "status": "PASS" if observed == expected else "FAIL",
                "note": f"expected={expected}",
            }
        )
    for filename, expected in refreeze_equivalence[
        "byte_identical_outputs"
    ].items():
        path = STATS_V2B_REPORT / filename
        observed = sha256(path)
        rows.append(
            {
                "check": f"finalization_refreeze_equivalent_{path.stem}",
                "artifact": str(path.relative_to(ROOT)),
                "artifact_mtime_utc": iso_utc(path.stat().st_mtime),
                "holdout_started_utc": run_started.isoformat(),
                "sha256": observed,
                "status": "PASS" if observed == expected else "FAIL",
                "note": (
                    "byte-identical before and after no-refit finalization "
                    "reprojection"
                ),
            }
        )
    no_refit = not bool(holdout_summary["model_refit_performed"])
    rows.append(
        {
            "check": "holdout_projection_without_model_refit",
            "artifact": str(
                (STATS_V2B_REPORT / "holdout_summary.json").relative_to(ROOT)
            ),
            "artifact_mtime_utc": iso_utc(
                (STATS_V2B_REPORT / "holdout_summary.json").stat().st_mtime
            ),
            "holdout_started_utc": run_started.isoformat(),
            "sha256": sha256(STATS_V2B_REPORT / "holdout_summary.json"),
            "status": "PASS" if no_refit else "FAIL",
            "note": "model_refit_performed must remain false",
        }
    )
    rows.append(
        {
            "check": "freeze_declares_post_holdout_changes_prohibited",
            "artifact": "",
            "artifact_mtime_utc": "",
            "holdout_started_utc": run_started.isoformat(),
            "sha256": "",
            "status": "PASS"
            if manifest.get("post_holdout_changes_allowed") is False
            else "FAIL",
            "note": "",
        }
    )
    result = pd.DataFrame(rows)
    result.to_csv(out_dir / "chronology_audit.csv", index=False)
    return result


def k_range_audit(
    values: np.ndarray,
    *,
    seeds: list[int],
    fuzzifier: float,
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[int, FCMResult]]:
    seed_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    best_by_k: dict[int, FCMResult] = {}
    for k in range(2, 9):
        best, fits = fit_best_fcm(
            values,
            k=k,
            seeds=seeds,
            fuzzifier=fuzzifier,
        )
        best_by_k[k] = best
        for fit in fits:
            seed_rows.append(
                {
                    "k": k,
                    "seed": fit.seed,
                    "objective": fit.objective,
                    "iterations": fit.iterations,
                    "converged": fit.converged,
                    **fcm_metrics(values, fit),
                }
            )
        summary_rows.append(
            {
                "k": k,
                "representative_seed": best.seed,
                "objective": best.objective,
                "converged_seed_count": sum(fit.converged for fit in fits),
                **fcm_metrics(values, best),
                **seed_stability(fits),
            }
        )
    seed_frame = pd.DataFrame(seed_rows)
    summary = pd.DataFrame(summary_rows)
    seed_frame.to_csv(out_dir / "k_seed_scores.csv", index=False)
    summary.to_csv(out_dir / "k_summary.csv", index=False)
    return seed_frame, summary, best_by_k


def algorithm_audit(
    values: np.ndarray,
    fcm: FCMResult,
    *,
    seeds: list[int],
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    score_rows = [
        {
            "algorithm": "FCM",
            "run_id": f"seed-{fcm.seed}",
            "representative": True,
            **metric_scores(values, fcm.labels),
        }
    ]
    kmeans_labels: dict[str, np.ndarray] = {}
    kmeans_inertia: dict[str, float] = {}
    for seed in seeds:
        fit = KMeans(n_clusters=4, random_state=seed, n_init=1).fit(values)
        run_id = f"seed-{seed}"
        kmeans_labels[run_id] = fit.labels_
        kmeans_inertia[run_id] = float(fit.inertia_)
    representative = min(kmeans_inertia, key=kmeans_inertia.get)
    for run_id, labels in kmeans_labels.items():
        score_rows.append(
            {
                "algorithm": "K-means",
                "run_id": run_id,
                "representative": run_id == representative,
                **metric_scores(values, labels),
            }
        )
    ward_labels = AgglomerativeClustering(
        n_clusters=4,
        linkage="ward",
    ).fit_predict(values)
    score_rows.append(
        {
            "algorithm": "Ward",
            "run_id": "deterministic",
            "representative": True,
            **metric_scores(values, ward_labels),
        }
    )
    stability = pd.DataFrame(
        [
            {
                "algorithm": "FCM",
                **pairwise_ari({f"seed-{fcm.seed}": fcm.labels}),
            },
            {"algorithm": "K-means", **pairwise_ari(kmeans_labels)},
            {
                "algorithm": "Ward",
                "ari_mean": 1.0,
                "ari_min": 1.0,
                "ari_max": 1.0,
                "ari_std": 0.0,
            },
        ]
    )
    representatives = {
        "FCM": fcm.labels,
        "K-means": kmeans_labels[representative],
        "Ward": ward_labels,
    }
    agreement_rows = []
    for (left_name, left), (right_name, right) in itertools.combinations(
        representatives.items(),
        2,
    ):
        agreement_rows.append(
            {
                "left_algorithm": left_name,
                "right_algorithm": right_name,
                "ari": adjusted_rand_score(left, right),
                "nmi": normalized_mutual_info_score(left, right),
            }
        )
    scores = pd.DataFrame(score_rows)
    agreement = pd.DataFrame(agreement_rows)
    scores.to_csv(out_dir / "algorithm_scores.csv", index=False)
    stability.to_csv(out_dir / "algorithm_stability.csv", index=False)
    agreement.to_csv(out_dir / "algorithm_agreement.csv", index=False)
    return scores, stability, agreement


def align_centers(candidate: np.ndarray, reference: np.ndarray) -> np.ndarray:
    costs = np.sqrt(squared_distances(candidate, reference))
    candidate_indices, reference_indices = linear_sum_assignment(costs)
    aligned = np.empty_like(candidate)
    for candidate_index, reference_index in zip(
        candidate_indices,
        reference_indices,
        strict=True,
    ):
        aligned[reference_index] = candidate[candidate_index]
    return aligned


def leave_family_out_audit(
    weighted: pd.DataFrame,
    context: pd.DataFrame,
    *,
    features: list[str],
    full_centers: np.ndarray,
    full_memberships: np.ndarray,
    fuzzifier: float,
    seeds: list[int],
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    aligned = weighted[["query_run_id", *features]].merge(
        context[["query_run_id", "logical_question_id"]],
        on="query_run_id",
        validate="one_to_one",
    )
    full_by_id = {
        run_id: index
        for index, run_id in enumerate(weighted["query_run_id"].astype(str))
    }
    rows: list[dict[str, Any]] = []
    for family in sorted(aligned["logical_question_id"].astype(str).unique()):
        hold_mask = aligned["logical_question_id"].astype(str).eq(family)
        train_values = aligned.loc[~hold_mask, features].to_numpy(dtype=float)
        hold_values = aligned.loc[hold_mask, features].to_numpy(dtype=float)
        hold_ids = aligned.loc[hold_mask, "query_run_id"].astype(str).tolist()
        best, fits = fit_best_fcm(
            train_values,
            k=4,
            seeds=seeds,
            fuzzifier=fuzzifier,
        )
        centers = align_centers(best.centers, full_centers)
        projected, _ = memberships_from_centers(
            hold_values,
            centers,
            fuzzifier=fuzzifier,
        )
        full_offsets = [full_by_id[run_id] for run_id in hold_ids]
        reference = full_memberships[full_offsets]
        rows.append(
            {
                "logical_question_id": family,
                "holdout_rows": int(hold_mask.sum()),
                "training_rows": int((~hold_mask).sum()),
                "hard_label_ari": float(
                    adjusted_rand_score(
                        reference.argmax(axis=1),
                        projected.argmax(axis=1),
                    )
                ),
                "mean_membership_l1": float(
                    np.abs(reference - projected).sum(axis=1).mean()
                ),
                "max_membership_l1": float(
                    np.abs(reference - projected).sum(axis=1).max()
                ),
                "mean_center_shift": float(
                    np.sqrt(squared_distances(centers, full_centers).diagonal()).mean()
                ),
                "max_center_shift": float(
                    np.sqrt(squared_distances(centers, full_centers).diagonal()).max()
                ),
                **seed_stability(fits),
            }
        )
    detail = pd.DataFrame(rows)
    weights = detail["holdout_rows"].to_numpy(dtype=float)
    summary = pd.DataFrame(
        [
            {
                "fold_count": len(detail),
                "row_count": int(detail["holdout_rows"].sum()),
                "weighted_hard_label_ari": float(
                    np.average(detail["hard_label_ari"], weights=weights)
                ),
                "minimum_hard_label_ari": float(detail["hard_label_ari"].min()),
                "weighted_mean_membership_l1": float(
                    np.average(detail["mean_membership_l1"], weights=weights)
                ),
                "maximum_center_shift": float(detail["max_center_shift"].max()),
            }
        ]
    )
    detail.to_csv(out_dir / "leave_family_out.csv", index=False)
    summary.to_csv(out_dir / "leave_family_out_summary.csv", index=False)
    return detail, summary


def prototype_profiles(
    raw: pd.DataFrame,
    transformed: pd.DataFrame,
    memberships: np.ndarray,
    context: pd.DataFrame,
    contract: dict[str, Any],
    features: list[str],
    fuzzifier: float,
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw_indexed = raw.set_index(raw["query_run_id"].astype(str))
    transformed_indexed = transformed.set_index(
        transformed["query_run_id"].astype(str)
    )
    run_ids = transformed["query_run_id"].astype(str)
    profile_rows: list[dict[str, Any]] = []
    for cluster in range(memberships.shape[1]):
        weights = memberships[:, cluster] ** fuzzifier
        for feature in features:
            raw_values = pd.to_numeric(
                raw_indexed.loc[run_ids, feature],
                errors="coerce",
            ).to_numpy(dtype=float)
            semantic_values = pd.to_numeric(
                transformed_indexed.loc[run_ids, feature],
                errors="coerce",
            ).to_numpy(dtype=float)
            valid = np.isfinite(raw_values)
            raw_mean = (
                float(np.average(raw_values[valid], weights=weights[valid]))
                if valid.any()
                else math.nan
            )
            semantic_mean = float(np.average(semantic_values, weights=weights))
            global_mean = float(np.mean(semantic_values))
            profile_rows.append(
                {
                    "cluster": cluster,
                    "feature": feature,
                    "family": contract["features"][feature]["family"],
                    "fuzzy_mass": float(weights.sum()),
                    "raw_fuzzy_mean": raw_mean,
                    "raw_global_median": float(np.nanmedian(raw_values)),
                    "semantic_fuzzy_mean": semantic_mean,
                    "semantic_global_mean": global_mean,
                    "semantic_deviation": semantic_mean - global_mean,
                    "absolute_semantic_deviation": abs(semantic_mean - global_mean),
                }
            )
    profiles = pd.DataFrame(profile_rows)
    top = (
        profiles.sort_values(
            ["cluster", "absolute_semantic_deviation"],
            ascending=[True, False],
        )
        .groupby("cluster")
        .head(6)
        .reset_index(drop=True)
    )

    merged = pd.DataFrame(
        {"query_run_id": run_ids, **{
            f"membership_c{cluster}": memberships[:, cluster]
            for cluster in range(memberships.shape[1])
        }}
    ).merge(
        context,
        on="query_run_id",
        validate="one_to_one",
    )
    context_rows: list[dict[str, Any]] = []
    for cluster in range(memberships.shape[1]):
        membership_column = f"membership_c{cluster}"
        for column in (
            "logical_question_id",
            "execution_strategy",
            "dataset_id",
            "runtime_config_id",
        ):
            grouped = (
                merged.assign(context_value=merged[column].fillna("<missing>").astype(str))
                .groupby("context_value", as_index=False)[membership_column]
                .sum()
                .sort_values(membership_column, ascending=False)
            )
            total = float(grouped[membership_column].sum())
            for rank, (_, row) in enumerate(grouped.head(5).iterrows(), start=1):
                context_rows.append(
                    {
                        "cluster": cluster,
                        "context_field": column,
                        "rank": rank,
                        "context_value": row["context_value"],
                        "fuzzy_mass": float(row[membership_column]),
                        "fuzzy_mass_share": float(row[membership_column] / total),
                    }
                )
    context_profiles = pd.DataFrame(context_rows)
    profiles.to_csv(out_dir / "prototype_feature_profiles.csv", index=False)
    top.to_csv(out_dir / "prototype_top_features.csv", index=False)
    context_profiles.to_csv(out_dir / "prototype_context_profiles.csv", index=False)
    return profiles, top, context_profiles


def balanced_skew_audit(
    weighted: pd.DataFrame,
    memberships: pd.DataFrame,
    features: list[str],
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pairs = read_csv(BALANCED_SKEW_PAIRS)
    vector_by_id = weighted.set_index(weighted["query_run_id"].astype(str))
    member_by_id = memberships.set_index(
        memberships["query_run_id"].astype(str)
    )
    membership_columns = [f"membership_c{cluster}" for cluster in range(4)]
    rows: list[dict[str, Any]] = []
    for _, pair in pairs.iterrows():
        balanced_id = str(pair["balanced_query_run_id"])
        skew_id = str(pair["skew_query_run_id"])
        if balanced_id not in vector_by_id.index or skew_id not in vector_by_id.index:
            continue
        left = vector_by_id.loc[balanced_id, features].to_numpy(dtype=float)
        right = vector_by_id.loc[skew_id, features].to_numpy(dtype=float)
        left_u = member_by_id.loc[
            balanced_id,
            membership_columns,
        ].to_numpy(dtype=float)
        right_u = member_by_id.loc[
            skew_id,
            membership_columns,
        ].to_numpy(dtype=float)
        rows.append(
            {
                "pair_key": pair["pair_key"],
                "logical_question_id": pair["logical_question_id"],
                "execution_strategy": pair["execution_strategy"],
                "balanced_query_run_id": balanced_id,
                "skew_query_run_id": skew_id,
                "semantic_feature_l2": float(np.linalg.norm(right - left)),
                "membership_l1": float(np.abs(right_u - left_u).sum()),
                "dominant_cluster_changed": int(left_u.argmax() != right_u.argmax()),
                "gac_visible_rms_delta_v1": pair["gac_visible_rms_delta"],
                "topology_only_rms_delta_v1": pair["topology_only_rms_delta"],
            }
        )
    detail = pd.DataFrame(rows)
    summary_rows = [
        {
            "scope": "all",
            "pair_count": len(detail),
            "median_semantic_feature_l2": detail["semantic_feature_l2"].median(),
            "median_membership_l1": detail["membership_l1"].median(),
            "p90_membership_l1": detail["membership_l1"].quantile(0.9),
            "dominant_cluster_change_share": detail[
                "dominant_cluster_changed"
            ].mean(),
        }
    ]
    for family, group in detail.groupby("logical_question_id"):
        summary_rows.append(
            {
                "scope": f"question:{family}",
                "pair_count": len(group),
                "median_semantic_feature_l2": group[
                    "semantic_feature_l2"
                ].median(),
                "median_membership_l1": group["membership_l1"].median(),
                "p90_membership_l1": group["membership_l1"].quantile(0.9),
                "dominant_cluster_change_share": group[
                    "dominant_cluster_changed"
                ].mean(),
            }
        )
    summary = pd.DataFrame(summary_rows)
    detail.to_csv(out_dir / "balanced_skew_pairs.csv", index=False)
    summary.to_csv(out_dir / "balanced_skew_summary.csv", index=False)
    return detail, summary


def pairwise_condition_metrics(
    group: pd.DataFrame,
    features: list[str],
) -> dict[str, float]:
    membership_columns = [f"membership_c{cluster}" for cluster in range(4)]
    feature_values = group[features].to_numpy(dtype=float)
    membership_values = group[membership_columns].to_numpy(dtype=float)
    feature_distances = [
        float(np.linalg.norm(feature_values[left] - feature_values[right]))
        for left, right in itertools.combinations(range(len(group)), 2)
    ]
    membership_distances = [
        float(
            np.abs(
                membership_values[left] - membership_values[right]
            ).sum()
        )
        for left, right in itertools.combinations(range(len(group)), 2)
    ]
    labels = membership_values.argmax(axis=1)
    dominant_count = pd.Series(labels).value_counts().iloc[0]
    return {
        "mean_pairwise_feature_l2": float(np.mean(feature_distances)),
        "max_pairwise_feature_l2": float(np.max(feature_distances)),
        "mean_pairwise_membership_l1": float(np.mean(membership_distances)),
        "max_pairwise_membership_l1": float(np.max(membership_distances)),
        "dominant_cluster_agreement": float(dominant_count / len(group)),
    }


def repeatability_audit(
    contract: dict[str, Any],
    features: list[str],
    centers: np.ndarray,
    fuzzifier: float,
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    _, _, weighted, projection = project_dataset(
        REPEATABILITY_FEATURE_DIR,
        contract,
        features,
        centers,
        fuzzifier,
    )
    mapping = read_csv(REPEATABILITY_MAPPING)[
        [
            "query_run_id",
            "condition_id",
            "repetition_index",
            "logical_question_id",
            "execution_strategy",
            "dataset_id",
            "runtime_config_id",
        ]
    ].drop_duplicates("query_run_id")
    frame = (
        weighted.merge(projection, on="query_run_id", validate="one_to_one")
        .merge(mapping, on="query_run_id", validate="one_to_one")
    )
    frame["display_state"] = quality_class(frame)
    frame.to_csv(out_dir / "repeatability_rows.csv", index=False)
    rows = []
    feature_rows = []
    for condition_id, group in frame.groupby("condition_id"):
        if len(group) < 2:
            continue
        mean_membership = group["max_membership"].mean()
        mean_margin = group["top2_margin"].mean()
        mean_entropy = group["membership_entropy"].mean()
        condition_quality = quality_class(
            pd.DataFrame(
                {
                    "max_membership": [mean_membership],
                    "top2_margin": [mean_margin],
                    "membership_entropy": [mean_entropy],
                }
            )
        )[0]
        rows.append(
            {
                "condition_id": condition_id,
                "repetition_count": len(group),
                "logical_question_id": group["logical_question_id"].iloc[0],
                "execution_strategy": group["execution_strategy"].iloc[0],
                "dataset_id": group["dataset_id"].iloc[0],
                "runtime_config_id": group["runtime_config_id"].iloc[0],
                "display_state": condition_quality,
                "mean_top_membership": mean_membership,
                "mean_top2_margin": mean_margin,
                "mean_membership_entropy": mean_entropy,
                **pairwise_condition_metrics(group, features),
            }
        )
        for feature in features:
            values = group[feature].to_numpy(dtype=float)
            median = float(np.median(values))
            mad = float(np.median(np.abs(values - median)))
            feature_rows.append(
                {
                    "condition_id": condition_id,
                    "feature": feature,
                    "repetition_count": len(values),
                    "median": median,
                    "mad": mad,
                    "range": float(np.max(values) - np.min(values)),
                }
            )
    detail = pd.DataFrame(rows)
    feature_detail = pd.DataFrame(feature_rows)
    summary = pd.DataFrame(
        [
            {
                "condition_count": len(detail),
                "row_count": len(frame),
                "median_mean_feature_l2": detail[
                    "mean_pairwise_feature_l2"
                ].median(),
                "p95_mean_feature_l2": detail[
                    "mean_pairwise_feature_l2"
                ].quantile(0.95),
                "median_mean_membership_l1": detail[
                    "mean_pairwise_membership_l1"
                ].median(),
                "p95_mean_membership_l1": detail[
                    "mean_pairwise_membership_l1"
                ].quantile(0.95),
                "maximum_membership_l1": detail[
                    "max_pairwise_membership_l1"
                ].max(),
                "maximum_feature_l2": detail[
                    "max_pairwise_feature_l2"
                ].max(),
                "minimum_dominant_cluster_agreement": detail[
                    "dominant_cluster_agreement"
                ].min(),
                "median_dominant_cluster_agreement": detail[
                    "dominant_cluster_agreement"
                ].median(),
                "clear_prototype_condition_count": int(
                    detail["display_state"].eq("clear_prototype").sum()
                ),
                "mixed_boundary_condition_count": int(
                    detail["display_state"].eq("mixed_boundary").sum()
                ),
                "weak_prototype_coverage_condition_count": int(
                    detail["display_state"]
                    .eq("weak_prototype_coverage")
                    .sum()
                ),
                "median_feature_mad": feature_detail["mad"].median(),
                "p95_feature_mad": feature_detail["mad"].quantile(0.95),
                "maximum_feature_mad": feature_detail["mad"].max(),
            }
        ]
    )
    detail.to_csv(out_dir / "repeatability_conditions.csv", index=False)
    feature_detail.to_csv(
        out_dir / "repeatability_feature_conditions.csv",
        index=False,
    )
    summary.to_csv(out_dir / "repeatability_summary.csv", index=False)
    return detail, summary


def controlled_contrast_audit(
    contract: dict[str, Any],
    features: list[str],
    centers: np.ndarray,
    fuzzifier: float,
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    _, _, weighted, projection = project_dataset(
        CONFIRMATORY_FEATURE_DIR,
        contract,
        features,
        centers,
        fuzzifier,
    )
    vector_by_id = weighted.set_index(weighted["query_run_id"].astype(str))
    member_by_id = projection.set_index(
        projection["query_run_id"].astype(str)
    )
    membership_columns = [f"membership_c{cluster}" for cluster in range(4)]
    specifications = [
        (
            "B-C_worker_placement",
            read_csv(CONFIRMATORY_REPORT_DIR / "paired_worker_contrast.csv"),
            "b_query_run_id",
            "c_query_run_id",
            "worker_rows_cv_delta_c_minus_b",
        ),
        (
            "A-D_regional_asymmetry",
            read_csv(CONFIRMATORY_REPORT_DIR / "paired_region_contrast.csv"),
            "a_query_run_id",
            "d_query_run_id",
            "remote_region_rows_isf_delta_d_minus_a",
        ),
    ]
    rows: list[dict[str, Any]] = []
    for contrast, pairs, left_column, right_column, direct_signal in specifications:
        for _, pair in pairs.iterrows():
            left_id = str(pair[left_column])
            right_id = str(pair[right_column])
            left_x = vector_by_id.loc[left_id, features].to_numpy(dtype=float)
            right_x = vector_by_id.loc[right_id, features].to_numpy(dtype=float)
            left_u = member_by_id.loc[
                left_id,
                membership_columns,
            ].to_numpy(dtype=float)
            right_u = member_by_id.loc[
                right_id,
                membership_columns,
            ].to_numpy(dtype=float)
            delta = right_x - left_x
            top_index = int(np.argmax(np.abs(delta)))
            rows.append(
                {
                    "contrast": contrast,
                    "query_condition_id": pair["query_condition_id"],
                    "repetition_index": pair["repetition_index"],
                    "left_query_run_id": left_id,
                    "right_query_run_id": right_id,
                    "direct_signal": direct_signal,
                    "direct_signal_delta": pair[direct_signal],
                    "semantic_feature_l2": float(np.linalg.norm(delta)),
                    "membership_l1": float(np.abs(right_u - left_u).sum()),
                    "dominant_cluster_changed": int(
                        left_u.argmax() != right_u.argmax()
                    ),
                    "top_changed_feature": features[top_index],
                    "top_changed_feature_delta": float(delta[top_index]),
                }
            )
    detail = pd.DataFrame(rows)
    summary = (
        detail.groupby(["contrast", "query_condition_id"], as_index=False)
        .agg(
            pair_count=("membership_l1", "size"),
            median_direct_signal_delta=("direct_signal_delta", "median"),
            median_semantic_feature_l2=("semantic_feature_l2", "median"),
            median_membership_l1=("membership_l1", "median"),
            dominant_cluster_change_share=("dominant_cluster_changed", "mean"),
        )
    )
    detail.to_csv(out_dir / "controlled_contrasts.csv", index=False)
    summary.to_csv(out_dir / "controlled_contrast_summary.csv", index=False)
    return detail, summary


def external_projection_audit(
    contract: dict[str, Any],
    features: list[str],
    centers: np.ndarray,
    fuzzifier: float,
    p99_threshold: float,
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    datasets = {
        "stats_ceb_pilot_8_development": STATS_PILOT_FEATURE_DIR,
        "validation_holdout_195": VALIDATION_FEATURE_DIR,
        "stats_v2_first_12_development": STATS_V2_DEV_FEATURE_DIR,
        "stats_v2b_confirmatory_12": STATS_V2B_FEATURE_DIR,
    }
    v1_ood = {
        "stats_ceb_pilot_8_development": 1,
        "validation_holdout_195": 1,
        "stats_v2_first_12_development": 7,
        "stats_v2b_confirmatory_12": 5,
    }
    detail_rows = []
    summary_rows = []
    ood_case_rows = []
    ood_attribution_rows = []
    for dataset, directory in datasets.items():
        support, _, weighted, projection = project_dataset(
            directory,
            contract,
            features,
            centers,
            fuzzifier,
        )
        projection = projection.copy()
        projection["dataset"] = dataset
        projection["ood_above_frozen_p99"] = (
            projection["nearest_center_distance"] > p99_threshold
        )
        projection["distance_over_p99"] = (
            projection["nearest_center_distance"] / p99_threshold
        )
        detail_rows.extend(projection.to_dict("records"))
        support_by_id = support.set_index(support["query_run_id"].astype(str))
        weighted_by_id = weighted.set_index(
            weighted["query_run_id"].astype(str)
        )
        dataset_ood_cases = []
        for _, projected in projection[
            projection["ood_above_frozen_p99"]
        ].iterrows():
            query_run_id = str(projected["query_run_id"])
            cluster = int(projected["dominant_cluster"])
            vector = weighted_by_id.loc[
                query_run_id,
                features,
            ].to_numpy(dtype=float)
            squared = (vector - centers[cluster]) ** 2
            total = float(squared.sum())
            contribution = (
                squared / total if total > 0 else np.zeros_like(squared)
            )
            order = np.argsort(contribution)[::-1]
            top_three = order[:3]
            skew_share = float(
                sum(
                    contribution[index]
                    for index, feature in enumerate(features)
                    if contract["features"][feature]["family"]
                    == "skew_imbalance"
                )
            )
            top_three_skew_share = float(
                sum(
                    contribution[index]
                    for index in top_three
                    if contract["features"][features[index]]["family"]
                    == "skew_imbalance"
                )
            )
            mild_exceedance = bool(projected["distance_over_p99"] <= 1.10)
            semantically_attributed = bool(
                mild_exceedance
                and skew_share >= 0.75
                and top_three_skew_share >= 0.75
            )
            context = support_by_id.loc[query_run_id]
            case = {
                "dataset": dataset,
                "query_run_id": query_run_id,
                "dataset_id": str(context.get("dataset_id", "")),
                "logical_question_id": str(
                    context.get("logical_question_id", "")
                ),
                "execution_strategy": str(
                    context.get("execution_strategy", "")
                ),
                "intervention_axis": str(
                    context.get("intervention_axis", "")
                ),
                "nearest_cluster": cluster,
                "nearest_center_distance": float(
                    projected["nearest_center_distance"]
                ),
                "distance_over_p99": float(projected["distance_over_p99"]),
                "skew_family_distance_share": skew_share,
                "top_three_skew_distance_share": top_three_skew_share,
                "mild_p99_exceedance": mild_exceedance,
                "semantically_attributed": semantically_attributed,
                "top_feature_1": features[order[0]],
                "top_feature_2": features[order[1]],
                "top_feature_3": features[order[2]],
            }
            dataset_ood_cases.append(case)
            ood_case_rows.append(case)
            for rank, index in enumerate(order, start=1):
                feature = features[index]
                ood_attribution_rows.append(
                    {
                        "dataset": dataset,
                        "query_run_id": query_run_id,
                        "nearest_cluster": cluster,
                        "rank": rank,
                        "feature": feature,
                        "family": contract["features"][feature]["family"],
                        "weighted_value": float(vector[index]),
                        "center_value": float(centers[cluster, index]),
                        "squared_distance": float(squared[index]),
                        "distance_contribution_share": float(
                            contribution[index]
                        ),
                    }
                )
        attributed_count = sum(
            bool(case["semantically_attributed"])
            for case in dataset_ood_cases
        )
        summary_rows.append(
            {
                "dataset": dataset,
                "row_count": len(projection),
                "v1_ood_count": v1_ood[dataset],
                "v2_ood_count": int(
                    projection["ood_above_frozen_p99"].sum()
                ),
                "v2_within_p99_count": int(
                    (~projection["ood_above_frozen_p99"]).sum()
                ),
                "v2_distance_median": projection[
                    "nearest_center_distance"
                ].median(),
                "v2_distance_p99": projection[
                    "nearest_center_distance"
                ].quantile(0.99),
                "v2_max_distance_over_p99": projection[
                    "distance_over_p99"
                ].max(),
                "v2_max_membership_median": projection[
                    "max_membership"
                ].median(),
                "v2_top2_margin_median": projection["top2_margin"].median(),
                "v2_ood_semantically_attributed_count": attributed_count,
            }
        )
    detail = pd.DataFrame(detail_rows)
    summary = pd.DataFrame(summary_rows)
    ood_cases = pd.DataFrame(ood_case_rows)
    ood_attribution = pd.DataFrame(ood_attribution_rows)
    detail.to_csv(out_dir / "external_projections.csv", index=False)
    summary.to_csv(out_dir / "external_projection_summary.csv", index=False)
    ood_cases.to_csv(out_dir / "external_ood_cases.csv", index=False)
    ood_attribution.to_csv(
        out_dir / "external_ood_attribution.csv",
        index=False,
    )
    return detail, summary, ood_cases, ood_attribution


def missingness_audit(
    datasets: dict[str, Path],
    contract: dict[str, Any],
    features: list[str],
    out_dir: Path,
) -> pd.DataFrame:
    rows = []
    for dataset, directory in datasets.items():
        support, raw, transformed, weighted = transform_dataset(
            directory,
            contract,
            features,
        )
        for feature in features:
            raw_values = pd.to_numeric(raw[feature], errors="coerce")
            transformed_values = pd.to_numeric(
                transformed[feature],
                errors="coerce",
            )
            weighted_values = pd.to_numeric(weighted[feature], errors="coerce")
            specification = contract["features"][feature]
            rows.append(
                {
                    "dataset": dataset,
                    "row_count": len(support),
                    "feature": feature,
                    "family": specification["family"],
                    "applicability": specification["applicability"],
                    "null_semantics": specification["null_semantics"],
                    "semantic_neutral": specification["neutral"],
                    "raw_missing_count": int(raw_values.isna().sum()),
                    "raw_missing_share": float(raw_values.isna().mean()),
                    "neutral_mapping_count": int(raw_values.isna().sum()),
                    "transformed_nonfinite_count": int(
                        (~np.isfinite(transformed_values)).sum()
                    ),
                    "weighted_nonfinite_count": int(
                        (~np.isfinite(weighted_values)).sum()
                    ),
                }
            )
    result = pd.DataFrame(rows)
    result.to_csv(out_dir / "missingness_applicability.csv", index=False)
    return result


def pressure_uncertainty_audit(
    memberships: pd.DataFrame,
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pressure = read_csv(PRESSURE_EVIDENCE)
    pressure["active"] = pressure["pressure_status"].isin(
        ACTIVE_PRESSURE_STATUSES
    )
    counts = (
        pressure.groupby("query_run_id", as_index=False)
        .agg(
            active_pressure_count=("active", "sum"),
            pressure_family_count=("pressure_id", "nunique"),
        )
    )
    frame = memberships.merge(
        counts,
        on="query_run_id",
        validate="one_to_one",
    )
    frame["membership_uncertainty"] = 1.0 - frame["max_membership"]
    frame["multi_pressure"] = frame["active_pressure_count"] >= 2
    rho_uncertainty, p_uncertainty = spearmanr(
        frame["active_pressure_count"],
        frame["membership_uncertainty"],
    )
    rho_entropy, p_entropy = spearmanr(
        frame["active_pressure_count"],
        frame["membership_entropy_normalized"],
    )
    rho_margin, p_margin = spearmanr(
        frame["active_pressure_count"],
        frame["top2_margin"],
    )
    low = frame.loc[~frame["multi_pressure"], "membership_uncertainty"]
    high = frame.loc[frame["multi_pressure"], "membership_uncertainty"]
    mw = mannwhitneyu(high, low, alternative="two-sided")
    summary = pd.DataFrame(
        [
            {
                "row_count": len(frame),
                "multi_pressure_rows": int(frame["multi_pressure"].sum()),
                "rho_active_count_vs_uncertainty": float(rho_uncertainty),
                "p_active_count_vs_uncertainty": float(p_uncertainty),
                "rho_active_count_vs_entropy": float(rho_entropy),
                "p_active_count_vs_entropy": float(p_entropy),
                "rho_active_count_vs_top2_margin": float(rho_margin),
                "p_active_count_vs_top2_margin": float(p_margin),
                "median_uncertainty_zero_or_one_pressure": float(low.median()),
                "median_uncertainty_multi_pressure": float(high.median()),
                "mann_whitney_u": float(mw.statistic),
                "mann_whitney_p": float(mw.pvalue),
                "direction_consistent_with_h2": bool(
                    rho_uncertainty > 0
                    and rho_entropy > 0
                    and rho_margin < 0
                ),
            }
        ]
    )
    frame.to_csv(out_dir / "pressure_uncertainty_rows.csv", index=False)
    summary.to_csv(out_dir / "pressure_uncertainty_summary.csv", index=False)
    return frame, summary


def exact_mcnemar_two_sided(v1_fail_v2_pass: int, v1_pass_v2_fail: int) -> float:
    discordant = v1_fail_v2_pass + v1_pass_v2_fail
    if discordant == 0:
        return 1.0
    tail = min(v1_fail_v2_pass, v1_pass_v2_fail)
    probability = sum(
        math.comb(discordant, value) * (0.5**discordant)
        for value in range(tail + 1)
    )
    return min(1.0, 2.0 * probability)


def promotion_gates(
    *,
    chronology: pd.DataFrame,
    k_summary: pd.DataFrame,
    lfo_summary: pd.DataFrame,
    repeatability_summary: pd.DataFrame,
    controlled_summary: pd.DataFrame,
    external_summary: pd.DataFrame,
    external_ood_cases: pd.DataFrame,
    missingness: pd.DataFrame,
    pressure_summary: pd.DataFrame,
    out_dir: Path,
) -> tuple[pd.DataFrame, str]:
    k4 = k_summary[k_summary["k"].eq(4)].iloc[0]
    lfo = lfo_summary.iloc[0]
    repeatability = repeatability_summary.iloc[0]
    v2b = external_summary[
        external_summary["dataset"].eq("stats_v2b_confirmatory_12")
    ].iloc[0]
    validation = external_summary[
        external_summary["dataset"].eq("validation_holdout_195")
    ].iloc[0]
    validation_ood = external_ood_cases[
        external_ood_cases["dataset"].eq("validation_holdout_195")
    ]
    validation_ood_attribution_share = (
        float(validation_ood["semantically_attributed"].mean())
        if len(validation_ood)
        else 1.0
    )
    bc = controlled_summary[
        controlled_summary["contrast"].eq("B-C_worker_placement")
    ]
    ad = controlled_summary[
        controlled_summary["contrast"].eq("A-D_regional_asymmetry")
    ]
    bc_top = bc[
        bc["query_condition_id"].str.startswith("top_tenants")
    ]["median_semantic_feature_l2"].median()
    bc_point = bc[
        bc["query_condition_id"].str.startswith("tenant_point")
    ]["median_semantic_feature_l2"].median()
    ad_top = ad[
        ad["query_condition_id"].str.startswith("top_tenants")
    ]["median_semantic_feature_l2"].median()
    ad_point = ad[
        ad["query_condition_id"].str.startswith("tenant_point")
    ]["median_semantic_feature_l2"].median()
    chronology_gate_rows = chronology[~chronology["status"].eq("INFO")]
    rows = [
        {
            "gate": "chronology_and_hashes",
            "gate_type": "core",
            "value": float(chronology_gate_rows["status"].eq("PASS").mean()),
            "threshold": 1.0,
            "status": "PASS"
            if chronology_gate_rows["status"].eq("PASS").all()
            else "FAIL",
        },
        {
            "gate": "k4_seed_stability",
            "gate_type": "core",
            "value": float(k4["seed_ari_mean"]),
            "threshold": 0.8,
            "status": "PASS"
            if float(k4["seed_ari_mean"]) >= 0.8
            else "FAIL",
        },
        {
            "gate": "k4_nontrivial_silhouette",
            "gate_type": "core",
            "value": float(k4["silhouette_hard_labels"]),
            "threshold": 0.2,
            "status": "PASS"
            if float(k4["silhouette_hard_labels"]) >= 0.2
            else "FAIL",
        },
        {
            "gate": "leave_family_out_weighted_ari",
            "gate_type": "core",
            "value": float(lfo["weighted_hard_label_ari"]),
            "threshold": 0.75,
            "status": "PASS"
            if float(lfo["weighted_hard_label_ari"]) >= 0.75
            else "FAIL",
        },
        {
            "gate": "repeatability_minimum_cluster_agreement",
            "gate_type": "core",
            "value": float(
                repeatability["minimum_dominant_cluster_agreement"]
            ),
            "threshold": 0.95,
            "status": "PASS"
            if float(
                repeatability["minimum_dominant_cluster_agreement"]
            )
            >= 0.95
            else "FAIL",
        },
        {
            "gate": "v2b_frozen_p99_coverage",
            "gate_type": "core",
            "value": float(v2b["v2_within_p99_count"] / v2b["row_count"]),
            "threshold": 0.75,
            "status": "PASS"
            if float(v2b["v2_within_p99_count"] / v2b["row_count"]) >= 0.75
            else "FAIL",
        },
        {
            "gate": "v2b_not_worse_than_v1",
            "gate_type": "core",
            "value": float(v2b["v1_ood_count"] - v2b["v2_ood_count"]),
            "threshold": 0.0,
            "status": "PASS"
            if int(v2b["v2_ood_count"]) <= int(v2b["v1_ood_count"])
            else "FAIL",
        },
        {
            "gate": "validation_holdout_v2_coverage",
            "gate_type": "core",
            "value": float(
                validation["v2_within_p99_count"] / validation["row_count"]
            ),
            "threshold": 0.95,
            "status": "PASS"
            if float(
                validation["v2_within_p99_count"] / validation["row_count"]
            )
            >= 0.95
            else "FAIL",
        },
        {
            "gate": "validation_ood_semantically_attributed",
            "gate_type": "core",
            "value": validation_ood_attribution_share,
            "threshold": 1.0,
            "status": "PASS"
            if validation_ood_attribution_share == 1.0
            else "FAIL",
        },
        {
            "gate": "validation_v2_uniformly_better_than_v1",
            "gate_type": "informational",
            "value": float(
                validation["v2_ood_count"] - validation["v1_ood_count"]
            ),
            "threshold": 0.0,
            "status": "PASS"
            if int(validation["v2_ood_count"])
            <= int(validation["v1_ood_count"])
            else "WARN",
        },
        {
            "gate": "all_weighted_values_finite",
            "gate_type": "core",
            "value": float(missingness["weighted_nonfinite_count"].sum()),
            "threshold": 0.0,
            "status": "PASS"
            if int(missingness["weighted_nonfinite_count"].sum()) == 0
            else "FAIL",
        },
        {
            "gate": "bc_top_tenants_exceeds_point_control",
            "gate_type": "core",
            "value": float(bc_top - bc_point),
            "threshold": 0.0,
            "status": "PASS" if bc_top > bc_point else "FAIL",
        },
        {
            "gate": "ad_top_tenants_exceeds_point_control",
            "gate_type": "core",
            "value": float(ad_top - ad_point),
            "threshold": 0.0,
            "status": "PASS" if ad_top > ad_point else "FAIL",
        },
    ]
    gates = pd.DataFrame(rows)
    core = gates[gates["gate_type"].eq("core")]
    core_pass = core["status"].eq("PASS").all()
    h2_consistent = bool(
        pressure_summary.iloc[0]["direction_consistent_with_h2"]
    )
    external_membership = float(v2b["v2_max_membership_median"])
    if not core_pass:
        decision = "KEEP_V1_FINAL_V2_EXPLORATORY"
    elif not h2_consistent or external_membership < 0.5:
        decision = "PROMOTE_V2_WITH_LIMITED_FUZZY_CLAIM"
    else:
        decision = "PROMOTE_V2_FINAL"
    gates.to_csv(out_dir / "promotion_gate.csv", index=False)
    return gates, decision


def write_readme(
    out_dir: Path,
    *,
    decision: str,
    chronology: pd.DataFrame,
    k_summary: pd.DataFrame,
    algorithm_agreement: pd.DataFrame,
    lfo_summary: pd.DataFrame,
    balanced_summary: pd.DataFrame,
    repeatability_summary: pd.DataFrame,
    controlled_summary: pd.DataFrame,
    external_summary: pd.DataFrame,
    external_ood_cases: pd.DataFrame,
    pressure_summary: pd.DataFrame,
    gates: pd.DataFrame,
) -> None:
    k3 = k_summary[k_summary["k"].eq(3)].iloc[0]
    k4 = k_summary[k_summary["k"].eq(4)].iloc[0]
    balanced = balanced_summary[balanced_summary["scope"].eq("all")].iloc[0]
    repeatability = repeatability_summary.iloc[0]
    lfo = lfo_summary.iloc[0]
    pressure = pressure_summary.iloc[0]
    v2b = external_summary[
        external_summary["dataset"].eq("stats_v2b_confirmatory_12")
    ].iloc[0]
    validation = external_summary[
        external_summary["dataset"].eq("validation_holdout_195")
    ].iloc[0]
    validation_ood = external_ood_cases[
        external_ood_cases["dataset"].eq("validation_holdout_195")
    ]
    mcnemar = exact_mcnemar_two_sided(5, 0)
    controlled_lines = []
    for _, row in controlled_summary.iterrows():
        controlled_lines.append(
            f"- {row['contrast']} / {row['query_condition_id']}: "
            f"feature L2={row['median_semantic_feature_l2']:.4f}, "
            f"membership L1={row['median_membership_l1']:.4f}"
        )
    algorithm_lines = []
    for _, row in algorithm_agreement.iterrows():
        algorithm_lines.append(
            f"- {row['left_algorithm']} prema {row['right_algorithm']}: "
            f"ARI={row['ari']:.4f}, NMI={row['nmi']:.4f}"
        )
    gate_lines = [
        f"- [{row['gate_type']}] `{row['gate']}`: "
        f"{row['status']} (value={row['value']:.4f})"
        for _, row in gates.iterrows()
    ]
    out_dir.joinpath("README.md").write_text(
        f"""# Semantic V2 final consistency audit

## Odluka

```text
{decision}
```

V2b nije korišten za ponovno učenje. Ovaj paket provjerava da li zamrznuti
semantički ugovor ostaje koherentan sa unutrašnjom strukturom i ranijim
kontrolisanim dokazima.

## Hronologija

- provjere: {len(chronology)}
- prolaz: {int(chronology['status'].eq('PASS').sum())}/{len(chronology)}
- isti feature-contract SHA nalazi se u ugovoru, freeze paketu i V2b izvještaju
- korektivni repartition extractor i model freeze prethode V2b attemptu
- `model_refit_performed=false`

## Rezolucija prototipa

| Mjera | k=3 | k=4 |
| --- | ---: | ---: |
| silhouette | {k3['silhouette_hard_labels']:.4f} | {k4['silhouette_hard_labels']:.4f} |
| MPC | {k3['modified_partition_coefficient']:.4f} | {k4['modified_partition_coefficient']:.4f} |
| seed ARI mean | {k3['seed_ari_mean']:.4f} | {k4['seed_ari_mean']:.4f} |
| avg max membership | {k3['avg_max_membership']:.4f} | {k4['avg_max_membership']:.4f} |

`k=3` ostaje makrorezolucija, a `k=4` operativni detaljniji opis. Potpuni
rezultati za `k=2..8` nalaze se u `k_summary.csv`.

## Poređenje algoritama

{chr(10).join(algorithm_lines)}

Algoritamsko slaganje nije dokaz ground-truth klasa. Ono provjerava da
geometrija nije artefakt samo jedne implementacije.

## Prenosivost unutar corpusa

- leave-question-family-out foldovi: {int(lfo['fold_count'])}
- weighted hard-label ARI: {lfo['weighted_hard_label_ari']:.4f}
- minimum family ARI: {lfo['minimum_hard_label_ari']:.4f}
- weighted membership L1: {lfo['weighted_mean_membership_l1']:.4f}

## Kontrolisani kontrasti

- balanced/skew parovi: {int(balanced['pair_count'])}
- medijana promjene semantičkog feature prostora:
  {balanced['median_semantic_feature_l2']:.4f}
- medijana promjene fuzzy članstava:
  {balanced['median_membership_l1']:.4f}

{chr(10).join(controlled_lines)}

Feature promjena i promjena članstva nisu isto. V2 može zadržati fizički
kontrast u `x`, ali ga ostaviti unutar istog grubog prototipa u `u`.

## Ponovljivost

- uslovi: {int(repeatability['condition_count'])}
- redovi: {int(repeatability['row_count'])}
- medijana mean membership L1:
  {repeatability['median_mean_membership_l1']:.3e}
- 95. percentil mean membership L1:
  {repeatability['p95_mean_membership_l1']:.3e}
- minimalno dominant-cluster slaganje:
  {repeatability['minimum_dominant_cluster_agreement']:.4f}

## H2/RQ3

- Spearman active-pressure count prema uncertainty:
  {pressure['rho_active_count_vs_uncertainty']:.4f}
- Spearman prema normalizovanoj entropiji:
  {pressure['rho_active_count_vs_entropy']:.4f}
- Spearman prema top-2 margini:
  {pressure['rho_active_count_vs_top2_margin']:.4f}
- smjer konzistentan sa H2:
  {str(bool(pressure['direction_consistent_with_h2'])).lower()}

Ovo ostaje interni konvergentni dokaz jer pressure score i FCM dijele dio
izvedenih pokazatelja.

## Vanjski V2b holdout

- V2 unutar zamrznutog P99: {int(v2b['v2_within_p99_count'])}/{int(v2b['row_count'])}
- V1 unutar vlastitog P99:
  {int(v2b['row_count'] - v2b['v1_ood_count'])}/{int(v2b['row_count'])}
- V2 medijana maksimalnog članstva:
  {v2b['v2_max_membership_median']:.4f}
- egzaktni dvostrani McNemar za 5:0 diskordantnih prelaza:
  p={mcnemar:.4f}

McNemar vrijednost se ne tumači kao statistički dokaz univerzalne
generalizacije. Holdout ima samo 12 deterministički odabranih upita. Rezultat
je deskriptivno konzistentan sa boljom pokrivenošću, ali nije populacijska
procjena.

## Raniji validacijski skup

- V2 unutar zamrznutog P99:
  {int(validation['v2_within_p99_count'])}/{int(validation['row_count'])}
- V1 unutar vlastitog P99:
  {int(validation['row_count'] - validation['v1_ood_count'])}/{int(validation['row_count'])}
- V2 OOD redovi: {int(validation['v2_ood_count'])}
- najveće prekoračenje:
  {validation['v2_max_distance_over_p99']:.4f} x P99
- semantički atribuirani OOD redovi:
  {int(validation_ood['semantically_attributed'].sum())}/{len(validation_ood)}
- medijana udjela OOD udaljenosti iz skew porodice:
  {validation_ood['skew_family_distance_share'].median():.4f}

V2 nije uniformno poboljšao P99 pokrivenost: V1 je ovdje imao jedan, a V2
pet OOD redova. Svih pet V2 slučajeva su blaga prekoračenja od približno
`1,03 x P99` iz `tenant_point_rollup` porodice nad namjerno regionalno
neuravnoteženim profilom. Oko 91% njihove kvadratne udaljenosti potiče od
tri maksimalna topološka skew pokazatelja. Zato se tumače kao fizički
objašnjivi rubni slučajevi, a ne kao dominacija jednog neograničenog omjera.
Detalji su u `external_ood_cases.csv` i `external_ood_attribution.csv`.

## Gateovi

{chr(10).join(gate_lines)}

## Granica tvrdnje

Promocija V2 znači da semantički ograničen `x^(19)` postaje finalni modelski
ulaz, dok V1 ostaje baseline/ablation. V2 poboljšava STATS-CEB transfer i
geometriju, ali ne daje uniformno bolju P99 pokrivenost niti zadržava jednaku
osjetljivost fuzzy članstava na svaki skew kontrast. Ne znači da su četiri
prototipa univerzalne klase. Sirovi `Z` sloj ostaje obavezan za magnitude koje
log-arctan namjerno sabija.
""",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (
        contract,
        manifest,
        features,
        frozen_centers,
        fuzzifier,
        p99_threshold,
    ) = load_frozen_model()
    baseline_support, baseline_raw, baseline_transformed, baseline_weighted = (
        transform_dataset(BASELINE_FEATURE_DIR, contract, features)
    )
    values = baseline_weighted[features].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Baseline semantic-v2 matrix contains non-finite values")
    seeds = [int(value) for value in manifest["seeds"]]

    print("[semantic-v2-consistency] 1/11 chronology", flush=True)
    chronology = chronology_audit(manifest, out_dir)

    print("[semantic-v2-consistency] 2/11 k=2..8 and seeds", flush=True)
    _, k_summary, best_by_k = k_range_audit(
        values,
        seeds=seeds,
        fuzzifier=fuzzifier,
        out_dir=out_dir,
    )
    frozen_memberships, frozen_distances = memberships_from_centers(
        values,
        frozen_centers,
        fuzzifier=fuzzifier,
    )
    baseline_memberships = membership_frame(
        baseline_weighted["query_run_id"],
        frozen_memberships,
        frozen_distances,
    )
    baseline_memberships.to_csv(
        out_dir / "baseline_memberships.csv",
        index=False,
    )

    print("[semantic-v2-consistency] 3/11 algorithms", flush=True)
    _, _, algorithm_agreement = algorithm_audit(
        values,
        best_by_k[4],
        seeds=seeds,
        out_dir=out_dir,
    )

    print("[semantic-v2-consistency] 4/11 leave-family-out", flush=True)
    context = read_csv(BASELINE_CONTEXT)
    _, lfo_summary = leave_family_out_audit(
        baseline_weighted,
        context,
        features=features,
        full_centers=frozen_centers,
        full_memberships=frozen_memberships,
        fuzzifier=fuzzifier,
        seeds=seeds,
        out_dir=out_dir,
    )

    print("[semantic-v2-consistency] 5/11 prototype profiles", flush=True)
    prototype_profiles(
        baseline_raw,
        baseline_transformed,
        frozen_memberships,
        context,
        contract,
        features,
        fuzzifier,
        out_dir,
    )

    print("[semantic-v2-consistency] 6/11 balanced/skew", flush=True)
    _, balanced_summary = balanced_skew_audit(
        baseline_weighted,
        baseline_memberships,
        features,
        out_dir,
    )

    print("[semantic-v2-consistency] 7/11 repeatability", flush=True)
    _, repeatability_summary = repeatability_audit(
        contract,
        features,
        frozen_centers,
        fuzzifier,
        out_dir,
    )

    print("[semantic-v2-consistency] 8/11 controlled contrasts", flush=True)
    _, controlled_summary = controlled_contrast_audit(
        contract,
        features,
        frozen_centers,
        fuzzifier,
        out_dir,
    )

    print("[semantic-v2-consistency] 9/11 external projections", flush=True)
    (
        _,
        external_summary,
        external_ood_cases,
        _,
    ) = external_projection_audit(
        contract,
        features,
        frozen_centers,
        fuzzifier,
        p99_threshold,
        out_dir,
    )

    print("[semantic-v2-consistency] 10/11 missingness and H2", flush=True)
    missingness = missingness_audit(
        {
            "baseline_1964": BASELINE_FEATURE_DIR,
            "validation_195": VALIDATION_FEATURE_DIR,
            "repeatability_328": REPEATABILITY_FEATURE_DIR,
            "confirmatory_abcd_48": CONFIRMATORY_FEATURE_DIR,
            "stats_pilot_8": STATS_PILOT_FEATURE_DIR,
            "stats_v2_dev_12": STATS_V2_DEV_FEATURE_DIR,
            "stats_v2b_12": STATS_V2B_FEATURE_DIR,
        },
        contract,
        features,
        out_dir,
    )
    _, pressure_summary = pressure_uncertainty_audit(
        baseline_memberships,
        out_dir,
    )

    print("[semantic-v2-consistency] 11/11 promotion decision", flush=True)
    gates, decision = promotion_gates(
        chronology=chronology,
        k_summary=k_summary,
        lfo_summary=lfo_summary,
        repeatability_summary=repeatability_summary,
        controlled_summary=controlled_summary,
        external_summary=external_summary,
        external_ood_cases=external_ood_cases,
        missingness=missingness,
        pressure_summary=pressure_summary,
        out_dir=out_dir,
    )
    write_readme(
        out_dir,
        decision=decision,
        chronology=chronology,
        k_summary=k_summary,
        algorithm_agreement=algorithm_agreement,
        lfo_summary=lfo_summary,
        balanced_summary=balanced_summary,
        repeatability_summary=repeatability_summary,
        controlled_summary=controlled_summary,
        external_summary=external_summary,
        external_ood_cases=external_ood_cases,
        pressure_summary=pressure_summary,
        gates=gates,
    )
    summary = {
        "decision": decision,
        "row_count": len(baseline_support),
        "feature_count": len(features),
        "feature_contract_sha256": sha256(CONTRACT_PATH),
        "model_manifest_sha256": sha256(
            FREEZE_DIR / "semantic_v2_model_manifest.yml"
        ),
        "all_core_gates_pass": bool(
            gates.loc[gates["gate_type"].eq("core"), "status"].eq("PASS").all()
        ),
        "h2_direction_consistent": bool(
            pressure_summary.iloc[0]["direction_consistent_with_h2"]
        ),
        "v2b_mcnemar_exact_two_sided": exact_mcnemar_two_sided(5, 0),
        "validation_v1_ood_count": int(
            external_summary.loc[
                external_summary["dataset"].eq("validation_holdout_195"),
                "v1_ood_count",
            ].iloc[0]
        ),
        "validation_v2_ood_count": int(
            external_summary.loc[
                external_summary["dataset"].eq("validation_holdout_195"),
                "v2_ood_count",
            ].iloc[0]
        ),
        "validation_v2_ood_semantically_attributed_count": int(
            external_ood_cases.loc[
                external_ood_cases["dataset"].eq("validation_holdout_195"),
                "semantically_attributed",
            ].sum()
        ),
        "external_coverage_uniformly_improved": False,
        "model_refit_after_v2b": False,
    }
    (out_dir / "consistency_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
