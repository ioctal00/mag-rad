from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from master_regimes.extract.query_sweep_index import index_query_sweep

csv.field_size_limit(sys.maxsize)

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_PROGRAM = REPO_ROOT / "generated/corpus/pressure-raw-v1/pressure_raw_program.yml"
DEFAULT_STATE_ROOT = REPO_ROOT / "generated/pressure-raw-runs"
DEFAULT_OUT = DEFAULT_STATE_ROOT / "_program/pressure-raw-v1"
REGIONAL_EXECUTION_AGGREGATE_FIELDS = (
    "regional_temp_evidence_region_count",
    "regional_temp_read_blocks_sum",
    "regional_temp_read_blocks_max",
    "regional_temp_written_blocks_sum",
    "regional_temp_written_blocks_max",
    "regional_spill_region_count",
    "regional_spill_present",
)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def resolve(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def csv_fields(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def merged_fields(
    rows: Iterable[dict[str, Any]],
    preferred: Iterable[str] = (),
) -> list[str]:
    result = list(preferred)
    seen = set(result)
    for row in rows:
        for field in row:
            if field.startswith("_") or field in seen:
                continue
            seen.add(field)
            result.append(field)
    return result


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    preferred: Iterable[str] = (),
) -> None:
    fields = merged_fields(rows, preferred)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def enrich_execution_features_from_regions(index_dir: Path) -> int:
    """Project regional temp evidence into the one-row-per-execution table."""
    region_path = index_dir / "region_fragments.csv"
    execution_path = index_dir / "execution_features.csv"
    if not region_path.exists() or not execution_path.exists():
        return 0

    by_query: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: {"read": [], "written": []})
    )
    with region_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            query_run_id = str(row.get("query_run_id", ""))
            region_id = str(row.get("region_id", "")) or "__unknown__"
            if not query_run_id:
                continue
            read_value = float_or_none(row.get("remote_temp_blocks_read"))
            written_value = float_or_none(row.get("remote_temp_blocks_written"))
            if read_value is not None:
                by_query[query_run_id][region_id]["read"].append(read_value)
            if written_value is not None:
                by_query[query_run_id][region_id]["written"].append(written_value)

    aggregates: dict[str, dict[str, Any]] = {}
    for query_run_id, regions in by_query.items():
        regional_reads: list[float] = []
        regional_writes: list[float] = []
        spill_count = 0
        for values in regions.values():
            if not values["read"] and not values["written"]:
                continue
            read_sum = sum(values["read"])
            written_sum = sum(values["written"])
            regional_reads.append(read_sum)
            regional_writes.append(written_sum)
            if read_sum > 0.0 or written_sum > 0.0:
                spill_count += 1
        if not regional_reads and not regional_writes:
            continue
        aggregates[query_run_id] = {
            "regional_temp_evidence_region_count": max(
                len(regional_reads),
                len(regional_writes),
            ),
            "regional_temp_read_blocks_sum": sum(regional_reads),
            "regional_temp_read_blocks_max": max(regional_reads, default=0.0),
            "regional_temp_written_blocks_sum": sum(regional_writes),
            "regional_temp_written_blocks_max": max(regional_writes, default=0.0),
            "regional_spill_region_count": spill_count,
            "regional_spill_present": "true" if spill_count > 0 else "false",
        }

    temporary = execution_path.with_suffix(".csv.tmp")
    enriched_count = 0
    with execution_path.open(newline="", encoding="utf-8") as source_handle:
        reader = csv.DictReader(source_handle)
        fields = list(reader.fieldnames or [])
        fields.extend(
            field for field in REGIONAL_EXECUTION_AGGREGATE_FIELDS if field not in fields
        )
        with temporary.open("w", newline="", encoding="utf-8") as target_handle:
            writer = csv.DictWriter(target_handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in reader:
                values = aggregates.get(str(row.get("query_run_id", "")))
                if values:
                    row.update(values)
                    enriched_count += 1
                writer.writerow({field: row.get(field, "") for field in fields})
    temporary.replace(execution_path)
    return enriched_count


def consolidate_program_hardware(
    *,
    state_root: Path,
    batch_ids: set[str],
    index_dir: Path,
) -> int:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for batch_id in sorted(batch_ids):
        pattern = state_root / batch_id / "run/hardware-snapshots"
        for source in sorted(pattern.glob("*/hardware_nodes.csv")):
            source_rows, _ = read_csv(source)
            for row in source_rows:
                snapshot_id = str(row.get("snapshot_id", ""))
                node_name = str(row.get("node_name", ""))
                key = (batch_id, snapshot_id, node_name)
                if key in seen:
                    continue
                seen.add(key)
                output = dict(row)
                output["batch_id"] = batch_id
                output["hardware_snapshot_dir"] = str(source.parent)
                for field in ("summary_file", "raw_file"):
                    relative = str(output.get(field, ""))
                    if relative:
                        output[field] = str((source.parent / relative).resolve())
                rows.append(output)
    write_csv(
        index_dir / "program_hardware_nodes.csv",
        rows,
        ("batch_id", "snapshot_id", "node_name", "groups", "ansible_host"),
    )
    return len(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def batch_roles(program: dict[str, Any]) -> dict[str, str]:
    policy = program.get("consolidation_policy") or {}
    kind_roles = policy.get("role_by_batch_kind") or {}
    result: dict[str, str] = {}
    batches = [
        program.get("smoke_batch") or {},
        *(program.get("rendered_batches") or []),
        *(program.get("prepared_batches") or []),
    ]
    for batch in batches:
        batch_id = str(batch.get("batch_id", ""))
        kind = str(batch.get("kind", ""))
        if batch_id and kind in kind_roles:
            result[batch_id] = str(kind_roles[kind])
    for batch_id, role in (policy.get("external_batch_roles") or {}).items():
        result[str(batch_id)] = str(role)
    return result


def expected_primary_rows(
    program: dict[str, Any],
    matrix_rows: list[dict[str, str]],
    roles: dict[str, str],
) -> list[dict[str, str]]:
    primary_batches = {batch_id for batch_id, role in roles.items() if role == "primary"}
    return [row for row in matrix_rows if str(row.get("batch_id", "")) in primary_batches]


def attempt_number(event: dict[str, Any], collection_dir: Path) -> int:
    for value in (
        event.get("program_attempt_id"),
        event.get("attempt_id"),
        str(collection_dir),
    ):
        matches = re.findall(r"attempt-(\d+)", str(value or ""))
        if matches:
            return int(matches[-1])
    return 0


def query_run_hint(collection_dir: Path) -> str:
    manifest = load_json(collection_dir / "execution_manifest.json")
    return str(manifest.get("query_run_id") or manifest.get("attempt_id") or collection_dir.name)


def index_candidates(collection_dir: Path) -> list[Path]:
    result: list[Path] = []
    for ancestor in (collection_dir, *collection_dir.parents):
        candidate = ancestor / "_index"
        if (candidate / "query_runs.csv").exists():
            result.append(candidate.resolve())
        if ancestor == WORKSPACE_ROOT:
            break
    return result


def partial_query_sweep(collection_dir: Path) -> Path | None:
    for ancestor in collection_dir.parents:
        if (ancestor / "query_sweep_manifest.json").is_file():
            return ancestor
        if ancestor == WORKSPACE_ROOT:
            break
    return None


def resolve_source_index(
    *,
    collection_dir: Path,
    execution_slot_id: str,
    query_cache: dict[Path, list[dict[str, str]]],
) -> tuple[Path | None, dict[str, str] | None, str]:
    hint = query_run_hint(collection_dir)
    matches: list[tuple[int, Path, dict[str, str]]] = []
    for materialize_partial in (False, True):
        for index_dir in index_candidates(collection_dir):
            if index_dir not in query_cache:
                query_cache[index_dir] = read_csv(index_dir / "query_runs.csv")[0]
            rows = query_cache[index_dir]
            exact = [row for row in rows if str(row.get("query_run_id", "")) == hint]
            if not exact:
                exact = [
                    row
                    for row in rows
                    if str(row.get("execution_slot_id", "")) == execution_slot_id
                    and str(row.get("collection_dir", ""))
                    in {
                        collection_dir.name,
                        f"query-collections/{collection_dir.name}",
                        str(collection_dir),
                    }
                ]
            for row in exact:
                score = len(list(index_dir.glob("*.csv")))
                matches.append((score, index_dir, row))
        if matches or materialize_partial:
            break
        sweep_dir = partial_query_sweep(collection_dir)
        if sweep_dir is None:
            break
        try:
            generated_index = index_query_sweep(sweep_dir=sweep_dir)
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            return (
                None,
                None,
                f"partial_sweep_index_failed:{type(error).__name__}:{error}",
            )
        query_cache.pop(generated_index.resolve(), None)
    if not matches:
        return None, None, "query_not_found_in_ancestor_indexes"
    best_score = max(item[0] for item in matches)
    best = [item for item in matches if item[0] == best_score]
    unique = {
        (
            str(index_dir),
            str(row.get("query_run_id", "")),
        )
        for _, index_dir, row in best
    }
    if len(unique) != 1:
        return None, None, "ambiguous_best_source_index"
    _, index_dir, row = best[0]
    return index_dir, row, ""


def discover_candidates(
    *,
    program: dict[str, Any],
    state_root: Path,
    roles: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    issues: list[str] = []
    query_cache: dict[Path, list[dict[str, str]]] = {}
    for status_path in sorted(state_root.glob("*/run/status.json")):
        state = load_json(status_path)
        batch_id = str(state.get("batch_id") or status_path.parents[1].name)
        role = roles.get(batch_id, "")
        if not role:
            issues.append(f"unknown_batch:{batch_id}")
            continue
        if str(state.get("program_id", "")) != str(program.get("program_id", "")):
            issues.append(f"program_id_mismatch:{batch_id}")
            continue
        checkpoint_dir = status_path.parent / "checkpoints"
        for checkpoint_path in sorted(checkpoint_dir.glob("*.jsonl")):
            for line_number, raw_line in enumerate(
                checkpoint_path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if not raw_line.strip():
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError:
                    issues.append(f"invalid_checkpoint_json:{checkpoint_path}:{line_number}")
                    continue
                if event.get("status") != "completed":
                    continue
                slot_id = str(event.get("execution_slot_id", ""))
                collection_dir = Path(str(event.get("collection_dir", "")))
                candidate: dict[str, Any] = {
                    "program_id": program.get("program_id", ""),
                    "source_batch_id": batch_id,
                    "segment_id": (event.get("segment_id") or checkpoint_path.stem),
                    "consolidation_role": role,
                    "training_eligible": role == "primary",
                    "execution_slot_id": slot_id,
                    "pair_id": event.get("pair_id", ""),
                    "repeat_id": event.get("repeat_id", ""),
                    "program_attempt_id": (
                        event.get("program_attempt_id") or event.get("attempt_id") or ""
                    ),
                    "attempt_number": attempt_number(
                        event,
                        collection_dir,
                    ),
                    "completed_at_utc": event.get("completed_at_utc", ""),
                    "collection_dir": str(collection_dir),
                    "checkpoint_file": str(checkpoint_path.resolve()),
                    "checkpoint_line": line_number,
                    "candidate_valid": False,
                    "invalid_reason": "",
                    "disposition": "",
                }
                invalid: list[str] = []
                if not slot_id:
                    invalid.append("missing_execution_slot_id")
                if event.get("program_id") not in {
                    None,
                    "",
                    program.get("program_id"),
                }:
                    invalid.append("checkpoint_program_id_mismatch")
                if event.get("batch_id") not in {None, "", batch_id}:
                    invalid.append("checkpoint_batch_id_mismatch")
                if not collection_dir.exists():
                    invalid.append("missing_collection_dir")
                if not invalid:
                    index_dir, query_row, index_error = resolve_source_index(
                        collection_dir=collection_dir,
                        execution_slot_id=slot_id,
                        query_cache=query_cache,
                    )
                    if index_error:
                        invalid.append(index_error)
                    elif query_row is not None and index_dir is not None:
                        if str(query_row.get("execution_status", "")) != "completed":
                            invalid.append("indexed_query_not_completed")
                        indexed_slot = str(query_row.get("execution_slot_id", ""))
                        if indexed_slot and indexed_slot != slot_id:
                            invalid.append("indexed_execution_slot_id_mismatch")
                        candidate.update(
                            {
                                "query_run_id": query_row.get(
                                    "query_run_id",
                                    "",
                                ),
                                "instance_id": query_row.get(
                                    "instance_id",
                                    "",
                                ),
                                "indexed_batch_id": query_row.get(
                                    "batch_id",
                                    "",
                                ),
                                "source_index_dir": str(index_dir),
                                "_query_row": query_row,
                            }
                        )
                candidate["invalid_reason"] = ",".join(invalid)
                candidate["candidate_valid"] = not invalid
                candidates.append(candidate)
    return candidates, issues


def resolve_attempts(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[
            (
                str(candidate.get("source_batch_id", "")),
                str(candidate.get("segment_id", "")),
                str(candidate.get("execution_slot_id", "")),
            )
        ].append(candidate)
    selected: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for group in grouped.values():
        valid = [row for row in group if row.get("candidate_valid") is True]
        winner = (
            max(
                valid,
                key=lambda row: (
                    str(row.get("completed_at_utc", "")),
                    int(row.get("attempt_number", 0)),
                    int(row.get("checkpoint_line", 0)),
                ),
            )
            if valid
            else None
        )
        for row in group:
            if row is winner:
                row["disposition"] = (
                    "selected_primary"
                    if row.get("training_eligible")
                    else "selected_nontraining_role"
                )
                selected.append(row)
            elif row.get("candidate_valid"):
                row["disposition"] = "superseded_successful_attempt"
                exclusions.append(row)
            else:
                row["disposition"] = "invalid_candidate"
                exclusions.append(row)
        if winner is not None and not winner.get("training_eligible"):
            exclusions.append(
                {
                    **winner,
                    "disposition": "excluded_from_training_by_role",
                }
            )
    return selected, exclusions


def duplicate_audit(
    selected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    primary = [row for row in selected if row.get("training_eligible") is True]
    for field in ("execution_slot_id", "query_run_id"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in primary:
            grouped[str(row.get(field, ""))].append(row)
        for value, rows in grouped.items():
            if value and len(rows) > 1:
                issues.append(
                    {
                        "issue": f"duplicate_primary_{field}",
                        "value": value,
                        "count": len(rows),
                        "source_batch_ids": ",".join(
                            sorted({str(row.get("source_batch_id", "")) for row in rows})
                        ),
                        "query_run_ids": ",".join(
                            sorted({str(row.get("query_run_id", "")) for row in rows})
                        ),
                    }
                )
    return issues


def training_view(
    *,
    selected: list[dict[str, Any]],
    matrix_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, str]]]:
    matrix_by_slot = {str(row.get("execution_slot_id", "")): row for row in matrix_rows}
    result: list[dict[str, Any]] = []
    issues: list[str] = []
    identity_aliases: list[dict[str, str]] = []
    for row in selected:
        if row.get("training_eligible") is not True:
            continue
        slot_id = str(row.get("execution_slot_id", ""))
        planned = matrix_by_slot.get(slot_id)
        if planned is None:
            issues.append(f"primary_slot_missing_from_matrix:{slot_id}")
            continue
        if str(planned.get("batch_id", "")) != str(row.get("source_batch_id", "")):
            issues.append(f"primary_slot_batch_mismatch:{slot_id}")
            continue
        observed_pair_id = str(row.get("pair_id", ""))
        observed_repeat_id = str(row.get("repeat_id", ""))
        planned_pair_id = str(planned.get("pair_id", ""))
        planned_repeat_id = str(planned.get("repeat_id", ""))
        mismatched_identity_fields = [
            field
            for field, observed_value, planned_value in (
                ("pair_id", observed_pair_id, planned_pair_id),
                ("repeat_id", observed_repeat_id, planned_repeat_id),
            )
            if observed_value and observed_value != planned_value
        ]
        if mismatched_identity_fields:
            repetition_index = str(planned.get("repetition_index", ""))
            placement_alias_valid = (
                str(planned.get("backend", "")) == "placement_aware_worker"
                and observed_pair_id.startswith("pair-")
                and planned_pair_id.startswith("pair-")
                and observed_repeat_id == f"{observed_pair_id}::r{repetition_index}"
                and planned_repeat_id == f"{planned_pair_id}::r{repetition_index}"
            )
            if not placement_alias_valid:
                for identity_field in mismatched_identity_fields:
                    issues.append(f"primary_{identity_field}_mismatch:{slot_id}")
                continue
            identity_aliases.append(
                {
                    "execution_slot_id": slot_id,
                    "backend": "placement_aware_worker",
                    "planned_pair_id": planned_pair_id,
                    "observed_pair_id": observed_pair_id,
                    "planned_repeat_id": planned_repeat_id,
                    "observed_repeat_id": observed_repeat_id,
                    "resolution": "canonicalized_to_execution_matrix",
                }
            )
        indexed_batch = str(row.get("indexed_batch_id", ""))
        if indexed_batch and indexed_batch != str(row.get("source_batch_id", "")):
            issues.append(f"primary_indexed_batch_mismatch:{slot_id}")
            continue
        query_row = row.get("_query_row") or {}
        result.append(
            {
                **planned,
                "query_run_id": row.get("query_run_id", ""),
                "program_attempt_id": row.get(
                    "program_attempt_id",
                    "",
                ),
                "resolved_attempt_number": row.get(
                    "attempt_number",
                    "",
                ),
                "resolved_completed_at_utc": row.get(
                    "completed_at_utc",
                    "",
                ),
                "source_index_dir": row.get("source_index_dir", ""),
                "collection_dir": row.get("collection_dir", ""),
                "observed_pair_id": observed_pair_id,
                "observed_repeat_id": observed_repeat_id,
                "identity_resolution": (
                    "canonicalized_placement_alias" if mismatched_identity_fields else "exact"
                ),
                "observed_execution_status": query_row.get(
                    "execution_status",
                    "",
                ),
                "observed_elapsed_seconds": query_row.get(
                    "elapsed_seconds",
                    "",
                ),
            }
        )
    planned_to_observed: dict[str, set[str]] = defaultdict(set)
    observed_to_planned: dict[str, set[str]] = defaultdict(set)
    for alias in identity_aliases:
        planned_to_observed[alias["planned_pair_id"]].add(alias["observed_pair_id"])
        observed_to_planned[alias["observed_pair_id"]].add(alias["planned_pair_id"])
    for pair_id, aliases in planned_to_observed.items():
        if len(aliases) > 1:
            issues.append(f"placement_pair_alias_not_functional:{pair_id}")
    for pair_id, aliases in observed_to_planned.items():
        if len(aliases) > 1:
            issues.append(f"placement_pair_alias_not_injective:{pair_id}")
    return result, issues, identity_aliases


def consolidate_primary_index(
    *,
    training_rows: list[dict[str, Any]],
    out_dir: Path,
    state_root: Path | None = None,
    primary_batch_ids: set[str] | None = None,
) -> dict[str, int]:
    index_dir = out_dir / "_index"
    index_dir.mkdir(parents=True, exist_ok=True)
    selected_by_source: dict[Path, set[str]] = defaultdict(set)
    selected_instances: dict[Path, set[str]] = defaultdict(set)
    selected_planned_metadata: dict[tuple[Path, str], dict[str, str]] = {}
    identity_fields = (
        "batch_id",
        "execution_slot_id",
        "condition_id",
        "pair_id",
        "repeat_id",
        "repetition_index",
    )
    design_fields = (
        "dataset_profile_id",
        "runtime_config_id",
        "topology_id",
        "intervention_role",
        "intervention_axis",
        "pressure_axis",
        "pressure_level",
        "variant",
        "pressure_pair_key",
        "physical_strategy_id",
        "scenario_level",
        "join_shape_id",
        "remote_shape_id",
        "edge_stress_scope",
        "transfer_volume_level",
        "network_subblock",
        "coordinator_pressure_kind",
        "coordinator_shape_id",
        "mitigation_action",
        "target_metric",
        "dataset_role",
    )
    for row in training_rows:
        source = Path(str(row["source_index_dir"]))
        query_run_id = str(row["query_run_id"])
        selected_by_source[source].add(query_run_id)
        selected_instances[source].add(str(row.get("instance_id", "")))
        planned_metadata = {
            field: str(row.get(field, "")) for field in identity_fields if field in row
        }
        planned_metadata.update(
            {
                field: str(row.get(field, ""))
                for field in design_fields
                if field in row and str(row.get(field, ""))
            }
        )
        selected_planned_metadata[(source, query_run_id)] = planned_metadata
    table_names = sorted(
        {path.name for source in selected_by_source for path in source.glob("*.csv")}
    )
    table_counts: dict[str, int] = {}
    for table_index, table_name in enumerate(table_names, start=1):
        print(
            f"[CONSOLIDATE INDEX {table_index}/{len(table_names)}] {table_name}",
            flush=True,
        )
        source_files: list[tuple[Path, Path]] = []
        for source in selected_by_source:
            table_path = source / table_name
            if table_path.exists():
                source_files.append((source, table_path))
            elif table_name == "execution_features.csv" and (source / "query_runs.csv").exists():
                # Placement-aware query-sweep indexes already expose the
                # enriched execution row in query_runs.csv. Normalize that
                # schema here so downstream feature builders see every
                # selected primary execution through one canonical table.
                source_files.append((source, source / "query_runs.csv"))
        fieldnames: list[str] = []
        seen_fields: set[str] = set()
        for _source, source_file in source_files:
            fields = csv_fields(source_file)
            for field in fields:
                if field not in seen_fields:
                    seen_fields.add(field)
                    fieldnames.append(field)
        rows_written = 0
        seen_context: set[tuple[tuple[str, str], ...]] = set()
        target = index_dir / table_name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
                extrasaction="ignore",
            )
            writer.writeheader()
            for source, source_file in source_files:
                with source_file.open(
                    newline="",
                    encoding="utf-8",
                ) as source_handle:
                    reader = csv.DictReader(source_handle)
                    for row in reader:
                        if "query_run_id" in fieldnames:
                            if str(row.get("query_run_id", "")) not in (selected_by_source[source]):
                                continue
                        elif "instance_id" in fieldnames:
                            if str(row.get("instance_id", "")) not in (selected_instances[source]):
                                continue
                        else:
                            key = tuple(sorted((field, str(value)) for field, value in row.items()))
                            if key in seen_context:
                                continue
                            seen_context.add(key)
                        output_row = {field: row.get(field, "") for field in fieldnames}
                        planned_metadata = selected_planned_metadata.get(
                            (source, str(row.get("query_run_id", "")))
                        )
                        if planned_metadata:
                            for field, value in planned_metadata.items():
                                if field in fieldnames:
                                    output_row[field] = value
                        writer.writerow(output_row)
                        rows_written += 1
        table_counts[table_name.removesuffix(".csv")] = rows_written
    regional_enriched_execution_count = enrich_execution_features_from_regions(index_dir)
    if state_root is not None and primary_batch_ids is not None:
        table_counts["program_hardware_nodes"] = consolidate_program_hardware(
            state_root=state_root,
            batch_ids=primary_batch_ids,
            index_dir=index_dir,
        )
    schema_candidates = [
        REPO_ROOT / "docs/feature_schema.yml",
        *[source / "feature_schema.yml" for source in selected_by_source],
    ]
    for schema in schema_candidates:
        if schema.exists():
            (index_dir / "feature_schema.yml").write_text(
                schema.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            break
    write_json(
        index_dir / "index_manifest.json",
        {
            "index_contract": "pressure_raw_program_primary_index_v1",
            "training_role": "primary",
            "source_index_dirs": [str(path) for path in sorted(selected_by_source)],
            "selected_query_run_count": len(training_rows),
            "regional_enriched_execution_count": regional_enriched_execution_count,
            "derived_execution_fields": list(REGIONAL_EXECUTION_AGGREGATE_FIELDS),
            "tables": table_counts,
        },
    )
    return table_counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Resolve pressure-raw attempts and build a primary-only program index.")
    )
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()

    print("[CONSOLIDATE 1/5] loading program contract and execution matrix", flush=True)
    program = load_yaml(args.program.resolve())
    state_root = args.state_root.resolve()
    out_dir = args.out_dir.resolve()
    if out_dir == state_root:
        raise ValueError("out-dir must not be the raw state root")
    matrix_rows = read_csv(resolve(str(program["execution_matrix"])))[0]
    roles = batch_roles(program)
    expected_rows = expected_primary_rows(program, matrix_rows, roles)
    expected_slots = {str(row.get("execution_slot_id", "")) for row in expected_rows}

    print("[CONSOLIDATE 2/5] discovering completed attempts", flush=True)
    candidates, discovery_issues = discover_candidates(
        program=program,
        state_root=state_root,
        roles=roles,
    )
    print("[CONSOLIDATE 3/5] resolving attempts and primary identities", flush=True)
    selected, exclusions = resolve_attempts(candidates)
    duplicates = duplicate_audit(selected)
    training_rows, training_issues, identity_aliases = training_view(
        selected=selected,
        matrix_rows=matrix_rows,
    )
    selected_primary_slots = {str(row.get("execution_slot_id", "")) for row in training_rows}
    missing_primary_slots = sorted(expected_slots - selected_primary_slots)
    unexpected_primary_slots = sorted(selected_primary_slots - expected_slots)
    fatal_issues = [
        *discovery_issues,
        *training_issues,
        *([f"duplicate_audit_issue_count:{len(duplicates)}"] if duplicates else []),
        *(
            [f"unexpected_primary_slot_count:{len(unexpected_primary_slots)}"]
            if unexpected_primary_slots
            else []
        ),
    ]
    if fatal_issues:
        gate = "NO_GO"
    elif missing_primary_slots:
        gate = "PARTIAL" if args.allow_incomplete else "NO_GO"
    else:
        gate = "GO"

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    role_counts: dict[str, int] = defaultdict(int)
    for row in selected:
        role_counts[str(row.get("consolidation_role", ""))] += 1
    print("[CONSOLIDATE 4/5] materializing the primary-only index", flush=True)
    table_counts = consolidate_primary_index(
        training_rows=training_rows,
        out_dir=out_dir,
        state_root=state_root,
        primary_batch_ids={
            batch_id for batch_id, role in roles.items() if role == "primary"
        },
    )
    index_validation_issues: list[str] = []
    if training_rows and table_counts.get("query_runs") != len(training_rows):
        index_validation_issues.append(
            "primary_query_runs_count_mismatch:"
            f"{table_counts.get('query_runs', 0)}!={len(training_rows)}"
        )
    if index_validation_issues:
        fatal_issues.extend(index_validation_issues)
        gate = "NO_GO"
    write_csv(
        out_dir / "attempt_candidates.csv",
        candidates,
        (
            "program_id",
            "source_batch_id",
            "segment_id",
            "consolidation_role",
            "training_eligible",
            "execution_slot_id",
            "program_attempt_id",
            "attempt_number",
            "query_run_id",
            "candidate_valid",
            "disposition",
        ),
    )
    write_csv(
        out_dir / "resolved_executions.csv",
        selected,
        (
            "program_id",
            "source_batch_id",
            "segment_id",
            "consolidation_role",
            "training_eligible",
            "execution_slot_id",
            "program_attempt_id",
            "attempt_number",
            "query_run_id",
            "disposition",
        ),
    )
    write_csv(
        out_dir / "excluded_executions.csv",
        exclusions,
        (
            "source_batch_id",
            "segment_id",
            "consolidation_role",
            "execution_slot_id",
            "program_attempt_id",
            "query_run_id",
            "disposition",
            "invalid_reason",
        ),
    )
    write_csv(
        out_dir / "duplicate_audit.csv",
        duplicates,
        (
            "issue",
            "value",
            "count",
            "source_batch_ids",
            "query_run_ids",
        ),
    )
    write_csv(
        out_dir / "identity_aliases.csv",
        identity_aliases,
        (
            "execution_slot_id",
            "backend",
            "planned_pair_id",
            "observed_pair_id",
            "planned_repeat_id",
            "observed_repeat_id",
            "resolution",
        ),
    )
    write_csv(
        out_dir / "training_execution_view.csv",
        training_rows,
        (
            "batch_id",
            "execution_slot_id",
            "condition_id",
            "pair_id",
            "repeat_id",
            "query_run_id",
            "program_attempt_id",
            "resolved_attempt_number",
            "observed_pair_id",
            "observed_repeat_id",
            "identity_resolution",
            "source_index_dir",
        ),
    )
    write_csv(
        out_dir / "missing_primary_slots.csv",
        [
            {
                **next(
                    row for row in expected_rows if str(row.get("execution_slot_id", "")) == slot_id
                ),
                "missing_reason": "no_resolved_completed_primary_attempt",
            }
            for slot_id in missing_primary_slots
        ],
        ("batch_id", "execution_slot_id", "condition_id", "missing_reason"),
    )
    manifest = {
        "program_id": program.get("program_id", ""),
        "consolidation_contract": "pressure_raw_program_consolidation_v1",
        "gate": gate,
        "allow_incomplete": args.allow_incomplete,
        "expected_primary_slot_count": len(expected_slots),
        "resolved_primary_slot_count": len(training_rows),
        "missing_primary_slot_count": len(missing_primary_slots),
        "unexpected_primary_slot_count": len(unexpected_primary_slots),
        "attempt_candidate_count": len(candidates),
        "resolved_execution_count_by_role": dict(sorted(role_counts.items())),
        "excluded_execution_count": len(exclusions),
        "duplicate_issue_count": len(duplicates),
        "identity_alias_count": len(identity_aliases),
        "identity_alias_policy": (
            "placement_aware_worker aliases are accepted only when slot and "
            "batch identities match, repeat suffixes are valid, and pair "
            "mapping is bijective"
        ),
        "fatal_issues": fatal_issues,
        "training_index_dir": str(out_dir / "_index"),
        "training_index_table_counts": table_counts,
        "training_policy": {
            "eligible_roles": ["primary"],
            "smoke_in_training": False,
            "sentinel_in_training": False,
            "calibration_in_training": False,
            "holdout_in_training": False,
            "attempt_resolution": "latest_successful_program_attempt",
        },
    }
    write_json(out_dir / "consolidation_manifest.json", manifest)
    print("[CONSOLIDATE 5/5] writing manifest and checksums", flush=True)
    checksum_lines = []
    for path in sorted(out_dir.rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            checksum_lines.append(f"{sha256_file(path)}  {path.relative_to(out_dir)}\n")
    (out_dir / "checksums.sha256").write_text(
        "".join(checksum_lines),
        encoding="utf-8",
    )
    print(out_dir)
    print(
        f"gate={gate} primary={len(training_rows)}/{len(expected_slots)} "
        f"excluded={len(exclusions)} duplicates={len(duplicates)}",
        flush=True,
    )
    return 0 if gate in {"GO", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
