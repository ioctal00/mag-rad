from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import load_yaml

REQUIRED_CAPABILITIES = {
    "supports_reference_join",
    "supports_colocated_user_join",
    "supports_global_users",
    "supports_global_user_dimension",
    "supports_non_colocated_join",
    "supports_cross_region_user_overlap",
    "supports_high_group_cardinality",
    "supports_hot_tenants",
    "supports_hot_time_windows",
    "supports_hot_tenant_skew",
    "supports_region_imbalance",
    "supports_region_local_skew_asymmetry",
    "supports_shard_skew",
    "supports_wide_payload",
    "supports_large_scan",
    "supports_distribution_key_filter",
    "supports_region_partitioning",
    "supports_etl_rollups",
    "supports_tenant_tiers",
    "supports_selective_filters",
    "supports_materialized_refresh",
}

REQUIRED_AUDIT_SECTIONS = {
    "table_counts_min",
    "tenant_skew",
    "parameter_sources",
}

EXTERNAL_RELATIONAL_CONTRACT = "external_relational_v1"


def _number(value: Any, default: float = 0.0) -> float:
    if value in ("", None):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _profile_region_tenant_count(profile: dict[str, Any], region: str) -> int:
    regions = profile.get("regions", {}) or {}
    region_spec = regions.get(region, {})
    tenant_range = region_spec.get("tenant_id_range", [])
    if not isinstance(tenant_range, list) or len(tenant_range) != 2:
        return 0
    return int(tenant_range[1]) - int(tenant_range[0]) + 1


