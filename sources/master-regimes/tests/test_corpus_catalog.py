from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from master_regimes.corpus_manifest import validate_corpus_manifest

ROOT = Path(__file__).resolve().parents[1]
GROUPS_PATH = ROOT / "workloads/corpus/query-groups.yml"
BACKLOG_PATH = ROOT / "workloads/corpus/pre-us-backlog.yml"
REGIME_COVERAGE_PATH = ROOT / "workloads/corpus/regime-coverage.yml"
CORPUS_MANIFEST_PATH = ROOT / "workloads/corpus/corpus_manifest.pre-us-pilot.yml"
PLAN_C_CORPUS_MANIFEST_PATH = ROOT / "workloads/corpus/corpus_manifest.plan-c-pilot.yml"
CLEAN_RUN_CORPUS_MANIFEST_PATH = ROOT / "workloads/corpus/corpus_manifest.clean-run-v1.yml"
WORKLOAD_ROOT = ROOT / "workloads"

STRATEGIES = {
    "single_region_citus",
    "fdw_raw",
    "etl_materialized",
    "regional_partial",
    "multiregion_union",
}

TEMPLATE_REQUIRED_STATUSES = {"runnable_now", "template_ready_needs_us"}
REGIME_COVERAGE_STATUSES = {
    "covered",
    "weak",
    "missing",
    "probe_ready",
    "requires_dataset_change",
    "requires_us_region",
}


def _yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert isinstance(value, dict)
    return value


def _template_specs() -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for path in sorted((WORKLOAD_ROOT / "suites").glob("*.yml")) + [
        WORKLOAD_ROOT / "registry.yml",
        WORKLOAD_ROOT / "gac_registry.yml",
    ]:
        if not path.exists():
            continue
        for template_id, spec in (_yaml(path).get("templates") or {}).items():
            if isinstance(spec, dict):
                specs[str(template_id)] = spec
    return specs


def _groups() -> dict[str, dict[str, Any]]:
    data = _yaml(GROUPS_PATH)
    groups = data.get("groups", [])
    assert isinstance(groups, list)
    return {str(group["logical_question_id"]): group for group in groups}


def _strategy_template_ids(spec: dict[str, Any]) -> set[str]:
    template_ids = {
        str(template_id)
        for template_id in spec.get("alternate_template_ids", []) or []
        if str(template_id)
    }
    if spec.get("template_id"):
        template_ids.add(str(spec["template_id"]))
    return template_ids


def test_query_groups_have_full_strategy_matrix_and_existing_templates() -> None:
    groups = _groups()
    templates = _template_specs()

    assert groups
    for logical_question_id, group in groups.items():
        strategies = group.get("strategies") or {}
        assert set(strategies) == STRATEGIES

        for strategy, spec in strategies.items():
            status = spec.get("status")
            template_id = spec.get("template_id")
            if status in TEMPLATE_REQUIRED_STATUSES:
                assert template_id, f"{logical_question_id}.{strategy} needs a template_id"
                for candidate_id in _strategy_template_ids(spec):
                    assert candidate_id in templates, f"missing template {candidate_id}"
                    template = templates[candidate_id]
                    assert template.get("logical_question_id") == logical_question_id
                    assert template.get("execution_strategy") == strategy


def test_every_workload_template_is_accounted_for_by_query_groups() -> None:
    groups = _groups()
    templates = _template_specs()
    referenced = set()
    for group in groups.values():
        for spec in (group.get("strategies") or {}).values():
            if isinstance(spec, dict):
                referenced.update(_strategy_template_ids(spec))

    unreferenced = sorted(set(templates) - referenced)
    assert unreferenced == []


