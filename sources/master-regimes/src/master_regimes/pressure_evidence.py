from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

PRESSURE_EVIDENCE_CONTRACT = "feature_first_multi_label_pressure_evidence_v1"
PRESSURE_MODEL_ROLE = "posthoc_feature_first_evidence_not_clustering_input"


@dataclass(frozen=True)
class PressureFeature:
    name: str
    mode: str = "high"
    weight: float = 1.0


@dataclass(frozen=True)
class PressureFamily:
    pressure_id: str
    label: str
    focus: str
    features: tuple[PressureFeature, ...]


PRESSURE_FAMILIES: tuple[PressureFamily, ...] = (
    PressureFamily(
        pressure_id="remote_fanin",
        label="FDW/WAN prenos prema GAC-u",
        focus="Provjeri količinu regionalnog/FDW izlaza koji prelazi FDW/WAN granicu prema GAC-u.",
        features=(
            PressureFeature("remote_path_share", weight=0.25),
            PressureFeature("remote_to_final_rows_ratio"),
            PressureFeature("wan_output_to_final_rows_ratio"),
        ),
    ),
    PressureFamily(
        pressure_id="gac_finalization",
        label="Globalna finalizacija",
        focus=(
            "Pregledaj globalni GROUP/ORDER/LIMIT dio plana i rad nakon izlaza "
            "iz regionalnog/FDW sloja."
        ),
        features=(
            PressureFeature("global_group_merge_ratio"),
            PressureFeature("temp_blocks_per_final_row", weight=0.5),
            PressureFeature("aggregate_rows_estimate_error_log", mode="abs", weight=0.5),
        ),
    ),
    PressureFamily(
        pressure_id="spill",
        label="Spill",
        focus="Provjeri work_mem, hash/sort operatore i privremene blokove.",
        features=(
            PressureFeature("spill_per_wan_mb"),
            PressureFeature("temp_blocks_per_wan_row"),
            PressureFeature("temp_blocks_per_final_row"),
            PressureFeature("hash_batches_max"),
        ),
    ),
    PressureFamily(
        pressure_id="skew",
        label="Skew po regionima i worker taskovima",
        focus="Provjeri tenant/regionalnu distribuciju i shard/task neravnotežu.",
        features=(
            PressureFeature("remote_region_rows_isf"),
            PressureFeature("worker_task_scan_rows_isf"),
            PressureFeature("worker_task_scan_actual_rows_max_share"),
        ),
    ),
    PressureFamily(
        pressure_id="topology_task",
        label="Citus task/topologija",
        focus=(
            "Provjeri širinu Citus task izvršavanja, shard locality i "
            "repartition/map-merge signale."
        ),
        features=(
            PressureFeature("task_count_to_shard_count_ratio"),
            PressureFeature("active_task_share"),
            PressureFeature("citus_repartition_query", mode="binary"),
        ),
    ),
    PressureFamily(
        pressure_id="estimate_error",
        label="Greška procjene plana",
        focus="Provjeri stale statistike, kardinalitet procjene i plan-choice nestabilnost.",
        features=(
            PressureFeature("root_rows_estimate_error_log", mode="abs"),
            PressureFeature("foreign_scan_rows_estimate_error_log", mode="abs"),
            PressureFeature("aggregate_rows_estimate_error_log", mode="abs"),
            PressureFeature("remote_root_rows_estimate_error_log", mode="abs"),
        ),
    ),
)


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def _numeric(frame: pd.DataFrame, feature: str, mode: str) -> pd.Series:
    if feature not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    values = pd.to_numeric(frame[feature], errors="coerce")
    if mode == "abs":
        return values.abs()
    if mode == "binary":
        return values.where(values.isna(), values.gt(0).astype(float))
    return values


def _series_thresholds(values: pd.Series) -> dict[str, float | None]:
    non_null = values.replace([np.inf, -np.inf], np.nan).dropna()
    if non_null.empty:
        return {"p50": None, "p75": None, "p90": None}
    return {
        "p50": float(non_null.quantile(0.50)),
        "p75": float(non_null.quantile(0.75)),
        "p90": float(non_null.quantile(0.90)),
    }


def build_pressure_thresholds(
    raw_features: pd.DataFrame,
    families: tuple[PressureFamily, ...] = PRESSURE_FAMILIES,
) -> dict[str, dict[str, float | None]]:
    thresholds: dict[str, dict[str, float | None]] = {}
    for family in families:
        for feature in family.features:
            key = f"{feature.name}::{feature.mode}"
            if key in thresholds:
                continue
            thresholds[key] = _series_thresholds(_numeric(raw_features, feature.name, feature.mode))
    return thresholds


def _feature_score(
    value: float | None,
    thresholds: dict[str, float | None],
    mode: str,
) -> float | None:
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    if mode == "binary":
        return 1.0 if value > 0 else 0.0

    p50 = thresholds.get("p50")
    p75 = thresholds.get("p75")
    p90 = thresholds.get("p90")
    if p50 is None or p75 is None or p90 is None:
        return None

    if p90 <= p50:
        return 1.0 if value > p90 else 0.0
    if value <= p50:
        return 0.0
    if value <= p75:
        denominator = p75 - p50
        if denominator <= 0:
            return 0.5
        return 0.5 * (value - p50) / denominator
    if value <= p90:
        denominator = p90 - p75
        if denominator <= 0:
            return 0.75
        return 0.5 + 0.5 * (value - p75) / denominator
    return 1.0


