from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE_12_PATH = ROOT / "analysis/scripts/agent/12_corpus_coverage_gate.py"


def _load_phase12():
    script_dir = str(PHASE_12_PATH.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location("phase12_corpus_coverage_gate", PHASE_12_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase12_filters_cells_by_execution_class_scope() -> None:
    phase12 = _load_phase12()
    cells = [
        {"corpus_cell_id": "pilot-a"},
        {"corpus_cell_id": "pilot-b", "execution_class": "pilot"},
        {"corpus_cell_id": "long-a", "execution_class": "long_budget"},
    ]

    assert [
        cell["corpus_cell_id"]
        for cell in phase12._filter_cells_by_execution_class(
            cells,
            phase12._parse_execution_classes("pilot"),
        )
    ] == ["pilot-a", "pilot-b"]
    assert [
        cell["corpus_cell_id"]
        for cell in phase12._filter_cells_by_execution_class(
            cells,
            phase12._parse_execution_classes("pilot,long_budget"),
        )
    ] == ["pilot-a", "pilot-b", "long-a"]
    assert [
        cell["corpus_cell_id"]
        for cell in phase12._filter_cells_by_execution_class(
            cells,
            phase12._parse_execution_classes("all"),
        )
    ] == ["pilot-a", "pilot-b", "long-a"]


def test_phase12_marks_excluded_representative_templates_as_context() -> None:
    phase12 = _load_phase12()
    pilot_cells = [{"template_id": "pilot_template"}]
    all_cells = [
        {"template_id": "pilot_template"},
        {"template_id": "long_budget_template", "execution_class": "long_budget"},
    ]
    rows = phase12._coverage_matrix_rows(
        {
            "coverage_cells": [
                {
                    "coverage_cell_id": "long_budget_case",
                    "current_status": "weak",
                    "representative_templates": ["long_budget_template"],
                },
                {
                    "coverage_cell_id": "missing_case",
                    "current_status": "weak",
                    "representative_templates": ["not_in_manifest"],
                },
            ]
        },
        pilot_cells,
        all_cells=all_cells,
    )
    gates = {row[0]: row[6] for row in rows}

    assert gates["long_budget_case"] == "context"
    assert gates["missing_case"] == "warn"


def test_phase12_design_only_report_does_not_mark_planned_cells_missing(tmp_path: Path) -> None:
    phase12 = _load_phase12()
    manifest = tmp_path / "corpus.yml"
    coverage = tmp_path / "regime-coverage.yml"
    index_dir = tmp_path / "_index"
    manifest.write_text(
        """
corpus_id: test-corpus
cells:
  - corpus_cell_id: c1
    logical_question_id: top_tenants
    execution_strategy: fdw_raw
    template_id: gac_fdw_top_tenants
    dataset_profile_id: d1
    runtime_config_id: default
    expected_regime_targets: [remote_fetch_heavy]
""".lstrip(),
        encoding="utf-8",
    )
    coverage.write_text("coverage_cells: []\n", encoding="utf-8")
    index_dir.mkdir()

    report = phase12.build_report(index_dir, manifest, coverage)

    assert "design_only_no_observed_index_rows" in report
    assert "planned cells are not marked missing in design-only mode" in report
    assert "missing_planned_cells | not_evaluated" in report
