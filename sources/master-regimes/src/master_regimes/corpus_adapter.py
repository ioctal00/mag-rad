from __future__ import annotations

import csv
import hashlib
import json
import random
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import load_yaml, stable_slug, write_yaml
from .corpus_cells import expand_corpus_cells
from .corpus_manifest import assert_corpus_manifest_valid
from .runtime_config import load_runtime_config_specs
from .workload import _manifest_metadata_value

INSTANCE_FIELDNAMES = [
    "condition_id",
    "execution_slot_id",
    "pair_id",
    "repeat_id",
    "instance_id",
    "template_id",
    "param_json",
    "rendered_sql_path",
    "expected_shape_tags",
    "corpus_id",
    "corpus_version",
    "batch_id",
    "collection_contract_version",
    "corpus_cell_id",
    "logical_question_id",
    "execution_strategy",
    "execution_scope",
    "target_scope",
    "component_match_id",
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
    "expected_regime_targets",
    "execution_class",
    "runtime_sensitivity",
    "required_dataset_capabilities",
    "distribution_key_usage",
    "intervention_roles",
    "cache_policy",
    "order_policy",
    "shuffle_seed",
    "warmup_run_flag",
    "repetition_index",
    "run_order",
    "sentinel_flag",
]

CORPUS_CELL_FIELDNAMES = [
    "corpus_id",
    "corpus_version",
    "batch_id",
    "collection_contract_version",
    "corpus_cell_id",
    "logical_question_id",
    "execution_strategy",
    "execution_scope",
    "target_scope",
    "component_match_id",
    "template_id",
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
    "expected_regime_targets",
    "execution_class",
]

STRATEGY_TARGET_GROUP = {
    "single_region_citus": "coordinators",
    "fdw_raw": "analytics_clients",
    "etl_materialized": "analytics_clients",
    "multiregion_union": "analytics_clients",
}


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    template_id: str
    spec: dict[str, Any]
    registry_path: Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _workspace_root() -> Path:
    return _repo_root().parent


def _resolve(base: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (base / candidate).resolve()


def _workspace_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(_workspace_root()))
    except ValueError:
        return str(resolved)


def _load_template_from_registry(registry_path: Path, template_id: str) -> TemplateSpec:
    registry = load_yaml(registry_path)
    templates = registry.get("templates") or {}
    if not isinstance(templates, dict) or template_id not in templates:
        raise ValueError(f"Template {template_id} not found in {registry_path}")
    spec = templates[template_id]
    if not isinstance(spec, dict):
        raise ValueError(f"Template {template_id} spec in {registry_path} must be a mapping")
    return TemplateSpec(template_id=template_id, spec=spec, registry_path=registry_path)


def _load_template_for_cell(
    *,
    query_groups: dict[str, dict[str, Any]],
    manifest_path: Path,
    cell: dict[str, Any],
) -> TemplateSpec:
    logical_question_id = str(cell["logical_question_id"])
    execution_strategy = str(cell["execution_strategy"])
    template_id = str(cell["template_id"])
    strategy = query_groups[logical_question_id]["strategies"][execution_strategy]
    suite = strategy.get("suite")
    preferred_registry: Path | None = None
    if suite:
        preferred_registry = _resolve(_repo_root(), str(suite))
        try:
            return _load_template_from_registry(preferred_registry, template_id)
        except ValueError as exc:
            if "not found" not in str(exc):
                raise

    # Alternate templates may live in a dedicated suite even when the query
    # group's primary template names an older registry.
    suite_paths = [
        str(path.relative_to(_repo_root()))
        for path in sorted((_repo_root() / "workloads" / "suites").glob("*.yml"))
    ]
    for raw_path in ("workloads/registry.yml", "workloads/gac_registry.yml", *suite_paths):
        registry_path = _resolve(_repo_root(), raw_path)
        if preferred_registry is not None and registry_path == preferred_registry:
            continue
        try:
            return _load_template_from_registry(registry_path, template_id)
        except ValueError as exc:
            if "not found" not in str(exc):
                raise
            continue
    raise ValueError(f"Unable to locate template {template_id} for {manifest_path}")


