from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import adjusted_rand_score, silhouette_score


@dataclass(frozen=True)
class FCMResult:
    k: int
    seed: int
    centers: np.ndarray
    memberships: np.ndarray
    labels: np.ndarray
    objective: float
    iterations: int
    converged: bool


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _support_values(
    support: pd.DataFrame,
    candidates: Iterable[str],
) -> pd.Series:
    result = pd.Series(np.nan, index=support.index, dtype=float)
    for candidate in candidates:
        values = _numeric(support, candidate)
        result = result.where(result.notna(), values)
    return result


def _semantic_values(
    values: pd.Series,
    *,
    specification: dict[str, Any],
    support: pd.DataFrame,
) -> pd.Series:
    kind = str(specification["transform"])
    neutral = float(specification.get("neutral", 0.0))
    finite = values.astype(float)

    if kind == "bounded_share":
        transformed = finite.clip(lower=0.0, upper=1.0)
    elif kind == "nonnegative_log_atan":
        transformed = (2.0 / math.pi) * np.arctan(
            np.log1p(finite.clip(lower=0.0))
        )
    elif kind == "positive_baseline_log2_atan":
        transformed = (2.0 / math.pi) * np.arctan(
            np.log2(finite.clip(lower=1.0))
        )
    elif kind == "positive_excess_log_atan":
        transformed = (2.0 / math.pi) * np.arctan(
            np.log1p((finite - 1.0).clip(lower=0.0))
        )
    elif kind == "binary":
        transformed = finite.clip(lower=0.0, upper=1.0)
    elif kind == "signed_atan":
        transformed = 0.5 + np.arctan(finite) / math.pi
    elif kind in {"isf_excess_share", "max_share_excess"}:
        counts = _support_values(
            support,
            [str(value) for value in specification.get("support_columns", [])],
        )
        valid_counts = counts.where(counts > 1.0)
        if kind == "isf_excess_share":
            transformed = (finite - 1.0) / (valid_counts - 1.0)
        else:
            uniform_share = 1.0 / valid_counts
            transformed = (finite - uniform_share) / (1.0 - uniform_share)
        transformed = transformed.clip(lower=0.0, upper=1.0)
    else:
        raise ValueError(f"Unsupported semantic transform {kind!r}")
    return transformed.fillna(neutral).astype(float)


