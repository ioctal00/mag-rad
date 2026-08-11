from __future__ import annotations

import csv
from pathlib import Path

from master_regimes.workload import render_workload


def test_render_workload_writes_corpus_metadata(tmp_path: Path) -> None:
    registry = tmp_path / "suite.yml"
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "query.sql.j2").write_text("select {{ limit_k }};\n", encoding="utf-8")
    registry.write_text(
        """
templates:
  q_top:
    file: templates/query.sql.j2
    family: topk
    logical_question_id: top_tenants
    execution_strategy: fdw_raw
    expected_pressure_tags:
      - topk
      - fdw_remote_scan
    expected_regime_targets:
      - remote_fetch_heavy
      - gac_finalization_heavy
    runtime_sensitivity:
      fetch_size: high
      work_mem: high
      wan_latency: high
    required_dataset_capabilities:
      - supports_hot_tenants
    parameters:
      limit_k: [10]
""",
        encoding="utf-8",
    )

    manifest = render_workload(
        registry_path=registry,
        output_dir=tmp_path / "rendered",
        max_instances=None,
    )

    rows = list(csv.DictReader(manifest.open(newline="", encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["logical_question_id"] == "top_tenants"
    assert rows[0]["execution_strategy"] == "fdw_raw"
    assert rows[0]["expected_regime_targets"] == (
        "remote_fetch_heavy,gac_finalization_heavy"
    )
    assert rows[0]["runtime_sensitivity"] == (
        '{"fetch_size":"high","wan_latency":"high","work_mem":"high"}'
    )
    assert rows[0]["required_dataset_capabilities"] == "supports_hot_tenants"
