from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_SOURCES = (
    REPO_ROOT / "configs/collection/pressure_probe_preflight_sources.yml"
)
DEFAULT_OUT = (
    REPO_ROOT / "analysis/reports/pressure-collection-uniformity-preflight-v1"
)
PROVENANCE_FIELDS = [
    "collection_family",
    "source_index_id",
    "source_index_kind",
    "source_index_dir",
    "source_query_sweep_dir",
    "source_schema_sha256",
]
CHILD_TABLES = (
    "plan_files",
    "fdw_remote_plans",
    "region_fragments",
    "worker_task_fragments",
    "remote_edge_observations",
    "plan_nodes",
    "plan_edges",
    "query_bindings",
    "node_artifacts",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and validate a uniform multi-source execution evidence package."
    )
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def resolve_workspace_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def resolve_evidence_path(value: str, evidence_workspace_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else evidence_workspace_root / path


def relative_to_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def ordered_union(field_lists: list[list[str]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for fields in sorted(field_lists, key=len, reverse=True):
        for field in fields:
            if field not in seen:
                result.append(field)
                seen.add(field)
    return result


def selection_ids(path: Path) -> set[str]:
    _, rows = read_csv(path)
    return {
        str(row.get("query_run_id", "")).strip()
        for row in rows
        if str(row.get("query_run_id", "")).strip()
    }


def schema_hash(fields: list[str]) -> str:
    return hashlib.sha256("\n".join(fields).encode()).hexdigest()


def query_sweep_dir_for_row(
    *,
    row: dict[str, Any],
    source: dict[str, Any],
    index_dir: Path,
) -> Path | None:
    if source["index_kind"] == "placement_query_sweep":
        return index_dir.parent.resolve()
    database_sweep_id = str(row.get("database_sweep_id", "")).strip()
    query_sweep_dir = str(row.get("query_sweep_dir", "")).strip()
    if not database_sweep_id or not query_sweep_dir:
        return None
    evidence_workspace_root = Path(
        str(source.get("_evidence_workspace_root", WORKSPACE_ROOT))
    )
    corpus_root = (
        evidence_workspace_root
        / "master-regimes-infra/generated/runs/corpus-sweeps"
    )
    candidates = list(
        corpus_root.glob(f"*/database-sweeps/{database_sweep_id}")
    )
    if len(candidates) != 1:
        return None
    return (candidates[0] / query_sweep_dir).resolve()


def with_provenance(
    row: dict[str, Any],
    *,
    source: dict[str, Any],
    index_dir: Path,
    source_schema_hash: str,
) -> dict[str, Any]:
    query_sweep_dir = query_sweep_dir_for_row(
        row=row,
        source=source,
        index_dir=index_dir,
    )
    return {
        "collection_family": source["collection_family"],
        "source_index_id": source["source_id"],
        "source_index_kind": source["index_kind"],
        "source_index_dir": relative_to_workspace(index_dir),
        "source_query_sweep_dir": (
            relative_to_workspace(query_sweep_dir) if query_sweep_dir else ""
        ),
        "source_schema_sha256": source_schema_hash,
        **row,
    }


def integer(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_sources(config_path: Path) -> tuple[
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    sources = payload.get("sources") or []
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"No sources configured in {config_path}")
    evidence_workspace_root = resolve_workspace_path(
        str(payload.get("evidence_workspace_root") or WORKSPACE_ROOT)
    ).resolve()
    if not evidence_workspace_root.is_dir():
        raise FileNotFoundError(
            f"Evidence workspace root does not exist: {evidence_workspace_root}"
        )

    execution_sources: list[dict[str, Any]] = []
    child_rows: dict[str, list[dict[str, Any]]] = {
        table: [] for table in CHILD_TABLES
    }
    schema_rows: list[dict[str, Any]] = []
    for raw_source in sources:
        source = {
            **raw_source,
            "_evidence_workspace_root": str(evidence_workspace_root),
        }
        index_dir = resolve_evidence_path(
            str(source["index_dir"]),
            evidence_workspace_root,
        )
        execution_file = (
            index_dir / "execution_features.csv"
            if (index_dir / "execution_features.csv").exists()
            else index_dir / "query_runs.csv"
        )
        execution_fields, execution_rows = read_csv(execution_file)
        selected_ids = selection_ids(
            resolve_evidence_path(
                str(source["selection_csv"]),
                evidence_workspace_root,
            )
        )
        selected = [
            row for row in execution_rows if row.get("query_run_id") in selected_ids
        ]
        expected = integer(source.get("expected_selected_count"))
        if len(selected) != expected:
            raise ValueError(
                f"{source['source_id']}: selected {len(selected)} rows, expected {expected}"
            )
        source_hash = schema_hash(execution_fields)
        execution_sources.append(
            {
                "source": source,
                "index_dir": index_dir,
                "execution_file": execution_file,
                "execution_fields": execution_fields,
                "schema_hash": source_hash,
                "selected_ids": {row["query_run_id"] for row in selected},
                "rows": selected,
            }
        )
        schema_rows.append(
            {
                "source_index_id": source["source_id"],
                "collection_family": source["collection_family"],
                "source_index_kind": source["index_kind"],
                "source_index_dir": relative_to_workspace(index_dir),
                "execution_file": execution_file.name,
                "execution_column_count": len(execution_fields),
                "source_schema_sha256": source_hash,
                "selected_execution_count": len(selected),
            }
        )
        for table in CHILD_TABLES:
            path = index_dir / f"{table}.csv"
            if not path.exists():
                continue
            _, rows = read_csv(path)
            child_rows[table].extend(
                with_provenance(
                    row,
                    source=source,
                    index_dir=index_dir,
                    source_schema_hash=source_hash,
                )
                for row in rows
                if row.get("query_run_id") in {item["query_run_id"] for item in selected}
            )
    return execution_sources, child_rows, schema_rows


def evidence_quality_rows(
    executions: list[dict[str, Any]],
    children: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    by_table: dict[str, Counter[str]] = {}
    for table, rows in children.items():
        by_table[table] = Counter(str(row.get("query_run_id", "")) for row in rows)

    result: list[dict[str, Any]] = []
    for row in executions:
        query_run_id = str(row["query_run_id"])
        result.append(
            {
                "collection_family": row["collection_family"],
                "source_index_id": row["source_index_id"],
                "query_run_id": query_run_id,
                "template_id": row.get("template_id", ""),
                "execution_status": row.get("execution_status", ""),
                "main_plan_count": sum(
                    child.get("query_run_id") == query_run_id
                    and child.get("plan_scope") == "main"
                    for child in children["plan_files"]
                ),
                "regional_remote_plan_count": by_table["region_fragments"][
                    query_run_id
                ],
                "indexed_regional_remote_plan_count": row.get(
                    "regional_remote_plan_count", ""
                ),
                "remote_region_evidence_completeness": row.get(
                    "remote_region_evidence_completeness", ""
                ),
                "regional_internal_plan_count": sum(
                    child.get("query_run_id") == query_run_id
                    and child.get("plan_scope") == "fdw_auto_explain_internal"
                    for child in children["plan_files"]
                ),
                "fdw_remote_plan_count": by_table["fdw_remote_plans"][query_run_id],
                "worker_task_fragment_count": by_table["worker_task_fragments"][
                    query_run_id
                ],
                "remote_edge_observation_count": by_table[
                    "remote_edge_observations"
                ][query_run_id],
                "indexed_worker_task_plan_count": row.get(
                    "worker_task_plan_count", ""
                ),
                "regional_plan_evidence_status": row.get(
                    "regional_plan_evidence_status", ""
                ),
                "worker_task_evidence_status": row.get(
                    "worker_task_evidence_status", ""
                ),
                "worker_task_plan_format": row.get("worker_task_plan_format", ""),
                "worker_task_timing_status": row.get(
                    "worker_task_timing_status", ""
                ),
                "worker_task_parse_ok_count": row.get(
                    "worker_task_parse_ok_count", ""
                ),
                "worker_task_parse_partial_count": row.get(
                    "worker_task_parse_partial_count", ""
                ),
                "worker_task_parse_failed_count": row.get(
                    "worker_task_parse_failed_count", ""
                ),
                "result_signature_status": row.get("result_signature_status", ""),
                "result_multiset_sha256": row.get("result_multiset_sha256", ""),
                "database_result_rows_stored": row.get(
                    "database_result_rows_stored", ""
                ),
            }
        )
    return result


def validate(
    executions: list[dict[str, Any]],
    children: dict[str, list[dict[str, Any]]],
    quality: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    execution_ids = [str(row["query_run_id"]) for row in executions]
    duplicate_ids = [
        query_run_id
        for query_run_id, count in Counter(execution_ids).items()
        if count > 1
    ]
    for query_run_id in duplicate_ids:
        errors.append(
            {
                "check_id": "unique_query_run_id",
                "query_run_id": query_run_id,
                "detail": "query_run_id occurs in more than one selected source",
            }
        )

    plan_keys = {
        (str(row.get("query_run_id", "")), str(row.get("plan_id", "")))
        for row in children["plan_files"]
    }
    for table, key in (
        ("fdw_remote_plans", "plan_id"),
        ("region_fragments", "remote_plan_id"),
        ("worker_task_fragments", "plan_id"),
        ("plan_nodes", "parent_plan_id"),
        ("plan_edges", "parent_plan_id"),
    ):
        for row in children[table]:
            plan_key = (
                str(row.get("query_run_id", "")),
                str(row.get(key, "")),
            )
            if plan_key not in plan_keys:
                errors.append(
                    {
                        "check_id": f"{table}_plan_fk",
                        "query_run_id": row.get("query_run_id", ""),
                        "detail": f"{key}={row.get(key, '')} is absent from plan_files",
                    }
                )

    remote_sql_keys = {
        (str(row.get("query_run_id", "")), str(row.get("plan_id", "")))
        for row in children["fdw_remote_plans"]
    }
    for row in children["region_fragments"]:
        key = (
            str(row.get("query_run_id", "")),
            str(row.get("remote_plan_id", "")),
        )
        if key not in remote_sql_keys:
            errors.append(
                {
                    "check_id": "region_fragment_remote_sql_fk",
                    "query_run_id": row.get("query_run_id", ""),
                    "detail": "regional plan has no fdw_remote_plans row",
                }
            )

    for row in children["fdw_remote_plans"]:
        if not str(row.get("remote_sql_text", "")).strip() and not str(
            row.get("remote_sql_file", "")
        ).strip():
            errors.append(
                {
                    "check_id": "remote_sql_available",
                    "query_run_id": row.get("query_run_id", ""),
                    "detail": f"remote SQL unavailable for plan_id={row.get('plan_id', '')}",
                }
            )

    for row in children["plan_files"]:
        source_query_sweep_dir = str(
            row.get("source_query_sweep_dir", "")
        ).strip()
        if not source_query_sweep_dir:
            continue
        source_root = resolve_workspace_path(source_query_sweep_dir)
        for field in (
            "plan_json_file",
            "explain_text_file",
            "explain_text_sql_file",
            "explain_analyze_json_sql_file",
            "remote_sql_file",
        ):
            relative_path = str(row.get(field, "")).strip()
            if not relative_path:
                continue
            if not (source_root / relative_path).exists():
                errors.append(
                    {
                        "check_id": "raw_artifact_path_exists",
                        "query_run_id": row.get("query_run_id", ""),
                        "detail": f"{field} does not resolve: {relative_path}",
                }
            )

    remote_edge_keys: Counter[tuple[str, str]] = Counter(
        (
            str(row.get("query_run_id", "")),
            str(row.get("edge_id", "")),
        )
        for row in children["remote_edge_observations"]
    )
    for (query_run_id, edge_id), count in remote_edge_keys.items():
        if not edge_id:
            errors.append(
                {
                    "check_id": "remote_edge_id_present",
                    "query_run_id": query_run_id,
                    "detail": "remote edge row has no edge_id",
                }
            )
        if count != 1:
            errors.append(
                {
                    "check_id": "remote_edge_key_unique",
                    "query_run_id": query_run_id,
                    "detail": f"edge_id={edge_id} occurs {count} times",
                }
            )

    for row in quality:
        query_run_id = str(row["query_run_id"])
        if row["execution_status"] != "completed":
            errors.append(
                {
                    "check_id": "execution_completed",
                    "query_run_id": query_run_id,
                    "detail": f"status={row['execution_status']}",
                }
            )
        if integer(row["main_plan_count"]) != 1:
            errors.append(
                {
                    "check_id": "exactly_one_main_plan",
                    "query_run_id": query_run_id,
                    "detail": f"main_plan_count={row['main_plan_count']}",
                }
            )
        if row["result_signature_status"] != "completed":
            errors.append(
                {
                    "check_id": "result_signature_completed",
                    "query_run_id": query_run_id,
                    "detail": f"status={row['result_signature_status']}",
                }
            )
        if not str(row["result_multiset_sha256"]).strip():
            errors.append(
                {
                    "check_id": "result_signature_hash_present",
                    "query_run_id": query_run_id,
                    "detail": "stream-only multiset hash is blank",
                }
            )
        if truthy(row["database_result_rows_stored"]):
            errors.append(
                {
                    "check_id": "database_result_rows_not_stored",
                    "query_run_id": query_run_id,
                    "detail": "database result rows were stored",
                }
            )
        if row["collection_family"] == "remote_path":
            edge_count = integer(row["remote_edge_observation_count"])
            if edge_count != 2:
                errors.append(
                    {
                        "check_id": "remote_path_has_two_edges",
                        "query_run_id": query_run_id,
                        "detail": f"remote_edge_observation_count={edge_count}",
                    }
                )
            unavailable = [
                edge
                for edge in children["remote_edge_observations"]
                if edge.get("query_run_id") == query_run_id
                and edge.get("availability_status") != "available"
            ]
            if unavailable:
                errors.append(
                    {
                        "check_id": "remote_edge_observation_available",
                        "query_run_id": query_run_id,
                        "detail": f"unavailable_edge_count={len(unavailable)}",
                    }
                )
        for status_field in (
            "regional_plan_evidence_status",
            "worker_task_evidence_status",
            "worker_task_timing_status",
        ):
            if not str(row.get(status_field, "")).strip():
                errors.append(
                    {
                        "check_id": f"{status_field}_present",
                        "query_run_id": query_run_id,
                        "detail": "status is blank",
                    }
                )
        if row["regional_plan_evidence_status"] == "missing_unexpected":
            errors.append(
                {
                    "check_id": "regional_plan_not_missing",
                    "query_run_id": query_run_id,
                    "detail": "Foreign Scan exists but no correlated regional plan exists",
                }
            )
        if row["regional_plan_evidence_status"] == "available":
            completeness = number(row["remote_region_evidence_completeness"])
            if completeness != 1.0:
                errors.append(
                    {
                        "check_id": "regional_evidence_complete",
                        "query_run_id": query_run_id,
                        "detail": f"completeness={completeness}",
                    }
                )
            if integer(row["indexed_regional_remote_plan_count"]) != integer(
                row["regional_remote_plan_count"]
            ):
                errors.append(
                    {
                        "check_id": "regional_plan_count_matches_child_table",
                        "query_run_id": query_run_id,
                        "detail": (
                            f"indexed={row['indexed_regional_remote_plan_count']} "
                            f"child={row['regional_remote_plan_count']}"
                        ),
                    }
                )
        if row["worker_task_evidence_status"] == "missing_unexpected":
            errors.append(
                {
                    "check_id": "worker_task_not_missing",
                    "query_run_id": query_run_id,
                    "detail": "Citus task evidence was expected but no task rows were parsed",
                }
            )
        if integer(row["worker_task_parse_failed_count"]) > 0:
            errors.append(
                {
                    "check_id": "worker_task_parse_failed",
                    "query_run_id": query_run_id,
                    "detail": (
                        f"failed={row['worker_task_parse_failed_count']}"
                    ),
                }
            )
        if row["worker_task_evidence_status"] == "available":
            child_count = integer(row["worker_task_fragment_count"])
            if integer(row["indexed_worker_task_plan_count"]) != child_count:
                errors.append(
                    {
                        "check_id": "worker_task_count_matches_child_table",
                        "query_run_id": query_run_id,
                        "detail": (
                            f"indexed={row['indexed_worker_task_plan_count']} "
                            f"child={child_count}"
                        ),
                    }
                )
            parsed_count = (
                integer(row["worker_task_parse_ok_count"])
                + integer(row["worker_task_parse_partial_count"])
                + integer(row["worker_task_parse_failed_count"])
            )
            if parsed_count != child_count:
                errors.append(
                    {
                        "check_id": "worker_task_parse_count_complete",
                        "query_run_id": query_run_id,
                        "detail": f"parsed={parsed_count} child={child_count}",
                    }
                )
        if row["worker_task_evidence_status"] == "structurally_unavailable_repartition":
            warnings.append(
                {
                    "check_id": "repartition_task_list_structurally_unavailable",
                    "query_run_id": query_run_id,
                    "detail": "Citus reports Tasks Shown: None for repartition query",
                }
            )
        if row["worker_task_timing_status"] == "unavailable_in_embedded_task_plan":
            warnings.append(
                {
                    "check_id": "worker_task_timing_unavailable",
                    "query_run_id": query_run_id,
                    "detail": "row/byte/operator evidence exists, per-task timing does not",
                }
            )

    internal_plan_keys = {
        (str(row.get("query_run_id", "")), str(row.get("plan_id", "")))
        for row in children["plan_files"]
        if row.get("plan_scope") == "fdw_auto_explain_internal"
    }
    for row in children["region_fragments"]:
        if (
            str(row.get("query_run_id", "")),
            str(row.get("remote_plan_id", "")),
        ) in internal_plan_keys:
            errors.append(
                {
                    "check_id": "internal_plan_not_promoted_to_region",
                    "query_run_id": row.get("query_run_id", ""),
                    "detail": "internal auto_explain statement leaked into region_fragments",
                }
            )

    return errors, warnings


def markdown_report(
    *,
    summary: dict[str, Any],
    schema_rows: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> str:
    source_lines = [
        "| Izvor | Porodica | Vrsta indeksa | Redovi | Kolone | Nedostajuće wrapper kolone |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in schema_rows:
        source_lines.append(
            "| "
            + " | ".join(
                [
                    str(row["source_index_id"]),
                    str(row["collection_family"]),
                    str(row["source_index_kind"]),
                    str(row["selected_execution_count"]),
                    str(row["execution_column_count"]),
                    str(row["missing_from_canonical_count"]),
                ]
            )
            + " |"
        )
    return "\n".join(
        [
            "# Preflight uniformnosti višeslojnih kolekcija",
            "",
            f"**Odluka: {summary['status']}**",
            "",
            "## Obuhvat",
            "",
            *source_lines,
            "",
            "## Centralizovani oblik",
            "",
            f"- izvršenja: `{summary['execution_count']}`",
            f"- regionalni planovi: `{summary['region_fragment_count']}`",
            f"- worker/task fragmenti: `{summary['worker_task_fragment_count']}`",
            f"- udaljeni edge redovi: `{summary['remote_edge_observation_count']}`",
            f"- plan dokumenti: `{summary['plan_file_count']}`",
            (
                "- interni `auto_explain` dokumenti zadržani samo u katalogu: "
                f"`{summary['internal_auto_explain_plan_count']}`"
            ),
            (
                "- remote SQL tekst dostupan: "
                f"`{summary['remote_sql_text_available_count']}/"
                f"{summary['fdw_remote_plan_count']}`"
            ),
            (
                "- worker/task parser: "
                f"`{summary['worker_task_parse_ok_count']}` strukturiranih i "
                f"`{summary['worker_task_parse_partial_count']}` tekstualno "
                "parsiranih fragmenata, bez neuspjeha"
            ),
            (
                "- jedan red u `executions.csv` predstavlja jedno globalno ili direktno "
                "SQL izvršenje"
            ),
            (
                "- udaljeni edge redovi, regionalni planovi i worker/task planovi "
                "ostaju 1:N child tabele povezane stabilnim identitetima"
            ),
            (
                "- Citus worker plan je tekstualni plan ugrađen u JSON dokument "
                "koordinatorskog plana; raw JSON i izvorni auto_explain log ostaju "
                "autoritativni artefakti"
            ),
            "",
            "## Nalaz",
            "",
            (
                f"- greške ugovora: `{len(errors)}`; upozorenja o očekivanoj "
                f"nedostupnosti: `{len(warnings)}`"
            ),
            (
                "- `structurally_unavailable_repartition` znači da Citus namjerno ne "
                "prikazuje task listu za repartition plan; to nije nulta vrijednost"
            ),
            (
                "- `unavailable_in_embedded_task_plan` znači da su dostupni task "
                "redovi/operatori, ali ne i pouzdano per-task vrijeme"
            ),
            (
                "- `partial` je očekivani status za Citus tekstualni task plan: "
                "poznati operatori, redovi i bufferi se izdvajaju uz srednju "
                "pouzdanost, a raw plan ostaje dostupan za ponovnu obradu"
            ),
            (
                "- placement B/C izvori imaju užu query-sweep shemu, ali se u "
                "`executions.csv` proširuju na kanonski union bez izmišljanja vrijednosti"
            ),
            "",
            "## Izlazi",
            "",
            "- `executions.csv`",
            "- `execution_evidence_quality.csv`",
            "- `plan_files.csv`",
            "- `fdw_remote_plans.csv`",
            "- `region_fragments.csv`",
            "- `worker_task_fragments.csv`",
            "- `remote_edge_observations.csv`",
            "- `plan_nodes.csv`",
            "- `plan_edges.csv`",
            "- `analysis_plan_files.csv` i `analysis_plan_nodes.csv` bez internih izjava",
            "- `internal_auto_explain_plan_files.csv` i `internal_auto_explain_plan_nodes.csv`",
            "- `query_bindings.csv`",
            "- `node_artifacts.csv`",
            "- `schema_matrix.csv`",
            "- `errors.csv`",
            "- `warnings.csv`",
            "- `summary.json`",
            "",
            "## Odluka za veliki run",
            "",
            (
                "GO je dozvoljen samo kada nema referencijalnih grešaka, neočekivano "
                "nedostajućih regionalnih/task dokaza ni neuspjelih task parsera."
            ),
            "",
        ]
    )


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    execution_sources, children, schema_rows = load_sources(args.sources.resolve())

    canonical_fields = ordered_union(
        [source["execution_fields"] for source in execution_sources]
    )
    fields_by_source = {
        source["source"]["source_id"]: set(source["execution_fields"])
        for source in execution_sources
    }
    for row in schema_rows:
        source_fields = fields_by_source[str(row["source_index_id"])]
        missing = [field for field in canonical_fields if field not in source_fields]
        row["canonical_execution_column_count"] = len(canonical_fields)
        row["missing_from_canonical_count"] = len(missing)
        row["missing_from_canonical_json"] = json.dumps(missing)
    executions = [
        with_provenance(
            row,
            source=source["source"],
            index_dir=source["index_dir"],
            source_schema_hash=source["schema_hash"],
        )
        for source in execution_sources
        for row in source["rows"]
    ]
    quality = evidence_quality_rows(executions, children)
    errors, warnings = validate(executions, children, quality)

    write_csv(
        out_dir / "executions.csv",
        executions,
        [*PROVENANCE_FIELDS, *canonical_fields],
    )
    write_csv(
        out_dir / "execution_evidence_quality.csv",
        quality,
        list(quality[0]) if quality else [],
    )
    for table, rows in children.items():
        fields = ordered_union([list(row) for row in rows]) if rows else PROVENANCE_FIELDS
        write_csv(out_dir / f"{table}.csv", rows, fields)
    analysis_plan_files = [
        row
        for row in children["plan_files"]
        if row.get("plan_scope") != "fdw_auto_explain_internal"
    ]
    internal_plan_files = [
        row
        for row in children["plan_files"]
        if row.get("plan_scope") == "fdw_auto_explain_internal"
    ]
    analysis_plan_nodes = [
        row
        for row in children["plan_nodes"]
        if row.get("plan_scope") != "fdw_auto_explain_internal"
    ]
    internal_plan_nodes = [
        row
        for row in children["plan_nodes"]
        if row.get("plan_scope") == "fdw_auto_explain_internal"
    ]
    for name, rows in (
        ("analysis_plan_files", analysis_plan_files),
        ("internal_auto_explain_plan_files", internal_plan_files),
        ("analysis_plan_nodes", analysis_plan_nodes),
        ("internal_auto_explain_plan_nodes", internal_plan_nodes),
    ):
        fields = ordered_union([list(row) for row in rows]) if rows else PROVENANCE_FIELDS
        write_csv(out_dir / f"{name}.csv", rows, fields)
    write_csv(out_dir / "schema_matrix.csv", schema_rows, list(schema_rows[0]))
    write_csv(
        out_dir / "errors.csv",
        errors,
        ["check_id", "query_run_id", "detail"],
    )
    write_csv(
        out_dir / "warnings.csv",
        warnings,
        ["check_id", "query_run_id", "detail"],
    )

    summary = {
        "status": "GO" if not errors else "NO_GO",
        "execution_count": len(executions),
        "source_count": len(execution_sources),
        "plan_file_count": len(children["plan_files"]),
        "internal_auto_explain_plan_count": sum(
            row.get("plan_scope") == "fdw_auto_explain_internal"
            for row in children["plan_files"]
        ),
        "fdw_remote_plan_count": len(children["fdw_remote_plans"]),
        "remote_sql_text_available_count": sum(
            bool(str(row.get("remote_sql_text", "")).strip())
            for row in children["fdw_remote_plans"]
        ),
        "region_fragment_count": len(children["region_fragments"]),
        "worker_task_fragment_count": len(children["worker_task_fragments"]),
        "remote_edge_observation_count": len(
            children["remote_edge_observations"]
        ),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "worker_task_parse_ok_count": sum(
            integer(row.get("worker_task_parse_ok_count")) for row in quality
        ),
        "worker_task_parse_partial_count": sum(
            integer(row.get("worker_task_parse_partial_count")) for row in quality
        ),
        "worker_task_parse_failed_count": sum(
            integer(row.get("worker_task_parse_failed_count")) for row in quality
        ),
        "worker_task_evidence_status_counts": dict(
            Counter(row["worker_task_evidence_status"] for row in quality)
        ),
        "worker_task_timing_status_counts": dict(
            Counter(row["worker_task_timing_status"] for row in quality)
        ),
        "regional_plan_evidence_status_counts": dict(
            Counter(row["regional_plan_evidence_status"] for row in quality)
        ),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "README.md").write_text(
        markdown_report(
            summary=summary,
            schema_rows=schema_rows,
            errors=errors,
            warnings=warnings,
        ),
        encoding="utf-8",
    )
    print(out_dir / "README.md")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