def _query_groups(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    path = _resolve(manifest_path.parent, str(manifest.get("query_groups", "query-groups.yml")))
    groups = load_yaml(path).get("groups") or []
    if not isinstance(groups, list):
        raise ValueError(f"Expected groups list in {path}")
    return {str(group["logical_question_id"]): group for group in groups}


def _dataset_profile_specs(
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for dataset_profile_id, spec in (manifest.get("dataset_profiles") or {}).items():
        if isinstance(spec, str):
            profile_path = _resolve(manifest_path.parent, spec)
            load_method = "sql"
        elif isinstance(spec, dict):
            profile_path = _resolve(manifest_path.parent, str(spec["profile"]))
            load_method = str(spec.get("load_method", "sql"))
        else:
            raise ValueError(f"Invalid dataset profile spec for {dataset_profile_id}")
        profile = load_yaml(profile_path)
        execution_adapter = profile.get("execution_adapter") or {}
        if not isinstance(execution_adapter, dict):
            raise ValueError(f"execution_adapter in {profile_path} must be a mapping when provided")
        aliases = {str(dataset_profile_id), str(profile.get("dataset_id", dataset_profile_id))}
        for alias in aliases:
            result[alias] = {
                "id": str(dataset_profile_id),
                "profile_path": profile_path,
                "load_method": load_method,
                "profile": profile,
                "adapter": str(execution_adapter.get("id", "citus_datagen")),
                "execution_adapter": execution_adapter,
            }
    return result


def _param_product(parameters: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not parameters:
        return [{}]
    keys = list(parameters)
    return [
        dict(zip(keys, values, strict=True))
        for values in product(*(parameters[key] for key in keys))
    ]


def _cell_parameters(cell: dict[str, Any], template: TemplateSpec) -> dict[str, list[Any]]:
    parameters = cell.get("parameters")
    if parameters is None:
        parameters = template.spec.get("parameters", {}) or {}
    if not isinstance(parameters, dict):
        raise ValueError(f"Cell {cell.get('corpus_cell_id')} parameters must be a mapping")
    defaults = cell.get("_parameter_defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError("Internal parameter defaults must be a mapping")
    normalized: dict[str, list[Any]] = {}
    for key, value in {**defaults, **parameters}.items():
        normalized[str(key)] = value if isinstance(value, list) else [value]
    return normalized


def _template_environment(registry_path: Path) -> Environment:
    search_paths = [registry_path.parent]
    if registry_path.parent.name == "suites":
        search_paths.append(registry_path.parent.parent)
    return Environment(
        loader=FileSystemLoader([str(path) for path in search_paths]),
        undefined=StrictUndefined,
        autoescape=False,
    )


def _group_id(
    *,
    corpus_id: str,
    dataset_profile_id: str,
    runtime_config_id: str,
    target_group: str,
) -> str:
    return "__".join(
        stable_slug(value)
        for value in (corpus_id, dataset_profile_id, runtime_config_id, target_group)
    )


def _render_cell_instances(
    *,
    output_dir: Path,
    corpus_id: str,
    cell: dict[str, Any],
    template: TemplateSpec,
    max_instances_per_cell: int | None,
) -> list[dict[str, str]]:
    env = _template_environment(template.registry_path)
    template_file = str(template.spec["file"])
    values_list = _param_product(_cell_parameters(cell, template))
    if max_instances_per_cell is not None:
        values_list = values_list[:max_instances_per_cell]

    rows: list[dict[str, str]] = []
    queries_dir = output_dir / "queries"
    queries_dir.mkdir(parents=True, exist_ok=True)
    for index, values in enumerate(values_list, start=1):
        param_json = json.dumps(values, sort_keys=True)
        corpus_version = str(cell.get("corpus_version", ""))
        batch_id = str(cell.get("batch_id", ""))
        collection_contract_version = str(cell.get("collection_contract_version", ""))
        pressure_level = str(cell.get("pressure_level", ""))
        variant = str(cell.get("variant", pressure_level))
        pair_key = str(cell.get("pressure_pair_key", ""))
        pair_id = ""
        if pair_key:
            pair_payload = "::".join(
                (
                    corpus_version or corpus_id,
                    batch_id,
                    pair_key,
                    str(cell.get("execution_scope", "")),
                    str(cell.get("target_scope", "")),
                    str(cell["dataset_profile_id"]),
                    str(cell.get("topology_id", "")),
                    param_json,
                )
            )
            pair_id = "pair-" + hashlib.sha256(pair_payload.encode("utf-8")).hexdigest()[:24]
        suffix = "__".join(
            f"{stable_slug(str(key))}-{stable_slug(str(value))}" for key, value in values.items()
        )
        instance_id = "__".join(
            item
            for item in (
                stable_slug(str(cell["corpus_cell_id"])),
                stable_slug(str(template.template_id)),
                suffix or f"case-{index:03d}",
            )
            if item
        )
        rendered_filename = f"{instance_id}.sql"
        if len(rendered_filename.encode("utf-8")) > 220:
            short_cell = stable_slug(str(cell["corpus_cell_id"]))[:80]
            instance_digest = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()[:20]
            rendered_filename = f"{short_cell}--{instance_digest}.sql"
        rendered_path = queries_dir / rendered_filename
        rendered = env.get_template(template_file).render(**values)
        rendered_path.write_text(rendered.strip() + "\n", encoding="utf-8")
        expected_targets = cell.get(
            "expected_regime_targets", template.spec.get("expected_regime_targets", [])
        )
        row = {
            "condition_id": str(cell.get("condition_id", "")),
            "execution_slot_id": "",
            "pair_id": pair_id,
            "repeat_id": "",
            "instance_id": instance_id,
            "template_id": template.template_id,
            "param_json": param_json,
            "rendered_sql_path": str(rendered_path.resolve()),
            "expected_shape_tags": ",".join(template.spec.get("expected_pressure_tags", [])),
            "corpus_id": corpus_id,
            "corpus_version": corpus_version,
            "batch_id": batch_id,
            "collection_contract_version": collection_contract_version,
            "corpus_cell_id": str(cell["corpus_cell_id"]),
            "logical_question_id": str(cell["logical_question_id"]),
            "execution_strategy": str(cell["execution_strategy"]),
            "execution_scope": str(cell.get("execution_scope", "")),
            "target_scope": str(cell.get("target_scope", "")),
            "component_match_id": str(cell.get("component_match_id", "")),
            "dataset_profile_id": str(cell["dataset_profile_id"]),
            "runtime_config_id": str(cell["runtime_config_id"]),
            "topology_id": str(cell.get("topology_id", "")),
            "intervention_role": str(cell.get("intervention_role", "")),
            "intervention_axis": str(cell.get("intervention_axis", "")),
            "pressure_axis": str(cell.get("pressure_axis", "")),
            "pressure_level": pressure_level,
            "variant": variant,
            "pressure_pair_key": pair_key,
            "physical_strategy_id": str(cell.get("physical_strategy_id", "")),
            "scenario_level": str(cell.get("scenario_level", "")),
            "join_shape_id": str(cell.get("join_shape_id", "")),
            "remote_shape_id": str(cell.get("remote_shape_id", "")),
            "edge_stress_scope": str(cell.get("edge_stress_scope", "")),
            "transfer_volume_level": str(cell.get("transfer_volume_level", "")),
            "network_subblock": str(cell.get("network_subblock", "")),
            "coordinator_pressure_kind": _manifest_metadata_value(
                cell.get("coordinator_pressure_kind", "")
            ),
            "coordinator_shape_id": str(cell.get("coordinator_shape_id", "")),
            "mitigation_action": str(cell.get("mitigation_action", "")),
            "target_metric": str(cell.get("target_metric", "")),
            "dataset_role": str(cell.get("dataset_role", "")),
            "expected_regime_targets": _manifest_metadata_value(expected_targets),
            "execution_class": str(cell.get("execution_class", "pilot")),
            "runtime_sensitivity": _manifest_metadata_value(
                template.spec.get("runtime_sensitivity")
            ),
            "required_dataset_capabilities": _manifest_metadata_value(
                template.spec.get("required_dataset_capabilities")
            ),
            "distribution_key_usage": _manifest_metadata_value(
                template.spec.get("distribution_key_usage")
            ),
            "intervention_roles": _manifest_metadata_value(template.spec.get("intervention_roles")),
            "sentinel_flag": str(bool(cell.get("sentinel_flag", False))).lower(),
            "_repeatability_repetitions": str(cell.get("repeatability_repetitions", "")),
        }
        rows.append(row)
    return rows


def _write_instance_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INSTANCE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _deterministic_shuffle_rows(
    rows: list[dict[str, str]],
    *,
    group_id: str,
    seed: int,
) -> list[dict[str, str]]:
    keyed_rows: list[tuple[str, dict[str, str]]] = []
    rng = random.Random(seed)
    for row in rows:
        base = "::".join(
            [
                group_id,
                row.get("corpus_cell_id", ""),
                row.get("instance_id", ""),
                row.get("repetition_index", ""),
                str(seed),
            ]
        )
        digest = hashlib.sha256(base.encode("utf-8")).hexdigest()
        # The random suffix only breaks impossible hash ties while preserving
        # deterministic output for the fixed seed.
        keyed_rows.append((f"{digest}:{rng.random():.18f}", row))
    return [row for _, row in sorted(keyed_rows, key=lambda item: item[0])]


def _explicitly_scheduled_rows(
    rows: list[dict[str, str]],
    schedule: Any,
) -> list[dict[str, str]]:
    if not isinstance(schedule, list) or not schedule:
        raise ValueError(
            "execution_policy.explicit_schedule must be a non-empty list"
        )

    remaining = list(rows)
    ordered: list[dict[str, str]] = []
    for position, entry in enumerate(schedule, start=1):
        if not isinstance(entry, dict):
            raise ValueError(
                "Every explicit schedule entry must map corpus_cell_id and "
                "repetition_index"
            )
        cell_id = str(entry.get("corpus_cell_id", "")).strip()
        repetition_index = str(entry.get("repetition_index", "")).strip()
        instance_id = str(entry.get("instance_id", "")).strip()
        if not cell_id or repetition_index == "":
            raise ValueError(
                f"Explicit schedule entry {position} is missing corpus_cell_id "
                "or repetition_index"
            )
        matches = [
            row
            for row in remaining
            if row.get("corpus_cell_id", "") == cell_id
            and row.get("repetition_index", "") == repetition_index
            and (not instance_id or row.get("instance_id", "") == instance_id)
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Explicit schedule entry {position} resolves to {len(matches)} rows: "
                f"corpus_cell_id={cell_id!r}, repetition_index={repetition_index!r}, "
                f"instance_id={instance_id!r}"
            )
        selected = matches[0]
        ordered.append(selected)
        remaining.remove(selected)

    if remaining:
        sample = [
            f"{row.get('corpus_cell_id', '')}::r{row.get('repetition_index', '')}"
            for row in remaining[:5]
        ]
        raise ValueError(
            "Explicit schedule does not cover every expanded execution row; "
            f"remaining={len(remaining)}, sample={sample}"
        )
    return ordered


def _apply_execution_policy_to_rows(
    rows: list[dict[str, str]],
    *,
    group_id: str,
    execution_policy: dict[str, Any],
) -> list[dict[str, str]]:
    cache_policy = str(
        execution_policy.get("cache_policy")
        or execution_policy.get("name")
        or "mixed_cache_first_observed"
    )
    order_policy = str(execution_policy.get("order_policy", "deterministic_shuffle"))
    shuffle_seed = int(execution_policy.get("shuffle_seed", 20260624) or 20260624)
    repetitions_default = int(execution_policy.get("repetitions_default", 1) or 1)
    sentinel_repetitions = int(
        execution_policy.get("sentinel_repetitions", repetitions_default) or repetitions_default
    )
    expanded_rows: list[dict[str, str]] = []
    for source_row in rows:
        condition_id = source_row.get("condition_id") or (
            "cond-"
            + hashlib.sha256(
                "::".join(
                    [
                        source_row.get("corpus_id", ""),
                        source_row.get("corpus_cell_id", ""),
                        source_row.get("dataset_profile_id", ""),
                        source_row.get("runtime_config_id", ""),
                        source_row.get("topology_id", ""),
                        source_row.get("instance_id", ""),
                    ]
                ).encode("utf-8")
            ).hexdigest()[:20]
        )
        sentinel = source_row.get("sentinel_flag", "").lower() == "true"
        explicit_repetitions = source_row.get("_repeatability_repetitions", "")
        repetitions = (
            int(explicit_repetitions)
            if explicit_repetitions
            else sentinel_repetitions
            if sentinel
            else repetitions_default
        )
        if repetitions < 1:
            raise ValueError("Repeatability repetitions must be at least 1")
        for repetition_index in range(repetitions):
            row = dict(source_row)
            row.pop("_repeatability_repetitions", None)
            row["condition_id"] = condition_id
            row["repetition_index"] = str(repetition_index)
            row["repeat_id"] = (
                f"{row['pair_id']}::r{repetition_index}" if row.get("pair_id") else ""
            )
            row["execution_slot_id"] = f"{condition_id}::r{repetition_index}"
            expanded_rows.append(row)

    ordered_rows = expanded_rows
    if order_policy in {
        "deterministic_shuffle",
        "deterministic_interleaved_shuffle",
    }:
        ordered_rows = _deterministic_shuffle_rows(
            ordered_rows,
            group_id=group_id,
            seed=shuffle_seed,
        )
    elif order_policy == "explicit_schedule":
        ordered_rows = _explicitly_scheduled_rows(
            ordered_rows,
            execution_policy.get("explicit_schedule"),
        )
    elif order_policy != "manifest_order":
        raise ValueError(
            "execution_policy.order_policy must be deterministic_shuffle, "
            "deterministic_interleaved_shuffle, explicit_schedule or manifest_order"
        )

    for run_order, row in enumerate(ordered_rows, start=1):
        row["cache_policy"] = cache_policy
        row["order_policy"] = order_policy
        row["shuffle_seed"] = (
            str(shuffle_seed)
            if order_policy in {"deterministic_shuffle", "deterministic_interleaved_shuffle"}
            else ""
        )
        row["warmup_run_flag"] = "false"
        row["run_order"] = str(run_order)
    return ordered_rows


def _write_corpus_cells(path: Path, corpus_id: str, cells: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CORPUS_CELL_FIELDNAMES)
        writer.writeheader()
        for cell in cells:
            writer.writerow(
                {
                    "corpus_id": corpus_id,
                    "corpus_version": str(cell.get("corpus_version", "")),
                    "batch_id": str(cell.get("batch_id", "")),
                    "collection_contract_version": str(cell.get("collection_contract_version", "")),
                    "corpus_cell_id": str(cell["corpus_cell_id"]),
                    "logical_question_id": str(cell["logical_question_id"]),
                    "execution_strategy": str(cell["execution_strategy"]),
                    "execution_scope": str(cell.get("execution_scope", "")),
                    "target_scope": str(cell.get("target_scope", "")),
                    "component_match_id": str(cell.get("component_match_id", "")),
                    "template_id": str(cell["template_id"]),
                    "dataset_profile_id": str(cell["dataset_profile_id"]),
                    "runtime_config_id": str(cell["runtime_config_id"]),
                    "topology_id": str(cell.get("topology_id", "")),
                    "intervention_role": str(cell.get("intervention_role", "")),
                    "intervention_axis": str(cell.get("intervention_axis", "")),
                    "pressure_axis": str(cell.get("pressure_axis", "")),
                    "pressure_level": str(cell.get("pressure_level", "")),
                    "variant": str(
                        cell.get(
                            "variant",
                            cell.get("pressure_level", ""),
                        )
                    ),
                    "pressure_pair_key": str(cell.get("pressure_pair_key", "")),
                    "physical_strategy_id": str(cell.get("physical_strategy_id", "")),
                    "scenario_level": str(cell.get("scenario_level", "")),
                    "join_shape_id": str(cell.get("join_shape_id", "")),
                    "remote_shape_id": str(cell.get("remote_shape_id", "")),
                    "edge_stress_scope": str(cell.get("edge_stress_scope", "")),
                    "transfer_volume_level": str(
                        cell.get("transfer_volume_level", "")
                    ),
                    "network_subblock": str(cell.get("network_subblock", "")),
                    "coordinator_pressure_kind": _manifest_metadata_value(
                        cell.get("coordinator_pressure_kind", "")
                    ),
                    "coordinator_shape_id": str(cell.get("coordinator_shape_id", "")),
                    "mitigation_action": str(cell.get("mitigation_action", "")),
                    "target_metric": str(cell.get("target_metric", "")),
                    "dataset_role": str(cell.get("dataset_role", "")),
                    "expected_regime_targets": _manifest_metadata_value(
                        cell.get("expected_regime_targets", [])
                    ),
                    "execution_class": str(cell.get("execution_class", "pilot")),
                }
            )


def _sweep_config(
    *,
    sweep_id: str,
    region: str,
    dataset_spec: dict[str, Any],
    runtime_specs: list[dict[str, Any]],
    instance_manifest: Path,
    target_group: str,
    strategies: list[str],
    has_etl: bool,
    execution_budget: dict[str, Any],
    execution_policy: dict[str, Any],
) -> dict[str, Any]:
    analytics = target_group == "analytics_clients"
    dataset_adapter = str(dataset_spec.get("adapter", "citus_datagen"))
    adapter_config = dataset_spec.get("execution_adapter") or {}
    profile_regions = (dataset_spec.get("profile") or {}).get("regions") or {}
    dataset_region_ids = [
        str(region_id).strip().lower()
        for region_id in profile_regions
        if str(region_id).strip()
    ]
    if "multiregion_union" in strategies and len(dataset_region_ids) < 2:
        raise ValueError(
            "multiregion_union requires at least two regions in the dataset profile"
        )
    active_region_ids = (
        dataset_region_ids if "multiregion_union" in strategies else [region]
    )
    collection: dict[str, Any] = {
        "global_stats_scope": "none",
        "target_group": target_group,
        "citus_explain_all_tasks": True,
    }
    target_host = str(execution_policy.get("target_host", "")).strip()
    if not target_host and not analytics:
        # A direct regional experiment represents exactly one region. Make the
        # choice explicit instead of relying on inventory host sort order.
        target_host = f"{region}-coord-1"
    if target_host:
        collection["target_host"] = target_host
    hard_timeout_seconds = int(execution_budget.get("hard_timeout_seconds", 0) or 0)
    timeout_grace_seconds = int(execution_budget.get("timeout_grace_seconds", 30) or 30)
    if hard_timeout_seconds > 0:
        collection["hard_timeout_seconds"] = hard_timeout_seconds
        collection["timeout_grace_seconds"] = timeout_grace_seconds
    cache_policy = str(
        execution_policy.get("cache_policy")
        or execution_policy.get("name")
        or "mixed_cache_first_observed"
    )
    order_policy = str(execution_policy.get("order_policy", "deterministic_shuffle"))
    shuffle_seed = int(execution_policy.get("shuffle_seed", 20260624) or 20260624)
    collection["cache_policy"] = cache_policy
    collection["record_run_order"] = bool(execution_policy.get("record_run_order", True))
    collection["record_buffer_features"] = bool(
        execution_policy.get("record_buffer_features", True)
    )
    collection["os_sampler"] = bool(execution_policy.get("os_sampler", False))
    os_sampler_node_groups = execution_policy.get("os_sampler_node_groups", []) or []
    if not isinstance(os_sampler_node_groups, list):
        raise ValueError("execution_policy.os_sampler_node_groups must be a list")
    collection["os_sampler_node_groups"] = list(
        dict.fromkeys(
            active_region_ids
            if os_sampler_node_groups == ["active_regions"]
            else [
                str(group).strip()
                for group in os_sampler_node_groups
                if str(group).strip()
            ]
        )
    )
    collection["result_signature"] = bool(execution_policy.get("result_signature", False))
    result_signature_scope = str(
        execution_policy.get("result_signature_scope", "every_execution")
    )
    if result_signature_scope not in {
        "every_execution",
        "first_repetition_per_condition",
    }:
        raise ValueError(
            "execution_policy.result_signature_scope must be "
            "every_execution or first_repetition_per_condition"
        )
    collection["result_signature_scope"] = result_signature_scope
    collection["network_profile_probe"] = bool(execution_policy.get("network_profile_probe", False))
    requested_remote_edge_context = bool(
        execution_policy.get("remote_edge_context", False)
    )
    effective_remote_edge_context = analytics and requested_remote_edge_context
    collection["remote_edge_context"] = effective_remote_edge_context
    requested_fdw_auto_explain = bool(
        execution_policy.get("fdw_auto_explain", analytics)
    )
    effective_fdw_auto_explain = analytics and requested_fdw_auto_explain
    collection["fdw_auto_explain"] = effective_fdw_auto_explain
    fdw_auto_explain_regions = execution_policy.get(
        "fdw_auto_explain_regions",
        [],
    ) or []
    if not isinstance(fdw_auto_explain_regions, list):
        raise ValueError("execution_policy.fdw_auto_explain_regions must be a list")
    collection["fdw_auto_explain_regions"] = list(
        dict.fromkeys(
            active_region_ids
            if fdw_auto_explain_regions == ["active_regions"]
            else [
                str(fdw_region).strip().lower()
                for fdw_region in fdw_auto_explain_regions
                if str(fdw_region).strip()
            ]
        )
    )
    if analytics:
        if "multiregion_union" in strategies:
            collection["fdw_bootstrap"] = {
                "enabled": True,
                "regions": dataset_region_ids,
                "adapter": dataset_adapter,
            }
        else:
            collection["fdw_bootstrap"] = {
                "enabled": True,
                "region": region,
                "adapter": dataset_adapter,
            }
    if dataset_adapter == "stats_ceb":
        selection_path = _resolve(
            dataset_spec["profile_path"].parent,
            str(adapter_config["correctness_selection"]),
        )
        collection["correctness_validation"] = {
            "enabled": True,
            "adapter": "stats_ceb",
            "selection": _workspace_relative(selection_path),
            "timeout_seconds": hard_timeout_seconds or 300,
            "filter_workload_to_passed": bool(
                execution_policy.get(
                    "correctness_filter_workload_to_passed",
                    False,
                )
            ),
        }
    if has_etl:
        etl_lookback_days = int(
            execution_policy.get("gac_etl_bootstrap_lookback_days")
            or execution_policy.get("etl_bootstrap_lookback_days")
            or 30
        )
        etl_timeout_seconds = int(
            execution_policy.get("gac_etl_bootstrap_timeout_seconds")
            or execution_policy.get("etl_bootstrap_timeout_seconds")
            or 0
        )
        collection["gac_etl_bootstrap"] = {
            "enabled": True,
            "region": region,
            "lookback_days": etl_lookback_days,
            **({"timeout_seconds": etl_timeout_seconds} if etl_timeout_seconds > 0 else {}),
        }
    return {
        "sweep_id": sweep_id,
        "region": region,
        "datasets": [
            {
                "id": dataset_spec["id"],
                "profile": _workspace_relative(dataset_spec["profile_path"]),
                "load_method": dataset_spec["load_method"],
                "adapter": dataset_adapter,
                **(
                    {"regions": dataset_region_ids}
                    if "multiregion_union" in strategies
                    else {}
                ),
            }
        ],
        "runtime_configs": [
            {
                "id": runtime_spec["id"],
                "pg_options": runtime_spec["pg_options"],
                "regional_pg_options": runtime_spec["regional_pg_options"],
                "psql_variables": runtime_spec["psql_variables"],
                "fdw_server_options": runtime_spec["fdw_server_options"],
                "network_profile": runtime_spec.get("network_profile", {}),
                "intervention_axis": runtime_spec["intervention_axis"],
                "expected_effect": runtime_spec["expected_effect"],
            }
            for runtime_spec in runtime_specs
        ],
        "workload": {
            "instance_manifest": _workspace_relative(instance_manifest),
            "order_policy": order_policy,
            "shuffle_seed": shuffle_seed,
            "filter_instances_by_runtime_config": len(runtime_specs) > 1,
        },
        "collection": collection,
        "execution_policy": {
            "cache_policy": cache_policy,
            "measurement_lane": (
                "global_gac_serial" if analytics else "representative_region_serial"
            ),
            "query_concurrency": 1,
            "representative_region": "" if analytics else region,
            "warmup_per_instance": bool(execution_policy.get("warmup_per_instance", False)),
            "explicit_cache_reset": bool(execution_policy.get("explicit_cache_reset", False)),
            "repetitions_default": int(execution_policy.get("repetitions_default", 1) or 1),
            "sentinel_repetitions": int(
                execution_policy.get(
                    "sentinel_repetitions",
                    execution_policy.get("repetitions_default", 1),
                )
                or 1
            ),
            "cache_features_in_default_model": bool(
                execution_policy.get("cache_features_in_default_model", False)
            ),
            "order_policy": order_policy,
            "shuffle_seed": shuffle_seed,
            "record_run_order": bool(execution_policy.get("record_run_order", True)),
            "record_buffer_features": bool(execution_policy.get("record_buffer_features", True)),
            "preserve_instance_order_across_runtime_configs": bool(
                execution_policy.get(
                    "preserve_instance_order_across_runtime_configs",
                    False,
                )
            ),
            "os_sampler": bool(execution_policy.get("os_sampler", False)),
            "os_sampler_node_groups": collection["os_sampler_node_groups"],
            "result_signature": bool(execution_policy.get("result_signature", False)),
            "result_signature_scope": result_signature_scope,
            "network_profile_probe": bool(execution_policy.get("network_profile_probe", False)),
            "remote_edge_context": effective_remote_edge_context,
            "remote_edge_context_requested": requested_remote_edge_context,
            "fdw_auto_explain": effective_fdw_auto_explain,
            "fdw_auto_explain_regions": collection["fdw_auto_explain_regions"],
            "fdw_auto_explain_requested": requested_fdw_auto_explain,
        },
    }


def render_corpus(
    *,
    manifest_path: Path,
    output_dir: Path,
    max_instances_per_cell: int | None = None,
    region: str = "eu",
    include_execution_classes: set[str] | None = None,
) -> Path:
    assert_corpus_manifest_valid(manifest_path)
    manifest_path = manifest_path.resolve()
    manifest = load_yaml(manifest_path)
    corpus_id = str(manifest["corpus_id"])
    execution_budget = manifest.get("execution_budget") or {}
    if not isinstance(execution_budget, dict):
        raise ValueError("execution_budget must be a mapping when provided")
    execution_policy = manifest.get("execution_policy") or {}
    if not isinstance(execution_policy, dict):
        raise ValueError("execution_policy must be a mapping when provided")
    collection_defaults = {
        field: str(manifest.get(field, ""))
        for field in (
            "corpus_version",
            "batch_id",
            "collection_contract_version",
        )
    }
    parameter_defaults = manifest.get("parameter_defaults") or {}
    if not isinstance(parameter_defaults, dict):
        raise ValueError("parameter_defaults must be a mapping when provided")
    source_cells = [
        {
            **{
                key: value
                for key, value in collection_defaults.items()
                if value and key not in cell
            },
            **cell,
            "_parameter_defaults": parameter_defaults,
        }
        for cell in manifest.get("cells") or []
        if isinstance(cell, dict)
    ]
    all_cells = expand_corpus_cells(source_cells)
    include_execution_classes = (
        {"pilot"} if include_execution_classes is None else include_execution_classes
    )
    include_all_execution_classes = len(include_execution_classes) == 0
    cells = (
        all_cells
        if include_all_execution_classes
        else [
            cell
            for cell in all_cells
            if str(cell.get("execution_class", "pilot")) in include_execution_classes
        ]
    )
    query_groups = _query_groups(manifest_path, manifest)
    dataset_specs = _dataset_profile_specs(manifest_path, manifest)
    runtime_specs = load_runtime_config_specs(
        manifest_path=manifest_path,
        manifest=manifest,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "corpus_manifest.yml").write_text(
        manifest_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_corpus_cells(output_dir / "corpus_cells.csv", corpus_id, all_cells)

    groups: dict[str, dict[str, Any]] = {}
    cell_templates: dict[str, TemplateSpec] = {}
    group_runtime_configs = bool(
        execution_policy.get("group_runtime_configs_by_active_scope", False)
    )
    for cell in cells:
        execution_strategy = str(cell["execution_strategy"])
        if execution_strategy not in STRATEGY_TARGET_GROUP:
            raise ValueError(
                f"Corpus adapter cannot execute strategy {execution_strategy} before "
                "a dedicated backend mapping is defined."
            )
        dataset_profile_id = str(cell["dataset_profile_id"])
        runtime_config_id = str(cell["runtime_config_id"])
        target_group = STRATEGY_TARGET_GROUP[execution_strategy]
        active_scope = (
            "multi-edge"
            if execution_strategy == "multiregion_union"
            else f"single-{region}"
        )
        runtime_group_id = (
            f"runtime-bundle-{active_scope}"
            if group_runtime_configs
            else runtime_config_id
        )
        group_id = _group_id(
            corpus_id=corpus_id,
            dataset_profile_id=dataset_profile_id,
            runtime_config_id=runtime_group_id,
            target_group=target_group,
        )
        groups.setdefault(
            group_id,
            {
                "group_id": group_id,
                "dataset_profile_id": dataset_profile_id,
                "runtime_config_ids": [],
                "target_group": target_group,
                "cells": [],
            },
        )
        groups[group_id]["cells"].append(cell)
        if runtime_config_id not in groups[group_id]["runtime_config_ids"]:
            groups[group_id]["runtime_config_ids"].append(runtime_config_id)
        cell_templates[str(cell["corpus_cell_id"])] = _load_template_for_cell(
            query_groups=query_groups,
            manifest_path=manifest_path,
            cell=cell,
        )

    plan_groups: list[dict[str, Any]] = []
    for group_id, group in sorted(groups.items()):
        group_dir = output_dir / "groups" / group_id
        rows: list[dict[str, str]] = []
        strategies = sorted({str(cell["execution_strategy"]) for cell in group["cells"]})
        has_etl = "etl_materialized" in strategies
        for cell in group["cells"]:
            rows.extend(
                _render_cell_instances(
                    output_dir=group_dir,
                    corpus_id=corpus_id,
                    cell=cell,
                    template=cell_templates[str(cell["corpus_cell_id"])],
                    max_instances_per_cell=max_instances_per_cell,
                )
            )
        rows = _apply_execution_policy_to_rows(
            rows,
            group_id=group_id,
            execution_policy=execution_policy,
        )
        manifest_file = group_dir / "instance_manifest.csv"
        _write_instance_manifest(manifest_file, rows)

        dataset_spec = dataset_specs[str(group["dataset_profile_id"])]
        group_runtime_specs = [
            runtime_specs[runtime_id]
            for runtime_id in sorted(group["runtime_config_ids"])
        ]
        sweep_id = group_id
        sweep_config = _sweep_config(
            sweep_id=sweep_id,
            region=region,
            dataset_spec=dataset_spec,
            runtime_specs=group_runtime_specs,
            instance_manifest=manifest_file,
            target_group=str(group["target_group"]),
            strategies=strategies,
            has_etl=has_etl,
            execution_budget=execution_budget,
            execution_policy=execution_policy,
        )
        sweep_file = output_dir / "sweeps" / f"{group_id}.yml"
        write_yaml(sweep_file, sweep_config)
        plan_groups.append(
            {
                "group_id": group_id,
                "sweep_id": sweep_id,
                "dataset_profile_id": group["dataset_profile_id"],
                "dataset_adapter": dataset_spec["adapter"],
                "runtime_config_id": (
                    group["runtime_config_ids"][0]
                    if len(group["runtime_config_ids"]) == 1
                    else "multiple"
                ),
                "runtime_config_ids": sorted(group["runtime_config_ids"]),
                "target_group": group["target_group"],
                "strategies": strategies,
                "runtime_intervention_axis": "|".join(
                    sorted(
                        {
                            str(runtime_spec["intervention_axis"])
                            for runtime_spec in group_runtime_specs
                        }
                    )
                ),
                "runtime_expected_effect": (
                    "multiple"
                    if len(group_runtime_specs) > 1
                    else group_runtime_specs[0]["expected_effect"]
                ),
                "network_profile_id": (
                    "multiple"
                    if len(group_runtime_specs) > 1
                    else str(
                        group_runtime_specs[0]
                        .get("network_profile", {})
                        .get("id", "")
                    )
                ),
                "cell_count": len(group["cells"]),
                "instance_count": len(rows),
                "instance_manifest": _workspace_relative(manifest_file),
                "sweep_config": _workspace_relative(sweep_file),
                "fdw_bootstrap_required": group["target_group"] == "analytics_clients",
                "gac_etl_bootstrap_required": has_etl,
            }
        )

    plan = {
        "corpus_id": corpus_id,
        "source_manifest": _workspace_relative(manifest_path),
        "rendered_corpus_manifest": _workspace_relative(output_dir / "corpus_manifest.yml"),
        "corpus_cells": _workspace_relative(output_dir / "corpus_cells.csv"),
        "region": region,
        "max_instances_per_cell": max_instances_per_cell,
        "execution_budget": execution_budget,
        "execution_policy": execution_policy,
        "execution_backend": "master-regimes-infra.database_sweep",
        "included_execution_classes": (
            ["all"] if include_all_execution_classes else sorted(include_execution_classes)
        ),
        "source_cell_count": len(source_cells),
        "manifest_cell_count": len(all_cells),
        "excluded_cell_count": len(all_cells) - len(cells),
        "group_count": len(plan_groups),
        "groups": plan_groups,
    }
    plan_path = output_dir / "corpus_execution_plan.yml"
    write_yaml(plan_path, plan)
    (output_dir / "README.md").write_text(
        "# Corpus Execution Plan\n\n"
        "Generated from a controlled `corpus_manifest.yml`. Each group is an "
        "infra-compatible database sweep that shares one dataset profile, one "
        "active topology scope and one target group. A group may contain more "
        "than one runtime config when the manifest explicitly enables runtime "
        "bundling. `corpus_cells.csv` is the "
        "dimension table for the generated corpus cells. Run the generated "
        "`sweeps/*.yml` files through `master-regimes-infra`.\n",
        encoding="utf-8",
    )
    return plan_path
