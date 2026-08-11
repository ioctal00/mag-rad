from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "common-scripts"
        / "run_database_sweep.py"
    )
    spec = importlib.util.spec_from_file_location("run_database_sweep", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_regional_pg_options_are_encoded_for_remote_fdw_session() -> None:
    module = _load_module()

    options = module.apply_regional_pg_options_to_fdw(
        {"fetch_size": "500"},
        {"work_mem": "64kB", "statement_timeout": "300000"},
    )

    assert options == {
        "fetch_size": "500",
        "options": "-c statement_timeout=300000 -c work_mem=64kB",
    }


def test_existing_libpq_options_are_preserved() -> None:
    module = _load_module()

    options = module.apply_regional_pg_options_to_fdw(
        {"options": "-c application_name=probe"},
        {"work_mem": "256MB"},
    )

    assert options["options"] == "-c application_name=probe -c work_mem=256MB"
