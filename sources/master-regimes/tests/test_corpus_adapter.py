from __future__ import annotations

import csv
from pathlib import Path

import yaml

from master_regimes.corpus_adapter import render_corpus

ROOT = Path(__file__).resolve().parents[1]
CORPUS_MANIFEST = ROOT / "workloads/corpus/corpus_manifest.pre-us-pilot.yml"
PLAN_C_CORPUS_MANIFEST = ROOT / "workloads/corpus/corpus_manifest.plan-c-pilot.yml"
CLEAN_RUN_CORPUS_MANIFEST = ROOT / "workloads/corpus/corpus_manifest.clean-run-v1.yml"
JOIN_PRESSURE_PROBE_MANIFEST = (
    ROOT
    / "workloads/corpus/corpus_manifest.join-pressure-intensity-probe-v1.yml"
)


def _yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert isinstance(value, dict)
    return value


def test_render_corpus_writes_grouped_execution_plan(tmp_path: Path) -> None:
    plan_path = render_corpus(
        manifest_path=CORPUS_MANIFEST,
        output_dir=tmp_path / "corpus-render",
        max_instances_per_cell=1,
    )

    plan = _yaml(plan_path)
    groups = plan["groups"]
    assert plan["corpus_id"] == "pre-us-eu-gac-corpus-v1"
    assert (tmp_path / "corpus-render" / "corpus_manifest.yml").exists()
    assert (tmp_path / "corpus-render" / "corpus_cells.csv").exists()
    corpus_cells = list(
        csv.DictReader((tmp_path / "corpus-render" / "corpus_cells.csv").open())
    )
    assert len(corpus_cells) == 17
    assert {
        row["runtime_config_id"]
        for row in corpus_cells
        if row["corpus_cell_id"] == "top_tenants_fdw_skew_fetch_small"
    } == {"fetch_small"}
    assert plan["group_count"] == 7
    assert {group["target_group"] for group in groups} == {
        "analytics_clients",
        "coordinators",
    }
    assert sum(group["cell_count"] for group in groups) == 17
    assert sum(group["instance_count"] for group in groups) == 17

    analytics_groups = [
        group for group in groups if group["target_group"] == "analytics_clients"
    ]
    assert analytics_groups
    assert all(group["fdw_bootstrap_required"] is True for group in analytics_groups)
    assert any(group["gac_etl_bootstrap_required"] is True for group in analytics_groups)


def test_join_pressure_probe_samples_database_workers(tmp_path: Path) -> None:
    plan_path = render_corpus(
        manifest_path=JOIN_PRESSURE_PROBE_MANIFEST,
        output_dir=tmp_path / "join-probe-render",
    )

    plan = _yaml(plan_path)
    assert sum(group["instance_count"] for group in plan["groups"]) == 16
    for group in plan["groups"]:
        sweep_path = ROOT.parent / group["sweep_config"]
        sweep = _yaml(sweep_path)
        assert sweep["collection"]["os_sampler"] is True
        assert sweep["collection"]["os_sampler_node_groups"] == ["db_nodes"]


