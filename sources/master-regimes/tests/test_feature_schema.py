from __future__ import annotations

from pathlib import Path

import yaml


def _schema() -> dict[str, object]:
    schema_file = Path(__file__).resolve().parents[1] / "docs" / "feature_schema.yml"
    return yaml.safe_load(schema_file.read_text(encoding="utf-8"))


def test_feature_schema_declares_required_quality_fields() -> None:
    schema = _schema()
    required = {
        "source_table",
        "feature_scope",
        "feature_reliability",
        "model_role",
        "included_in_default_model",
        "proxy_of",
        "requires_topology",
        "null_policy",
    }
    scopes = set(schema["allowed_values"]["feature_scope"])
    reliabilities = set(schema["allowed_values"]["feature_reliability"])
    roles = set(schema["allowed_values"]["model_role"])
    topologies = set(schema["allowed_values"]["requires_topology"])

    for section_name, key_name in (("columns", "name"), ("column_patterns", "pattern")):
        entries = schema[section_name]
        assert entries, section_name
        for entry in entries:
            assert key_name in entry
            assert required.issubset(entry), entry.get(key_name)
            assert entry["feature_scope"] in scopes
            assert entry["feature_reliability"] in reliabilities
            assert entry["model_role"] in roles
            assert entry["requires_topology"] in topologies
            assert isinstance(entry["included_in_default_model"], bool)
            if entry["model_role"] != "input":
                assert entry["included_in_default_model"] is False


def test_feature_schema_keeps_identity_and_context_out_of_default_model() -> None:
    schema = _schema()
    forbidden_exact = {
        "corpus_cell_id",
        "corpus_id",
        "dataset_id",
        "dataset_profile_id",
        "execution_strategy",
        "fdw_region",
        "instance_id",
        "logical_question_id",
        "pressure_tags",
        "query_family",
        "region_id",
        "remote_plan_id",
        "runtime_config_id",
        "system_id",
        "target_node",
        "task_index",
        "template_id",
        "worker_node",
    }
    forbidden_suffixes = (
        "_id",
        "_path",
        "_file",
        "_files",
        "_json",
        "_status",
        "_tag",
        "_tags",
    )
    forbidden_substrings = ("password", "secret", "token")

    entries = [*schema["columns"], *schema["column_patterns"]]
    for entry in entries:
        if entry["included_in_default_model"] is not True:
            continue
        name = entry.get("name") or entry.get("pattern")
        assert entry["model_role"] == "input", name
        assert name not in forbidden_exact
        assert not any(str(name).endswith(suffix) for suffix in forbidden_suffixes), name
        assert not any(substring in str(name) for substring in forbidden_substrings), name
        if "fingerprint" in str(name):
            allowed_fingerprint_summary = any(
                token in str(name)
                for token in (
                    "_fingerprint_count",
                    "_fingerprint_dominant_share",
                    "_dominant_plan_fingerprint_share",
                )
            )
            assert allowed_fingerprint_summary, name


