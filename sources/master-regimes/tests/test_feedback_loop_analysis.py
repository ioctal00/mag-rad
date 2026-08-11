from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs/validation/feedback_loop_analysis_v1.yml"
RELEASE = ROOT / "releases/feedback-loop-analysis-v1"


def read_csv(name: str) -> list[dict[str, str]]:
    with (RELEASE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_frozen_six_domain_contract() -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert contract["policy"]["fixed_domains"] == [
        "remote_fdw_path",
        "regional_reduction",
        "gac_finalization",
        "imbalance",
        "disk_spill",
        "repartition_locality",
    ]
    assert contract["policy"]["refit_frozen_representation"] is False
    assert contract["policy"]["future_outcomes_allowed"] is False
    assert contract["policy"]["missing_outcome_as_zero"] is False


def test_local_memory_is_temporal_and_preserves_missingness() -> None:
    rows = read_csv("local_memory_replay.csv")
    assert len(rows) == 8
    assert all(int(row["future_outcome_count_used"]) == 0 for row in rows)
    assert all(row["missing_outcome_imputed_as_zero"] == "False" for row in rows)
    assert all(
        row["replay_outcomes_added_during_frozen_replay"] == "False" for row in rows
    )
    abstentions = [row for row in rows if row["recommendation_status"] == "abstained"]
    assert len(abstentions) == 4
    assert all(row["estimated_log2_gain"] == "" for row in abstentions)


def test_transition_and_projection_counts() -> None:
    transitions = read_csv("table_transition_summary.csv")
    assert sum(row["phase"] == "adaptive" for row in transitions) == 5
    assert sum(row["phase"] == "frozen_replay" for row in transitions) == 3
    assert (
        sum(row["phase"] == "aggregate_exact_confirmatory" for row in transitions)
        == 3
    )
    assert all(row["result_validity_axis"] for row in transitions)
    assert all(row["end_to_end_effect_axis"] for row in transitions)
    assert all(row["physical_transition_axis"] for row in transitions)
    projections = read_csv("cluster_projection_audit.csv")
    states = [row for row in projections if row["record_type"] == "state_projection"]
    transition_rows = [
        row for row in projections if row["record_type"] == "transition_projection"
    ]
    assert len(states) == 15
    assert len(transition_rows) == 8
    assert all(row["frozen_representation_refit"] == "False" for row in projections)


def test_exact_aggregate_addendum_preserves_logical_identity() -> None:
    states = read_csv("trajectory_domain_profiles.csv")
    exact = [
        row for row in states if row["phase"] == "aggregate_exact_confirmatory"
    ]
    assert len(exact) == 5
    assert {
        row["logical_question_id"] for row in exact
    } == {"event_exact_full_flow_summary"}


def test_rq_h_formulations_are_complete_and_unchanged_by_analysis() -> None:
    rows = read_csv("rq_hypothesis_evidence_map.csv")
    assert [row["item"] for row in rows] == [
        "RQ1",
        "RQ2",
        "RQ3",
        "RQ4",
        "H1",
        "H2",
        "H3",
        "H4",
    ]
    assert all(row["fixed_statement"].strip() for row in rows)
    audit = json.loads((RELEASE / "numerical_consistency_audit.json").read_text())
    assert audit["fixed_rq_h_text_exact"] is True


def test_release_checksums() -> None:
    lines = (RELEASE / "checksums.sha256").read_text(encoding="utf-8").splitlines()
    assert lines
    for line in lines:
        expected, relative = line.split("  ", 1)
        target = RELEASE / relative
        assert target.exists()
        assert hashlib.sha256(target.read_bytes()).hexdigest() == expected


def test_numerical_consistency_gate_passes() -> None:
    audit = json.loads((RELEASE / "numerical_consistency_audit.json").read_text())
    assert audit["pass"] is True
    assert all(value is True for key, value in audit.items() if key != "pass")


def test_figure_decimal_labels_use_bosnian_separator() -> None:
    decimal_dot = re.compile(r"<!--\s*[−-]?\d+\.\d+\s*-->")
    for name in ("figure_regime_trajectory.svg", "figure_runtime_and_domains.svg"):
        source = (RELEASE / name).read_text(encoding="utf-8")
        assert decimal_dot.search(source) is None
        assert re.search(r"<!--\s*[−-]?\d+,\d+\s*-->", source) is not None