def test_render_plan_c_corpus_keeps_segment_optimized_groups(tmp_path: Path) -> None:
    plan_path = render_corpus(
        manifest_path=PLAN_C_CORPUS_MANIFEST,
        output_dir=tmp_path / "plan-c-render",
        max_instances_per_cell=1,
    )

    plan = _yaml(plan_path)
    groups = plan["groups"]
    corpus_cells = list(
        csv.DictReader((tmp_path / "plan-c-render" / "corpus_cells.csv").open())
    )

    assert plan["corpus_id"] == "plan-c-eu-us-gac-pilot-v1"
    assert len(corpus_cells) >= 31
    assert plan["group_count"] == 8
    assert plan["included_execution_classes"] == ["pilot"]
    assert plan["manifest_cell_count"] >= 31
    assert plan["excluded_cell_count"] == 4
    assert {group["target_group"] for group in groups} == {
        "analytics_clients",
        "coordinators",
    }
    assert {
        (group["dataset_profile_id"], group["runtime_config_id"])
        for group in groups
    } == {
        ("pilot-balanced-v1", "default"),
        ("pilot-balanced-v1", "fetch_small"),
        ("pilot-balanced-v1", "work_mem_high"),
        ("pilot-balanced-v1", "work_mem_low"),
        ("pilot-skew-heavy-v1", "default"),
        ("pilot-skew-heavy-v1", "fetch_large"),
        ("pilot-skew-heavy-v1", "fetch_small"),
    }

    balanced_default = next(
        group
        for group in groups
        if group["dataset_profile_id"] == "pilot-balanced-v1"
        and group["runtime_config_id"] == "default"
        and group["target_group"] == "analytics_clients"
    )
    assert balanced_default["cell_count"] >= 20
    assert balanced_default["fdw_bootstrap_required"] is True
    assert balanced_default["gac_etl_bootstrap_required"] is True

    coordinator_default = next(
        group
        for group in groups
        if group["dataset_profile_id"] == "pilot-balanced-v1"
        and group["runtime_config_id"] == "default"
        and group["target_group"] == "coordinators"
    )
    assert coordinator_default["cell_count"] == 1
    assert coordinator_default["fdw_bootstrap_required"] is False
    assert coordinator_default["gac_etl_bootstrap_required"] is False


def test_render_plan_c_corpus_can_render_long_budget_cells(tmp_path: Path) -> None:
    plan_path = render_corpus(
        manifest_path=PLAN_C_CORPUS_MANIFEST,
        output_dir=tmp_path / "plan-c-long-render",
        max_instances_per_cell=1,
        include_execution_classes={"long_budget"},
    )

    plan = _yaml(plan_path)
    groups = plan["groups"]
    assert plan["included_execution_classes"] == ["long_budget"]
    assert plan["excluded_cell_count"] >= 28
    assert plan["group_count"] == 1
    assert groups[0]["cell_count"] == 4
    manifest_path = ROOT.parent / groups[0]["instance_manifest"]
    rows = list(csv.DictReader(manifest_path.open(newline="", encoding="utf-8")))
    assert {row["execution_class"] for row in rows} == {"long_budget"}
    assert {row["corpus_cell_id"] for row in rows} == {
        "daily_kpi_multiregion_balanced_default",
        "daily_rollup_fdw_balanced_default",
        "daily_rollup_multiregion_balanced_default",
        "multi_dimension_multiregion_balanced_default",
    }


def test_render_corpus_expands_dataset_and_runtime_cell_lists(tmp_path: Path) -> None:
    source = _yaml(PLAN_C_CORPUS_MANIFEST)
    source["query_groups"] = str(ROOT / "workloads" / "corpus" / "query-groups.yml")
    source["runtime_catalog"] = str(ROOT / "workloads" / "corpus" / "runtime-configs.yml")
    source["dataset_profiles"] = {
        "pilot-balanced-v1": {
            "profile": str(ROOT / "datasets" / "profiles" / "pilot-balanced.yml"),
            "load_method": "copy_pipe",
        },
        "pilot-skew-heavy-v1": {
            "profile": str(ROOT / "datasets" / "profiles" / "pilot-skew-heavy.yml"),
            "load_method": "copy_pipe",
        },
    }
    source["cells"] = [
        {
            "corpus_cell_id": "top_tenants_fdw_matrix",
            "logical_question_id": "top_tenants",
            "execution_strategy": "fdw_raw",
            "template_id": "gac_fdw_top_tenants",
            "dataset_profile_id": ["pilot-balanced-v1", "pilot-skew-heavy-v1"],
            "runtime_config_id": ["fetch_small", "fetch_large"],
            "topology_id": "eu_us_gac",
            "intervention_role": "positive_case",
            "intervention_axis": "fetch_size",
            "expected_regime_targets": ["remote_fetch_heavy", "gac_finalization_heavy"],
            "parameters": {
                "lookback_days": [7],
                "limit_k": [10],
            },
        }
    ]
    manifest_path = tmp_path / "matrix-corpus.yml"
    manifest_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")

    plan_path = render_corpus(
        manifest_path=manifest_path,
        output_dir=tmp_path / "matrix-render",
    )

    plan = _yaml(plan_path)
    cells = list(csv.DictReader((tmp_path / "matrix-render" / "corpus_cells.csv").open()))

    assert plan["source_cell_count"] == 1
    assert plan["manifest_cell_count"] == 4
    assert plan["group_count"] == 4
    assert {
        (row["dataset_profile_id"], row["runtime_config_id"])
        for row in cells
    } == {
        ("pilot-balanced-v1", "fetch_small"),
        ("pilot-balanced-v1", "fetch_large"),
        ("pilot-skew-heavy-v1", "fetch_small"),
        ("pilot-skew-heavy-v1", "fetch_large"),
    }


