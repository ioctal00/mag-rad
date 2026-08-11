from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_yaml

RUNTIME_AXES = {
    "none",
    "fetch_size",
    "work_mem",
    "wan_latency",
    "gac_finalization",
    "remote_path",
    "regional_finalization",
    "join_strategy",
    "join_order",
    "planner_operator",
    "parallelism",
    "jit",
    "combined_pressure",
}
SENSITIVITY_VALUES = {"high", "low", "none"}
MAPPING_FIELDS = (
    "pg_options",
    "regional_pg_options",
    "psql_variables",
    "fdw_server_options",
)
NETWORK_PROFILE_FIELD = "network_profile"


def _resolve(base: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (base / candidate).resolve()


def _mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def _normalize_runtime_config(config_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "id": config_id,
        "description": str(spec.get("description", "")),
        "enabled": bool(spec.get("enabled", True)),
        "intervention_axis": str(spec.get("intervention_axis", "none")),
        "applies_when": _mapping(
            spec.get("applies_when", {}),
            field_name=f"runtime_configs.{config_id}.applies_when",
        ),
        "negative_control_when": _mapping(
            spec.get("negative_control_when", {}),
            field_name=f"runtime_configs.{config_id}.negative_control_when",
        ),
        "expected_effect": str(spec.get("expected_effect", "")),
        "requires": list(spec.get("requires", []) or []),
        NETWORK_PROFILE_FIELD: _mapping(
            spec.get(NETWORK_PROFILE_FIELD, {}),
            field_name=f"runtime_configs.{config_id}.{NETWORK_PROFILE_FIELD}",
        ),
    }
    for field in MAPPING_FIELDS:
        normalized[field] = _mapping(
            spec.get(field, {}),
            field_name=f"runtime_configs.{config_id}.{field}",
        )
    return normalized


def load_runtime_config_specs(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    catalog_ref = manifest.get("runtime_catalog")
    if catalog_ref:
        catalog_path = _resolve(manifest_path.parent, str(catalog_ref))
        catalog = load_yaml(catalog_path)
        catalog_specs = catalog.get("runtime_configs") or {}
        if not isinstance(catalog_specs, dict):
            raise ValueError(f"runtime_configs in {catalog_path} must be a mapping")
        for config_id, spec in catalog_specs.items():
            if not isinstance(spec, dict):
                raise ValueError(f"runtime config {config_id} in {catalog_path} must be a mapping")
            specs[str(config_id)] = dict(spec)

    inline_specs = manifest.get("runtime_configs") or {}
    if not isinstance(inline_specs, dict):
        raise ValueError("runtime_configs must be a mapping")
    for config_id, spec in inline_specs.items():
        if spec is None:
            spec = {}
        if not isinstance(spec, dict):
            raise ValueError(f"runtime config {config_id} must be a mapping")
        merged = {**specs.get(str(config_id), {}), **spec}
        specs[str(config_id)] = merged

    return {
        config_id: _normalize_runtime_config(config_id, spec)
        for config_id, spec in sorted(specs.items())
    }


def validate_runtime_config_specs(
    runtime_configs: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    if "default" not in runtime_configs:
        errors.append("runtime_configs must define default")
    for config_id, spec in runtime_configs.items():
        axis = str(spec.get("intervention_axis", "none"))
        if axis not in RUNTIME_AXES:
            errors.append(f"{config_id}: unknown intervention_axis {axis}")
        for field in (
            *MAPPING_FIELDS,
            NETWORK_PROFILE_FIELD,
            "applies_when",
            "negative_control_when",
        ):
            if not isinstance(spec.get(field, {}), dict):
                errors.append(f"{config_id}: {field} must be a mapping")
        if config_id == "default" and axis != "none":
            errors.append("default runtime_config must use intervention_axis=none")
        if axis == "none" and config_id != "default" and spec.get("enabled", True):
            errors.append(f"{config_id}: enabled non-default config needs an intervention_axis")
        if (
            spec.get("enabled", True)
            and not any(spec.get(field) for field in (*MAPPING_FIELDS, NETWORK_PROFILE_FIELD))
            and config_id != "default"
        ):
            errors.append(
                f"{config_id}: non-default runtime_config should define at least one "
                "runtime option or network_profile mapping"
            )
    return errors


def _sensitivity(template: dict[str, Any], axis: str) -> str:
    sensitivities = template.get("runtime_sensitivity") or {}
    if axis in {"gac_finalization", "regional_finalization"}:
        raw = sensitivities.get(axis, sensitivities.get("work_mem", "none"))
    elif axis == "remote_path":
        explicit = sensitivities.get(axis)
        if explicit is not None:
            raw = explicit
        else:
            ranking = {"none": 0, "low": 1, "high": 2}
            raw = max(
                (
                    str(sensitivities.get("fetch_size", "none")),
                    str(sensitivities.get("wan_latency", "none")),
                ),
                key=lambda value: ranking.get(value, 0),
            )
    else:
        raw = sensitivities.get(axis, "none")
    value = str(raw)
    return value if value in SENSITIVITY_VALUES else "none"


def validate_runtime_cell(
    *,
    cell: dict[str, Any],
    template: dict[str, Any],
    runtime_configs: dict[str, dict[str, Any]],
) -> list[str]:
    cell_id = str(cell.get("corpus_cell_id", ""))
    runtime_config_id = str(cell.get("runtime_config_id", ""))
    role = str(cell.get("intervention_role", ""))
    cell_axis = str(cell.get("intervention_axis", ""))
    runtime = runtime_configs.get(runtime_config_id)
    if runtime is None:
        return [f"{cell_id}: unknown runtime_config_id {runtime_config_id}"]
    if runtime.get("enabled") is False:
        return [f"{cell_id}: runtime_config {runtime_config_id} is disabled"]

    axis = str(runtime.get("intervention_axis", "none"))
    if runtime_config_id == "default":
        return []

    errors: list[str] = []
    if not cell_axis:
        errors.append(f"{cell_id}: non-default runtime_config requires intervention_axis")
    elif cell_axis != axis:
        errors.append(
            f"{cell_id}: intervention_axis {cell_axis} does not match "
            f"runtime_config axis {axis}"
        )

    sensitivity = _sensitivity(template, axis)
    if role == "positive_case":
        applies_when = runtime.get("applies_when", {})
        expected = str(applies_when.get(axis, "high"))
        if sensitivity != expected:
            errors.append(
                f"{cell_id}: positive runtime intervention {runtime_config_id} expects "
                f"{axis} sensitivity {expected}, got {sensitivity}"
            )
    elif role == "negative_control":
        negative_when = runtime.get("negative_control_when", {})
        allowed = negative_when.get(axis, ["low", "none"])
        if isinstance(allowed, str):
            allowed_values = {allowed}
        elif isinstance(allowed, list):
            allowed_values = {str(item) for item in allowed}
        else:
            allowed_values = {"low", "none"}
        if sensitivity not in allowed_values:
            errors.append(
                f"{cell_id}: negative control {runtime_config_id} expects {axis} "
                f"sensitivity in {sorted(allowed_values)}, got {sensitivity}"
            )
    elif role not in {"calibration", "final_check"}:
        errors.append(
            f"{cell_id}: non-default runtime_config {runtime_config_id} requires "
            "positive_case, negative_control, calibration or final_check role"
        )
    return errors
