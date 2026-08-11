from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from master_regimes.regime_interpretation import (
    semantic_v2_membership_rows,
    semantic_v2_prototype_meta_for_cluster,
    spill_location_evidence,
)


def load_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "analysis"
        / "scripts"
        / "live_diagnosis_runner.py"
    )
    spec = importlib.util.spec_from_file_location("live_diagnosis_runner", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_dataset_load(
    root: Path,
    *,
    dataset_id: str,
    region: str,
    created_at: str,
    hot_tenant_count: int,
    hot_event_share: float,
) -> None:
    load_dir = (
        root
        / "generated"
        / "runs"
        / "dataset-loads"
        / f"{created_at}-{dataset_id}-{region}"
    )
    load_dir.mkdir(parents=True)
    (load_dir / "dataset_load_manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "region": region,
                "created_at_utc": created_at,
                "load_id": load_dir.name,
                "datagen_env": {
                    "DATAGEN_TENANT_START": "1" if region == "eu" else "10001",
                    "DATAGEN_TENANT_END": "800" if region == "eu" else "10800",
                    "DATAGEN_EVENTS_PER_TENANT": "250",
                    "DATAGEN_GLOBAL_USERS_PER_TENANT": "100",
                    "DATAGEN_LOOKBACK_DAYS": "30",
                    "DATAGEN_RANDOM_SEED": "42",
                },
                "effective_distribution": {
                    "distribution_key": "tenant_id",
                    "shard_count": 32,
                    "skew_profile": "heavy" if hot_tenant_count else "balanced",
                    **(
                        {"hot_tenant_pct": 5, "hot_event_pct": 65}
                        if hot_tenant_count
                        else {}
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    (load_dir / "capability_audit.json").write_text(
        json.dumps(
            {
                "tenant_skew": {
                    "hot_tenant_count": hot_tenant_count,
                    "hot_event_share": hot_event_share,
                    "events_cv": 2.75 if hot_tenant_count else 0.0,
                    "max_to_mean_ratio": 13.0 if hot_tenant_count else 1.0,
                },
                "tenant_placement": {
                    "dominant_hot_worker": "",
                    "dominant_hot_worker_hot_tenant_count": 0,
                    "dominant_hot_worker_hot_event_share": 0.0,
                    "dominant_hot_worker_probe_ids": [],
                },
            }
        ),
        encoding="utf-8",
    )
    (load_dir / "dataset_parameter_values.json").write_text(
        json.dumps(
            {
                "parameter_values": {
                    "hot_tenant_probe_ids": [1] if hot_tenant_count else [],
                    "cold_tenant_probe_ids": [41] if region == "eu" else [10001],
                    "dominant_hot_worker_probe_ids": [],
                }
            }
        ),
        encoding="utf-8",
    )


def test_latest_dataset_context_preserves_each_region(tmp_path: Path) -> None:
    module = load_module()
    dataset_id = "regional-skew"
    write_dataset_load(
        tmp_path,
        dataset_id=dataset_id,
        region="eu",
        created_at="20260727T003549Z",
        hot_tenant_count=40,
        hot_event_share=0.65,
    )
    write_dataset_load(
        tmp_path,
        dataset_id=dataset_id,
        region="us",
        created_at="20260727T003603Z",
        hot_tenant_count=0,
        hot_event_share=0.0,
    )

    context = module.latest_dataset_load_context(
        infra_root=tmp_path,
        dataset_id=dataset_id,
    )

    assert context["regionCount"] == 2
    assert [region["regionId"] for region in context["regions"]] == ["eu", "us"]
    assert context["regions"][0]["tenantSkew"]["hotTenantCount"] == 40
    assert context["regions"][1]["tenantSkew"]["hotTenantCount"] == 0
    assert context["regions"][0]["generation"] == {
        "tenantStart": 1,
        "tenantEnd": 800,
        "tenantCount": 800,
        "eventsPerTenantAvg": 250,
        "estimatedEventRows": 200000,
        "usersPerTenantAvg": 100,
        "estimatedUserRows": 80000,
        "lookbackDays": 30,
        "randomSeed": 42,
        "distributionKey": "tenant_id",
        "shardCount": 32,
        "skewProfile": "heavy",
        "hotTenantPct": 5,
        "hotEventPct": 65,
    }
    assert context["regions"][1]["generation"]["skewProfile"] == "balanced"
    assert context["regions"][1]["generation"]["hotTenantPct"] is None
    assert "tenantSkew" not in context


@pytest.mark.parametrize(
    "runtime_config_id,axis",
    [
        ("default", "none"),
        ("live_work_mem_64kb", "work_mem"),
        ("work_mem_low", "work_mem"),
        ("live_work_mem_64mb", "work_mem"),
        ("work_mem_high", "work_mem"),
        ("live_join_order_explicit", "join_order"),
        ("live_hashagg_off", "planner_operator"),
        ("live_parallel_off", "parallelism"),
        ("live_parallel_four", "parallelism"),
        ("live_jit_off", "jit"),
        ("live_jit_on", "jit"),
    ],
)
def test_allowlisted_live_runtime_profiles_are_session_only(
    runtime_config_id: str,
    axis: str,
) -> None:
    module = load_module()

    resolved_id, spec = module.resolve_runtime_config(runtime_config_id)

    assert resolved_id == runtime_config_id
    assert spec["intervention_axis"] == axis
    assert not spec.get("fdw_server_options")
    assert not spec.get("network_profile")
    assert spec.get("pg_options", {}) or runtime_config_id == "default"


def test_live_runtime_rejects_persistent_fdw_and_network_profiles() -> None:
    module = load_module()

    with pytest.raises(ValueError, match="nije podržan"):
        module.resolve_runtime_config("fetch_large")
    with pytest.raises(ValueError, match="nije podržan"):
        module.resolve_runtime_config("wan_40ms")


def test_pushdown_payload_preserves_observed_miss() -> None:
    module = load_module()

    payload = module.pushdown_payload(
        {
            "pushdown_fidelity_score": 0.1,
            "pushdown_miss_score": 0.9,
            "pushdown_fidelity_component_count": 4,
            "pushdown_fidelity_evidence_status": "available",
            "pushdown_miss_reason_codes": (
                "local_filter_after_remote,aggregate_not_pushdowned"
            ),
            "foreign_scan_filter_present_count": 2,
            "foreign_scan_filter_pushdown_match_count": 0,
            "remote_sql_where_present_count": 0,
            "remote_sql_group_by_present_count": 0,
        }
    )

    assert payload["available"] is True
    assert payload["missScore"] == 0.9
    assert [reason["id"] for reason in payload["reasons"]] == [
        "local_filter_after_remote",
        "aggregate_not_pushdowned",
    ]
    assert {
        component["id"]: component["status"]
        for component in payload["components"]
    } == {
        "projection": "not_recorded",
        "where": "not_pushed",
        "group_by": "not_pushed",
        "order_by": "not_observed",
    }
    assert payload["heuristic"] is True


def test_semantic_v2_prototype_map_matches_final_thesis_profiles() -> None:
    expected = [
        ("P0", "Selektivna distribuirana putanja bez spill-a"),
        ("P1", "Udaljeni priliv sa globalnom finalizacijom i spill-om"),
        ("P2", "Distribuirana sekvencijalna putanja bez jakog spill-a"),
        ("P3", "Lokalni/materijalizovani ili nizak udaljeni tok"),
    ]
    assert [
        (
            semantic_v2_prototype_meta_for_cluster(cluster)["regime_id"],
            semantic_v2_prototype_meta_for_cluster(cluster)["regime_name"],
        )
        for cluster in range(4)
    ] == expected
    legacy_names = {
        "GAC/FDW finalization and spill pressure",
        "Skew-amplified remote/fan-in pressure",
        "Selective remote lookup / low-output multi-region",
        "Local/materialized low-pressure",
    }
    assert not legacy_names.intersection(name for _, name in expected)


def test_semantic_label_mapping_preserves_memberships_and_order() -> None:
    original = [0.048, 0.858, 0.080, 0.014]
    rows = semantic_v2_membership_rows(original)

    assert [row["regimeId"] for row in rows] == ["P1", "P2", "P0", "P3"]
    assert [row["membership"] for row in rows] == [
        original[1],
        original[2],
        original[0],
        original[3],
    ]


def test_canonical_training_example_for_each_cluster_uses_expected_name() -> None:
    membership_path = (
        Path(__file__).resolve().parents[1]
        / "analysis"
        / "reports"
        / "semantic-v2-model-freeze"
        / "baseline_memberships_k4.csv"
    )
    if not membership_path.exists():
        pytest.skip("optional frozen semantic-v2 report artifacts are not restored")
    memberships = pd.read_csv(membership_path)
    expected_ids = ["P0", "P1", "P2", "P3"]

    for cluster, regime_id in enumerate(expected_ids):
        candidates = memberships[
            memberships["dominant_cluster"].eq(cluster)
        ].sort_values("max_membership", ascending=False)
        assert not candidates.empty
        canonical = candidates.iloc[0]
        vector = [
            float(canonical[f"membership_c{candidate_cluster}"])
            for candidate_cluster in range(4)
        ]
        mapped = semantic_v2_membership_rows(vector)
        assert mapped[0]["cluster"] == cluster
        assert mapped[0]["regimeId"] == regime_id
        assert (
            mapped[0]["name"]
            == semantic_v2_prototype_meta_for_cluster(cluster)["regime_name"]
        )


def test_missing_dataset_metadata_remains_not_recorded(tmp_path: Path) -> None:
    module = load_module()
    dataset_id = "missing-audit"
    write_dataset_load(
        tmp_path,
        dataset_id=dataset_id,
        region="eu",
        created_at="20260727T003549Z",
        hot_tenant_count=40,
        hot_event_share=0.65,
    )
    audit_path = next(
        (
            tmp_path
            / "generated"
            / "runs"
            / "dataset-loads"
        ).glob("*/capability_audit.json")
    )
    audit_path.unlink()

    context = module.latest_dataset_load_context(
        infra_root=tmp_path,
        dataset_id=dataset_id,
    )
    tenant_skew = context["regions"][0]["tenantSkew"]

    assert set(tenant_skew.values()) == {None}
    assert context["regions"][0]["placement"] == {
        "dominantHotWorker": None,
        "dominantHotWorkerHotTenantCount": None,
        "dominantHotWorkerHotEventShare": None,
        "dominantHotWorkerProbeIds": [],
    }


def test_task_and_worker_aggregate_imbalance_are_distinct_metrics() -> None:
    module = load_module()
    payload = module.cross_region_payload(
        {
            "worker_task_scan_rows_isf": 1.973,
            "worker_scan_rows_isf": 1.116,
            "worker_scan_rows_cv": 0.049,
            "remote_region_actual_rows_min": 200_000,
            "remote_region_actual_rows_mean": 200_000,
            "remote_region_actual_rows_max": 200_000,
            "remote_region_actual_rows_imbalance_ratio": 1.0,
            "remote_region_tuple_bytes_min": 3_200_000,
            "remote_region_tuple_bytes_mean": 3_200_000,
            "remote_region_tuple_bytes_max": 3_200_000,
            "remote_region_tuple_bytes_imbalance_ratio": 1.0,
            "remote_region_task_count_min": 32,
            "remote_region_task_count_mean": 32,
            "remote_region_task_count_max": 32,
            "remote_region_task_count_imbalance_ratio": 1.0,
            "remote_region_actual_time_min": 259.431,
            "remote_region_actual_time_mean": 300.769,
            "remote_region_actual_time_max": 342.107,
            "remote_region_actual_time_imbalance_ratio": 1.137,
        }
    )
    metrics = {
        metric["id"]: metric
        for metric in payload["metrics"]
    }

    assert metrics["worker_task_scan_rows_isf"]["value"] == 1.973
    assert metrics["worker_scan_rows_isf"]["value"] == 1.116
    assert metrics["worker_scan_rows_cv"]["value"] == 0.049
    assert metrics["worker_task_scan_rows_isf"]["label"] == "ISF scan redova po Citus tasku"
    assert metrics["worker_scan_rows_isf"]["label"] == "worker-agregirani ISF scan redova"
    assert [row["label"] for row in payload["regionStats"]] == [
        "izlazni redovi po regionu",
        "bajtovi slogova po regionu",
        "broj Citus taskova po regionu",
        "stvarno vrijeme po regionu",
    ]


def test_spill_location_distinguishes_regional_from_gac_temp_blocks() -> None:
    payload = spill_location_evidence(
        {
            "spill_present": 1,
            "main_spill_blocks_sum": 0,
            "remote_spill_blocks_sum": 2932,
        }
    )

    assert payload["present"] is True
    assert payload["statusLabel"] == "prisutan"
    assert payload["layerLabel"] == "regionalni Citus planovi"
    assert payload["mainTempBlocks"] == 0
    assert payload["regionalTempBlocks"] == 2932
