from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

REGIME_COLORS = {
    "R0": "#2c4a63",
    "R1": "#1f6b63",
    "R2": "#7b5726",
    "R3": "#59636f",
}

SEMANTIC_V2_PROTOTYPE_COLORS = {
    "P0": "#2c4a63",
    "P1": "#1f6b63",
    "P2": "#7b5726",
    "P3": "#59636f",
}

SEMANTIC_V2_PROTOTYPE_BY_CLUSTER: dict[int, dict[str, str]] = {
    0: {
        "regime_id": "P0",
        "regime_name": "Selektivna distribuirana putanja bez spill-a",
        "interpretation": (
            "Selektivna distribuirana putanja sa niskim spill-om i nižim "
            "udaljenim vremenskim udjelom."
        ),
        "macro_family": "selective_distributed_low_spill",
        "macro_family_name": "Selektivna distribuirana putanja",
        "variant": "selective_distributed_low_spill",
    },
    1: {
        "regime_id": "P1",
        "regime_name": "Udaljeni priliv sa globalnom finalizacijom i spill-om",
        "interpretation": (
            "Udaljeni priliv prema GAC-u sa globalnom finalizacijom i povišenim "
            "normalizovanim spill-om."
        ),
        "macro_family": "remote_fanin_finalization_spill",
        "macro_family_name": "Udaljeni priliv i globalna finalizacija",
        "variant": "remote_fanin_finalization_spill",
    },
    2: {
        "regime_id": "P2",
        "regime_name": "Distribuirana sekvencijalna putanja bez jakog spill-a",
        "interpretation": (
            "Distribuirana sekvencijalna task putanja sa udaljenim/finalnim "
            "tokom, ali bez jakog normalizovanog spill-a."
        ),
        "macro_family": "distributed_sequential_low_spill",
        "macro_family_name": "Distribuirana sekvencijalna putanja",
        "variant": "distributed_sequential_low_spill",
    },
    3: {
        "regime_id": "P3",
        "regime_name": "Lokalni/materijalizovani ili nizak udaljeni tok",
        "interpretation": (
            "Lokalni ili materijalizovani profil sa malim udaljenim tokom i "
            "niskim normalizovanim spill-om."
        ),
        "macro_family": "local_materialized_low_remote",
        "macro_family_name": "Lokalni ili nizak udaljeni tok",
        "variant": "local_materialized_low_remote",
    },
}


REGIME_BY_CLUSTER: dict[int, dict[str, str]] = {
    0: {
        "regime_id": "R1",
        "regime_name": "Veliki FDW/WAN prenos sa globalnom finalizacijom i spill-om",
        "macro_family": "fdw_wan_transfer",
        "macro_family_name": "FDW/WAN prenos prema GAC-u",
        "variant": "spill_finalization_variant",
    },
    1: {
        "regime_id": "R2",
        "regime_name": "Regionalna agregacija i FDW/WAN prenos prema GAC-u",
        "macro_family": "fdw_wan_transfer",
        "macro_family_name": "FDW/WAN prenos prema GAC-u",
        "variant": "aggregate_fetch_variant",
    },
    2: {
        "regime_id": "R0",
        "regime_name": "Selektivni FDW dohvat sa niskim finalnim izlazom",
        "macro_family": "low_final_cardinality",
        "macro_family_name": "Selektivni FDW dohvat / nizak finalni izlaz",
        "variant": "selective_low_final_cardinality_variant",
    },
    3: {
        "regime_id": "R3",
        "regime_name": "Lokalni/ETL ili nizak FDW/WAN prenos",
        "macro_family": "low_fdw_wan_transfer",
        "macro_family_name": "Nizak FDW/WAN prenos / materializovani baseline",
        "variant": "low_remote_flow_variant",
    },
}


AMBIGUITY_THRESHOLDS = {
    "crisp_top_membership": 0.50,
    "crisp_top2_margin": 0.15,
    "suppress_residual_membership_below": 0.20,
    "high_entropy": 1.05,
}


@dataclass(frozen=True, slots=True)
class AmbiguityAssessment:
    label: str
    mixed: bool
    explain_cluster_as_context_only: bool
    reason: str


def regime_meta_for_cluster(cluster: int) -> dict[str, str]:
    return REGIME_BY_CLUSTER[int(cluster)]


def semantic_v2_prototype_meta_for_cluster(cluster: int) -> dict[str, str]:
    return SEMANTIC_V2_PROTOTYPE_BY_CLUSTER[int(cluster)]


