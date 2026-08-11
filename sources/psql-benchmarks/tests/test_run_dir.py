from __future__ import annotations

from src.psql_benchmarks.run_dir import _safe_label


def test_long_run_label_is_shortened_deterministically() -> None:
    label = "regional-memory-equivalence-" * 20

    first = _safe_label(label)
    second = _safe_label(label)

    assert first == second
    assert len(first.encode("utf-8")) <= 160
    assert "--" in first