def test_pre_us_backlog_references_query_groups_and_current_statuses() -> None:
    groups = _groups()
    backlog = _yaml(BACKLOG_PATH)
    templates = _template_specs()

    for item in backlog.get("pre_us_template_backlog", []):
        logical_question_id = item["logical_question_id"]
        strategy = item["strategy"]
        assert logical_question_id in groups
        assert strategy in STRATEGIES
        group_strategy = groups[logical_question_id]["strategies"][strategy]
        assert item["status_now"] == group_strategy["status"]

    for item in backlog.get("completed_p1_items", []):
        logical_question_id = item["logical_question_id"]
        strategy = item["strategy"]
        template_id = item["template_id"]
        assert logical_question_id in groups
        assert strategy in STRATEGIES
        group_strategy = groups[logical_question_id]["strategies"][strategy]
        assert item["status_now"] == group_strategy["status"] == "runnable_now"
        assert template_id in _strategy_template_ids(group_strategy)
        assert template_id in templates

    for item in backlog.get("us_or_later_backlog", []):
        logical_question_id = item["logical_question_id"]
        strategy = item["strategy"]
        template_id = item["template_id"]
        assert logical_question_id in groups
        group_strategy = groups[logical_question_id]["strategies"][strategy]
        assert item["status_now"] == group_strategy["status"]
        assert group_strategy["template_id"] == template_id
        assert template_id in templates


def test_pre_us_mini_test_uses_runnable_templates() -> None:
    groups = _groups()
    backlog = _yaml(BACKLOG_PATH)
    templates = _template_specs()

    mini_test = backlog["current_runnable_mini_test"]["templates"]
    assert mini_test
    for group_spec in mini_test:
        logical_question_id = group_spec["logical_question_id"]
        assert logical_question_id in groups
        for strategy_template in group_spec["strategies"]:
            strategy, template_id = strategy_template.split(":", 1)
            group_strategy = groups[logical_question_id]["strategies"][strategy]
            assert group_strategy["status"] == "runnable_now"
            assert template_id in _strategy_template_ids(group_strategy)
            assert template_id in templates


def test_regime_coverage_references_query_groups_and_templates() -> None:
    groups = _groups()
    templates = _template_specs()
    coverage = _yaml(REGIME_COVERAGE_PATH)

    declared_regimes = {
        item["regime_target"] for item in coverage.get("regime_targets", [])
    }
    assert declared_regimes == {
        "remote_fetch_heavy",
        "gac_finalization_heavy",
        "skew_imbalance",
        "join_movement",
        "well_reduced_localized",
        "mixed_or_unknown",
    }

    covered_regimes: set[str] = set()
    cells = coverage.get("coverage_cells", [])
    assert cells
    for cell in cells:
        status = cell["current_status"]
        regime = cell["regime_target"]
        logical_question_id = cell["logical_question_id"]

        assert status in REGIME_COVERAGE_STATUSES
        assert regime in declared_regimes
        assert logical_question_id in groups
        assert cell.get("coverage_cell_id")
        assert cell.get("expected_primary_evidence")
        assert cell.get("next_action")
        covered_regimes.add(regime)

        for strategy in cell.get("execution_strategies", []):
            assert strategy in STRATEGIES
            assert strategy in groups[logical_question_id]["strategies"]

        if status in {"covered", "weak", "requires_dataset_change", "requires_us_region"}:
            assert cell.get("representative_templates")
        for template_id in cell.get("representative_templates", []):
            assert template_id in templates

    assert declared_regimes == covered_regimes


def test_pre_us_corpus_manifest_is_valid() -> None:
    result = validate_corpus_manifest(CORPUS_MANIFEST_PATH)
    assert result["errors"] == []
    assert result["status"] == "ok"
    assert result["cell_count"] >= 17


