from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

from master_regimes.temporal_contract import cutoff_offset_days

ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    script = ROOT / "analysis/scripts/agent/76_build_pressure_raw_collection.py"
    spec = importlib.util.spec_from_file_location("pressure_raw_collection_builder", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_runner():
    script = ROOT / "analysis/scripts/agent/78_run_pressure_raw_batch.py"
    spec = importlib.util.spec_from_file_location("pressure_raw_batch_runner", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_consolidator():
    script = ROOT / "analysis/scripts/agent/86_consolidate_pressure_raw_program.py"
    spec = importlib.util.spec_from_file_location(
        "pressure_raw_program_consolidator",
        script,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_batch_runner_registers_standard_and_placement_indexes(
    tmp_path: Path,
) -> None:
    module = load_runner()
    standard = tmp_path / "corpus"
    standard_index = standard / "database-sweeps/cell-a/_index"
    standard_index.mkdir(parents=True)
    (standard_index / "execution_features.csv").write_text(
        "query_run_id\nq1\n",
        encoding="utf-8",
    )

    standard_sources = module.index_sources_for_artifact(
        artifact=str(standard),
        backend="standard_corpus",
        segment_id="segment-a",
    )
    assert standard_sources == [
        {
            "segment_id": "segment-a",
            "index_kind": "database_sweep",
            "index_dir": str(standard_index.resolve()),
            "execution_file": "execution_features.csv",
        }
    ]

    placement = tmp_path / "placement"
    placement_index = placement / "queries-b/_index"
    placement_index.mkdir(parents=True)
    (placement_index / "query_runs.csv").write_text(
        "query_run_id\nq2\n",
        encoding="utf-8",
    )
    (placement / "capability_smoke_manifest.json").write_text(
        json.dumps(
            {
                "query_sweeps": {
                    "B": {
                        "index_dir": str(placement_index),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    placement_sources = module.index_sources_for_artifact(
        artifact=str(placement),
        backend="placement_aware_worker",
        segment_id="segment-b",
    )
    assert placement_sources == [
        {
            "segment_id": "segment-b",
            "placement_state": "B",
            "index_kind": "placement_query_sweep",
            "index_dir": str(placement_index.resolve()),
            "execution_file": "query_runs.csv",
        }
    ]


def test_standard_segment_reuses_pressure_batch_hardware_snapshot(
    tmp_path: Path,
) -> None:
    module = load_runner()
    snapshot_dir = tmp_path / "hardware"

    command = module.command_for(
        program_id="program-v1",
        batch_id="batch-a",
        segment={
            "segment_id": "segment-a",
            "backend": "standard_corpus",
            "plan": "master-regimes/generated/plan.yml",
            "group_id": "group-a",
        },
        attempt=1,
        dry_run=False,
        hardware_snapshot_dir=snapshot_dir,
    )

    assert command[command.index("--hardware-snapshot-dir") + 1] == str(snapshot_dir)


def test_pressure_raw_program_has_stable_pairs_and_bounded_smoke(
    tmp_path: Path,
) -> None:
    module = load_builder()
    outputs = module.build_program(
        ROOT / "configs/collection/pressure_raw_program_v1.yml",
        tmp_path / "pressure-raw-v1",
    )
    program = yaml.safe_load(outputs["program"].read_text(encoding="utf-8"))
    matrix = pd.read_csv(outputs["matrix"], low_memory=False)
    configurations = pd.read_csv(
        outputs["configurations"],
        low_memory=False,
    )
    coverage_audit = json.loads(outputs["coverage_audit"].read_text(encoding="utf-8"))
    summary = json.loads(outputs["summary"].read_text(encoding="utf-8"))

    assert len(matrix) == 2607
    parameter_rows = [json.loads(value) for value in matrix["param_json"]]
    assert all(
        parameters.get("as_of_unix") == 1782864000
        or parameters.get("cutoff_ts") == "2026-06-01 00:00:00+00"
        for parameters in parameter_rows
    )
    assert {
        cutoff_offset_days(1782864000, parameters["cutoff_ts"])
        for parameters in parameter_rows
        if parameters.get("cutoff_ts")
    } == {7, 14, 30}
    assert matrix["execution_slot_id"].is_unique
    assert all(len(Path(path).name.encode("utf-8")) <= 255 for path in matrix["rendered_sql_path"])
    repeat_sizes = matrix.groupby("repeat_id").size()
    assert repeat_sizes.min() >= 2
    assert repeat_sizes.max() <= 3
    assert summary["planned_counterfactual_pair_count"] == 418
    assert summary["planned_pairs_by_axis"] == {
        "gac_finalization": 99,
        "regional_finalization": 75,
        "remote_path": 75,
        "repartition_join": 99,
        "worker_data_skew": 70,
    }
    assert summary["execution_optimization"] == {
        "instrumented_execution_count": 2607,
        "stream_only_result_signature_query_count": 869,
        "result_signature_scope": "first_repetition_per_condition",
        "avoided_redundant_signature_queries": 1738,
        "query_level_concurrency": 1,
    }
    assert summary["progress_plan"]["slot_count"] == 2607
    assert summary["progress_plan"]["planned_work_units"] > 2607
    assert summary["progress_plan"]["dataset_weights"] == {
        "small": 1.0,
        "medium": 3.0,
        "large": 8.0,
    }
    assert set(matrix["progress_cost_class"]) == {
        "light",
        "medium",
        "heavy",
        "extreme",
    }
    assert set(
        matrix.groupby("dataset_size_class")["progress_dataset_weight"].first().to_dict().items()
    ) == {
        ("small", 1.0),
        ("medium", 3.0),
        ("large", 8.0),
    }
    assert set(
        matrix.loc[
            matrix["repetition_index"].eq(0),
            "planned_query_passes",
        ]
    ) == {2}
    assert set(
        matrix.loc[
            ~matrix["repetition_index"].eq(0),
            "planned_query_passes",
        ]
    ) == {1}
    assert len(configurations) == 869
    assert set(configurations["physical_execution_count"]) == {3}
    assert configurations["stable_identity_valid"].all()
    assert set(
        configurations.loc[
            configurations["pressure_axis"].eq("remote_path"),
            "network_subblock",
        ]
    ) >= {
        "bandwidth_only",
        "delay_only",
        "fetch_only",
    }
    controls = configurations[configurations["is_negative_control"].eq(True)]
    assert set(controls["pressure_axis"]) == {
        "gac_finalization",
        "regional_finalization",
        "remote_path",
        "repartition_join",
        "worker_data_skew",
    }
    gac = configurations[configurations["pressure_axis"].eq("gac_finalization")]
    assert len(gac) == 198
    assert gac["pair_id"].nunique() == 99
    assert gac["is_negative_control"].sum() == 48
    assert set(gac["coordinator_shape_id"]) == {
        "active_user_distinct",
        "event_topk",
        "selective_summary",
        "tenant_point",
        "user_group_topk",
        "user_group_topk_memory",
        "user_segment_join",
    }
    structural_gac = gac[
        gac["coordinator_shape_id"].isin(
            {
                "active_user_distinct",
                "event_topk",
                "user_group_topk",
                "user_segment_join",
            }
        )
    ]
    assert set(structural_gac["runtime_config_id"]) == {"default"}
    joins = configurations[configurations["pressure_axis"].eq("repartition_join")]
    assert len(joins) == 198
    assert joins["pair_id"].nunique() == 99
    assert joins["is_negative_control"].sum() == 48
    assert set(joins["join_shape_id"]) == {
        "joined_row_sample",
        "no_join_tenant_point",
        "reference_daily_aggregate",
        "scalar_summary",
        "segment_aggregate",
        "user_value_topk",
    }
    assert set(
        joins.loc[
            joins["is_negative_control"].eq(False),
            "scenario_level",
        ]
    ) == {"sparse", "moderate", "broad", "router"}
    assert set(
        joins.loc[
            joins["is_negative_control"].eq(False),
            "physical_strategy_id",
        ]
    ) == {
        "colocated_distributed_join",
        "repartition_mapmerge_join",
        "router_colocated_join",
    }
    assert joins["dataset_profile_id"].nunique() == 6
    assert {
        "physical_strategy_id",
        "scenario_level",
        "join_shape_id",
    } <= set(matrix.columns)
    skew = matrix[matrix["pressure_axis"].eq("worker_data_skew")]
    assert set(skew["target_metric"]) == {"skew_multidimensional_reserved_for_phase_2"}
    assert set(
        skew.loc[
            skew["skew_signature_role"].eq("task_and_worker_positive"),
            "intervention_role",
        ]
    ) == {"positive_case"}
    assert set(
        skew.loc[
            ~skew["skew_signature_role"].eq("task_and_worker_positive"),
            "intervention_role",
        ]
    ) == {"negative_control"}
    assert set(
        skew.loc[
            skew["dataset_profile_id"].eq("pilot-region-local-skew-asymmetric-medium-v1"),
            "expected_hot_regions",
        ]
    ) == {"eu"}
    assert set(
        skew.loc[
            ~skew["dataset_profile_id"].eq("pilot-region-local-skew-asymmetric-medium-v1"),
            "expected_hot_regions",
        ]
    ) == {"eu,us"}
    assert coverage_audit["status"] == "ok"
    assert coverage_audit["isolated"]["configuration_count"] == 869
    assert coverage_audit["isolated"]["combined_configuration_count"] == 0
    assert coverage_audit["execution_deduplication"] == {
        "physical_condition_key": [
            "execution_strategy",
            "dataset_profile_id",
            "runtime_config_id",
            "topology_id",
            "template_id",
            "param_json",
        ],
        "cross_batch_exact_duplicate_count": 0,
        "status": "ok",
        "repetitions_are_intentional": True,
        "placement_state_pairs_are_intentional": True,
    }
    assert (
        coverage_audit["prepared_not_yet_materialized"]["batch-200-combined-holdout"][
            "planned_configuration_count"
        ]
        == 60
    )
    combined = coverage_audit["prepared_not_yet_materialized"]["batch-200-combined-holdout"]
    assert combined["base_case_count_by_expected_pressure_count"] == {
        "2": 18,
        "3": 6,
    }
    assert combined["base_case_count"] == 24
    assert combined["fully_one_at_a_time_mitigated_base_case_count"] == 12
    assert combined["computed_configuration_count"] == 60
    for block in ("bandwidth_only", "delay_only", "fetch_only"):
        assert coverage_audit["network_calibration_blocks"][block] == {
            "configuration_count": 24,
            "pair_count": 8,
            "sql_shape_count": 4,
            "dataset_count": 2,
        }
    smoke = program["smoke_batch"]
    assert smoke["execution_count"] == 30
    assert len(smoke["segments"]) == 5
    assert all(segment["execution_count"] == 6 for segment in smoke["segments"])
    n3 = next(
        item for item in program["prepared_batches"] if item["batch_id"] == "batch-300-n3-holdout"
    )
    assert n3["status"].startswith("blocked")
    assert program["execution_policy"]["database_result_rows_stored"] is False
    assert program["execution_policy"]["result_signature_scope"] == "first_repetition_per_condition"
    assert program["execution_policy"]["full_program_auto_run_forbidden"] is True
    assert (
        program["manual_execution_protocol"]["sentinel_policy"][
            "never_run_all_sentinels_as_one_terminal_block"
        ]
        is True
    )

    contract = yaml.safe_load(
        (ROOT / "configs/collection/pressure_raw_collection_v1.yml").read_text(encoding="utf-8")
    )
    assert contract["design_scope"] == {
        "model_agnostic": True,
        "feature_set_agnostic": True,
        "target_agnostic": False,
        "supported_future_tasks": [
            "confirmed_physical_signature_multilabel",
            "paired_mitigation_benefit_regression",
        ],
        "target_materialization_reserved_for_phase_2": True,
    }
    assert set(contract["future_derived_value_provenance"]["evidence_roles"]) == {
        "label_only",
        "model_eligible",
        "shared_descriptive",
    }


def test_pressure_dataset_profiles_freeze_the_same_time_origin() -> None:
    sweep_path = ROOT / "configs/collection/pressure_raw_dataset_sweep_v1.yml"
    sweep = yaml.safe_load(sweep_path.read_text(encoding="utf-8"))
    for profile_id, spec in sweep["profiles"].items():
        profile_path = (sweep_path.parent / spec["profile"]).resolve()
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        assert profile["base_time_unix"] == 1782864000, profile_id
        assert profile["scale"]["lookback_days"] == 30, profile_id


def test_progress_checkpoint_scope_excludes_smoke_and_dry_run(
    tmp_path: Path,
) -> None:
    module = load_runner()
    runs_root = tmp_path / "runs"
    production = runs_root / "batch-100-gac/run/checkpoints"
    smoke = runs_root / "batch-000-collection-smoke/run/checkpoints"
    dry_run = tmp_path / "dry-run/checkpoints"
    for directory, slot_id in (
        (production, "prod-slot"),
        (smoke, "smoke-slot"),
        (dry_run, "dry-slot"),
    ):
        directory.mkdir(parents=True)
        (directory / "segment.jsonl").write_text(
            json.dumps(
                {
                    "execution_slot_id": slot_id,
                    "status": "completed",
                }
            )
            + "\n",
            encoding="utf-8",
        )

    paths = module.checkpoint_paths(
        runs_root=runs_root,
        batch_ids={"batch-100-gac"},
        current_state_dir=tmp_path / "dry-run",
        include_current=False,
    )
    records = module.completed_checkpoint_records(paths)

    assert set(records) == {"prod-slot"}


def test_resume_ignores_checkpoint_without_completed_artifact(
    tmp_path: Path,
) -> None:
    module = load_runner()
    checkpoint = tmp_path / "checkpoint.jsonl"
    collection_dir = tmp_path / "collection"
    collection_dir.mkdir()
    checkpoint.write_text(
        json.dumps(
            {
                "status": "completed",
                "execution_slot_id": "slot-1",
                "collection_dir": str(collection_dir),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert (
        module.completed_checkpoint_records(
            [checkpoint],
            require_artifact=True,
        )
        == {}
    )

    (collection_dir / "execution_manifest.json").write_text(
        json.dumps({"execution_status": "completed"}),
        encoding="utf-8",
    )
    assert set(
        module.completed_checkpoint_records(
            [checkpoint],
            require_artifact=True,
        )
    ) == {"slot-1"}


def test_segment_completion_uses_exact_expected_slot_set() -> None:
    module = load_runner()
    batch_rows = [
        {
            "group_id": "group-a",
            "execution_slot_id": "slot-1",
        },
        {
            "group_id": "group-a",
            "execution_slot_id": "slot-2",
        },
        {
            "group_id": "group-b",
            "execution_slot_id": "slot-3",
        },
    ]
    segment = {
        "segment_id": "segment-a",
        "backend": "standard_corpus",
        "group_id": "group-a",
    }

    assert module.expected_segment_slots(
        batch_rows=batch_rows,
        segment=segment,
    ) == {"slot-1", "slot-2"}


def test_consolidator_indexes_partial_sweep_for_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_consolidator()
    sweep_dir = tmp_path / "partial-sweep"
    collection_dir = sweep_dir / "query-collections/query-1"
    collection_dir.mkdir(parents=True)
    (collection_dir / "execution_manifest.json").write_text(
        json.dumps(
            {
                "query_run_id": "query-1",
                "execution_status": "completed",
            }
        ),
        encoding="utf-8",
    )
    (sweep_dir / "query_sweep_manifest.json").write_text(
        json.dumps(
            {
                "sweep_id": "partial-sweep",
                "status": "running",
                "executions": [],
            }
        ),
        encoding="utf-8",
    )

    def fake_index_query_sweep(*, sweep_dir: Path) -> Path:
        index_dir = sweep_dir / "_index"
        index_dir.mkdir()
        pd.DataFrame(
            [
                {
                    "query_run_id": "query-1",
                    "execution_slot_id": "slot-1",
                    "execution_status": "completed",
                    "collection_dir": str(collection_dir),
                }
            ]
        ).to_csv(index_dir / "query_runs.csv", index=False)
        return index_dir

    monkeypatch.setattr(
        module,
        "index_query_sweep",
        fake_index_query_sweep,
    )

    index_dir, query_row, error = module.resolve_source_index(
        collection_dir=collection_dir,
        execution_slot_id="slot-1",
        query_cache={},
    )

    assert error == ""
    assert index_dir == sweep_dir / "_index"
    assert query_row is not None
    assert query_row["query_run_id"] == "query-1"


def test_weighted_progress_estimates_only_runnable_work() -> None:
    module = load_runner()
    rows = [
        {
            "execution_slot_id": "done",
            "batch_id": "ready",
            "planned_work_units": "2",
        },
        {
            "execution_slot_id": "pending",
            "batch_id": "ready",
            "planned_work_units": "8",
        },
        {
            "execution_slot_id": "blocked",
            "batch_id": "blocked",
            "planned_work_units": "24",
        },
    ]
    completed = {
        "done": {
            "status": "completed",
            "elapsed_seconds": 10,
            "planned_work_units": 2,
        }
    }

    snapshot = module.progress_snapshot(
        rows=rows,
        completed=completed,
        runnable_batch_ids={"ready"},
    )

    assert snapshot["runnable_completed_slot_count"] == 1
    assert snapshot["runnable_slot_count"] == 2
    assert snapshot["blocked_slot_count"] == 1
    assert snapshot["runnable_completed_work_units"] == 2
    assert snapshot["runnable_work_units"] == 10
    assert snapshot["seconds_per_work_unit"] == 5
    assert snapshot["eta_seconds"] == 40
    assert snapshot["remaining_cost_class_counts"] == {"unknown": 1}
    assert snapshot["remaining_dataset_size_counts"] == {"unknown": 1}


def test_consolidator_selects_latest_successful_attempt_and_excludes_smoke() -> None:
    module = load_consolidator()
    candidates = [
        {
            "source_batch_id": "batch-primary",
            "consolidation_role": "primary",
            "training_eligible": True,
            "execution_slot_id": "slot-1",
            "query_run_id": "query-old",
            "attempt_number": 1,
            "completed_at_utc": "20260730T000000Z",
            "checkpoint_line": 1,
            "candidate_valid": True,
        },
        {
            "source_batch_id": "batch-primary",
            "consolidation_role": "primary",
            "training_eligible": True,
            "execution_slot_id": "slot-1",
            "query_run_id": "query-new",
            "attempt_number": 2,
            "completed_at_utc": "20260730T010000Z",
            "checkpoint_line": 1,
            "candidate_valid": True,
        },
        {
            "source_batch_id": "batch-primary",
            "consolidation_role": "primary",
            "training_eligible": True,
            "execution_slot_id": "slot-1",
            "query_run_id": "query-new-cross-state-root",
            "attempt_number": 1,
            "completed_at_utc": "20260730T030000Z",
            "checkpoint_line": 1,
            "candidate_valid": True,
        },
        {
            "source_batch_id": "batch-smoke",
            "consolidation_role": "smoke",
            "training_eligible": False,
            "execution_slot_id": "slot-1",
            "query_run_id": "query-smoke",
            "attempt_number": 3,
            "completed_at_utc": "20260730T020000Z",
            "checkpoint_line": 1,
            "candidate_valid": True,
        },
    ]

    selected, exclusions = module.resolve_attempts(candidates)

    assert {row["query_run_id"] for row in selected} == {
        "query-new-cross-state-root",
        "query-smoke",
    }
    assert (
        next(
            row
            for row in selected
            if row["query_run_id"] == "query-new-cross-state-root"
        )["disposition"]
        == "selected_primary"
    )
    assert {row["disposition"] for row in exclusions} == {
        "superseded_successful_attempt",
        "excluded_from_training_by_role",
    }


def test_consolidator_rejects_duplicate_primary_slots() -> None:
    module = load_consolidator()
    selected = [
        {
            "source_batch_id": "batch-a",
            "training_eligible": True,
            "execution_slot_id": "slot-1",
            "query_run_id": "query-a",
        },
        {
            "source_batch_id": "batch-b",
            "training_eligible": True,
            "execution_slot_id": "slot-1",
            "query_run_id": "query-b",
        },
    ]

    issues = module.duplicate_audit(selected)

    assert issues == [
        {
            "issue": "duplicate_primary_execution_slot_id",
            "value": "slot-1",
            "count": 2,
            "source_batch_ids": "batch-a,batch-b",
            "query_run_ids": "query-a,query-b",
        }
    ]


def test_consolidator_canonicalizes_bijective_placement_identity_aliases() -> None:
    module = load_consolidator()
    selected = []
    matrix_rows = []
    for state in ("B", "C"):
        slot_id = f"skew-dataset::{state}::query::r0"
        selected.append(
            {
                "source_batch_id": "batch-120-skew",
                "training_eligible": True,
                "execution_slot_id": slot_id,
                "pair_id": "pair-observed",
                "repeat_id": "pair-observed::r0",
                "query_run_id": f"query-{state}",
                "_query_row": {},
            }
        )
        matrix_rows.append(
            {
                "batch_id": "batch-120-skew",
                "backend": "placement_aware_worker",
                "execution_slot_id": slot_id,
                "pair_id": "pair-planned",
                "repeat_id": "pair-planned::r0",
                "repetition_index": "0",
            }
        )

    rows, issues, aliases = module.training_view(
        selected=selected,
        matrix_rows=matrix_rows,
    )

    assert issues == []
    assert len(rows) == 2
    assert {row["pair_id"] for row in rows} == {"pair-planned"}
    assert {row["observed_pair_id"] for row in rows} == {"pair-observed"}
    assert {row["identity_resolution"] for row in rows} == {"canonicalized_placement_alias"}
    assert len(aliases) == 2


def test_consolidator_rejects_invalid_placement_identity_alias() -> None:
    module = load_consolidator()

    rows, issues, aliases = module.training_view(
        selected=[
            {
                "source_batch_id": "batch-120-skew",
                "training_eligible": True,
                "execution_slot_id": "slot-1",
                "pair_id": "pair-observed",
                "repeat_id": "wrong-repeat",
                "query_run_id": "query-1",
            }
        ],
        matrix_rows=[
            {
                "batch_id": "batch-120-skew",
                "backend": "placement_aware_worker",
                "execution_slot_id": "slot-1",
                "pair_id": "pair-planned",
                "repeat_id": "pair-planned::r0",
                "repetition_index": "0",
            }
        ],
    )

    assert rows == []
    assert issues == [
        "primary_pair_id_mismatch:slot-1",
        "primary_repeat_id_mismatch:slot-1",
    ]
    assert aliases == []


def test_consolidator_builds_primary_only_index_end_to_end(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_consolidator()
    matrix_path = tmp_path / "execution_matrix.csv"
    pd.DataFrame(
        [
            {
                "batch_id": "batch-primary",
                "execution_slot_id": "slot-1",
                "condition_id": "condition-1",
                "pair_id": "pair-1",
                "repeat_id": "repeat-1",
                "instance_id": "instance-1",
            }
        ]
    ).to_csv(matrix_path, index=False)
    program_path = tmp_path / "program.yml"
    program_path.write_text(
        yaml.safe_dump(
            {
                "program_id": "program-1",
                "execution_matrix": str(matrix_path),
                "consolidation_policy": {
                    "role_by_batch_kind": {
                        "isolated": "primary",
                        "collection_smoke": "smoke",
                    },
                    "external_batch_roles": {},
                },
                "rendered_batches": [
                    {
                        "batch_id": "batch-primary",
                        "kind": "isolated",
                    }
                ],
                "prepared_batches": [],
                "smoke_batch": {
                    "batch_id": "batch-smoke",
                    "kind": "collection_smoke",
                },
            }
        ),
        encoding="utf-8",
    )
    state_root = tmp_path / "state"

    def add_attempt(
        *,
        batch_id: str,
        query_run_id: str,
        attempt: int,
        completed_at: str,
        indexed_batch_id: str,
    ) -> Path:
        collection_dir = (
            tmp_path
            / f"{batch_id}__attempt-{attempt:02d}"
            / "query-sweeps"
            / query_run_id
            / "query-collections"
            / query_run_id
        )
        collection_dir.mkdir(parents=True)
        (collection_dir / "execution_manifest.json").write_text(
            json.dumps({"attempt_id": query_run_id}),
            encoding="utf-8",
        )
        index_dir = collection_dir.parents[1] / "_index"
        index_dir.mkdir()
        pd.DataFrame(
            [
                {
                    "query_run_id": query_run_id,
                    "execution_slot_id": "slot-1",
                    "execution_status": "completed",
                    "batch_id": indexed_batch_id,
                    "instance_id": "instance-1",
                    "elapsed_seconds": attempt,
                }
            ]
        ).to_csv(index_dir / "query_runs.csv", index=False)
        pd.DataFrame(
            [
                {
                    "query_run_id": query_run_id,
                    "region_id": "eu",
                }
            ]
        ).to_csv(index_dir / "region_fragments.csv", index=False)
        batch_run = state_root / batch_id / "run"
        batch_run.mkdir(parents=True, exist_ok=True)
        (batch_run / "status.json").write_text(
            json.dumps(
                {
                    "program_id": "program-1",
                    "batch_id": batch_id,
                }
            ),
            encoding="utf-8",
        )
        checkpoint = batch_run / "checkpoints/segment.jsonl"
        checkpoint.parent.mkdir(exist_ok=True)
        with checkpoint.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "program_id": "program-1",
                        "batch_id": batch_id,
                        "program_attempt_id": (f"segment::attempt-{attempt:02d}"),
                        "execution_slot_id": "slot-1",
                        "pair_id": "pair-1",
                        "repeat_id": "repeat-1",
                        "status": "completed",
                        "collection_dir": str(collection_dir),
                        "completed_at_utc": completed_at,
                    }
                )
                + "\n"
            )
        return collection_dir

    add_attempt(
        batch_id="batch-primary",
        query_run_id="query-old",
        attempt=1,
        completed_at="20260730T000000Z",
        indexed_batch_id="batch-primary",
    )
    add_attempt(
        batch_id="batch-primary",
        query_run_id="query-new",
        attempt=2,
        completed_at="20260730T010000Z",
        indexed_batch_id="batch-primary",
    )
    add_attempt(
        batch_id="batch-smoke",
        query_run_id="query-smoke",
        attempt=3,
        completed_at="20260730T020000Z",
        indexed_batch_id="batch-primary",
    )
    out_dir = tmp_path / "consolidated"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "86_consolidate_pressure_raw_program.py",
            "--program",
            str(program_path),
            "--state-root",
            str(state_root),
            "--out-dir",
            str(out_dir),
        ],
    )

    assert module.main() == 0
    manifest = json.loads((out_dir / "consolidation_manifest.json").read_text(encoding="utf-8"))
    training = pd.read_csv(out_dir / "training_execution_view.csv")
    query_runs = pd.read_csv(out_dir / "_index/query_runs.csv")
    regions = pd.read_csv(out_dir / "_index/region_fragments.csv")
    excluded = pd.read_csv(out_dir / "excluded_executions.csv")

    assert manifest["gate"] == "GO"
    assert manifest["resolved_primary_slot_count"] == 1
    assert training["query_run_id"].tolist() == ["query-new"]
    assert query_runs["query_run_id"].tolist() == ["query-new"]
    assert regions["query_run_id"].tolist() == ["query-new"]
    assert set(excluded["query_run_id"]) == {
        "query-old",
        "query-smoke",
    }


def test_consolidator_normalizes_enriched_query_runs_as_execution_features(
    tmp_path: Path,
) -> None:
    module = load_consolidator()
    standard_index = tmp_path / "standard" / "_index"
    placement_index = tmp_path / "placement" / "_index"
    standard_index.mkdir(parents=True)
    placement_index.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "query_run_id": "query-standard",
                "execution_slot_id": "slot-standard",
                "elapsed_seconds": 1.0,
                "standard_metric": 10,
            }
        ]
    ).to_csv(standard_index / "query_runs.csv", index=False)
    pd.DataFrame(
        [
            {
                "query_run_id": "query-standard",
                "execution_slot_id": "slot-standard",
                "elapsed_seconds": 1.0,
                "standard_metric": 10,
            }
        ]
    ).to_csv(standard_index / "execution_features.csv", index=False)
    pd.DataFrame(
        [
            {
                "query_run_id": "query-placement",
                "execution_slot_id": "slot-placement",
                "elapsed_seconds": 2.0,
                "pair_id": "pair-observed",
                "intervention_role": "final_check",
                "intervention_axis": "shard_placement",
                "target_metric": "execution_time_seconds",
                "dataset_role": "pressure_isolated",
                "placement_metric": 20,
            }
        ]
    ).to_csv(placement_index / "query_runs.csv", index=False)

    counts = module.consolidate_primary_index(
        training_rows=[
            {
                "source_index_dir": str(standard_index),
                "query_run_id": "query-standard",
                "instance_id": "instance-standard",
            },
            {
                "source_index_dir": str(placement_index),
                "query_run_id": "query-placement",
                "instance_id": "instance-placement",
                "batch_id": "batch-placement",
                "execution_slot_id": "slot-placement",
                "condition_id": "condition-placement",
                "pair_id": "pair-canonical",
                "repeat_id": "pair-canonical::r0",
                "repetition_index": "0",
                "intervention_role": "positive_case",
                "intervention_axis": "dataset_and_shard_placement",
                "target_metric": "skew_multidimensional_reserved_for_phase_2",
                "dataset_role": "pressure_negative_control",
            },
        ],
        out_dir=tmp_path / "out",
    )

    features = pd.read_csv(tmp_path / "out/_index/execution_features.csv")
    assert counts["execution_features"] == 2
    assert set(features["query_run_id"]) == {
        "query-standard",
        "query-placement",
    }
    placement = features.loc[features["query_run_id"] == "query-placement"].iloc[0]
    assert placement["placement_metric"] == 20
    assert placement["pair_id"] == "pair-canonical"
    assert placement["intervention_role"] == "positive_case"
    assert placement["intervention_axis"] == "dataset_and_shard_placement"
    assert placement["target_metric"] == "skew_multidimensional_reserved_for_phase_2"
    assert placement["dataset_role"] == "pressure_negative_control"


def test_consolidator_projects_regional_temp_evidence_to_execution_rows(
    tmp_path: Path,
) -> None:
    module = load_consolidator()
    index_dir = tmp_path / "_index"
    index_dir.mkdir()
    pd.DataFrame(
        [
            {"query_run_id": "query-spill", "elapsed_seconds": 1.0},
            {"query_run_id": "query-no-evidence", "elapsed_seconds": 2.0},
        ]
    ).to_csv(index_dir / "execution_features.csv", index=False)
    pd.DataFrame(
        [
            {
                "query_run_id": "query-spill",
                "region_id": "eu",
                "remote_temp_blocks_read": 100,
                "remote_temp_blocks_written": 120,
            },
            {
                "query_run_id": "query-spill",
                "region_id": "us",
                "remote_temp_blocks_read": 0,
                "remote_temp_blocks_written": 0,
            },
        ]
    ).to_csv(index_dir / "region_fragments.csv", index=False)

    assert module.enrich_execution_features_from_regions(index_dir) == 1

    rows = pd.read_csv(index_dir / "execution_features.csv")
    spill = rows.loc[rows["query_run_id"] == "query-spill"].iloc[0]
    missing = rows.loc[rows["query_run_id"] == "query-no-evidence"].iloc[0]
    assert spill["regional_temp_evidence_region_count"] == 2
    assert spill["regional_temp_read_blocks_sum"] == 100
    assert spill["regional_temp_written_blocks_sum"] == 120
    assert spill["regional_spill_region_count"] == 1
    assert bool(spill["regional_spill_present"])
    assert pd.isna(missing["regional_spill_present"])


def test_consolidator_normalizes_one_hardware_snapshot_per_batch(
    tmp_path: Path,
) -> None:
    module = load_consolidator()
    state_root = tmp_path / "state"
    snapshot_dir = state_root / "batch-primary/run/hardware-snapshots/snapshot-1"
    snapshot_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "snapshot_id": "snapshot-1",
                "node_name": "worker-1",
                "groups": "db_nodes",
                "summary_file": "nodes/worker-1/hardware_summary.json",
                "raw_file": "nodes/worker-1/hardware_raw.json",
            }
        ]
    ).to_csv(snapshot_dir / "hardware_nodes.csv", index=False)
    index_dir = tmp_path / "out/_index"
    index_dir.mkdir(parents=True)

    count = module.consolidate_program_hardware(
        state_root=state_root,
        batch_ids={"batch-primary"},
        index_dir=index_dir,
    )

    rows = pd.read_csv(index_dir / "program_hardware_nodes.csv")
    assert count == 1
    assert rows.iloc[0]["batch_id"] == "batch-primary"
    assert rows.iloc[0]["snapshot_id"] == "snapshot-1"
    assert rows.iloc[0]["node_name"] == "worker-1"
    assert Path(rows.iloc[0]["summary_file"]).is_absolute()


def test_skew_profiles_drive_hot_ranges_and_region_applicability() -> None:
    module = load_builder()
    small_heavy = yaml.safe_load(
        (ROOT / "datasets/profiles/raw-small-skew-heavy.yml").read_text(encoding="utf-8")
    )
    asymmetric = yaml.safe_load(
        (ROOT / "datasets/profiles/pilot-region-local-skew-asymmetric-medium.yml").read_text(
            encoding="utf-8"
        )
    )
    condition = {
        "template_id": "gac_fdw_multiregion_hot_worker_probe",
        "parameters": {"cpu_terms": 32},
    }

    assert module.hot_ids(small_heavy, "eu") == [1, 2, 3, 4]
    assert module.hot_ids(small_heavy, "us") == [10001, 10002, 10003, 10004]
    assert module.hot_ids(asymmetric, "eu") == list(range(1, 41))
    assert module.hot_ids(asymmetric, "us") == []
    assert module.skew_condition_parameters(condition, small_heavy) == {
        "cpu_terms": 32,
        "eu_hot_tenant_min": 1,
        "eu_hot_tenant_max": 4,
        "us_hot_tenant_min": 10001,
        "us_hot_tenant_max": 10004,
    }
    assert module.skew_condition_parameters(condition, asymmetric) == {
        "cpu_terms": 32,
        "eu_hot_tenant_min": 1,
        "eu_hot_tenant_max": 40,
        "us_hot_tenant_min": 10001,
        "us_hot_tenant_max": 10010,
    }
