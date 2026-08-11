from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def load_feature_contract(
    preprocessing_report: Path,
    *,
    matrix_name: str,
) -> pd.DataFrame:
    report = pd.read_csv(preprocessing_report, low_memory=False)
    contract = report[
        report["matrix"].astype(str).eq(matrix_name)
        & report["status"].astype(str).eq("kept")
    ].copy()
    required = {"feature", "transform", "center", "scale"}
    missing = required - set(contract.columns)
    if contract.empty or missing:
        raise ValueError(
            f"Invalid preprocessing contract for {matrix_name}: "
            f"rows={len(contract)}, missing={sorted(missing)}"
        )
    return contract.reset_index(drop=True)


def apply_frozen_preprocessing(
    raw: pd.DataFrame,
    contract: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "query_run_id" not in raw.columns:
        raise ValueError("Raw feature matrix must contain query_run_id")
    scaled = pd.DataFrame({"query_run_id": raw["query_run_id"].astype(str)})
    quality: list[dict[str, Any]] = []
    for _, spec in contract.iterrows():
        feature = str(spec["feature"])
        if feature not in raw.columns:
            raise ValueError(f"Raw feature matrix is missing locked feature {feature}")
        values = pd.to_numeric(raw[feature], errors="coerce")
        transformed = values.copy()
        transform = str(spec["transform"])
        if transform == "log1p":
            transformed = np.log1p(transformed.where(transformed > -1))
        elif transform != "identity":
            raise ValueError(f"Unsupported transform {transform!r} for {feature}")
        center = float(spec["center"])
        scale = float(spec["scale"])
        if not math.isfinite(scale) or abs(scale) < 1.0e-12:
            scale = 1.0
        scaled[feature] = (transformed.fillna(center) - center) / scale
        quality.append(
            {
                "feature": feature,
                "transform": transform,
                "missing_count": int(values.isna().sum()),
                "missing_share": float(values.isna().mean()),
                "baseline_center": center,
                "baseline_scale": scale,
            }
        )
    return scaled, pd.DataFrame(quality)


def fuzzy_memberships(
    values: np.ndarray,
    centers: np.ndarray,
    *,
    fuzzifier: float,
) -> tuple[np.ndarray, np.ndarray]:
    if fuzzifier <= 1:
        raise ValueError("Fuzzifier must be greater than 1")
    difference = values[:, None, :] - centers[None, :, :]
    distances = np.sqrt(np.maximum(np.sum(difference * difference, axis=2), 1.0e-12))
    exponent = 2.0 / (fuzzifier - 1.0)
    ratios = distances[:, :, None] / distances[:, None, :]
    memberships = 1.0 / np.maximum(
        np.sum(np.power(ratios, exponent), axis=2),
        1.0e-12,
    )
    return memberships, distances


def display_state(
    maximum: float,
    margin: float,
    entropy: float,
) -> str:
    if maximum >= 0.50 and margin >= 0.15 and entropy < 1.05:
        return "clear_prototype"
    if maximum >= 0.35:
        return "mixed_boundary"
    return "weak_prototype_coverage"


def project_to_frozen_model(
    raw: pd.DataFrame,
    *,
    preprocessing_report: Path,
    centers_file: Path,
    baseline_scaled_file: Path,
    matrix_name: str,
    k: int,
    seed: int,
    fuzzifier: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    contract = load_feature_contract(
        preprocessing_report,
        matrix_name=matrix_name,
    )
    features = contract["feature"].astype(str).tolist()
    scaled, quality = apply_frozen_preprocessing(raw, contract)
    centers = pd.read_csv(centers_file, low_memory=False)
    selected = centers[
        centers["k"].astype(int).eq(k) & centers["seed"].astype(int).eq(seed)
    ].sort_values("cluster")
    if len(selected) != k:
        raise ValueError(f"Expected {k} frozen centers, found {len(selected)}")
    center_values = selected[features].to_numpy(dtype=float)
    memberships, distances = fuzzy_memberships(
        scaled[features].to_numpy(dtype=float),
        center_values,
        fuzzifier=fuzzifier,
    )

    baseline = pd.read_csv(baseline_scaled_file, low_memory=False)
    _, baseline_distances = fuzzy_memberships(
        baseline[features].to_numpy(dtype=float),
        center_values,
        fuzzifier=fuzzifier,
    )
    baseline_nearest = np.min(baseline_distances, axis=1)

    rows: list[dict[str, Any]] = []
    for index, query_run_id in enumerate(scaled["query_run_id"].astype(str)):
        membership = memberships[index]
        order = np.argsort(membership)[::-1]
        maximum = float(membership[order[0]])
        margin = float(maximum - membership[order[1]])
        entropy = float(
            -np.sum(
                np.maximum(membership, 1.0e-12)
                * np.log(np.maximum(membership, 1.0e-12))
            )
        )
        nearest = float(np.min(distances[index]))
        row: dict[str, Any] = {
            "query_run_id": query_run_id,
            "hard_cluster": int(order[0]),
            "max_membership": maximum,
            "top2_margin": margin,
            "membership_entropy": entropy,
            "nearest_center_distance": nearest,
            "nearest_center_distance_baseline_percentile": float(
                np.mean(baseline_nearest <= nearest)
            ),
            "display_state": display_state(maximum, margin, entropy),
        }
        for cluster in range(k):
            row[f"membership_c{cluster}"] = float(membership[cluster])
        rows.append(row)
    return scaled, pd.DataFrame(rows), quality
