from __future__ import annotations

import csv
import hashlib
import json
import re
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .config import load_yaml, write_yaml

COUNT_QUERY_RE = re.compile(
    r"^\s*SELECT\s+COUNT\s*\(\s*\*\s*\)\s+FROM\s+",
    flags=re.IGNORECASE | re.DOTALL,
)
FROM_RE = re.compile(
    r"\bFROM\b(?P<from>.*?)(?:\bWHERE\b|$)",
    flags=re.IGNORECASE | re.DOTALL,
)
TABLE_RE = re.compile(
    r"(?:^|,)\s*(?P<table>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+(?:AS\s+)?[A-Za-z_][A-Za-z0-9_]*)?",
    flags=re.IGNORECASE,
)
FORBIDDEN_RE = re.compile(
    r"\b(?:GROUP\s+BY|DISTINCT|LIMIT|INSERT|UPDATE|DELETE|COPY)\b",
    flags=re.IGNORECASE,
)
COUNT_SELECT_RE = re.compile(
    r"^\s*SELECT\s+COUNT\s*\(\s*\*\s*\)\s*",
    flags=re.IGNORECASE,
)


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "master-regimes-stats-ceb-admission/1.0"},
    )
    temporary = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as out:
        while block := response.read(1024 * 1024):
            out.write(block)
    temporary.replace(destination)


def ensure_locked_resource(
    *,
    resource: dict[str, Any],
    cache_dir: Path,
    download: bool = True,
) -> dict[str, Any]:
    path = cache_dir / str(resource["filename"])
    if not path.exists():
        if not download:
            return {
                "path": str(path),
                "status": "not_downloaded",
                "expected_sha256": str(resource.get("sha256", "")),
                "expected_md5": str(resource.get("md5", "")),
            }
        _download(str(resource["url"]), path)

    actual_sha256 = file_digest(path, "sha256")
    actual_md5 = file_digest(path, "md5")
    expected_sha256 = str(resource.get("sha256", ""))
    expected_md5 = str(resource.get("md5", ""))
    errors: list[str] = []
    if expected_sha256 and actual_sha256 != expected_sha256:
        errors.append(f"sha256 mismatch: {actual_sha256} != {expected_sha256}")
    if expected_md5 and actual_md5 != expected_md5:
        errors.append(f"md5 mismatch: {actual_md5} != {expected_md5}")
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": actual_sha256,
        "md5": actual_md5,
        "expected_sha256": expected_sha256,
        "expected_md5": expected_md5,
        "errors": errors,
        "status": "ok" if not errors else "error",
    }


def _safe_query_members(archive: zipfile.ZipFile, *, prefix: str) -> list[str]:
    members: list[str] = []
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe ZIP member: {info.filename}")
        if not info.is_dir() and info.filename.startswith(prefix) and path.suffix == ".sql":
            members.append(info.filename)
    return sorted(members)


def _parse_expected_results(path: Path) -> dict[int, tuple[int, str]]:
    results: dict[int, tuple[int, str]] = {}
    for query_id, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        expected_text, separator, sql = line.partition("||")
        if not separator:
            raise ValueError(f"Malformed expected-results line {query_id}")
        results[query_id] = (int(expected_text), sql.strip())
    return results


def _tables(sql: str) -> list[str]:
    match = FROM_RE.search(sql)
    if not match:
        return []
    return sorted(
        {
            table_match.group("table").lower()
            for table_match in TABLE_RE.finditer(match.group("from"))
        }
    )


def _normalized_sql(sql: str) -> str:
    return " ".join(sql.strip().rstrip(";").split()).lower()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(rows)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fragment_sql(sql: str) -> str:
    match = FROM_RE.search(sql)
    if not match:
        raise ValueError("STATS-CEB query has no FROM clause")
    from_clause = match.group("from")
    replacements = [
        (table_match.start("table"), table_match.end("table"))
        for table_match in TABLE_RE.finditer(from_clause)
    ]
    if not replacements:
        raise ValueError("STATS-CEB query has no parsed tables")
    for start, end in reversed(replacements):
        from_clause = (
            from_clause[:start]
            + "{{ schema_name }}."
            + from_clause[start:end]
            + from_clause[end:]
        )
    rendered = sql[: match.start("from")] + from_clause + sql[match.end("from") :]
    rendered = COUNT_SELECT_RE.sub(
        "select count(*) as result_count\n",
        rendered,
        count=1,
    )
    return rendered.strip().rstrip(";") + "\n"


