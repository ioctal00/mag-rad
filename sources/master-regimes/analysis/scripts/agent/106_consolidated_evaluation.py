#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT = ROOT / "configs/validation/consolidated_evaluation_v1.yml"
DEFAULT_OUT_DIR = ROOT / "analysis/reports/consolidated-evaluation-v1"
ABLATION_SCRIPT = ROOT / "analysis/scripts/agent/105_representation_ablation_e1_e4.py"
BASE_SCRIPT = ROOT / "analysis/scripts/agent/103_representation_value_ablation.py"
MEMORY_SCRIPT = ROOT / "analysis/scripts/agent/101_fuzzy_intervention_memory.py"
DBA_SCRIPT = ROOT / "analysis/scripts/agent/102_dba_local_memory_panel.py"
TOPOLOGY_SCRIPT = ROOT / "analysis/scripts/agent/104_n3_topology_memory_experiment.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consolidate existing evaluations without SQL execution or model refit."
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def resolve_input(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def load_module(path: Path, name: str) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        converted = float(value)
        return converted if math.isfinite(converted) else None
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(out_dir: Path) -> None:
    target = out_dir / "checksums.sha256"
    rows = [
        f"{sha256_file(path)}  {path.relative_to(out_dir)}"
        for path in sorted(out_dir.rglob("*"))
        if path.is_file() and path != target
    ]
    target.write_text("\n".join(rows) + "\n", encoding="utf-8")


def utc_iso(value: float | int) -> str:
    return datetime.fromtimestamp(float(value), tz=UTC).isoformat().replace("+00:00", "Z")


def run_id_timestamp(values: pd.Series) -> tuple[str, str]:
    extracted = values.astype(str).str.extract(r"^(\d{8}T\d{6}Z)")[0].dropna()
    if extracted.empty:
        return "", ""
    return str(extracted.min()), str(extracted.max())


def _validate_contract(contract: dict[str, Any]) -> None:
    policy = contract["policy"]
    if int(policy["frozen_neighbors"]) != 5:
        raise ValueError("Frozen k must remain five")
    if str(policy["frozen_distance_metric"]) != "euclidean":
        raise ValueError("Frozen distance must remain Euclidean")
    if float(policy["frozen_coverage_quantile"]) != 0.99:
        raise ValueError("Frozen coverage rule must remain empirical P99")
    if list(policy["sensitivity_neighbors"]) != [1, 3, 5]:
        raise ValueError("Sensitivity k contract changed")
    if set(policy["sensitivity_metrics"]) != {"euclidean", "cosine", "manhattan"}:
        raise ValueError("Sensitivity metric contract changed")


def _load_ablation_inputs(contract: dict[str, Any]) -> tuple[Any, Any, Any, Any, Any, Any]:
    ablation = load_module(ABLATION_SCRIPT, "consolidated_ablation_105")
    base = load_module(BASE_SCRIPT, "consolidated_base_103")
    memory = load_module(MEMORY_SCRIPT, "consolidated_memory_101")
    dba = load_module(DBA_SCRIPT, "consolidated_dba_102")
    topology = load_module(TOPOLOGY_SCRIPT, "consolidated_topology_104")
    ablation_contract = read_yaml(resolve_input(contract["inputs"]["representation_contract"]))
    base_contract = read_yaml(resolve_input(ablation_contract["inputs"]["base_ablation_contract"]))
    data = ablation.load_inputs(
        ablation_contract,
        base_contract,
        base,
        memory,
        dba,
        topology,
    )
    return ablation, base, memory, dba, topology, data


def provenance_table(contract: dict[str, Any]) -> pd.DataFrame:
    inputs = contract["inputs"]
    expected = contract["expected"]
    broad = pd.read_csv(resolve_input(inputs["broad_query_runs"]), low_memory=False)
    broad_manifest = json.loads(
        resolve_input(inputs["broad_consolidation"]).read_text(encoding="utf-8")
    )
    action_summary = json.loads(
        resolve_input(inputs["broad_action_summary"]).read_text(encoding="utf-8")
    )
    development_dir = resolve_input(inputs["development_report"])
    development_episodes = pd.read_csv(development_dir / "episodes.csv", low_memory=False)
    scenario_metrics = pd.read_csv(development_dir / "scenario_metrics.csv", low_memory=False)
    development_ids = set(
        scenario_metrics.loc[scenario_metrics["panel"].eq("gac_topk"), "scenario_id"].astype(str)
    )
    primary_development = development_episodes[
        development_episodes["scenario_id"].astype(str).isin(development_ids)
    ]
    final_dir = resolve_input(inputs["final_panel_report"])
    final_states = pd.read_csv(final_dir / "observed_episode_states.csv", low_memory=False)
    final_outcomes = pd.read_csv(final_dir / "observed_action_outcomes.csv", low_memory=False)
    final_start, final_end = run_id_timestamp(
        pd.concat(
            [final_states["baseline_query_run_id"], final_outcomes["action_query_run_id"]],
            ignore_index=True,
        )
    )
    topology_dir = resolve_input(inputs["topology_report"])
    topology_runs = pd.read_csv(topology_dir / "raw_execution_identifiers.csv", low_memory=False)
    topology_states = pd.read_csv(topology_dir / "episode_states.csv", low_memory=False)
    topology_outcomes = pd.read_csv(topology_dir / "action_outcomes.csv", low_memory=False)
    rows = [
        {
            "dataset_id": "broad_intervention_corpus",
            "dataset_name": "Siroki intervencijski korpus",
            "execution_count": len(broad),
            "state_count": int(broad["condition_id"].nunique()),
            "action_episode_count": int(action_summary["pair_count"]),
            "controlled_pair_count": int(action_summary["pair_count"]),
            "sql_shape_count": int(broad["template_id"].nunique()),
            "topologies": ";".join(sorted(broad["topology_id"].dropna().astype(str).unique())),
            "time_start_utc": str(broad["created_at_utc"].min()),
            "time_end_utc": str(broad["created_at_utc"].max()),
            "actions": ";".join(sorted(broad["mitigation_action"].dropna().astype(str).unique())),
            "feature_transformations": (
                "raw and derived multilayer evidence; no final similarity fit"
            ),
            "used_for_fit": False,
            "used_for_hyperparameter_selection": False,
            "used_for_evaluation": True,
            "allowed_claim": (
                "collector completeness, physical evidence, result equivalence and "
                "intervention contract; not final action-selection quality"
            ),
            "source_scope_note": "2607 primary rows selected from append-only attempts",
        },
        {
            "dataset_id": "development_reference_panel",
            "dataset_name": "Razvojni/reference GAC Top-K panel",
            "execution_count": int(expected["development_executions"]),
            "state_count": len(development_ids),
            "action_episode_count": len(primary_development),
            "controlled_pair_count": len(primary_development),
            "sql_shape_count": int(primary_development["component_match_id"].nunique()),
            "topologies": "eu_us_gac",
            "time_start_utc": utc_iso(primary_development["baseline_started_at_unix"].min()),
            "time_end_utc": utc_iso(primary_development["action_finished_at_unix"].max()),
            "actions": ";".join(
                sorted(primary_development["mitigation_action"].astype(str).unique())
            ),
            "feature_transformations": (
                "93 candidates -> 64 active -> family weighting -> six frozen PCA components"
            ),
            "used_for_fit": True,
            "used_for_hyperparameter_selection": True,
            "used_for_evaluation": True,
            "allowed_claim": (
                "development of representation, k, metric and P99 rule; developmental "
                "kNN/FCM/K-means comparison; not a final holdout"
            ),
            "source_scope_note": "26 primary states and 78 action episodes within a 36-state study",
        },
        {
            "dataset_id": "final_dba_panel",
            "dataset_name": "Zavrsni DBA panel",
            "execution_count": len(final_states) + len(final_outcomes),
            "state_count": len(final_states),
            "action_episode_count": len(final_outcomes),
            "controlled_pair_count": len(final_outcomes),
            "sql_shape_count": int(final_states["query_id"].nunique()),
            "topologies": ";".join(sorted(final_states["topology_id"].astype(str).unique())),
            "time_start_utc": final_start,
            "time_end_utc": final_end,
            "actions": ";".join(sorted(final_outcomes["mitigation_action"].astype(str).unique())),
            "feature_transformations": "frozen 93 -> 64 -> 6 representation; no refit",
            "used_for_fit": False,
            "used_for_hyperparameter_selection": False,
            "used_for_evaluation": True,
            "allowed_claim": (
                "temporal first-occurrence, repeated-query, same-query-excluded transfer, "
                "regret and abstention; not isolated topology causality"
            ),
            "source_scope_note": (
                "21 N2 and 24 N3 decision states collected sequentially; "
                "three action-specific episodes per state"
            ),
        },
        {
            "dataset_id": "controlled_topology_memory_panel",
            "dataset_name": "Kontrolisani N2/N3 topology-memory panel",
            "execution_count": len(topology_runs),
            "state_count": len(topology_states),
            "action_episode_count": len(topology_outcomes),
            "controlled_pair_count": len(topology_outcomes),
            "sql_shape_count": int(topology_states["query_id"].nunique()),
            "topologies": ";".join(sorted(topology_states["topology_id"].astype(str).unique())),
            "time_start_utc": utc_iso(topology_runs["query_started_at_unix"].min()),
            "time_end_utc": utc_iso(topology_runs["query_finished_at_unix"].max()),
            "actions": ";".join(
                sorted(topology_outcomes["mitigation_action"].astype(str).unique())
            ),
            "feature_transformations": "frozen N2 representation and empirical P99; no N3 refit",
            "used_for_fit": False,
            "used_for_hyperparameter_selection": False,
            "used_for_evaluation": True,
            "allowed_claim": (
                "controlled N2-to-N3 physical shift, conservative abstention and N3 local "
                "cross-query adaptation"
            ),
            "source_scope_note": "N2 control, N3 phase A and N3 phase B; same 15 logical scenarios",
        },
    ]
    result = pd.DataFrame(rows)
    checks = {
        "broad_executions": len(broad) == int(expected["broad_executions"]),
        "broad_resolved_primary": int(broad_manifest["resolved_primary_slot_count"])
        == int(expected["broad_executions"]),
        "broad_pairs": int(action_summary["pair_count"]) == int(expected["broad_pairs"]),
        "development_states": len(development_ids) == int(expected["development_states"]),
        "development_episodes": len(primary_development)
        == int(expected["development_action_episodes"]),
        "final_counts": len(final_states) == int(expected["final_states"])
        and len(final_outcomes) == int(expected["final_action_episodes"])
        and len(final_states) + len(final_outcomes) == int(expected["final_executions"]),
        "final_topologies": final_states.groupby("topology_id").size().to_dict()
        == {
            "eu_us_gac": int(expected["final_n2_states"]),
            "eu_us_apac_gac": int(expected["final_n3_states"]),
        },
        "topology_counts": len(topology_states) == int(expected["topology_states"])
        and len(topology_outcomes) == int(expected["topology_action_episodes"])
        and len(topology_runs) == int(expected["topology_executions"]),
        "topology_rounds": topology_states.groupby("round_id").size().to_dict()
        == {key: int(value) for key, value in expected["topology_rounds"].items()},
    }
    if not all(checks.values()):
        raise ValueError(f"Provenance validation failed: {checks}")
    result.attrs["checks"] = checks
    return result


def _topology_baseline_indexes(contract: dict[str, Any]) -> dict[str, pd.DataFrame]:
    root = resolve_input(contract["inputs"]["topology_index_root"])
    names = {
        "n2_control": "n3-topology-memory-v1-n2-control",
        "phase_a": "n3-topology-memory-v1-phase-a-baseline",
        "phase_b": "n3-topology-memory-v1-phase-b-baseline",
    }
    return {
        key: pd.read_csv(root / name / "_index/query_runs.csv", low_memory=False)
        for key, name in names.items()
    }


def _source_sha_for_run(indexes: dict[str, pd.DataFrame], round_id: str, run_id: str) -> str:
    frame = indexes[round_id]
    selected = frame[frame["query_run_id"].astype(str).eq(run_id)]
    if len(selected) != 1:
        raise ValueError(f"Cannot resolve source SQL for {round_id}/{run_id}")
    source = Path(str(selected.iloc[0]["source_sql_file"]))
    if not source.exists():
        raise FileNotFoundError(source)
    return sha256_file(source)


def identity_audit(contract: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    topology_dir = resolve_input(contract["inputs"]["topology_report"])
    states = pd.read_csv(topology_dir / "episode_states.csv", low_memory=False)
    delta = pd.read_csv(topology_dir / "topology_sql_delta_audit.csv", low_memory=False)
    indexes = _topology_baseline_indexes(contract)
    rows: list[dict[str, Any]] = []
    for query_id in sorted(states["query_id"].astype(str).unique()):
        selected = states[states["query_id"].astype(str).eq(query_id)].set_index("round_id")
        n2 = selected.loc["n2_control"]
        phase_a = selected.loc["phase_a"]
        phase_b = selected.loc["phase_b"]
        delta_row = delta[
            delta["query_id"].astype(str).eq(query_id)
            & delta["block_id"].astype(str).eq("phase_a_baseline")
        ].iloc[0]
        rows.append(
            {
                "scenario": query_id,
                "n2_raw_sql_sha256": _source_sha_for_run(
                    indexes, "n2_control", str(n2["baseline_query_run_id"])
                ),
                "n3_phase_a_raw_sql_sha256": _source_sha_for_run(
                    indexes, "phase_a", str(phase_a["baseline_query_run_id"])
                ),
                "n3_phase_b_raw_sql_sha256": _source_sha_for_run(
                    indexes, "phase_b", str(phase_b["baseline_query_run_id"])
                ),
                "n2_normalized_sql_hash": str(n2["normalized_sql_hash"]),
                "n3_phase_a_normalized_sql_hash": str(phase_a["normalized_sql_hash"]),
                "n3_phase_b_normalized_sql_hash": str(phase_b["normalized_sql_hash"]),
                "topology_independent_canonical_sha256": str(delta_row["n2_canonical_sha256"]),
                "logical_query_hash": str(n2["logical_query_hash"]),
                "query_id": query_id,
                "memory_key": str(n2["logical_query_hash"]),
                "memory_key_definition": (
                    "sha256(query_id, query_shape, cutoff_ts, limit_k); topology excluded"
                ),
                "n2_n3_raw_sql_equal": _source_sha_for_run(
                    indexes, "n2_control", str(n2["baseline_query_run_id"])
                )
                == _source_sha_for_run(indexes, "phase_a", str(phase_a["baseline_query_run_id"])),
                "n2_n3_normalized_sql_equal": str(n2["normalized_sql_hash"])
                == str(phase_a["normalized_sql_hash"]),
                "n2_n3_logical_hash_equal": str(n2["logical_query_hash"])
                == str(phase_a["logical_query_hash"]),
                "canonical_sql_matches_after_topology_removal": bool(
                    delta_row["canonical_sql_matches"]
                ),
            }
        )
    audit = pd.DataFrame(rows)
    final_states = pd.read_csv(
        resolve_input(contract["inputs"]["final_panel_report"]) / "observed_episode_states.csv",
        low_memory=False,
    )
    final_context = ["topology_id", "region_count", "dataset_profile_id", "profile"]
    contracts = pd.DataFrame(
        [
            {
                "scope": "final_dba_panel_direct_branch",
                "canonical_name": "exact_query_memory",
                "legacy_name": "exact_query_memory",
                "identity_key": "normalized_sql_hash + compatible_context",
                "context_fields": ";".join(final_context),
                "automatic_text_identity": True,
                "note": "normalized SQL identity, not byte-identical raw SQL",
            },
            {
                "scope": "topology_panel_topology_agnostic_branch",
                "canonical_name": "logical_query_memory",
                "legacy_name": "blind_exact_query",
                "identity_key": "logical_query_hash",
                "context_fields": "",
                "automatic_text_identity": False,
                "note": "manual topology-independent scenario contract",
            },
            {
                "scope": "topology_panel_context_branch",
                "canonical_name": "context_logical_query_memory",
                "legacy_name": "context_exact_query",
                "identity_key": "logical_query_hash + topology_id + dataset_pair + profile",
                "context_fields": "topology_id;dataset_pair;profile",
                "automatic_text_identity": False,
                "note": "logical scenario identity constrained to compatible context",
            },
        ]
    )
    final_key = final_states.assign(
        context_key=final_states[final_context].astype(str).agg("|".join, axis=1)
    )
    checks = {
        "scenario_count": len(audit) == int(contract["expected"]["topology_scenarios"]),
        "raw_sql_changes_with_apac_branch": not audit["n2_n3_raw_sql_equal"].any(),
        "normalized_sql_changes_with_apac_branch": not audit["n2_n3_normalized_sql_equal"].any(),
        "logical_identity_stable_across_topology": audit["n2_n3_logical_hash_equal"].all(),
        "canonical_sql_equal_after_source_removal": audit[
            "canonical_sql_matches_after_topology_removal"
        ].all(),
        "logical_hash_bijective_with_query_id": audit["logical_query_hash"].nunique()
        == audit["query_id"].nunique()
        == len(audit),
        "final_exact_key_does_not_merge_query_ids": (
            final_key.groupby(["normalized_sql_hash", "context_key"])["query_id"].nunique().max()
            == 1
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"Identity audit failed: {checks}")
    return audit, contracts, checks


def _frozen_r3(
    contract: dict[str, Any], ablation: Any, memory: Any, data: Any
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    artifact_path = resolve_input(contract["inputs"]["frozen_full_model"])
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if artifact.get("fitted_on_n3") is not False:
        raise ValueError("Frozen R3 artifact was fitted on N3")
    transformer = ablation.FrozenFullTransformer(
        data.state_contract["state_representation"]["features"], artifact, memory
    )
    values = (
        transformer.transform(data.reference_states),
        transformer.transform(data.final_states),
        transformer.transform(data.topology_states),
    )
    expected = contract["expected"]
    if len(data.state_contract["state_representation"]["features"]) != int(
        expected["r3_candidate_features"]
    ):
        raise ValueError("R3 candidate feature count changed")
    if len(artifact["active_features"]) != int(expected["r3_active_features"]):
        raise ValueError("R3 active feature count changed")
    if values[0].shape[1] != int(expected["r3_components"]):
        raise ValueError("R3 component count changed")
    return (*values, artifact)


def _actual_gains(outcomes: pd.DataFrame, episode_id: str, actions: list[str]) -> dict[str, float]:
    selected = outcomes[outcomes["episode_id"].astype(str).eq(episode_id)].set_index(
        "mitigation_action"
    )["target_log2_gain"]
    if set(actions) - set(selected.index.astype(str)):
        raise ValueError(f"Incomplete outcomes for {episode_id}")
    return {action: float(selected[action]) for action in actions}


def _evaluate_event(
    event: pd.Series,
    value: np.ndarray,
    memory_states: pd.DataFrame,
    memory_outcomes: pd.DataFrame,
    memory_values: np.ndarray,
    actual_outcomes: pd.DataFrame,
    *,
    evaluation: str,
    metric: str,
    neighbors: int,
    quantile: float,
    threshold: float,
    contract: dict[str, Any],
    dba: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    actions = [str(value) for value in contract["policy"]["actions"]]
    estimator_states = memory_states.copy().reset_index(drop=True)
    estimator_states["normalized_sql_hash"] = estimator_states["logical_identity"]
    predictions, evidence, nearest, eligible_count = dba._estimate_from_memory(
        value,
        memory_values,
        estimator_states,
        memory_outcomes,
        neighbors=neighbors,
        epsilon=float(contract["policy"]["distance_epsilon"]),
        distance_metric=metric,
        excluded_query_id=str(event["query_id"]),
        excluded_normalized_sql_hash=str(event["logical_identity"]),
    )
    status = dba._status(
        memory_count=eligible_count,
        nearest_distance=nearest,
        coverage_threshold=threshold,
        minimum_history=int(contract["policy"]["minimum_history_for_available"]),
    )
    _candidate, predicted = dba._decision_actions(predictions, status, tuple(actions))
    actual = _actual_gains(actual_outcomes, str(event["episode_id"]), actions)
    actual_best = max(actions, key=actual.__getitem__)
    predicted_values = [float(predictions[action]) for action in actions]
    finite_predictions = [value for value in predicted_values if math.isfinite(value)]
    predicted_margin = (
        sorted(finite_predictions, reverse=True)[0] - sorted(finite_predictions, reverse=True)[1]
        if len(finite_predictions) >= 2
        else float("nan")
    )
    response_l2: list[float] = []
    best_disagreement: list[float] = []
    for neighbor in evidence:
        gains = neighbor["action_gains"]
        response_l2.append(
            float(np.linalg.norm([actual[action] - float(gains[action]) for action in actions]))
        )
        best_disagreement.append(
            float(max(actions, key=lambda action: float(gains[action])) != actual_best)
        )
    ordered_distances = sorted(float(row["distance"]) for row in evidence)
    row = {
        "evaluation": evaluation,
        "episode_id": str(event["episode_id"]),
        "query_id": str(event["query_id"]),
        "logical_identity": str(event["logical_identity"]),
        "topology_id": str(event["topology_id"]),
        "distance_metric": metric,
        "neighbors": neighbors,
        "coverage_quantile": quantile,
        "coverage_threshold": threshold,
        "nearest_distance": nearest,
        "normalized_nearest_distance": nearest / threshold if threshold > 0 else float("inf"),
        "coverage_margin": threshold - nearest,
        "nearest_second_distance_margin": (
            ordered_distances[1] - ordered_distances[0]
            if len(ordered_distances) >= 2
            else float("nan")
        ),
        "predicted_action_margin": predicted_margin,
        "eligible_history_state_count": eligible_count,
        "decision_status": status,
        "predicted_action": predicted,
        "actual_best_action": actual_best,
        "top1_correct": bool(predicted and predicted == actual_best),
        "regret_log2": actual[actual_best] - actual[predicted] if predicted else float("nan"),
        "neighbor_response_l2_mean": float(np.mean(response_l2)) if response_l2 else float("nan"),
        "neighbor_best_action_disagreement_share": (
            float(np.mean(best_disagreement)) if best_disagreement else float("nan")
        ),
        **{f"predicted_gain__{action}": predictions[action] for action in actions},
        **{f"actual_gain__{action}": actual[action] for action in actions},
    }
    traces = [
        {
            "evaluation": evaluation,
            "episode_id": str(event["episode_id"]),
            "query_id": str(event["query_id"]),
            "distance_metric": metric,
            "neighbors": neighbors,
            "coverage_quantile": quantile,
            "neighbor_rank": rank,
            "neighbor_episode_id": neighbor["episode_id"],
            "neighbor_query_id": neighbor["query_id"],
            "neighbor_topology_id": neighbor["topology_id"],
            "distance": neighbor["distance"],
            "weight": neighbor["weight"],
            "action_gains_json": json.dumps(
                neighbor["action_gains"], sort_keys=True, separators=(",", ":")
            ),
        }
        for rank, neighbor in enumerate(evidence, start=1)
    ]
    return row, traces


def _threshold_variant(
    row: dict[str, Any],
    *,
    quantile: float,
    threshold: float,
    contract: dict[str, Any],
    dba: Any,
) -> dict[str, Any]:
    actions = [str(value) for value in contract["policy"]["actions"]]
    result = dict(row)
    status = dba._status(
        memory_count=int(row["eligible_history_state_count"]),
        nearest_distance=float(row["nearest_distance"]),
        coverage_threshold=threshold,
        minimum_history=int(contract["policy"]["minimum_history_for_available"]),
    )
    predictions = {action: float(row[f"predicted_gain__{action}"]) for action in actions}
    _candidate, predicted = dba._decision_actions(predictions, status, tuple(actions))
    actual = {action: float(row[f"actual_gain__{action}"]) for action in actions}
    actual_best = max(actions, key=actual.__getitem__)
    result.update(
        {
            "coverage_quantile": quantile,
            "coverage_threshold": threshold,
            "normalized_nearest_distance": (
                float(row["nearest_distance"]) / threshold if threshold > 0 else float("inf")
            ),
            "coverage_margin": threshold - float(row["nearest_distance"]),
            "decision_status": status,
            "predicted_action": predicted,
            "top1_correct": bool(predicted and predicted == actual_best),
            "regret_log2": (actual[actual_best] - actual[predicted] if predicted else float("nan")),
        }
    )
    return result


def sensitivity_analysis(
    contract: dict[str, Any],
    data: Any,
    reference: np.ndarray,
    final: np.ndarray,
    topology: np.ndarray,
    dba: Any,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    policy = contract["policy"]
    rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    final_map = dict(zip(data.final_states["episode_id"].astype(str), final, strict=True))
    topology_map = dict(zip(data.topology_states["episode_id"].astype(str), topology, strict=True))
    for metric in policy["sensitivity_metrics"]:
        thresholds = {
            float(quantile): dba._nearest_threshold(reference, float(quantile), str(metric))
            for quantile in policy["sensitivity_quantiles"]
        }
        base_quantile = float(policy["frozen_coverage_quantile"])
        base_threshold = thresholds[base_quantile]
        for neighbors in policy["sensitivity_neighbors"]:
            memory_states = data.reference_states.copy().reset_index(drop=True)
            memory_outcomes = data.reference_outcomes.copy().reset_index(drop=True)
            memory_values = reference.copy()
            for _, event in data.final_states.sort_values("episode_order").iterrows():
                row, event_traces = _evaluate_event(
                    event,
                    final_map[str(event["episode_id"])],
                    memory_states,
                    memory_outcomes,
                    memory_values,
                    data.final_outcomes,
                    evaluation="E2",
                    metric=str(metric),
                    neighbors=int(neighbors),
                    quantile=base_quantile,
                    threshold=base_threshold,
                    contract=contract,
                    dba=dba,
                )
                rows.extend(
                    _threshold_variant(
                        row,
                        quantile=quantile,
                        threshold=threshold,
                        contract=contract,
                        dba=dba,
                    )
                    for quantile, threshold in thresholds.items()
                )
                traces.extend(event_traces)
                memory_states = pd.concat([memory_states, event.to_frame().T], ignore_index=True)
                selected = data.final_outcomes[
                    data.final_outcomes["episode_id"].astype(str).eq(str(event["episode_id"]))
                ]
                memory_outcomes = pd.concat([memory_outcomes, selected], ignore_index=True)
                memory_values = np.vstack(
                    [memory_values, final_map[str(event["episode_id"])][None, :]]
                )
            n2_mask = data.topology_states["round_id"].astype(str).eq("n2_control")
            a_mask = data.topology_states["round_id"].astype(str).eq("phase_a")
            b_mask = data.topology_states["round_id"].astype(str).eq("phase_b")
            n2_states = data.topology_states[n2_mask].reset_index(drop=True)
            a_states = data.topology_states[a_mask].reset_index(drop=True)
            b_states = data.topology_states[b_mask].reset_index(drop=True)
            n2_values = topology[n2_mask.to_numpy()]
            a_values = topology[a_mask.to_numpy()]
            memories = {
                "E3": (
                    pd.concat([data.reference_states, n2_states], ignore_index=True),
                    pd.concat(
                        [
                            data.reference_outcomes,
                            data.topology_outcomes[
                                data.topology_outcomes["round_id"].eq("n2_control")
                            ],
                        ],
                        ignore_index=True,
                    ),
                    np.vstack([reference, n2_values]),
                    a_states,
                    data.topology_outcomes[data.topology_outcomes["round_id"].eq("phase_a")],
                ),
                "E4": (
                    pd.concat([data.reference_states, n2_states, a_states], ignore_index=True),
                    pd.concat(
                        [
                            data.reference_outcomes,
                            data.topology_outcomes[
                                data.topology_outcomes["round_id"].isin(["n2_control", "phase_a"])
                            ],
                        ],
                        ignore_index=True,
                    ),
                    np.vstack([reference, n2_values, a_values]),
                    b_states,
                    data.topology_outcomes[data.topology_outcomes["round_id"].eq("phase_b")],
                ),
            }
            for evaluation, (
                fixed_states,
                fixed_outcomes,
                fixed_values,
                events,
                actual,
            ) in memories.items():
                for _, event in events.sort_values("episode_order").iterrows():
                    row, event_traces = _evaluate_event(
                        event,
                        topology_map[str(event["episode_id"])],
                        fixed_states,
                        fixed_outcomes,
                        fixed_values,
                        actual,
                        evaluation=evaluation,
                        metric=str(metric),
                        neighbors=int(neighbors),
                        quantile=base_quantile,
                        threshold=base_threshold,
                        contract=contract,
                        dba=dba,
                    )
                    rows.extend(
                        _threshold_variant(
                            row,
                            quantile=quantile,
                            threshold=threshold,
                            contract=contract,
                            dba=dba,
                        )
                        for quantile, threshold in thresholds.items()
                    )
                    traces.extend(event_traces)
    episode_rows = pd.DataFrame(rows)
    summary_rows: list[dict[str, Any]] = []
    for keys, group in episode_rows.groupby(
        ["evaluation", "distance_metric", "neighbors", "coverage_quantile"],
        sort=True,
    ):
        recommended = group[group["predicted_action"].fillna("").astype(str).ne("")]
        summary_rows.append(
            {
                "evaluation": keys[0],
                "distance_metric": keys[1],
                "neighbors": keys[2],
                "coverage_quantile": keys[3],
                "coverage_threshold": float(group["coverage_threshold"].iloc[0]),
                "episode_count": len(group),
                "recommendation_count": len(recommended),
                "abstention_count": len(group) - len(recommended),
                "coverage": len(recommended) / len(group),
                "correct_count": int(recommended["top1_correct"].sum()),
                "top1_accuracy": (
                    float(recommended["top1_correct"].mean()) if len(recommended) else float("nan")
                ),
                "mean_regret_log2": (
                    float(recommended["regret_log2"].mean()) if len(recommended) else float("nan")
                ),
            }
        )
    return episode_rows, pd.DataFrame(summary_rows), pd.DataFrame(traces)


def distance_error_analysis(episode_rows: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    policy = contract["policy"]
    selected = episode_rows[
        episode_rows["distance_metric"].eq(policy["frozen_distance_metric"])
        & episode_rows["neighbors"].eq(int(policy["frozen_neighbors"]))
        & episode_rows["coverage_quantile"].eq(float(policy["frozen_coverage_quantile"]))
    ]
    rows: list[dict[str, Any]] = []
    for evaluation, group in selected.groupby("evaluation", sort=True):
        recommended = group[group["predicted_action"].fillna("").astype(str).ne("")]
        pairs = {
            "nearest_distance_vs_top1_error": (
                recommended["nearest_distance"],
                (~recommended["top1_correct"].astype(bool)).astype(float),
            ),
            "nearest_distance_vs_regret": (
                recommended["nearest_distance"],
                recommended["regret_log2"],
            ),
            "nearest_distance_vs_response_disagreement": (
                recommended["nearest_distance"],
                recommended["neighbor_response_l2_mean"],
            ),
            "response_disagreement_vs_top1_error": (
                recommended["neighbor_response_l2_mean"],
                (~recommended["top1_correct"].astype(bool)).astype(float),
            ),
        }
        for relationship, (left, right) in pairs.items():
            joined = pd.concat([left, right], axis=1).dropna()
            coefficient, p_value = (
                spearmanr(joined.iloc[:, 0], joined.iloc[:, 1])
                if len(joined) >= 3 and joined.iloc[:, 0].nunique() > 1
                else (float("nan"), float("nan"))
            )
            rows.append(
                {
                    "evaluation": evaluation,
                    "relationship": relationship,
                    "sample_count": len(joined),
                    "spearman_rho": coefficient,
                    "p_value_exploratory": p_value,
                    "interpretation_scope": "exploratory; not causal or calibrated",
                }
            )
    return pd.DataFrame(rows)


def action_stability(data: Any, contract: dict[str, Any]) -> pd.DataFrame:
    actions = [str(value) for value in contract["policy"]["actions"]]
    rows: list[dict[str, Any]] = []
    for scope, states, outcomes, grouping in (
        ("final_panel_repeated_sql", data.final_states, data.final_outcomes, "query_id"),
        ("controlled_topology_rounds", data.topology_states, data.topology_outcomes, "query_id"),
    ):
        best = []
        for episode_id in states["episode_id"].astype(str):
            gains = _actual_gains(outcomes, episode_id, actions)
            best.append(
                {
                    "episode_id": episode_id,
                    grouping: str(
                        states.loc[states["episode_id"].astype(str).eq(episode_id), grouping].iloc[
                            0
                        ]
                    ),
                    "best_action": max(actions, key=gains.__getitem__),
                }
            )
        frame = pd.DataFrame(best)
        for identity, group in frame.groupby(grouping, sort=True):
            rows.append(
                {
                    "scope": scope,
                    "query_id": identity,
                    "observation_count": len(group),
                    "distinct_best_action_count": group["best_action"].nunique(),
                    "stable_best_action": group["best_action"].nunique() == 1,
                    "best_actions": ";".join(group["best_action"].astype(str)),
                }
            )
    return pd.DataFrame(rows)


def q08_failure_analysis(
    contract: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    report = resolve_input(contract["inputs"]["topology_report"])
    scored = pd.read_csv(report / "phase_recommendations_scored.csv", low_memory=False)
    states = pd.read_csv(report / "episode_states.csv", low_memory=False)
    outcomes = pd.read_csv(report / "action_outcomes.csv", low_memory=False)
    selected = scored[
        scored["phase"].astype(str).eq("B")
        & scored["method"].astype(str).eq("cross_query_knn")
        & scored["query_id"].astype(str).eq("q08_tenant_avg")
    ]
    if len(selected) != 1:
        raise ValueError("Expected one q08 phase-B cross-query row")
    row = selected.iloc[0]
    evidence = json.loads(str(row["neighbor_evidence_json"]))
    state_by_episode = states.set_index("episode_id", drop=False)
    neighbor_rows: list[dict[str, Any]] = []
    actions = [str(value) for value in contract["policy"]["actions"]]
    for rank, neighbor in enumerate(evidence, start=1):
        state = state_by_episode.loc[str(neighbor["episode_id"])]
        gains = {action: float(neighbor["action_gains"][action]) for action in actions}
        neighbor_rows.append(
            {
                "neighbor_rank": rank,
                "episode_id": neighbor["episode_id"],
                "query_id": neighbor["query_id"],
                "logical_query_hash": str(state["logical_query_hash"]),
                "topology_id": neighbor["topology_id"],
                "distance": float(neighbor["distance"]),
                "weight": float(neighbor["weight"]),
                **{f"gain__{action}": gains[action] for action in actions},
                "best_action": max(actions, key=gains.__getitem__),
            }
        )
    neighbors = pd.DataFrame(neighbor_rows)
    actual = {action: float(row[f"actual_gain__{action}"]) for action in actions}
    predicted = {action: float(row[f"predicted_gain__{action}"]) for action in actions}
    actual_order = sorted(actions, key=lambda action: (-actual[action], action))
    predicted_order = sorted(actions, key=lambda action: (-predicted[action], action))
    rankings = pd.DataFrame(
        [
            {
                "action": action,
                "predicted_gain_log2": predicted[action],
                "predicted_rank": predicted_order.index(action) + 1,
                "actual_gain_log2": actual[action],
                "actual_rank": actual_order.index(action) + 1,
            }
            for action in actions
        ]
    )
    phase_b = scored[
        scored["phase"].astype(str).eq("B") & scored["method"].astype(str).eq("cross_query_knn")
    ]
    with_q08 = float(phase_b["regret_log2"].mean())
    without_q08 = float(
        phase_b.loc[~phase_b["query_id"].astype(str).eq("q08_tenant_avg"), "regret_log2"].mean()
    )
    q08_history = []
    for round_id in ("n2_control", "phase_a", "phase_b"):
        gains = outcomes[
            outcomes["round_id"].astype(str).eq(round_id)
            & outcomes["query_id"].astype(str).eq("q08_tenant_avg")
        ].set_index("mitigation_action")["target_log2_gain"]
        q08_history.append(
            {
                "round_id": round_id,
                "best_action": str(gains.idxmax()),
                **{f"gain__{action}": float(gains[action]) for action in actions},
            }
        )
    summary = {
        "episode_id": str(row["episode_id"]),
        "query_id": str(row["query_id"]),
        "logical_query_hash": str(row["logical_query_hash"]),
        "topology_id": str(row["topology_id"]),
        "nearest_distance": float(row["nearest_distance"]),
        "coverage_threshold": float(row["coverage_threshold"]),
        "predicted_action": str(row["predicted_action"]),
        "actual_best_action": str(row["actual_best_action"]),
        "regret_log2": float(row["regret_log2"]),
        "predicted_top2_margin_log2": predicted[predicted_order[0]] - predicted[predicted_order[1]],
        "actual_top2_margin_log2": actual[actual_order[0]] - actual[actual_order[1]],
        "phase_b_mean_regret_with_q08": with_q08,
        "phase_b_mean_regret_without_q08": without_q08,
        "q08_share_of_total_phase_b_regret": float(row["regret_log2"])
        / float(phase_b["regret_log2"].sum()),
        "neighbor_best_action_counts": neighbors["best_action"].value_counts().to_dict(),
        "q08_round_stability": q08_history,
        "diagnosis": (
            "Three of five neighbors favor regional Top-K, but two more distant neighbors "
            "have much larger remote-over-regional gain margins. Inverse-distance weighted "
            "gain averaging therefore narrowly ranks remote first. q08 itself has a stable, "
            "much larger regional-over-remote margin in N2, phase A and phase B. The failure "
            "is action-response mismatch among physically close cases, not missing action "
            "support or instability of q08."
        ),
        "excluded_from_primary_result": False,
    }
    expected = float(contract["expected"]["q08_regret_log2"])
    if not math.isclose(summary["regret_log2"], expected, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("q08 regret changed")
    return neighbors, rankings, summary


def cluster_bootstrap(episode_rows: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    policy = contract["policy"]
    selected = episode_rows[
        episode_rows["distance_metric"].eq(policy["frozen_distance_metric"])
        & episode_rows["neighbors"].eq(int(policy["frozen_neighbors"]))
        & episode_rows["coverage_quantile"].eq(float(policy["frozen_coverage_quantile"]))
    ]
    specification = contract["bootstrap"]
    rng = np.random.default_rng(int(specification["random_seed"]))
    samples = int(specification["samples"])
    alpha = (1.0 - float(specification["confidence_level"])) / 2.0
    rows: list[dict[str, Any]] = []
    for evaluation, frame in selected.groupby("evaluation", sort=True):
        query_ids = sorted(frame["query_id"].astype(str).unique())
        aggregates: list[tuple[float, float, float, float]] = []
        for query_id in query_ids:
            group = frame[frame["query_id"].astype(str).eq(query_id)]
            recommended = group[group["predicted_action"].fillna("").astype(str).ne("")]
            aggregates.append(
                (
                    float(len(group)),
                    float(len(recommended)),
                    float(recommended["top1_correct"].sum()),
                    float(recommended["regret_log2"].sum()),
                )
            )
        cluster_values = np.asarray(aggregates, dtype=float)
        sampled_indexes = rng.integers(0, len(query_ids), size=(samples, len(query_ids)))
        totals = cluster_values[sampled_indexes].sum(axis=1)
        draws = {
            "coverage": np.divide(
                totals[:, 1], totals[:, 0], out=np.zeros(samples), where=totals[:, 0] > 0
            ),
            "top1_accuracy": np.divide(
                totals[:, 2],
                totals[:, 1],
                out=np.full(samples, np.nan),
                where=totals[:, 1] > 0,
            ),
            "mean_regret_log2": np.divide(
                totals[:, 3],
                totals[:, 1],
                out=np.full(samples, np.nan),
                where=totals[:, 1] > 0,
            ),
        }
        for metric, values in draws.items():
            finite = np.asarray(values, dtype=float)
            finite = finite[np.isfinite(finite)]
            rows.append(
                {
                    "evaluation": evaluation,
                    "metric": metric,
                    "estimate": (float(np.mean(finite)) if len(finite) else float("nan")),
                    "ci_lower": (
                        float(np.quantile(finite, alpha)) if len(finite) else float("nan")
                    ),
                    "ci_upper": (
                        float(np.quantile(finite, 1.0 - alpha)) if len(finite) else float("nan")
                    ),
                    "bootstrap_samples": samples,
                    "cluster_key": "query_id",
                }
            )
    return pd.DataFrame(rows)


def claim_evidence_matrix(
    contract: dict[str, Any],
    representation_summary: pd.DataFrame,
    topology_summary: dict[str, Any],
    q08: dict[str, Any],
) -> pd.DataFrame:
    e4 = representation_summary[
        representation_summary["evaluation"].eq("E4")
        & representation_summary["representation"].eq("R3_full_multilayer")
    ].iloc[0]
    return pd.DataFrame(
        [
            {
                "claim_id": "C1",
                "claim": (
                    "Collector produced one complete primary record for every planned "
                    "broad-corpus slot."
                ),
                "status": "supported_in_controlled_corpus",
                "evidence": "2607/2607 resolved primary executions; no missing or duplicate slots",
                "source": "broad_intervention_corpus",
                "prohibited_overclaim": "arbitrary production concurrency reliability",
            },
            {
                "claim_id": "C2",
                "claim": "All broad-corpus controlled pairs have equivalent query results.",
                "status": "supported",
                "evidence": "418/418 after typed correctness recovery",
                "source": "broad_intervention_corpus",
                "prohibited_overclaim": "all possible rewrites are semantics preserving",
            },
            {
                "claim_id": "C3",
                "claim": (
                    "Full multilayer state supports cross-query action transfer on the final panel."
                ),
                "status": "supported_within_panel",
                "evidence": (
                    "E1 14/15 coverage, 12/14 correct, regret 0.0443; E2 41/45, 38/41, 0.0214"
                ),
                "source": "final_dba_panel+representation_ablation",
                "prohibited_overclaim": "universal action optimizer",
            },
            {
                "claim_id": "C4",
                "claim": (
                    "N2 to N3 creates a physical representation shift without changing "
                    "the best action in this panel."
                ),
                "status": "supported_in_controlled_panel",
                "evidence": "15/15 phase-A R3 states outside N2 P99; 15/15 best actions unchanged",
                "source": "controlled_topology_memory_panel",
                "prohibited_overclaim": "N3 always preserves action ranking",
            },
            {
                "claim_id": "C5",
                "claim": (
                    "Phase-A R3 abstention follows the frozen physical coverage rule but "
                    "is conservative for action selection."
                ),
                "status": "supported",
                "evidence": "R3 0/15 coverage; topology-independent logical memory 15/15 correct",
                "source": "controlled_topology_memory_panel+representation_ablation",
                "prohibited_overclaim": "P99 is a calibrated error probability or safety guarantee",
            },
            {
                "claim_id": "C6",
                "claim": (
                    "After phase-A N3 cases are retained, same-query-excluded N3 "
                    "cross-query transfer becomes available."
                ),
                "status": "supported_with_failure_case",
                "evidence": (
                    f"{int(e4['recommendation_count'])}/15 coverage, "
                    f"{int(e4['correct_decision_count'])}/15 correct, regret "
                    f"{float(e4['mean_regret_log2']):.4f}; q08 regret {q08['regret_log2']:.4f}"
                ),
                "source": "controlled_topology_memory_panel+representation_ablation",
                "prohibited_overclaim": "hierarchical/logical 100% as cross-query evidence",
            },
            {
                "claim_id": "C7",
                "claim": "Prototype compression is not the final operational memory.",
                "status": "developmental_comparison_only",
                "evidence": (
                    "development panel: direct kNN retained more useful local detail than "
                    "FCM; K-means also competitive"
                ),
                "source": "development_reference_panel",
                "prohibited_overclaim": "FCM comparison is a final holdout result",
            },
            {
                "claim_id": "C8",
                "claim": "Physical novelty and action-response novelty are distinct.",
                "status": "supported_as_diagnostic_observation",
                "evidence": (
                    "R3 N2-N3 median distance 6.799 versus P99 1.953 while all 30 matched "
                    "pairs retain the best action"
                ),
                "source": "representation_ablation+controlled_topology_memory_panel",
                "prohibited_overclaim": "physical distance is calibrated to action-selection error",
            },
        ]
    )


def _figure_representation(summary: pd.DataFrame, out_dir: Path) -> None:
    evaluations = ["E1", "E2", "E3", "E4"]
    representations = [
        "R1_sql_structural",
        "R2_coordinator_physical",
        "R3_full_multilayer",
    ]
    labels = {
        "R1_sql_structural": "R1 SQL",
        "R2_coordinator_physical": "R2 koordinator",
        "R3_full_multilayer": "R3 višeslojno",
    }
    colors = ["#727272", "#2f7f74", "#b84a3a"]
    fig, axes = plt.subplots(1, 3, figsize=(11.4, 3.5))
    metrics = [
        ("coverage", "Pokrivenost"),
        ("top1_accuracy", "Top-1 među preporukama"),
        ("mean_regret_log2", "Prosječni propušteni dobitak"),
    ]
    x = np.arange(len(evaluations))
    width = 0.24
    for axis, (metric, title) in zip(axes, metrics, strict=True):
        for offset, (representation, color) in enumerate(zip(representations, colors, strict=True)):
            values = []
            for evaluation in evaluations:
                row = summary[
                    summary["evaluation"].eq(evaluation)
                    & summary["representation"].eq(representation)
                ].iloc[0]
                values.append(float(row[metric]) if pd.notna(row[metric]) else 0.0)
            axis.bar(
                x + (offset - 1) * width, values, width, label=labels[representation], color=color
            )
        axis.set_title(title)
        axis.set_xticks(x, evaluations)
        axis.grid(axis="y", alpha=0.25)
        if metric != "mean_regret_log2":
            axis.set_ylim(0, 1.05)
    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="lower center", ncol=3, frameon=False)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    for suffix in ("pdf", "png"):
        fig.savefig(out_dir / f"representation_ablation.{suffix}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def _figure_topology(ablation_release: Path, out_dir: Path) -> None:
    matched = pd.read_csv(ablation_release / "matched_query_topology_pairs.csv")
    summary = pd.read_csv(ablation_release / "representation_summary.csv")
    r3 = matched[matched["representation"].eq("R3_full_multilayer")]
    e3 = summary[
        summary["evaluation"].eq("E3") & summary["representation"].eq("R3_full_multilayer")
    ].iloc[0]
    e4 = summary[
        summary["evaluation"].eq("E4") & summary["representation"].eq("R3_full_multilayer")
    ].iloc[0]
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.7))
    distances = np.sort(r3["representation_distance_l2"].to_numpy(dtype=float))
    cumulative_share = np.arange(1, len(distances) + 1) / len(distances)
    axes[0].step(distances, cumulative_share, where="post", color="#2f7f74", linewidth=2)
    axes[0].scatter(distances, cumulative_share, color="#2f7f74", s=14)
    axes[0].axvline(1.9533554892194174, color="#b84a3a", linestyle="--", label="N2 P99")
    axes[0].set_xlabel("R3 udaljenost N2–N3")
    axes[0].set_ylabel("Kumulativni udio uparenih stanja")
    axes[0].set_ylim(0, 1.05)
    axes[0].legend(frameon=False)
    axes[0].set_title("Fizički pomak topologije")
    x = np.arange(2)
    axes[1].bar(
        x - 0.18, [e3["coverage"], e4["coverage"]], 0.36, color="#727272", label="Pokrivenost"
    )
    axes[1].bar(
        x + 0.18,
        [0 if pd.isna(e3["top1_accuracy"]) else e3["top1_accuracy"], e4["top1_accuracy"]],
        0.36,
        color="#b84a3a",
        label="Top-1",
    )
    axes[1].set_xticks(x, ["N3 faza A\nN2 memorija", "N3 faza B\n+ raniji N3 slučajevi"])
    axes[1].set_ylim(0, 1.05)
    axes[1].set_title("Pokrivenost nakon lokalne adaptacije")
    axes[1].legend(frameon=False)
    axes[1].grid(axis="y", alpha=0.25)
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(out_dir / f"topology_shift_adaptation.{suffix}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def _figure_q08(rankings: pd.DataFrame, out_dir: Path) -> None:
    labels = {
        "increase_gac_work_mem": "GAC work_mem",
        "regional_topk_candidates": "Regionalni Top-K",
        "mitigate_remote_path_bundle": "Remote",
    }
    x = np.arange(len(rankings))
    width = 0.36
    fig, axis = plt.subplots(figsize=(7.4, 3.8))
    axis.bar(
        x - width / 2, rankings["predicted_gain_log2"], width, label="Procjena", color="#727272"
    )
    axis.bar(x + width / 2, rankings["actual_gain_log2"], width, label="Izmjereno", color="#b84a3a")
    axis.set_xticks(x, [labels[value] for value in rankings["action"]])
    axis.set_ylabel("Dobitak, log2")
    axis.set_title("q08: fizički bliski susjedi, različit akcijski odziv")
    axis.legend(frameon=False)
    axis.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(out_dir / f"q08_failure_case.{suffix}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def _figure_coverage_regret(summary: pd.DataFrame, out_dir: Path) -> None:
    selected = summary[
        summary["distance_metric"].eq("euclidean")
        & summary["neighbors"].eq(5)
        & summary["evaluation"].isin(["E2", "E3", "E4"])
    ]
    fig, axis = plt.subplots(figsize=(6.8, 4.2))
    colors = {"E2": "#2f7f74", "E3": "#727272", "E4": "#b84a3a"}
    plotted_evaluations: list[str] = []
    for evaluation, group in selected.groupby("evaluation"):
        ordered = group.sort_values("coverage_quantile")
        finite = ordered["mean_regret_log2"].notna()
        if not finite.any():
            continue
        ordered = ordered[finite]
        plotted_evaluations.append(str(evaluation))
        axis.plot(
            ordered["coverage"],
            ordered["mean_regret_log2"],
            marker="o",
            color=colors[evaluation],
            label=evaluation,
        )
        point_labels: dict[tuple[float, float], list[str]] = {}
        for row in ordered.itertuples():
            point = (float(row.coverage), float(row.mean_regret_log2))
            point_labels.setdefault(point, []).append(f"P{int(row.coverage_quantile * 100)}")
        for (coverage, regret), labels in point_labels.items():
            axis.annotate(
                "/".join(labels),
                (coverage, regret),
                xytext=(3, 3),
                textcoords="offset points",
                fontsize=8,
            )
    if "E3" not in plotted_evaluations:
        axis.text(
            0.02,
            0.04,
            "E3: 0/15 pokrivenih pri svim prikazanim pragovima",
            transform=axis.transAxes,
            fontsize=8,
            color=colors["E3"],
        )
    axis.set_xlabel("Pokrivenost")
    axis.set_ylabel("Prosječni propušteni dobitak, log2")
    axis.set_title("Osjetljivost na granicu apstinencije")
    axis.grid(alpha=0.25)
    axis.legend(frameon=False)
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(out_dir / f"coverage_regret_curve.{suffix}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def write_report(
    out_dir: Path,
    provenance: pd.DataFrame,
    identities: pd.DataFrame,
    representation_summary: pd.DataFrame,
    robustness: pd.DataFrame,
    q08: dict[str, Any],
    claims: pd.DataFrame,
    distance_analysis: pd.DataFrame,
) -> None:
    e1 = representation_summary[
        representation_summary["evaluation"].eq("E1")
        & representation_summary["representation"].eq("R3_full_multilayer")
    ].iloc[0]
    e2 = representation_summary[
        representation_summary["evaluation"].eq("E2")
        & representation_summary["representation"].eq("R3_full_multilayer")
    ].iloc[0]
    e3 = representation_summary[
        representation_summary["evaluation"].eq("E3")
        & representation_summary["representation"].eq("R3_full_multilayer")
    ].iloc[0]
    e4 = representation_summary[
        representation_summary["evaluation"].eq("E4")
        & representation_summary["representation"].eq("R3_full_multilayer")
    ].iloc[0]
    text = f"""# Konsolidovana evaluacija

Ovaj paket ne pokrece SQL, ne refituje modele i ne mijenja zamrznutu
konfiguraciju. Spaja cetiri dokazna skupa, Task 1B representation ablation i
kontrolisani N2/N3 panel.

## Glavni rezultati

- Siroki korpus: 2.607/2.607 primarnih izvrsenja i 418/418 rezultatski
  ekvivalentnih kontrolisanih parova.
- Zavrsni DBA panel je full-information evaluacija sa 45 stanja, 135
  action-specific epizoda i 180 izvrsenja. Tri ishoda istog stanja otkrivaju
  se zajedno tek nakon preporuke.
- R3 E1: {int(e1.recommendation_count)}/15 preporuka,
  Top-1 {float(e1.top1_accuracy):.3f}, regret {float(e1.mean_regret_log2):.4f}.
- R3 E2 bez istog query/logickog identiteta: {int(e2.recommendation_count)}/45,
  Top-1 {float(e2.top1_accuracy):.3f}, regret {float(e2.mean_regret_log2):.4f}.
- N3 faza A: R3 je izvan zamrznute N2 P99 granice u 15/15 slucajeva i
  apstinira u {int(e3.abstention_count)}/15. Najbolja akcija ipak ostaje ista
  kao u uparenom N2 stanju u 15/15 slucajeva.
- N3 faza B: R3 cross-query memorija pokriva {int(e4.recommendation_count)}/15,
  bira ispravno {int(e4.correct_decision_count)}/15 i ima regret
  {float(e4.mean_regret_log2):.4f}. Staticni baseline ima Top-1 0,600 i regret
  0,3678.
- q08 ostaje u glavnom rezultatu. Njegov regret je {q08["regret_log2"]:.4f},
  a srednji regret faze B bez njega bio bi
  {q08["phase_b_mean_regret_without_q08"]:.4f}.

## Interpretacija

Promjena N2 u N3 znacajno pomjera fizicku R3 reprezentaciju, ali u ovom panelu
ne mijenja najbolju od tri akcije. P99 je empirijska novelty/coverage granica
zamrznutog N2 prostora. Nije vjerovatnoca greske niti sigurnosna garancija.
Apstinencija faze A zato je proceduralno opravdana prema ugovoru pokrivenosti,
ali se naknadno pokazuje konzervativnom za action-selection zadatak.

Representation ablation razdvaja pet pojmova: SQL-strukturnu slicnost,
pojednostavljenu coordinator fizicku slicnost, punu viseslojnu fizicku
slicnost, action-response slicnost i konacnu odluku. R2 prenosi vise odluka u
fazi A, dok R3 eksplicitno prijavljuje fizicki distribution shift. Nakon
dodavanja ranijih N3 stanja i njihovih akcijskih ishoda R3 daje najbolji
faza-B rezultat. To je
safety/generalization kompromis, a ne automatska pobjeda jedne reprezentacije.

## Identitet memorije

Zavrsni DBA panel koristi `exact_query_memory` definisanu kao hash
normalizovanog SQL-a uz topologiju, broj regiona, profil podataka i runtime
profil. Kontrolisani topology panel ne koristi isti SQL tekst: N3 dodaje APAC
`UNION ALL` granu. Njegova stara oznaka `blind_exact_query` u ovom paketu je
kanonizovana kao `logical_query_memory`, zasnovana na unaprijed definisanom
topoloski nezavisnom hash-u scenarija.

## q08 granica metode

Tri od pet susjeda q08 preferiraju regionalni Top-K, ali dva druga susjeda
imaju mnogo vece remote-over-regional margine. Inverzno ponderisanje
udaljenoscu zato vrlo tijesno rangira remote akciju ispred regionalne. Stvarni
q08 odziv stabilno preferira regionalni Top-K kroz N2, N3 fazu A i N3 fazu B.
Problem je razlika action-response profila fizicki bliskih slucajeva, a ne
nedostajuca akcija ili nestabilnost samog q08.

## Reprodukcija

```bash
make representation-ablation-e1-e4-release
make consolidated-evaluation-release
make consolidated-evaluation-local-gate
make consolidated-evaluation-manuscript-gate
make -C ../master-regimes-thesis/manuscript check
```

## Otvorena ogranicenja

- Tri akcije pripadaju GAC Top-K domenu. `work_mem` je uglavnom negativna
  kontrola, pa panel prvenstveno razlikuje regionalni Top-K i remote akciju.
- Empirijska P99 granica nije kalibrisana prema action-selection gresci.
- Kontrolisani topology panel ima 15 logickih scenarija na jednoj
  infrastrukturi.
- `logical_query_memory` zavisi od eksplicitnog scenarijskog ugovora i nije
  automatsko dokazivanje semanticke ekvivalentnosti proizvoljnih SQL tekstova.
- FCM i K-means rezultati su razvojni komparatori, ne finalni holdout.
- Jedna operativna DBA intervencija otkrila bi samo vlastiti ishod. Partial-
  feedback replay nije dio ove evaluacije.
"""
    (out_dir / "README.md").write_text(text, encoding="utf-8")
    (out_dir / "REPRODUCE.md").write_text(
        "# Reprodukcija\n\n```bash\n"
        "make representation-ablation-e1-e4-release\n"
        "make consolidated-evaluation-release\n"
        "make consolidated-evaluation-local-gate\n"
        "make consolidated-evaluation-manuscript-gate\n"
        "make -C ../master-regimes-thesis/manuscript check\n"
        "```\n",
        encoding="utf-8",
    )
    write_json(
        out_dir / "manuscript_numbers.json",
        {
            "broad_executions": 2607,
            "broad_pairs": 418,
            "final_panel_state_count": 45,
            "final_panel_action_episode_count": 135,
            "final_panel_executions": 180,
            "r3_e1_coverage_count": int(e1.recommendation_count),
            "r3_e1_correct_count": int(e1.correct_decision_count),
            "r3_e1_top1": float(e1.top1_accuracy),
            "r3_e1_regret": float(e1.mean_regret_log2),
            "r3_e2_coverage_count": int(e2.recommendation_count),
            "r3_e2_correct_count": int(e2.correct_decision_count),
            "r3_e2_top1": float(e2.top1_accuracy),
            "r3_e2_regret": float(e2.mean_regret_log2),
            "r3_e3_coverage_count": int(e3.recommendation_count),
            "r3_e4_coverage_count": int(e4.recommendation_count),
            "r3_e4_correct_count": int(e4.correct_decision_count),
            "r3_e4_top1": float(e4.top1_accuracy),
            "r3_e4_regret": float(e4.mean_regret_log2),
            "topology_best_action_agreement": 15,
            "topology_logical_memory_phase_a_correct": 15,
            "topology_static_phase_b_top1": 0.6,
            "topology_static_phase_b_regret": 0.3677567977671438,
            "q08_regret": q08["regret_log2"],
            "q08_regret_without": q08["phase_b_mean_regret_without_q08"],
        },
    )


def analyze(contract_path: Path, out_dir: Path) -> dict[str, Any]:
    contract = read_yaml(contract_path)
    _validate_contract(contract)
    out_dir.mkdir(parents=True, exist_ok=True)
    provenance = provenance_table(contract)
    provenance.to_csv(out_dir / "dataset_provenance.csv", index=False)
    write_json(out_dir / "dataset_provenance.json", provenance.to_dict(orient="records"))
    identities, memory_contract, identity_checks = identity_audit(contract)
    identities.to_csv(out_dir / "sql_identity_audit.csv", index=False)
    memory_contract.to_csv(out_dir / "memory_key_contract.csv", index=False)
    write_json(out_dir / "identity_audit.json", {"checks": identity_checks})
    representation_release = resolve_input(contract["inputs"]["representation_release"])
    leakage = json.loads(
        (representation_release / "leakage_audit.json").read_text(encoding="utf-8")
    )
    if leakage["status"] != "PASS":
        raise ValueError("Task 1B leakage audit did not pass")
    representation_summary = pd.read_csv(
        representation_release / "representation_summary.csv", low_memory=False
    )
    shutil.copy2(
        representation_release / "episode_representation_results.csv",
        out_dir / "representation_episode_results.csv",
    )
    representation_summary.to_csv(out_dir / "representation_summary.csv", index=False)
    shutil.copy2(
        representation_release / "bootstrap_intervals.csv",
        out_dir / "representation_bootstrap_intervals.csv",
    )
    shutil.copy2(
        representation_release / "physical_action_response_summary.csv",
        out_dir / "physical_action_response_summary.csv",
    )
    ablation, _base, memory, dba, _topology_module, data = _load_ablation_inputs(contract)
    reference, final, topology_values, artifact = _frozen_r3(contract, ablation, memory, data)
    episode_rows, robustness, traces = sensitivity_analysis(
        contract, data, reference, final, topology_values, dba
    )
    episode_rows.to_csv(out_dir / "robustness_episode_results.csv", index=False)
    robustness.to_csv(out_dir / "robustness_summary.csv", index=False)
    traces.to_csv(out_dir / "robustness_neighbor_trace.csv", index=False)
    robustness[
        robustness["distance_metric"].eq("euclidean") & robustness["neighbors"].eq(5)
    ].to_csv(out_dir / "coverage_regret_curve.csv", index=False)
    distance = distance_error_analysis(episode_rows, contract)
    distance.to_csv(out_dir / "distance_error_analysis.csv", index=False)
    stability = action_stability(data, contract)
    stability.to_csv(out_dir / "best_action_stability.csv", index=False)
    bootstrap = cluster_bootstrap(episode_rows, contract)
    bootstrap.to_csv(out_dir / "robustness_bootstrap_intervals.csv", index=False)
    q08_neighbors, q08_rankings, q08 = q08_failure_analysis(contract)
    q08_neighbors.to_csv(out_dir / "q08_neighbors.csv", index=False)
    q08_rankings.to_csv(out_dir / "q08_action_rankings.csv", index=False)
    write_json(out_dir / "q08_failure_analysis.json", q08)
    topology_summary = json.loads(
        (resolve_input(contract["inputs"]["topology_report"]) / "analysis_summary.json").read_text(
            encoding="utf-8"
        )
    )
    claims = claim_evidence_matrix(contract, representation_summary, topology_summary, q08)
    claims.to_csv(out_dir / "claim_evidence_matrix.csv", index=False)
    _figure_representation(representation_summary, out_dir)
    _figure_topology(representation_release, out_dir)
    _figure_q08(q08_rankings, out_dir)
    _figure_coverage_regret(robustness, out_dir)
    write_report(
        out_dir,
        provenance,
        identities,
        representation_summary,
        robustness,
        q08,
        claims,
        distance,
    )
    final_config = robustness[
        robustness["distance_metric"].eq(contract["policy"]["frozen_distance_metric"])
        & robustness["neighbors"].eq(int(contract["policy"]["frozen_neighbors"]))
        & robustness["coverage_quantile"].eq(float(contract["policy"]["frozen_coverage_quantile"]))
    ]
    expected_phase_b = contract["expected"]["topology_phase_b_cross_query"]
    e4 = final_config[final_config["evaluation"].eq("E4")].iloc[0]
    consistency = {
        "no_sql_execution": True,
        "no_model_refit": True,
        "frozen_artifact_sha256": sha256_file(
            resolve_input(contract["inputs"]["frozen_full_model"])
        ),
        "frozen_artifact_internal_sha256": artifact["artifact_sha256"],
        "task_1b_leakage_status": leakage["status"],
        "provenance_checks": provenance.attrs["checks"],
        "identity_checks": identity_checks,
        "phase_b_cross_query_matches_archive": (
            int(e4["recommendation_count"]) == int(expected_phase_b["coverage_count"])
            and int(e4["correct_count"]) == int(expected_phase_b["correct_count"])
            and math.isclose(
                float(e4["mean_regret_log2"]),
                float(expected_phase_b["mean_regret_log2"]),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ),
        "q08_retained": q08["excluded_from_primary_result"] is False,
        "final_configuration_unchanged": len(final_config) == 3,
    }
    consistency["status"] = (
        "PASS"
        if all(
            value
            for key, value in consistency.items()
            if isinstance(value, bool) and key != "no_sql_execution"
        )
        else "FAIL"
    )
    write_json(out_dir / "consistency_audit.json", consistency)
    write_json(
        out_dir / "input_manifest.json",
        {
            "contract": str(contract_path),
            "contract_sha256": sha256_file(contract_path),
            "inputs": {
                key: {
                    "path": str(resolve_input(value)),
                    "sha256": sha256_file(resolve_input(value))
                    if resolve_input(value).is_file()
                    else None,
                }
                for key, value in contract["inputs"].items()
            },
        },
    )
    write_checksums(out_dir)
    if consistency["status"] != "PASS":
        raise SystemExit(2)
    return {
        "status": "PASS",
        "output_dir": str(out_dir),
        "provenance_sets": len(provenance),
        "identity_scenarios": len(identities),
        "robustness_configurations": len(robustness),
        "q08_regret_log2": q08["regret_log2"],
    }


def main() -> int:
    args = parse_args()
    result = analyze(args.contract.resolve(), args.out_dir.resolve())
    print(json.dumps(_json_safe(result), indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