def semantic_v2_membership_rows(
    membership_values: list[float],
    *,
    distance_values: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Attach the frozen P0-P3 contract without changing model values."""

    expected = len(SEMANTIC_V2_PROTOTYPE_BY_CLUSTER)
    if len(membership_values) != expected:
        raise ValueError(
            f"Semantic V2 expects {expected} memberships, got {len(membership_values)}"
        )
    if distance_values is not None and len(distance_values) != expected:
        raise ValueError(
            f"Semantic V2 expects {expected} distances, got {len(distance_values)}"
        )

    rows: list[dict[str, Any]] = []
    for cluster in sorted(
        range(expected),
        key=lambda cluster_id: float(membership_values[cluster_id]),
        reverse=True,
    ):
        meta = semantic_v2_prototype_meta_for_cluster(cluster)
        row: dict[str, Any] = {
            "cluster": cluster,
            "regimeId": meta["regime_id"],
            "name": meta["regime_name"],
            "macroFamily": meta["macro_family"],
            "macroFamilyName": meta["macro_family_name"],
            "variant": meta["variant"],
            "color": SEMANTIC_V2_PROTOTYPE_COLORS.get(
                meta["regime_id"],
                "#475569",
            ),
            "membership": float(membership_values[cluster]),
        }
        if distance_values is not None:
            row["distance"] = float(distance_values[cluster])
        rows.append(row)
    return rows


def pushdown_component_statuses(raw_row: dict[str, Any]) -> list[dict[str, Any]]:
    """Summarize SQL pushdown components as a heuristic post-hoc audit."""

    fdw_count = _number(raw_row, "fdw_foreign_scan_count")
    local_filters = _number(raw_row, "foreign_scan_filter_present_count")
    matched_filters = _number(
        raw_row,
        "foreign_scan_filter_pushdown_match_count",
    )
    remote_where = _number(raw_row, "remote_sql_where_present_count")
    remote_group = _number(raw_row, "remote_sql_group_by_present_count")
    remote_order = _number(raw_row, "remote_sql_order_by_present_count")
    aggregate_above = _number(raw_row, "aggregate_above_foreign_scan_count")
    sort_above = _number(raw_row, "sort_above_foreign_scan_count")
    reason_codes = {
        code.strip()
        for code in str(raw_row.get("pushdown_miss_reason_codes") or "")
        .replace(";", ",")
        .split(",")
        if code.strip()
    }
    projection_expansion = _number(
        raw_row,
        "projection_width_expansion_ratio",
    )

    def component(
        component_id: str,
        label: str,
        status: str,
        status_label: str,
        evidence: dict[str, float | None],
    ) -> dict[str, Any]:
        return {
            "id": component_id,
            "label": label,
            "status": status,
            "statusLabel": status_label,
            "evidence": evidence,
        }

    has_component_evidence = bool(
        reason_codes
        or any(
            value is not None
            for value in (
                fdw_count,
                local_filters,
                matched_filters,
                remote_where,
                remote_group,
                remote_order,
                aggregate_above,
                sort_above,
                projection_expansion,
            )
        )
    )
    if not has_component_evidence:
        return [
            component(
                component_id,
                label,
                "not_recorded",
                "nije zabilježeno",
                {},
            )
            for component_id, label in (
                ("projection", "projekcija"),
                ("where", "WHERE"),
                ("group_by", "GROUP BY"),
                ("order_by", "ORDER BY"),
            )
        ]

    if projection_expansion is None:
        projection_status = ("not_recorded", "nije zabilježeno")
    elif projection_expansion > 1.05:
        projection_status = ("partial", "djelimično prenesena")
    else:
        projection_status = ("observed", "bez opažene ekspanzije")

    if local_filters and local_filters > 0:
        match_ratio = (matched_filters or 0.0) / local_filters
        if match_ratio >= 1:
            where_status = ("pushed", "prenesen")
        elif match_ratio > 0:
            where_status = ("partial", "djelimično prenesen")
        else:
            where_status = ("not_pushed", "nije prenesen")
    elif remote_where and remote_where > 0:
        where_status = ("pushed", "prenesen")
    else:
        where_status = ("not_observed", "nije opažen")

    if (
        "aggregate_not_pushdowned" in reason_codes
        or (_number(raw_row, "aggregate_pushdown_missed_flag") or 0) > 0
    ):
        group_status = ("not_pushed", "nije prenesen")
    elif aggregate_above and aggregate_above > 0:
        group_status = (
            ("partial", "djelimično prenesen")
            if remote_group and remote_group > 0
            else ("not_pushed", "nije prenesen")
        )
    elif remote_group and remote_group > 0:
        group_status = ("pushed", "prenesen")
    else:
        group_status = ("not_observed", "nije opažen")

    if (
        "sort_not_pushdowned" in reason_codes
        or (_number(raw_row, "sort_pushdown_missed_flag") or 0) > 0
    ):
        order_status = ("not_pushed", "nije prenesen")
    elif sort_above and sort_above > 0:
        order_status = (
            ("partial", "djelimično prenesen")
            if remote_order and remote_order > 0
            else ("not_pushed", "nije prenesen")
        )
    elif remote_order and remote_order > 0:
        order_status = ("pushed", "prenesen")
    else:
        order_status = ("not_observed", "nije opažen")

    return [
        component(
            "projection",
            "projekcija",
            projection_status[0],
            projection_status[1],
            {"projection_width_expansion_ratio": projection_expansion},
        ),
        component(
            "where",
            "WHERE",
            where_status[0],
            where_status[1],
            {
                "local_filter_count": local_filters,
                "matched_filter_count": matched_filters,
                "remote_where_count": remote_where,
            },
        ),
        component(
            "group_by",
            "GROUP BY",
            group_status[0],
            group_status[1],
            {
                "aggregate_above_fdw_count": aggregate_above,
                "remote_group_by_count": remote_group,
            },
        ),
        component(
            "order_by",
            "ORDER BY",
            order_status[0],
            order_status[1],
            {
                "sort_above_fdw_count": sort_above,
                "remote_order_by_count": remote_order,
            },
        ),
    ]


def spill_location_evidence(raw_row: dict[str, Any]) -> dict[str, Any]:
    """Locate observed temp-block spill without inferring general memory pressure."""

    main_blocks = _number(raw_row, "main_spill_blocks_sum")
    regional_blocks = _number(raw_row, "remote_spill_blocks_sum")
    model_spill = _number(raw_row, "spill_present")
    recorded = any(
        value is not None
        for value in (main_blocks, regional_blocks, model_spill)
    )
    layers: list[dict[str, Any]] = []
    if main_blocks is not None and main_blocks > 0:
        layers.append(
            {
                "id": "gac_main",
                "label": "GAC/glavni plan",
                "tempBlocks": main_blocks,
            }
        )
    if regional_blocks is not None and regional_blocks > 0:
        layers.append(
            {
                "id": "regional_citus",
                "label": "regionalni Citus planovi",
                "tempBlocks": regional_blocks,
            }
        )

    present = bool(layers) or bool(model_spill and model_spill > 0)
    if not recorded:
        status = "not_recorded"
        status_label = "nije zabilježeno"
        layer_label = "nije zabilježeno"
    elif not present:
        status = "not_observed"
        status_label = "nije opažen"
        layer_label = "nema opaženog spill-a"
    elif layers:
        status = "observed"
        status_label = "prisutan"
        layer_label = " + ".join(str(layer["label"]) for layer in layers)
    else:
        status = "observed_layer_unknown"
        status_label = "prisutan, sloj nije zabilježen"
        layer_label = "sloj nije zabilježen"

    return {
        "available": recorded,
        "present": present,
        "status": status,
        "statusLabel": status_label,
        "layerLabel": layer_label,
        "mainTempBlocks": main_blocks,
        "regionalTempBlocks": regional_blocks,
        "layers": layers,
        "semantics": (
            "Spill znači opažene privremene blokove u plan artefaktima; "
            "nije dokaz ukupnog memorijskog pritiska čvora."
        ),
        "modelRelationship": (
            "Lokacija spill-a je post-hoc audit. Finalni modelski prostor koristi "
            "spill prisustvo i normalizovane spill omjere, ne ove nazive slojeva."
        ),
    }


def assess_ambiguity(
    *,
    top_membership: float,
    top2_margin: float,
    entropy: float,
) -> AmbiguityAssessment:
    if (
        top_membership >= AMBIGUITY_THRESHOLDS["crisp_top_membership"]
        and top2_margin >= AMBIGUITY_THRESHOLDS["crisp_top2_margin"]
        and entropy < AMBIGUITY_THRESHOLDS["high_entropy"]
    ):
        return AmbiguityAssessment(
            label="contextual",
            mixed=False,
            explain_cluster_as_context_only=False,
            reason=(
                "vodeći prototip je dovoljno izdvojen da se koristi kao režimski "
                "kontekst, uz provjeru feature evidence-a"
            ),
        )
    return AmbiguityAssessment(
        label="mixed_boundary",
        mixed=True,
        explain_cluster_as_context_only=True,
        reason=(
            "fuzzy pripadnost je mješovita; cluster procente treba tumačiti kao "
            "geometrijsku sličnost prototipima, ne kao procenat aktivnog uzroka"
        ),
    )


def macro_family_summary(memberships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for row in memberships:
        regime_id = str(row.get("regimeId", ""))
        membership = float(row.get("membership", 0.0) or 0.0)
        meta = next(
            (value for value in REGIME_BY_CLUSTER.values() if value["regime_id"] == regime_id),
            None,
        )
        if meta is None:
            continue
        family_id = meta["macro_family"]
        current = totals.setdefault(
            family_id,
            {
                "familyId": family_id,
                "name": meta["macro_family_name"],
                "membership": 0.0,
                "regimeIds": [],
            },
        )
        current["membership"] += membership
        current["regimeIds"].append(regime_id)
    return sorted(totals.values(), key=lambda item: item["membership"], reverse=True)


def _number(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value in ("", None):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def mechanism_tags(raw_row: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive feature-first mechanism tags for per-query interpretation.

    These tags are intentionally not clustering labels. They summarize direct
    evidence from normalized flow/skew/spill features.
    """

    def tag(tag_id: str, label: str, level: str, evidence: dict[str, Any]) -> dict[str, Any]:
        return {"id": tag_id, "label": label, "level": level, "evidence": evidence}

    rows: list[dict[str, Any]] = []
    remote_path = _number(raw_row, "remote_path_share")
    remote_final = _number(raw_row, "remote_to_final_rows_ratio")
    wan_final = _number(raw_row, "wan_output_to_final_rows_ratio")
    global_merge = _number(raw_row, "global_group_merge_ratio")
    temp_final = _number(raw_row, "temp_blocks_per_final_row")
    temp_wan_bytes = _number(raw_row, "temp_bytes_to_wan_bytes_ratio")
    region_isf = _number(raw_row, "remote_region_rows_isf")
    task_isf = _number(raw_row, "worker_task_scan_rows_isf")
    repartition = _number(raw_row, "citus_repartition_query")
    estimate_errors = [
        abs(value)
        for value in (
            _number(raw_row, "root_rows_estimate_error_log"),
            _number(raw_row, "foreign_scan_rows_estimate_error_log"),
            _number(raw_row, "aggregate_rows_estimate_error_log"),
            _number(raw_row, "remote_root_rows_estimate_error_log"),
        )
        if value is not None
    ]

    if (remote_path is not None and remote_path >= 0.75) or (
        remote_final is not None and remote_final >= 100
    ) or (wan_final is not None and wan_final >= 100):
        rows.append(
            tag(
                "remote_fanin",
                "FDW/WAN prenos prema GAC-u",
                "extreme" if max(remote_final or 0, wan_final or 0) >= 10_000 else "high",
                {
                    "remote_path_share": remote_path,
                    "remote_to_final_rows_ratio": remote_final,
                    "wan_output_to_final_rows_ratio": wan_final,
                },
            )
        )

    if global_merge is not None and global_merge >= 100:
        rows.append(
            tag(
                "final_reduction",
                "Globalna/finalna redukcija",
                "extreme" if global_merge >= 10_000 else "high",
                {"global_group_merge_ratio": global_merge},
            )
        )

    if (temp_final is not None and temp_final >= 100) or (
        temp_wan_bytes is not None and temp_wan_bytes >= 1
    ):
        rows.append(
            tag(
                "memory_spill",
                "Normalizovani spill intenzitet",
                "high",
                {
                    "temp_blocks_per_final_row": temp_final,
                    "temp_bytes_to_wan_bytes_ratio": temp_wan_bytes,
                },
            )
        )

    if (region_isf is not None and region_isf >= 1.5) or (
        task_isf is not None and task_isf >= 1.5
    ):
        rows.append(
            tag(
                "skew_imbalance",
                "Skew i neravnoteža po regionima/taskovima",
                "high",
                {
                    "remote_region_rows_isf": region_isf,
                    "worker_task_scan_rows_isf": task_isf,
                },
            )
        )

    if repartition is not None and repartition >= 1:
        rows.append(
            tag(
                "repartition_locality",
                "Repartition/lokalnost signal",
                "present",
                {"citus_repartition_query": repartition},
            )
        )

    if estimate_errors and max(estimate_errors) >= 3:
        rows.append(
            tag(
                "estimate_error",
                "Greška procjene redova",
                "high",
                {"max_abs_estimate_error_log": max(estimate_errors)},
            )
        )

    if not rows:
        rows.append(
            tag(
                "no_strong_mechanism",
                "Nema snažnog izolovanog mehanizma",
                "weak",
                {},
            )
        )
    return rows
