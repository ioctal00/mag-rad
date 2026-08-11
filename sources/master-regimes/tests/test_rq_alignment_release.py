from __future__ import annotations

import csv
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "releases/rq-alignment-v1"


def read_csv(name: str) -> list[dict[str, str]]:
    with (RELEASE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_frozen_feature_contract_is_documented() -> None:
    families = read_csv("rq1_feature_families.csv")
    indicators = {
        indicator
        for row in families
        for indicator in row["indicators"].split(";")
    }
    assert len(families) == 6
    assert len(indicators) == 21
    assert "remote_path_share" in indicators
    assert "worker_task_scan_rows_isf" in indicators
    assert "citus_repartition_query" in indicators


def test_ratio_first_audit_and_k4_decision_are_frozen() -> None:
    feature_spaces = {
        row["model"]: row for row in read_csv("rq1_feature_space_audit.csv")
    }
    assert math.isclose(
        float(feature_spaces["flow_ratio_v3_reduced"]["dataset_id_nmi"]), 0.001
    )
    model_audit = read_csv("rq2_fcm_model_audit.csv")
    selected = [row for row in model_audit if row["decision"].startswith("selected")]
    assert len(selected) == 1
    assert selected[0]["k"] == "4"
    assert math.isclose(float(selected[0]["seed_ari"]), 1.0)


def test_mixed_case_preserves_secondary_membership() -> None:
    rows = read_csv("rq3_mixed_case_memberships.csv")
    memberships = sorted((float(row["membership"]), row["regime_id"]) for row in rows)
    assert len(rows) == 4
    assert math.isclose(sum(value for value, _ in memberships), 1.0)
    top, second = memberships[-1], memberships[-2]
    assert top[1] == "R1"
    assert second[1] == "R2"
    assert top[0] - second[0] < 0.006
    assert sum(int(row["hard_assignment"]) for row in rows) == 1


def test_feature_support_has_opposing_physical_evidence() -> None:
    rows = read_csv("rq3_mixed_case_feature_support.csv")
    assert {row["direction"] for row in rows} == {"R1", "R2"}
    strongest = max(rows, key=lambda row: abs(float(row["support"])))
    assert strongest["feature"] == "worker_task_scan_rows_isf"
    assert float(strongest["support"]) < 0


def test_threshold_rows_cover_the_frozen_corpus() -> None:
    rows = read_csv("rq3_threshold_audit.csv")
    assert sum(int(row["row_count"]) for row in rows) == 1964
    assert math.isclose(sum(float(row["share"]) for row in rows), 1.0)
