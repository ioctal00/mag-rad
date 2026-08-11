#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


CORE_COUNTS = {
    "pressure-raw-v1": 799,
    "dba-local-memory-v1": 60,
    "n3-topology-memory-v1": 180,
    "confirmatory-action-replication-v1": 60,
    "feedback-loop-v1": 9,
}

REQUIRED_RELEASES = (
    "representation-ablation-e1-e4-v1",
    "representation-value-ablation-v1",
    "confirmatory-action-replication-v1",
    "consolidated-evaluation-v1",
    "feedback-loop-execution-v1",
    "feedback-loop-analysis-v1",
    "rq-alignment-v1",
    "rq-alignment-v2",
    "fcm-f21-development-v1",
    "model-lineage-audit-v1",
    "temporal-validity-audit-v1",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verify_queries(root: Path) -> None:
    rows = read_rows(root / "reproducibility/query-catalog.csv")
    if not rows:
        raise ValueError("Query catalog is empty")
    counts = Counter(row["rendered_corpus"] for row in rows)
    for corpus, expected in CORE_COUNTS.items():
        if counts[corpus] != expected:
            raise ValueError(f"{corpus}: expected={expected} observed={counts[corpus]}")
    for row in rows:
        path = root / row["sql_path"]
        if not path.is_file() or digest(path) != row["sql_sha256"]:
            raise ValueError(f"Invalid SQL catalog entry: {row['sql_path']}")
        if row["rendered_corpus"] in CORE_COUNTS:
            text = path.read_text(encoding="utf-8")
            wall_clock = re.search(
                r"\b(?:now\s*\(|current_timestamp\b|clock_timestamp\s*\()",
                text,
                re.IGNORECASE,
            )
            if wall_clock and "1782864000" not in text:
                raise ValueError(f"Unanchored wall-clock SQL in core corpus: {path}")
    print(f"[reproducibility] query catalog PASS ({len(rows)} rows)")


def verify_datasets(root: Path) -> None:
    rows = read_rows(root / "reproducibility/dataset-catalog.csv")
    if not rows:
        raise ValueError("Dataset catalog is empty")
    for row in rows:
        path = root / row["profile_path"]
        if not path.is_file() or digest(path) != row["profile_sha256"]:
            raise ValueError(f"Invalid dataset profile: {row['dataset_id']}")
        if row["dataset_id"] == "locked_current_dataset_snapshot":
            if row["regeneration_contract"] != "recorded snapshot; exact regeneration is not guaranteed":
                raise ValueError("Feedback-loop dataset limitation is missing")
            continue
        if not row["generator"] or not row["seed"]:
            raise ValueError(f"Incomplete generator contract: {row['dataset_id']}")
    print(f"[reproducibility] dataset catalog PASS ({len(rows)} rows)")


def verify_sources(root: Path) -> None:
    rows = read_rows(root / "reproducibility/source-provenance.csv")
    spec = json.loads((root / "config/release-spec.json").read_text(encoding="utf-8"))
    expected = spec["source_snapshots"]
    for row in rows:
        if not re.fullmatch(r"[0-9a-f]{40}", row["commit"]):
            raise ValueError(f"Invalid source commit: {row['repository']}")
        if row["repository"] == "master-regimes-thesis":
            continue
        if expected.get(row["repository"]) != row["commit"]:
            raise ValueError(f"Release spec source mismatch: {row['repository']}")
        if not (root / row["snapshot_path"]).is_dir():
            raise ValueError(f"Missing source snapshot: {row['snapshot_path']}")
    print("[reproducibility] source provenance PASS")


def verify_releases(root: Path) -> None:
    actionability = root / "artifacts/results/pressure-actionability-v1"
    if not actionability.is_dir():
        raise ValueError("Missing wide intervention actionability result package")
    for name in REQUIRED_RELEASES:
        path = root / "releases" / name
        if not path.is_dir() or not any(candidate.is_file() for candidate in path.rglob("*")):
            raise ValueError(f"Missing required result release: {name}")
    main_rows = read_rows(root / "releases/feedback-loop-execution-v1/main/execution_manifest.csv")
    aggregate_rows = read_rows(
        root
        / "releases/feedback-loop-execution-v1/aggregate-exact/frozen_execution_plan.csv"
    )
    if len(main_rows) != 85 or len(aggregate_rows) != 25:
        raise ValueError("Unexpected feedback-loop execution counts")
    feedback_release = root / "releases/feedback-loop-execution-v1"
    for path in feedback_release.rglob("*"):
        if path.is_file() and path.suffix.lower() in {
            ".csv",
            ".json",
            ".jsonl",
            ".md",
            ".txt",
            ".yaml",
            ".yml",
        }:
            if "/home/" in path.read_text(encoding="utf-8"):
                raise ValueError(f"Local absolute path in feedback-loop release: {path}")
    print("[reproducibility] result releases PASS")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads(
        (root / "reproducibility/evidence-blocks.json").read_text(encoding="utf-8")
    )
    if inventory.get("dataset_materialization", {}).get("materialized_database_dump_included") is not False:
        raise ValueError("Dataset materialization limitation is missing")
    verify_queries(root)
    verify_datasets(root)
    verify_sources(root)
    verify_releases(root)
    print("[reproducibility] PACKAGE CONTRACT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
