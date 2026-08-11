#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy.stats import rankdata, spearmanr

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT = ROOT / "configs/validation/representation_ablation_e1_e4_v1.yml"
DEFAULT_OUT_DIR = ROOT / "analysis/reports/representation-ablation-e1-e4-v1"
BASE_SCRIPT = ROOT / "analysis/scripts/agent/103_representation_value_ablation.py"
MEMORY_SCRIPT = ROOT / "analysis/scripts/agent/101_fuzzy_intervention_memory.py"
DBA_SCRIPT = ROOT / "analysis/scripts/agent/102_dba_local_memory_panel.py"
TOPOLOGY_SCRIPT = ROOT / "analysis/scripts/agent/104_n3_topology_memory_experiment.py"
REPRESENTATIONS = (
    "R1_sql_structural",
    "R2_coordinator_physical",
    "R3_full_multilayer",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run leakage-safe representation ablation over E1-E4 without SQL execution."
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


def _json_default(value: Any) -> Any:
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
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
        json.dumps(
            _json_safe(value),
            indent=2,
            sort_keys=True,
            default=_json_default,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(out_dir: Path) -> None:
    checksum_path = out_dir / "checksums.sha256"
    rows = [
        f"{sha256_file(path)}  {path.relative_to(out_dir)}"
        for path in sorted(out_dir.rglob("*"))
        if path.is_file() and path != checksum_path
    ]
    checksum_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def validate_contract(contract: dict[str, Any], base_contract: dict[str, Any]) -> None:
    policy = contract["policy"]
    if int(policy["neighbors"]) != 5 or policy["distance_metric"] != "euclidean":
        raise ValueError("All representations must use frozen Euclidean k=5")
    if not policy["exclude_same_query_id"] or not policy["exclude_same_logical_identity"]:
        raise ValueError("Both same-query exclusions are mandatory")
    if tuple(policy["actions"]) != tuple(base_contract["decision_policy"]["actions"]):
        raise ValueError("Action catalog differs from the final DBA panel")
    if set(contract["evaluations"]) != {"E1", "E2", "E3", "E4"}:
        raise ValueError("Exactly E1-E4 must be configured")


@dataclass
class InputData:
    reference_states: pd.DataFrame
    reference_outcomes: pd.DataFrame
    final_states: pd.DataFrame
    final_outcomes: pd.DataFrame
    topology_states: pd.DataFrame
    topology_outcomes: pd.DataFrame
    development_metadata: pd.DataFrame
    final_metadata: pd.DataFrame
    topology_metadata: pd.DataFrame
    state_contract: dict[str, Any]
    final_contract: dict[str, Any]


@dataclass
class RepresentationData:
    name: str
    reference_values: np.ndarray
    final_values: np.ndarray
    topology_values: np.ndarray
    threshold: float
    fit_manifest: dict[str, Any]
    fit_audit: pd.DataFrame


class FrozenFullTransformer:
    def __init__(
        self,
        specifications: dict[str, Any],
        artifact: dict[str, Any],
        memory_module: Any,
    ) -> None:
        self.specifications = specifications
        self.artifact = artifact
        self.memory_module = memory_module
        self.active_features = [str(value) for value in artifact["active_features"]]

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        transformed = self.memory_module.transform_values(frame, self.specifications, "before__")
        values = transformed[self.active_features].to_numpy(dtype=float)
        medians = np.asarray(self.artifact["imputer_statistics"], dtype=float)
        values = np.where(np.isnan(values), medians[None, :], values)
        scaled = (values - np.asarray(self.artifact["scaler_mean"], dtype=float)) / np.asarray(
            self.artifact["scaler_scale"], dtype=float
        )
        weighted = scaled * np.asarray(self.artifact["family_weights"], dtype=float)
        centered = weighted - np.asarray(self.artifact["pca_mean"], dtype=float)
        return centered @ np.asarray(self.artifact["pca_components"], dtype=float).T


def _logical_identity(frame: pd.DataFrame) -> pd.Series:
    if "logical_query_hash" in frame.columns:
        logical = frame["logical_query_hash"].fillna("").astype(str)
        normalized = (
            frame.get("normalized_sql_hash", pd.Series("", index=frame.index, dtype=str))
            .fillna("")
            .astype(str)
        )
        return logical.where(logical.ne(""), normalized)
    return frame["normalized_sql_hash"].fillna("").astype(str)


def normalize_states(frame: pd.DataFrame, source_scope: str) -> pd.DataFrame:
    result = frame.copy().reset_index(drop=True)
    result["logical_identity"] = _logical_identity(result)
    result["source_scope"] = source_scope
    if "query_occurrence" not in result:
        result["query_occurrence"] = 1
    if "planned_query_occurrences" not in result:
        result["planned_query_occurrences"] = 1
    if "applicable_actions_json" not in result:
        result["applicable_actions_json"] = json.dumps([], separators=(",", ":"))
    if "applicability_source" not in result:
        result["applicability_source"] = "frozen_three_action_contract"
    return result


def _topology_metadata(
    states: pd.DataFrame,
    work_dir: Path,
    memory_module: Any,
    topology_module: Any,
    base_module: Any,
) -> pd.DataFrame:
    block_by_round = {
        "n2_control": "n2_control",
        "phase_a": "phase_a_baseline",
        "phase_b": "phase_b_baseline",
    }
    indexed = pd.concat(
        [
            topology_module.load_executions(work_dir, block_id, memory_module)
            for block_id in block_by_round.values()
        ],
        ignore_index=True,
    )
    by_run = indexed.set_index(indexed["query_run_id"].astype(str), drop=False)
    rows: list[dict[str, Any]] = []
    for state in states.to_dict(orient="records"):
        run_id = str(state["baseline_query_run_id"])
        if run_id not in by_run.index:
            raise ValueError(f"Missing topology baseline execution {run_id}")
        member = by_run.loc[run_id]
        if isinstance(member, pd.DataFrame):
            if len(member) != 1:
                raise ValueError(f"Ambiguous topology baseline execution {run_id}")
            member = member.iloc[0]
        source_path = Path(str(member["source_sql_file"]))
        if not source_path.exists():
            raise ValueError(f"Missing rendered SQL: {source_path}")
        row = {
            "episode_id": str(state["episode_id"]),
            "query_id": str(state["query_id"]),
            "source_sql_file": str(source_path),
            "normalized_sql_hash": str(state["normalized_sql_hash"]),
        }
        for target, source in base_module.PLAN_FEATURE_SOURCES.items():
            row[target] = pd.to_numeric(pd.Series([member.get(source)]), errors="coerce").iloc[0]
        rows.append(row)
    return pd.DataFrame(rows)


def load_inputs(
    contract: dict[str, Any],
    base_contract: dict[str, Any],
    base_module: Any,
    memory_module: Any,
    dba_module: Any,
    topology_module: Any,
) -> InputData:
    inputs = contract["inputs"]
    state_contract = read_yaml(resolve_input(inputs["development_state_contract"]))
    final_contract = read_yaml(resolve_input(inputs["final_panel_contract"]))
    feature_names = list(state_contract["state_representation"]["features"])
    reference_states, reference_outcomes = dba_module._reference_memory(
        final_contract, feature_names
    )
    development_rows, source_indexes = base_module._development_rows(base_contract, memory_module)
    development_metadata = base_module._metadata_from_development(development_rows, source_indexes)
    development_metadata = reference_states[["episode_id"]].merge(
        development_metadata, on="episode_id", how="left", validate="one_to_one"
    )
    if "normalized_sql_hash" not in reference_states:
        reference_states = reference_states.merge(
            development_metadata[["episode_id", "normalized_sql_hash"]],
            on="episode_id",
            how="left",
            validate="one_to_one",
        )
    reference_states = normalize_states(reference_states, "development_reference")
    final_report = resolve_input(inputs["final_panel_report"])
    final_states = normalize_states(
        pd.read_csv(final_report / "observed_episode_states.csv", low_memory=False).sort_values(
            "episode_order"
        ),
        "final_panel",
    )
    final_outcomes = pd.read_csv(final_report / "observed_action_outcomes.csv", low_memory=False)
    topology_report = resolve_input(inputs["topology_report"])
    topology_states = normalize_states(
        pd.read_csv(topology_report / "episode_states.csv", low_memory=False),
        "topology_experiment",
    )
    topology_outcomes = pd.read_csv(topology_report / "action_outcomes.csv", low_memory=False)
    final_metadata = base_module._metadata_from_final(
        final_states,
        resolve_input(inputs["final_panel_index"]),
        memory_module,
    )
    topology_metadata = _topology_metadata(
        topology_states,
        resolve_input(inputs["topology_work_dir"]),
        memory_module,
        topology_module,
        base_module,
    )
    expected = contract["expected"]
    if len(reference_states) != int(expected["development_states"]):
        raise ValueError("Unexpected development state count")
    if len(final_states) != int(expected["final_episodes"]):
        raise ValueError("Unexpected final panel size")
    if len(final_outcomes) != int(expected["final_action_outcomes"]):
        raise ValueError("Unexpected final action outcome count")
    observed_rounds = topology_states.groupby("round_id").size().to_dict()
    if observed_rounds != {key: int(value) for key, value in expected["topology_rounds"].items()}:
        raise ValueError(f"Unexpected topology rounds: {observed_rounds}")
    if len(topology_outcomes) != int(expected["topology_action_outcomes"]):
        raise ValueError("Unexpected topology action outcome count")
    if not final_outcomes["result_equal"].astype(bool).all():
        raise ValueError("Final panel contains non-equivalent action results")
    if not topology_outcomes["result_equal"].astype(bool).all():
        raise ValueError("Topology panel contains non-equivalent action results")
    return InputData(
        reference_states=reference_states,
        reference_outcomes=reference_outcomes,
        final_states=final_states,
        final_outcomes=final_outcomes,
        topology_states=topology_states,
        topology_outcomes=topology_outcomes,
        development_metadata=development_metadata,
        final_metadata=final_metadata,
        topology_metadata=topology_metadata,
        state_contract=state_contract,
        final_contract=final_contract,
    )


def _aligned_structural_features(
    metadata: pd.DataFrame,
    states: pd.DataFrame,
    specifications: dict[str, Any],
    base_module: Any,
) -> pd.DataFrame:
    features = base_module.structural_feature_frame(metadata, specifications)
    return states[["episode_id"]].merge(
        features, on="episode_id", how="left", validate="one_to_one"
    )


def _selection_audit_from_artifact(
    specifications: dict[str, Any], artifact: dict[str, Any]
) -> pd.DataFrame:
    active = set(str(value) for value in artifact["active_features"])
    return pd.DataFrame(
        [
            {
                "representation": "R3_full_multilayer",
                "feature": name,
                "family": specification["family"],
                "transform": specification["transform"],
                "selected": name in active,
                "decision": "frozen_selected" if name in active else "frozen_excluded",
                "fit_scope": "preexisting_development_artifact",
            }
            for name, specification in specifications.items()
        ]
    )


def build_representations(
    contract: dict[str, Any],
    base_contract: dict[str, Any],
    data: InputData,
    base_module: Any,
    memory_module: Any,
    dba_module: Any,
) -> tuple[dict[str, RepresentationData], pd.DataFrame, pd.DataFrame]:
    policy = contract["policy"]
    quantile = float(policy["coverage_quantile"])
    metric = str(policy["distance_metric"])
    representations: dict[str, RepresentationData] = {}
    feature_frames: list[pd.DataFrame] = []
    fit_audits: list[pd.DataFrame] = []

    structural_contract = base_contract["representations"]["sql_structural"]
    structural_specs = structural_contract["features"]
    structural_reference = _aligned_structural_features(
        data.development_metadata, data.reference_states, structural_specs, base_module
    )
    structural_final = _aligned_structural_features(
        data.final_metadata, data.final_states, structural_specs, base_module
    )
    structural_topology = _aligned_structural_features(
        data.topology_metadata, data.topology_states, structural_specs, base_module
    )
    structural_processor = base_module.StructuralPreprocessor(structural_specs)
    r1_reference = structural_processor.fit(structural_reference)
    r1_final = structural_processor.transform(structural_final)
    r1_topology = structural_processor.transform(structural_topology)
    r1_threshold = dba_module._nearest_threshold(r1_reference, quantile, metric)
    r1_audit = structural_processor.selection_audit.copy()
    r1_audit.insert(0, "representation", "R1_sql_structural")
    r1_audit["fit_scope"] = "development_reference_only"
    fit_audits.append(r1_audit)
    representations["R1_sql_structural"] = RepresentationData(
        name="R1_sql_structural",
        reference_values=r1_reference,
        final_values=r1_final,
        topology_values=r1_topology,
        threshold=r1_threshold,
        fit_manifest={
            "fit_scope": "development_reference_only",
            "fit_state_count": len(data.reference_states),
            "fit_episode_ids": data.reference_states["episode_id"].astype(str).tolist(),
            "candidate_feature_count": len(structural_specs),
            "active_feature_count": len(structural_specs),
            "output_dimensions": r1_reference.shape[1],
            "coverage_quantile": quantile,
            "coverage_threshold": r1_threshold,
        },
        fit_audit=r1_audit,
    )

    full_specs = data.state_contract["state_representation"]["features"]
    r2_contract = base_contract["representations"]["coordinator_physical"]
    r2_names = [str(value) for value in r2_contract["included_features"]]
    r2_processor = memory_module.StatePreprocessor(
        specifications={name: full_specs[name] for name in r2_names},
        pca_components=int(r2_contract["pca_components"]),
        minimum_active_features=int(r2_contract["minimum_active_features"]),
    )
    r2_reference = r2_processor.fit(data.reference_states)
    r2_final = r2_processor.transform(data.final_states)
    r2_topology = r2_processor.transform(data.topology_states)
    r2_threshold = dba_module._nearest_threshold(r2_reference, quantile, metric)
    r2_audit = r2_processor.selection_audit.copy()
    r2_audit.insert(0, "representation", "R2_coordinator_physical")
    r2_audit["fit_scope"] = "development_reference_only"
    fit_audits.append(r2_audit)
    representations["R2_coordinator_physical"] = RepresentationData(
        name="R2_coordinator_physical",
        reference_values=r2_reference,
        final_values=r2_final,
        topology_values=r2_topology,
        threshold=r2_threshold,
        fit_manifest={
            "fit_scope": "development_reference_only",
            "fit_state_count": len(data.reference_states),
            "fit_episode_ids": data.reference_states["episode_id"].astype(str).tolist(),
            "candidate_feature_count": len(r2_names),
            "active_feature_count": len(r2_processor.active_features or []),
            "active_features": list(r2_processor.active_features or []),
            "output_dimensions": r2_reference.shape[1],
            "coverage_quantile": quantile,
            "coverage_threshold": r2_threshold,
        },
        fit_audit=r2_audit,
    )

    artifact_path = resolve_input(contract["inputs"]["frozen_full_model"])
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if artifact.get("fitted_on_n3") is not False:
        raise ValueError("Frozen R3 artifact must not be fitted on N3")
    frozen = FrozenFullTransformer(full_specs, artifact, memory_module)
    r3_reference = frozen.transform(data.reference_states)
    r3_final = frozen.transform(data.final_states)
    r3_topology = frozen.transform(data.topology_states)
    r3_threshold = dba_module._nearest_threshold(r3_reference, quantile, metric)
    expected = contract["expected"]
    if len(full_specs) != int(expected["full_candidate_features"]):
        raise ValueError("R3 candidate feature count changed")
    if len(frozen.active_features) != int(expected["full_active_features"]):
        raise ValueError("R3 active feature count changed")
    if r3_reference.shape[1] != int(expected["full_components"]):
        raise ValueError("R3 PCA component count changed")
    if not math.isclose(
        r3_threshold,
        float(expected["full_coverage_threshold"]),
        rel_tol=1e-10,
        abs_tol=1e-10,
    ):
        raise ValueError(f"R3 P99 changed: {r3_threshold}")
    r3_audit = _selection_audit_from_artifact(full_specs, artifact)
    fit_audits.append(r3_audit)
    representations["R3_full_multilayer"] = RepresentationData(
        name="R3_full_multilayer",
        reference_values=r3_reference,
        final_values=r3_final,
        topology_values=r3_topology,
        threshold=r3_threshold,
        fit_manifest={
            "fit_scope": "preexisting_development_artifact",
            "fit_state_count": int(artifact["reference_state_count"]),
            "fit_episode_ids": data.reference_states["episode_id"].astype(str).tolist(),
            "candidate_feature_count": len(full_specs),
            "active_feature_count": len(frozen.active_features),
            "active_features": frozen.active_features,
            "output_dimensions": r3_reference.shape[1],
            "coverage_quantile": float(artifact["coverage_quantile"]),
            "coverage_threshold": r3_threshold,
            "artifact_path": str(artifact_path),
            "artifact_sha256": sha256_file(artifact_path),
            "artifact_internal_sha256": artifact["artifact_sha256"],
            "fitted_on_n3": artifact["fitted_on_n3"],
        },
        fit_audit=r3_audit,
    )

    base_features = base_module._feature_contract_rows(base_contract, data.state_contract)
    name_map = {
        "sql_structural": "R1_sql_structural",
        "coordinator_physical": "R2_coordinator_physical",
        "full_multilayer": "R3_full_multilayer",
    }
    base_features["representation"] = base_features["representation"].map(name_map)
    base_features["target_or_outcome_used_for_selection"] = False
    selection = pd.concat(fit_audits, ignore_index=True)[
        ["representation", "feature", "selected", "decision", "fit_scope"]
    ].rename(
        columns={
            "selected": "active_after_reference_fit",
            "decision": "selection_decision",
            "fit_scope": "selection_fit_scope",
        }
    )
    base_features = base_features.merge(
        selection,
        on=["representation", "feature"],
        how="left",
        validate="one_to_one",
    )
    base_features["active_after_reference_fit"] = (
        base_features["active_after_reference_fit"].fillna(False).astype(bool)
    )
    excluded = ~base_features["included"].astype(bool)
    base_features.loc[excluded, "selection_decision"] = "excluded_from_candidate_contract"
    base_features.loc[excluded, "selection_fit_scope"] = "not_applicable"
    feature_frames.append(base_features)
    return (
        representations,
        pd.concat(fit_audits, ignore_index=True),
        pd.concat(feature_frames, ignore_index=True),
    )


def _episode_value_map(states: pd.DataFrame, values: np.ndarray) -> dict[str, np.ndarray]:
    return {
        str(episode_id): values[index]
        for index, episode_id in enumerate(states["episode_id"].astype(str))
    }


def _actual_by_action(
    outcomes: pd.DataFrame, episode_id: str, actions: tuple[str, ...]
) -> pd.Series:
    selected = outcomes[outcomes["episode_id"].astype(str).eq(episode_id)]
    values = selected.set_index("mitigation_action")["target_log2_gain"]
    if set(actions) - set(values.index.astype(str)):
        raise ValueError(f"Incomplete action response for {episode_id}")
    return values.loc[list(actions)].astype(float)


def _evaluate_one(
    *,
    evaluation: str,
    representation: RepresentationData,
    event: pd.Series,
    event_value: np.ndarray,
    actual_outcomes: pd.DataFrame,
    memory_states: pd.DataFrame,
    memory_outcomes: pd.DataFrame,
    memory_values: np.ndarray,
    contract: dict[str, Any],
    dba_module: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    actions = tuple(str(value) for value in contract["policy"]["actions"])
    estimator_states = memory_states.copy().reset_index(drop=True)
    estimator_states["normalized_sql_hash"] = estimator_states["logical_identity"]
    predictions, neighbors, nearest, eligible_count = dba_module._estimate_from_memory(
        event_value,
        memory_values,
        estimator_states,
        memory_outcomes,
        neighbors=int(contract["policy"]["neighbors"]),
        epsilon=float(contract["policy"]["distance_epsilon"]),
        distance_metric=str(contract["policy"]["distance_metric"]),
        excluded_query_id=str(event["query_id"]),
        excluded_normalized_sql_hash=str(event["logical_identity"]),
    )
    status = dba_module._status(
        memory_count=eligible_count,
        nearest_distance=nearest,
        coverage_threshold=representation.threshold,
        minimum_history=int(contract["policy"]["minimum_history_for_available"]),
    )
    candidate, predicted = dba_module._decision_actions(predictions, status, actions)
    actual = _actual_by_action(actual_outcomes, str(event["episode_id"]), actions)
    best = str(actual.idxmax())
    regret = float(actual.max() - actual[predicted]) if predicted else float("nan")
    memory_lookup = memory_states.set_index("episode_id", drop=False)
    trace_rows: list[dict[str, Any]] = []
    for rank, neighbor in enumerate(neighbors, start=1):
        neighbor_id = str(neighbor["episode_id"])
        state = memory_lookup.loc[neighbor_id]
        if isinstance(state, pd.DataFrame):
            state = state.iloc[0]
        trace_rows.append(
            {
                "evaluation": evaluation,
                "representation": representation.name,
                "episode_id": str(event["episode_id"]),
                "query_id": str(event["query_id"]),
                "logical_identity": str(event["logical_identity"]),
                "neighbor_rank": rank,
                "neighbor_episode_id": neighbor_id,
                "neighbor_query_id": str(state["query_id"]),
                "neighbor_logical_identity": str(state["logical_identity"]),
                "neighbor_source_scope": str(state["source_scope"]),
                "neighbor_episode_order": state.get("episode_order", np.nan),
                "distance": float(neighbor["distance"]),
                "weight": float(neighbor["weight"]),
                "same_query_id": str(state["query_id"]) == str(event["query_id"]),
                "same_logical_identity": str(state["logical_identity"])
                == str(event["logical_identity"]),
                "future_or_current_neighbor": bool(
                    str(state["source_scope"]) == "final_panel"
                    and pd.notna(state.get("episode_order"))
                    and int(state["episode_order"]) >= int(event.get("episode_order", 0))
                ),
                "action_gains_json": json.dumps(
                    neighbor["action_gains"], sort_keys=True, separators=(",", ":")
                ),
            }
        )
    row = {
        "evaluation": evaluation,
        "representation": representation.name,
        "episode_id": str(event["episode_id"]),
        "episode_order": int(event.get("episode_order", 0)),
        "round_id": str(event.get("round_id", "final_panel")),
        "query_id": str(event["query_id"]),
        "logical_identity": str(event["logical_identity"]),
        "topology_id": str(event["topology_id"]),
        "history_state_count": len(memory_states),
        "eligible_history_state_count": eligible_count,
        "nearest_distance": nearest,
        "coverage_threshold": representation.threshold,
        "coverage_ratio": (
            nearest / representation.threshold
            if representation.threshold > 0 and np.isfinite(nearest)
            else (0.0 if np.isfinite(nearest) and nearest == 0 else float("inf"))
        ),
        "decision_status": status,
        "candidate_action": candidate,
        "predicted_action": predicted,
        "actual_best_action": best,
        "top1_correct": bool(predicted and predicted == best),
        "regret_log2": regret,
        "neighbor_count": len(neighbors),
        "neighbor_evidence_json": json.dumps(neighbors, sort_keys=True, separators=(",", ":")),
        **{f"predicted_gain__{action}": predictions[action] for action in actions},
        **{f"actual_gain__{action}": float(actual[action]) for action in actions},
    }
    return row, trace_rows


def evaluate_sequential_final(
    representation: RepresentationData,
    data: InputData,
    contract: dict[str, Any],
    dba_module: Any,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    value_map = _episode_value_map(data.final_states, representation.final_values)
    memory_states = data.reference_states.copy().reset_index(drop=True)
    memory_outcomes = data.reference_outcomes.copy().reset_index(drop=True)
    memory_values = representation.reference_values.copy()
    rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for _, event in data.final_states.sort_values("episode_order").iterrows():
        row, trace = _evaluate_one(
            evaluation="E2",
            representation=representation,
            event=event,
            event_value=value_map[str(event["episode_id"])],
            actual_outcomes=data.final_outcomes,
            memory_states=memory_states,
            memory_outcomes=memory_outcomes,
            memory_values=memory_values,
            contract=contract,
            dba_module=dba_module,
        )
        rows.append(row)
        traces.extend(trace)
        event_frame = event.to_frame().T
        memory_states = pd.concat([memory_states, event_frame], ignore_index=True)
        selected_outcomes = data.final_outcomes[
            data.final_outcomes["episode_id"].astype(str).eq(str(event["episode_id"]))
        ]
        memory_outcomes = pd.concat([memory_outcomes, selected_outcomes], ignore_index=True)
        memory_values = np.vstack([memory_values, value_map[str(event["episode_id"])][None, :]])
    e2 = pd.DataFrame(rows)
    e1 = e2[
        e2["episode_id"].isin(
            data.final_states[data.final_states["query_occurrence"].astype(int).eq(1)][
                "episode_id"
            ].astype(str)
        )
    ].copy()
    e1["evaluation"] = "E1"
    trace_frame = pd.DataFrame(traces)
    e1_trace = trace_frame[trace_frame["episode_id"].isin(set(e1["episode_id"]))].copy()
    e1_trace["evaluation"] = "E1"
    return pd.concat([e1, e2], ignore_index=True), pd.concat(
        [e1_trace, trace_frame], ignore_index=True
    )


def _round_values(
    representation: RepresentationData, states: pd.DataFrame, round_id: str
) -> tuple[pd.DataFrame, np.ndarray]:
    mask = states["round_id"].astype(str).eq(round_id).to_numpy()
    return states.loc[mask].reset_index(drop=True), representation.topology_values[mask]


def evaluate_fixed_topology(
    representation: RepresentationData,
    data: InputData,
    contract: dict[str, Any],
    dba_module: Any,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    n2_states, n2_values = _round_values(representation, data.topology_states, "n2_control")
    a_states, a_values = _round_values(representation, data.topology_states, "phase_a")
    b_states, b_values = _round_values(representation, data.topology_states, "phase_b")
    n2_outcomes = data.topology_outcomes[
        data.topology_outcomes["round_id"].astype(str).eq("n2_control")
    ]
    a_outcomes = data.topology_outcomes[
        data.topology_outcomes["round_id"].astype(str).eq("phase_a")
    ]
    memory_a_states = pd.concat([data.reference_states, n2_states], ignore_index=True)
    memory_a_outcomes = pd.concat([data.reference_outcomes, n2_outcomes], ignore_index=True)
    memory_a_values = np.vstack([representation.reference_values, n2_values])
    memory_b_states = pd.concat([memory_a_states, a_states], ignore_index=True)
    memory_b_outcomes = pd.concat([memory_a_outcomes, a_outcomes], ignore_index=True)
    memory_b_values = np.vstack([memory_a_values, a_values])
    rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for evaluation, targets, values, actual, memory_states, memory_outcomes, memory_values in (
        (
            "E3",
            a_states,
            a_values,
            a_outcomes,
            memory_a_states,
            memory_a_outcomes,
            memory_a_values,
        ),
        (
            "E4",
            b_states,
            b_values,
            data.topology_outcomes[data.topology_outcomes["round_id"].astype(str).eq("phase_b")],
            memory_b_states,
            memory_b_outcomes,
            memory_b_values,
        ),
    ):
        value_map = _episode_value_map(targets, values)
        for _index, event in targets.sort_values("episode_order").reset_index(drop=True).iterrows():
            row, trace = _evaluate_one(
                evaluation=evaluation,
                representation=representation,
                event=event,
                event_value=value_map[str(event["episode_id"])],
                actual_outcomes=actual,
                memory_states=memory_states,
                memory_outcomes=memory_outcomes,
                memory_values=memory_values,
                contract=contract,
                dba_module=dba_module,
            )
            rows.append(row)
            traces.extend(trace)
    return pd.DataFrame(rows), pd.DataFrame(traces)


def summarize_results(results: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (evaluation, representation), group in results.groupby(
        ["evaluation", "representation"], sort=True
    ):
        recommended = group[group["predicted_action"].fillna("").astype(str).ne("")]
        distances = pd.to_numeric(group["nearest_distance"], errors="coerce").dropna()
        rows.append(
            {
                "evaluation": evaluation,
                "representation": representation,
                "episode_count": len(group),
                "recommendation_count": len(recommended),
                "abstention_count": len(group) - len(recommended),
                "coverage": len(recommended) / len(group),
                "correct_decision_count": int(recommended["top1_correct"].astype(bool).sum()),
                "top1_accuracy": (
                    float(recommended["top1_correct"].astype(bool).mean())
                    if len(recommended)
                    else float("nan")
                ),
                "mean_regret_log2": (
                    float(recommended["regret_log2"].mean()) if len(recommended) else float("nan")
                ),
                "nearest_distance_median": (
                    float(distances.median()) if len(distances) else float("nan")
                ),
                "nearest_distance_p25": (
                    float(distances.quantile(0.25)) if len(distances) else float("nan")
                ),
                "nearest_distance_p75": (
                    float(distances.quantile(0.75)) if len(distances) else float("nan")
                ),
                "nearest_distance_p95": (
                    float(distances.quantile(0.95)) if len(distances) else float("nan")
                ),
                "coverage_threshold": float(group["coverage_threshold"].iloc[0]),
            }
        )
    return pd.DataFrame(rows)


def bootstrap_intervals(
    results: pd.DataFrame, summary: pd.DataFrame, contract: dict[str, Any]
) -> pd.DataFrame:
    specification = contract["bootstrap"]
    samples = int(specification["samples"])
    seed = int(specification["random_seed"])
    alpha = (1.0 - float(specification["confidence_level"])) / 2.0
    base_module = load_module(BASE_SCRIPT, "representation_ablation_bootstrap_base_103")
    rows: list[dict[str, Any]] = []
    for (evaluation, representation), group in results.groupby(
        ["evaluation", "representation"], sort=True
    ):
        distributions = base_module._cluster_metric_samples(group, samples=samples, seed=seed)
        point = summary[
            summary["evaluation"].eq(evaluation) & summary["representation"].eq(representation)
        ].iloc[0]
        for metric, distribution in distributions.items():
            finite = distribution[np.isfinite(distribution)]
            rows.append(
                {
                    "evaluation": evaluation,
                    "representation": representation,
                    "metric": metric,
                    "point_estimate": float(point[metric]),
                    "ci_lower": (
                        float(np.quantile(finite, alpha)) if len(finite) else float("nan")
                    ),
                    "ci_upper": (
                        float(np.quantile(finite, 1.0 - alpha)) if len(finite) else float("nan")
                    ),
                    "cluster_key": specification["cluster_key"],
                    "cluster_count": group["query_id"].nunique(),
                    "bootstrap_samples": samples,
                    "finite_bootstrap_samples": len(finite),
                }
            )
    return pd.DataFrame(rows)


def paired_bootstrap_differences(results: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    specification = contract["bootstrap"]
    samples = int(specification["samples"])
    seed = int(specification["random_seed"])
    alpha = (1.0 - float(specification["confidence_level"])) / 2.0
    base_module = load_module(BASE_SCRIPT, "representation_ablation_paired_base_103")
    rows: list[dict[str, Any]] = []
    for evaluation in ("E1", "E2", "E3", "E4"):
        distributions = {
            representation: base_module._cluster_metric_samples(
                results[
                    results["evaluation"].eq(evaluation)
                    & results["representation"].eq(representation)
                ],
                samples=samples,
                seed=seed,
            )
            for representation in REPRESENTATIONS
        }
        for baseline in REPRESENTATIONS[:2]:
            for metric in ("coverage", "top1_accuracy", "mean_regret_log2"):
                if metric == "mean_regret_log2":
                    delta = (
                        distributions[baseline][metric]
                        - distributions["R3_full_multilayer"][metric]
                    )
                    formula = "baseline_minus_R3"
                else:
                    delta = (
                        distributions["R3_full_multilayer"][metric]
                        - distributions[baseline][metric]
                    )
                    formula = "R3_minus_baseline"
                finite = delta[np.isfinite(delta)]
                rows.append(
                    {
                        "evaluation": evaluation,
                        "candidate": "R3_full_multilayer",
                        "baseline": baseline,
                        "metric": metric,
                        "difference_formula": formula,
                        "positive_favors_R3": True,
                        "mean_difference": (float(finite.mean()) if len(finite) else float("nan")),
                        "ci_lower": (
                            float(np.quantile(finite, alpha)) if len(finite) else float("nan")
                        ),
                        "ci_upper": (
                            float(np.quantile(finite, 1.0 - alpha)) if len(finite) else float("nan")
                        ),
                        "bootstrap_samples": samples,
                    }
                )
    return pd.DataFrame(rows)


def _identity_prediction(
    event: pd.Series,
    memory_states: pd.DataFrame,
    memory_outcomes: pd.DataFrame,
    actions: tuple[str, ...],
    *,
    context_aware: bool,
) -> tuple[dict[str, float], str, list[str]]:
    selected = memory_states[
        memory_states["logical_identity"].astype(str).eq(str(event["logical_identity"]))
    ]
    if context_aware:
        selected = selected[selected["topology_id"].astype(str).eq(str(event["topology_id"]))]
    ids = selected["episode_id"].astype(str).tolist()
    if not ids:
        return {action: float("nan") for action in actions}, "identity_unseen", []
    known = memory_outcomes[memory_outcomes["episode_id"].astype(str).isin(ids)]
    predictions = {
        action: float(
            known[known["mitigation_action"].astype(str).eq(action)]["target_log2_gain"].median()
        )
        for action in actions
    }
    return predictions, "available", ids


def _identity_row(
    evaluation: str,
    method: str,
    event: pd.Series,
    predictions: dict[str, float],
    status: str,
    evidence: list[str],
    outcomes: pd.DataFrame,
    actions: tuple[str, ...],
) -> dict[str, Any]:
    actual = _actual_by_action(outcomes, str(event["episode_id"]), actions)
    predicted = max(actions, key=predictions.__getitem__) if status == "available" else ""
    best = str(actual.idxmax())
    return {
        "evaluation": evaluation,
        "reference_method": method,
        "identity_definition": (
            "logical_identity+topology_id"
            if method == "exact_context_memory"
            else "logical_identity_without_topology"
        ),
        "episode_id": str(event["episode_id"]),
        "query_id": str(event["query_id"]),
        "logical_identity": str(event["logical_identity"]),
        "topology_id": str(event["topology_id"]),
        "history_match_count": len(evidence),
        "decision_status": status,
        "predicted_action": predicted,
        "actual_best_action": best,
        "top1_correct": bool(predicted and predicted == best),
        "regret_log2": float(actual.max() - actual[predicted]) if predicted else float("nan"),
        "evidence_episode_ids_json": json.dumps(evidence, separators=(",", ":")),
    }


def identity_memory_baselines(data: InputData, contract: dict[str, Any]) -> pd.DataFrame:
    actions = tuple(str(value) for value in contract["policy"]["actions"])
    rows: list[dict[str, Any]] = []
    memory_states = pd.DataFrame(columns=data.final_states.columns)
    memory_outcomes = pd.DataFrame(columns=data.final_outcomes.columns)
    for _, event in data.final_states.sort_values("episode_order").iterrows():
        for method, context_aware in (
            ("logical_query_memory", False),
            ("exact_context_memory", True),
        ):
            predictions, status, evidence = _identity_prediction(
                event,
                memory_states,
                memory_outcomes,
                actions,
                context_aware=context_aware,
            )
            row = _identity_row(
                "E2", method, event, predictions, status, evidence, data.final_outcomes, actions
            )
            rows.append(row)
            if int(event["query_occurrence"]) == 1:
                first = dict(row)
                first["evaluation"] = "E1"
                rows.append(first)
        memory_states = pd.concat([memory_states, event.to_frame().T], ignore_index=True)
        memory_outcomes = pd.concat(
            [
                memory_outcomes,
                data.final_outcomes[
                    data.final_outcomes["episode_id"].astype(str).eq(str(event["episode_id"]))
                ],
            ],
            ignore_index=True,
        )
    n2 = data.topology_states[data.topology_states["round_id"].eq("n2_control")]
    phase_a = data.topology_states[data.topology_states["round_id"].eq("phase_a")]
    n2_outcomes = data.topology_outcomes[data.topology_outcomes["round_id"].eq("n2_control")]
    phase_a_outcomes = data.topology_outcomes[data.topology_outcomes["round_id"].eq("phase_a")]
    for evaluation, targets, target_outcomes, known_states, known_outcomes in (
        (
            "E3",
            phase_a,
            phase_a_outcomes,
            n2,
            n2_outcomes,
        ),
        (
            "E4",
            data.topology_states[data.topology_states["round_id"].eq("phase_b")],
            data.topology_outcomes[data.topology_outcomes["round_id"].eq("phase_b")],
            pd.concat([n2, phase_a], ignore_index=True),
            pd.concat([n2_outcomes, phase_a_outcomes], ignore_index=True),
        ),
    ):
        for _, event in targets.sort_values("episode_order").iterrows():
            for method, context_aware in (
                ("logical_query_memory", False),
                ("exact_context_memory", True),
            ):
                predictions, status, evidence = _identity_prediction(
                    event,
                    known_states,
                    known_outcomes,
                    actions,
                    context_aware=context_aware,
                )
                rows.append(
                    _identity_row(
                        evaluation,
                        method,
                        event,
                        predictions,
                        status,
                        evidence,
                        target_outcomes,
                        actions,
                    )
                )
    return pd.DataFrame(rows)


def identity_memory_summary(rows: pd.DataFrame) -> pd.DataFrame:
    output: list[dict[str, Any]] = []
    for (evaluation, method), group in rows.groupby(["evaluation", "reference_method"], sort=True):
        recommended = group[group["predicted_action"].fillna("").astype(str).ne("")]
        output.append(
            {
                "evaluation": evaluation,
                "reference_method": method,
                "identity_definition": group["identity_definition"].iloc[0],
                "episode_count": len(group),
                "recommendation_count": len(recommended),
                "abstention_count": len(group) - len(recommended),
                "coverage": len(recommended) / len(group),
                "correct_decision_count": int(recommended["top1_correct"].sum()),
                "top1_accuracy": (
                    float(recommended["top1_correct"].mean()) if len(recommended) else float("nan")
                ),
                "mean_regret_log2": (
                    float(recommended["regret_log2"].mean()) if len(recommended) else float("nan")
                ),
            }
        )
    return pd.DataFrame(output)


def _rank_disagreement(left: np.ndarray, right: np.ndarray) -> float:
    disagreements = 0
    comparisons = 0
    for first, second in itertools.combinations(range(len(left)), 2):
        left_sign = np.sign(left[first] - left[second])
        right_sign = np.sign(right[first] - right[second])
        disagreements += int(left_sign != right_sign)
        comparisons += 1
    return disagreements / comparisons if comparisons else float("nan")


def response_distance_analysis(
    representations: dict[str, RepresentationData],
    data: InputData,
    contract: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    actions = [str(value) for value in contract["policy"]["actions"]]
    response = data.topology_outcomes.pivot(
        index="episode_id", columns="mitigation_action", values="target_log2_gain"
    )[actions]
    states = data.topology_states.reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for representation, bundle in representations.items():
        for left_index, right_index in itertools.combinations(range(len(states)), 2):
            left = states.iloc[left_index]
            right = states.iloc[right_index]
            left_topology = "N2" if int(left["region_count"]) == 2 else "N3"
            right_topology = "N2" if int(right["region_count"]) == 2 else "N3"
            pair_type = "-".join(sorted((left_topology, right_topology)))
            left_response = response.loc[str(left["episode_id"])].to_numpy(dtype=float)
            right_response = response.loc[str(right["episode_id"])].to_numpy(dtype=float)
            response_delta = left_response - right_response
            representation_distance = float(
                np.linalg.norm(
                    bundle.topology_values[left_index] - bundle.topology_values[right_index]
                )
            )
            rows.append(
                {
                    "representation": representation,
                    "pair_type": pair_type,
                    "left_episode_id": str(left["episode_id"]),
                    "right_episode_id": str(right["episode_id"]),
                    "left_round_id": str(left["round_id"]),
                    "right_round_id": str(right["round_id"]),
                    "left_query_id": str(left["query_id"]),
                    "right_query_id": str(right["query_id"]),
                    "same_query_id": str(left["query_id"]) == str(right["query_id"]),
                    "representation_distance_l2": representation_distance,
                    "action_response_distance_l1": float(np.abs(response_delta).sum()),
                    "action_response_distance_l2": float(np.linalg.norm(response_delta)),
                    "left_best_action": actions[int(np.argmax(left_response))],
                    "right_best_action": actions[int(np.argmax(right_response))],
                    "best_action_equal": int(np.argmax(left_response))
                    == int(np.argmax(right_response)),
                    "action_rank_disagreement": _rank_disagreement(left_response, right_response),
                    "action_response_spearman": float(
                        spearmanr(rankdata(left_response), rankdata(right_response)).statistic
                    ),
                }
            )
    pairs = pd.DataFrame(rows)
    summary_rows: list[dict[str, Any]] = []
    for (representation, pair_type), group in pairs.groupby(
        ["representation", "pair_type"], sort=True
    ):
        correlation = spearmanr(
            group["representation_distance_l2"],
            group["action_response_distance_l2"],
        )
        summary_rows.append(
            {
                "representation": representation,
                "pair_type": pair_type,
                "pair_count": len(group),
                "representation_distance_median": float(
                    group["representation_distance_l2"].median()
                ),
                "action_response_distance_l2_median": float(
                    group["action_response_distance_l2"].median()
                ),
                "best_action_agreement_share": float(group["best_action_equal"].mean()),
                "rank_disagreement_mean": float(group["action_rank_disagreement"].mean()),
                "distance_response_spearman": float(correlation.statistic),
                "distance_response_pvalue_exploratory": float(correlation.pvalue),
                "interpretation": "exploratory_non_independent_pairs",
            }
        )
    matched = pairs[pairs["same_query_id"].astype(bool) & pairs["pair_type"].eq("N2-N3")].copy()
    return pairs, pd.DataFrame(summary_rows), matched


def _gain_digest(frame: pd.DataFrame, actions: tuple[str, ...]) -> str:
    columns = ["episode_id", *[f"actual_gain__{action}" for action in actions]]
    text = frame[columns].sort_values("episode_id").to_csv(index=False, float_format="%.17g")
    return hashlib.sha256(text.encode()).hexdigest()


def leakage_audit(
    results: pd.DataFrame,
    traces: pd.DataFrame,
    summary: pd.DataFrame,
    representations: dict[str, RepresentationData],
    data: InputData,
    contract: dict[str, Any],
    feature_manifest: pd.DataFrame,
) -> dict[str, Any]:
    actions = tuple(str(value) for value in contract["policy"]["actions"])
    expected_sets = {
        "E1": set(
            data.final_states[data.final_states["query_occurrence"].astype(int).eq(1)][
                "episode_id"
            ].astype(str)
        ),
        "E2": set(data.final_states["episode_id"].astype(str)),
        "E3": set(
            data.topology_states[data.topology_states["round_id"].eq("phase_a")][
                "episode_id"
            ].astype(str)
        ),
        "E4": set(
            data.topology_states[data.topology_states["round_id"].eq("phase_b")][
                "episode_id"
            ].astype(str)
        ),
    }
    observed_sets = {
        (evaluation, representation): set(group["episode_id"].astype(str))
        for (evaluation, representation), group in results.groupby(["evaluation", "representation"])
    }
    fit_ids = {
        representation: set(bundle.fit_manifest["fit_episode_ids"])
        for representation, bundle in representations.items()
    }
    target_ids = set(data.final_states["episode_id"].astype(str)) | set(
        data.topology_states["episode_id"].astype(str)
    )
    gain_digests = {
        f"{evaluation}::{representation}": _gain_digest(group, actions)
        for (evaluation, representation), group in results.groupby(["evaluation", "representation"])
    }
    digest_by_evaluation: dict[str, set[str]] = {}
    for key, digest in gain_digests.items():
        evaluation = key.split("::", 1)[0]
        digest_by_evaluation.setdefault(evaluation, set()).add(digest)
    abstention_ok = all(
        int(row.recommendation_count) + int(row.abstention_count) == int(row.episode_count)
        and (
            pd.isna(row.top1_accuracy)
            if int(row.recommendation_count) == 0
            else math.isclose(
                float(row.top1_accuracy),
                int(row.correct_decision_count) / int(row.recommendation_count),
            )
        )
        for row in summary.itertuples(index=False)
    )
    forbidden = ("query_id", "scenario_id", "sql_hash", "best_action", "target_log2_gain")
    included_features = feature_manifest[feature_manifest["included"].astype(bool)][
        "feature"
    ].astype(str)
    checks = {
        "all_transforms_fit_only_on_development_reference": all(
            bundle.fit_manifest["fit_scope"]
            in {"development_reference_only", "preexisting_development_artifact"}
            and int(bundle.fit_manifest["fit_state_count"])
            == int(contract["expected"]["development_states"])
            and not fit_ids[name] & target_ids
            for name, bundle in representations.items()
        ),
        "R3_uses_preexisting_artifact_without_n3_fit": (
            representations["R3_full_multilayer"].fit_manifest["fit_scope"]
            == "preexisting_development_artifact"
            and representations["R3_full_multilayer"].fit_manifest["fitted_on_n3"] is False
        ),
        "no_same_query_neighbors": bool(
            traces.empty or not traces["same_query_id"].astype(bool).any()
        ),
        "no_same_logical_identity_neighbors": bool(
            traces.empty or not traces["same_logical_identity"].astype(bool).any()
        ),
        "no_future_final_panel_neighbors": bool(
            traces.empty or not traces["future_or_current_neighbor"].astype(bool).any()
        ),
        "identical_episode_sets_by_evaluation": all(
            observed_sets[(evaluation, representation)] == expected_sets[evaluation]
            for evaluation in expected_sets
            for representation in REPRESENTATIONS
        ),
        "identical_action_outcomes_by_evaluation": all(
            len(digests) == 1 for digests in digest_by_evaluation.values()
        ),
        "abstentions_excluded_from_top1_denominator": abstention_ok,
        "feature_contract_excludes_identifiers_and_outcomes": not any(
            token in name.lower() for name in included_features for token in forbidden
        )
        and not feature_manifest["target_or_outcome_used_for_selection"].astype(bool).any(),
        "coverage_thresholds_calibrated_per_representation": len(
            {bundle.threshold for bundle in representations.values()}
        )
        > 1,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "fit_episode_ids_by_representation": {key: sorted(value) for key, value in fit_ids.items()},
        "actual_gain_sha256_by_evaluation_representation": gain_digests,
        "explicitly_forbidden_feature_name_patterns": list(forbidden),
    }


def action_rankings(results: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    actions = [str(value) for value in contract["policy"]["actions"]]
    rows: list[dict[str, Any]] = []
    for row in results.to_dict(orient="records"):
        actual = {action: float(row[f"actual_gain__{action}"]) for action in actions}
        predicted = {action: row[f"predicted_gain__{action}"] for action in actions}
        actual_order = sorted(actions, key=lambda action: (-actual[action], action))
        predicted_order = (
            sorted(actions, key=lambda action: (-float(predicted[action]), action))
            if all(np.isfinite(predicted[action]) for action in actions)
            else []
        )
        for action in actions:
            rows.append(
                {
                    "evaluation": row["evaluation"],
                    "representation": row["representation"],
                    "episode_id": row["episode_id"],
                    "query_id": row["query_id"],
                    "action": action,
                    "actual_gain_log2": actual[action],
                    "actual_rank": actual_order.index(action) + 1,
                    "predicted_gain_log2": predicted[action],
                    "predicted_rank": (
                        predicted_order.index(action) + 1 if predicted_order else np.nan
                    ),
                    "selected_action": action == row["predicted_action"],
                }
            )
    return pd.DataFrame(rows)


def reproduction_audit(
    results: pd.DataFrame, contract: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame]:
    archived = pd.read_csv(
        resolve_input(contract["inputs"]["archived_ablation_release"]) / "episode_results.csv",
        low_memory=False,
    )
    archived = archived[archived["representation"].astype(str).eq("full_multilayer")].copy()
    current_final = results[
        results["evaluation"].eq("E2") & results["representation"].eq("R3_full_multilayer")
    ].copy()
    final_join = current_final.merge(
        archived,
        on="episode_id",
        suffixes=("_current", "_archived"),
        validate="one_to_one",
    )
    final_join["prediction_matches"] = (
        final_join["predicted_action_current"]
        .fillna("")
        .eq(final_join["predicted_action_archived"].fillna(""))
    )
    final_join["status_matches"] = final_join["decision_status_current"].eq(
        final_join["decision_status_archived"]
    )
    final_join["distance_matches"] = np.isclose(
        final_join["nearest_distance_current"],
        final_join["nearest_distance_archived"],
        equal_nan=True,
        rtol=1e-10,
        atol=1e-10,
    )
    topology_scored = pd.read_csv(
        resolve_input(contract["inputs"]["topology_report"]) / "phase_recommendations_scored.csv",
        low_memory=False,
    )
    topology_scored = topology_scored[
        topology_scored["method"].astype(str).eq("cross_query_knn")
    ].copy()
    topology_scored["evaluation"] = topology_scored["phase"].map({"A": "E3", "B": "E4"})
    current_topology = results[
        results["evaluation"].isin(["E3", "E4"])
        & results["representation"].eq("R3_full_multilayer")
    ]
    topology_join = current_topology.merge(
        topology_scored,
        on=["evaluation", "query_id"],
        suffixes=("_current", "_archived"),
        validate="one_to_one",
    )
    topology_join["prediction_matches"] = (
        topology_join["predicted_action_current"]
        .fillna("")
        .eq(topology_join["predicted_action_archived"].fillna(""))
    )
    topology_join["status_matches"] = topology_join["decision_status_current"].eq(
        topology_join["decision_status_archived"]
    )
    topology_join["distance_matches"] = np.isclose(
        topology_join["nearest_distance_current"],
        topology_join["nearest_distance_archived"],
        equal_nan=True,
        rtol=1e-10,
        atol=1e-10,
    )
    detail = pd.concat(
        [
            final_join[
                [
                    "episode_id",
                    "prediction_matches",
                    "status_matches",
                    "distance_matches",
                ]
            ].assign(scope="archived_E2"),
            topology_join[
                [
                    "episode_id_current",
                    "prediction_matches",
                    "status_matches",
                    "distance_matches",
                ]
            ]
            .rename(columns={"episode_id_current": "episode_id"})
            .assign(scope="archived_E3_E4"),
        ],
        ignore_index=True,
    )
    checks = {
        "R3_reproduces_archived_E2": len(final_join) == 45
        and final_join[["prediction_matches", "status_matches", "distance_matches"]].all(axis=None),
        "R3_reproduces_archived_E3_E4": len(topology_join) == 30
        and topology_join[["prediction_matches", "status_matches", "distance_matches"]].all(
            axis=None
        ),
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}, detail


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "Nema redova."
    lines = ["| " + " | ".join(columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in frame[columns].itertuples(index=False, name=None):
        rendered: list[str] = []
        for value in row:
            if pd.isna(value):
                text = ""
            elif isinstance(value, (float, np.floating)):
                text = f"{float(value):.4f}"
            else:
                text = str(value)
            rendered.append(text.replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(rendered) + " |")
    return "\n".join(lines)


def input_manifest(contract_path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    inputs = contract["inputs"]
    paths = {
        "experiment_contract": contract_path,
        "base_ablation_contract": resolve_input(inputs["base_ablation_contract"]),
        "development_state_contract": resolve_input(inputs["development_state_contract"]),
        "development_episodes": resolve_input(inputs["development_report"]) / "episodes.csv",
        "final_panel_contract": resolve_input(inputs["final_panel_contract"]),
        "final_episode_states": resolve_input(inputs["final_panel_report"])
        / "observed_episode_states.csv",
        "final_action_outcomes": resolve_input(inputs["final_panel_report"])
        / "observed_action_outcomes.csv",
        "final_execution_features": resolve_input(inputs["final_panel_index"])
        / "execution_features.csv",
        "archived_ablation_results": resolve_input(inputs["archived_ablation_release"])
        / "episode_results.csv",
        "topology_contract": resolve_input(inputs["topology_contract"]),
        "topology_episode_states": resolve_input(inputs["topology_report"]) / "episode_states.csv",
        "topology_action_outcomes": resolve_input(inputs["topology_report"])
        / "action_outcomes.csv",
        "topology_frozen_recommendations": resolve_input(inputs["topology_report"])
        / "phase_recommendations_scored.csv",
        "frozen_full_model": resolve_input(inputs["frozen_full_model"]),
    }
    return {
        "experiment_id": contract["experiment_id"],
        "offline_only": True,
        "archived_results_modified": False,
        "inputs": {
            name: {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for name, path in paths.items()
        },
    }


def write_report(
    out_dir: Path,
    contract: dict[str, Any],
    summary: pd.DataFrame,
    thresholds: pd.DataFrame,
    bootstrap: pd.DataFrame,
    paired: pd.DataFrame,
    identity_summary: pd.DataFrame,
    response_summary: pd.DataFrame,
    matched_topology: pd.DataFrame,
    leakage: dict[str, Any],
    reproduction: dict[str, Any],
) -> None:
    metric_columns = [
        "evaluation",
        "representation",
        "episode_count",
        "recommendation_count",
        "abstention_count",
        "coverage",
        "correct_decision_count",
        "top1_accuracy",
        "mean_regret_log2",
        "nearest_distance_median",
    ]
    threshold_table = _markdown_table(
        thresholds,
        [
            "representation",
            "fit_state_count",
            "output_dimensions",
            "coverage_quantile",
            "coverage_threshold",
        ],
    )
    result_table = _markdown_table(summary, metric_columns)
    identity_table = _markdown_table(
        identity_summary,
        [
            "evaluation",
            "reference_method",
            "episode_count",
            "recommendation_count",
            "coverage",
            "top1_accuracy",
            "mean_regret_log2",
        ],
    )
    response_table = _markdown_table(
        response_summary,
        [
            "representation",
            "pair_type",
            "pair_count",
            "representation_distance_median",
            "action_response_distance_l2_median",
            "best_action_agreement_share",
            "rank_disagreement_mean",
            "distance_response_spearman",
        ],
    )
    matched_summary = (
        matched_topology.groupby("representation", sort=True)
        .agg(
            matched_pair_count=("episode_id", "size")
            if "episode_id" in matched_topology
            else ("left_episode_id", "size"),
            physical_distance_median=("representation_distance_l2", "median"),
            response_distance_median=("action_response_distance_l2", "median"),
            best_action_agreement=("best_action_equal", "mean"),
        )
        .reset_index()
    )
    matched_table = _markdown_table(matched_summary, list(matched_summary.columns))
    significant = paired[(paired["ci_lower"] > 0) | (paired["ci_upper"] < 0)][
        [
            "evaluation",
            "baseline",
            "metric",
            "mean_difference",
            "ci_lower",
            "ci_upper",
        ]
    ]
    significant_table = _markdown_table(significant, list(significant.columns))
    checks = {**leakage["checks"], **reproduction["checks"]}
    check_table = _markdown_table(
        pd.DataFrame([{"check": key, "passed": value} for key, value in checks.items()]),
        ["check", "passed"],
    )
    e1 = summary[summary["evaluation"].eq("E1")].set_index("representation")
    e2 = summary[summary["evaluation"].eq("E2")].set_index("representation")
    e3 = summary[summary["evaluation"].eq("E3")].set_index("representation")
    e4 = summary[summary["evaluation"].eq("E4")].set_index("representation")
    r3_e1 = e1.loc["R3_full_multilayer"]
    r3_e2 = e2.loc["R3_full_multilayer"]
    r2_e3 = e3.loc["R2_coordinator_physical"]
    r3_e3 = e3.loc["R3_full_multilayer"]
    r3_e4 = e4.loc["R3_full_multilayer"]
    best_e2 = e2.sort_values(["top1_accuracy", "mean_regret_log2"], ascending=[False, True]).index[
        0
    ]
    best_e4 = e4.sort_values(["top1_accuracy", "mean_regret_log2"], ascending=[False, True]).index[
        0
    ]
    report = f"""# Offline ablation reprezentacija kroz E1-E4

## Pitanje

> {contract["research_question"]}

Ovaj eksperiment nije pokrenuo nijedan SQL upit. Ponovo koristi 26 razvojnih
stanja, 45 stanja zavrsnog DBA panela i 45 kontrolisanih N2/N3 stanja. Svako
stanje grupise tri epizode pojedinacnih akcija sa zasebno izmjerenim ishodima.
Arhivirani rezultati nisu mijenjani.

## Reprezentacije

- **R1 SQL-strukturna:** 18 obiljezja normalizovanog SQL-a i sedam osnovnih
  porodica operatora glavnog GAC plana. Ne koristi identifikatore niti runtime
  action ishode. Svih 25 kandidata ostaje u izlaznom prostoru.
- **R2 coordinator fizicka:** rezultat, wall-clock, bufferi i standardni
  coordinator `EXPLAIN` pokazatelji. Iskljucuje regionalne planove, worker/task
  fragmente, edge dokaz, OS telemetriju i viseslojne topoloske odnose. Od 22
  kandidata, 15 je aktivno na razvojnoj referenci, pa su reducirani na sest PCA
  komponenti.
- **R3 puna viseslojna:** neizmijenjeni zamrznuti tok 93 kandidata -> 64 aktivna
  pokazatelja -> 6 PCA komponenti. Parametri su ucitani iz postojeceg artefakta,
  bez refita na zavrsnom ili N3 panelu.

## Kalibracija pokrivenosti

Svaka reprezentacija koristi k=5 i euklidsku udaljenost, ali vlastiti empirical
P99 prag izracunat samo iz razvojnih stanja:

{threshold_table}

R1 prag je nula jer razvojnih 26 stanja sadrzi jedan SQL oblik i sve njegove
strukturne koordinate su konstantne. To je stvarno ogranicenje dostupnog
kalibracijskog skupa, ne razlog za post-hoc sirenje praga.

## E1-E4

{result_table}

Na E2 puna reprezentacija postiže Top-1 `{float(r3_e2["top1_accuracy"]):.4f}` uz
regret `{float(r3_e2["mean_regret_log2"]):.4f}`. Najbolja tačkasta reprezentacija
na E2 je `{best_e2}`, a na E4 `{best_e4}`. Coverage i kvalitet moraju se citati
zajedno, jer apstinencije nisu racunate kao pogresne Top-1 preporuke.

Na prvom susretu s novim SQL-om R3 daje preporuku za
`{int(r3_e1["recommendation_count"])}/{int(r3_e1["episode_count"])}` epizoda i
ispravno bira prvu akciju u `{int(r3_e1["correct_decision_count"])}` od tih
slucajeva. U E3 isti zamrznuti prostor ne prenosi preporuke na N3: medijana
udaljenosti `{float(r3_e3["nearest_distance_median"]):.4f}` veca je od praga
`{float(r3_e3["coverage_threshold"]):.4f}`, pa R3 apstinira u svih
`{int(r3_e3["episode_count"])}` epizoda. R2 u E3 pokriva
`{int(r2_e3["recommendation_count"])}/{int(r2_e3["episode_count"])}`, ali uz
Top-1 `{float(r2_e3["top1_accuracy"]):.4f}` i regret
`{float(r2_e3["mean_regret_log2"]):.4f}`. Nakon sto je faza A dodana kao ranija
N3 memorija, R3 u E4 pokriva svih `{int(r3_e4["episode_count"])}` epizoda uz
Top-1 `{float(r3_e4["top1_accuracy"]):.4f}`. To razlikuje otkrivanje nepokrivenog
fizickog stanja od uspjesnog prijenosa action-response ponasanja.

## Exact i logical memorija

{identity_table}

Ovi redovi su referentni baselinei i nisu ukljuceni u cross-query poređenje R1-R3.

## Fizicka i action-response udaljenost

{response_table}

Za iste SQL scenarije preko N2-N3 granice:

{matched_table}

Spearmanove vrijednosti su eksploratorne. Parovi dijele epizode i zato nisu
nezavisna populacijska opazanja. Analiza provjerava geometrijsko slaganje, a ne
kauzalnost.

## Grupisani bootstrap

Intervali su dobijeni sa `{contract["bootstrap"]["samples"]}` resampliranja,
grupisanih po `query_id`. Pozitivna uparena razlika favorizuje R3. Intervali koji
ne obuhvataju nulu su:

{significant_table}

## Leakage i reprodukcija

Status: **{"PASS" if all(checks.values()) else "FAIL"}**

{check_table}

## Zakljucak

Rezultat se ne tumaci kao univerzalna pobjeda jedne reprezentacije. E1 i E2
direktno mjere cross-query vrijednost dodatnog viseslojnog dokaza, dok E3 i E4
pokazuju da geometrijska osjetljivost na promjenu topologije nije isto sto i
promjena optimalnog action-response poretka. R1 i R2 ostaju stvarni baselinei,
a ne namjerno oslabljene varijante.

## Otvoreni metodoloski problemi

- Razvojna referenca sadrzi 26 stanja jednog SQL oblika. R1 P99 je zato nula i
  nije robustno kalibrisan za raznovrsnu SQL-strukturnu memoriju.
- Samo 15 `query_id` grupa ulazi u svaku zavrsnu evaluaciju. Tačkaste Top-1
  razlike uglavnom imaju siroke bootstrap intervale i ne dokazuju univerzalnu
  nadmoc R3.
- Potpuna apstinencija R3 u E3 potvrđuje detekciju nepokrivenog N3 stanja, ali
  ne daje procjenu kakvu bi preporuku R3 napravio bez coverage pravila.
- Fizicka/action-response korelacija je eksploratorna jer parovi dijele epizode
  i nisu nezavisna populacijska opazanja.
- Zakljucci vaze za tri poznate GAC Top-K akcije i posmatranu infrastrukturu.
  Ne dokazuju izbor proizvoljne PostgreSQL akcije niti univerzalnu prenosivost.

## Reprodukcija

```bash
make representation-ablation-e1-e4
make representation-ablation-e1-e4-local-gate
```

Glavni masinski izlazi su `episode_representation_results.csv`,
`representation_summary.csv`, `neighbor_trace.csv`, `action_rankings.csv`,
`bootstrap_intervals.csv`, `paired_representation_differences.csv`,
`physical_action_response_pairs.csv`, `physical_action_response_summary.csv`,
`identity_memory_results.csv`, `feature_manifest.csv`, `fit_manifest.json`,
`leakage_audit.json` i `input_manifest.json`.
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")


def analyze(contract_path: Path, out_dir: Path) -> dict[str, Any]:
    contract = read_yaml(contract_path)
    base_contract = read_yaml(resolve_input(contract["inputs"]["base_ablation_contract"]))
    validate_contract(contract, base_contract)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_module = load_module(BASE_SCRIPT, "representation_ablation_e1_e4_base_103")
    memory_module = load_module(MEMORY_SCRIPT, "representation_ablation_e1_e4_memory_101")
    dba_module = load_module(DBA_SCRIPT, "representation_ablation_e1_e4_dba_102")
    topology_module = load_module(TOPOLOGY_SCRIPT, "representation_ablation_e1_e4_topology_104")
    data = load_inputs(
        contract,
        base_contract,
        base_module,
        memory_module,
        dba_module,
        topology_module,
    )
    representations, fit_audit, feature_manifest = build_representations(
        contract, base_contract, data, base_module, memory_module, dba_module
    )
    result_frames: list[pd.DataFrame] = []
    trace_frames: list[pd.DataFrame] = []
    for representation in representations.values():
        final_results, final_trace = evaluate_sequential_final(
            representation, data, contract, dba_module
        )
        topology_results, topology_trace = evaluate_fixed_topology(
            representation, data, contract, dba_module
        )
        result_frames.extend([final_results, topology_results])
        trace_frames.extend([final_trace, topology_trace])
    results = pd.concat(result_frames, ignore_index=True)
    traces = pd.concat(trace_frames, ignore_index=True)
    summary = summarize_results(results)
    bootstrap = bootstrap_intervals(results, summary, contract)
    paired = paired_bootstrap_differences(results, contract)
    identity = identity_memory_baselines(data, contract)
    identity_summary = identity_memory_summary(identity)
    pairs, response_summary, matched_topology = response_distance_analysis(
        representations, data, contract
    )
    rankings = action_rankings(results, contract)
    fit_manifest = {
        "experiment_id": contract["experiment_id"],
        "fit_policy": "development_reference_only_per_representation",
        "final_or_n3_outcomes_used_for_fit": False,
        "representations": {
            name: representation.fit_manifest for name, representation in representations.items()
        },
    }
    thresholds = pd.DataFrame(
        [
            {
                "representation": name,
                "fit_state_count": value.fit_manifest["fit_state_count"],
                "output_dimensions": value.fit_manifest["output_dimensions"],
                "coverage_quantile": value.fit_manifest["coverage_quantile"],
                "coverage_threshold": value.threshold,
            }
            for name, value in representations.items()
        ]
    )
    leakage = leakage_audit(
        results,
        traces,
        summary,
        representations,
        data,
        contract,
        feature_manifest,
    )
    reproduction, reproduction_detail = reproduction_audit(results, contract)
    manifest = input_manifest(contract_path, contract)

    results.to_csv(out_dir / "episode_representation_results.csv", index=False)
    summary.to_csv(out_dir / "representation_summary.csv", index=False)
    traces.to_csv(out_dir / "neighbor_trace.csv", index=False)
    rankings.to_csv(out_dir / "action_rankings.csv", index=False)
    bootstrap.to_csv(out_dir / "bootstrap_intervals.csv", index=False)
    paired.to_csv(out_dir / "paired_representation_differences.csv", index=False)
    identity.to_csv(out_dir / "identity_memory_results.csv", index=False)
    identity_summary.to_csv(out_dir / "identity_memory_summary.csv", index=False)
    pairs.to_csv(out_dir / "physical_action_response_pairs.csv", index=False)
    response_summary.to_csv(out_dir / "physical_action_response_summary.csv", index=False)
    matched_topology.to_csv(out_dir / "matched_query_topology_pairs.csv", index=False)
    feature_manifest.to_csv(out_dir / "feature_manifest.csv", index=False)
    fit_audit.to_csv(out_dir / "feature_fit_audit.csv", index=False)
    thresholds.to_csv(out_dir / "coverage_thresholds.csv", index=False)
    reproduction_detail.to_csv(out_dir / "reproduction_audit_detail.csv", index=False)
    write_json(out_dir / "fit_manifest.json", fit_manifest)
    write_json(out_dir / "leakage_audit.json", leakage)
    write_json(out_dir / "reproduction_audit.json", reproduction)
    write_json(out_dir / "input_manifest.json", manifest)
    analysis_summary = {
        "status": (
            "PASS" if leakage["status"] == "PASS" and reproduction["status"] == "PASS" else "FAIL"
        ),
        "offline_only": True,
        "archived_results_modified": False,
        "research_question": contract["research_question"],
        "evaluation_episode_counts": {
            evaluation: int(group["episode_id"].nunique())
            for evaluation, group in results.groupby("evaluation")
        },
        "representation_summary": summary.to_dict(orient="records"),
        "coverage_thresholds": thresholds.to_dict(orient="records"),
        "leakage_status": leakage["status"],
        "reproduction_status": reproduction["status"],
    }
    write_json(out_dir / "analysis_summary.json", analysis_summary)
    write_report(
        out_dir,
        contract,
        summary,
        thresholds,
        bootstrap,
        paired,
        identity_summary,
        response_summary,
        matched_topology,
        leakage,
        reproduction,
    )
    (out_dir / "REPRODUCE.md").write_text(
        "# Reprodukcija\n\n```bash\nmake representation-ablation-e1-e4\n"
        "make representation-ablation-e1-e4-local-gate\n```\n",
        encoding="utf-8",
    )
    write_checksums(out_dir)
    if analysis_summary["status"] != "PASS":
        raise SystemExit(2)
    return analysis_summary


def main() -> int:
    args = parse_args()
    result = analyze(args.contract.resolve(), args.out_dir.resolve())
    print(
        json.dumps(
            _json_safe(result),
            indent=2,
            sort_keys=True,
            default=_json_default,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
