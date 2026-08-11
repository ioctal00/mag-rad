from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

CORE_LOGICAL_RUN_IDS = (
    "clean-run-v1",
    "clean-run-v1-validation-holdout",
    "clean-run-v1-region-asymmetry",
    "clean-run-v1-region-asymmetry-skew-rerun",
)
MAIN_LOGICAL_RUN_ID = "clean-run-v1"


@dataclass(frozen=True)
class EvidenceContract:
    contract_id: str
    strategies: dict[str, dict[str, Any]]
    unknown_strategy_policy: str
    identity: dict[str, list[str]]
    consistency_fields: tuple[str, ...]
    feature_consistency_fields: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> EvidenceContract:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            contract_id=str(payload.get("contract_id") or ""),
            strategies=dict(payload.get("strategies") or {}),
            unknown_strategy_policy=str(
                payload.get("unknown_strategy_policy") or "fail"
            ),
            identity={
                str(key): [str(value) for value in values]
                for key, values in dict(payload.get("identity") or {}).items()
            },
            consistency_fields=tuple(
                str(value) for value in payload.get("consistency_fields") or []
            ),
            feature_consistency_fields=tuple(
                str(value)
                for value in payload.get("feature_consistency_fields") or []
            ),
        )

    def strategy(self, name: str) -> dict[str, Any]:
        if name not in self.strategies:
            if self.unknown_strategy_policy == "fail":
                raise ValueError(f"Uncovered execution strategy: {name}")
            return {}
        return self.strategies[name]


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value)


def truthy(value: Any) -> bool:
    return text(value).strip().lower() in {"1", "true", "yes", "y"}


def integer(value: Any) -> int | None:
    if value is None or text(value).strip() == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def stable_score(seed: str, *parts: Any) -> str:
    source = "\x1f".join([seed, *(text(part) for part in parts)])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _same(left: Any, right: Any) -> bool:
    left_text = text(left)
    right_text = text(right)
    if not left_text and not right_text:
        return True
    return left_text == right_text


def _duplicates(frame: pd.DataFrame, columns: list[str]) -> int:
    if frame.empty or any(column not in frame.columns for column in columns):
        return 0
    return int(frame.duplicated(columns, keep=False).sum())


def _attempt_lookup(run_root: Path) -> dict[str, dict[str, Any]]:
    attempts = read_csv(run_root / "query_attempts.csv")
    if attempts.empty:
        return {}
    attempts = attempts.sort_values(
        ["query_run_id", "attempt_number"], kind="stable"
    ).drop_duplicates("query_run_id", keep="last")
    return {
        text(row["query_run_id"]): row.to_dict()
        for _, row in attempts.iterrows()
    }


def resolve_artifact_path(
    value: Any,
    *,
    attempt: dict[str, Any],
    query_sweep_dir: Any = "",
) -> Path | None:
    raw = text(value).strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    index_dir = Path(text(attempt.get("database_sweep_index_dir")))
    database_sweep_dir = index_dir.parent
    if raw.startswith("_index/") and text(query_sweep_dir):
        return database_sweep_dir / text(query_sweep_dir) / candidate
    return database_sweep_dir / candidate


def _context_mismatch_count(
    parent: pd.Series,
    children: pd.DataFrame,
    fields: Iterable[str],
) -> tuple[int, str]:
    mismatches: list[str] = []
    if children.empty:
        return 0, ""
    for field in fields:
        if field not in parent.index or field not in children.columns:
            continue
        for child_value in children[field]:
            if not _same(parent[field], child_value):
                mismatches.append(field)
                break
    unique = sorted(set(mismatches))
    return len(unique), ",".join(unique)


def _applicable_regions(rule: dict[str, Any]) -> list[str]:
    if rule.get("remote_region_evidence") == "not_applicable":
        return []
    return [str(value) for value in rule.get("expected_regions") or []]


