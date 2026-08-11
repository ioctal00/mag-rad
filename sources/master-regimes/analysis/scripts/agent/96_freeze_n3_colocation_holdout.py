#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT.parent
DEFAULT_CONTRACT = ROOT / "configs/models/colocation_ranking_v1.yml"
DEFAULT_BATCH = ROOT / "configs/collection/batches/batch-300-n3-holdout.yml"
DEFAULT_CORPUS = (
    ROOT / "workloads/corpus/pressure-raw-v1/batch-300-n3-colocation-holdout.yml"
)
DEFAULT_PLAN = (
    ROOT
    / "generated/corpus/pressure-raw-v1-n3-colocation-holdout/corpus_execution_plan.yml"
)
DEFAULT_REPORT = ROOT / "analysis/reports/pressure-raw-v1-colocation-ranking-robustness"
DEFAULT_OUT = ROOT / "generated/model-freezes/colocation-ranking-before-n3-v1"
EXPECTED_REGIONS = ("eu", "us", "apac")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze and validate the no-refit N=3 colocation holdout contract."
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--ranking-report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-dirty", action="store_true")
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def workspace_path(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else WORKSPACE / path


def repository_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == ROOT.name:
        return WORKSPACE / path
    return ROOT / path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def validate_rendered_plan(plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    groups = list(plan.get("groups") or [])
    rows: list[dict[str, str]] = []
    rendered_sql_paths: set[Path] = set()
    sweep_region_sets: set[tuple[str, ...]] = set()
    fdw_region_sets: set[tuple[str, ...]] = set()
    auto_explain_sets: set[tuple[str, ...]] = set()

    for group in groups:
        manifest_path = workspace_path(str(group["instance_manifest"]))
        group_rows = read_csv(manifest_path)
        rows.extend(group_rows)
        rendered_sql_paths.update(
            workspace_path(str(row["rendered_sql_path"])) for row in group_rows
        )
        sweep = load_yaml(workspace_path(str(group["sweep_config"])))
        dataset = (sweep.get("datasets") or [{}])[0]
        sweep_region_sets.add(tuple(str(value) for value in dataset.get("regions") or []))
        bootstrap = (sweep.get("collection") or {}).get("fdw_bootstrap") or {}
        fdw_region_sets.add(tuple(str(value) for value in bootstrap.get("regions") or []))
        auto_explain_sets.add(
            tuple(
                str(value)
                for value in (sweep.get("collection") or {}).get(
                    "fdw_auto_explain_regions", []
                )
            )
        )

    condition_ids = {str(row.get("condition_id", "")) for row in rows}
    pair_ids = {str(row.get("pair_id", "")) for row in rows}
    datasets = {str(row.get("dataset_profile_id", "")) for row in rows}
    templates = {str(row.get("template_id", "")) for row in rows}
    variants = {str(row.get("variant", "")) for row in rows}
    repetition_counts: dict[str, int] = {}
    for row in rows:
        condition_id = str(row.get("condition_id", ""))
        repetition_counts[condition_id] = repetition_counts.get(condition_id, 0) + 1

    expected = {
        "group_count": 4,
        "execution_count": 96,
        "condition_count": 32,
        "pair_count": 16,
        "dataset_count": 4,
        "template_count": 8,
    }
    actual = {
        "group_count": len(groups),
        "execution_count": len(rows),
        "condition_count": len(condition_ids),
        "pair_count": len(pair_ids),
        "dataset_count": len(datasets),
        "template_count": len(templates),
    }
    for name, expected_value in expected.items():
        if actual[name] != expected_value:
            errors.append(f"{name}={actual[name]}, expected {expected_value}")
    if variants != {"mitigated", "stressed"}:
        errors.append(f"variants={sorted(variants)}")
    if set(repetition_counts.values()) != {3}:
        errors.append("every N=3 condition must have exactly three repetitions")
    expected_region_tuple = EXPECTED_REGIONS
    if sweep_region_sets != {expected_region_tuple}:
        errors.append(f"dataset region sets={sorted(sweep_region_sets)}")
    if fdw_region_sets != {expected_region_tuple}:
        errors.append(f"FDW bootstrap region sets={sorted(fdw_region_sets)}")
    if auto_explain_sets != {expected_region_tuple}:
        errors.append(f"auto_explain region sets={sorted(auto_explain_sets)}")

    missing_edges: dict[str, list[str]] = {}
    for sql_path in sorted(rendered_sql_paths):
        sql = sql_path.read_text(encoding="utf-8").lower()
        missing = [region for region in EXPECTED_REGIONS if f"fdw_{region}." not in sql]
        if missing:
            missing_edges[str(sql_path)] = missing
    if missing_edges:
        errors.append(f"rendered SQL missing N=3 edges: {missing_edges}")
    if errors:
        raise ValueError("N=3 rendered plan validation failed: " + "; ".join(errors))
    return {
        **actual,
        "regions": list(EXPECTED_REGIONS),
        "variants": sorted(variants),
        "repetitions_per_condition": 3,
        "rendered_sql_count": len(rendered_sql_paths),
    }


def frozen_execution_rows(plan: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for group in plan.get("groups") or []:
        group_rows = read_csv(workspace_path(str(group["instance_manifest"])))
        for row in group_rows:
            sql_path = workspace_path(str(row["rendered_sql_path"]))
            rows.append(
                {
                    **row,
                    "rendered_sql_sha256": sha256_file(sql_path),
                }
            )
    frame = pd.DataFrame(rows).sort_values("execution_slot_id").reset_index(drop=True)
    if len(frame) != 96 or frame["execution_slot_id"].duplicated().any():
        raise ValueError("Frozen N=3 execution table must contain 96 unique slots")
    return frame


def main() -> int:
    args = parse_args()
    contract_path = args.contract.resolve()
    batch_path = args.batch.resolve()
    corpus_path = args.corpus.resolve()
    plan_path = args.plan.resolve()
    report_dir = args.ranking_report.resolve()
    out_dir = args.out_dir.resolve()
    contract = load_yaml(contract_path)
    training_reference_path = repository_path(str(contract["source_matrix"])).resolve()
    required_paths = [
        contract_path,
        batch_path,
        corpus_path,
        plan_path,
        report_dir / "benchmark_manifest.json",
        report_dir / "colocation_ranking_model.joblib",
        training_reference_path,
    ]
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing freeze inputs: " + ", ".join(missing))
    dirty = git_output("status", "--porcelain", "--untracked-files=no")
    if dirty and not args.allow_dirty:
        raise RuntimeError("N=3 freeze requires a clean tracked worktree")

    batch = load_yaml(batch_path)
    benchmark = load_json(report_dir / "benchmark_manifest.json")
    plan = load_yaml(plan_path)
    design = validate_rendered_plan(plan)
    expected_executions = frozen_execution_rows(plan)
    frozen_inputs = batch.get("frozen_inputs") or {}
    if benchmark.get("primary_estimator") != frozen_inputs.get("primary_estimator"):
        raise ValueError("Primary estimator differs between batch and benchmark")
    if benchmark.get("selected_feature_view") != frozen_inputs.get(
        "selected_feature_view"
    ):
        raise ValueError("Selected feature view differs between batch and benchmark")
    if benchmark.get("frozen_before_n3_holdout") is not True:
        raise ValueError("Ranking benchmark is not marked frozen before N=3")
    if batch.get("design", {}).get("model_refit_allowed") is not False:
        raise ValueError("N=3 batch must explicitly forbid model refit")

    selected_names = [str(value) for value in benchmark["selected_feature_names"]]
    training_reference = pd.read_csv(training_reference_path, low_memory=False)
    missing_training_columns = sorted(
        {"pair_id", str(contract["target"]["field"]), *selected_names}
        - set(training_reference.columns)
    )
    if missing_training_columns:
        raise ValueError(
            "Training reference is missing frozen columns: "
            + ", ".join(missing_training_columns)
        )
    if len(training_reference) != int(benchmark["pair_count"]):
        raise ValueError("Training reference row count differs from benchmark")
    if training_reference["pair_id"].duplicated().any():
        raise ValueError("Training reference must contain one row per pair")
    model = joblib.load(report_dir / "colocation_ranking_model.joblib")
    model_features = [str(value) for value in model.feature_names_in_]
    if model_features != selected_names:
        raise ValueError("Serialized model feature order differs from benchmark")

    out_dir.mkdir(parents=True, exist_ok=True)
    expected_executions_path = out_dir / "expected_executions.csv"
    expected_executions.to_csv(expected_executions_path, index=False)
    copies = {
        "ranking_contract": (contract_path, out_dir / "colocation_ranking_v1.yml"),
        "batch_contract": (batch_path, out_dir / "batch-300-n3-holdout.yml"),
        "corpus_manifest": (
            corpus_path,
            out_dir / "batch-300-n3-colocation-holdout.yml",
        ),
        "rendered_execution_plan": (
            plan_path,
            out_dir / "corpus_execution_plan.yml",
        ),
        "model": (
            report_dir / "colocation_ranking_model.joblib",
            out_dir / "colocation_ranking_model.joblib",
        ),
        "benchmark_manifest": (
            report_dir / "benchmark_manifest.json",
            out_dir / "benchmark_manifest.json",
        ),
        "training_pair_reference": (
            training_reference_path,
            out_dir / "training_pair_reference.csv",
        ),
    }
    for source, destination in copies.values():
        shutil.copy2(source, destination)
    source_files = {
        **{name: destination for name, (_, destination) in copies.items()},
        "expected_executions": expected_executions_path,
    }
    manifest = {
        "freeze_contract": "colocation-ranking-before-n3-v1",
        "git_commit": git_output("rev-parse", "HEAD"),
        "git_worktree_clean": not bool(dirty),
        "no_refit": True,
        "primary_estimator": benchmark["primary_estimator"],
        "selected_feature_view": benchmark["selected_feature_view"],
        "selected_feature_names": benchmark["selected_feature_names"],
        "coverage_reference": benchmark["coverage_reference"],
        "primary_ranking_metrics": frozen_inputs["primary_ranking_metrics"],
        "ranking_support_rule": frozen_inputs["ranking_support_rule"],
        "target": contract["target"],
        "n3_design": design,
        "training_reference": {
            "row_count": len(training_reference),
            "pair_count": int(training_reference["pair_id"].nunique()),
            "selected_feature_names": selected_names,
            "target_field": str(contract["target"]["field"]),
        },
        "source_sha256": {
            name: sha256_file(path) for name, path in source_files.items()
        },
    }
    manifest_path = out_dir / "freeze_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksum_paths = [*source_files.values(), manifest_path]
    (out_dir / "checksums.sha256").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in checksum_paths),
        encoding="utf-8",
    )
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