def semantic_transform(
    raw: pd.DataFrame,
    support: pd.DataFrame,
    contract: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if "query_run_id" not in raw or "query_run_id" not in support:
        raise ValueError("raw and support matrices must contain query_run_id")
    if raw["query_run_id"].duplicated().any() or support["query_run_id"].duplicated().any():
        raise ValueError("query_run_id must be unique in raw and support matrices")

    support_indexed = support.set_index(support["query_run_id"].astype(str))
    run_ids = raw["query_run_id"].astype(str)
    aligned_support = support_indexed.reindex(run_ids).reset_index(drop=True)
    specifications = contract.get("features", {})
    if not isinstance(specifications, dict) or not specifications:
        raise ValueError("Semantic contract must define feature specifications")

    transformed = pd.DataFrame({"query_run_id": run_ids})
    audit_rows: list[dict[str, Any]] = []
    for feature, specification in specifications.items():
        if feature not in raw:
            raise ValueError(f"Raw matrix is missing semantic feature {feature}")
        if not isinstance(specification, dict):
            raise ValueError(f"Invalid semantic specification for {feature}")
        values = _numeric(raw, feature)
        transformed[feature] = _semantic_values(
            values,
            specification=specification,
            support=aligned_support,
        )
        audit_rows.append(
            {
                "feature": feature,
                "family": str(specification["family"]),
                "transform": str(specification["transform"]),
                "neutral": float(specification.get("neutral", 0.0)),
                "missing_count": int(values.isna().sum()),
                "missing_share": float(values.isna().mean()),
                "semantic_min": float(transformed[feature].min()),
                "semantic_median": float(transformed[feature].median()),
                "semantic_p99": float(transformed[feature].quantile(0.99)),
                "semantic_max": float(transformed[feature].max()),
                "dropped_as_redundant": bool(
                    specification.get("drop_as_redundant", False)
                ),
                "redundant_with": str(specification.get("redundant_with", "")),
            }
        )

    dropped = {
        feature
        for feature, specification in specifications.items()
        if bool(specification.get("drop_as_redundant", False))
    }
    model_features = [feature for feature in specifications if feature not in dropped]
    family_counts: dict[str, int] = {}
    for feature in model_features:
        family = str(specifications[feature]["family"])
        family_counts[family] = family_counts.get(family, 0) + 1

    weighted = pd.DataFrame({"query_run_id": run_ids})
    weight_rows: list[dict[str, Any]] = []
    for feature in model_features:
        family = str(specifications[feature]["family"])
        weight = 1.0 / math.sqrt(family_counts[family])
        weighted[feature] = transformed[feature] * weight
        weight_rows.append(
            {
                "feature": feature,
                "family": family,
                "family_feature_count": family_counts[family],
                "family_energy_weight": weight,
            }
        )
    return transformed, weighted, pd.DataFrame(audit_rows).merge(
        pd.DataFrame(weight_rows),
        on=["feature", "family"],
        how="left",
    )


def squared_distances(values: np.ndarray, centers: np.ndarray) -> np.ndarray:
    difference = values[:, None, :] - centers[None, :, :]
    return np.sum(difference * difference, axis=2)


def memberships_from_centers(
    values: np.ndarray,
    centers: np.ndarray,
    *,
    fuzzifier: float,
) -> tuple[np.ndarray, np.ndarray]:
    if fuzzifier <= 1.0:
        raise ValueError("fuzzifier must be greater than 1")
    distances = np.maximum(squared_distances(values, centers), 1.0e-12)
    inverse = distances ** (-1.0 / (fuzzifier - 1.0))
    memberships = inverse / inverse.sum(axis=1, keepdims=True)
    return memberships, np.sqrt(distances)


def fit_fcm(
    values: np.ndarray,
    *,
    k: int,
    seed: int,
    fuzzifier: float = 1.7,
    max_iter: int = 600,
    tolerance: float = 1.0e-4,
) -> FCMResult:
    rng = np.random.default_rng(seed)
    memberships = rng.random((len(values), k)) + 1.0e-12
    memberships /= memberships.sum(axis=1, keepdims=True)
    previous = math.inf
    converged = False
    objective = math.inf
    centers = np.zeros((k, values.shape[1]), dtype=float)
    iteration = 0
    for _iteration in range(1, max_iter + 1):
        iteration = _iteration
        weights = memberships**fuzzifier
        centers = (weights.T @ values) / np.maximum(
            weights.sum(axis=0)[:, None],
            1.0e-12,
        )
        distances = np.maximum(squared_distances(values, centers), 1.0e-12)
        inverse = distances ** (-1.0 / (fuzzifier - 1.0))
        memberships = inverse / inverse.sum(axis=1, keepdims=True)
        objective = float(np.sum((memberships**fuzzifier) * distances))
        if abs(previous - objective) < tolerance:
            converged = True
            break
        previous = objective
    return FCMResult(
        k=k,
        seed=seed,
        centers=centers,
        memberships=memberships,
        labels=memberships.argmax(axis=1),
        objective=objective,
        iterations=iteration,
        converged=converged,
    )


def fit_best_fcm(
    values: np.ndarray,
    *,
    k: int,
    seeds: Iterable[int],
    fuzzifier: float = 1.7,
    max_iter: int = 600,
    tolerance: float = 1.0e-4,
) -> tuple[FCMResult, list[FCMResult]]:
    fits = [
        fit_fcm(
            values,
            k=k,
            seed=seed,
            fuzzifier=fuzzifier,
            max_iter=max_iter,
            tolerance=tolerance,
        )
        for seed in seeds
    ]
    return min(fits, key=lambda fit: fit.objective), fits


def align_fit(fit: FCMResult, reference: FCMResult) -> FCMResult:
    costs = np.sqrt(squared_distances(fit.centers, reference.centers))
    fit_indices, reference_indices = linear_sum_assignment(costs)
    centers = np.empty_like(fit.centers)
    memberships = np.empty_like(fit.memberships)
    for fit_index, reference_index in zip(
        fit_indices,
        reference_indices,
        strict=True,
    ):
        centers[reference_index] = fit.centers[fit_index]
        memberships[:, reference_index] = fit.memberships[:, fit_index]
    return FCMResult(
        k=fit.k,
        seed=fit.seed,
        centers=centers,
        memberships=memberships,
        labels=memberships.argmax(axis=1),
        objective=fit.objective,
        iterations=fit.iterations,
        converged=fit.converged,
    )


def fcm_metrics(values: np.ndarray, fit: FCMResult) -> dict[str, float]:
    memberships = fit.memberships
    k = fit.k
    partition_coefficient = float(np.mean(np.sum(memberships**2, axis=1)))
    safe = np.maximum(memberships, 1.0e-12)
    partition_entropy = float(
        -np.mean(np.sum(safe * np.log(safe), axis=1))
    )
    center_distances = squared_distances(fit.centers, fit.centers)
    center_distances[center_distances <= 1.0e-12] = np.inf
    minimum_center_distance = float(np.min(center_distances))
    labels = fit.labels
    silhouette = (
        float(silhouette_score(values, labels))
        if len(np.unique(labels)) > 1
        else math.nan
    )
    counts = np.bincount(labels, minlength=k)
    top2 = np.sort(memberships, axis=1)[:, -2:]
    return {
        "silhouette_hard_labels": silhouette,
        "partition_coefficient": partition_coefficient,
        "modified_partition_coefficient": (
            (partition_coefficient - 1.0 / k) / (1.0 - 1.0 / k)
        ),
        "partition_entropy": partition_entropy,
        "normalized_partition_entropy": partition_entropy / math.log(k),
        "xie_beni_index": fit.objective
        / max(len(values) * minimum_center_distance, 1.0e-12),
        "avg_max_membership": float(memberships.max(axis=1).mean()),
        "avg_top2_margin": float((top2[:, 1] - top2[:, 0]).mean()),
        "cluster_min_share": float(counts.min() / len(values)),
        "cluster_max_share": float(counts.max() / len(values)),
    }


def seed_stability(fits: list[FCMResult]) -> dict[str, float]:
    values = [
        float(adjusted_rand_score(left.labels, right.labels))
        for index, left in enumerate(fits)
        for right in fits[index + 1 :]
    ]
    return {
        "seed_ari_mean": float(np.mean(values)) if values else math.nan,
        "seed_ari_min": float(np.min(values)) if values else math.nan,
        "seed_ari_max": float(np.max(values)) if values else math.nan,
    }