def _group_by_query_run_id(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if frame.empty or "query_run_id" not in frame.columns:
        return {}
    return {
        text(query_run_id): group.copy()
        for query_run_id, group in frame.groupby("query_run_id", sort=False)
    }


def correlation_key_dictionary(contract: EvidenceContract) -> pd.DataFrame:
    """Return the implemented parent-child identity contract as tabular data."""

    identities = contract.identity

    def key(name: str) -> str:
        return ", ".join(identities.get(name, []))

    return pd.DataFrame(
        [
            {
                "layer": "global_execution",
                "child_record": "query_runs",
                "primary_identity": key("query_observation_key"),
                "parent_identity": "logical_run_id",
                "auxiliary_scope": (
                    "bounded execution_id; SHA-256-derived remote marker; "
                    "single-query collection window"
                ),
                "content_check": "rendered SQL hash and main plan fingerprint",
                "validation_rule": "one unique query_run_id per selected execution",
            },
            {
                "layer": "gac_main_plan",
                "child_record": "plan_files(plan_scope=main)",
                "primary_identity": key("main_plan_key"),
                "parent_identity": key("query_observation_key"),
                "auxiliary_scope": "plan_scope=main inside the query collection",
                "content_check": "parseable JSON plan and plan fingerprint",
                "validation_rule": "exactly one parseable main plan",
            },
            {
                "layer": "regional_auto_explain",
                "child_record": "region_fragments",
                "primary_identity": key("remote_fragment_key"),
                "parent_identity": key("query_observation_key"),
                "auxiliary_scope": (
                    "region host; log lines after captured start_line; "
                    "SHA-256-derived postgres_fdw application_name; "
                    "serial query execution; remote_sql_id within scoped log"
                ),
                "content_check": "remote SQL hash and remote plan fingerprint",
                "validation_rule": (
                    "all and only strategy-applicable regions; unique remote "
                    "plan and remote SQL slot"
                ),
            },
            {
                "layer": "citus_worker_task",
                "child_record": "worker_task_fragments",
                "primary_identity": key("worker_task_key"),
                "parent_identity": key("remote_fragment_key"),
                "auxiliary_scope": "fdw_region, remote plan_id and task_index",
                "content_check": "worker plan parse status and task metadata",
                "validation_rule": (
                    "no orphan task; region agrees; task count agrees when "
                    "Citus exposes the task list"
                ),
            },
            {
                "layer": "execution_feature_row",
                "child_record": "execution_features",
                "primary_identity": key("feature_row_key"),
                "parent_identity": key("query_observation_key"),
                "auxiliary_scope": "feature schema copied into logical index",
                "content_check": "context fields agree with parent query",
                "validation_rule": "exactly one feature row per query_run_id",
            },
            {
                "layer": "retry_resolution",
                "child_record": "resolved_query_status",
                "primary_identity": key("logical_instance_key"),
                "parent_identity": "logical_run_id",
                "auxiliary_scope": (
                    "attempt_number, execution_status and resolved_query_run_id"
                ),
                "content_check": "all attempt metadata remains in query_attempts",
                "validation_rule": (
                    "select highest-ranked completed attempt; emit one query "
                    "observation or leave the logical instance unresolved"
                ),
            },
        ]
    )


def audit_logical_run(
    logical_root: Path,
    logical_run_id: str,
    contract: EvidenceContract,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    run_root = logical_root / logical_run_id
    index_dir = run_root / "_index"
    query_runs = read_csv(index_dir / "query_runs.csv")
    features = read_csv(index_dir / "execution_features.csv")
    regions = read_csv(index_dir / "region_fragments.csv")
    workers = read_csv(index_dir / "worker_task_fragments.csv")
    plan_files = read_csv(index_dir / "plan_files.csv")
    attempts = _attempt_lookup(run_root)

    if query_runs.empty:
        raise FileNotFoundError(f"No query_runs.csv for {logical_run_id}")
    if features.empty:
        raise FileNotFoundError(f"No execution_features.csv for {logical_run_id}")

    query_identity_counts = query_runs["query_run_id"].astype(str).value_counts()
    feature_identity_counts = features["query_run_id"].astype(str).value_counts()
    feature_by_query = features.set_index("query_run_id", drop=False)
    regions_by_query = _group_by_query_run_id(regions)
    workers_by_query = _group_by_query_run_id(workers)
    plans_by_query = _group_by_query_run_id(plan_files)
    rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for _, query in query_runs.iterrows():
        query_run_id = text(query["query_run_id"])
        strategy_name = text(query.get("execution_strategy"))
        rule = contract.strategy(strategy_name)
        expected_regions = _applicable_regions(rule)
        remote_applicable = bool(expected_regions)

        query_regions = regions_by_query.get(query_run_id, pd.DataFrame())
        query_workers = workers_by_query.get(query_run_id, pd.DataFrame())
        query_plans = plans_by_query.get(query_run_id, pd.DataFrame())
        feature = (
            feature_by_query.loc[query_run_id]
            if query_run_id in feature_by_query.index
            else pd.Series(dtype=object)
        )
        query_row_count = int(query_identity_counts.get(query_run_id, 0))
        feature_row_count = int(feature_identity_counts.get(query_run_id, 0))
        if isinstance(feature, pd.DataFrame):
            feature = feature.iloc[0]

        observed_regions = sorted(
            {
                text(value)
                for value in query_regions.get("region_id", pd.Series(dtype=str))
                if text(value)
            }
        )
        missing_regions = sorted(set(expected_regions) - set(observed_regions))
        unexpected_regions = sorted(set(observed_regions) - set(expected_regions))

        expected_fragment_count: int | None = None
        source = rule.get("expected_remote_fragment_count_source")
        if remote_applicable and source == "fdw_remote_sql_count":
            expected_fragment_count = integer(feature.get("fdw_remote_sql_count"))

        region_identity_duplicates = _duplicates(
            query_regions, ["query_run_id", "region_id", "remote_plan_id"]
        )
        remote_sql_slot_duplicates = _duplicates(
            query_regions, ["query_run_id", "region_id", "remote_sql_id"]
        )
        worker_identity_duplicates = _duplicates(
            query_workers,
            ["query_run_id", "fdw_region", "plan_id", "task_index"],
        )
        plan_identity_duplicates = _duplicates(query_plans, ["plan_id"])

        region_context_count, region_context_fields = _context_mismatch_count(
            query, query_regions, contract.consistency_fields
        )
        worker_context_count, worker_context_fields = _context_mismatch_count(
            query, query_workers, contract.consistency_fields
        )
        feature_context_count, feature_context_fields = _context_mismatch_count(
            query,
            feature.to_frame().T if not feature.empty else pd.DataFrame(),
            contract.feature_consistency_fields,
        )

        remote_plan_ids = set(
            query_regions.get("remote_plan_id", pd.Series(dtype=str))
            .dropna()
            .astype(str)
        )
        worker_plan_ids = set(
            query_workers.get("plan_id", pd.Series(dtype=str)).dropna().astype(str)
        )
        orphan_worker_plan_ids = sorted(worker_plan_ids - remote_plan_ids)

        worker_region_mismatch_count = 0
        worker_count_mismatch_count = 0
        worker_expected_plan_count = 0
        expected_worker_fragment_count = 0
        worker_unavailable_plan_count = 0
        if not query_regions.empty:
            for _, region in query_regions.iterrows():
                plan_id = text(region.get("remote_plan_id"))
                region_id = text(region.get("region_id"))
                plan_workers = (
                    query_workers[
                        query_workers["plan_id"].astype(str).eq(plan_id)
                    ]
                    if not query_workers.empty
                    else pd.DataFrame()
                )
                if not plan_workers.empty:
                    worker_region_mismatch_count += int(
                        (~plan_workers["fdw_region"].astype(str).eq(region_id)).sum()
                    )
                list_available = truthy(
                    region.get("remote_citus_task_list_available")
                )
                expected_tasks = integer(region.get("remote_citus_task_count"))
                if list_available and expected_tasks is not None:
                    worker_expected_plan_count += 1
                    expected_worker_fragment_count += expected_tasks
                    if len(plan_workers) != expected_tasks:
                        worker_count_mismatch_count += 1
                else:
                    worker_unavailable_plan_count += 1

        main_plan_count = 0
        if not query_plans.empty and "plan_scope" in query_plans.columns:
            main_plan_count = int(
                query_plans["plan_scope"].astype(str).eq("main").sum()
            )
        main_plan_parse_error = text(query.get("plan_parse_error")).strip()
        region_parse_failure_count = 0
        if not query_regions.empty and "parse_status" in query_regions.columns:
            region_parse_failure_count = int(
                (~query_regions["parse_status"].astype(str).eq("ok")).sum()
            )
        worker_parse_failure_count = 0
        if not query_workers.empty and "parse_status" in query_workers.columns:
            worker_parse_failure_count = int(
                query_workers["parse_status"].astype(str).eq("failed").sum()
            )

        attempt = attempts.get(query_run_id, {})
        main_path = resolve_artifact_path(
            query.get("plan_json_file"), attempt=attempt
        )
        main_plan_exists = bool(main_path and main_path.exists())
        main_plan_parse_ok = (
            main_plan_count == 1
            and main_plan_exists
            and not main_plan_parse_error
        )
        remote_path_missing_count = 0
        for _, region in query_regions.iterrows():
            path = resolve_artifact_path(
                region.get("remote_plan_json_file"),
                attempt=attempt,
                query_sweep_dir=region.get("query_sweep_dir"),
            )
            if not path or not path.exists():
                remote_path_missing_count += 1
        worker_path_missing_count = 0
        for _, worker in query_workers.iterrows():
            path = resolve_artifact_path(
                worker.get("plan_json_file"),
                attempt=attempt,
                query_sweep_dir=worker.get("query_sweep_dir"),
            )
            if not path or not path.exists():
                worker_path_missing_count += 1

        applicable_slots = 1 + len(expected_regions)
        found_slots = int(main_plan_exists) + sum(
            1 for region in expected_regions if region in observed_regions
        )
        completeness = found_slots / applicable_slots if applicable_slots else 1.0

        fragment_count_matches = (
            True
            if expected_fragment_count is None
            else len(query_regions) == expected_fragment_count
        )
        applicable_ok = (
            not missing_regions
            and not unexpected_regions
            and (
                remote_applicable
                or (query_regions.empty and query_workers.empty)
            )
        )
        uniqueness_ok = not any(
            [
                query_row_count != 1,
                feature_row_count != 1,
                region_identity_duplicates,
                remote_sql_slot_duplicates,
                worker_identity_duplicates,
                plan_identity_duplicates,
            ]
        )
        consistency_ok = not any(
            [
                region_context_count,
                worker_context_count,
                feature_context_count,
                len(orphan_worker_plan_ids),
                worker_region_mismatch_count,
                worker_count_mismatch_count,
            ]
        )
        artifact_paths_ok = (
            main_plan_exists
            and remote_path_missing_count == 0
            and worker_path_missing_count == 0
        )
        resolution_status = "resolved"
        issue_codes: list[str] = []
        if query_row_count != 1:
            issue_codes.append("query_row_cardinality")
        if feature_row_count != 1:
            issue_codes.append("feature_row_cardinality")
        if main_plan_count != 1:
            issue_codes.append("main_plan_count")
        if main_plan_parse_error:
            issue_codes.append("main_plan_parse_failed")
        if not main_plan_exists:
            issue_codes.append("main_plan_file_missing")
        if missing_regions:
            issue_codes.append("missing_region")
        if unexpected_regions:
            issue_codes.append("unexpected_region")
        if not fragment_count_matches:
            issue_codes.append("remote_fragment_count")
        if not uniqueness_ok:
            issue_codes.append("duplicate_candidate")
            resolution_status = "ambiguous"
        if region_context_count or worker_context_count or feature_context_count:
            issue_codes.append("context_mismatch")
        if orphan_worker_plan_ids:
            issue_codes.append("orphan_worker_plan")
        if worker_region_mismatch_count:
            issue_codes.append("worker_region_mismatch")
        if worker_count_mismatch_count:
            issue_codes.append("worker_count_mismatch")
        if remote_path_missing_count or worker_path_missing_count:
            issue_codes.append("child_plan_file_missing")
        if region_parse_failure_count:
            issue_codes.append("regional_plan_parse_failed")
        if worker_parse_failure_count:
            issue_codes.append("worker_plan_parse_failed")

        for code in issue_codes:
            unresolved.append(
                {
                    "logical_run_id": logical_run_id,
                    "query_run_id": query_run_id,
                    "execution_strategy": strategy_name,
                    "template_id": text(query.get("template_id")),
                    "issue_code": code,
                    "resolution_status": resolution_status,
                }
            )

        rows.append(
            {
                "logical_run_id": logical_run_id,
                "query_run_id": query_run_id,
                "instance_id": text(query.get("instance_id")),
                "template_id": text(query.get("template_id")),
                "logical_question_id": text(query.get("logical_question_id")),
                "execution_strategy": strategy_name,
                "expected_shape_tags": text(query.get("expected_shape_tags")),
                "intervention_axis": text(query.get("intervention_axis")),
                "dataset_id": text(query.get("dataset_id")),
                "runtime_config_id": text(query.get("runtime_config_id")),
                "attempt_number": integer(attempt.get("attempt_number")),
                "query_row_count": query_row_count,
                "feature_row_count": feature_row_count,
                "query_feature_one_to_one": (
                    query_row_count == 1 and feature_row_count == 1
                ),
                "remote_evidence_applicable": remote_applicable,
                "expected_regions": ",".join(expected_regions),
                "observed_regions": ",".join(observed_regions),
                "missing_region_count": len(missing_regions),
                "unexpected_region_count": len(unexpected_regions),
                "expected_remote_fragment_count": expected_fragment_count,
                "observed_remote_fragment_count": len(query_regions),
                "remote_fragment_count_matches": fragment_count_matches,
                "observed_worker_fragment_count": len(query_workers),
                "worker_expected_plan_count": worker_expected_plan_count,
                "expected_worker_fragment_count": expected_worker_fragment_count,
                "worker_unavailable_plan_count": worker_unavailable_plan_count,
                "worker_count_mismatch_count": worker_count_mismatch_count,
                "main_plan_count": main_plan_count,
                "main_plan_exists": main_plan_exists,
                "main_plan_parse_ok": main_plan_parse_ok,
                "main_plan_parse_error": main_plan_parse_error,
                "region_parse_failure_count": region_parse_failure_count,
                "worker_parse_failure_count": worker_parse_failure_count,
                "applicable_slot_count": applicable_slots,
                "found_slot_count": found_slots,
                "evidence_completeness": completeness,
                "region_identity_duplicate_rows": region_identity_duplicates,
                "remote_sql_slot_duplicate_rows": remote_sql_slot_duplicates,
                "worker_identity_duplicate_rows": worker_identity_duplicates,
                "plan_identity_duplicate_rows": plan_identity_duplicates,
                "region_context_mismatch_count": region_context_count,
                "region_context_mismatch_fields": region_context_fields,
                "worker_context_mismatch_count": worker_context_count,
                "worker_context_mismatch_fields": worker_context_fields,
                "feature_context_mismatch_count": feature_context_count,
                "feature_context_mismatch_fields": feature_context_fields,
                "orphan_worker_plan_count": len(orphan_worker_plan_ids),
                "worker_region_mismatch_count": worker_region_mismatch_count,
                "remote_path_missing_count": remote_path_missing_count,
                "worker_path_missing_count": worker_path_missing_count,
                "applicability_ok": applicable_ok,
                "uniqueness_ok": uniqueness_ok,
                "consistency_ok": consistency_ok,
                "artifact_paths_ok": artifact_paths_ok,
                "resolution_status": resolution_status,
                "issue_count": len(issue_codes),
                "issue_codes": ",".join(issue_codes),
            }
        )

    return pd.DataFrame(rows), pd.DataFrame(unresolved)


def summarize_logical_run(
    logical_root: Path,
    logical_run_id: str,
    audit: pd.DataFrame,
    unresolved: pd.DataFrame,
) -> dict[str, Any]:
    """Summarize identity, retry and evidence cardinality for one logical run."""

    run_root = logical_root / logical_run_id
    index_dir = run_root / "_index"
    query_runs = read_csv(index_dir / "query_runs.csv")
    features = read_csv(index_dir / "execution_features.csv")
    regions = read_csv(index_dir / "region_fragments.csv")
    workers = read_csv(index_dir / "worker_task_fragments.csv")
    attempts = read_csv(run_root / "query_attempts.csv")
    resolved = read_csv(run_root / "resolved_query_status.csv")

    query_counts = (
        query_runs["query_run_id"].astype(str).value_counts()
        if not query_runs.empty
        else pd.Series(dtype=int)
    )
    feature_counts = (
        features["query_run_id"].astype(str).value_counts()
        if not features.empty
        else pd.Series(dtype=int)
    )
    query_ids = set(query_counts.index)
    feature_ids = set(feature_counts.index)
    one_to_one_ids = {
        value
        for value in query_ids & feature_ids
        if int(query_counts[value]) == 1 and int(feature_counts[value]) == 1
    }

    attempt_status = (
        attempts.get("execution_status", pd.Series(dtype=str))
        .astype(str)
        .str.lower()
    )
    attempt_counts = pd.to_numeric(
        resolved.get("attempt_count", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0)
    resolved_status = (
        resolved.get("resolved_status", pd.Series(dtype=str))
        .astype(str)
        .str.lower()
    )
    timed_out_count = (
        int(attempts.get("timed_out", pd.Series(dtype=object)).map(truthy).sum())
        if not attempts.empty
        else 0
    )

    expected_region_slots = int(
        audit["expected_regions"]
        .fillna("")
        .astype(str)
        .map(lambda value: len([item for item in value.split(",") if item]))
        .sum()
    )
    found_expected_region_slots = expected_region_slots - int(
        audit["missing_region_count"].sum()
    )
    expected_worker_fragments = int(audit["expected_worker_fragment_count"].sum())

    return {
        "logical_run_id": logical_run_id,
        "report_scope": (
            "main_corpus"
            if logical_run_id == MAIN_LOGICAL_RUN_ID
            else "validation_regression"
        ),
        "expected_logical_instance_count": int(len(resolved)),
        "resolved_completed_instance_count": int(resolved_status.eq("completed").sum()),
        "unresolved_logical_instance_count": int(
            (~resolved_status.eq("completed")).sum()
        ),
        "query_attempt_count": int(len(attempts)),
        "completed_attempt_count": int(attempt_status.eq("completed").sum()),
        "timeout_attempt_count": timed_out_count,
        "failed_attempt_count": int(attempt_status.eq("failed").sum()),
        "missing_attempt_count": int(attempt_status.eq("missing").sum()),
        "retried_instance_count": int(attempt_counts.gt(1).sum()),
        "resolved_after_retry_count": int(
            (attempt_counts.gt(1) & resolved_status.eq("completed")).sum()
        ),
        "query_run_row_count": int(len(query_runs)),
        "unique_query_run_id_count": int(len(query_counts)),
        "duplicate_query_run_row_count": int(query_counts[query_counts.gt(1)].sum()),
        "execution_feature_row_count": int(len(features)),
        "unique_feature_query_run_id_count": int(len(feature_counts)),
        "duplicate_feature_row_count": int(
            feature_counts[feature_counts.gt(1)].sum()
        ),
        "query_without_feature_count": int(len(query_ids - feature_ids)),
        "feature_without_query_count": int(len(feature_ids - query_ids)),
        "one_to_one_query_feature_count": int(len(one_to_one_ids)),
        "one_to_one_query_feature_ok": bool(
            len(one_to_one_ids) == len(query_ids) == len(feature_ids)
        ),
        "exactly_one_main_plan_count": int(audit["main_plan_count"].eq(1).sum()),
        "parsed_main_plan_count": int(audit["main_plan_parse_ok"].sum()),
        "main_plan_parse_failure_count": int(
            (~audit["main_plan_parse_ok"]).sum()
        ),
        "remote_applicable_query_count": int(audit["remote_evidence_applicable"].sum()),
        "remote_not_applicable_query_count": int(
            (~audit["remote_evidence_applicable"]).sum()
        ),
        "expected_region_slot_count": expected_region_slots,
        "found_expected_region_slot_count": found_expected_region_slots,
        "observed_region_fragment_count": int(len(regions)),
        "regional_plan_parse_failure_count": int(
            audit["region_parse_failure_count"].sum()
        ),
        "expected_worker_fragment_count_when_available": expected_worker_fragments,
        "observed_worker_fragment_count": int(len(workers)),
        "worker_plan_parse_failure_count": int(
            audit["worker_parse_failure_count"].sum()
        ),
        "worker_task_list_unavailable_plan_count": int(
            audit["worker_unavailable_plan_count"].sum()
        ),
        "duplicate_child_identity_row_count": int(
            audit[
                [
                    "region_identity_duplicate_rows",
                    "remote_sql_slot_duplicate_rows",
                    "worker_identity_duplicate_rows",
                    "plan_identity_duplicate_rows",
                ]
            ].sum().sum()
        ),
        "orphan_worker_plan_count": int(audit["orphan_worker_plan_count"].sum()),
        "context_mismatch_count": int(
            audit[
                [
                    "region_context_mismatch_count",
                    "worker_context_mismatch_count",
                    "feature_context_mismatch_count",
                ]
            ].sum().sum()
        ),
        "missing_applicable_evidence_query_count": int(
            (
                audit["remote_evidence_applicable"]
                & (
                    audit["missing_region_count"].gt(0)
                    | audit["main_plan_exists"].eq(False)
                )
            ).sum()
        ),
        "artifact_path_failure_count": int((~audit["artifact_paths_ok"]).sum()),
        "fully_complete_query_count": int(audit["issue_count"].eq(0).sum()),
        "unresolved_issue_count": int(len(unresolved)),
        "overall_correctness_gate": bool(
            len(resolved) == len(query_runs) == len(features)
            and resolved_status.eq("completed").all()
            and len(one_to_one_ids) == len(query_ids) == len(feature_ids)
            and audit["issue_count"].eq(0).all()
        ),
    }


def select_manual_cases(
    audit: pd.DataFrame,
    *,
    sample_size: int = 24,
    seed: str = "collector-correctness-v1",
) -> pd.DataFrame:
    if audit.empty:
        return audit.copy()
    candidates = audit.copy()
    defaults = {
        "expected_shape_tags": "",
        "intervention_axis": "",
        "worker_unavailable_plan_count": 0,
    }
    for column, default in defaults.items():
        if column not in candidates.columns:
            candidates[column] = default
    candidates["selection_score"] = candidates.apply(
        lambda row: stable_score(
            seed,
            row["logical_run_id"],
            row["query_run_id"],
        ),
        axis=1,
    )
    selected_indexes: list[int] = []

    def take_one(frame: pd.DataFrame) -> None:
        frame = frame.loc[~frame.index.isin(selected_indexes)]
        if not frame.empty:
            selected_indexes.append(frame.sort_values("selection_score").index[0])

    for _, group in candidates.groupby("logical_question_id", sort=True):
        take_one(group)
    for _, group in candidates.groupby("execution_strategy", sort=True):
        take_one(group)
    for logical_run_id in sorted(candidates["logical_run_id"].unique()):
        take_one(candidates[candidates["logical_run_id"].eq(logical_run_id)])
    take_one(candidates[candidates["attempt_number"].fillna(1).astype(float).gt(1)])
    worker_unavailable = candidates.get(
        "worker_unavailable_plan_count",
        pd.Series(0, index=candidates.index),
    )
    take_one(candidates[worker_unavailable.gt(0)])
    shape_tags = candidates.get(
        "expected_shape_tags",
        pd.Series("", index=candidates.index),
    )
    take_one(
        candidates[
            shape_tags.astype(str).str.contains(
                "repartition", case=False, na=False
            )
        ]
    )
    take_one(candidates[candidates["issue_count"].gt(0)])

    remaining = candidates.loc[~candidates.index.isin(selected_indexes)].sort_values(
        "selection_score"
    )
    selected_indexes.extend(
        remaining.head(max(0, sample_size - len(selected_indexes))).index.tolist()
    )
    result = candidates.loc[selected_indexes[:sample_size]].copy()
    result.insert(0, "manual_case_id", [f"CC-{index:02d}" for index in range(1, len(result) + 1)])
    result["selection_seed"] = seed
    result["selection_reason"] = result.apply(
        lambda row: (
            f"family={row['logical_question_id']};"
            f"strategy={row['execution_strategy']};"
            f"run={row['logical_run_id']}"
        ),
        axis=1,
    )
    columns = [
        "manual_case_id",
        "logical_run_id",
        "query_run_id",
        "instance_id",
        "template_id",
        "logical_question_id",
        "execution_strategy",
        "expected_shape_tags",
        "intervention_axis",
        "dataset_id",
        "runtime_config_id",
        "attempt_number",
        "expected_regions",
        "observed_regions",
        "observed_remote_fragment_count",
        "observed_worker_fragment_count",
        "worker_unavailable_plan_count",
        "evidence_completeness",
        "issue_codes",
        "selection_reason",
        "selection_seed",
        "selection_score",
    ]
    return result[columns].reset_index(drop=True)


def summarize_audit(
    audit: pd.DataFrame,
    unresolved: pd.DataFrame,
    manual_results: pd.DataFrame | None = None,
) -> dict[str, Any]:
    manual_results = manual_results if manual_results is not None else pd.DataFrame()
    reviewed = (
        manual_results[
            manual_results.get("review_status", pd.Series(dtype=str))
            .astype(str)
            .eq("reviewed")
        ]
        if not manual_results.empty
        else pd.DataFrame()
    )
    correct = (
        int(reviewed["link_correct"].astype(str).str.lower().eq("true").sum())
        if not reviewed.empty and "link_correct" in reviewed.columns
        else 0
    )
    return {
        "query_count": int(len(audit)),
        "logical_run_count": int(audit["logical_run_id"].nunique()),
        "execution_strategies": sorted(audit["execution_strategy"].unique().tolist()),
        "fully_complete_query_count": int(audit["issue_count"].eq(0).sum()),
        "minimum_evidence_completeness": float(
            audit["evidence_completeness"].min()
        ),
        "applicability_failure_count": int((~audit["applicability_ok"]).sum()),
        "uniqueness_failure_count": int((~audit["uniqueness_ok"]).sum()),
        "consistency_failure_count": int((~audit["consistency_ok"]).sum()),
        "artifact_path_failure_count": int((~audit["artifact_paths_ok"]).sum()),
        "ambiguous_candidate_count": int(
            audit["resolution_status"].eq("ambiguous").sum()
        ),
        "unresolved_issue_count": int(len(unresolved)),
        "manual_reviewed_count": int(len(reviewed)),
        "manual_correct_link_count": correct,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
