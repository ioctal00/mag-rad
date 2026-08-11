from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import yaml

from master_regimes.corpus_adapter import render_corpus
from master_regimes.dataset_profile import validate_dataset_profile
from master_regimes.stats_ceb import (
    prepare_full_selection,
    prepare_holdout_selection,
    run_admission_gate,
)

ROOT = Path(__file__).resolve().parents[1]


def _digest(value: bytes, algorithm: str) -> str:
    return hashlib.new(algorithm, value).hexdigest()


def test_stats_ceb_admission_rejects_no_pinned_inputs(tmp_path: Path) -> None:
    sql = b"SELECT COUNT(*) FROM users AS u WHERE u.UpVotes >= 0;\n"
    cache = tmp_path / "cache"
    cache.mkdir()
    queries_path = cache / "queries.zip"
    with zipfile.ZipFile(queries_path, "w") as archive:
        archive.writestr("stats/q-1.sql", sql)
    schema_path = cache / "schema-postgres.sql"
    schema_path.write_bytes(b"CREATE TABLE users (id int);\n")
    expected_path = cache / "stats_CEB.sql"
    expected_path.write_bytes(b"7||SELECT COUNT(*) FROM users AS u WHERE u.UpVotes >= 0;\n")

    source_dir = tmp_path / "source"
    selected_dir = source_dir / "selected-queries"
    selected_dir.mkdir(parents=True)
    (selected_dir / "q-1.sql").write_bytes(sql)
    source_lock = {
        "source_id": "test",
        "resources": {
            "queries": {
                "url": "https://invalid.test/queries.zip",
                "filename": queries_path.name,
                "md5": _digest(queries_path.read_bytes(), "md5"),
                "sha256": _digest(queries_path.read_bytes(), "sha256"),
            },
            "schema": {
                "url": "https://invalid.test/schema.sql",
                "filename": schema_path.name,
                "md5": _digest(schema_path.read_bytes(), "md5"),
                "sha256": _digest(schema_path.read_bytes(), "sha256"),
            },
            "expected_results": {
                "url": "https://invalid.test/stats_CEB.sql",
                "filename": expected_path.name,
                "sha256": _digest(expected_path.read_bytes(), "sha256"),
            },
            "dump": {
                "url": "https://invalid.test/stats_dump.pg",
                "filename": "stats_dump.pg",
                "md5": "0" * 32,
            },
        },
        "contracts": {
            "archive_query_count": 1,
            "query_archive_prefix": "stats/",
        },
    }
    selection = {
        "selection_id": "test",
        "queries": [
            {
                "query_id": 1,
                "expected_count": 7,
                "source_sha256": _digest(sql, "sha256"),
                "expected_citus_strategy": "reference_only",
                "tables": ["users"],
            }
        ],
    }
    source_lock_path = source_dir / "source-lock.yml"
    selection_path = source_dir / "query-selection.yml"
    source_lock_path.write_text(yaml.safe_dump(source_lock), encoding="utf-8")
    selection_path.write_text(yaml.safe_dump(selection), encoding="utf-8")

    output = run_admission_gate(
        source_lock_path=source_lock_path,
        selection_path=selection_path,
        cache_dir=cache,
        out_dir=tmp_path / "report",
    )

    decision = json.loads((output / "go_no_go.json").read_text(encoding="utf-8"))
    assert decision["decision"] == "GO"
    assert decision["dump_downloaded"] is False


def test_external_stats_dataset_profile_validates() -> None:
    profile_path = ROOT / "datasets" / "profiles" / "stats-ceb-replicated.yml"
    result = validate_dataset_profile(profile_path)
    assert result["status"] == "ok", result["errors"]

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    selection = yaml.safe_load(
        (ROOT / "external" / "stats-ceb" / "query-selection.yml").read_text(
            encoding="utf-8"
        )
    )
    assert "tags" in profile["physical_design"]["reference_tables"]
    assert "tags" not in profile["physical_design"]["distributed_tables"]
    assert profile["physical_design"] == selection["physical_design"]


def test_stats_corpus_renders_eight_frozen_queries(tmp_path: Path) -> None:
    plan_path = render_corpus(
        manifest_path=(
            ROOT
            / "workloads"
            / "corpus"
            / "corpus_manifest.stats-ceb-portability-v1.yml"
        ),
        output_dir=tmp_path / "rendered",
        include_execution_classes={"pilot"},
    )
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    sweep_path = ROOT.parent / plan["groups"][0]["sweep_config"]
    sweep = yaml.safe_load(sweep_path.read_text(encoding="utf-8"))

    assert plan["groups"][0]["instance_count"] == 8
    assert plan["groups"][0]["dataset_adapter"] == "stats_ceb"
    assert sweep["datasets"][0]["adapter"] == "stats_ceb"
    assert sweep["collection"]["fdw_bootstrap"]["adapter"] == "stats_ceb"
    assert sweep["collection"]["correctness_validation"]["adapter"] == "stats_ceb"