def test_render_clean_run_corpus_stays_segmented_and_near_target_size(
    tmp_path: Path,
) -> None:
    plan_path = render_corpus(
        manifest_path=CLEAN_RUN_CORPUS_MANIFEST,
        output_dir=tmp_path / "clean-run-render",
    )

    plan = _yaml(plan_path)

    assert plan["corpus_id"] == "clean-run-eu-us-gac-v1"
    assert plan["source_cell_count"] == 50
    assert plan["manifest_cell_count"] == 98
    assert plan["group_count"] == 8
    assert sum(group["instance_count"] for group in plan["groups"]) == 1964
    assert {
        (group["dataset_profile_id"], group["runtime_config_id"], group["target_group"])
        for group in plan["groups"]
    } == {
        ("pilot-balanced-v1", "default", "analytics_clients"),
        ("pilot-balanced-v1", "default", "coordinators"),
        ("pilot-balanced-v1", "work_mem_high", "analytics_clients"),
        ("pilot-balanced-v1", "work_mem_low", "analytics_clients"),
        ("pilot-skew-heavy-v1", "default", "analytics_clients"),
        ("pilot-skew-heavy-v1", "default", "coordinators"),
        ("pilot-skew-heavy-v1", "fetch_large", "analytics_clients"),
        ("pilot-skew-heavy-v1", "fetch_small", "analytics_clients"),
    }


def test_render_clean_run_corpus_can_include_long_budget_cells(tmp_path: Path) -> None:
    plan_path = render_corpus(
        manifest_path=CLEAN_RUN_CORPUS_MANIFEST,
        output_dir=tmp_path / "clean-run-all-render",
        include_execution_classes=set(),
    )

    plan = _yaml(plan_path)
    rows = []
    for group in plan["groups"]:
        manifest_path = ROOT.parent / group["instance_manifest"]
        rows.extend(csv.DictReader(manifest_path.open(newline="", encoding="utf-8")))

    assert plan["included_execution_classes"] == ["all"]
    assert plan["source_cell_count"] == 50
    assert plan["manifest_cell_count"] == 98
    assert plan["group_count"] == 8
    assert sum(group["instance_count"] for group in plan["groups"]) == 1966
    assert {
        "gac_fdw_multiregion_daily_kpi",
        "gac_fdw_multiregion_region_daily_join",
    }.issubset({row["template_id"] for row in rows})
    assert {
        row["execution_class"]
        for row in rows
        if row["template_id"]
        in {
            "gac_fdw_multiregion_daily_kpi",
            "gac_fdw_multiregion_region_daily_join",
        }
    } == {"long_budget"}


