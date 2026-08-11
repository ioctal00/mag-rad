#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def numeric_delta(left: Path, right: Path, key: str) -> tuple[float, int]:
    left_frame = pd.read_csv(left).sort_values(key).reset_index(drop=True)
    right_frame = pd.read_csv(right).sort_values(key).reset_index(drop=True)
    if list(left_frame.columns) != list(right_frame.columns):
        raise ValueError(f"Kolone se razlikuju: {left} vs {right}")
    if len(left_frame) != len(right_frame):
        raise ValueError(f"Broj redova se razlikuje: {left} vs {right}")
    numeric_columns = [
        column
        for column in left_frame.columns
        if column != key
        and pd.api.types.is_numeric_dtype(left_frame[column])
        and pd.api.types.is_numeric_dtype(right_frame[column])
    ]
    if not numeric_columns:
        return 0.0, len(left_frame)
    left_values = left_frame[numeric_columns].to_numpy(dtype=float)
    right_values = right_frame[numeric_columns].to_numpy(dtype=float)
    return float(np.nanmax(np.abs(left_values - right_values))), len(left_frame)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--tolerance", type=float, default=1.0e-10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    frozen_matrix = (
        root
        / "artifacts/results/feature-semantic-contract-v2/semantic_v2_weighted.csv"
    )
    rebuilt_matrix = root / "build/semantic-v2/semantic_v2_weighted.csv"
    frozen_model = root / "artifacts/results/semantic-v2-model-freeze"
    rebuilt_model = root / "build/semantic-v2-model"
    for path in (frozen_matrix, rebuilt_matrix, frozen_model, rebuilt_model):
        if not path.exists():
            raise SystemExit(f"Nedostaje: {path}")

    freeze_hashes = json.loads(
        (frozen_model / "freeze_sha256.json").read_text(encoding="utf-8")
    )
    matrix_hash = sha256(rebuilt_matrix)
    expected_hash = str(freeze_hashes["weighted_matrix_sha256"])
    print(f"[compare] weighted_matrix_sha256={matrix_hash}")
    if matrix_hash != expected_hash:
        delta, rows = numeric_delta(
            frozen_matrix,
            rebuilt_matrix,
            "query_run_id",
        )
        print(
            f"[compare] byte hash differs; numeric rows={rows} max_abs_delta={delta:.3e}"
        )
        if delta > args.tolerance:
            raise SystemExit("Semantic matrix differs beyond tolerance")

    for k in (3, 4):
        center_delta, _ = numeric_delta(
            frozen_model / f"cluster_centers_k{k}.csv",
            rebuilt_model / f"cluster_centers_k{k}.csv",
            "cluster",
        )
        membership_delta, rows = numeric_delta(
            frozen_model / f"baseline_memberships_k{k}.csv",
            rebuilt_model / f"baseline_memberships_k{k}.csv",
            "query_run_id",
        )
        frozen_memberships = pd.read_csv(
            frozen_model / f"baseline_memberships_k{k}.csv"
        ).sort_values("query_run_id")
        rebuilt_memberships = pd.read_csv(
            rebuilt_model / f"baseline_memberships_k{k}.csv"
        ).sort_values("query_run_id")
        hard_match = float(
            (
                frozen_memberships["dominant_cluster"].to_numpy()
                == rebuilt_memberships["dominant_cluster"].to_numpy()
            ).mean()
        )
        print(
            f"[compare] k={k} rows={rows} center_delta={center_delta:.3e} "
            f"membership_delta={membership_delta:.3e} hard_match={hard_match:.6f}"
        )
        if (
            center_delta > args.tolerance
            or membership_delta > args.tolerance
            or hard_match != 1.0
        ):
            raise SystemExit(f"Rebuilt k={k} model does not match frozen output")

    print("[compare] PASS semantic matrix and FCM outputs reproduced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