def test_semantic_v2_holdout_selection_is_deterministic_and_disjoint(
    tmp_path: Path,
) -> None:
    selection_path = tmp_path / "query-selection.semantic-v2-holdout.yml"
    output = prepare_holdout_selection(
        source_lock_path=ROOT / "external/stats-ceb/source-lock.yml",
        development_selection_path=ROOT / "external/stats-ceb/query-selection.yml",
        cache_dir=ROOT / "tmp/stats-ceb",
        selection_path=selection_path,
        selected_query_dir=tmp_path / "selected-queries",
        fragments_dir=tmp_path / "fragments",
        seed="stats-ceb-semantic-v2-holdout",
        table_count_quotas={2: 2, 3: 3, 4: 3, 5: 2, 6: 2},
    )
    selection = yaml.safe_load(output.read_text(encoding="utf-8"))
    query_ids = [int(item["query_id"]) for item in selection["queries"]]
    development = yaml.safe_load(
        (ROOT / "external/stats-ceb/query-selection.yml").read_text(
            encoding="utf-8"
        )
    )
    development_ids = {
        int(item["query_id"]) for item in development["queries"]
    }

    assert query_ids == [2, 6, 24, 94, 8, 38, 86, 35, 109, 129, 76, 74]
    assert not development_ids.intersection(query_ids)
    assert selection["selection_method"]["outcome_fields_used_for_selection"] == []
    assert selection["model_contract"]["refit_allowed"] is False
    for query_id in query_ids:
        fragment = (tmp_path / "fragments" / f"q-{query_id}.sql.j2").read_text(
            encoding="utf-8"
        )
        assert "count(*) as result_count" in fragment
        assert "{{ schema_name }}." in fragment

    report = run_admission_gate(
        source_lock_path=ROOT / "external/stats-ceb/source-lock.yml",
        selection_path=selection_path,
        cache_dir=ROOT / "tmp/stats-ceb",
        out_dir=tmp_path / "admission",
    )
    decision = json.loads((report / "go_no_go.json").read_text(encoding="utf-8"))
    assert decision["decision"] == "GO"


def test_semantic_v2b_holdout_excludes_prior_holdout(tmp_path: Path) -> None:
    output = prepare_holdout_selection(
        source_lock_path=ROOT / "external/stats-ceb/source-lock.yml",
        development_selection_path=ROOT / "external/stats-ceb/query-selection.yml",
        excluded_selection_paths=[
            ROOT / "external/stats-ceb/query-selection.semantic-v2-holdout.yml"
        ],
        cache_dir=ROOT / "tmp/stats-ceb",
        selection_path=tmp_path / "selection.yml",
        selected_query_dir=tmp_path / "selected-queries",
        fragments_dir=tmp_path / "fragments",
        seed="stats-ceb-semantic-v2b-holdout",
        selection_id="stats-ceb-semantic-v2b-holdout",
        table_count_quotas={2: 1, 3: 3, 4: 4, 5: 2, 6: 2},
    )
    selection = yaml.safe_load(output.read_text(encoding="utf-8"))
    query_ids = {int(item["query_id"]) for item in selection["queries"]}
    prior = yaml.safe_load(
        (
            ROOT / "external/stats-ceb/query-selection.semantic-v2-holdout.yml"
        ).read_text(encoding="utf-8")
    )
    prior_ids = {int(item["query_id"]) for item in prior["queries"]}

    assert selection["selection_id"] == "stats-ceb-semantic-v2b-holdout"
    assert not query_ids.intersection(prior_ids)
    assert prior_ids.issubset(
        set(selection["selection_method"]["excluded_development_query_ids"])
    )