def prepare_holdout_selection(
    *,
    source_lock_path: Path,
    development_selection_path: Path,
    cache_dir: Path,
    selection_path: Path,
    selected_query_dir: Path,
    fragments_dir: Path,
    seed: str,
    table_count_quotas: dict[int, int],
    excluded_selection_paths: list[Path] | None = None,
    selection_id: str = "stats-ceb-semantic-v2-holdout",
) -> Path:
    """Materialize a deterministic STATS-CEB holdout without outcome inspection."""
    source_lock_path = source_lock_path.resolve()
    development_selection_path = development_selection_path.resolve()
    source_lock = load_yaml(source_lock_path)
    development_selection = load_yaml(development_selection_path)
    excluded_selections = [
        load_yaml(path.resolve()) for path in (excluded_selection_paths or [])
    ]
    resources = source_lock.get("resources") or {}

    query_resource = resources.get("queries")
    expected_resource = resources.get("expected_results")
    if not isinstance(query_resource, dict) or not isinstance(expected_resource, dict):
        raise ValueError("Source lock must define queries and expected_results resources")
    query_audit = ensure_locked_resource(
        resource=query_resource,
        cache_dir=cache_dir,
    )
    expected_audit = ensure_locked_resource(
        resource=expected_resource,
        cache_dir=cache_dir,
    )
    if query_audit["status"] != "ok" or expected_audit["status"] != "ok":
        raise ValueError("Pinned STATS-CEB query sources failed integrity validation")

    expected_results = _parse_expected_results(Path(str(expected_audit["path"])))
    archive_prefix = str(
        (source_lock.get("contracts") or {}).get("query_archive_prefix", "stats/")
    )
    development_ids = {
        int(item["query_id"])
        for item in development_selection.get("queries", [])
    }
    for excluded_selection in excluded_selections:
        development_ids.update(
            int(item["query_id"])
            for item in excluded_selection.get("queries", [])
        )
    candidates: dict[int, list[dict[str, Any]]] = {
        int(table_count): [] for table_count in table_count_quotas
    }
    archive_path = Path(str(query_audit["path"]))
    with zipfile.ZipFile(archive_path) as archive:
        for member in _safe_query_members(archive, prefix=archive_prefix):
            match = re.fullmatch(
                re.escape(archive_prefix) + r"q-(?P<query_id>\d+)\.sql",
                member,
            )
            if not match:
                continue
            query_id = int(match.group("query_id"))
            if query_id in development_ids:
                continue
            sql = archive.read(member).decode("utf-8")
            tables = _tables(sql)
            table_count = len(tables)
            if (
                table_count not in candidates
                or not COUNT_QUERY_RE.search(sql)
                or FORBIDDEN_RE.search(sql)
            ):
                continue
            candidates[table_count].append(
                {
                    "query_id": query_id,
                    "sql": sql,
                    "tables": tables,
                    "selection_hash": hashlib.sha256(
                        f"{seed}:{query_id}".encode()
                    ).hexdigest(),
                }
            )

    selected: list[dict[str, Any]] = []
    for table_count, quota in sorted(table_count_quotas.items()):
        ranked = sorted(
            candidates.get(int(table_count), []),
            key=lambda item: (str(item["selection_hash"]), int(item["query_id"])),
        )
        if len(ranked) < int(quota):
            raise ValueError(
                f"Only {len(ranked)} eligible {table_count}-table queries for quota {quota}"
            )
        selected.extend(ranked[: int(quota)])

    selected_query_dir.mkdir(parents=True, exist_ok=True)
    fragments_dir.mkdir(parents=True, exist_ok=True)
    query_rows: list[dict[str, Any]] = []
    for item in selected:
        query_id = int(item["query_id"])
        sql = str(item["sql"]).strip() + "\n"
        expected = expected_results.get(query_id)
        if expected is None:
            raise ValueError(f"Missing pinned expected result for q-{query_id}")
        query_path = selected_query_dir / f"q-{query_id}.sql"
        fragment_path = fragments_dir / f"q-{query_id}.sql.j2"
        query_path.write_text(sql, encoding="utf-8")
        fragment_path.write_text(_fragment_sql(sql), encoding="utf-8")
        query_rows.append(
            {
                "query_id": query_id,
                "expected_count": int(expected[0]),
                "source_sha256": file_digest(query_path, "sha256"),
                "expected_citus_strategy": "not_used_for_holdout_selection",
                "tables": item["tables"],
                "table_count_stratum": len(item["tables"]),
                "selection_hash": item["selection_hash"],
                "reason": (
                    "Deterministic hash-ranked holdout selected before execution; "
                    "runtime, expected count and model behavior were not selection inputs."
                ),
            }
        )

    selection = {
        "selection_id": selection_id,
        "source_lock": str(source_lock_path.name),
        "selection_frozen_before_plan_execution": True,
        "selection_rationale": (
            "Previously unexecuted scalar COUNT queries selected by a fixed SHA-256 "
            "seed within table-count strata. Expected result values are attached only "
            "after selection and are not ranking inputs."
        ),
        "selection_method": {
            "algorithm": "sha256(seed:query_id), ascending within table_count",
            "seed": seed,
            "table_count_quotas": {
                int(key): int(value) for key, value in sorted(table_count_quotas.items())
            },
            "excluded_development_query_ids": sorted(development_ids),
            "outcome_fields_used_for_selection": [],
        },
        "regional_semantics": development_selection["regional_semantics"],
        "physical_design": development_selection["physical_design"],
        "queries": query_rows,
        "execution_contract": {
            "statement_timeout_seconds": 300,
            "explain_without_analyze_first": True,
            "keep_failed_queries": True,
            "statuses": [
                "passed",
                "unsupported_sql",
                "result_mismatch",
                "timeout",
                "incomplete_topology_evidence",
                "feature_contract_failure",
                "infrastructure_failure",
            ],
        },
        "result_contract": development_selection["result_contract"],
        "model_contract": {
            "model_id": "semantic-v2-transfer-oriented-fcm",
            "refit_allowed": False,
            "feature_schema_change_allowed": False,
            "projection_role": "confirmatory_external_holdout",
            "ood_rule": "nearest_center_distance_above_frozen_baseline_p99",
            "post_observation_contract_changes_allowed": False,
        },
    }
    write_yaml(selection_path, selection)
    return selection_path.resolve()