def test_render_corpus_instance_manifest_preserves_cell_metadata(tmp_path: Path) -> None:
    plan_path = render_corpus(
        manifest_path=CORPUS_MANIFEST,
        output_dir=tmp_path / "corpus-render",
        max_instances_per_cell=1,
    )
    plan = _yaml(plan_path)
    analytics_group = next(
        group
        for group in plan["groups"]
        if group["target_group"] == "analytics_clients"
        and group["dataset_profile_id"] == "geo-skew-heavy-v1"
    )
    manifest_path = ROOT.parent / analytics_group["instance_manifest"]
    rows = list(csv.DictReader(manifest_path.open(newline="", encoding="utf-8")))

    assert {row["corpus_id"] for row in rows} == {"pre-us-eu-gac-corpus-v1"}
    assert {row["dataset_profile_id"] for row in rows} == {"geo-skew-heavy-v1"}
    assert {row["runtime_config_id"] for row in rows} == {"default"}
    assert {row["topology_id"] for row in rows} == {"eu_gac"}
    assert {row["corpus_cell_id"] for row in rows} == {
        "top_tenants_fdw_skew_default",
        "top_tenants_etl_skew_default",
    }
    assert all(Path(row["rendered_sql_path"]).exists() for row in rows)


def test_render_corpus_writes_infra_database_sweep_configs(tmp_path: Path) -> None:
    plan_path = render_corpus(
        manifest_path=CORPUS_MANIFEST,
        output_dir=tmp_path / "corpus-render",
        max_instances_per_cell=1,
    )
    plan = _yaml(plan_path)
    coordinator_group = next(
        group for group in plan["groups"] if group["target_group"] == "coordinators"
    )
    coordinator_sweep = _yaml(ROOT.parent / coordinator_group["sweep_config"])
    analytics_group = next(
        group for group in plan["groups"] if group["target_group"] == "analytics_clients"
    )
    analytics_sweep = _yaml(ROOT.parent / analytics_group["sweep_config"])

    assert coordinator_sweep["collection"]["target_group"] == "coordinators"
    assert coordinator_sweep["collection"]["target_host"] == "eu-coord-1"
    assert (
        coordinator_sweep["execution_policy"]["measurement_lane"]
        == "representative_region_serial"
    )
    assert coordinator_sweep["execution_policy"]["query_concurrency"] == 1
    assert coordinator_sweep["execution_policy"]["representative_region"] == "eu"
    assert coordinator_sweep["collection"]["fdw_auto_explain"] is False
    assert "fdw_bootstrap" not in coordinator_sweep["collection"]
    assert coordinator_sweep["workload"]["instance_manifest"].endswith(
        "instance_manifest.csv"
    )
    assert coordinator_sweep["datasets"][0]["profile"].startswith("master-regimes/")

    assert analytics_sweep["collection"]["target_group"] == "analytics_clients"
    assert "target_host" not in analytics_sweep["collection"]
    assert analytics_sweep["execution_policy"]["measurement_lane"] == "global_gac_serial"
    assert analytics_sweep["execution_policy"]["query_concurrency"] == 1
    assert analytics_sweep["collection"]["fdw_bootstrap"]["enabled"] is True
    assert analytics_sweep["collection"]["gac_etl_bootstrap"]["enabled"] is True

    fetch_group = next(
        group
        for group in plan["groups"]
        if group["runtime_config_id"] == "fetch_small"
        and group["dataset_profile_id"] == "geo-skew-heavy-v1"
    )
    fetch_sweep = _yaml(ROOT.parent / fetch_group["sweep_config"])
    fetch_runtime = fetch_sweep["runtime_configs"][0]
    assert fetch_runtime["intervention_axis"] == "fetch_size"
    assert fetch_runtime["fdw_server_options"] == {"fetch_size": "100"}
    assert fetch_runtime["psql_variables"] == {"FETCH_COUNT": "100"}

    work_mem_group = next(
        group
        for group in plan["groups"]
        if group["runtime_config_id"] == "work_mem_low"
        and group["dataset_profile_id"] == "geo-balanced-v1"
    )
    work_mem_sweep = _yaml(ROOT.parent / work_mem_group["sweep_config"])
    work_mem_runtime = work_mem_sweep["runtime_configs"][0]
    assert work_mem_runtime["intervention_axis"] == "work_mem"
    assert work_mem_runtime["pg_options"] == {"work_mem": "4MB"}