def test_semantic_v2_holdout_profile_and_corpus_render(tmp_path: Path) -> None:
    profile_path = (
        ROOT / "datasets/profiles/stats-ceb-semantic-v2-holdout.yml"
    )
    result = validate_dataset_profile(profile_path)
    assert result["status"] == "ok", result["errors"]

    plan_path = render_corpus(
        manifest_path=(
            ROOT
            / "workloads"
            / "corpus"
            / "corpus_manifest.stats-ceb-semantic-v2-holdout.yml"
        ),
        output_dir=tmp_path / "rendered",
        include_execution_classes={"pilot"},
    )
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    sweep_path = ROOT.parent / plan["groups"][0]["sweep_config"]
    sweep = yaml.safe_load(sweep_path.read_text(encoding="utf-8"))
    manifest = yaml.safe_load(
        (
            ROOT
            / "workloads"
            / "corpus"
            / "corpus_manifest.stats-ceb-semantic-v2-holdout.yml"
        ).read_text(encoding="utf-8")
    )

    assert plan["groups"][0]["instance_count"] == 12
    assert plan["groups"][0]["dataset_adapter"] == "stats_ceb"
    assert (
        sweep["collection"]["correctness_validation"]["selection"]
        == "master-regimes/external/stats-ceb/query-selection.semantic-v2-holdout.yml"
    )
    assert manifest["frozen_model_contract"]["refit_allowed"] is False


def test_semantic_v2b_holdout_profile_and_corpus_render(tmp_path: Path) -> None:
    profile_path = (
        ROOT / "datasets/profiles/stats-ceb-semantic-v2b-holdout.yml"
    )
    result = validate_dataset_profile(profile_path)
    assert result["status"] == "ok", result["errors"]

    plan_path = render_corpus(
        manifest_path=(
            ROOT
            / "workloads"
            / "corpus"
            / "corpus_manifest.stats-ceb-semantic-v2b-holdout.yml"
        ),
        output_dir=tmp_path / "rendered-v2b",
        include_execution_classes={"pilot"},
    )
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    sweep_path = ROOT.parent / plan["groups"][0]["sweep_config"]
    sweep = yaml.safe_load(sweep_path.read_text(encoding="utf-8"))

    assert plan["groups"][0]["instance_count"] == 12
    assert plan["groups"][0]["dataset_adapter"] == "stats_ceb"
    assert (
        sweep["collection"]["correctness_validation"]["selection"]
        == "master-regimes/external/stats-ceb/"
        "query-selection.semantic-v2b-holdout.yml"
    )


def test_full_no_refit_selection_and_corpus_cover_all_queries(
    tmp_path: Path,
) -> None:
    selection_path = tmp_path / "query-selection.full-no-refit-v1.yml"
    output = prepare_full_selection(
        source_lock_path=ROOT / "external/stats-ceb/source-lock.yml",
        development_selection_path=ROOT / "external/stats-ceb/query-selection.yml",
        cache_dir=ROOT / "tmp/stats-ceb",
        selection_path=selection_path,
        selected_query_dir=tmp_path / "selected-queries",
        fragments_dir=tmp_path / "fragments",
    )
    selection = yaml.safe_load(output.read_text(encoding="utf-8"))

    assert [int(item["query_id"]) for item in selection["queries"]] == list(
        range(1, 147)
    )
    assert selection["selection_method"]["technical_exclusions"] == []
    assert selection["model_contract"]["refit_allowed"] is False
    assert len(list((tmp_path / "selected-queries").glob("q-*.sql"))) == 146
    assert len(list((tmp_path / "fragments").glob("q-*.sql.j2"))) == 146

    report = run_admission_gate(
        source_lock_path=ROOT / "external/stats-ceb/source-lock.yml",
        selection_path=selection_path,
        cache_dir=ROOT / "tmp/stats-ceb",
        out_dir=tmp_path / "admission",
    )
    decision = json.loads((report / "go_no_go.json").read_text(encoding="utf-8"))
    assert decision["decision"] == "GO"
    assert decision["selected_query_count"] == 146

    profile_path = ROOT / "datasets/profiles/stats-ceb-full-no-refit.yml"
    result = validate_dataset_profile(profile_path)
    assert result["status"] == "ok", result["errors"]

    plan_path = render_corpus(
        manifest_path=(
            ROOT
            / "workloads"
            / "corpus"
            / "corpus_manifest.stats-ceb-full-no-refit-v1.yml"
        ),
        output_dir=tmp_path / "rendered-full",
        include_execution_classes={"pilot"},
    )
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    sweep_path = ROOT.parent / plan["groups"][0]["sweep_config"]
    sweep = yaml.safe_load(sweep_path.read_text(encoding="utf-8"))

    assert plan["groups"][0]["instance_count"] == 146
    assert (
        sweep["collection"]["correctness_validation"][
            "filter_workload_to_passed"
        ]
        is True
    )
