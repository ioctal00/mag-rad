from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_yaml
from .corpus_cells import expand_corpus_cells
from .dataset_profile import validate_dataset_profile
from .runtime_config import (
    load_runtime_config_specs,
    validate_runtime_cell,
    validate_runtime_config_specs,
)

STRATEGIES = {
    "single_region_citus",
    "fdw_raw",
    "etl_materialized",
    "regional_partial",
    "multiregion_union",
}

INTERVENTION_ROLES = {
    "baseline",
    "positive_case",
    "negative_control",
    "calibration",
    "final_check",
}

TEMPLATE_REQUIRED_STATUSES = {"runnable_now", "template_ready_needs_us"}
EXECUTION_CLASSES = {"pilot", "long_budget"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve(base: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (base / candidate).resolve()


def _template_specs(workload_root: Path) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    paths = sorted((workload_root / "suites").glob("*.yml")) + [
        workload_root / "registry.yml",
        workload_root / "gac_registry.yml",
    ]
    for path in paths:
        if not path.exists():
            continue
        for template_id, spec in (load_yaml(path).get("templates") or {}).items():
            if isinstance(spec, dict):
                specs[str(template_id)] = spec
    return specs


def _group_strategy_template_ids(group_strategy: dict[str, Any]) -> set[str]:
    template_ids = {
        str(template_id)
        for template_id in group_strategy.get("alternate_template_ids", []) or []
        if str(template_id)
    }
    template_id = group_strategy.get("template_id")
    if template_id:
        template_ids.add(str(template_id))
    return template_ids


def _query_groups(path: Path) -> dict[str, dict[str, Any]]:
    groups = load_yaml(path).get("groups") or []
    if not isinstance(groups, list):
        raise ValueError(f"Expected groups list in {path}")
    return {str(group["logical_question_id"]): group for group in groups}


def _dataset_profiles(manifest: dict[str, Any], manifest_path: Path) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for dataset_id, spec in (manifest.get("dataset_profiles") or {}).items():
        if isinstance(spec, str):
            profile_path = _resolve(manifest_path.parent, spec)
        elif isinstance(spec, dict):
            profile_path = _resolve(manifest_path.parent, str(spec["profile"]))
        else:
            raise ValueError(f"Invalid dataset profile spec for {dataset_id}")
        profile = load_yaml(profile_path)
        profile_result = validate_dataset_profile(profile_path)
        if profile_result["errors"]:
            raise ValueError(
                f"Invalid dataset profile {profile_path}: "
                + "; ".join(profile_result["errors"])
            )
        profile_id = str(profile.get("dataset_id", dataset_id))
        profiles[profile_id] = profile
        profiles[str(dataset_id)] = profile
    return profiles


def validate_corpus_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    root = _repo_root()
    manifest = load_yaml(manifest_path)
    workload_root = root / "workloads"
    query_groups_path = _resolve(
        manifest_path.parent,
        str(manifest.get("query_groups", "query-groups.yml")),
    )
    templates = _template_specs(workload_root)
    groups = _query_groups(query_groups_path)
    dataset_profiles = _dataset_profiles(manifest, manifest_path)
    runtime_configs = load_runtime_config_specs(
        manifest_path=manifest_path,
        manifest=manifest,
    )
    errors: list[str] = []
    warnings: list[str] = []
    seen_cells: set[str] = set()
    errors.extend(validate_runtime_config_specs(runtime_configs))

    raw_cells = [cell for cell in manifest.get("cells") or [] if isinstance(cell, dict)]
    expanded_cells = expand_corpus_cells(raw_cells)
    for cell in expanded_cells:
        if not isinstance(cell, dict):
            errors.append("Each corpus cell must be a mapping.")
            continue
        cell_id = str(cell.get("corpus_cell_id", ""))
        logical_question_id = str(cell.get("logical_question_id", ""))
        execution_strategy = str(cell.get("execution_strategy", ""))
        template_id = str(cell.get("template_id", ""))
        dataset_profile_id = str(cell.get("dataset_profile_id", ""))
        intervention_role = str(cell.get("intervention_role", ""))
        execution_class = str(cell.get("execution_class", "pilot"))
        pressure_axis = str(cell.get("pressure_axis", ""))
        pressure_level = str(cell.get("pressure_level", ""))
        pressure_pair_key = str(cell.get("pressure_pair_key", ""))
        target_metric = str(cell.get("target_metric", ""))
        corpus_version = str(cell.get("corpus_version", ""))
        batch_id = str(cell.get("batch_id", ""))
        collection_contract_version = str(
            cell.get("collection_contract_version", "")
        )

        if not cell_id:
            errors.append("Corpus cell is missing corpus_cell_id.")
        elif cell_id in seen_cells:
            errors.append(f"Duplicate corpus_cell_id: {cell_id}")
        seen_cells.add(cell_id)

        if execution_strategy not in STRATEGIES:
            errors.append(f"{cell_id}: unknown execution_strategy {execution_strategy}")
        if intervention_role not in INTERVENTION_ROLES:
            errors.append(f"{cell_id}: unknown intervention_role {intervention_role}")
        if execution_class not in EXECUTION_CLASSES:
            errors.append(f"{cell_id}: unknown execution_class {execution_class}")
        pressure_fields = (pressure_axis, pressure_level, pressure_pair_key, target_metric)
        if any(pressure_fields) and not all(pressure_fields):
            errors.append(
                f"{cell_id}: pressure cells require pressure_axis, pressure_level, "
                "pressure_pair_key and target_metric together"
            )
        if pressure_level and pressure_level not in {
            "mitigated",
            "intermediate",
            "stressed",
            "control",
            "combined",
        }:
            errors.append(f"{cell_id}: unknown pressure_level {pressure_level}")
        collection_fields = (
            corpus_version,
            batch_id,
            collection_contract_version,
        )
        if any(collection_fields) and not all(collection_fields):
            errors.append(
                f"{cell_id}: collection cells require corpus_version, batch_id "
                "and collection_contract_version together"
            )
        if template_id not in templates:
            errors.append(f"{cell_id}: unknown template_id {template_id}")
            continue
        if logical_question_id not in groups:
            errors.append(f"{cell_id}: unknown logical_question_id {logical_question_id}")
            continue
        if dataset_profile_id not in dataset_profiles:
            errors.append(f"{cell_id}: unknown dataset_profile_id {dataset_profile_id}")
        template = templates[template_id]
        errors.extend(
            validate_runtime_cell(
                cell=cell,
                template=template,
                runtime_configs=runtime_configs,
            )
        )
        if template.get("logical_question_id") != logical_question_id:
            errors.append(
                f"{cell_id}: template {template_id} belongs to "
                f"{template.get('logical_question_id')}, not {logical_question_id}"
            )
        if template.get("execution_strategy") != execution_strategy:
            errors.append(
                f"{cell_id}: template {template_id} strategy is "
                f"{template.get('execution_strategy')}, not {execution_strategy}"
            )
        if "parameters" in cell:
            cell_parameters = cell.get("parameters") or {}
            template_parameters = template.get("parameters") or {}
            if isinstance(cell_parameters, dict) and isinstance(template_parameters, dict):
                missing_parameters = sorted(set(template_parameters) - set(cell_parameters))
                if missing_parameters:
                    errors.append(
                        f"{cell_id}: cell parameter override is missing template "
                        f"parameters {missing_parameters}"
                    )

        group_strategy = (groups[logical_question_id].get("strategies") or {}).get(
            execution_strategy
        )
        if not isinstance(group_strategy, dict):
            errors.append(f"{cell_id}: query group has no strategy {execution_strategy}")
            continue
        if group_strategy.get("status") not in TEMPLATE_REQUIRED_STATUSES:
            errors.append(
                f"{cell_id}: query group status is {group_strategy.get('status')}, "
                "not runnable/template-ready"
            )
        group_template_ids = _group_strategy_template_ids(group_strategy)
        if template_id not in group_template_ids:
            errors.append(
                f"{cell_id}: query group templates are {sorted(group_template_ids)}, "
                f"not {template_id}"
            )

        dataset_profile = dataset_profiles.get(dataset_profile_id, {})
        capabilities = dataset_profile.get("capabilities", {}) or {}
        missing_capabilities = [
            str(capability)
            for capability in template.get("required_dataset_capabilities", []) or []
            if capabilities.get(str(capability)) is not True
        ]
        if missing_capabilities:
            errors.append(
                f"{cell_id}: dataset {dataset_profile_id} lacks required capabilities "
                f"{missing_capabilities}"
            )

        expected_from_cell = set(cell.get("expected_regime_targets") or [])
        expected_from_template = set(template.get("expected_regime_targets") or [])
        if expected_from_cell and not expected_from_cell.issubset(expected_from_template):
            warnings.append(
                f"{cell_id}: cell expected_regime_targets are not a subset of template targets"
            )

    return {
        "manifest": str(manifest_path),
        "corpus_id": manifest.get("corpus_id", ""),
        "cell_count": len(expanded_cells),
        "source_cell_count": len(manifest.get("cells") or []),
        "errors": errors,
        "warnings": warnings,
        "status": "ok" if not errors else "error",
    }


def assert_corpus_manifest_valid(manifest_path: Path) -> dict[str, Any]:
    result = validate_corpus_manifest(manifest_path)
    if result["errors"]:
        raise ValueError("\n".join(result["errors"]))
    return result