def prepare_full_selection(
    *,
    source_lock_path: Path,
    development_selection_path: Path,
    cache_dir: Path,
    selection_path: Path,
    selected_query_dir: Path,
    fragments_dir: Path,
    selection_id: str = "stats-ceb-full-no-refit-v1",
) -> Path:
    """Materialize every pinned, locally compatible STATS-CEB query."""
    source_lock_path = source_lock_path.resolve()
    development_selection_path = development_selection_path.resolve()
    source_lock = load_yaml(source_lock_path)
    development_selection = load_yaml(development_selection_path)
    resources = source_lock.get("resources") or {}
    contracts = source_lock.get("contracts") or {}

    query_resource = resources.get("queries")
    expected_resource = resources.get("expected_results")
    if not isinstance(query_resource, dict) or not isinstance(expected_resource, dict):
        raise ValueError("Source lock must define queries and expected_results resources")
    query_audit = ensure_locked_resource(resource=query_resource, cache_dir=cache_dir)
    expected_audit = ensure_locked_resource(
        resource=expected_resource,
        cache_dir=cache_dir,
    )
    if query_audit["status"] != "ok" or expected_audit["status"] != "ok":
        raise ValueError("Pinned STATS-CEB query sources failed integrity validation")

    expected_results = _parse_expected_results(Path(str(expected_audit["path"])))
    archive_prefix = str(contracts.get("query_archive_prefix", "stats/"))
    expected_query_count = int(contracts.get("archive_query_count", 0))
    archive_path = Path(str(query_audit["path"]))
    selected_query_dir.mkdir(parents=True, exist_ok=True)
    fragments_dir.mkdir(parents=True, exist_ok=True)
    query_rows: list[dict[str, Any]] = []

    with zipfile.ZipFile(archive_path) as archive:
        members = _safe_query_members(archive, prefix=archive_prefix)
        for member in members:
            match = re.fullmatch(
                re.escape(archive_prefix) + r"q-(?P<query_id>\d+)\.sql",
                member,
            )
            if not match:
                raise ValueError(f"Unexpected STATS-CEB query member: {member}")
            query_id = int(match.group("query_id"))
            sql = archive.read(member).decode("utf-8").strip() + "\n"
            if not COUNT_QUERY_RE.search(sql) or FORBIDDEN_RE.search(sql):
                raise ValueError(f"q-{query_id} is not locally compatible")
            published = expected_results.get(query_id)
            if published is None:
                raise ValueError(f"Missing pinned expected result for q-{query_id}")

            query_path = selected_query_dir / f"q-{query_id}.sql"
            fragment_path = fragments_dir / f"q-{query_id}.sql.j2"
            query_path.write_text(sql, encoding="utf-8")
            fragment_path.write_text(_fragment_sql(sql), encoding="utf-8")
            tables = _tables(sql)
            query_rows.append(
                {
                    "query_id": query_id,
                    "expected_count": int(published[0]),
                    "source_sha256": file_digest(query_path, "sha256"),
                    "expected_citus_strategy": "observed_not_preregistered",
                    "tables": tables,
                    "table_count_stratum": len(tables),
                    "selection_hash": hashlib.sha256(
                        f"{selection_id}:{query_id}".encode()
                    ).hexdigest(),
                    "reason": (
                        "Complete pinned STATS-CEB workload member. Inclusion does "
                        "not depend on runtime, result, plan or model behavior."
                    ),
                }
            )

    query_rows.sort(key=lambda item: int(item["query_id"]))
    if len(query_rows) != expected_query_count:
        raise ValueError(
            f"Prepared {len(query_rows)} queries; expected {expected_query_count}"
        )
    if [int(item["query_id"]) for item in query_rows] != list(
        range(1, expected_query_count + 1)
    ):
        raise ValueError("Full STATS-CEB selection must contain query IDs 1..146")

    selection = {
        "selection_id": selection_id,
        "source_lock": str(source_lock_path.name),
        "selection_frozen_before_plan_execution": True,
        "selection_rationale": (
            "Complete locally compatible workload from the pinned STATS-CEB "
            "archive. No query is selected or excluded using runtime, result, "
            "plan, distance, membership or OOD behavior."
        ),
        "selection_method": {
            "algorithm": "all pinned archive members ordered by query_id",
            "archive_query_count": expected_query_count,
            "included_query_count": len(query_rows),
            "outcome_fields_used_for_selection": [],
            "technical_exclusions": [],
        },
        "regional_semantics": development_selection["regional_semantics"],
        "physical_design": development_selection["physical_design"],
        "queries": query_rows,
        "execution_contract": {
            "statement_timeout_seconds": 300,
            "explain_without_analyze_first": True,
            "keep_failed_queries": True,
            "statuses": [
                "passed",
                "unsupported_sql",
                "result_mismatch",
                "timeout",
                "incomplete_topology_evidence",
                "feature_contract_failure",
                "infrastructure_failure",
            ],
        },
        "result_contract": development_selection["result_contract"],
        "model_contract": {
            "model_id": "semantic-v2-transfer-oriented-fcm",
            "refit_allowed": False,
            "feature_schema_change_allowed": False,
            "projection_role": "external_full_workload_no_refit_audit",
            "ood_rule": "nearest_center_distance_above_frozen_baseline_p99",
            "post_observation_contract_changes_allowed": False,
        },
    }
    write_yaml(selection_path, selection)
    return selection_path.resolve()


