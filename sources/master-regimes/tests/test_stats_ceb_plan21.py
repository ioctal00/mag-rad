from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "analysis" / "scripts" / "agent" / "58_stats_ceb_portability_pilot.py"


def load_script():
    spec = importlib.util.spec_from_file_location("stats_ceb_plan21", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_query_id_is_extracted_from_rendered_instance() -> None:
    module = load_script()
    assert (
        module.query_id_from_instance(
            "stats_ceb_external_strategy_pilot__"
            "stats_ceb_multiregion_count__query_id-130"
        )
        == 130
    )


def test_expected_strategy_compatibility_is_explicit() -> None:
    module = load_script()
    assert module.strategy_compatible(
        "repartition_candidate",
        "repartition_mapmerge",
    )
    assert module.strategy_compatible(
        "wide_colocated_reference",
        "colocated_join_candidate,reference_join_candidate,router_single_task",
    )
    assert not module.strategy_compatible(
        "colocated_post_join",
        "repartition_mapmerge",
    )


def test_boolean_values_are_parsed_without_string_truthiness() -> None:
    module = load_script()
    assert module.as_bool(True)
    assert module.as_bool("true")
    assert not module.as_bool(False)
    assert not module.as_bool("False")
