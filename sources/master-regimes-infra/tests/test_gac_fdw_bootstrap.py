from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "common-scripts"
        / "run_gac_fdw_bootstrap.py"
    )
    spec = importlib.util.spec_from_file_location(
        "run_gac_fdw_bootstrap",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_join_views_are_explicit_fdw_imports() -> None:
    module = _load_module()

    assert "mr_joined_events_colocated" in module.FDW_TABLES
    assert "mr_joined_events_repartition" in module.FDW_TABLES
    sql = module.regional_join_views_sql()
    assert "JOIN public.users" in sql
    assert "JOIN public.global_users" in sql
    assert "CREATE OR REPLACE VIEW public.mr_joined_events_colocated" in sql
    assert "CREATE OR REPLACE VIEW public.mr_joined_events_repartition" in sql
