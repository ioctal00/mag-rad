from __future__ import annotations

import json
from pathlib import Path

import yaml

from master_regimes.dataset_profile import REQUIRED_CAPABILITIES, validate_dataset_profile

ROOT = Path(__file__).resolve().parents[1]
DATASET_SCHEMA_DECISION_PATH = ROOT / "workloads/corpus/dataset-schema-decision.yml"
REGIME_COVERAGE_PATH = ROOT / "workloads/corpus/regime-coverage.yml"


def _is_dataset_profile(path: Path) -> bool:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return isinstance(value, dict) and "expected_audit_signals" in value


def test_canonical_dataset_profiles_validate() -> None:
    profile_paths = [
        *sorted((ROOT / "datasets" / "profiles").glob("*.yml")),
        *[
            path
            for path in sorted(
                (
                    ROOT.parent
                    / "master-regimes-infra"
                    / "configs"
                    / "sweeps"
                    / "regime-pilot-v1"
                ).glob("*.yml")
            )
            if _is_dataset_profile(path)
        ],
        *[
            path
            for path in sorted(
                (
                    ROOT.parent
                    / "master-regimes-infra"
                    / "configs"
                    / "sweeps"
                    / "two-profiles-three-shapes-v2"
                ).glob("*.yml")
            )
            if _is_dataset_profile(path)
        ],
    ]
    assert profile_paths

    for profile_path in profile_paths:
        result = validate_dataset_profile(profile_path)
        assert result["status"] == "ok", (profile_path, result["errors"])


def test_dataset_schema_decision_covers_capability_contract() -> None:
    decision = yaml.safe_load(DATASET_SCHEMA_DECISION_PATH.read_text(encoding="utf-8"))
    coverage = yaml.safe_load(REGIME_COVERAGE_PATH.read_text(encoding="utf-8"))
    decision_capabilities = {
        item["capability"] for item in decision.get("capability_decisions", [])
    }
    profile_capabilities: dict[str, set[str]] = {}
    for profile_path in sorted((ROOT / "datasets" / "profiles").glob("*.yml")):
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
        profile_capabilities[str(profile["dataset_id"])] = set(profile["capabilities"])

    assert REQUIRED_CAPABILITIES <= decision_capabilities
    assert decision["decision_summary"]["overall_decision"]
    assert decision["go_no_go"]["current_gate_result"]

    for dataset_id, capabilities in profile_capabilities.items():
        assert REQUIRED_CAPABILITIES <= capabilities, dataset_id

    coverage_required = {
        capability
        for cell in coverage.get("coverage_cells", [])
        for capability in cell.get("required_dataset_capabilities", [])
    }
    assert coverage_required <= decision_capabilities


def test_dataset_profile_audit_thresholds_pass(tmp_path: Path) -> None:
    audit_path = tmp_path / "capability_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "table_counts": {
                    "tenants": 128,
                    "events": 102400,
                    "users": 20480,
                    "global_users": 20480,
                },
                "measured_capabilities": {
                    "supports_reference_join": True,
                    "supports_colocated_user_join": True,
                    "supports_global_users": True,
                    "supports_non_colocated_join": True,
                    "supports_cross_region_user_overlap": False,
                    "supports_high_group_cardinality": True,
                    "supports_hot_tenant_skew": True,
                    "supports_materialized_refresh": True,
                },
                "tenant_skew": {
                    "events_cv": 1.2,
                    "max_to_mean_ratio": 5.0,
                    "top1_event_share": 0.1,
                    "top5_event_share": 0.55,
                    "hot_tenant_count": 10,
                    "hot_event_share": 0.5,
                },
                "dataset_parameter_values": {"hot_tenant_count": 10},
            }
        ),
        encoding="utf-8",
    )

    result = validate_dataset_profile(
        ROOT.parent
        / "master-regimes-infra"
        / "configs"
        / "sweeps"
        / "regime-pilot-v1"
        / "pilot-skew-heavy.yml",
        audit_path=audit_path,
    )

    assert result["status"] == "ok", result["errors"]


def test_dataset_profile_audit_thresholds_fail(tmp_path: Path) -> None:
    audit_path = tmp_path / "capability_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "table_counts": {
                    "tenants": 128,
                    "events": 102400,
                    "users": 20480,
                    "global_users": 20480,
                },
                "measured_capabilities": {
                    "supports_reference_join": True,
                    "supports_colocated_user_join": True,
                    "supports_global_users": True,
                    "supports_non_colocated_join": True,
                    "supports_cross_region_user_overlap": False,
                    "supports_high_group_cardinality": True,
                    "supports_hot_tenant_skew": True,
                    "supports_materialized_refresh": True,
                },
                "tenant_skew": {
                    "events_cv": 0.1,
                    "max_to_mean_ratio": 1.1,
                    "top1_event_share": 0.01,
                    "top5_event_share": 0.03,
                    "hot_tenant_count": 0,
                    "hot_event_share": 0.0,
                },
                "dataset_parameter_values": {"hot_tenant_count": 0},
            }
        ),
        encoding="utf-8",
    )

    result = validate_dataset_profile(
        ROOT.parent
        / "master-regimes-infra"
        / "configs"
        / "sweeps"
        / "regime-pilot-v1"
        / "pilot-skew-heavy.yml",
        audit_path=audit_path,
    )

    assert result["status"] == "error"
    assert any("tenant_skew.events_cv" in error for error in result["errors"])


def test_region_local_skew_asymmetric_profile_validates_for_both_regions() -> None:
    profile_path = ROOT / "datasets" / "profiles" / "pilot-region-local-skew-asymmetric.yml"

    eu_result = validate_dataset_profile(profile_path, region="eu")
    us_result = validate_dataset_profile(profile_path, region="us")

    assert eu_result["status"] == "ok", eu_result["errors"]
    assert us_result["status"] == "ok", us_result["errors"]


def test_region_distribution_override_requires_declared_capability(tmp_path: Path) -> None:
    source_path = ROOT / "datasets" / "profiles" / "pilot-region-local-skew-asymmetric.yml"
    profile = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    profile["dataset_id"] = "invalid-region-skew-capability-v1"
    profile["capabilities"]["supports_region_local_skew_asymmetry"] = False
    profile_path = tmp_path / "invalid-region-skew-capability.yml"
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    result = validate_dataset_profile(profile_path, region="eu")

    assert result["status"] == "error"
    assert any("regions.<id>.distribution skew override" in error for error in result["errors"])
