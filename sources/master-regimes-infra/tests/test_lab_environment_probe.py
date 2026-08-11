from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "probe_lab_environment", ROOT / "common-scripts" / "probe_lab_environment.py"
)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


def payload(*, netem: bool = False, fdw_fetch_size: bool = False) -> dict[str, str]:
    options = ["host=10.0.0.1"]
    if fdw_fetch_size:
        options.append("fetch_size=1000")
    return {
        "SETTINGS": json.dumps(
            [
                {
                    "name": "work_mem",
                    "setting": "4096",
                    "unit": "kB",
                    "source": "default",
                    "boot_value": "4096",
                    "reset_value": "4096",
                }
            ]
        ),
        "CITUS": "12.1-1",
        "FDW": json.dumps([{"server": "eu_server", "options": options}]),
        "TC": base64.b64encode(("qdisc netem 1: root" if netem else "qdisc fq_codel 0: root").encode()).decode(),
    }


def test_probe_classifies_network_and_fdw_interventions_as_attention() -> None:
    node = {"node_id": "eu-coord-1", "layer": "regional_coordinator", "region": "eu", "database": "app"}
    result = PROBE.classify_node(node, payload(netem=True, fdw_fetch_size=True))

    assert result["status"] == "attention"
    assert result["network"]["netemActive"] is True
    assert any("fetch_size" in deviation for deviation in result["deviations"])


def test_audit_is_verified_only_when_every_node_has_no_deviation() -> None:
    node = {"node_id": "eu-coord-1", "layer": "regional_coordinator", "region": "eu", "database": "app"}
    verified = PROBE.classify_node(node, payload())
    audit = PROBE.build_audit([verified], datetime(2026, 8, 8, tzinfo=UTC))

    assert audit["status"] == "verified"
    assert audit["summary"] == {"nodeCount": 1, "verifiedCount": 1, "attentionCount": 0, "failedCount": 0}


def test_make_target_runs_read_only_probe() -> None:
    completed = subprocess.run(
        ["make", "-n", "eu-us-gac-vps-lab-environment-probe"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "probe_lab_environment.py" in completed.stdout
    assert "lab-environment-probes" in completed.stdout
