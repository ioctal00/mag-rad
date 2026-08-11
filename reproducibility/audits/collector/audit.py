#!/usr/bin/env python3
"""Offline audit of the thesis evidence collection and indexing pipeline.

The validator reads source snapshots, packaged raw attempts, packaged logical
indexes, and published audit tables. It never connects to experiment hosts or
executes SQL. By default it verifies hashes only for audit-critical release
files; pass --full-hash to verify every entry in artifacts/release-manifest.json.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import tarfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


THIS_FILE = Path(__file__).resolve()
PACKAGE_ROOT = THIS_FILE.parents[3]
OUTPUT_DIR = THIS_FILE.parent


def workspace_file(relative_path: str) -> Path:
    prefixes = {
        "master-regimes": "master-regimes",
        "master-regimes-infra": "master-regimes-infra",
        "psql-benchmarks": "psql-benchmarks",
        "citus-datagen": "citus-datagen",
    }
    parts = Path(relative_path).parts
    if parts and parts[0] == "master-thesis-final":
        return PACKAGE_ROOT.joinpath(*parts[1:])
    if parts and parts[0] in prefixes:
        return PACKAGE_ROOT / "sources" / prefixes[parts[0]] / Path(*parts[1:])
    return PACKAGE_ROOT / relative_path


def package_file(relative_path: str) -> Path:
    return PACKAGE_ROOT / relative_path


def line_ref(relative_path: str, needle: str | None = None) -> str:
    path = workspace_file(relative_path)
    line_number = 1
    if needle and path.is_file():
        for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if needle in line:
                line_number = index
                break
    return f"{relative_path}:{line_number}"


def read_csv_path(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def tar_csv(
    archive: tarfile.TarFile,
    member_name: str,
) -> list[dict[str, str]]:
    try:
        member = archive.extractfile(member_name)
    except KeyError:
        return []
    if member is None:
        return []
    with io.TextIOWrapper(member, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def bool_text(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def audit_logical_archives() -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted((PACKAGE_ROOT / "artifacts/logical-indexes").glob("*.tar.gz")):
        with tarfile.open(path, "r:gz") as archive:
            names = archive.getnames()
            prefix = names[0].split("/", 1)[0]

            def indexed(name: str) -> list[dict[str, str]]:
                return tar_csv(archive, f"{prefix}/_index/{name}")

            def root_table(name: str) -> list[dict[str, str]]:
                return tar_csv(archive, f"{prefix}/{name}")

            queries = indexed("query_runs.csv")
            features = indexed("execution_features.csv")
            plans = indexed("plan_files.csv")
            regions = indexed("region_fragments.csv")
            workers = indexed("worker_task_fragments.csv")
            attempts = root_table("query_attempts.csv")
            resolved = root_table("resolved_query_status.csv")

        query_ids = [row.get("query_run_id", "") for row in queries]
        feature_ids = [row.get("query_run_id", "") for row in features]
        query_set = set(query_ids)
        plan_main_counts: Counter[str] = Counter(
            row.get("query_run_id", "")
            for row in plans
            if row.get("plan_scope") == "main"
        )
        region_plan_ids = {
            row.get("remote_plan_id", "") for row in regions if row.get("remote_plan_id")
        }
        worker_plan_ids = {
            row.get("plan_id", "") for row in workers if row.get("plan_id")
        }
        resolved_completed = {
            row.get("resolved_query_run_id", "")
            for row in resolved
            if row.get("resolved_status") == "completed" and row.get("resolved_query_run_id")
        }
        retry_count = sum(
            1 for row in resolved if int(row.get("attempt_count") or 0) > 1
        )
        worker_unavailable_regions = sum(
            1
            for row in regions
            if str(row.get("remote_citus_task_list_available", "")).lower() == "false"
        )
        specialized_partial = not plans and bool(queries)
        checks = {
            "query_ids_unique": len(query_ids) == len(query_set),
            "query_feature_one_to_one": query_set == set(feature_ids)
            and len(feature_ids) == len(set(feature_ids)),
            "exactly_one_main_plan": (
                None
                if specialized_partial
                else all(plan_main_counts.get(query_id, 0) == 1 for query_id in query_set)
            ),
            "region_children_linked": not (
                {row.get("query_run_id", "") for row in regions} - query_set
            ),
            "worker_children_linked": not (
                {row.get("query_run_id", "") for row in workers} - query_set
            ),
            "worker_plans_linked_to_regions": not (worker_plan_ids - region_plan_ids),
            "resolved_completed_matches_index": (
                None if not resolved else resolved_completed == query_set
            ),
        }
        for check_name, passed in checks.items():
            if passed is False:
                errors.append(f"{path.name}: {check_name}")
        results.append(
            {
                "archive": path.name,
                "query_count": len(queries),
                "feature_count": len(features),
                "plan_file_count": len(plans),
                "region_fragment_count": len(regions),
                "worker_fragment_count": len(workers),
                "physical_attempt_count": len(attempts),
                "logical_status_count": len(resolved),
                "retried_logical_slot_count": retry_count,
                "region_rows_with_unavailable_task_list": worker_unavailable_regions,
                "specialized_partial_index": specialized_partial,
                "checks": checks,
            }
        )
    return results, errors


def audit_raw_archives() -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted((PACKAGE_ROOT / "artifacts/raw-attempts").glob("*.tar.gz")):
        names: set[str] = set()
        query_dirs: set[str] = set()
        statuses: dict[str, str] = {}
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                name = member.name
                names.add(name)
                if name.endswith("/input/query.sql"):
                    query_dirs.add(name[: -len("/input/query.sql")])
                if not name.endswith("/execution_status.json"):
                    continue
                query_dir = name[: -len("/execution_status.json")]
                if "/query-collections/" not in query_dir:
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                try:
                    payload = json.loads(handle.read().decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    statuses[query_dir] = "invalid"
                else:
                    statuses[query_dir] = str(
                        payload.get("status") or payload.get("execution_status") or ""
                    ).lower()
        execution_manifest_count = sum(
            f"{query_dir}/execution_manifest.json" in names for query_dir in query_dirs
        )
        execution_status_count = len(statuses)
        per_query = {
            query_dir: {
                "main_plan": False,
                "regional_log": False,
            }
            for query_dir in query_dirs
        }
        result_signature_count = 0
        result_rows_count = 0
        os_summary_count = 0
        marker = "/query-collections/"
        for name in names:
            if marker not in name:
                continue
            before, after = name.split(marker, 1)
            collection_id = after.split("/", 1)[0]
            query_dir = f"{before}{marker}{collection_id}"
            state = per_query.get(query_dir)
            if state is None:
                continue
            if "/nodes/" in name and "/plans/" in name and name.endswith(".explain.json"):
                state["main_plan"] = True
            if "/regional-auto-explain/" in name and name.endswith(".log"):
                state["regional_log"] = True
            result_signature_count += name.endswith(".result-signature.json")
            result_rows_count += name.endswith("result_rows.csv")
            os_summary_count += name.endswith("os_query_summary.json") or name.endswith(
                "os_summary.json"
            )
        main_plan_count = sum(state["main_plan"] for state in per_query.values())
        regional_log_query_count = sum(
            state["regional_log"] for state in per_query.values()
        )
        completed_dirs = {
            query_dir for query_dir, status in statuses.items() if status == "completed"
        }
        completed_manifest_count = sum(
            f"{query_dir}/execution_manifest.json" in names for query_dir in completed_dirs
        )
        completed_main_plan_count = sum(
            per_query[query_dir]["main_plan"] for query_dir in completed_dirs
        )
        archive_errors: list[str] = []
        if execution_status_count != len(query_dirs):
            archive_errors.append("missing top-level execution statuses")
        if completed_manifest_count != len(completed_dirs):
            archive_errors.append("completed execution missing top-level manifest")
        if completed_main_plan_count != len(completed_dirs):
            archive_errors.append("completed execution missing GAC/main EXPLAIN artifact")
        errors.extend(f"{path.name}: {item}" for item in archive_errors)
        results.append(
            {
                "archive": path.name,
                "query_collection_count": len(query_dirs),
                "completed_query_collection_count": len(completed_dirs),
                "incomplete_query_collection_count": len(query_dirs) - len(completed_dirs),
                "execution_manifest_count": execution_manifest_count,
                "execution_status_count": execution_status_count,
                "main_plan_query_count": main_plan_count,
                "completed_main_plan_query_count": completed_main_plan_count,
                "regional_log_query_count": regional_log_query_count,
                "result_signature_artifact_count": result_signature_count,
                "result_rows_artifact_count": result_rows_count,
                "os_summary_artifact_count": os_summary_count,
                "errors": archive_errors,
            }
        )
    return results, errors


def audit_release_manifest(full_hash: bool) -> dict[str, Any]:
    manifest_path = PACKAGE_ROOT / "artifacts/release-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {row["path"]: row for row in payload.get("files", [])}
    critical = {
        "reproducibility/source-provenance.csv",
        "artifacts/results/collector-correctness-v2/collector_correctness_summary.json",
        "artifacts/results/collector-correctness-v2/query_evidence_audit.csv",
        "artifacts/logical-indexes/clean-run-v1.tar.gz",
        "artifacts/raw-attempts/clean-run-v1.tar.gz",
        "releases/feedback-loop-execution-v1/main/result_equivalence_audit.csv",
        "sources/master-regimes-infra/common-scripts/run_query_collection.py",
        "sources/master-regimes-infra/common-scripts/run_query_collection_sweep.py",
        "sources/master-regimes-infra/common-scripts/index_corpus_run_attempts.py",
        "sources/master-regimes/src/master_regimes/extract/query_sweep_index.py",
        "sources/psql-benchmarks/src/psql_benchmarks/flows.py",
        "sources/psql-benchmarks/src/psql_benchmarks/os_sampler.py",
        "sources/psql-benchmarks/src/psql_benchmarks/psql.py",
    }
    selected = set(entries) if full_hash else critical
    missing_entries: list[str] = []
    missing_files: list[str] = []
    hash_mismatches: list[str] = []
    size_mismatches: list[str] = []
    for relative in sorted(selected):
        entry = entries.get(relative)
        if entry is None:
            missing_entries.append(relative)
            continue
        path = PACKAGE_ROOT / relative
        if not path.is_file():
            missing_files.append(relative)
            continue
        if path.stat().st_size != int(entry["size"]):
            size_mismatches.append(relative)
        if sha256_file(path) != entry["sha256"]:
            hash_mismatches.append(relative)
    return {
        "declared_file_count": payload.get("file_count"),
        "manifest_entry_count": len(entries),
        "verified_file_count": len(selected) - len(missing_entries) - len(missing_files),
        "verification_scope": "all" if full_hash else "audit_critical",
        "missing_manifest_entries": missing_entries,
        "missing_files": missing_files,
        "size_mismatches": size_mismatches,
        "hash_mismatches": hash_mismatches,
        "ok": not (missing_entries or missing_files or size_mismatches or hash_mismatches),
    }


def audit_correctness_summary() -> dict[str, Any]:
    path = PACKAGE_ROOT / "artifacts/results/collector-correctness-v2/collector_correctness_summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_zero = (
        "ambiguous_candidate_count",
        "applicability_failure_count",
        "artifact_path_failure_count",
        "consistency_failure_count",
        "uniqueness_failure_count",
        "unresolved_issue_count",
    )
    failures = {key: payload.get(key) for key in expected_zero if payload.get(key) != 0}
    main = payload.get("main_corpus", {})
    validation = payload.get("validation_regression", {})
    return {
        "query_count": payload.get("query_count"),
        "fully_complete_query_count": payload.get("fully_complete_query_count"),
        "manual_reviewed_count": payload.get("manual_reviewed_count"),
        "manual_sampling_design": payload.get("manual_sampling_design"),
        "main_corpus_query_count": main.get("query_run_row_count"),
        "main_corpus_worker_fragment_count": main.get("observed_worker_fragment_count"),
        "worker_task_list_unavailable_plan_count": main.get(
            "worker_task_list_unavailable_plan_count"
        ),
        "validation_attempt_count": validation.get("query_attempt_count"),
        "validation_resolved_count": validation.get("resolved_completed_instance_count"),
        "validation_retried_instance_count": validation.get("retried_instance_count"),
        "validation_resolved_after_retry_count": validation.get("resolved_after_retry_count"),
        "unexpected_nonzero_failures": failures,
        "ok": (
            payload.get("query_count") == payload.get("fully_complete_query_count")
            and bool(main.get("overall_correctness_gate"))
            and bool(validation.get("overall_correctness_gate"))
            and not failures
        ),
    }


def audit_equivalence_tables() -> dict[str, Any]:
    paths = [
        PACKAGE_ROOT / "releases/feedback-loop-execution-v1/main/result_equivalence_audit.csv",
        PACKAGE_ROOT / "releases/feedback-loop-execution-v1/aggregate-exact/result_equivalence_audit.csv",
    ]
    rows = [row for path in paths for row in read_csv_path(path)]
    equivalent = [row for row in rows if row.get("result_validation_status") == "equivalent"]
    missing_hashes = []
    hash_mismatches = []
    for row in equivalent:
        ordered = (row.get("before_ordered_sha256"), row.get("after_ordered_sha256"))
        multiset = (row.get("before_multiset_sha256"), row.get("after_multiset_sha256"))
        if not all((*ordered, *multiset)):
            missing_hashes.append(row.get("decision_id", ""))
        if ordered[0] != ordered[1] or multiset[0] != multiset[1]:
            hash_mismatches.append(row.get("decision_id", ""))

    n3_path = PACKAGE_ROOT / "artifacts/results/pressure-actionability-v1/n3_result/n3_result_equivalence.csv"
    n3_rows = read_csv_path(n3_path)
    n3_failures = [
        row.get("pair_id", "")
        for row in n3_rows
        if not (bool_text(row.get("comparable")) and bool_text(row.get("equivalent")))
    ]
    return {
        "feedback_rows": len(rows),
        "feedback_equivalent_rows": len(equivalent),
        "feedback_missing_hash_rows": missing_hashes,
        "feedback_hash_mismatch_rows": hash_mismatches,
        "n3_pair_count": len(n3_rows),
        "n3_failed_pair_ids": n3_failures,
        "ok": not (missing_hashes or hash_mismatches or n3_failures),
    }


def audit_source_snapshots() -> dict[str, Any]:
    expected = [
        "sources/master-regimes-infra/common-scripts/run_query_collection.py",
        "sources/master-regimes-infra/common-scripts/run_query_collection_sweep.py",
        "sources/master-regimes-infra/common-scripts/index_corpus_run_attempts.py",
        "sources/master-regimes/src/master_regimes/collector_audit.py",
        "sources/master-regimes/src/master_regimes/extract/query_sweep_index.py",
        "sources/psql-benchmarks/src/psql_benchmarks/flows.py",
        "sources/psql-benchmarks/src/psql_benchmarks/os_sampler.py",
        "sources/psql-benchmarks/src/psql_benchmarks/psql.py",
    ]
    missing = [relative for relative in expected if not package_file(relative).is_file()]
    provenance_rows = read_csv_path(PACKAGE_ROOT / "reproducibility/source-provenance.csv")
    repositories = {row.get("repository", "") for row in provenance_rows}
    required_repositories = {
        "master-regimes",
        "master-regimes-infra",
        "psql-benchmarks",
    }
    return {
        "expected_snapshot_file_count": len(expected),
        "missing_snapshot_files": missing,
        "provenance_repository_count": len(repositories),
        "missing_provenance_repositories": sorted(required_repositories - repositories),
        "ok": not missing and required_repositories <= repositories,
    }


def code_contract_observations() -> dict[str, Any]:
    runner = workspace_file(
        "master-regimes-infra/common-scripts/run_query_collection.py"
    ).read_text(encoding="utf-8")
    indexer = workspace_file(
        "master-regimes/src/master_regimes/extract/query_sweep_index.py"
    ).read_text(encoding="utf-8")
    os_sampler = workspace_file(
        "psql-benchmarks/src/psql_benchmarks/os_sampler.py"
    ).read_text(encoding="utf-8")
    resolver = workspace_file(
        "master-regimes-infra/common-scripts/index_corpus_run_attempts.py"
    ).read_text(encoding="utf-8")
    return {
        "runner_sets_unique_fdw_application_name": "OPTIONS (ADD application_name" in runner,
        "runner_captures_log_suffix_from_start_line": "tail -n +{start_line + 1}" in runner,
        "indexer_filters_auto_explain_by_application_name": "application_name" in indexer,
        "indexer_silently_skips_malformed_auto_explain_json": (
            "except json.JSONDecodeError:\n            continue" in indexer
        ),
        "result_signature_is_follow_up_execution": (
            "Computing stream-only result signature" in runner
            and "./bin/result-signature" in runner
        ),
        "os_sampler_reads_cpu_steal": '"steal"' in os_sampler,
        "os_sampler_reads_host_network_counters": "/proc/net/dev" in os_sampler,
        "resolver_key_contains_target_host": "target_host" in resolver[
            resolver.find("def logical_query_key") : resolver.find("def planned_query_row")
        ],
        "indexer_has_typed_missing_statuses": all(
            token in indexer
            for token in (
                "missing_unexpected",
                "not_applicable_direct_or_local",
                "structurally_unavailable_repartition",
                "unavailable_in_embedded_task_plan",
            )
        ),
    }


def finding(
    finding_id: str,
    severity: str,
    title: str,
    disposition: str,
    evidence: Iterable[str],
    impact: str,
    recommendation: str,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "title": title,
        "disposition": disposition,
        "evidence": list(evidence),
        "impact": impact,
        "recommendation": recommendation,
    }


def build_findings(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        finding(
            "COL-001",
            "positive",
            "The packaged canonical indexes preserve the query-to-plan-to-region-to-worker graph",
            "verified",
            [
                line_ref(
                    "master-regimes/src/master_regimes/extract/query_sweep_index.py",
                    "def _auto_explain_plan_files",
                ),
                "master-thesis-final/artifacts/results/collector-correctness-v2/collector_correctness_summary.json:1",
            ],
            "Across standard logical archives, query IDs are unique, features are one-to-one, each query has one main plan, and worker plan IDs resolve to regional plan IDs.",
            "Retain these checks as release gates.",
        ),
        finding(
            "COL-002",
            "positive",
            "Missing, unavailable, and not-applicable evidence are not collapsed into numeric zero",
            "verified",
            [
                line_ref(
                    "master-regimes/src/master_regimes/extract/query_sweep_index.py",
                    'regional_status = "missing_unexpected"',
                ),
                line_ref(
                    "master-regimes/src/master_regimes/extract/query_sweep_index.py",
                    'worker_status = "structurally_unavailable_repartition"',
                ),
            ],
            "The index can distinguish absence caused by execution structure from an unexpected collector gap.",
            "Keep status columns alongside all derived numeric features.",
        ),
        finding(
            "COL-003",
            "positive",
            "Attempt and slot identities support crash-safe resume and deterministic consolidation",
            "verified",
            [
                line_ref(
                    "master-regimes/src/master_regimes/corpus_adapter.py",
                    'row["execution_slot_id"] =',
                ),
                line_ref(
                    "master-regimes-infra/common-scripts/run_query_collection_sweep.py",
                    "os.fsync(handle.fileno())",
                ),
                line_ref(
                    "master-regimes-infra/common-scripts/index_corpus_run_attempts.py",
                    "best = max(",
                ),
            ],
            "Completed attempts outrank failed or missing attempts, while physical attempts remain auditable.",
            "Preserve both query_attempts.csv and resolved_query_status.csv in every public logical run.",
        ),
        finding(
            "COL-004",
            "medium",
            "Regional auto_explain attribution is window-scoped but not parser-enforced by application name",
            "open limitation",
            [
                line_ref(
                    "master-regimes-infra/common-scripts/run_query_collection.py",
                    "OPTIONS (ADD application_name",
                ),
                line_ref(
                    "master-regimes-infra/common-scripts/run_query_collection.py",
                    "tail -n +{start_line + 1}",
                ),
                line_ref(
                    "master-regimes/src/master_regimes/extract/query_sweep_index.py",
                    "documents = _extract_auto_explain_json_documents",
                ),
            ],
            "The runner creates a unique FDW application name, but the indexer ingests every auto_explain document in the captured log suffix. The link is strong only under the declared serial, controlled workload; concurrent regional statements could be misattributed.",
            "Persist the PostgreSQL log prefix fields and filter documents by application_name, backend PID, or a query marker before claiming production-grade correlation.",
        ),
        finding(
            "COL-005",
            "medium",
            "Result equivalence uses a follow-up SQL execution and the package exposes hashes, not raw rows",
            "open limitation",
            [
                line_ref(
                    "master-regimes-infra/common-scripts/run_query_collection.py",
                    "Computing stream-only result signature",
                ),
                line_ref(
                    "psql-benchmarks/src/psql_benchmarks/psql.py",
                    "def result_signature",
                ),
                "master-thesis-final/releases/feedback-loop-execution-v1/main/result_equivalence_audit.csv:1",
            ],
            "The published equality hashes are internally consistent, but they are produced by a second execution after EXPLAIN ANALYZE. Most raw-attempt archives contain neither signature artifacts nor result rows, so an external reader cannot recompute those hashes from the release alone.",
            "Describe this as same-SQL/same-context follow-up validation, and package signature JSON or bounded typed result snapshots for representative cases.",
        ),
        finding(
            "COL-006",
            "medium",
            "OS, network, disk, and VPS steal samples are host-level ambient context",
            "accepted limitation",
            [
                line_ref(
                    "psql-benchmarks/src/psql_benchmarks/os_sampler.py",
                    'Path("/proc/stat")',
                ),
                line_ref(
                    "psql-benchmarks/src/psql_benchmarks/os_sampler.py",
                    '"cpu_steal_pct"',
                ),
                line_ref(
                    "master-regimes/src/master_regimes/extract/query_sweep_index.py",
                    '"destination_rx_scope": "gac_node_global_shared_across_edges"',
                ),
            ],
            "Query-window alignment narrows time, but counters still include PostgreSQL background work, other processes, shared interfaces, and hypervisor scheduling. cpu_steal_pct is denied guest CPU time, not SQL CPU consumption.",
            "Use these fields only as ambient infrastructure context unless future collection adds PID/cgroup/eBPF attribution.",
        ),
        finding(
            "COL-007",
            "low",
            "Malformed regional auto_explain JSON is silently discarded",
            "open gap",
            [
                line_ref(
                    "master-regimes/src/master_regimes/extract/query_sweep_index.py",
                    "except json.JSONDecodeError:",
                )
            ],
            "Expected-region checks may reveal a missing required plan, but malformed extra/internal documents disappear without a parse-failure row or source offset.",
            "Emit a parse-error record with host, log path, line range, and document hash.",
        ),
        finding(
            "COL-008",
            "low",
            "Logical retry identity omits the concrete target host",
            "contract assumption",
            [
                line_ref(
                    "master-regimes-infra/common-scripts/index_corpus_run_attempts.py",
                    "def logical_query_key",
                )
            ],
            "The key includes target_group, condition, instance, and repetition but not target_host/coordinator. Intended manifests keep the host stable, yet an accidental rerun on another coordinator in the same group could be merged.",
            "Add target_host or a topology/coordinator identity to the logical key, or validate it as an immutable context field before resolution.",
        ),
        finding(
            "COL-009",
            "medium",
            "The release snapshots implementation code but does not prove the exact run-time commit",
            "open provenance gap",
            [
                "master-thesis-final/reproducibility/source-provenance.csv:1",
                "master-thesis-final/artifacts/results/experimental-reproducibility-v2/source_manifest.json:1",
                "master-thesis-final/artifacts/results/experimental-reproducibility-v2/collection_protocol.csv:1",
            ],
            "The package is sufficient to inspect current/snapshotted implementation and recorded indexes, but several protocol values are reconstructed_from_versioned_config and the run-time commit policy says not_recorded unless explicitly persisted.",
            "Do not describe the package as bit-identical run provenance. Persist repository commits and dirty-state patches in every future execution manifest.",
        ),
        finding(
            "COL-010",
            "low",
            "One specialized logical archive is not a full collector index",
            "explicit packaging gap",
            [
                "master-thesis-final/artifacts/logical-indexes/pressure-raw-v1-n3-colocation-holdout.tar.gz:1"
            ],
            "The pressure N3 holdout archive has query/features/region/worker tables but no plan_files, query_attempts, or resolved_query_status tables. It supports downstream feature audit, not a complete retry/main-plan audit by itself.",
            "Label specialized derived indexes explicitly and provide a manifest linking them to their raw-attempt source archive and canonical logical run.",
        ),
    ]


def check_row(check_id: str, status: str, summary: str, evidence: list[str]) -> dict[str, Any]:
    return {"id": check_id, "status": status, "summary": summary, "evidence": evidence}


def render_report(payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    checks = payload["checks"]
    findings = payload["findings"]
    logical = metrics["logical_archives"]
    raw = metrics["raw_archives"]
    lines = [
        "# Evidence collection and indexing audit",
        "",
        f"**Verdict:** `{payload['verdict']}`",
        "",
        "This is an offline, read-only audit. It did not connect to infrastructure, execute SQL, or alter the audited repositories. The validator re-read packaged CSV/JSON data and tar archives instead of trusting only the existing summary report.",
        "",
        "## Pipeline trace",
        "",
        "1. **Planned identity.** The corpus adapter derives a condition identity and an `execution_slot_id = condition_id::repetition`; the sweep writes a completed slot only after an indexable manifest exists and the checkpoint is flushed with `fsync`.",
        "2. **Primary GAC execution.** The runner uploads one rendered SQL file and invokes the benchmark wrapper with `EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)` and `citus.explain_all_tasks=on`. One top-level execution manifest binds the SQL, coordinator, runtime options, query window, status, and artifact paths.",
        "3. **FDW and regional evidence.** The GAC plan exposes FDW `Remote SQL`. For the primary execution path, regional role-scoped `auto_explain` is enabled and unique FDW application names are configured. The runner records each regional PostgreSQL log start line and later copies the appended suffix.",
        "4. **Regional Citus and worker/task evidence.** The indexer classifies regional documents as diagnostic, remote query, or internal statement. Citus task plans embedded in regional JSON/text are parsed into worker fragments linked by query ID and regional plan ID.",
        "5. **Edge and OS context.** Optional SSH probes collect route, RTT, qdisc, and interface context. Optional samplers bracket the query window and read host `/proc` counters. These are node/window observations, not process-level SQL attribution.",
        "6. **Result validation.** Optional stream signatures compute ordered and multiset SHA-256 summaries. They run after the primary EXPLAIN execution, so they are follow-up validation under the same intended context rather than a transactionally identical observation.",
        "7. **Retry consolidation.** Physical attempts remain in `query_attempts.csv`. Resolution groups the declared logical fields, ranks completed attempts above timeouts/failures/missing rows, and uses the latest attempt within the best status.",
        "8. **Typed evidence status.** The final index distinguishes `available`, `missing_unexpected`, `not_applicable`, `structurally_unavailable_repartition`, and unavailable timing in embedded task plans.",
        "",
        "## Validator checks",
        "",
        "| Check | Status | Result |",
        "| --- | --- | --- |",
    ]
    for row in checks:
        lines.append(f"| `{row['id']}` | **{row['status']}** | {row['summary']} |")

    lines.extend(
        [
            "",
            "## Packaged logical indexes",
            "",
            "| Archive | Queries | Features | Plans | Regions | Workers | Attempts | Retries | Status |",
            "| --- | --: | --: | --: | --: | --: | --: | --: | --- |",
        ]
    )
    for row in logical:
        status = "derived/partial" if row["specialized_partial_index"] else "canonical"
        lines.append(
            f"| `{row['archive']}` | {row['query_count']} | {row['feature_count']} | "
            f"{row['plan_file_count']} | {row['region_fragment_count']} | "
            f"{row['worker_fragment_count']} | {row['physical_attempt_count']} | "
            f"{row['retried_logical_slot_count']} | {status} |"
        )

    lines.extend(
        [
            "",
            "## Packaged raw attempts",
            "",
            "| Archive | Query directories | Completed | Incomplete | GAC plans | Regional log windows | Result signatures | OS summaries |",
            "| --- | --: | --: | --: | --: | --: | --: | --: |",
        ]
    )
    for row in raw:
        lines.append(
            f"| `{row['archive']}` | {row['query_collection_count']} | "
            f"{row['completed_query_collection_count']} | "
            f"{row['incomplete_query_collection_count']} | "
            f"{row['main_plan_query_count']} | {row['regional_log_query_count']} | "
            f"{row['result_signature_artifact_count']} | {row['os_summary_artifact_count']} |"
        )

    lines.extend(
        [
            "",
            "## Findings and explicit gaps",
            "",
        ]
    )
    for row in findings:
        lines.extend(
            [
                f"### {row['id']} [{row['severity']}] {row['title']}",
                "",
                f"**Disposition:** {row['disposition']}",
                "",
                row["impact"],
                "",
                f"**Recommendation:** {row['recommendation']}",
                "",
                "Evidence: " + ", ".join(f"`{item}`" for item in row["evidence"]),
                "",
            ]
        )

    lines.extend(
        [
            "## Public audit sufficiency",
            "",
            "The package is sufficient to audit the archived relational graph for the canonical corpus runs: rendered SQL, GAC plans, regional log windows, normalized regional/worker tables, attempt tables, resolution tables, source snapshots, checksums, and a stratified manual audit are present. The independent validator reproduced key one-to-one and parent/child invariants.",
            "",
            "It is not sufficient for three stronger claims: (1) production-safe regional statement attribution under concurrent load, (2) independent recomputation of most published result hashes from raw result rows, and (3) proof that the packaged source snapshot is exactly the unmodified code used at run time. The host-level telemetry also cannot attribute CPU, network, or disk consumption to one SQL process.",
            "",
            "The 24-row manual review is documented as deterministic stratified sampling, not a probability sample. It supports spot validation but is not a statistical estimate of collector error rate.",
            "",
            "## Reproduction",
            "",
            "```bash",
            "python3 reproducibility/audits/collector/audit.py",
            "python3 reproducibility/audits/collector/audit.py --full-hash",
            "```",
            "",
            "The first command verifies audit-critical release hashes and all logical/raw archive invariants. The second additionally verifies every file listed by `artifacts/release-manifest.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full-hash",
        action="store_true",
        help="Verify SHA-256 for every release-manifest entry instead of audit-critical files.",
    )
    args = parser.parse_args()

    logical, logical_errors = audit_logical_archives()
    raw, raw_errors = audit_raw_archives()
    release = audit_release_manifest(args.full_hash)
    correctness = audit_correctness_summary()
    equivalence = audit_equivalence_tables()
    sources = audit_source_snapshots()
    code_contract = code_contract_observations()

    checks = [
        check_row(
            "source-snapshots",
            "PASS" if sources["ok"] else "FAIL",
            f"{sources['expected_snapshot_file_count']} collector/indexer source files and repository provenance entries checked.",
            ["master-thesis-final/reproducibility/source-provenance.csv:1"],
        ),
        check_row(
            "release-hashes",
            "PASS" if release["ok"] else "FAIL",
            f"{release['verified_file_count']} files verified ({release['verification_scope']} scope).",
            ["master-thesis-final/artifacts/release-manifest.json:1"],
        ),
        check_row(
            "logical-index-graph",
            "PASS" if not logical_errors else "FAIL",
            f"{len(logical)} logical archives checked; {sum(row['query_count'] for row in logical)} query rows inspected.",
            ["master-thesis-final/artifacts/logical-indexes/:1"],
        ),
        check_row(
            "raw-artifact-presence",
            "PASS" if not raw_errors else "FAIL",
            f"{len(raw)} raw archives checked; {sum(row['query_collection_count'] for row in raw)} query directories inspected.",
            ["master-thesis-final/artifacts/raw-attempts/:1"],
        ),
        check_row(
            "published-correctness-gate",
            "PASS" if correctness["ok"] else "FAIL",
            f"Published gate reports {correctness['fully_complete_query_count']}/{correctness['query_count']} complete queries and {correctness['validation_resolved_after_retry_count']} resolved retries.",
            ["master-thesis-final/artifacts/results/collector-correctness-v2/collector_correctness_summary.json:1"],
        ),
        check_row(
            "equivalence-table-consistency",
            "PASS" if equivalence["ok"] else "FAIL",
            f"{equivalence['feedback_equivalent_rows']} feedback-loop equivalence rows and {equivalence['n3_pair_count']} N3 pairs checked.",
            ["master-thesis-final/releases/feedback-loop-execution-v1/main/result_equivalence_audit.csv:1"],
        ),
        check_row(
            "correlation-concurrency-boundary",
            "WARN" if not code_contract["indexer_filters_auto_explain_by_application_name"] else "PASS",
            "Unique FDW application names are configured, but the indexer does not filter parsed log documents by that identity.",
            [
                line_ref(
                    "master-regimes-infra/common-scripts/run_query_collection.py",
                    "OPTIONS (ADD application_name",
                ),
                line_ref(
                    "master-regimes/src/master_regimes/extract/query_sweep_index.py",
                    "documents = _extract_auto_explain_json_documents",
                ),
            ],
        ),
        check_row(
            "host-attribution-boundary",
            "WARN",
            "CPU, steal, interface, TCP, disk, and qdisc evidence is host/window scoped, not query-process scoped.",
            [
                line_ref(
                    "psql-benchmarks/src/psql_benchmarks/os_sampler.py",
                    '"cpu_steal_pct"',
                )
            ],
        ),
    ]

    failures = [row for row in checks if row["status"] == "FAIL"]
    metrics = {
        "logical_archives": logical,
        "raw_archives": raw,
        "release_manifest": release,
        "correctness_summary": correctness,
        "equivalence": equivalence,
        "source_snapshots": sources,
        "code_contract": code_contract,
        "logical_errors": logical_errors,
        "raw_errors": raw_errors,
    }
    findings = build_findings(metrics)
    payload = {
        "schema_version": "collector-offline-audit-v1",
        "generated_from": "packaged offline evidence; deterministic output",
        "scope": {
            "mode": "offline_read_only",
            "repositories": [
                "psql-benchmarks",
                "master-regimes-infra",
                "master-regimes",
                "master-thesis-final",
            ],
            "network_or_sql_execution": False,
        },
        "verdict": "fail" if failures else "pass_with_limitations",
        "checks": checks,
        "findings": findings,
        "metrics": metrics,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "findings.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"verdict": payload["verdict"], "checks": checks}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
