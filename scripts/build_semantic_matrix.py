#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from master_regimes.config import load_yaml
from master_regimes.representation_audit import semantic_transform

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild the 19-feature semantic matrix without prose reports."
    )
    parser.add_argument(
        "--feature-file",
        type=Path,
        default=ROOT
        / "artifacts/features/clean-run-v1-semantic-v2/execution_features_all.csv",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT
        / "sources/master-regimes/configs/features/"
        "feature_semantic_contract_v2.yml",
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "build/semantic-v2")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = load_yaml(args.contract.resolve())
    all_features = pd.read_csv(args.feature_file.resolve(), low_memory=False)
    features = [
        feature
        for feature, specification in contract["features"].items()
        if not specification.get("drop_as_redundant", False)
    ]
    required = {"query_run_id", *features}
    missing = sorted(required.difference(all_features.columns))
    if missing:
        raise ValueError(f"Nedostaju feature kolone: {missing}")

    raw = all_features[["query_run_id", *features]].copy()
    transformed, weighted, audit = semantic_transform(raw, all_features, contract)
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw.to_csv(out_dir / "semantic_v2_raw.csv", index=False)
    transformed.to_csv(out_dir / "semantic_v2_transformed.csv", index=False)
    weighted.to_csv(out_dir / "semantic_v2_weighted.csv", index=False)
    audit.to_csv(out_dir / "semantic_transform_audit.csv", index=False)
    print(
        f"[semantic-matrix] rows={len(raw)} features={len(features)} out={out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
