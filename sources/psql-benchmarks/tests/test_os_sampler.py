from __future__ import annotations

from psql_benchmarks.os_sampler import _summarize_sample_rows


def test_summary_reports_cpu_steal_separately_from_busy_share() -> None:
    first = {
        "ts_unix": 1.0,
        "cpu": {
            "user": 100,
            "system": 50,
            "idle": 800,
            "iowait": 20,
            "steal": 30,
        },
        "meminfo_kb": {},
        "net": {},
        "tcp": {},
        "disk": {},
    }
    last = {
        "ts_unix": 2.0,
        "cpu": {
            "user": 140,
            "system": 60,
            "idle": 840,
            "iowait": 20,
            "steal": 40,
        },
        "meminfo_kb": {},
        "net": {},
        "tcp": {},
        "disk": {},
    }

    summary = _summarize_sample_rows([first, last])

    assert summary["cpu_busy_pct"] == 60.0
    assert summary["cpu_steal_pct"] == 10.0