def _validate_external_relational_contract(
    profile: dict[str, Any],
    *,
    profile_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    for key in ("dataset_id", "generator", "budget_class", "source_lock"):
        if not profile.get(key):
            errors.append(f"missing required field: {key}")
    capabilities = profile.get("capabilities")
    if not isinstance(capabilities, dict):
        errors.append("capabilities must be a mapping")
    else:
        missing_capabilities = sorted(REQUIRED_CAPABILITIES - set(capabilities))
        if missing_capabilities:
            errors.append(f"capabilities missing keys: {missing_capabilities}")

    regions = profile.get("regions")
    if not isinstance(regions, dict) or not {"eu", "us"} <= set(regions):
        errors.append("regions must define eu and us")
    elif any(
        not isinstance(regions.get(region), dict)
        or regions[region].get("snapshot_role") != "replicated_identical"
        for region in ("eu", "us")
    ):
        errors.append("regions.eu/us must declare snapshot_role=replicated_identical")

    adapter = profile.get("execution_adapter")
    if not isinstance(adapter, dict) or adapter.get("id") != "stats_ceb":
        errors.append("execution_adapter.id must be stats_ceb")
    else:
        for key in (
            "regional_database",
            "regional_schema",
            "baseline_database",
            "baseline_schema",
            "citus_ddl",
            "correctness_selection",
        ):
            if not adapter.get(key):
                errors.append(f"execution_adapter.{key} is required")

    design = profile.get("physical_design")
    if not isinstance(design, dict):
        errors.append("physical_design must be a mapping")
    else:
        if int(design.get("shard_count", 0) or 0) <= 0:
            errors.append("physical_design.shard_count must be positive")
        if not isinstance(design.get("distributed_tables"), dict):
            errors.append("physical_design.distributed_tables must be a mapping")
        if not isinstance(design.get("reference_tables"), list):
            errors.append("physical_design.reference_tables must be a list")

    semantics = profile.get("regional_semantics")
    if not isinstance(semantics, dict):
        errors.append("regional_semantics must be a mapping")
    else:
        if semantics.get("comparison_rule") != "per_region_equals_baseline":
            errors.append(
                "regional_semantics.comparison_rule must be per_region_equals_baseline"
            )
        if semantics.get("aggregate_regional_results") is not False:
            errors.append("regional_semantics.aggregate_regional_results must be false")

    if profile_path is not None:
        for field in ("source_lock",):
            raw_path = profile.get(field)
            if raw_path and not (profile_path.parent / str(raw_path)).resolve().exists():
                errors.append(f"{field} path does not exist: {raw_path}")
        if isinstance(adapter, dict):
            for field in ("citus_ddl", "correctness_selection"):
                raw_path = adapter.get(field)
                if raw_path and not (profile_path.parent / str(raw_path)).resolve().exists():
                    errors.append(f"execution_adapter.{field} path does not exist: {raw_path}")
    return errors


def _validate_profile_contract(
    profile: dict[str, Any],
    *,
    region: str,
    profile_path: Path | None = None,
) -> list[str]:
    if profile.get("profile_contract") == EXTERNAL_RELATIONAL_CONTRACT:
        return _validate_external_relational_contract(
            profile,
            profile_path=profile_path,
        )
    errors: list[str] = []
    for key in ("dataset_id", "generator", "seed", "budget_class"):
        if key not in profile:
            errors.append(f"missing required field: {key}")
    for key in ("scale", "regions", "distribution", "capabilities"):
        value = profile.get(key)
        if not isinstance(value, dict):
            errors.append(f"{key} must be a mapping")
    if _profile_region_tenant_count(profile, region) <= 0:
        errors.append(f"regions.{region}.tenant_id_range must define a non-empty range")

    capabilities = profile.get("capabilities", {}) or {}
    missing_capabilities = sorted(REQUIRED_CAPABILITIES - set(capabilities))
    if missing_capabilities:
        errors.append(f"capabilities missing keys: {missing_capabilities}")

    expected = profile.get("expected_audit_signals")
    if not isinstance(expected, dict):
        errors.append("expected_audit_signals must be a mapping")
        return errors
    missing_sections = sorted(REQUIRED_AUDIT_SECTIONS - set(expected))
    if missing_sections:
        errors.append(f"expected_audit_signals missing sections: {missing_sections}")

    table_counts = expected.get("table_counts_min", {})
    if not isinstance(table_counts, dict):
        errors.append("expected_audit_signals.table_counts_min must be a mapping")
    else:
        for table_name in ("tenants", "events", "users", "global_users"):
            if _number(table_counts.get(table_name), -1.0) < 0:
                errors.append(
                    f"expected_audit_signals.table_counts_min.{table_name} "
                    "must be a non-negative number"
                )

    tenant_skew = expected.get("tenant_skew", {})
    if not isinstance(tenant_skew, dict):
        errors.append("expected_audit_signals.tenant_skew must be a mapping")
    else:
        has_bound = any(key.endswith("_min") or key.endswith("_max") for key in tenant_skew)
        if not has_bound:
            errors.append("expected_audit_signals.tenant_skew must define min/max bounds")
        if "hot_tenant_ids_available" not in tenant_skew:
            errors.append(
                "expected_audit_signals.tenant_skew.hot_tenant_ids_available is required"
            )

    parameter_sources = expected.get("parameter_sources", {})
    if not isinstance(parameter_sources, dict):
        errors.append("expected_audit_signals.parameter_sources must be a mapping")
    elif capabilities.get("supports_hot_tenant_skew") is True:
        hot_source = parameter_sources.get("hot_tenant_ids")
        if not isinstance(hot_source, dict):
            errors.append("hot skew profiles must declare parameter_sources.hot_tenant_ids")

    distribution = profile.get("distribution", {}) or {}
    skew_profile = str(distribution.get("skew_profile", "balanced"))
    region_distributions = []
    regions = profile.get("regions", {}) or {}
    if isinstance(regions, dict):
        for region_spec in regions.values():
            if isinstance(region_spec, dict) and isinstance(region_spec.get("distribution"), dict):
                region_distributions.append(region_spec["distribution"])
    has_region_skew = any(
        str(item.get("skew_profile", skew_profile)) != "balanced"
        for item in region_distributions
    )
    if (
        capabilities.get("supports_hot_tenant_skew") is True
        and skew_profile == "balanced"
        and not has_region_skew
    ):
        errors.append(
            "supports_hot_tenant_skew=true requires non-balanced global or per-region skew_profile"
        )
    if capabilities.get("supports_hot_tenant_skew") is False and (
        skew_profile != "balanced" or has_region_skew
    ):
        errors.append("non-balanced skew_profile should declare supports_hot_tenant_skew=true")
    if capabilities.get("supports_region_local_skew_asymmetry") is True and not has_region_skew:
        errors.append(
            "supports_region_local_skew_asymmetry=true requires regions.<id>.distribution override"
        )
    if capabilities.get("supports_region_local_skew_asymmetry") is False and has_region_skew:
        errors.append(
            "regions.<id>.distribution skew override requires "
            "supports_region_local_skew_asymmetry=true"
        )
    return errors


def _validate_audit_against_profile(
    *,
    profile: dict[str, Any],
    audit: dict[str, Any],
    region: str,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    expected = profile.get("expected_audit_signals", {}) or {}
    expected_by_region = profile.get("expected_audit_signals_by_region", {}) or {}
    region_expected = (
        expected_by_region.get(region, {})
        if isinstance(expected_by_region, dict)
        else {}
    )
    if isinstance(region_expected, dict):
        expected = {**expected, **region_expected}

    table_counts = audit.get("table_counts", {}) or {}
    for table_name, minimum in (expected.get("table_counts_min", {}) or {}).items():
        actual = _number(table_counts.get(table_name))
        if actual < _number(minimum):
            errors.append(
                f"table_counts.{table_name}={actual:g} below expected minimum {minimum}"
            )

    measured_capabilities = audit.get("measured_capabilities", {}) or {}
    for capability, declared_value in (profile.get("capabilities", {}) or {}).items():
        measured_value = measured_capabilities.get(capability)
        if declared_value is True and measured_value is False:
            errors.append(f"measured capability {capability}=false but profile declares true")
        elif declared_value is False and measured_value is True:
            warnings.append(f"measured capability {capability}=true but profile declares false")

    tenant_skew = audit.get("tenant_skew", {}) or {}
    expected_skew = expected.get("tenant_skew", {}) or {}
    metric_map = {
        "events_cv": "events_cv",
        "max_to_mean_ratio": "max_to_mean_ratio",
        "top1_event_share": "top1_event_share",
        "top5_event_share": "top5_event_share",
        "hot_tenant_count": "hot_tenant_count",
        "hot_event_share": "hot_event_share",
    }
    for expected_key, audit_key in metric_map.items():
        actual = _number(tenant_skew.get(audit_key))
        minimum = expected_skew.get(f"{expected_key}_min")
        maximum = expected_skew.get(f"{expected_key}_max")
        if minimum is not None and actual < _number(minimum):
            errors.append(f"tenant_skew.{audit_key}={actual:g} below minimum {minimum}")
        if maximum is not None and actual > _number(maximum):
            errors.append(f"tenant_skew.{audit_key}={actual:g} above maximum {maximum}")

    expects_hot_ids = expected_skew.get("hot_tenant_ids_available")
    dataset_parameter_values = audit.get("dataset_parameter_values", {}) or {}
    hot_tenant_count = _number(dataset_parameter_values.get("hot_tenant_count"))
    if expects_hot_ids is True and hot_tenant_count <= 0:
        errors.append("expected hot tenant ids, but audit has no hot_tenant_count")
    if expects_hot_ids is False and hot_tenant_count > 0:
        warnings.append("audit has hot_tenant_count but profile expects no hot tenant ids")
    return errors, warnings


def validate_dataset_profile(
    profile_path: Path,
    *,
    audit_path: Path | None = None,
    region: str = "eu",
) -> dict[str, Any]:
    profile_path = profile_path.resolve()
    profile = load_yaml(profile_path)
    errors = _validate_profile_contract(
        profile,
        region=region,
        profile_path=profile_path,
    )
    warnings: list[str] = []
    audit_summary: dict[str, Any] = {}
    if audit_path is not None and profile.get("profile_contract") != EXTERNAL_RELATIONAL_CONTRACT:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if not isinstance(audit, dict):
            raise ValueError(f"Expected JSON object in {audit_path}")
        audit_errors, audit_warnings = _validate_audit_against_profile(
            profile=profile,
            audit=audit,
            region=region,
        )
        errors.extend(audit_errors)
        warnings.extend(audit_warnings)
        audit_summary = {
            "audit_path": str(audit_path.resolve()),
            "audit_status": audit.get("status", ""),
            "tenant_skew": audit.get("tenant_skew", {}),
            "measured_capabilities": audit.get("measured_capabilities", {}),
        }
    elif audit_path is not None:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit_summary = {
            "audit_path": str(audit_path.resolve()),
            "audit_status": audit.get("status", "") if isinstance(audit, dict) else "",
        }

    return {
        "profile": str(profile_path),
        "dataset_id": profile.get("dataset_id", ""),
        "region": region,
        "errors": errors,
        "warnings": warnings,
        "audit": audit_summary,
        "status": "ok" if not errors else "error",
    }


def assert_dataset_profile_valid(
    profile_path: Path,
    *,
    audit_path: Path | None = None,
    region: str = "eu",
) -> dict[str, Any]:
    result = validate_dataset_profile(profile_path, audit_path=audit_path, region=region)
    if result["errors"]:
        raise ValueError("\n".join(result["errors"]))
    return result
