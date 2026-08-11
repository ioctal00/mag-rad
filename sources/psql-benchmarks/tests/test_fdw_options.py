from __future__ import annotations

from psql_benchmarks.fdw import _parse_key_value_options


def test_libpq_session_options_are_allowed_for_fdw_server() -> None:
    assert _parse_key_value_options(["options=-c work_mem=64kB"]) == {
        "options": "-c work_mem=64kB"
    }