def test_plan_c_corpus_manifest_is_valid_and_covers_required_strategy_pairs() -> None:
    result = validate_corpus_manifest(PLAN_C_CORPUS_MANIFEST_PATH)
    assert result["errors"] == []
    assert result["warnings"] == []
    assert result["status"] == "ok"
    assert result["cell_count"] >= 31

    manifest = _yaml(PLAN_C_CORPUS_MANIFEST_PATH)
    cells = manifest.get("cells", [])
    by_question_strategy = {
        (cell["logical_question_id"], cell["execution_strategy"])
        for cell in cells
    }

    required_pairs = {
        ("daily_tenant_rollup", "fdw_raw"),
        ("daily_tenant_rollup", "etl_materialized"),
        ("daily_tenant_rollup", "multiregion_union"),
        ("top_tenants", "fdw_raw"),
        ("top_tenants", "etl_materialized"),
        ("top_tenants", "multiregion_union"),
        ("tenant_point_rollup", "fdw_raw"),
        ("tenant_point_rollup", "etl_materialized"),
        ("tenant_point_rollup", "multiregion_union"),
        ("tenant_tier_daily_join", "fdw_raw"),
        ("tenant_tier_daily_join", "etl_materialized"),
        ("tenant_tier_daily_join", "multiregion_union"),
        ("global_user_topk", "fdw_raw"),
        ("global_user_topk", "etl_materialized"),
        ("global_user_topk", "multiregion_union"),
        ("event_full_scan_summary", "fdw_raw"),
        ("event_full_scan_summary", "multiregion_union"),
    }
    assert required_pairs <= by_question_strategy

    long_budget_cells = {
        cell["corpus_cell_id"]
        for cell in cells
        if cell.get("execution_class") == "long_budget"
    }
    assert long_budget_cells == {
        "daily_kpi_multiregion_balanced_default",
        "daily_rollup_fdw_balanced_default",
        "daily_rollup_multiregion_balanced_default",
        "multi_dimension_multiregion_balanced_default",
    }

    targets = {
        target
        for cell in cells
        for target in cell.get("expected_regime_targets", [])
    }
    assert {
        "remote_fetch_heavy",
        "gac_finalization_heavy",
        "join_movement",
        "well_reduced_localized",
    } <= targets


def test_clean_run_corpus_manifest_is_valid_and_near_target_size() -> None:
    result = validate_corpus_manifest(CLEAN_RUN_CORPUS_MANIFEST_PATH)

    assert result["errors"] == []
    assert result["warnings"] == []
    assert result["status"] == "ok"
    assert result["source_cell_count"] == 50
    assert result["cell_count"] == 98


def test_runtime_intervention_must_match_template_sensitivity(tmp_path: Path) -> None:
    source = _yaml(CORPUS_MANIFEST_PATH)
    source["query_groups"] = str(GROUPS_PATH)
    source["runtime_catalog"] = str(WORKLOAD_ROOT / "corpus" / "runtime-configs.yml")
    source["dataset_profiles"] = {
        "geo-skew-heavy-v1": {
            "profile": str(ROOT / "datasets" / "profiles" / "geo-skew-heavy.yml")
        }
    }
    source["cells"] = [
        {
            "corpus_cell_id": "bad_fetch_on_etl_positive",
            "logical_question_id": "top_tenants",
            "execution_strategy": "etl_materialized",
            "template_id": "gac_etl_top_tenants",
            "dataset_profile_id": "geo-skew-heavy-v1",
            "runtime_config_id": "fetch_small",
            "topology_id": "eu_gac",
            "intervention_role": "positive_case",
            "intervention_axis": "fetch_size",
            "expected_regime_targets": ["well_reduced_localized"],
        }
    ]
    manifest_path = tmp_path / "bad-runtime-manifest.yml"
    manifest_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")

    result = validate_corpus_manifest(manifest_path)

    assert result["status"] == "error"
    assert any("positive runtime intervention" in error for error in result["errors"])


def test_cell_parameter_override_must_cover_template_parameters(tmp_path: Path) -> None:
    source = _yaml(PLAN_C_CORPUS_MANIFEST_PATH)
    source["query_groups"] = str(GROUPS_PATH)
    source["runtime_catalog"] = str(WORKLOAD_ROOT / "corpus" / "runtime-configs.yml")
    source["dataset_profiles"] = {
        "geo-balanced-v1": {
            "profile": str(ROOT / "datasets" / "profiles" / "geo-balanced.yml")
        }
    }
    source["cells"] = [
        {
            "corpus_cell_id": "bad_missing_limit",
            "logical_question_id": "daily_tenant_rollup",
            "execution_strategy": "multiregion_union",
            "template_id": "gac_fdw_multiregion_daily_tenant_rollup",
            "dataset_profile_id": "geo-balanced-v1",
            "runtime_config_id": "default",
            "topology_id": "eu_us_gac",
            "intervention_role": "baseline",
            "expected_regime_targets": ["gac_finalization_heavy"],
            "parameters": {
                "lookback_days": [30],
                "min_value": [0],
            },
        }
    ]
    manifest_path = tmp_path / "bad-missing-param.yml"
    manifest_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")

    result = validate_corpus_manifest(manifest_path)

    assert result["status"] == "error"
    assert any("missing template parameters ['limit_k']" in error for error in result["errors"])