def run_admission_gate(
    *,
    source_lock_path: Path,
    selection_path: Path,
    cache_dir: Path,
    out_dir: Path,
) -> Path:
    source_lock_path = source_lock_path.resolve()
    selection_path = selection_path.resolve()
    source_lock = load_yaml(source_lock_path)
    selection = load_yaml(selection_path)
    resources = source_lock.get("resources") or {}
    errors: list[str] = []

    resource_audits: dict[str, dict[str, Any]] = {}
    for resource_id in ("queries", "schema", "expected_results"):
        resource = resources.get(resource_id)
        if not isinstance(resource, dict):
            errors.append(f"Missing source resource: {resource_id}")
            continue
        audit = ensure_locked_resource(resource=resource, cache_dir=cache_dir)
        resource_audits[resource_id] = audit
        errors.extend(f"{resource_id}: {message}" for message in audit.get("errors", []))

    dump = resources.get("dump")
    if isinstance(dump, dict):
        resource_audits["dump"] = ensure_locked_resource(
            resource=dump,
            cache_dir=cache_dir,
            download=False,
        )
    else:
        errors.append("Missing source resource: dump")

    contracts = source_lock.get("contracts") or {}
    archive_query_count = int(contracts.get("archive_query_count", 0))
    archive_prefix = str(contracts.get("query_archive_prefix", "stats/"))
    query_audit = resource_audits.get("queries", {})
    expected_audit = resource_audits.get("expected_results", {})
    archive_members: list[str] = []
    expected_results: dict[int, tuple[int, str]] = {}
    if query_audit.get("status") == "ok":
        with zipfile.ZipFile(Path(str(query_audit["path"]))) as archive:
            archive_members = _safe_query_members(archive, prefix=archive_prefix)
        if len(archive_members) != archive_query_count:
            errors.append(
                f"Query archive contains {len(archive_members)} SQL files; "
                f"expected {archive_query_count}"
            )
    if expected_audit.get("status") == "ok":
        expected_results = _parse_expected_results(Path(str(expected_audit["path"])))
        if len(expected_results) != archive_query_count:
            errors.append(
                f"Expected-results source contains {len(expected_results)} entries; "
                f"expected {archive_query_count}"
            )

    selected_dir = selection_path.parent / "selected-queries"
    rows: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    selection_queries = selection.get("queries") or []
    if not isinstance(selection_queries, list) or not selection_queries:
        errors.append("Selection must contain a non-empty queries list")
        selection_queries = []
    for item in selection_queries:
        query_errors: list[str] = []
        query_id = int(item["query_id"])
        if query_id in selected_ids:
            query_errors.append("duplicate query_id")
        selected_ids.add(query_id)
        local_path = selected_dir / f"q-{query_id}.sql"
        if not local_path.exists():
            query_errors.append("selected SQL file missing")
            sql = ""
            actual_sha256 = ""
        else:
            sql = local_path.read_text(encoding="utf-8")
            actual_sha256 = file_digest(local_path, "sha256")
        expected_sha256 = str(item.get("source_sha256", ""))
        if actual_sha256 and actual_sha256 != expected_sha256:
            query_errors.append("selected SQL sha256 mismatch")
        if sql and not COUNT_QUERY_RE.search(sql):
            query_errors.append("query is not a scalar COUNT(*) query")
        if sql and FORBIDDEN_RE.search(sql):
            query_errors.append("query contains a forbidden statement/shape")
        actual_tables = _tables(sql)
        declared_tables = sorted(str(value).lower() for value in item.get("tables", []))
        if actual_tables != declared_tables:
            query_errors.append(
                f"table set mismatch: {actual_tables} != {declared_tables}"
            )
        published = expected_results.get(query_id)
        published_count = published[0] if published else None
        if published_count != int(item.get("expected_count", -1)):
            query_errors.append(
                f"published count mismatch: {published_count} != {item.get('expected_count')}"
            )
        archive_member = f"{archive_prefix}q-{query_id}.sql"
        if archive_member not in archive_members:
            query_errors.append(f"archive member missing: {archive_member}")
        elif query_audit.get("status") == "ok" and sql:
            with zipfile.ZipFile(Path(str(query_audit["path"]))) as archive:
                archived_sql = archive.read(archive_member).decode("utf-8")
            if _normalized_sql(sql) != _normalized_sql(archived_sql):
                query_errors.append("selected SQL differs from pinned archive SQL")

        rows.append(
            {
                "query_id": query_id,
                "expected_citus_strategy": item.get("expected_citus_strategy", ""),
                "table_count": len(actual_tables),
                "tables": ",".join(actual_tables),
                "expected_count": item.get("expected_count", ""),
                "source_sha256": actual_sha256,
                "scalar_count_query": str(bool(sql and COUNT_QUERY_RE.search(sql))).lower(),
                "forbidden_construct_present": str(
                    bool(sql and FORBIDDEN_RE.search(sql))
                ).lower(),
                "status": "ok" if not query_errors else "error",
                "errors": " | ".join(query_errors),
            }
        )
        errors.extend(f"q-{query_id}: {message}" for message in query_errors)

    source_audit = {
        "source_id": source_lock.get("source_id", ""),
        "record_url": source_lock.get("record_url", ""),
        "doi": source_lock.get("doi", ""),
        "license": source_lock.get("license", ""),
        "resources": resource_audits,
        "archive_query_count": len(archive_members),
        "expected_result_count": len(expected_results),
        "selected_query_count": len(rows),
        "errors": errors,
        "status": "go" if not errors else "no_go",
    }
    go_no_go = {
        "gate_id": "stats-ceb-local-admission-v1",
        "selection_id": selection.get("selection_id", ""),
        "decision": "GO" if not errors else "NO-GO",
        "selected_query_count": len(rows),
        "source_integrity": "pass" if not errors else "fail",
        "dump_downloaded": resource_audits.get("dump", {}).get("status") == "ok",
        "dump_policy": "download only during explicit infrastructure prepare",
        "frozen_model_refit_allowed": False,
        "errors": errors,
    }
    _write_csv(out_dir / "phase0_query_audit.csv", rows)
    _write_json(out_dir / "source_audit.json", source_audit)
    _write_json(out_dir / "go_no_go.json", go_no_go)
    return out_dir.resolve()
