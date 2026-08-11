#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import re
import tarfile
from collections import Counter, defaultdict
from pathlib import Path


QUERY_FIELDS = (
    "evidence_block",
    "rendered_corpus",
    "sql_path",
    "sql_sha256",
    "condition_id",
    "execution_slot_id",
    "pair_id",
    "repeat_id",
    "logical_question_id",
    "dataset_profile_id",
    "topology_id",
    "template_id",
    "runtime_config_id",
    "intervention_role",
    "mitigation_action",
    "repetition_index",
    "run_order",
    "parameter_json",
    "expected_shape_tags",
)

DATASET_FIELDS = (
    "dataset_id",
    "profile_path",
    "profile_sha256",
    "generator",
    "seed",
    "base_time_unix",
    "lookback_days",
    "shard_count",
    "topologies_in_query_catalog",
    "query_catalog_rows",
    "regeneration_contract",
)

COVERAGE_FIELDS = (
    "rendered_corpus",
    "manifest_rows",
    "catalog_rows",
    "packaged_sql_files",
    "unresolved_manifest_rows",
    "status",
)

BLOCK_BY_CORPUS = {
    "clean-run-v1": "characterization_corpus",
    "wan-latency-companion-v1": "characterization_companion",
    "region-asymmetry-companion-v1": "characterization_companion",
    "validation-holdout-v1": "characterization_validation",
    "repeatability-v1": "measurement_repeatability",
    "confirmatory-skew-v1": "controlled_skew_validation",
    "stats-ceb-semantic-v2b-holdout": "external_schema_development",
    "stats-ceb-full-no-refit-v1": "external_schema_no_refit_audit",
    "pressure-raw-v1": "wide_intervention_corpus",
    "pressure-raw-v1-n3-colocation-holdout": "legacy_n3_colocation_audit",
    "dba-local-memory-v1": "final_dba_panel",
    "n3-topology-memory-v1": "controlled_topology_memory_panel",
    "confirmatory-action-replication-v1": "confirmatory_action_panel",
    "feedback-loop-v1": "longitudinal_feedback_loop",
}

CORE_SQL_COUNTS = {
    "pressure-raw-v1": 799,
    "dba-local-memory-v1": 60,
    "n3-topology-memory-v1": 180,
    "confirmatory-action-replication-v1": 60,
    "feedback-loop-v1": 9,
}

EXPERIMENT_DESIGNS = {
    "wide_intervention_corpus": {
        "rendered_corpus": "pressure-raw-v1",
        "unique_rendered_sql_files": 799,
        "execution_conditions": 869,
        "measured_executions": 2607,
        "controlled_pairs": 418,
        "repetition_rule": "three repetitions per condition",
        "result_release": "artifacts/results/pressure-actionability-v1",
    },
    "final_dba_panel": {
        "rendered_corpus": "dba-local-memory-v1",
        "rendered_sql_conditions": 60,
        "measured_executions": 180,
        "decision_points": 45,
        "sql_shapes": 15,
        "repetition_rule": "three temporal appearances per SQL shape",
        "result_release": "releases/consolidated-evaluation-v1",
    },
    "controlled_topology_memory_panel": {
        "rendered_corpus": "n3-topology-memory-v1",
        "rendered_sql_conditions": 180,
        "measured_executions": 180,
        "sql_shapes_per_round": 15,
        "repetition_rule": "N2 control, N3 phase A and N3 phase B",
        "result_release": "releases/consolidated-evaluation-v1",
    },
    "confirmatory_action_panel": {
        "rendered_corpus": "confirmatory-action-replication-v1",
        "rendered_sql_conditions": 60,
        "measured_executions": 300,
        "sql_shapes": 15,
        "conditions_per_shape": 4,
        "repetition_rule": "five balanced repetitions per condition",
        "result_release": "releases/confirmatory-action-replication-v1",
    },
    "longitudinal_feedback_loop": {
        "rendered_corpus": "feedback-loop-v1",
        "canonical_sql_states": 9,
        "main_execution_manifest_rows": 85,
        "aggregate_exact_replay_executions": 25,
        "repetition_rule": "adaptive states followed by frozen replay",
        "result_release": "releases/feedback-loop-execution-v1",
    },
}