def test_feature_schema_captures_default_model_and_proxy_boundaries() -> None:
    schema = _schema()
    columns = {entry["name"]: entry for entry in schema["columns"]}
    patterns = {entry["pattern"]: entry for entry in schema["column_patterns"]}

    final_features = schema["feature_sets"]["final_m0_flow_ratio_v3_reduced"]["features"]
    assert final_features == [
        "remote_path_share",
        "remote_to_final_rows_ratio",
        "wan_output_to_final_rows_ratio",
        "drf_bytes_proxy",
        "global_group_merge_ratio",
        "temp_bytes_to_wan_bytes_ratio",
        "temp_blocks_per_wan_row",
        "temp_blocks_per_final_row",
        "spill_per_wan_mb",
        "hash_batches_max",
        "remote_region_rows_isf",
        "worker_task_scan_rows_isf",
        "worker_task_scan_actual_rows_max_share",
        "task_count_to_shard_count_ratio",
        "active_task_share",
        "citus_repartition_query",
        "worker_task_seq_scan_share",
        "root_rows_estimate_error_log",
        "foreign_scan_rows_estimate_error_log",
        "aggregate_rows_estimate_error_log",
        "remote_root_rows_estimate_error_log",
    ]
    assert len(final_features) == 21

    for name in final_features:
        assert columns[name]["model_role"] == "input"

    for name in schema["feature_sets"]["final_m0_flow_ratio_v3_reduced"][
        "excluded_absolute_or_context_signals"
    ]:
        assert name not in final_features

    for name in (
        "has_foreign_scan",
        "join_node_count",
        "remote_path_share",
        "remote_plan_max_depth",
        "finalize_share",
        "drf_bytes_proxy",
        "rows_estimate_error_max_abs_log",
        "foreign_scan_rows_estimate_error_log",
        "is_router_query",
    ):
        assert columns[name]["model_role"] == "input"
        assert columns[name]["included_in_default_model"] is True

    for name in (
        "execution_time_seconds",
        "temp_blocks_sum",
        "task_count",
        "wan_output_rows",
        "wan_output_bytes_proxy",
        "remote_actual_rows_sum",
        "remote_region_tuple_bytes_sum",
        "global_group_count_proxy",
        "main_root_actual_rows",
    ):
        assert name not in final_features

    for name in (
        "template_id",
        "instance_id",
        "dataset_id",
        "pressure_tags",
        "plan_fingerprint",
        "fdw_remote_probe_status",
        "work_mem",
        "fetch_size",
        "filter_uses_distribution_key",
        "estimated_fanin_bytes",
        "fetch_share",
        "regions_touched",
        "task_time_cv",
        "execution_time_mean",
        "hardware_ram_bytes",
        "main_plan_max_depth",
        "main_plan_leaf_count",
        "main_plan_avg_branching_factor",
        "aggregate_min_depth",
        "foreign_scan_max_depth",
        "aggregate_above_foreign_scan",
        "blocking_operator_count",
        "dominant_time_node_actual_time_share",
        "remote_region_actual_rows_min",
        "remote_region_actual_rows_max",
        "remote_region_actual_rows_mean",
        "remote_region_actual_rows_imbalance_ratio",
        "remote_region_tuple_bytes_min",
        "remote_region_tuple_bytes_max",
        "remote_region_tuple_bytes_mean",
        "remote_region_tuple_bytes_imbalance_ratio",
        "remote_region_task_count_min",
        "remote_region_task_count_max",
        "remote_region_task_count_mean",
        "remote_region_task_count_imbalance_ratio",
        "remote_region_plan_fingerprint_all_same",
        "remote_region_actual_time_min",
        "remote_region_actual_time_max",
        "remote_region_actual_time_mean",
        "remote_region_actual_time_imbalance_ratio",
    ):
        assert columns[name]["included_in_default_model"] is False

    assert columns["fetch_share"]["proxy_of"] == "remote_path_share"
    assert columns["fetch_share"]["feature_reliability"] == "B"
    assert columns["fetch_share"]["included_in_default_model"] is False
    assert columns["drf_bytes"]["requires_topology"] == "eu_us"
    assert columns["drf_bytes"]["included_in_default_model"] is False
    assert patterns["parent_child_type_count_*"]["model_role"] == "input"
    assert patterns["parent_child_type_count_*"]["included_in_default_model"] is False
    assert patterns["parent_child_type_count_*"]["structural_feature"] is True
    assert schema["feature_sets"]["plan_structure_v1"]["include_where"][
        "structural_feature"
    ] is True
    assert schema["feature_sets"]["core_plus_structure_v1"]["compose"] == [
        "core_model_v1",
        "plan_structure_v1",
    ]

    for name in (
        "main_plan_max_depth",
        "main_plan_leaf_count",
        "aggregate_min_depth",
        "aggregate_above_foreign_scan",
        "blocking_operator_count",
        "dominant_time_node_actual_time_share",
    ):
        assert columns[name]["model_role"] == "input"
        assert columns[name]["structural_feature"] is True
