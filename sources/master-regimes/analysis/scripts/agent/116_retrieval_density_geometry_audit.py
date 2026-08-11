#!/usr/bin/env python3
"""Offline density and response-geometry audit for the frozen P64->6 memory.

The audit intentionally reuses only already measured complete three-action cases.
It does not execute SQL, refit the state representation on confirmatory data, or
change the thesis manuscript.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from scipy.stats import rankdata, spearmanr

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT = ROOT / "configs/validation/confirmatory_action_replication_v1.yml"
DEFAULT_CONFIRMATORY = ROOT / "releases/confirmatory-action-replication-v1"
DEFAULT_REFERENCE = ROOT / "analysis/reports/fuzzy-intervention-memory-v1"
DEFAULT_FINAL_DBA = ROOT / "analysis/reports/dba-local-memory-panel-v1"
DEFAULT_TOPOLOGY = ROOT / "analysis/reports/n3-topology-memory-v1"
DEFAULT_BROAD_RELEASE = ROOT / "releases/pressure-actionability-v1"
DEFAULT_OUT = ROOT / "llmcontext/extra-analysis"
DEFAULT_SEED = 2026081101

ACTIONS = (
    "increase_gac_work_mem",
    "regional_topk_candidates",
    "mitigate_remote_path_bundle",
)
MEMORY_SIZES = (5, 10, 15, 20, 30, 40, 60, 80, 100, 116, 130)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run three offline audits of retrieval density and response geometry."
    )
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--path-root", type=Path, default=ROOT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--reference-report", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--confirmatory-dir", type=Path, default=DEFAULT_CONFIRMATORY)
    parser.add_argument("--final-dba-dir", type=Path, default=DEFAULT_FINAL_DBA)
    parser.add_argument("--topology-dir", type=Path, default=DEFAULT_TOPOLOGY)
    parser.add_argument("--broad-release", type=Path, default=DEFAULT_BROAD_RELEASE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sampling-repetitions", type=int, default=2000)
    parser.add_argument("--permutations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return value


def load_module(path: Path, name: str) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_from(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def relative_manifest_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def markdown_table(frame: pd.DataFrame, digits: int = 3) -> str:
    if frame.empty:
        return "Nema redova."
    columns = [str(column) for column in frame.columns]
    lines = ["| " + " | ".join(columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for values in frame.itertuples(index=False, name=None):
        rendered: list[str] = []
        for value in values:
            if isinstance(value, (float, np.floating)):
                rendered.append("" if not np.isfinite(value) else f"{float(value):.{digits}f}")
            else:
                rendered.append(str(value))
        lines.append("| " + " | ".join(rendered) + " |")
    return "\n".join(lines)


def wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    if trials == 0:
        return (math.nan, math.nan)
    z = 1.959963984540054
    rate = successes / trials
    denominator = 1.0 + z * z / trials
    center = (rate + z * z / (2.0 * trials)) / denominator
    radius = (
        z * math.sqrt(rate * (1.0 - rate) / trials + z * z / (4.0 * trials * trials)) / denominator
    )
    return (max(0.0, center - radius), min(1.0, center + radius))


def response_matrix(outcomes: pd.DataFrame, episode_ids: list[str]) -> np.ndarray:
    duplicated = outcomes.duplicated(["episode_id", "mitigation_action"])
    if duplicated.any():
        raise ValueError("Duplicate action outcome for one episode")
    pivot = outcomes.pivot(
        index="episode_id", columns="mitigation_action", values="target_log2_gain"
    )
    missing_actions = set(ACTIONS) - set(pivot.columns.astype(str))
    if missing_actions:
        raise ValueError(f"Missing action outcomes: {sorted(missing_actions)}")
    pivot = pivot.reindex(index=episode_ids, columns=ACTIONS)
    if pivot.isna().any().any():
        missing = pivot[pivot.isna().any(axis=1)].index.tolist()
        raise ValueError(f"Incomplete three-action cases: {missing}")
    return pivot.to_numpy(dtype=float)


def audit_broad_corpus(release_dir: Path) -> tuple[pd.DataFrame, list[Path]]:
    release_manifest_path = release_dir / "release_manifest.json"
    consolidation_path = release_dir / "corpus/consolidation_manifest.json"
    pair_audit_path = release_dir / "action_audit/mitigation_pair_audit.csv"
    release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
    consolidation = json.loads(consolidation_path.read_text(encoding="utf-8"))
    pairs = pd.read_csv(pair_audit_path, low_memory=False)

    execution_count = int(release_manifest["evidence"]["execution_count"])
    pair_count = int(release_manifest["evidence"]["counterfactual_pair_count"])
    if execution_count != 2607 or pair_count != 418:
        raise AssertionError("Unexpected broad-corpus execution or pair count")
    if int(consolidation["resolved_primary_slot_count"]) != execution_count:
        raise AssertionError("Broad-corpus consolidation count disagrees with release")
    if len(pairs) != pair_count or pairs["pair_id"].nunique() != pair_count:
        raise AssertionError("Broad-corpus pair audit is incomplete or duplicated")
    action_support = pairs.groupby("stressed_condition_id")["mitigation_action"].nunique()
    complete_target_matrices = (
        pairs.groupby("stressed_condition_id")["mitigation_action"]
        .agg(lambda values: set(values.astype(str)))
        .map(lambda values: set(ACTIONS).issubset(values))
    )
    if int(action_support.max()) != 1 or int(complete_target_matrices.sum()) != 0:
        raise AssertionError("Broad corpus unexpectedly contains a complete action matrix")
    summary = pd.DataFrame(
        [
            {
                "physical_execution_count": execution_count,
                "controlled_pair_count": pair_count,
                "distinct_stressed_condition_count": int(pairs["stressed_condition_id"].nunique()),
                "distinct_action_count": int(pairs["mitigation_action"].nunique()),
                "maximum_actions_per_stressed_condition": int(action_support.max()),
                "complete_three_target_action_matrix_count": int(complete_target_matrices.sum()),
            }
        ]
    )
    return summary, [release_manifest_path, consolidation_path, pair_audit_path]


def load_cases(
    project_root: Path,
    contract_path: Path,
    reference_report: Path,
    confirmatory_dir: Path,
    final_dba_dir: Path,
    topology_dir: Path,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, float, dict[str, Any]]:
    project_root = project_root.resolve()
    reference_report = reference_report.resolve()
    contract = read_yaml(contract_path)
    state_contract_path = resolve_from(
        project_root, contract["model_freeze"]["state_contract"]
    )
    state_contract = read_yaml(state_contract_path)
    specifications = state_contract["state_representation"]["features"]
    feature_names = list(specifications)

    memory = load_module(
        project_root / "analysis/scripts/agent/101_fuzzy_intervention_memory.py",
        "density_geometry_memory_101",
    )
    dba = load_module(
        project_root / "analysis/scripts/agent/102_dba_local_memory_panel.py",
        "density_geometry_memory_102",
    )
    adapter = {
        "memory": {
            "reference_report": str(reference_report),
            "state_contract": str(state_contract_path),
        }
    }
    dba.ROOT = project_root
    reference_states, reference_outcomes = dba._reference_memory(adapter, feature_names)
    final_states = pd.read_csv(
        final_dba_dir / "observed_episode_states.csv", low_memory=False
    ).sort_values("episode_order")
    final_outcomes = pd.read_csv(final_dba_dir / "observed_action_outcomes.csv", low_memory=False)
    topology_states = pd.read_csv(
        topology_dir / "episode_states.csv", low_memory=False
    ).sort_values(["episode_order", "round_id"])
    topology_outcomes = pd.read_csv(topology_dir / "action_outcomes.csv", low_memory=False)
    confirmatory_states = pd.read_csv(
        confirmatory_dir / "scenario_states.csv", low_memory=False
    ).sort_values("scenario_order")
    confirmatory_outcomes = pd.read_csv(confirmatory_dir / "action_outcomes.csv", low_memory=False)

    if len(reference_states) != 26 or len(reference_outcomes) != 78:
        raise AssertionError("Expected 26 complete reference states and 78 outcomes")
    if len(final_states) != 45 or len(final_outcomes) != 135:
        raise AssertionError("Expected 45 final DBA states and 135 outcomes")
    if len(topology_states) != 45 or len(topology_outcomes) != 135:
        raise AssertionError("Expected 45 topology states and 135 outcomes")
    if len(confirmatory_states) != 15 or len(confirmatory_outcomes) != 45:
        raise AssertionError("Expected 15 confirmatory states and 45 outcomes")
    for label, outcomes in (
        ("final DBA", final_outcomes),
        ("topology", topology_outcomes),
        ("confirmatory", confirmatory_outcomes),
    ):
        if "result_equal" in outcomes and not outcomes["result_equal"].astype(bool).all():
            raise AssertionError(f"{label} outcomes contain an invalid result")
    final_run_ids = set(final_outcomes["baseline_query_run_id"].astype(str)) | set(
        final_outcomes["action_query_run_id"].astype(str)
    )
    topology_run_ids = set(topology_outcomes["baseline_query_run_id"].astype(str)) | set(
        topology_outcomes["action_query_run_id"].astype(str)
    )
    if final_run_ids & topology_run_ids:
        raise AssertionError("Final DBA and topology panels reuse physical run IDs")
    if len(final_run_ids) != 180 or len(topology_run_ids) != 180:
        raise AssertionError("Expected 180 distinct physical runs in each prior panel")

    processor = memory.StatePreprocessor(
        specifications=specifications,
        pca_components=int(contract["model_freeze"]["pca_components"]),
        minimum_active_features=int(
            state_contract["state_representation"]["minimum_active_features"]
        ),
    )
    reference_values = processor.fit(reference_states)
    final_values = processor.transform(final_states)
    topology_values = processor.transform(topology_states)
    confirmatory_values = processor.transform(confirmatory_states)
    threshold = dba._nearest_threshold(
        reference_values,
        float(contract["model_freeze"]["coverage_quantile"]),
        str(contract["model_freeze"]["distance_metric"]),
    )

    release_manifest = json.loads(
        (confirmatory_dir / "analysis_manifest.json").read_text(encoding="utf-8")
    )
    if len(processor.active_features or []) != 64:
        raise AssertionError("Frozen development fit no longer selects 64 features")
    if (
        reference_values.shape != (26, 6)
        or final_values.shape != (45, 6)
        or topology_values.shape != (45, 6)
        or confirmatory_values.shape != (15, 6)
    ):
        raise AssertionError("Unexpected P64->6 matrix dimensions")
    if not math.isclose(
        threshold,
        float(release_manifest["coverage_threshold"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise AssertionError("Recomputed P99 threshold differs from the release")

    reference_meta = reference_states[["episode_id", "query_id", "topology_id"]].copy()
    reference_meta["cohort"] = "reference"
    reference_meta["scenario_order"] = np.arange(1, len(reference_meta) + 1)
    reference_meta["logical_question_id"] = "event_raw_wide_sample"
    reference_meta["round_id"] = "development"

    final_meta = final_states[["episode_id", "query_id", "topology_id", "episode_order"]].rename(
        columns={"episode_order": "scenario_order"}
    )
    final_meta["cohort"] = "final_dba"
    final_meta["logical_question_id"] = final_meta["query_id"]
    final_meta["round_id"] = "temporal_panel"

    topology_meta = topology_states[
        ["episode_id", "query_id", "topology_id", "episode_order", "round_id"]
    ].rename(columns={"episode_order": "scenario_order"})
    topology_meta["cohort"] = "topology"
    topology_meta["logical_question_id"] = topology_meta["query_id"]

    confirmatory_meta = confirmatory_states[
        ["episode_id", "query_id", "topology_id", "scenario_order"]
    ].copy()
    confirmatory_meta["cohort"] = "confirmatory"
    confirmatory_meta["logical_question_id"] = confirmatory_meta["query_id"]
    confirmatory_meta["round_id"] = "confirmatory"

    cases = pd.concat(
        [reference_meta, final_meta, topology_meta, confirmatory_meta],
        ignore_index=True,
    )
    if cases["episode_id"].duplicated().any():
        raise AssertionError("Episode identities overlap across evidence panels")
    cases["case_index"] = np.arange(len(cases))
    states = np.vstack([reference_values, final_values, topology_values, confirmatory_values])
    all_outcomes = pd.concat(
        [
            reference_outcomes[["episode_id", "mitigation_action", "target_log2_gain"]],
            final_outcomes[["episode_id", "mitigation_action", "target_log2_gain"]],
            topology_outcomes[["episode_id", "mitigation_action", "target_log2_gain"]],
            confirmatory_outcomes[["episode_id", "mitigation_action", "target_log2_gain"]],
        ],
        ignore_index=True,
    )
    responses = response_matrix(all_outcomes, cases["episode_id"].astype(str).tolist())
    winners = np.argmax(responses, axis=1)
    cases["best_action"] = [ACTIONS[index] for index in winners]
    cases["winner_margin_log2"] = [float(np.sort(row)[-1] - np.sort(row)[-2]) for row in responses]
    for offset in range(states.shape[1]):
        cases[f"pca_{offset + 1}"] = states[:, offset]
    for offset, action in enumerate(ACTIONS):
        cases[f"gain__{action}"] = responses[:, offset]

    metadata = {
        "contract": contract,
        "state_contract_path": state_contract_path,
        "reference_report": reference_report,
        "active_features": processor.active_features,
        "coverage_threshold": threshold,
        "reference_state_count": len(reference_states),
        "final_dba_state_count": len(final_states),
        "topology_state_count": len(topology_states),
        "confirmatory_state_count": len(confirmatory_states),
        "final_dba_dir": final_dba_dir,
        "topology_dir": topology_dir,
        "final_dba_distinct_run_count": len(final_run_ids),
        "topology_distinct_run_count": len(topology_run_ids),
        "prior_panel_run_id_overlap_count": len(final_run_ids & topology_run_ids),
    }
    return cases, states, responses, threshold, metadata


def predict_from_indices(
    target_index: int,
    memory_indices: np.ndarray,
    states: np.ndarray,
    responses: np.ndarray,
    threshold: float,
    neighbors: int = 5,
) -> dict[str, Any]:
    distances = np.linalg.norm(states[memory_indices] - states[target_index], axis=1)
    order = np.argsort(distances)[: min(neighbors, len(memory_indices))]
    selected = memory_indices[order]
    selected_distances = distances[order]
    weights = 1.0 / (selected_distances + 1e-6)
    predictions = np.average(responses[selected], axis=0, weights=weights)
    candidate_index = int(np.argmax(predictions))
    actual_index = int(np.argmax(responses[target_index]))
    nearest = float(selected_distances[0])
    available = bool(len(memory_indices) >= 2 and nearest <= threshold)
    actual_best = float(responses[target_index, actual_index])
    return {
        "nearest_distance": nearest,
        "available": available,
        "candidate_action": ACTIONS[candidate_index],
        "actual_best_action": ACTIONS[actual_index],
        "candidate_correct": candidate_index == actual_index,
        "candidate_regret_log2": actual_best - float(responses[target_index, candidate_index]),
        "recommended_action": ACTIONS[candidate_index] if available else "",
        "top1_correct": bool(available and candidate_index == actual_index),
        "regret_log2": (
            actual_best - float(responses[target_index, candidate_index]) if available else math.nan
        ),
        "neighbor_indices": selected.tolist(),
    }


def summarize_sampling(rows: pd.DataFrame, repetitions: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries: list[dict[str, Any]] = []
    replicate_rows: list[dict[str, Any]] = []
    for memory_size, group in rows.groupby("memory_size", sort=True):
        replicate = []
        for sampling_repetition, sample in group.groupby("sampling_repetition", sort=True):
            issued = sample[sample["available"]]
            row = {
                "memory_size": int(memory_size),
                "sampling_repetition": int(sampling_repetition),
                "coverage": float(sample["available"].mean()),
                "top1_issued": (float(issued["top1_correct"].mean()) if len(issued) else math.nan),
                "regret_issued": (float(issued["regret_log2"].mean()) if len(issued) else math.nan),
                "candidate_top1": float(sample["candidate_correct"].mean()),
                "candidate_regret": float(sample["candidate_regret_log2"].mean()),
            }
            replicate.append(row)
            replicate_rows.append(row)
        replicate_frame = pd.DataFrame(replicate)
        issued = group[group["available"]]
        summary: dict[str, Any] = {
            "memory_size": int(memory_size),
            "sampling_repetitions": repetitions,
            "target_count_per_repetition": int(group["target_index"].nunique()),
            "pooled_coverage": float(group["available"].mean()),
            "pooled_top1_issued": (
                float(issued["top1_correct"].mean()) if len(issued) else math.nan
            ),
            "pooled_regret_issued_log2": (
                float(issued["regret_log2"].mean()) if len(issued) else math.nan
            ),
            "pooled_candidate_top1": float(group["candidate_correct"].mean()),
            "pooled_candidate_regret_log2": float(group["candidate_regret_log2"].mean()),
        }
        for metric in (
            "coverage",
            "top1_issued",
            "regret_issued",
            "candidate_top1",
            "candidate_regret",
        ):
            values = replicate_frame[metric].dropna()
            summary[f"{metric}_q025"] = float(values.quantile(0.025))
            summary[f"{metric}_median"] = float(values.median())
            summary[f"{metric}_q975"] = float(values.quantile(0.975))
        summaries.append(summary)
    return pd.DataFrame(summaries), pd.DataFrame(replicate_rows)


def learning_curves(
    cases: pd.DataFrame,
    states: np.ndarray,
    responses: np.ndarray,
    threshold: float,
    repetitions: int,
    seed: int,
    confirmatory_dir: Path,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    confirmatory_indices = cases.index[cases["cohort"].eq("confirmatory")].to_numpy()
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for memory_size in MEMORY_SIZES:
        for repetition in range(repetitions):
            for target_index in confirmatory_indices:
                candidates = np.delete(np.arange(len(cases)), target_index)
                memory_indices = rng.choice(candidates, size=memory_size, replace=False)
                prediction = predict_from_indices(
                    int(target_index), memory_indices, states, responses, threshold
                )
                rows.append(
                    {
                        "memory_size": memory_size,
                        "sampling_repetition": repetition,
                        "target_index": int(target_index),
                        "query_id": cases.at[target_index, "query_id"],
                        **{
                            key: value
                            for key, value in prediction.items()
                            if key != "neighbor_indices"
                        },
                    }
                )
    sampled = pd.DataFrame(rows)
    summary, replicate_summary = summarize_sampling(sampled, repetitions)

    augmentation_rows: list[dict[str, Any]] = []
    augmentation_sizes = (0, 1, 2, 3, 5, 8, 10, 14)
    augmentation_rng = np.random.default_rng(seed + 100)
    reference_indices = cases.index[cases["cohort"].eq("reference")].to_numpy()
    for new_cohort_count in augmentation_sizes:
        for repetition in range(repetitions):
            for target_index in confirmatory_indices:
                available_confirmatory = np.asarray(
                    [index for index in confirmatory_indices if index != target_index],
                    dtype=int,
                )
                added = augmentation_rng.choice(
                    available_confirmatory,
                    size=new_cohort_count,
                    replace=False,
                )
                memory_indices = np.asarray([*reference_indices, *added], dtype=int)
                prediction = predict_from_indices(
                    int(target_index), memory_indices, states, responses, threshold
                )
                augmentation_rows.append(
                    {
                        "memory_size": len(memory_indices),
                        "reference_case_count": len(reference_indices),
                        "new_cohort_case_count": new_cohort_count,
                        "sampling_repetition": repetition,
                        "target_index": int(target_index),
                        "query_id": cases.at[target_index, "query_id"],
                        **{
                            key: value
                            for key, value in prediction.items()
                            if key != "neighbor_indices"
                        },
                    }
                )
    augmentation = pd.DataFrame(augmentation_rows)
    augmentation_summary, augmentation_replicates = summarize_sampling(augmentation, repetitions)
    augmentation_counts = augmentation[
        ["memory_size", "reference_case_count", "new_cohort_case_count"]
    ].drop_duplicates("memory_size")
    augmentation_summary = augmentation_summary.merge(
        augmentation_counts, on="memory_size", how="left", validate="one_to_one"
    )
    augmentation_replicates = augmentation_replicates.merge(
        augmentation_counts, on="memory_size", how="left", validate="many_to_one"
    )

    final_indices = cases.index[cases["cohort"].eq("final_dba")].to_numpy()
    topology_indices = cases.index[cases["cohort"].eq("topology")].to_numpy()
    panel_rows: list[dict[str, Any]] = []
    for scope in (
        "reference_only",
        "reference_plus_final_dba",
        "reference_plus_topology",
        "all_prior_panels",
        "all_prior_plus_other_confirmatory",
    ):
        decisions: list[dict[str, Any]] = []
        for target_index in confirmatory_indices:
            if scope == "reference_only":
                memory_indices = reference_indices
            elif scope == "reference_plus_final_dba":
                memory_indices = np.asarray([*reference_indices, *final_indices], dtype=int)
            elif scope == "reference_plus_topology":
                memory_indices = np.asarray([*reference_indices, *topology_indices], dtype=int)
            elif scope == "all_prior_panels":
                memory_indices = np.asarray(
                    [*reference_indices, *final_indices, *topology_indices],
                    dtype=int,
                )
            else:
                other_confirmatory = [
                    index for index in confirmatory_indices if index != target_index
                ]
                memory_indices = np.asarray(
                    [
                        *reference_indices,
                        *final_indices,
                        *topology_indices,
                        *other_confirmatory,
                    ],
                    dtype=int,
                )
            prediction = predict_from_indices(
                int(target_index), memory_indices, states, responses, threshold
            )
            decisions.append(prediction)
        decision_frame = pd.DataFrame(decisions)
        issued = decision_frame[decision_frame["available"]]
        panel_rows.append(
            {
                "memory_scope": scope,
                "memory_size": len(memory_indices),
                "recommendation_count": len(issued),
                "coverage": float(decision_frame["available"].mean()),
                "top1_issued": (float(issued["top1_correct"].mean()) if len(issued) else math.nan),
                "candidate_correct_count": int(decision_frame["candidate_correct"].sum()),
                "candidate_top1": float(decision_frame["candidate_correct"].mean()),
                "candidate_regret_log2": float(decision_frame["candidate_regret_log2"].mean()),
                "median_nearest_distance": float(decision_frame["nearest_distance"].median()),
            }
        )
    panel_comparison = pd.DataFrame(panel_rows)

    prior: list[int] = []
    temporal_rows: list[dict[str, Any]] = []
    for target_index in confirmatory_indices:
        memory_indices = np.asarray([*reference_indices, *prior], dtype=int)
        prediction = predict_from_indices(
            int(target_index), memory_indices, states, responses, threshold
        )
        temporal_rows.append(
            {
                "scenario_order": int(cases.at[target_index, "scenario_order"]),
                "query_id": cases.at[target_index, "query_id"],
                "memory_size": len(memory_indices),
                **{key: value for key, value in prediction.items() if key != "neighbor_indices"},
            }
        )
        prior.append(int(target_index))
    temporal = pd.DataFrame(temporal_rows).sort_values("scenario_order")
    temporal["cumulative_coverage"] = temporal["available"].expanding().mean()
    temporal["cumulative_top1_issued"] = [
        float(
            temporal.iloc[: index + 1].loc[lambda frame: frame["available"], "top1_correct"].mean()
        )
        if temporal.iloc[: index + 1]["available"].any()
        else math.nan
        for index in range(len(temporal))
    ]
    temporal["cumulative_regret_issued_log2"] = [
        float(
            temporal.iloc[: index + 1].loc[lambda frame: frame["available"], "regret_log2"].mean()
        )
        if temporal.iloc[: index + 1]["available"].any()
        else math.nan
        for index in range(len(temporal))
    ]
    temporal["cumulative_candidate_top1"] = temporal["candidate_correct"].expanding().mean()

    released = pd.read_csv(confirmatory_dir / "per_scenario_predictions.csv")
    released = released[released["mode"].astype(str).eq("prequential_full_feedback")].sort_values(
        "scenario_order"
    )
    if (
        temporal["recommended_action"].tolist()
        != released["recommended_action"].fillna("").tolist()
    ):
        raise AssertionError("Temporal replay recommendations differ from the release")
    if temporal["candidate_action"].tolist() != released["candidate_action"].tolist():
        raise AssertionError("Temporal replay candidates differ from the release")
    if not np.allclose(temporal["nearest_distance"], released["nearest_distance"], atol=1e-12):
        raise AssertionError("Temporal replay distances differ from the release")
    if int(temporal["available"].sum()) != 14:
        raise AssertionError("Expected 14 issued prequential recommendations")
    if int(temporal["top1_correct"].sum()) != 8:
        raise AssertionError("Expected eight correct prequential recommendations")
    combined_replicates = pd.concat(
        [
            replicate_summary.assign(curve="uniform_case_density"),
            augmentation_replicates.assign(curve="reference_plus_new_cohort"),
        ],
        ignore_index=True,
    )
    return (
        sampled,
        summary,
        augmentation_summary,
        panel_comparison,
        combined_replicates,
        temporal,
    )


def pairwise_cases(
    cases: pd.DataFrame,
    states: np.ndarray,
    responses: np.ndarray,
) -> pd.DataFrame:
    centered = responses - responses.mean(axis=1, keepdims=True)
    ranks = np.vstack([rankdata(row, method="average") for row in responses])
    rows: list[dict[str, Any]] = []
    for left in range(len(cases)):
        for right in range(left + 1, len(cases)):
            left_cohort = str(cases.at[left, "cohort"])
            right_cohort = str(cases.at[right, "cohort"])
            pair_type = "-".join(sorted((left_cohort, right_cohort)))
            same_query_id = bool(cases.at[left, "query_id"] == cases.at[right, "query_id"])
            same_logical_question = bool(
                cases.at[left, "logical_question_id"] == cases.at[right, "logical_question_id"]
            )
            rows.append(
                {
                    "left_index": left,
                    "right_index": right,
                    "left_query_id": cases.at[left, "query_id"],
                    "right_query_id": cases.at[right, "query_id"],
                    "pair_type": pair_type,
                    "same_query_id": same_query_id,
                    "same_logical_question": same_logical_question,
                    "state_distance": float(np.linalg.norm(states[left] - states[right])),
                    "response_distance_raw": float(
                        np.linalg.norm(responses[left] - responses[right])
                    ),
                    "response_distance_centered": float(
                        np.linalg.norm(centered[left] - centered[right])
                    ),
                    "response_rank_distance": float(np.linalg.norm(ranks[left] - ranks[right])),
                    "same_winner": bool(
                        cases.at[left, "best_action"] == cases.at[right, "best_action"]
                    ),
                    "left_winner": cases.at[left, "best_action"],
                    "right_winner": cases.at[right, "best_action"],
                }
            )
    return pd.DataFrame(rows)


def neighbor_consistency(
    pairs: pd.DataFrame,
    threshold: float,
) -> pd.DataFrame:
    quantiles = (0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.50, 0.75, 1.0)
    radii = [
        (f"pooled_q{int(quantile * 100):02d}", float(pairs["state_distance"].quantile(quantile)))
        for quantile in quantiles
    ]
    radii.append(("frozen_P99", threshold))
    rows: list[dict[str, Any]] = []
    confirmatory_prior_types = {
        "confirmatory-final_dba",
        "confirmatory-reference",
        "confirmatory-topology",
    }
    subsets = {
        "all": pairs,
        "different_query_id": pairs[~pairs["same_query_id"]],
        "same_query_id": pairs[pairs["same_query_id"]],
        "confirmatory_vs_all_prior": pairs[pairs["pair_type"].isin(confirmatory_prior_types)],
        "confirmatory_vs_reference": pairs[pairs["pair_type"].eq("confirmatory-reference")],
        "confirmatory_vs_final_dba": pairs[pairs["pair_type"].eq("confirmatory-final_dba")],
        "confirmatory_vs_topology": pairs[pairs["pair_type"].eq("confirmatory-topology")],
        "confirmatory_vs_confirmatory": pairs[pairs["pair_type"].eq("confirmatory-confirmatory")],
    }
    for subset_name, subset in subsets.items():
        baseline = float(subset["same_winner"].mean())
        for label, radius in radii:
            selected = subset[subset["state_distance"] <= radius]
            successes = int(selected["same_winner"].sum())
            low, high = wilson_interval(successes, len(selected))
            rows.append(
                {
                    "pair_subset": subset_name,
                    "radius_label": label,
                    "radius": radius,
                    "pair_count": len(selected),
                    "same_winner_count": successes,
                    "same_winner_probability": (
                        successes / len(selected) if len(selected) else math.nan
                    ),
                    "wilson_95_low": low,
                    "wilson_95_high": high,
                    "unconditional_same_winner_probability": baseline,
                    "lift_over_baseline": (
                        successes / len(selected) - baseline if len(selected) else math.nan
                    ),
                }
            )
    return pd.DataFrame(rows)


def nearest_neighbor_rows(
    cases: pd.DataFrame,
    states: np.ndarray,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    scopes = {
        "all_other_cases": lambda target: np.asarray(
            [index for index in range(len(cases)) if index != target], dtype=int
        ),
        "reference_only_for_confirmatory": lambda target: cases.index[
            cases["cohort"].eq("reference")
        ].to_numpy(),
        "final_dba_only_for_confirmatory": lambda target: cases.index[
            cases["cohort"].eq("final_dba")
        ].to_numpy(),
        "topology_only_for_confirmatory": lambda target: cases.index[
            cases["cohort"].eq("topology")
        ].to_numpy(),
        "all_prior_for_confirmatory": lambda target: cases.index[
            ~cases["cohort"].eq("confirmatory")
        ].to_numpy(),
        "confirmatory_only_for_confirmatory": lambda target: np.asarray(
            [index for index in cases.index[cases["cohort"].eq("confirmatory")] if index != target],
            dtype=int,
        ),
    }
    for scope, candidate_function in scopes.items():
        target_indices = (
            range(len(cases))
            if scope == "all_other_cases"
            else cases.index[cases["cohort"].eq("confirmatory")]
        )
        for target in target_indices:
            candidates = candidate_function(int(target))
            distances = np.linalg.norm(states[candidates] - states[target], axis=1)
            neighbor = int(candidates[int(np.argmin(distances))])
            rows.append(
                {
                    "scope": scope,
                    "target_index": int(target),
                    "target_query_id": cases.at[target, "query_id"],
                    "target_cohort": cases.at[target, "cohort"],
                    "target_winner": cases.at[target, "best_action"],
                    "neighbor_index": neighbor,
                    "neighbor_query_id": cases.at[neighbor, "query_id"],
                    "neighbor_cohort": cases.at[neighbor, "cohort"],
                    "neighbor_winner": cases.at[neighbor, "best_action"],
                    "distance": float(distances.min()),
                    "same_winner": bool(
                        cases.at[target, "best_action"] == cases.at[neighbor, "best_action"]
                    ),
                }
            )
    return pd.DataFrame(rows)


def permutation_correlations(
    states: np.ndarray,
    responses: np.ndarray,
    cases: pd.DataFrame,
    permutations: int,
    seed: int,
) -> dict[str, Any]:
    left, right = np.triu_indices(len(cases), k=1)
    state_distance = np.linalg.norm(states[left] - states[right], axis=1)
    state_ranks = rankdata(state_distance, method="average")
    centered = responses - responses.mean(axis=1, keepdims=True)
    response_ranks = np.vstack([rankdata(row, method="average") for row in responses])
    metrics = {
        "raw": responses,
        "centered": centered,
        "action_rank": response_ranks,
    }

    def correlation(values: np.ndarray) -> float:
        distance = np.linalg.norm(values[left] - values[right], axis=1)
        ranked = rankdata(distance, method="average")
        return float(np.corrcoef(state_ranks, ranked)[0, 1])

    observed = {name: correlation(values) for name, values in metrics.items()}
    exceedances = {name: 0 for name in metrics}
    rng = np.random.default_rng(seed)
    cohort_indices = [group.index.to_numpy() for _, group in cases.groupby("cohort", sort=True)]
    for _ in range(permutations):
        permutation = np.arange(len(cases))
        for indices in cohort_indices:
            permutation[indices] = rng.permutation(indices)
        for name, values in metrics.items():
            statistic = correlation(values[permutation])
            if abs(statistic) >= abs(observed[name]):
                exceedances[name] += 1
    return {
        name: {
            "spearman_rho": observed[name],
            "stratified_permutation_count": permutations,
            "stratified_permutation_two_sided_p": (exceedances[name] + 1) / (permutations + 1),
        }
        for name in metrics
    }


def response_geometry(
    cases: pd.DataFrame,
    pairs: pd.DataFrame,
    states: np.ndarray,
    responses: np.ndarray,
    permutations: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    metrics = (
        "response_distance_raw",
        "response_distance_centered",
        "response_rank_distance",
    )
    correlations: list[dict[str, Any]] = []
    confirmatory_prior_types = {
        "confirmatory-final_dba",
        "confirmatory-reference",
        "confirmatory-topology",
    }
    subsets = {
        "all": pairs,
        "different_query_id": pairs[~pairs["same_query_id"]],
        "same_query_id": pairs[pairs["same_query_id"]],
        "confirmatory_vs_all_prior": pairs[pairs["pair_type"].isin(confirmatory_prior_types)],
        "confirmatory_vs_reference": pairs[pairs["pair_type"].eq("confirmatory-reference")],
        "confirmatory_vs_final_dba": pairs[pairs["pair_type"].eq("confirmatory-final_dba")],
        "confirmatory_vs_topology": pairs[pairs["pair_type"].eq("confirmatory-topology")],
        "confirmatory_vs_confirmatory": pairs[pairs["pair_type"].eq("confirmatory-confirmatory")],
    }
    for subset_name, subset in subsets.items():
        for metric in metrics:
            result = spearmanr(subset["state_distance"], subset[metric], nan_policy="raise")
            correlations.append(
                {
                    "pair_subset": subset_name,
                    "response_metric": metric,
                    "pair_count": len(subset),
                    "spearman_rho": float(result.statistic),
                    "naive_pairwise_p": float(result.pvalue),
                }
            )
    correlation_frame = pd.DataFrame(correlations)

    bin_frames: list[pd.DataFrame] = []
    for subset_name in ("all", "different_query_id", "confirmatory_vs_all_prior"):
        subset = subsets[subset_name].copy()
        subset["state_distance_bin"] = pd.qcut(
            subset["state_distance"], 5, labels=False, duplicates="drop"
        )
        binned = (
            subset.groupby("state_distance_bin", observed=True)
            .agg(
                pair_count=("state_distance", "size"),
                state_distance_min=("state_distance", "min"),
                state_distance_median=("state_distance", "median"),
                state_distance_max=("state_distance", "max"),
                response_distance_raw_median=("response_distance_raw", "median"),
                response_distance_centered_median=(
                    "response_distance_centered",
                    "median",
                ),
                response_rank_distance_median=(
                    "response_rank_distance",
                    "median",
                ),
                same_winner_probability=("same_winner", "mean"),
            )
            .reset_index()
        )
        binned["state_distance_bin"] = binned["state_distance_bin"].astype(int) + 1
        binned.insert(0, "pair_subset", subset_name)
        bin_frames.append(binned)
    bins = pd.concat(bin_frames, ignore_index=True)
    permutation = permutation_correlations(states, responses, cases, permutations, seed)
    return correlation_frame, bins, permutation


def write_figures(
    out_dir: Path,
    learning: pd.DataFrame,
    consistency: pd.DataFrame,
    pairs: pd.DataFrame,
) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")

    figure, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    axes[0].plot(
        learning["memory_size"], learning["pooled_coverage"], marker="o", label="Pokrivenost"
    )
    axes[0].plot(
        learning["memory_size"],
        learning["pooled_top1_issued"],
        marker="s",
        label="Top-1 među izdatim",
    )
    axes[0].plot(
        learning["memory_size"],
        learning["pooled_candidate_top1"],
        marker="^",
        label="Top-1 bez apstinencije",
    )
    axes[0].set(xlabel="Broj slučajeva u memoriji", ylabel="Udio", ylim=(0, 1.05))
    axes[0].legend(fontsize=8)
    axes[1].plot(
        learning["memory_size"],
        learning["pooled_regret_issued_log2"],
        marker="s",
        label="Regret izdatih",
    )
    axes[1].plot(
        learning["memory_size"],
        learning["pooled_candidate_regret_log2"],
        marker="^",
        label="Regret bez apstinencije",
    )
    axes[1].set(xlabel="Broj slučajeva u memoriji", ylabel="Srednji regret (log2)")
    axes[1].legend(fontsize=8)
    figure.tight_layout()
    figure.savefig(out_dir / "figure_learning_coverage_curve.png", dpi=180)
    plt.close(figure)

    view = consistency[
        consistency["pair_subset"].eq("all")
        & consistency["radius_label"].str.startswith("pooled_q")
    ].sort_values("radius")
    figure, axis = plt.subplots(figsize=(6.5, 4.2))
    axis.plot(view["radius"], view["same_winner_probability"], marker="o", label="Opaženo")
    axis.axhline(
        float(view["unconditional_same_winner_probability"].iloc[0]),
        color="black",
        linestyle="--",
        label="Marginalna osnova",
    )
    axis.set(
        xlabel="Kumulativni radijus u P64→6",
        ylabel="P(isti pobjednik | udaljenost ≤ radijus)",
        ylim=(0, 1.05),
    )
    axis.legend(fontsize=8)
    figure.tight_layout()
    figure.savefig(out_dir / "figure_neighbor_consistency.png", dpi=180)
    plt.close(figure)

    figure, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for same_winner, label, color in (
        (True, "Isti pobjednik", "#2a7f62"),
        (False, "Različit pobjednik", "#b44d48"),
    ):
        selected = pairs[pairs["same_winner"].eq(same_winner)]
        axes[0].scatter(
            selected["state_distance"],
            selected["response_distance_raw"],
            color=color,
            s=14,
            alpha=0.55,
            label=label,
        )
        axes[1].scatter(
            selected["state_distance"],
            selected["response_distance_centered"],
            color=color,
            s=14,
            alpha=0.55,
            label=label,
        )
    axes[0].set(xlabel="Udaljenost stanja", ylabel="Sirova udaljenost odziva")
    axes[0].legend(fontsize=8)
    axes[1].set(xlabel="Udaljenost stanja", ylabel="Centrirana udaljenost odziva")
    figure.tight_layout()
    figure.savefig(out_dir / "figure_state_response_geometry.png", dpi=180)
    plt.close(figure)


def render_learning_report(
    summary: pd.DataFrame,
    augmentation: pd.DataFrame,
    panel_comparison: pd.DataFrame,
    temporal: pd.DataFrame,
    threshold: float,
) -> str:
    view = summary[
        [
            "memory_size",
            "pooled_coverage",
            "pooled_top1_issued",
            "pooled_regret_issued_log2",
            "pooled_candidate_top1",
            "pooled_candidate_regret_log2",
        ]
    ].rename(
        columns={
            "memory_size": "n",
            "pooled_coverage": "Pokrivenost",
            "pooled_top1_issued": "Top-1 izdatih",
            "pooled_regret_issued_log2": "Regret izdatih",
            "pooled_candidate_top1": "Top-1 bez apstinencije",
            "pooled_candidate_regret_log2": "Regret bez apstinencije",
        }
    )
    first = summary.iloc[0]
    last = summary.iloc[-1]
    coverage_change = float(last["pooled_coverage"] - first["pooled_coverage"])
    candidate_change = float(last["pooled_candidate_top1"] - first["pooled_candidate_top1"])
    temporal_issued = temporal[temporal["available"]]
    temporal_low, temporal_high = wilson_interval(
        int(temporal_issued["top1_correct"].sum()), len(temporal_issued)
    )
    augmentation_view = augmentation[
        [
            "reference_case_count",
            "new_cohort_case_count",
            "memory_size",
            "pooled_coverage",
            "pooled_top1_issued",
            "pooled_candidate_top1",
            "pooled_candidate_regret_log2",
        ]
    ].rename(
        columns={
            "reference_case_count": "Stari slučajevi",
            "new_cohort_case_count": "Novi slučajevi",
            "memory_size": "Ukupno",
            "pooled_coverage": "Pokrivenost",
            "pooled_top1_issued": "Top-1 izdatih",
            "pooled_candidate_top1": "Top-1 bez apstinencije",
            "pooled_candidate_regret_log2": "Regret bez apstinencije",
        }
    )
    augmentation_start = augmentation.iloc[0]
    augmentation_end = augmentation.iloc[-1]
    panel_view = panel_comparison.copy()
    panel_view["memory_scope"] = panel_view["memory_scope"].map(
        {
            "reference_only": "26 razvojnih",
            "reference_plus_final_dba": "+ 45 završnih DBA",
            "reference_plus_topology": "+ 45 topology",
            "all_prior_panels": "svih 116 ranijih",
            "all_prior_plus_other_confirmatory": "116 + 14 drugih potvrdnih",
        }
    )
    panel_view = panel_view[
        [
            "memory_scope",
            "memory_size",
            "recommendation_count",
            "coverage",
            "candidate_correct_count",
            "candidate_top1",
            "candidate_regret_log2",
            "median_nearest_distance",
        ]
    ].rename(
        columns={
            "memory_scope": "Sastav memorije",
            "memory_size": "n",
            "recommendation_count": "Preporuke",
            "coverage": "Pokrivenost",
            "candidate_correct_count": "Tačno",
            "candidate_top1": "Top-1 kandidata",
            "candidate_regret_log2": "Regret kandidata",
            "median_nearest_distance": "Medijalni najbliži d",
        }
    )
    all_prior = panel_comparison[panel_comparison["memory_scope"].eq("all_prior_panels")].iloc[0]
    all_available = panel_comparison[
        panel_comparison["memory_scope"].eq("all_prior_plus_other_confirmatory")
    ].iloc[0]
    lines = [
        "# Analiza 1: veličina memorije, pokrivenost i kvalitet odluke",
        "",
        "## Pitanje",
        "",
        "Da li veći broj kompletnih slučajeva poboljšava samo pokrivenost zamrznute "
        "P64→6 memorije ili i sposobnost razlikovanja najbolje intervencije?",
        "",
        "## Podaci i postupak",
        "",
        "Analiza koristi svih 131 postojećih stanja sa kompletnom matricom tri "
        "akcije: 26 razvojnih, 45 završnih DBA, 45 iz kontrolisanog topology panela "
        "i 15 potvrdnih. P64→6 transformacija ostaje fitovana samo na 26 razvojnih "
        "stanja, iz kojih je izvedena i P99 granica. Za svaki od 15 potvrdnih "
        "ciljeva nasumično se uzima n slučajeva među preostalih 130, uz 2.000 "
        "ponavljanja po veličini memorije. Ovaj test može uključiti ponovljene "
        "q01–q15 slučajeve i kasnije potvrdne ishode. Zato nije nova holdout "
        "procjena, nego dijagnostika gustoće i sastava memorije.",
        "",
        "Objavljeni strogi i vremenski replay počinju sa 26 razvojnih stanja zato "
        "što ih zamrznuti `model_freeze.reference_report` ugovor eksplicitno imenuje "
        "kao početnu memoriju. Završni DBA i topology paneli zadržani su kao odvojeni "
        "evaluacijski dokazi. Njihovo uključivanje u ovom auditu jeste post-hoc "
        "osjetljivost i ne zamjenjuje unaprijed definisani rezultat.",
        "",
        f"Zamrznuta granica pokrivenosti iznosi {threshold:.6f}.",
        "",
        "## Retrospektivna kriva gustoće",
        "",
        markdown_table(view),
        "",
        "Top-1 među izdatim preporukama zavisi od apstinencije. Kolona bez "
        "apstinencije zato prikazuje kvalitet kandidata i kada je najbliži slučaj "
        "izvan P99 granice.",
        "",
        "## Sastav već postojeće historije",
        "",
        "Broj slučajeva nije dovoljan opis memorije. Sljedeći post-hoc replay "
        "uspoređuje različite već izmjerene panele bez refitovanja reprezentacije:",
        "",
        markdown_table(panel_view),
        "",
        "## Dopunjavanje zamrznute memorije novim kohortom",
        "",
        "Ova odvojena osjetljivost zadržava 26 razvojnih stanja i dodaje od 0 do 14 "
        "drugih potvrdnih slučajeva. Ona namjerno pokazuje šta bi se dogodilo kada "
        "bi memorija već sadržavala slučajeve iz iste nove populacije. Nikada ne "
        "koristi vlastiti ishod cilja:",
        "",
        markdown_table(augmentation_view),
        "",
        "## Strogo vremenski replay",
        "",
        f"U stvarnom redoslijedu memorija počinje sa 26 razvojnih stanja. Nakon svake "
        f"odluke otkrivaju se tri već izmjerena ishoda tog slučaja. Izdato je "
        f"{len(temporal_issued)}/15 preporuka, od kojih je "
        f"{int(temporal_issued['top1_correct'].sum())}/{len(temporal_issued)} bilo "
        f"tačno. Srednji regret izdatih preporuka bio je "
        f"{temporal_issued['regret_log2'].mean():.3f} log2. Ovo tačno reprodukuje "
        "objavljeni prequential rezultat. Deskriptivni 95% Wilsonov interval za "
        f"8/14 iznosi [{temporal_low:.3f}, {temporal_high:.3f}]. On pokazuje veliku "
        "nesigurnost omjera, ali nije interval univerzalne produkcijske tačnosti jer "
        "15 SQL oblika nisu slučajan uzorak takve populacije.",
        "",
        "## Zaključak",
        "",
        f"Uniformna kriva od n={int(first['memory_size'])} do "
        f"n={int(last['memory_size'])} povećava pokrivenost za "
        f"{coverage_change:+.3f}, a Top-1 kandidata za {candidate_change:+.3f}. "
        f"Kada se svih 26 starih slučajeva dopuni sa 14 slučajeva iz novog kohorta, "
        f"pokrivenost raste sa {augmentation_start['pooled_coverage']:.3f} na "
        f"{augmentation_end['pooled_coverage']:.3f}, a Top-1 kandidata sa "
        f"{augmentation_start['pooled_candidate_top1']:.3f} na "
        f"{augmentation_end['pooled_candidate_top1']:.3f}. Pokrivenost se zasićuje "
        "ranije od diskriminacije akcija. Top-1 pritom nije monotona funkcija broja "
        "slučajeva: sa tri do pet novih slučajeva privremeno opada jer se mijenja "
        "sastav pet najbližih susjeda. Veća lokalna memorija iz istog kohorta na "
        "kraju pomaže, ali ni taj povoljniji replay ne prelazi 10/15 tačnih odluka.",
        "",
        f"Još važnije, svih 116 slučajeva dostupnih prije potvrdnog panela daju "
        f"pokrivenost {all_prior['coverage']:.3f}, ali samo "
        f"{int(all_prior['candidate_correct_count'])}/15 tačnih kandidata i regret "
        f"{all_prior['candidate_regret_log2']:.3f}. Kada se dodaju i svih 14 drugih "
        f"potvrdnih slučajeva, rezultat je "
        f"{int(all_available['candidate_correct_count'])}/15, a ne monotono "
        "poboljšanje. Oskudnost podataka je dio problema pokrivenosti, ali sastav "
        "memorije i odnos fizičke sličnosti prema odzivu ostaju zaseban problem.",
        "",
        "Kriva se ne smije tumačiti kao procjena buduće produkcijske tačnosti, jer "
        "je post-hoc i sadrži ponovljena stanja istih q01–q15 upita.",
    ]
    return "\n".join(lines) + "\n"


def render_neighbor_report(
    cases: pd.DataFrame,
    consistency: pd.DataFrame,
    nearest: pd.DataFrame,
) -> str:
    selected = consistency[
        consistency["pair_subset"].eq("all")
        & consistency["radius_label"].isin(
            ["pooled_q01", "pooled_q05", "pooled_q10", "pooled_q20", "frozen_P99"]
        )
    ][
        [
            "radius_label",
            "radius",
            "pair_count",
            "same_winner_probability",
            "wilson_95_low",
            "wilson_95_high",
            "unconditional_same_winner_probability",
            "lift_over_baseline",
        ]
    ].rename(
        columns={
            "radius_label": "Radijus",
            "radius": "Vrijednost",
            "pair_count": "Parovi",
            "same_winner_probability": "P(isti pobjednik)",
            "wilson_95_low": "95% donja",
            "wilson_95_high": "95% gornja",
            "unconditional_same_winner_probability": "Osnova",
            "lift_over_baseline": "Razlika",
        }
    )
    nearest_summary = (
        nearest.groupby("scope")
        .agg(
            targets=("target_index", "size"),
            same_winner_probability=("same_winner", "mean"),
            median_distance=("distance", "median"),
        )
        .reset_index()
    )
    nearest_summary["scope"] = nearest_summary["scope"].map(
        {
            "all_other_cases": "svi drugi slučajevi",
            "confirmatory_only_for_confirmatory": "potvrdni među potvrdnim",
            "reference_only_for_confirmatory": "razvojni za potvrdni cilj",
            "final_dba_only_for_confirmatory": "završni DBA za potvrdni cilj",
            "topology_only_for_confirmatory": "topology za potvrdni cilj",
            "all_prior_for_confirmatory": "svi raniji za potvrdni cilj",
        }
    )
    nearest_summary = nearest_summary.rename(
        columns={
            "scope": "Skup susjeda",
            "targets": "Ciljevi",
            "same_winner_probability": "Udio istog pobjednika",
            "median_distance": "Medijalna udaljenost",
        }
    )
    threshold_by_pair = consistency[
        consistency["radius_label"].eq("frozen_P99")
        & consistency["pair_subset"].isin(
            [
                "different_query_id",
                "same_query_id",
                "confirmatory_vs_all_prior",
                "confirmatory_vs_reference",
                "confirmatory_vs_final_dba",
                "confirmatory_vs_topology",
                "confirmatory_vs_confirmatory",
            ]
        )
    ][
        [
            "pair_subset",
            "pair_count",
            "same_winner_probability",
            "unconditional_same_winner_probability",
            "lift_over_baseline",
        ]
    ].rename(
        columns={
            "pair_subset": "Skup parova",
            "pair_count": "Parovi unutar P99",
            "same_winner_probability": "P(isti pobjednik)",
            "unconditional_same_winner_probability": "Osnova",
            "lift_over_baseline": "Razlika",
        }
    )
    confirm_nearest = nearest_summary[
        nearest_summary["Skup susjeda"].eq("potvrdni među potvrdnim")
    ].iloc[0]
    reference_nearest = nearest_summary[
        nearest_summary["Skup susjeda"].eq("razvojni za potvrdni cilj")
    ].iloc[0]
    prior_nearest = nearest_summary[
        nearest_summary["Skup susjeda"].eq("svi raniji za potvrdni cilj")
    ].iloc[0]
    prior_threshold = consistency[
        consistency["pair_subset"].eq("confirmatory_vs_all_prior")
        & consistency["radius_label"].eq("frozen_P99")
    ].iloc[0]
    winner_counts = (
        cases.groupby(["cohort", "best_action"])
        .size()
        .reset_index(name="count")
        .replace(
            {
                "reference": "razvojni",
                "final_dba": "završni DBA",
                "topology": "topology",
                "confirmatory": "potvrdni",
            }
        )
        .rename(columns={"cohort": "Skup", "best_action": "Pobjednik", "count": "Broj"})
    )
    lines = [
        "# Analiza 2: konzistentnost pobjednika među fizičkim susjedima",
        "",
        "## Pitanje",
        "",
        "Kada su dva početna stanja bliska u zamrznutom P64→6 prostoru, koliko "
        "često imaju istu najbolju intervenciju?",
        "",
        "## Obuhvat",
        "",
        f"Analiza obuhvata svih {math.comb(len(cases), 2)} neuređenih parova među "
        f"{len(cases)} kompletnim stanjima. Ona pripadaju samo "
        f"{cases['logical_question_id'].nunique()} deklarisanoj logičkoj grupi. "
        "Završni DBA i topology panel ponavljaju q01–q15, pa su rezultati posebno "
        "prikazani za iste i različite identitete upita. Time se sprečava da "
        "ponavljanja istog SQL-a lažno izgledaju kao cross-query generalizacija.",
        "",
        "Raspodjela stvarnih pobjednika:",
        "",
        markdown_table(winner_counts),
        "",
        "Nijedan slučaj nema `increase_gac_work_mem` kao pobjednika. Zato ova analiza "
        "provjerava razdvajanje regionalne Top-K i udaljene intervencije, a ne punu "
        "troklasnu odluku.",
        "",
        "## Kumulativna konzistentnost",
        "",
        markdown_table(selected),
        "",
        "Osnova je bezuslovni udio jednakih pobjednika u prikazanom skupu parova. "
        "Pozitivna razlika iznad te osnove znači da uži radijus nosi dodatni signal. "
        "Wilsonov interval opisuje nesigurnost udjela, "
        "ali parovi nisu potpuno nezavisni jer isti slučaj učestvuje u više parova.",
        "",
        "Na zamrznutoj P99 granici rezultat po vrsti para je:",
        "",
        markdown_table(threshold_by_pair),
        "",
        "## Najbliži susjed",
        "",
        markdown_table(nearest_summary),
        "",
        "## Zaključak",
        "",
        f"Najbliži potvrdni susjed iz istog novog kohorta dijeli pobjednika u "
        f"{confirm_nearest['Udio istog pobjednika']:.3f} slučajeva. Najbliži "
        f"razvojni susjed to čini u samo "
        f"{reference_nearest['Udio istog pobjednika']:.3f} slučajeva, uz medijalnu "
        f"udaljenost {reference_nearest['Medijalna udaljenost']:.3f}. Kada se uključe "
        f"svi raniji paneli, najbliži susjed dijeli pobjednika u "
        f"{prior_nearest['Udio istog pobjednika']:.3f} slučajeva, a "
        f"{int(prior_threshold['pair_count'])} par između potvrdnog i svih "
        "ranijih panela ulazi u P99. "
        "Topology panel zato rješava fizičku nepokrivenost, ali sama dostupnost "
        "bliskih stanja još ne garantuje isti pobjednik. Pooled skup pokazuje lokalno "
        "slaganje, uglavnom zbog ponovljenih i kontrolisano srodnih stanja. U ciljnom "
        "cross-query presjeku P99 donosi samo 0,009 iznad bezuslovne osnove. "
        "Upotrebljivost susjeda zato zavisi od porijekla i sastava memorije.",
    ]
    return "\n".join(lines) + "\n"


def render_geometry_report(
    correlations: pd.DataFrame,
    bins: pd.DataFrame,
    permutation: dict[str, Any],
    nearest: pd.DataFrame,
) -> str:
    view = correlations[
        correlations["pair_subset"].isin(
            [
                "all",
                "different_query_id",
                "same_query_id",
                "confirmatory_vs_all_prior",
                "confirmatory_vs_topology",
                "confirmatory_vs_confirmatory",
            ]
        )
    ].copy()
    view = view.rename(
        columns={
            "pair_subset": "Parovi",
            "response_metric": "Metrika odziva",
            "pair_count": "n",
            "spearman_rho": "Spearman rho",
            "naive_pairwise_p": "Naivni p",
        }
    )
    permutation_frame = pd.DataFrame(
        [
            {
                "Metrika": name,
                "Spearman rho": values["spearman_rho"],
                "Stratifikovani permutacijski p": (
                    f"{values['stratified_permutation_two_sided_p']:.4f}"
                ),
                "Permutacije": values["stratified_permutation_count"],
            }
            for name, values in permutation.items()
        ]
    )
    nearest_summary = (
        nearest[~nearest["scope"].eq("all_other_cases")]
        .groupby("scope")
        .agg(
            targets=("target_index", "size"),
            agreement=("same_winner", "mean"),
            median_distance=("distance", "median"),
        )
        .reset_index()
    )
    nearest_summary["scope"] = nearest_summary["scope"].map(
        {
            "reference_only_for_confirmatory": "razvojni",
            "final_dba_only_for_confirmatory": "završni DBA",
            "topology_only_for_confirmatory": "topology",
            "all_prior_for_confirmatory": "svi raniji",
            "confirmatory_only_for_confirmatory": "drugi potvrdni",
        }
    )
    overall_centered = correlations[
        correlations["pair_subset"].eq("all")
        & correlations["response_metric"].eq("response_distance_centered")
    ].iloc[0]
    overall_rank = correlations[
        correlations["pair_subset"].eq("all")
        & correlations["response_metric"].eq("response_rank_distance")
    ].iloc[0]
    overall_pair_count = int(overall_centered["pair_count"])
    cross_rank = correlations[
        correlations["pair_subset"].eq("confirmatory_vs_all_prior")
        & correlations["response_metric"].eq("response_rank_distance")
    ].iloc[0]
    all_bins = bins[bins["pair_subset"].eq("all")]
    first_bin = all_bins.iloc[0]
    last_bin = all_bins.iloc[-1]
    lines = [
        "# Analiza 3: geometrija fizičkog stanja i geometrija odziva",
        "",
        "## Pitanje",
        "",
        "Da li veća udaljenost početnih fizičkih stanja u P64→6 prati veću "
        "udaljenost vektora stvarno izmjerenih dobitaka tri intervencije?",
        "",
        "## Metrike",
        "",
        "`raw` je euklidska udaljenost tri log2 dobitka. `centered` prije poređenja "
        "oduzima prosječni dobitak svakog slučaja i zato naglašava relativni profil "
        "akcija. `action_rank` poredi samo njihov poredak. Posljednje dvije metrike "
        "su važnije za pitanje izbora intervencije od zajedničkog nivoa ubrzanja.",
        "",
        "## Korelacije",
        "",
        markdown_table(view),
        "",
        f"Naivni p tretira svih {overall_pair_count} parova kao nezavisne i prikazan "
        "je samo radi audita. "
        "Primarni test je 10.000 permutacija cijelih response vektora, odvojeno "
        "unutar svakog od četiri eksperimentalna skupa:",
        "",
        markdown_table(permutation_frame),
        "",
        "## Kvintili udaljenosti stanja",
        "",
        markdown_table(bins),
        "",
        "## Slaganje najbližeg susjeda",
        "",
        markdown_table(nearest_summary),
        "",
        "## Zaključak",
        "",
        f"Na nivou svih stanja nije opažena mjerljiva monotona veza: za centrirani "
        f"profil odziva rho iznosi {overall_centered['spearman_rho']:.3f}, a za sam "
        f"poredak akcija {overall_rank['spearman_rho']:.3f}. Stratifikovani "
        f"permutacijski p za centrirani profil iznosi "
        f"{permutation['centered']['stratified_permutation_two_sided_p']:.4f}. Udio "
        "parova sa istim pobjednikom pada "
        f"sa {first_bin['same_winner_probability']:.3f} u najbližem na "
        f"{last_bin['same_winner_probability']:.3f} u najudaljenijem kvintilu. Taj "
        "pooled obrazac uključuje ponovljene identitete upita. Za sve parove između "
        "potvrdnog i ranijih skupova korelacija udaljenosti poretka iznosi samo "
        f"{cross_rank['spearman_rho']:.3f}. P64→6 zato nije potpuno nevezan za "
        "ponovljena lokalna stanja, ali njegova geometrija nije usmjerena na odziv "
        "intervencije dovoljno da podrži robustan cross-query izbor akcije. Ovaj "
        "audit ne pretvara 131 stanje u dokaz univerzalne neprenosivosti.",
    ]
    return "\n".join(lines) + "\n"


def render_summary(
    cases: pd.DataFrame,
    broad_audit: pd.DataFrame,
    learning: pd.DataFrame,
    augmentation: pd.DataFrame,
    panel_comparison: pd.DataFrame,
    consistency: pd.DataFrame,
    correlations: pd.DataFrame,
    permutation: dict[str, Any],
) -> str:
    first = learning.iloc[0]
    last = learning.iloc[-1]
    close = consistency[
        consistency["pair_subset"].eq("all") & consistency["radius_label"].eq("pooled_q05")
    ].iloc[0]
    cross_coverage = consistency[
        consistency["pair_subset"].eq("confirmatory_vs_all_prior")
        & consistency["radius_label"].eq("frozen_P99")
    ].iloc[0]
    augmentation_last = augmentation.iloc[-1]
    cross_rank = correlations[
        correlations["pair_subset"].eq("confirmatory_vs_all_prior")
        & correlations["response_metric"].eq("response_rank_distance")
    ].iloc[0]
    all_prior = panel_comparison[panel_comparison["memory_scope"].eq("all_prior_panels")].iloc[0]
    all_available = panel_comparison[
        panel_comparison["memory_scope"].eq("all_prior_plus_other_confirmatory")
    ].iloc[0]
    winner_counts = cases["best_action"].value_counts().to_dict()
    broad = broad_audit.iloc[0]
    broad_execution_label = f"{int(broad['physical_execution_count']):,}".replace(",", ".")
    temporal_low, temporal_high = wilson_interval(8, 14)
    lines = [
        "# Sažetak tri offline analize retrieval memorije",
        "",
        "## Autoritativna jedinica analize",
        "",
        "Top-1 nije testiran na samo 15 fizičkih izvršenja. Potvrdni panel sadrži "
        "300 fizičkih izvršenja, ali ona formiraju 15 SQL odluka: za svaki SQL oblik "
        "pet puta su izmjereni baseline i tri uslova. Ponavljanja stabilizuju stvarni "
        "poredak akcija, ali ne stvaraju nove nezavisne SQL odluke.",
        "",
        f"Široki korpus sa {broad_execution_label} izvršenja ima "
        f"{int(broad['controlled_pair_count'])} before/after parova, ali svaki od "
        f"{int(broad['distinct_stressed_condition_count'])} početnih uslova ima samo "
        "jednu izmjerenu akciju. Zato iz njega nije moguće izračunati stvarnog "
        "pobjednika među tri akcije bez izmišljanja nedostajućih kontrafaktualnih "
        "ishoda.",
        "",
        "Za ova tri audita koristi se najveći postojeći zajednički skup sa potpunom "
        "matricom akcija u istom zamrznutom prostoru: 26 razvojnih, 45 završnih DBA, "
        "45 kontrolisanih topology i 15 potvrdnih stanja. To je 131 stanje sa 393 "
        "izmjerena ishoda akcija, ali samo 31 deklarisana logička grupa. Ponovljena "
        "stanja q01–q15 zato nisu predstavljena kao novi nezavisni SQL problemi.",
        "",
        "Izvorni replay počinje sa 26 stanja jer zamrznuti ugovor upravo taj razvojni "
        "izvještaj definiše kao početnu memoriju. Preostala dva ranija panela bila su "
        "odvojeni evaluacijski dokazi. Njihovo sadašnje uključivanje provjerava "
        "osjetljivost na sastav memorije, ali ne mijenja retroaktivno finalni ugovor.",
        "",
        "## Glavni brojevi",
        "",
        f"- Stvarni pobjednici: `{winner_counts}`.",
        f"- Retrospektivna pokrivenost pri n={int(first['memory_size'])}: "
        f"{first['pooled_coverage']:.3f}; pri n={int(last['memory_size'])}: "
        f"{last['pooled_coverage']:.3f}.",
        f"- Top-1 kandidata bez apstinencije pri n={int(first['memory_size'])}: "
        f"{first['pooled_candidate_top1']:.3f}; pri n={int(last['memory_size'])}: "
        f"{last['pooled_candidate_top1']:.3f}.",
        f"- Među najbližih 5% svih parova isti pobjednik se javlja u "
        f"{close['same_winner_probability']:.3f} slučajeva, naspram marginalne "
        f"osnove {close['unconditional_same_winner_probability']:.3f}.",
        f"- Spearmanova veza state-distance i centriranog response-distance iznosi "
        f"{permutation['centered']['spearman_rho']:.3f}, uz stratifikovani "
        f"permutacijski p={permutation['centered']['stratified_permutation_two_sided_p']:.4f}.",
        "",
        "## Odgovor na dilemu",
        "",
        f"Nazivnik od 15 jeste malen za preciznu opću procjenu tačnosti. Rezultat "
        f"8/14 ima deskriptivni 95% Wilsonov interval [{temporal_low:.3f}, "
        f"{temporal_high:.3f}], a jedna odluka mijenja Top-1 za približno 0,071. "
        "Panel je zato dovoljan da pokaže da se raniji pozitivan rezultat nije "
        "ponovio na ovih 15 novih oblika, ali nije dovoljan da procijeni "
        "univerzalnu tačnost.",
        "",
        f"Slučajevi iz iste nove populacije mogu pomoći: sa 26 razvojnih i 14 drugih "
        f"potvrdnih slučajeva retrospektivni Top-1 kandidata dostiže "
        f"{augmentation_last['pooled_candidate_top1']:.3f}, a regret pada na "
        f"{augmentation_last['pooled_candidate_regret_log2']:.3f}. To odgovara "
        f"{int(round(15 * augmentation_last['pooled_candidate_top1']))}/15 tačnih "
        "odluka, ali koristi naknadno poznate ishode. Važniji test sastava memorije "
        f"pokazuje da svih {int(all_prior['memory_size'])} ranijih potpunih stanja "
        f"pokriva {int(all_prior['recommendation_count'])}/15 ciljeva, ali daje samo "
        f"{int(all_prior['candidate_correct_count'])}/15 tačnih kandidata. Kada se "
        f"dodaju i ishodi ostalih 14 potvrdnih slučajeva, rezultat je "
        f"{int(all_available['candidate_correct_count'])}/15. Veća memorija je zato "
        "riješila fizičku nepokrivenost, ali nije monotono riješila izbor akcije.",
        "",
        f"Unutar P99 nalazi se {int(cross_coverage['pair_count'])} par između "
        "potvrdnog i svih ranijih panela, dok Spearmanova veza udaljenosti poretka "
        f"akcija za te parove iznosi {cross_rank['spearman_rho']:.3f}. Premala "
        "memorija jeste dio problema pokrivenosti, ali nije jedini problem. P64→6 "
        "fizička geometrija samo slabo prati geometriju odziva na intervenciju.",
        "",
        "## Granice",
        "",
        "Ovo nisu novi infrastrukturni eksperimenti niti nova finalna evaluacija. "
        "Retrospektivna kriva koristi kasnije poznate slučajeve samo da razdvoji "
        "problem pokrivenosti od problema akcijskog odziva. Uz to, razvojnih 26 "
        "stanja predstavljaju parametrizacije jedne logičke Top-K namjere, a završni "
        "DBA i topology paneli ponavljaju q01–q15 u kontrolisanim kontekstima. Nijedan "
        "od 131 slučaja nema `work_mem` kao strogog pobjednika. Zaključci su zato "
        "ograničeni na ovaj konkretni P64→6 ugovor, dvije opažene pobjedničke akcije "
        "i postojeću infrastrukturu.",
        "",
        "## Datoteke",
        "",
        "- `01-learning-coverage-curve.md`",
        "- `02-neighbor-consistency.md`",
        "- `03-state-response-geometry.md`",
        "- `prior_panel_memory_comparison.csv`",
        "- `broad_corpus_action_matrix_audit.csv`",
        "- `case_catalog.csv`, `pairwise_distances.csv` i ostali pomoćni CSV/JSON izlazi",
        "- reprodukcija: `env UV_CACHE_DIR=tmp/.uv-cache uv run python "
        "analysis/scripts/agent/116_retrieval_density_geometry_audit.py`",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    if args.sampling_repetitions < 1 or args.permutations < 1:
        raise ValueError("Sampling repetitions and permutations must be positive")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "learning_curve_samples.csv").unlink(missing_ok=True)

    cases, states, responses, threshold, metadata = load_cases(
        args.project_root,
        args.contract,
        args.reference_report,
        args.confirmatory_dir,
        args.final_dba_dir,
        args.topology_dir,
    )
    broad_audit, broad_input_paths = audit_broad_corpus(args.broad_release)
    (
        _sampled,
        learning,
        augmentation,
        panel_comparison,
        learning_replicates,
        temporal,
    ) = learning_curves(
        cases,
        states,
        responses,
        threshold,
        args.sampling_repetitions,
        args.seed,
        args.confirmatory_dir,
    )
    pairs = pairwise_cases(cases, states, responses)
    consistency = neighbor_consistency(pairs, threshold)
    nearest = nearest_neighbor_rows(cases, states)
    correlations, bins, permutation = response_geometry(
        cases,
        pairs,
        states,
        responses,
        args.permutations,
        args.seed + 1,
    )

    cases.to_csv(args.out_dir / "case_catalog.csv", index=False)
    broad_audit.to_csv(args.out_dir / "broad_corpus_action_matrix_audit.csv", index=False)
    learning.to_csv(args.out_dir / "learning_curve_summary.csv", index=False)
    augmentation.to_csv(args.out_dir / "cohort_augmentation_curve.csv", index=False)
    panel_comparison.to_csv(args.out_dir / "prior_panel_memory_comparison.csv", index=False)
    learning_replicates.to_csv(args.out_dir / "learning_curve_replicates.csv", index=False)
    temporal.to_csv(args.out_dir / "temporal_memory_curve.csv", index=False)
    pairs.to_csv(args.out_dir / "pairwise_distances.csv", index=False)
    consistency.to_csv(args.out_dir / "neighbor_consistency_curve.csv", index=False)
    nearest.to_csv(args.out_dir / "nearest_neighbor_agreement.csv", index=False)
    correlations.to_csv(args.out_dir / "state_response_correlations.csv", index=False)
    bins.to_csv(args.out_dir / "state_distance_bins.csv", index=False)
    write_json(args.out_dir / "state_response_permutation.json", permutation)

    (args.out_dir / "01-learning-coverage-curve.md").write_text(
        render_learning_report(learning, augmentation, panel_comparison, temporal, threshold),
        encoding="utf-8",
    )
    (args.out_dir / "02-neighbor-consistency.md").write_text(
        render_neighbor_report(cases, consistency, nearest), encoding="utf-8"
    )
    (args.out_dir / "03-state-response-geometry.md").write_text(
        render_geometry_report(correlations, bins, permutation, nearest),
        encoding="utf-8",
    )
    (args.out_dir / "README.md").write_text(
        render_summary(
            cases,
            broad_audit,
            learning,
            augmentation,
            panel_comparison,
            consistency,
            correlations,
            permutation,
        ),
        encoding="utf-8",
    )
    write_figures(args.out_dir, learning, consistency, pairs)

    input_paths = [
        args.contract,
        metadata["state_contract_path"],
        metadata["reference_report"] / "episodes.csv",
        args.final_dba_dir / "observed_episode_states.csv",
        args.final_dba_dir / "observed_action_outcomes.csv",
        args.topology_dir / "episode_states.csv",
        args.topology_dir / "action_outcomes.csv",
        args.confirmatory_dir / "scenario_states.csv",
        args.confirmatory_dir / "action_outcomes.csv",
        args.confirmatory_dir / "per_scenario_predictions.csv",
        args.confirmatory_dir / "analysis_manifest.json",
        *broad_input_paths,
    ]
    write_json(
        args.out_dir / "analysis_manifest.json",
        {
            "status": "PASS",
            "analysis_contract": "retrieval-density-geometry-audit-v1",
            "sql_executions_performed": 0,
            "state_representation_refit_on_confirmatory_data": False,
            "reference_state_count": metadata["reference_state_count"],
            "final_dba_state_count": metadata["final_dba_state_count"],
            "topology_state_count": metadata["topology_state_count"],
            "confirmatory_state_count": metadata["confirmatory_state_count"],
            "complete_case_count": len(cases),
            "complete_action_outcome_count": int(len(cases) * len(ACTIONS)),
            "broad_corpus_action_matrix_audit": broad_audit.iloc[0].to_dict(),
            "pair_count": len(pairs),
            "active_feature_count": len(metadata["active_features"]),
            "pca_component_count": states.shape[1],
            "coverage_threshold": threshold,
            "sampling_repetitions": args.sampling_repetitions,
            "permutations": args.permutations,
            "seed": args.seed,
            "temporal_release_reproduction": {
                "recommendation_count": int(temporal["available"].sum()),
                "correct_count": int(temporal["top1_correct"].sum()),
                "status": "PASS",
            },
            "prior_panel_run_identity_audit": {
                "final_dba_distinct_run_count": metadata["final_dba_distinct_run_count"],
                "topology_distinct_run_count": metadata["topology_distinct_run_count"],
                "overlap_count": metadata["prior_panel_run_id_overlap_count"],
                "status": "PASS",
            },
            "limitations": [
                "retrospective density curve includes later confirmatory outcomes",
                "26 reference states are parameterizations of one logical Top-K question",
                "no complete case has increase_gac_work_mem as the strict winner",
                "131 complete states represent only 31 logical query groups",
                "repeated q01-q15 states are controlled separately from cross-query pairs",
                "the expanded prior-panel replay is a post-hoc sensitivity analysis",
                (
                    "earlier panels use less replication per action than the "
                    "five-repeat confirmatory panel"
                ),
            ],
            "inputs": [
                {
                    "path": relative_manifest_path(path, args.path_root),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in input_paths
            ],
        },
    )

    checksum_path = args.out_dir / "checksums.sha256"
    outputs = sorted(
        path for path in args.out_dir.iterdir() if path.is_file() and path != checksum_path
    )
    checksum_path.write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in outputs),
        encoding="utf-8",
    )
    print(f"wrote retrieval density and geometry audit to {args.out_dir}")


if __name__ == "__main__":
    main()