SOURCE_COMMITS = {
    "master-regimes": "1892a85c0576017f898df9162c4c1b5ac21f1d03",
    "master-regimes-infra": "1138de50262b36d86af17259c9fc87fb1fe3dede",
    "citus-datagen": "cacbfdd7f7ac3f38d8e4f1e4469accae24aa6f53",
    "psql-benchmarks": "98fa47e708c13de4257e3a804c10a395f069b93a",
    "master-regimes-thesis": "6f54029edb36dc51d49f28b9dc1e7205d9804855",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def corpus_name(rendered_root: Path, manifest: Path) -> str:
    return manifest.relative_to(rendered_root).parts[0]


def resolve_sql(
    rendered_root: Path,
    manifest: Path,
    rendered_path: str,
) -> Path:
    candidate = manifest.parent / "queries" / Path(rendered_path).name
    if candidate.is_file():
        return candidate
    marker = "/generated/corpus/"
    if marker in rendered_path:
        relative = rendered_path.split(marker, maxsplit=1)[1]
        candidate = rendered_root / relative
        if candidate.is_file():
            return candidate
    raise ValueError(f"Cannot resolve rendered SQL from {manifest}: {rendered_path}")


def collect_manifest_queries(
    root: Path,
) -> tuple[list[dict[str, str]], Counter[str], Counter[str]]:
    rendered_root = root / "artifacts/rendered-corpora"
    rows_by_path: dict[str, dict[str, str]] = {}
    manifest_counts: Counter[str] = Counter()
    unresolved: Counter[str] = Counter()
    for manifest in sorted(rendered_root.rglob("instance_manifest.csv")):
        corpus = corpus_name(rendered_root, manifest)
        with manifest.open(newline="", encoding="utf-8") as handle:
            for source in csv.DictReader(handle):
                manifest_counts[corpus] += 1
                try:
                    sql = resolve_sql(rendered_root, manifest, source["rendered_sql_path"])
                except ValueError:
                    unresolved[corpus] += 1
                    continue
                relative_sql = sql.relative_to(root).as_posix()
                rows_by_path.setdefault(
                    relative_sql,
                    {
                        "evidence_block": BLOCK_BY_CORPUS.get(corpus, "supporting_corpus"),
                        "rendered_corpus": corpus,
                        "sql_path": relative_sql,
                        "sql_sha256": digest(sql),
                        "condition_id": source.get("condition_id", ""),
                        "execution_slot_id": source.get("execution_slot_id", ""),
                        "pair_id": source.get("pair_id", ""),
                        "repeat_id": source.get("repeat_id", ""),
                        "logical_question_id": source.get("logical_question_id", ""),
                        "dataset_profile_id": source.get("dataset_profile_id", ""),
                        "topology_id": source.get("topology_id", ""),
                        "template_id": source.get("template_id", ""),
                        "runtime_config_id": source.get("runtime_config_id", ""),
                        "intervention_role": source.get("intervention_role", ""),
                        "mitigation_action": source.get("mitigation_action", ""),
                        "repetition_index": source.get("repetition_index", ""),
                        "run_order": source.get("run_order", ""),
                        "parameter_json": source.get("param_json", ""),
                        "expected_shape_tags": source.get("expected_shape_tags", ""),
                    },
                )
    return list(rows_by_path.values()), manifest_counts, unresolved


def feedback_metadata(stem: str) -> tuple[str, str, str]:
    if stem == "smoke_select_one":
        return "collector_smoke", "smoke_select_one", "smoke"
    if "event_exact" in stem:
        action = "regional_pushdown_rewrite" if "regional" in stem else "baseline"
        return "event_exact_full_flow_summary", stem, action
    if "event_full_scan" in stem:
        return "event_full_scan_summary", stem, "baseline"
    if "user_join" in stem:
        action = "regional_pushdown_rewrite" if "regional" in stem else "baseline"
        return "user_segment_topk", stem, action
    if "user_topk" in stem:
        action = "regional_pushdown_rewrite" if "partial" in stem else "baseline"
        return "user_value_topk", stem, action
    raise ValueError(f"Unknown feedback-loop SQL: {stem}")


def collect_feedback_queries(root: Path) -> list[dict[str, str]]:
    base = root / "artifacts/rendered-corpora/feedback-loop-v1"
    rows = []
    for sql in sorted(base.rglob("*.sql")):
        logical_question_id, template_id, action = feedback_metadata(sql.stem)
        rows.append(
            {
                "evidence_block": "longitudinal_feedback_loop",
                "rendered_corpus": "feedback-loop-v1",
                "sql_path": sql.relative_to(root).as_posix(),
                "sql_sha256": digest(sql),
                "condition_id": sql.parent.name,
                "execution_slot_id": "",
                "pair_id": "",
                "repeat_id": "",
                "logical_question_id": logical_question_id,
                "dataset_profile_id": "locked_current_dataset_snapshot",
                "topology_id": "eu_us_gac",
                "template_id": template_id,
                "runtime_config_id": "feedback_loop_frozen_contract",
                "intervention_role": "longitudinal_state",
                "mitigation_action": action,
                "repetition_index": "",
                "run_order": "frozen_manifest",
                "parameter_json": "{}",
                "expected_shape_tags": "see experiments/feedback-loop-v1",
            }
        )
    return rows


def collect_archived_confirmatory_skew(root: Path) -> list[dict[str, str]]:
    archive_path = root / "artifacts/raw-attempts/confirmatory-skew-v1.tar.gz"
    output = root / "artifacts/rendered-corpora/confirmatory-skew-v1/queries"
    output.mkdir(parents=True, exist_ok=True)
    dataset_by_state = {
        "a": "pilot-balanced-v1",
        "b": "pilot-skew-heavy-v1",
        "c": "pilot-skew-heavy-v1",
        "d": "pilot-region-imbalanced-v1",
    }
    rows = []
    with tarfile.open(archive_path, "r:gz") as archive:
        members = sorted(
            [
                member
                for member in archive.getmembers()
                if member.isfile() and member.name.endswith("/input/query.sql")
            ],
            key=lambda member: member.name,
        )
        if len(members) != 48:
            raise ValueError(f"confirmatory-skew archive: expected 48 SQL files, got {len(members)}")
        for index, member in enumerate(members, start=1):
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError(f"Cannot read {member.name}")
            payload = handle.read()
            state_match = re.search(r"confirmatory-skew-v1-state-([a-d])", member.name)
            if state_match is None:
                raise ValueError(f"Cannot infer confirmatory state from {member.name}")
            state = state_match.group(1)
            path = output / f"state-{state}-execution-{index:02d}.sql"
            path.write_bytes(payload)
            rows.append(
                {
                    "evidence_block": "controlled_skew_validation",
                    "rendered_corpus": "confirmatory-skew-v1",
                    "sql_path": path.relative_to(root).as_posix(),
                    "sql_sha256": digest(path),
                    "condition_id": member.name,
                    "execution_slot_id": f"confirmatory-skew-state-{state}-{index:02d}",
                    "pair_id": "",
                    "repeat_id": "",
                    "logical_question_id": "confirmatory_skew",
                    "dataset_profile_id": dataset_by_state[state],
                    "topology_id": "eu_us_gac",
                    "template_id": "archived_rendered_sql",
                    "runtime_config_id": "default",
                    "intervention_role": f"state_{state}",
                    "mitigation_action": "",
                    "repetition_index": "",
                    "run_order": str(index),
                    "parameter_json": "{}",
                    "expected_shape_tags": "see frozen confirmatory-skew design matrix",
                }
            )
    return rows


def scalar(text: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(key)}:\s*([^#\n]+)", text)
    if match:
        return match.group(1).strip().strip("'\"")
    inline = re.search(rf"\b{re.escape(key)}:\s*([^,}}\n]+)", text)
    return inline.group(1).strip().strip("'\"") if inline else ""


def profile_index(root: Path) -> dict[str, Path]:
    profiles = {}
    for path in sorted((root / "sources/master-regimes/datasets/profiles").glob("*.yml")):
        dataset_id = scalar(path.read_text(encoding="utf-8"), "dataset_id")
        if dataset_id:
            profiles[dataset_id] = path
    return profiles


def collect_datasets(root: Path, query_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    usage: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in query_rows:
        if row["dataset_profile_id"]:
            usage[row["dataset_profile_id"]].append(row)
    profiles = profile_index(root)
    datasets = []
    for dataset_id, rows in sorted(usage.items()):
        path = profiles.get(dataset_id)
        if path is None:
            if dataset_id != "locked_current_dataset_snapshot":
                raise ValueError(f"No packaged dataset profile for {dataset_id}")
            datasets.append(
                {
                    "dataset_id": dataset_id,
                    "profile_path": "experiments/feedback-loop-v1/query_trajectory_manifest.yaml",
                    "profile_sha256": digest(root / "experiments/feedback-loop-v1/query_trajectory_manifest.yaml"),
                    "generator": "citus-datagen; exact original profile name not recorded",
                    "seed": "not_recorded",
                    "base_time_unix": "1782864000",
                    "lookback_days": "30",
                    "shard_count": "not_recorded_in_feedback_contract",
                    "topologies_in_query_catalog": ";".join(sorted({row["topology_id"] for row in rows})),
                    "query_catalog_rows": str(len(rows)),
                    "regeneration_contract": "recorded snapshot; exact regeneration is not guaranteed",
                }
            )
            continue
        text = path.read_text(encoding="utf-8")
        datasets.append(
            {
                "dataset_id": dataset_id,
                "profile_path": path.relative_to(root).as_posix(),
                "profile_sha256": digest(path),
                "generator": scalar(text, "generator"),
                "seed": scalar(text, "seed"),
                "base_time_unix": scalar(text, "base_time_unix"),
                "lookback_days": scalar(text, "lookback_days"),
                "shard_count": scalar(text, "shard_count"),
                "topologies_in_query_catalog": ";".join(sorted({row["topology_id"] for row in rows})),
                "query_catalog_rows": str(len(rows)),
                "regeneration_contract": "profile + generator commit + seed + base_time_unix",
            }
        )
    return datasets


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    query_rows, manifest_counts, unresolved = collect_manifest_queries(root)
    query_rows += collect_archived_confirmatory_skew(root)
    query_rows += collect_feedback_queries(root)
    query_rows.sort(key=lambda row: (row["rendered_corpus"], row["sql_path"]))
    counts = Counter(row["rendered_corpus"] for row in query_rows)
    for corpus, expected in CORE_SQL_COUNTS.items():
        if counts[corpus] != expected:
            raise ValueError(f"{corpus}: expected {expected} SQL rows, got {counts[corpus]}")

    output = root / "reproducibility"
    write_csv(output / "query-catalog.csv", QUERY_FIELDS, query_rows)
    rendered_root = root / "artifacts/rendered-corpora"
    coverage_rows = []
    for corpus_dir in sorted(path for path in rendered_root.iterdir() if path.is_dir()):
        corpus = corpus_dir.name
        catalog_count = counts[corpus]
        sql_count = sum(1 for _ in corpus_dir.rglob("*.sql"))
        unresolved_count = unresolved[corpus]
        coverage_rows.append(
            {
                "rendered_corpus": corpus,
                "manifest_rows": str(manifest_counts[corpus]),
                "catalog_rows": str(catalog_count),
                "packaged_sql_files": str(sql_count),
                "unresolved_manifest_rows": str(unresolved_count),
                "status": (
                    "complete_from_raw_archive"
                    if unresolved_count and sql_count == catalog_count == unresolved_count
                    else
                    "template_and_manifest_only"
                    if unresolved_count
                    else "complete_reusing_packaged_sql"
                    if sql_count == 0 and catalog_count > 0
                    else "complete"
                    if sql_count == catalog_count
                    else "complete_with_uncatalogued_legacy_files"
                ),
            }
        )
    write_csv(output / "query-coverage.csv", COVERAGE_FIELDS, coverage_rows)
    datasets = collect_datasets(root, query_rows)
    write_csv(output / "dataset-catalog.csv", DATASET_FIELDS, datasets)

    source_rows = [
        {
            "repository": name,
            "commit": commit,
            "snapshot_path": f"sources/{name}" if name != "master-regimes-thesis" else "not_packaged",
        }
        for name, commit in SOURCE_COMMITS.items()
    ]
    write_csv(
        output / "source-provenance.csv",
        ("repository", "commit", "snapshot_path"),
        source_rows,
    )

    inventory = {
        "schema_version": 1,
        "query_catalog_rows": len(query_rows),
        "dataset_catalog_rows": len(datasets),
        "rendered_sql_rows_by_corpus": dict(sorted(counts.items())),
        "unresolved_manifest_rows_by_corpus": {
            key: value for key, value in sorted(unresolved.items()) if value
        },
        "core_experiment_designs": EXPERIMENT_DESIGNS,
        "dataset_materialization": {
            "materialized_database_dump_included": False,
            "deterministic_generator_included": True,
            "dataset_profiles_included": True,
            "row_level_snapshot_checksum_available": False,
            "reason": "Synthetic datasets are regenerated from frozen profiles; database dumps and query result rows are not distributed.",
        },
        "schema_and_loader_paths": [
            "sources/citus-datagen/sql",
            "sources/citus-datagen/src",
            "sources/citus-datagen/tools/cpp",
            "sources/master-regimes/datasets/profiles",
            "sources/master-regimes-infra/common-scripts/apply_dataset_profile.py",
        ],
        "source_commits": SOURCE_COMMITS,
    }
    (output / "evidence-blocks.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"catalog PASS: queries={len(query_rows)} datasets={len(datasets)} "
        f"corpora={len(counts)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
