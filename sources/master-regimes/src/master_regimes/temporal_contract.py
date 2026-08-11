"""Deterministic dataset/query time contracts used by thesis experiments."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

WALL_CLOCK_SQL_PATTERN = re.compile(
    r"\b(?:now\s*\(|current_timestamp\b|clock_timestamp\s*\(|"
    r"statement_timestamp\s*\(|transaction_timestamp\s*\()",
    flags=re.IGNORECASE,
)


def parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include an explicit UTC offset: {value!r}")
    return parsed.astimezone(UTC)


def dataset_anchor(base_time_unix: int) -> datetime:
    if int(base_time_unix) <= 0:
        raise ValueError("base_time_unix must be a positive frozen timestamp")
    return datetime.fromtimestamp(int(base_time_unix), tz=UTC)


def cutoff_offset_days(base_time_unix: int, cutoff_ts: str) -> int:
    delta = dataset_anchor(base_time_unix) - parse_utc_timestamp(cutoff_ts)
    seconds = delta.total_seconds()
    if seconds < 0 or seconds % 86400 != 0:
        raise ValueError(
            "cutoff_ts must be an integral non-negative day offset from base_time_unix"
        )
    return int(seconds // 86400)


def validate_dataset_time_contract(contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        anchor = dataset_anchor(int(contract.get("base_time_unix", 0)))
    except (TypeError, ValueError) as exc:
        return [str(exc)]

    try:
        declared_anchor = parse_utc_timestamp(str(contract.get("base_time_utc", "")))
    except ValueError as exc:
        errors.append(str(exc))
    else:
        if declared_anchor != anchor:
            errors.append("base_time_utc does not match base_time_unix")

    lookback_days = int(contract.get("generated_lookback_days", 0) or 0)
    if lookback_days <= 0:
        errors.append("generated_lookback_days must be positive")
    offsets = contract.get("allowed_cutoff_offsets_days")
    if not isinstance(offsets, list) or not offsets:
        errors.append("allowed_cutoff_offsets_days must be a non-empty list")
    elif any(int(offset) < 0 for offset in offsets):
        errors.append("cutoff offsets must be non-negative")
    if contract.get("wall_clock_functions_allowed_in_measured_sql") is not False:
        errors.append("measured SQL must not depend on wall-clock functions")
    return errors


def validate_cutoff_against_contract(cutoff_ts: str, contract: Mapping[str, Any]) -> list[str]:
    try:
        offset = cutoff_offset_days(int(contract["base_time_unix"]), cutoff_ts)
    except (KeyError, TypeError, ValueError) as exc:
        return [str(exc)]
    allowed = {int(value) for value in contract.get("allowed_cutoff_offsets_days", [])}
    if offset not in allowed:
        return [f"cutoff offset {offset} days is not allowed by the frozen contract"]
    return []


def wall_clock_functions(sql: str) -> list[str]:
    return [match.group(0) for match in WALL_CLOCK_SQL_PATTERN.finditer(sql)]


def cutoff_timestamp(base_time_unix: int, offset_days: int) -> datetime:
    if int(offset_days) < 0:
        raise ValueError("offset_days must be non-negative")
    return dataset_anchor(base_time_unix) - timedelta(days=int(offset_days))