def pressure_status(score: float | None, measured_feature_count: int) -> tuple[str, str]:
    if measured_feature_count == 0 or score is None:
        return "not_measured", "nije mjereno"
    if score >= 0.75:
        return "confirmed", "potvrđeno"
    if score >= 0.40:
        return "partially_confirmed", "djelimično potvrđeno"
    if score >= 0.15:
        return "weak", "slabo"
    return "contradicted", "nije potvrđeno"


def _feature_evidence_items(
    row: pd.Series,
    family: PressureFamily,
    thresholds: dict[str, dict[str, float | None]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for feature in family.features:
        raw_value = clean_value(row.get(feature.name))
        value = None if raw_value is None else float(raw_value)
        if value is not None and feature.mode == "abs":
            value = abs(value)
        if value is not None and feature.mode == "binary":
            value = 1.0 if value > 0 else 0.0
        key = f"{feature.name}::{feature.mode}"
        score = _feature_score(value, thresholds.get(key, {}), feature.mode)
        weighted_score = None if score is None else max(0.0, min(1.0, score * feature.weight))
        items.append(
            {
                "feature": feature.name,
                "mode": feature.mode,
                "weight": feature.weight,
                "raw_value": raw_value,
                "effective_value": clean_value(value),
                "feature_score": clean_value(score),
                "weighted_score": clean_value(weighted_score),
                "thresholds": thresholds.get(key, {}),
            }
        )
    return items


def _family_score(items: list[dict[str, Any]]) -> float | None:
    scores = [
        float(item["weighted_score"])
        for item in items
        if item.get("weighted_score") is not None
    ]
    if not scores:
        return None
    return max(scores)


def _reason(status: str, family: PressureFamily, dominant_feature: str | None) -> str:
    if status == "confirmed":
        return f"{family.label} je snažno potvrđen preko pokazatelja `{dominant_feature}`."
    if status == "partially_confirmed":
        return f"{family.label} ima vidljiv, ali ne dominantan feature-first signal."
    if status == "weak":
        return f"{family.label} ima slab feature-first signal."
    if status == "contradicted":
        return f"{family.label} nije povišen prema dostupnim pokazateljima."
    return f"{family.label} nije moguće procijeniti jer relevantni pokazatelji nisu dostupni."


def build_pressure_evidence(
    raw_features: pd.DataFrame,
    *,
    query_id_column: str = "query_run_id",
    families: tuple[PressureFamily, ...] = PRESSURE_FAMILIES,
    thresholds: dict[str, dict[str, float | None]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if query_id_column not in raw_features.columns:
        raise KeyError(f"Missing required column: {query_id_column}")

    thresholds = thresholds or build_pressure_thresholds(raw_features, families)
    rows: list[dict[str, Any]] = []
    wide_rows: list[dict[str, Any]] = []

    for _, row in raw_features.iterrows():
        query_run_id = str(row[query_id_column])
        wide: dict[str, Any] = {"query_run_id": query_run_id}
        for family in families:
            items = _feature_evidence_items(row, family, thresholds)
            measured = [item for item in items if item.get("feature_score") is not None]
            score = _family_score(items)
            status, status_label = pressure_status(score, len(measured))
            dominant = None
            if measured:
                dominant = max(
                    measured,
                    key=lambda item: float(item.get("weighted_score") or 0.0),
                )
            dominant_feature = str(dominant["feature"]) if dominant else None
            dominant_value = dominant.get("raw_value") if dominant else None
            dominant_score = dominant.get("weighted_score") if dominant else None
            band = (
                "high"
                if score is not None and score >= 0.75
                else "medium"
                if score is not None and score >= 0.40
                else "low"
                if score is not None
                else "not_measured"
            )

            rows.append(
                {
                    "query_run_id": query_run_id,
                    "pressure_contract": PRESSURE_EVIDENCE_CONTRACT,
                    "pressure_model_role": PRESSURE_MODEL_ROLE,
                    "pressure_id": family.pressure_id,
                    "pressure_label": family.label,
                    "pressure_score": clean_value(score),
                    "pressure_band": band,
                    "pressure_status": status,
                    "pressure_status_label": status_label,
                    "measured_feature_count": len(measured),
                    "configured_feature_count": len(items),
                    "dominant_feature": dominant_feature,
                    "dominant_feature_value": clean_value(dominant_value),
                    "dominant_feature_score": clean_value(dominant_score),
                    "recommended_focus": (
                        family.focus if status in {"confirmed", "partially_confirmed"} else ""
                    ),
                    "reason": _reason(status, family, dominant_feature),
                    "feature_evidence_json": json.dumps(items, ensure_ascii=False, sort_keys=True),
                }
            )
            wide[f"{family.pressure_id}_score"] = clean_value(score)
            wide[f"{family.pressure_id}_status"] = status
            wide[f"{family.pressure_id}_dominant_feature"] = dominant_feature
        wide_rows.append(wide)

    return pd.DataFrame(rows), pd.DataFrame(wide_rows)
