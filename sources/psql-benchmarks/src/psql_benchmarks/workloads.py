from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .settings import ROOT_DIR


@dataclass(frozen=True, slots=True)
class QueryTemplate:
    name: str
    path: Path
    variables: dict[str, str | int | float]


def baseline_queries() -> list[QueryTemplate]:
    return stage_a_core_queries()


def stage_a_core_queries() -> list[QueryTemplate]:
    base = ROOT_DIR / "sql" / "stage_a"
    return [
        QueryTemplate(
            name="a1_global_rolling_kpi",
            path=base / "a1_rolling_aggregate.sql",
            variables={"lookback_days": 30},
        ),
        QueryTemplate(
            name="a2_tenant_locality_aggregate",
            path=base / "a2_tenant_locality_aggregate.sql",
            variables={"tenant_id": 1, "lookback_days": 7},
        ),
        QueryTemplate(
            name="a3_cross_tenant_global_aggregation",
            path=base / "a3_cross_tenant_global_aggregation.sql",
            variables={"lookback_days": 30, "limit_rows": 50},
        ),
        QueryTemplate(
            name="a4_user_top_k",
            path=base / "a4_user_top_k.sql",
            variables={"lookback_days": 30, "limit_rows": 100},
        ),
        QueryTemplate(
            name="a5_fact_reference_join",
            path=base / "a5_fact_reference_join.sql",
            variables={"lookback_days": 30},
        ),
        QueryTemplate(
            name="a6_high_value_filter",
            path=base / "a6_high_value_filter.sql",
            variables={"lookback_days": 30, "min_value": 900},
        ),
    ]


def stage_a_exploratory_queries() -> list[QueryTemplate]:
    base = ROOT_DIR / "sql" / "stage_a"
    return [
        QueryTemplate(
            name="e1_recent_hourly_burst",
            path=base / "e1_recent_hourly_burst.sql",
            variables={"lookback_hours": 24},
        ),
        QueryTemplate(
            name="e2_full_scan_summary",
            path=base / "e2_full_scan_summary.sql",
            variables={},
        ),
        QueryTemplate(
            name="e3_bad_pushdown_sqrt",
            path=base / "e3_bad_pushdown_sqrt.sql",
            variables={"sqrt_min_value": 30},
        ),
        QueryTemplate(
            name="e4_colocated_user_segment_join",
            path=base / "e4_colocated_user_segment_join.sql",
            variables={"lookback_days": 30},
        ),
        QueryTemplate(
            name="e5_reference_staleness_probe",
            path=base / "e5_reference_staleness_probe.sql",
            variables={"lookback_days": 30, "tenant_tier": "enterprise", "tenant_status": "active"},
        ),
        QueryTemplate(
            name="e6_dataset_shape_probe",
            path=base / "e6_dataset_shape_probe.sql",
            variables={},
        ),
        QueryTemplate(
            name="e7_non_colocated_global_user_join",
            path=base / "e7_non_colocated_global_user_join.sql",
            variables={"lookback_days": 30},
        ),
    ]


def legacy_baseline_queries() -> list[QueryTemplate]:
    base = ROOT_DIR / "sql" / "baseline"
    return [
        QueryTemplate(
            name="tenant_time_window",
            path=base / "tenant_time_window.sql",
            variables={"tenant_id": 1, "lookback_days": 30},
        ),
        QueryTemplate(
            name="region_event_count",
            path=base / "region_event_count.sql",
            variables={},
        ),
        QueryTemplate(
            name="top_tenants_by_events",
            path=base / "top_tenants_by_events.sql",
            variables={"limit_rows": 10},
        ),
    ]
