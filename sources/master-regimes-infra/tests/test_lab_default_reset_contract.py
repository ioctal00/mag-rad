from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_viewer_default_reset_covers_both_network_directions() -> None:
    completed = subprocess.run(
        ["make", "-n", "eu-us-gac-vps-network-default-reset"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    output = completed.stdout

    assert "manage_network_latency.py" in output
    assert '"scope":"analytics_egress_to_region"' in output
    assert "manage_network_pressure.py" in output
    assert '"scope":"region_egress_to_analytics"' in output
    assert output.count("--action reset") == 2
    assert '"target_region_ids":["eu","us","apac"]' in output
