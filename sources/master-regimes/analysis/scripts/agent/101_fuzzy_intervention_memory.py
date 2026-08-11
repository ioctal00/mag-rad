#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy.stats import spearmanr
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, ndcg_score
from sklearn.preprocessing import StandardScaler

from master_regimes.fuzzy_intervention_memory import (
    effective_sample_size,
    estimate_actions,
    fuzzy_transition_edges,
    weighted_location_scale,
)
from master_regimes.representation_audit import (
    fcm_metrics,
    fit_best_fcm,
    memberships_from_centers,
    seed_stability,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT = ROOT / "configs/models/fuzzy_intervention_memory_v1.yml"
DEFAULT_OUT = ROOT / "analysis/reports/fuzzy-intervention-memory-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and evaluate the local fuzzy intervention memory."
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path).resolve()


def canonical_json(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)) or value == "":
        return "{}"
    parsed = json.loads(value) if isinstance(value, str) else value
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def scenario_key(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["component_match_id"].astype(str)
        + "::"
        + frame["dataset_profile_id"].astype(str)
        + "::"
        + frame["param_json"].map(canonical_json)
    )


def _numeric(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce")


def _safe_share(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.where(denominator > 0.0)


def aggregate_edge_features(edges: pd.DataFrame) -> pd.DataFrame:
    if edges.empty:
        return pd.DataFrame(columns=["query_run_id"])
    rows: list[dict[str, Any]] = []
    for query_run_id, group in edges.groupby("query_run_id", sort=True):
        remote_rows = _numeric(group, "remote_rows")
        remote_bytes = _numeric(group, "remote_bytes_proxy")
        source_bps = _numeric(group, "query_window_source_tx_bps")
        available = group.get(
            "availability_status", pd.Series("", index=group.index)
        ).astype(str).eq("available")
        row_sum = remote_rows.sum(min_count=1)
        byte_sum = remote_bytes.sum(min_count=1)
        rows.append(
            {
                "query_run_id": str(query_run_id),
                "edge_count": len(group),
                "edge_remote_rows_sum": row_sum,
                "edge_remote_rows_max_share": (
                    remote_rows.max() / row_sum if pd.notna(row_sum) and row_sum > 0 else np.nan
                ),
                "edge_remote_bytes_sum": byte_sum,
                "edge_remote_bytes_max_share": (
                    remote_bytes.max() / byte_sum if pd.notna(byte_sum) and byte_sum > 0 else np.nan
                ),
                "edge_foreign_scan_time_ms_sum": _numeric(
                    group, "foreign_scan_time_ms_sum"
                ).sum(min_count=1),
                "edge_regional_plan_time_ms_sum": _numeric(
                    group, "regional_plan_time_ms_sum"
                ).sum(min_count=1),
                "edge_boundary_wait_ms_sum": _numeric(
                    group, "foreign_scan_minus_regional_time_ms_proxy"
                ).sum(min_count=1),
                "edge_estimated_fetch_cycles_sum": _numeric(
                    group, "estimated_fetch_cycles"
                ).sum(min_count=1),
                "edge_rtt_context_median_ms_mean": _numeric(
                    group, "rtt_context_median_ms"
                ).mean(),
                "edge_rtt_context_median_ms_max": _numeric(
                    group, "rtt_context_median_ms"
                ).max(),
                "edge_source_tx_bytes_sum": _numeric(
                    group, "query_window_source_tx_bytes"
                ).sum(min_count=1),
                "edge_source_tx_bps_mean": source_bps.mean(),
                "edge_source_tx_bps_min": source_bps.min(),
                "edge_qdisc_drops_sum": _numeric(
                    group, "query_window_qdisc_drops"
                ).sum(min_count=1),
                "edge_qdisc_overlimits_sum": _numeric(
                    group, "query_window_qdisc_overlimits"
                ).sum(min_count=1),
                "edge_tcp_retrans_sum": _numeric(
                    group, "tcp_retrans_delta_node_global"
                ).sum(min_count=1),
                "edge_available_share": float(available.mean()),
            }
        )
    return pd.DataFrame(rows)


def enrich_executions(index_dir: Path) -> pd.DataFrame:
    executions = pd.read_csv(index_dir / "execution_features.csv", low_memory=False)
    executions["query_run_id"] = executions["query_run_id"].astype(str)
    edges_path = index_dir / "remote_edge_observations.csv"
    edge_features = (
        aggregate_edge_features(pd.read_csv(edges_path, low_memory=False))
        if edges_path.exists()
        else pd.DataFrame(columns=["query_run_id"])
    )
    return executions.merge(
        edge_features,
        on="query_run_id",
        how="left",
        validate="one_to_one",
    )


def condition_summary(executions: pd.DataFrame, source_id: str) -> pd.DataFrame:
    local = executions.copy()
    local["base_scenario_id"] = scenario_key(local)
    local["scenario_id"] = source_id + "::" + local["base_scenario_id"]
    rows: list[dict[str, Any]] = []
    for condition_id, group in local.groupby("condition_id", sort=True):
        completed = group[group["execution_status"].astype(str).eq("completed")]
        started_at = _numeric(completed, "query_started_at_unix")
        finished_at = _numeric(completed, "query_finished_at_unix")
        signatures = sorted(
            {
                str(value)
                for value in group.get(
                    "result_multiset_sha256", pd.Series(dtype=str)
                )
                if pd.notna(value) and str(value).strip()
            }
        )
        first = group.iloc[0]
        rows.append(
            {
                "source_id": source_id,
                "condition_id": str(condition_id),
                "scenario_id": str(first["scenario_id"]),
                "base_scenario_id": str(first["base_scenario_id"]),
                "component_match_id": str(first["component_match_id"]),
                "logical_question_id": str(first["logical_question_id"]),
                "dataset_profile_id": str(first["dataset_profile_id"]),
                "template_id": str(first["template_id"]),
                "variant": "" if pd.isna(first["variant"]) else str(first["variant"]),
                "mitigation_action": (
                    ""
                    if pd.isna(first["mitigation_action"])
                    else str(first["mitigation_action"])
                ),
                "execution_count": len(group),
                "completed_count": len(completed),
                "elapsed_median": pd.to_numeric(
                    completed["elapsed_seconds"], errors="coerce"
                ).median(),
                "condition_started_at_unix": started_at.min(),
                "condition_finished_at_unix": finished_at.max(),
                "result_multiset_sha256": signatures[0] if len(signatures) == 1 else "",
                "signature_count": len(signatures),
            }
        )
    return pd.DataFrame(rows)


def build_gain_rows(
    conditions: pd.DataFrame,
    *,
    repetitions_per_condition: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scenario_id, group in conditions.groupby("scenario_id", sort=True):
        baseline = group[group["variant"].eq("stressed")]
        if len(baseline) != 1:
            continue
        before = baseline.iloc[0]
        for after in group[group["mitigation_action"].ne("")].to_dict(orient="records"):
            valid_time = (
                pd.notna(before["elapsed_median"])
                and pd.notna(after["elapsed_median"])
                and float(before["elapsed_median"]) > 0.0
                and float(after["elapsed_median"]) > 0.0
            )
            result_equal = bool(
                before["result_multiset_sha256"]
                and after["result_multiset_sha256"]
                and before["result_multiset_sha256"]
                == after["result_multiset_sha256"]
            )
            rows.append(
                {
                    "source_id": before["source_id"],
                    "scenario_id": scenario_id,
                    "base_scenario_id": before["base_scenario_id"],
                    "component_match_id": before["component_match_id"],
                    "logical_question_id": before["logical_question_id"],
                    "dataset_profile_id": before["dataset_profile_id"],
                    "baseline_condition_id": before["condition_id"],
                    "action_condition_id": after["condition_id"],
                    "mitigation_action": after["mitigation_action"],
                    "baseline_elapsed_median": before["elapsed_median"],
                    "action_elapsed_median": after["elapsed_median"],
                    "baseline_started_at_unix": before[
                        "condition_started_at_unix"
                    ],
                    "baseline_finished_at_unix": before[
                        "condition_finished_at_unix"
                    ],
                    "action_started_at_unix": after["condition_started_at_unix"],
                    "action_finished_at_unix": after[
                        "condition_finished_at_unix"
                    ],
                    "episode_available_at_unix": max(
                        float(before["condition_finished_at_unix"]),
                        float(after["condition_finished_at_unix"]),
                    ),
                    "target_log2_gain": (
                        math.log2(
                            float(before["elapsed_median"])
                            / float(after["elapsed_median"])
                        )
                        if valid_time
                        else np.nan
                    ),
                    "completed": int(before["completed_count"])
                    == repetitions_per_condition
                    and int(after["completed_count"])
                    == repetitions_per_condition,
                    "result_equal": result_equal,
                }
            )
    return pd.DataFrame(rows)


def condition_feature_medians(
    executions: pd.DataFrame,
    feature_names: list[str],
) -> pd.DataFrame:
    values = pd.DataFrame(
        {name: _numeric(executions, name) for name in feature_names},
        index=executions.index,
    )
    values["condition_id"] = executions["condition_id"].astype(str)
    return values.groupby("condition_id", sort=True)[feature_names].median()


def build_source_episodes(
    source: dict[str, Any],
    feature_names: list[str],
    repetitions_per_condition: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    source_id = str(source["id"])
    executions = enrich_executions(resolve_path(source["index_dir"]))
    conditions = condition_summary(executions, source_id)
    gains = build_gain_rows(
        conditions,
        repetitions_per_condition=repetitions_per_condition,
    )
    feature_medians = condition_feature_medians(executions, feature_names)
    before = feature_medians.add_prefix("before__")
    after = feature_medians.add_prefix("after__")
    episodes = gains.merge(
        before,
        left_on="baseline_condition_id",
        right_index=True,
        how="left",
        validate="many_to_one",
    ).merge(
        after,
        left_on="action_condition_id",
        right_index=True,
        how="left",
        validate="many_to_one",
    )
    executions = executions.copy()
    executions["source_id"] = source_id
    return episodes, executions


def transform_values(
    frame: pd.DataFrame,
    specifications: dict[str, Any],
    prefix: str,
) -> pd.DataFrame:
    transformed = pd.DataFrame(index=frame.index)
    for name, specification in specifications.items():
        values = pd.to_numeric(frame[f"{prefix}{name}"], errors="coerce")
        kind = str(specification["transform"])
        if kind == "identity":
            transformed[name] = values
        elif kind == "log1p":
            transformed[name] = np.log1p(values.clip(lower=0.0))
        elif kind == "signed_log1p":
            transformed[name] = np.sign(values) * np.log1p(np.abs(values))
        else:
            raise ValueError(f"Unsupported transform {kind!r} for {name}")
    return transformed


@dataclass
class StatePreprocessor:
    specifications: dict[str, Any]
    pca_components: int
    minimum_active_features: int
    active_features: list[str] | None = None
    imputer: SimpleImputer | None = None
    scaler: StandardScaler | None = None
    pca: PCA | None = None
    family_weights: np.ndarray | None = None
    selection_audit: pd.DataFrame | None = None

    def fit(self, frame: pd.DataFrame, prefix: str = "before__") -> np.ndarray:
        transformed = transform_values(frame, self.specifications, prefix)
        audit_rows: list[dict[str, Any]] = []
        for name in transformed:
            observed_count = int(transformed[name].notna().sum())
            distinct_count = int(transformed[name].nunique(dropna=True))
            if observed_count == 0:
                decision = "all_missing"
            elif distinct_count <= 1:
                decision = "constant"
            else:
                decision = "selected"
            audit_rows.append(
                {
                    "feature": name,
                    "family": str(self.specifications[name]["family"]),
                    "transform": str(self.specifications[name]["transform"]),
                    "reference_state_count": len(frame),
                    "observed_count": observed_count,
                    "missing_share": 1.0 - observed_count / len(frame),
                    "distinct_count": distinct_count,
                    "selected": decision == "selected",
                    "decision": decision,
                }
            )
        self.selection_audit = pd.DataFrame(audit_rows)
        active = [
            name
            for name in transformed
            if transformed[name].notna().any()
            and transformed[name].nunique(dropna=True) > 1
        ]
        if len(active) < self.minimum_active_features:
            raise ValueError(
                f"Only {len(active)} active state features, expected at least "
                f"{self.minimum_active_features}"
            )
        self.active_features = active
        self.imputer = SimpleImputer(strategy="median")
        self.scaler = StandardScaler()
        imputed = self.imputer.fit_transform(transformed[active])
        scaled = self.scaler.fit_transform(imputed)
        family_counts: dict[str, int] = {}
        for name in active:
            family = str(self.specifications[name]["family"])
            family_counts[family] = family_counts.get(family, 0) + 1
        self.family_weights = np.asarray(
            [
                1.0 / math.sqrt(family_counts[str(self.specifications[name]["family"])])
                for name in active
            ],
            dtype=float,
        )
        weighted = scaled * self.family_weights
        component_count = min(
            self.pca_components,
            len(frame) - 1,
            weighted.shape[1],
        )
        if component_count < 1:
            raise ValueError("Not enough states for PCA")
        self.pca = PCA(n_components=component_count, random_state=0)
        return self.pca.fit_transform(weighted)

    def transform(self, frame: pd.DataFrame, prefix: str = "before__") -> np.ndarray:
        if (
            self.active_features is None
            or self.imputer is None
            or self.scaler is None
            or self.pca is None
            or self.family_weights is None
        ):
            raise RuntimeError("StatePreprocessor is not fitted")
        transformed = transform_values(frame, self.specifications, prefix)
        imputed = self.imputer.transform(transformed[self.active_features])
        scaled = self.scaler.transform(imputed)
        return self.pca.transform(scaled * self.family_weights)


def panel_episodes(
    strict: pd.DataFrame,
    panel: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    components = set(str(value) for value in panel["component_match_ids"])
    expected_actions = set(str(value) for value in panel["actions"])
    selected = strict[strict["component_match_id"].astype(str).isin(components)].copy()
    coverage_rows: list[dict[str, Any]] = []
    accepted: list[str] = []
    for scenario_id, group in selected.groupby("scenario_id", sort=True):
        actual_actions = set(group["mitigation_action"].astype(str))
        status = (
            "complete_action_panel"
            if actual_actions == expected_actions
            else "incomplete_action_panel"
        )
        coverage_rows.append(
            {
                "scenario_id": scenario_id,
                "component_match_id": str(group["component_match_id"].iloc[0]),
                "action_count": len(actual_actions),
                "actions": "|".join(sorted(actual_actions)),
                "status": status,
            }
        )
        if status == "complete_action_panel":
            accepted.append(str(scenario_id))
    return (
        selected[selected["scenario_id"].astype(str).isin(accepted)].copy(),
        pd.DataFrame(coverage_rows),
    )


def _state_rows(episodes: pd.DataFrame) -> pd.DataFrame:
    before_columns = [name for name in episodes if name.startswith("before__")]
    states = episodes[["scenario_id", *before_columns]].drop_duplicates(
        "scenario_id"
    )
    if len(states) != episodes["scenario_id"].nunique():
        raise ValueError("A scenario has more than one pre-action state")
    return states.set_index("scenario_id", drop=False)


def _memory_k(training_scenario_count: int, memory: dict[str, Any]) -> int:
    maximum = max(
        2,
        training_scenario_count
        // int(memory["minimum_scenarios_per_context"]),
    )
    return min(int(memory["primary_k"]), maximum, training_scenario_count - 1)


def _knn_action_estimates(
    *,
    train_values: np.ndarray,
    test_value: np.ndarray,
    train_scenarios: list[str],
    train_episodes: pd.DataFrame,
    actions: list[str],
    neighbors: int,
    epsilon: float,
) -> dict[str, float]:
    distances = np.sqrt(np.sum((train_values - test_value[None, :]) ** 2, axis=1))
    order = np.argsort(distances)[: min(neighbors, len(distances))]
    state_weights = {
        train_scenarios[index]: 1.0 / (float(distances[index]) + epsilon)
        for index in order
    }
    predictions: dict[str, float] = {}
    for action in actions:
        rows = train_episodes[train_episodes["mitigation_action"].eq(action)]
        if rows.empty:
            predictions[action] = float("nan")
            continue
        weights = np.asarray(
            [state_weights.get(str(scenario_id), 0.0) for scenario_id in rows["scenario_id"]],
            dtype=float,
        )
        location, _ = weighted_location_scale(
            rows["target_log2_gain"].to_numpy(dtype=float),
            weights,
        )
        predictions[action] = location
    return predictions


def _kmeans_action_estimates(
    *,
    train_values: np.ndarray,
    test_value: np.ndarray,
    train_scenarios: list[str],
    train_episodes: pd.DataFrame,
    actions: list[str],
    k: int,
    seed: int,
) -> dict[str, float]:
    model = KMeans(n_clusters=k, n_init=30, random_state=seed)
    labels = model.fit_predict(train_values)
    test_label = int(model.predict(test_value[None, :])[0])
    label_by_scenario = dict(zip(train_scenarios, labels, strict=True))
    global_median = float(train_episodes["target_log2_gain"].median())
    action_medians = train_episodes.groupby("mitigation_action")[
        "target_log2_gain"
    ].median()
    predictions: dict[str, float] = {}
    for action in actions:
        rows = train_episodes[train_episodes["mitigation_action"].eq(action)]
        local = rows[
            rows["scenario_id"].map(label_by_scenario).eq(test_label)
        ]
        predictions[action] = float(
            local["target_log2_gain"].mean()
            if not local.empty
            else action_medians.get(action, global_median)
        )
    return predictions


def ranking_metrics(frame: pd.DataFrame, prediction: str) -> dict[str, float]:
    pair_correct = 0
    pair_total = 0
    top_correct = 0
    regrets: list[float] = []
    ndcgs: list[float] = []
    for _, group in frame.groupby("scenario_id", sort=True):
        actual = group["target_log2_gain"].to_numpy(dtype=float)
        predicted = group[prediction].to_numpy(dtype=float)
        top_correct += int(np.argmax(actual) == np.argmax(predicted))
        regrets.append(float(np.max(actual) - actual[np.argmax(predicted)]))
        shifted = actual - min(0.0, float(np.min(actual)))
        ndcgs.append(float(ndcg_score([shifted], [predicted], k=len(group))))
        for left in range(len(group)):
            for right in range(left + 1, len(group)):
                actual_order = np.sign(actual[left] - actual[right])
                predicted_order = np.sign(predicted[left] - predicted[right])
                pair_total += 1
                pair_correct += int(actual_order == predicted_order)
    scenario_count = frame["scenario_id"].nunique()
    rho = (
        spearmanr(frame["target_log2_gain"], frame[prediction]).statistic
        if frame[prediction].nunique() > 1
        else 0.0
    )
    return {
        "mae": float(mean_absolute_error(frame["target_log2_gain"], frame[prediction])),
        "spearman": float(rho) if not np.isnan(rho) else 0.0,
        "pairwise_accuracy": pair_correct / pair_total if pair_total else 0.0,
        "top1_accuracy": top_correct / scenario_count if scenario_count else 0.0,
        "ndcg": float(np.mean(ndcgs)),
        "mean_regret": float(np.mean(regrets)),
        "median_regret": float(np.median(regrets)),
    }


def scenario_metrics(
    frame: pd.DataFrame,
    prediction: str,
    model: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scenario_id, group in frame.groupby("scenario_id", sort=True):
        actual = group["target_log2_gain"].to_numpy(dtype=float)
        predicted = group[prediction].to_numpy(dtype=float)
        correct = 0
        total = 0
        for left in range(len(group)):
            for right in range(left + 1, len(group)):
                total += 1
                correct += int(
                    np.sign(actual[left] - actual[right])
                    == np.sign(predicted[left] - predicted[right])
                )
        rows.append(
            {
                "model": model,
                "scenario_id": scenario_id,
                "pairwise_accuracy": correct / total if total else 0.0,
                "top1_correct": int(np.argmax(actual) == np.argmax(predicted)),
                "regret": float(np.max(actual) - actual[np.argmax(predicted)]),
            }
        )
    return pd.DataFrame(rows)


def count_rank_reversals(episodes: pd.DataFrame) -> tuple[int, int]:
    rankings = episodes.groupby("scenario_id").apply(
        lambda group: ">".join(
            group.sort_values("target_log2_gain", ascending=False)["mitigation_action"]
        ),
        include_groups=False,
    )
    actions = sorted(episodes["mitigation_action"].unique())
    reversals = 0
    for left_index, left in enumerate(actions):
        for right in actions[left_index + 1 :]:
            signs: set[int] = set()
            for _, group in episodes.groupby("scenario_id", sort=True):
                gains = group.set_index("mitigation_action")["target_log2_gain"]
                if left in gains and right in gains:
                    sign = int(np.sign(float(gains[left]) - float(gains[right])))
                    if sign:
                        signs.add(sign)
            reversals += int(signs == {-1, 1})
    return int(rankings.nunique()), reversals


def evaluate_panel(
    episodes: pd.DataFrame,
    *,
    panel_name: str,
    actions: list[str],
    specifications: dict[str, Any],
    state_contract: dict[str, Any],
    memory: dict[str, Any],
    random_seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    states = _state_rows(episodes)
    output_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for held_scenario in sorted(states.index.astype(str)):
        train_state_frame = states[states.index.astype(str) != held_scenario].copy()
        test_state_frame = states[states.index.astype(str) == held_scenario].copy()
        train_episodes = episodes[episodes["scenario_id"].ne(held_scenario)].copy()
        test_episodes = episodes[episodes["scenario_id"].eq(held_scenario)].copy()
        processor = StatePreprocessor(
            specifications=specifications,
            pca_components=int(state_contract["pca_components"]),
            minimum_active_features=int(state_contract["minimum_active_features"]),
        )
        train_values = processor.fit(train_state_frame)
        test_value = processor.transform(test_state_frame)[0]
        train_scenarios = train_state_frame["scenario_id"].astype(str).tolist()
        k = _memory_k(len(train_scenarios), memory)
        fcm, fits = fit_best_fcm(
            train_values,
            k=k,
            seeds=[int(value) for value in memory["seeds"]],
            fuzzifier=float(memory["fuzzifier"]),
        )
        test_membership, test_distances = memberships_from_centers(
            test_value[None, :],
            fcm.centers,
            fuzzifier=float(memory["fuzzifier"]),
        )
        membership_by_scenario = {
            scenario: fcm.memberships[index]
            for index, scenario in enumerate(train_scenarios)
        }
        historical_memberships = np.vstack(
            [membership_by_scenario[str(value)] for value in train_episodes["scenario_id"]]
        )
        fcm_estimates = estimate_actions(
            query_membership=test_membership[0],
            historical_memberships=historical_memberships,
            historical_actions=train_episodes["mitigation_action"].astype(str),
            historical_gains=train_episodes["target_log2_gain"].to_numpy(dtype=float),
            candidate_actions=actions,
            fuzzifier=float(memory["fuzzifier"]),
            minimum_observed_support=int(memory["minimum_observed_support"]),
            minimum_effective_support=float(memory["minimum_effective_support"]),
        )
        fcm_by_action = {estimate.action: estimate for estimate in fcm_estimates}
        global_median = float(train_episodes["target_log2_gain"].median())
        action_median = train_episodes.groupby("mitigation_action")[
            "target_log2_gain"
        ].median()
        knn = _knn_action_estimates(
            train_values=train_values,
            test_value=test_value,
            train_scenarios=train_scenarios,
            train_episodes=train_episodes,
            actions=actions,
            neighbors=int(memory["knn_neighbors"]),
            epsilon=float(memory["distance_epsilon"]),
        )
        hard = _kmeans_action_estimates(
            train_values=train_values,
            test_value=test_value,
            train_scenarios=train_scenarios,
            train_episodes=train_episodes,
            actions=actions,
            k=k,
            seed=random_seed,
        )
        for row in test_episodes.to_dict(orient="records"):
            action = str(row["mitigation_action"])
            estimate = fcm_by_action[action]
            output_rows.append(
                {
                    **row,
                    "panel": panel_name,
                    "prediction_global_median": global_median,
                    "prediction_action_median": float(
                        action_median.get(action, global_median)
                    ),
                    "prediction_knn": float(knn[action]),
                    "prediction_kmeans_hard_memory": float(hard[action]),
                    "prediction_fcm_soft_memory": estimate.prediction,
                    "fcm_weighted_stddev": estimate.weighted_stddev,
                    "fcm_effective_support": estimate.effective_support,
                    "fcm_observed_support": estimate.observed_support,
                    "fcm_prediction_status": estimate.status,
                    "fcm_nearest_center_distance": float(np.min(test_distances[0])),
                    "fcm_max_membership": float(np.max(test_membership[0])),
                    "fcm_k": k,
                }
            )
        stability = seed_stability(fits)
        fold_rows.append(
            {
                "panel": panel_name,
                "held_scenario": held_scenario,
                "training_scenario_count": len(train_scenarios),
                "active_feature_count": len(processor.active_features or []),
                "pca_component_count": int(train_values.shape[1]),
                "pca_explained_variance_share": float(
                    np.sum(processor.pca.explained_variance_ratio_)
                ),
                "fcm_k": k,
                "fcm_objective": fcm.objective,
                **stability,
            }
        )

    predictions = pd.DataFrame(output_rows)
    metric_rows: list[dict[str, Any]] = []
    scenario_rows: list[pd.DataFrame] = []
    for model in (
        "global_median",
        "action_median",
        "knn",
        "kmeans_hard_memory",
        "fcm_soft_memory",
    ):
        prediction = f"prediction_{model}"
        metric_rows.append(
            {"panel": panel_name, "model": model, **ranking_metrics(predictions, prediction)}
        )
        scenario_rows.append(scenario_metrics(predictions, prediction, model))
    detailed_scenarios = (
        pd.concat(scenario_rows, ignore_index=True)
        .assign(panel=panel_name)
        .merge(
            pd.DataFrame(fold_rows),
            left_on=["panel", "scenario_id"],
            right_on=["panel", "held_scenario"],
            how="left",
            validate="many_to_one",
        )
    )
    return predictions, pd.DataFrame(metric_rows), detailed_scenarios


PREQUENTIAL_MODELS = (
    "action_median",
    "knn",
    "kmeans_hard_memory",
    "fcm_soft_memory",
)


def evaluate_prequential_panel(
    episodes: pd.DataFrame,
    *,
    panel_name: str,
    actions: list[str],
    specifications: dict[str, Any],
    state_contract: dict[str, Any],
    memory: dict[str, Any],
    random_seed: int,
) -> pd.DataFrame:
    """Evaluate local memory using only fully revealed earlier scenarios."""
    states = _state_rows(episodes)
    availability = (
        episodes.groupby("scenario_id", sort=True)["episode_available_at_unix"]
        .max()
        .sort_values(kind="stable")
    )
    ordered = sorted(
        availability.items(),
        key=lambda item: (float(item[1]), str(item[0])),
    )
    output_rows: list[dict[str, Any]] = []
    for step, (held_scenario, revealed_at) in enumerate(ordered, start=1):
        prior_scenarios = [
            str(scenario_id)
            for scenario_id, timestamp in ordered
            if float(timestamp) < float(revealed_at)
        ]
        train_state_frame = states[
            states.index.astype(str).isin(prior_scenarios)
        ].copy()
        test_state_frame = states[
            states.index.astype(str) == str(held_scenario)
        ].copy()
        train_episodes = episodes[
            episodes["scenario_id"].astype(str).isin(prior_scenarios)
        ].copy()
        test_episodes = episodes[
            episodes["scenario_id"].astype(str).eq(str(held_scenario))
        ].copy()
        predictions = {
            model: {action: float("nan") for action in actions}
            for model in PREQUENTIAL_MODELS
        }
        statuses = {model: "cold_start" for model in PREQUENTIAL_MODELS}
        confidences = {model: float("nan") for model in PREQUENTIAL_MODELS}
        fcm_by_action: dict[str, Any] = {}
        fcm_nearest_distance = float("nan")
        fcm_max_membership = float("nan")
        fcm_k = 0
        active_feature_count = 0
        pca_component_count = 0
        knn_neighbor_evidence_json = "[]"

        if prior_scenarios:
            action_medians = train_episodes.groupby("mitigation_action")[
                "target_log2_gain"
            ].median()
            if all(action in action_medians.index for action in actions):
                predictions["action_median"] = {
                    action: float(action_medians[action]) for action in actions
                }
                statuses["action_median"] = "available"
                confidences["action_median"] = float(len(prior_scenarios))

        if len(prior_scenarios) >= 2:
            try:
                processor = StatePreprocessor(
                    specifications=specifications,
                    pca_components=int(state_contract["pca_components"]),
                    minimum_active_features=int(
                        state_contract["minimum_active_features"]
                    ),
                )
                train_values = processor.fit(train_state_frame)
                test_value = processor.transform(test_state_frame)[0]
                train_scenarios = train_state_frame["scenario_id"].astype(str).tolist()
                active_feature_count = len(processor.active_features or [])
                pca_component_count = int(train_values.shape[1])
                distances = np.sqrt(
                    np.sum((train_values - test_value[None, :]) ** 2, axis=1)
                )
                predictions["knn"] = _knn_action_estimates(
                    train_values=train_values,
                    test_value=test_value,
                    train_scenarios=train_scenarios,
                    train_episodes=train_episodes,
                    actions=actions,
                    neighbors=int(memory["knn_neighbors"]),
                    epsilon=float(memory["distance_epsilon"]),
                )
                statuses["knn"] = (
                    "available"
                    if all(
                        np.isfinite(predictions["knn"][action])
                        for action in actions
                    )
                    else "insufficient_local_evidence"
                )
                confidences["knn"] = 1.0 / (
                    float(np.min(distances)) + float(memory["distance_epsilon"])
                )
                neighbor_order = np.argsort(distances)[
                    : min(int(memory["knn_neighbors"]), len(distances))
                ]
                neighbor_evidence: list[dict[str, Any]] = []
                for index in neighbor_order:
                    scenario_id = str(train_scenarios[index])
                    gains = train_episodes[
                        train_episodes["scenario_id"].astype(str).eq(scenario_id)
                    ].set_index("mitigation_action")["target_log2_gain"]
                    neighbor_evidence.append(
                        {
                            "scenario_id": scenario_id,
                            "distance": float(distances[index]),
                            "weight": 1.0
                            / (
                                float(distances[index])
                                + float(memory["distance_epsilon"])
                            ),
                            "action_gains": {
                                action: float(gains[action])
                                for action in actions
                                if action in gains.index
                            },
                        }
                    )
                knn_neighbor_evidence_json = json.dumps(
                    neighbor_evidence,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                fcm_k = _memory_k(len(train_scenarios), memory)
                if fcm_k >= 2:
                    predictions["kmeans_hard_memory"] = _kmeans_action_estimates(
                        train_values=train_values,
                        test_value=test_value,
                        train_scenarios=train_scenarios,
                        train_episodes=train_episodes,
                        actions=actions,
                        k=fcm_k,
                        seed=random_seed,
                    )
                    statuses["kmeans_hard_memory"] = "available"
                    confidences["kmeans_hard_memory"] = float(
                        len(prior_scenarios)
                    )
                    fcm, _ = fit_best_fcm(
                        train_values,
                        k=fcm_k,
                        seeds=[int(value) for value in memory["seeds"]],
                        fuzzifier=float(memory["fuzzifier"]),
                    )
                    test_membership, test_distances = memberships_from_centers(
                        test_value[None, :],
                        fcm.centers,
                        fuzzifier=float(memory["fuzzifier"]),
                    )
                    membership_by_scenario = {
                        scenario: fcm.memberships[index]
                        for index, scenario in enumerate(train_scenarios)
                    }
                    historical_memberships = np.vstack(
                        [
                            membership_by_scenario[str(value)]
                            for value in train_episodes["scenario_id"]
                        ]
                    )
                    estimates = estimate_actions(
                        query_membership=test_membership[0],
                        historical_memberships=historical_memberships,
                        historical_actions=train_episodes[
                            "mitigation_action"
                        ].astype(str),
                        historical_gains=train_episodes[
                            "target_log2_gain"
                        ].to_numpy(dtype=float),
                        candidate_actions=actions,
                        fuzzifier=float(memory["fuzzifier"]),
                        minimum_observed_support=int(
                            memory["minimum_observed_support"]
                        ),
                        minimum_effective_support=float(
                            memory["minimum_effective_support"]
                        ),
                    )
                    fcm_by_action = {
                        estimate.action: estimate for estimate in estimates
                    }
                    for action, estimate in fcm_by_action.items():
                        predictions["fcm_soft_memory"][action] = estimate.prediction
                    statuses["fcm_soft_memory"] = (
                        "available"
                        if all(
                            estimate.status == "available"
                            for estimate in estimates
                        )
                        else "insufficient_local_evidence"
                    )
                    fcm_nearest_distance = float(np.min(test_distances[0]))
                    fcm_max_membership = float(np.max(test_membership[0]))
                    effective = min(
                        estimate.effective_support for estimate in estimates
                    )
                    confidences["fcm_soft_memory"] = effective / (
                        1.0 + fcm_nearest_distance
                    )
            except (ValueError, FloatingPointError):
                for model in ("knn", "kmeans_hard_memory", "fcm_soft_memory"):
                    statuses[model] = "insufficient_state_variation"

        for row in test_episodes.to_dict(orient="records"):
            action = str(row["mitigation_action"])
            estimate = fcm_by_action.get(action)
            output_rows.append(
                {
                    **row,
                    "panel": panel_name,
                    "prequential_step": step,
                    "scenario_available_at_unix": float(revealed_at),
                    "history_scenario_count": len(prior_scenarios),
                    "history_episode_count": len(train_episodes),
                    **{
                        f"prediction_{model}": predictions[model][action]
                        for model in PREQUENTIAL_MODELS
                    },
                    **{
                        f"prequential_status_{model}": statuses[model]
                        for model in PREQUENTIAL_MODELS
                    },
                    **{
                        f"prequential_confidence_{model}": confidences[model]
                        for model in PREQUENTIAL_MODELS
                    },
                    "fcm_weighted_stddev": (
                        estimate.weighted_stddev if estimate else float("nan")
                    ),
                    "fcm_effective_support": (
                        estimate.effective_support if estimate else 0.0
                    ),
                    "fcm_observed_support": (
                        estimate.observed_support if estimate else 0
                    ),
                    "fcm_action_status": (
                        estimate.status if estimate else statuses["fcm_soft_memory"]
                    ),
                    "fcm_nearest_center_distance": fcm_nearest_distance,
                    "fcm_max_membership": fcm_max_membership,
                    "fcm_k": fcm_k,
                    "knn_neighbor_evidence_json": knn_neighbor_evidence_json,
                    "active_feature_count": active_feature_count,
                    "pca_component_count": pca_component_count,
                }
            )
    return pd.DataFrame(output_rows)


def _available_prequential_scenarios(
    predictions: pd.DataFrame,
    model: str,
) -> pd.DataFrame:
    prediction = f"prediction_{model}"
    status = f"prequential_status_{model}"
    accepted = [
        str(scenario_id)
        for scenario_id, group in predictions.groupby("scenario_id", sort=True)
        if group[status].eq("available").all()
        and group[prediction].notna().all()
    ]
    return predictions[predictions["scenario_id"].astype(str).isin(accepted)].copy()


def summarize_prequential_predictions(
    predictions: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict[str, Any]] = []
    learning_rows: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    total_scenarios = int(predictions["scenario_id"].nunique())
    maximum_step = int(predictions["prequential_step"].max())
    available_by_model = {
        model: _available_prequential_scenarios(predictions, model)
        for model in PREQUENTIAL_MODELS
    }
    fcm_scenario_ids = set(
        available_by_model["fcm_soft_memory"]["scenario_id"].astype(str).unique()
    )

    def append_summary(
        *,
        model: str,
        available: pd.DataFrame,
        evaluation_scope: str,
        evaluation_scenario_count: int,
        include_startup: bool,
    ) -> None:
        prediction = f"prediction_{model}"
        first_step = (
            int(available["prequential_step"].min()) if not available.empty else None
        )
        first_history = (
            int(available["history_scenario_count"].min())
            if not available.empty
            else None
        )
        metrics = (
            ranking_metrics(available, prediction)
            if not available.empty
            else {
                "mae": float("nan"),
                "spearman": float("nan"),
                "pairwise_accuracy": float("nan"),
                "top1_accuracy": float("nan"),
                "ndcg": float("nan"),
                "mean_regret": float("nan"),
                "median_regret": float("nan"),
            }
        )
        predicted_count = int(available["scenario_id"].nunique())
        status = f"prequential_status_{model}"
        cold_start_count = sum(
            group[status].eq("cold_start").all()
            for _, group in predictions.groupby("scenario_id", sort=True)
        )
        summary_rows.append(
            {
                "panel": str(predictions["panel"].iloc[0]),
                "model": model,
                "evaluation_scope": evaluation_scope,
                "total_scenario_count": total_scenarios,
                "evaluation_scenario_count": evaluation_scenario_count,
                "predicted_scenario_count": predicted_count,
                "coverage": (
                    predicted_count / evaluation_scenario_count
                    if evaluation_scenario_count
                    else float("nan")
                ),
                "panel_coverage": predicted_count / total_scenarios,
                "cold_start_scenario_count": (
                    cold_start_count if include_startup else None
                ),
                "initial_abstention_scenario_count": (
                    first_step - 1
                    if include_startup and first_step is not None
                    else total_scenarios
                    if include_startup
                    else None
                ),
                "abstained_scenario_count": (
                    total_scenarios - predicted_count if include_startup else None
                ),
                "first_prediction_step": first_step if include_startup else None,
                "first_prediction_history_count": (
                    first_history if include_startup else None
                ),
                **metrics,
            }
        )

    for model in PREQUENTIAL_MODELS:
        available = available_by_model[model]
        prediction = f"prediction_{model}"
        append_summary(
            model=model,
            available=available,
            evaluation_scope="own_available",
            evaluation_scenario_count=total_scenarios,
            include_startup=True,
        )
        matched = available[
            available["scenario_id"].astype(str).isin(fcm_scenario_ids)
        ].copy()
        append_summary(
            model=model,
            available=matched,
            evaluation_scope="fcm_matched",
            evaluation_scenario_count=len(fcm_scenario_ids),
            include_startup=False,
        )
        for step in range(1, maximum_step + 1):
            prefix = available[available["prequential_step"].le(step)]
            prefix_count = int(prefix["scenario_id"].nunique())
            prefix_metrics = (
                ranking_metrics(prefix, prediction) if not prefix.empty else {}
            )
            learning_rows.append(
                {
                    "panel": str(predictions["panel"].iloc[0]),
                    "model": model,
                    "prequential_step": step,
                    "revealed_scenario_count": step,
                    "predicted_scenario_count": prefix_count,
                    "coverage_to_date": prefix_count / step,
                    "coverage_of_panel": prefix_count / total_scenarios,
                    **prefix_metrics,
                }
            )
        if available.empty:
            continue
        confidence = available.groupby("scenario_id", sort=True).agg(
            confidence=(f"prequential_confidence_{model}", "min")
        )
        confidence = confidence.sort_values("confidence", ascending=False)
        for selected_count in range(1, len(confidence) + 1):
            selected_ids = set(confidence.index[:selected_count])
            selected = available[available["scenario_id"].isin(selected_ids)]
            quality_rows.append(
                {
                    "panel": str(predictions["panel"].iloc[0]),
                    "model": model,
                    "selected_scenario_count": selected_count,
                    "coverage_of_available": selected_count / len(confidence),
                    "coverage_of_panel": selected_count / total_scenarios,
                    "minimum_confidence": float(
                        confidence.iloc[selected_count - 1]["confidence"]
                    ),
                    **ranking_metrics(selected, prediction),
                }
            )
    return (
        pd.DataFrame(summary_rows),
        pd.DataFrame(learning_rows),
        pd.DataFrame(quality_rows),
    )


def bootstrap_model_difference(
    scenario_frame: pd.DataFrame,
    *,
    candidate: str,
    baseline: str,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    candidate_rows = scenario_frame[scenario_frame["model"].eq(candidate)].set_index(
        "scenario_id"
    )
    baseline_rows = scenario_frame[scenario_frame["model"].eq(baseline)].set_index(
        "scenario_id"
    )
    aligned = candidate_rows[["pairwise_accuracy", "regret"]].join(
        baseline_rows[["pairwise_accuracy", "regret"]],
        lsuffix="_candidate",
        rsuffix="_baseline",
        how="inner",
        validate="one_to_one",
    )
    pair_delta = (
        aligned["pairwise_accuracy_candidate"]
        - aligned["pairwise_accuracy_baseline"]
    ).to_numpy(dtype=float)
    regret_delta = (
        aligned["regret_candidate"] - aligned["regret_baseline"]
    ).to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(aligned), size=(samples, len(aligned)))
    return {
        "candidate": candidate,
        "baseline": baseline,
        "scenario_count": len(aligned),
        "pairwise_delta_mean": float(pair_delta.mean()),
        "pairwise_delta_ci95": [
            float(value)
            for value in np.quantile(pair_delta[indices].mean(axis=1), [0.025, 0.975])
        ],
        "regret_delta_mean": float(regret_delta.mean()),
        "regret_delta_ci95": [
            float(value)
            for value in np.quantile(regret_delta[indices].mean(axis=1), [0.025, 0.975])
        ],
    }


def selective_coverage_curve(predictions: pd.DataFrame) -> pd.DataFrame:
    confidence = predictions.groupby("scenario_id", sort=True).agg(
        minimum_effective_support=("fcm_effective_support", "min"),
        nearest_center_distance=("fcm_nearest_center_distance", "first"),
    )
    confidence["confidence"] = confidence["minimum_effective_support"] / (
        1.0 + confidence["nearest_center_distance"]
    )
    ordered = confidence.sort_values("confidence", ascending=False)
    rows: list[dict[str, Any]] = []
    for scenario_count in range(1, len(ordered) + 1):
        selected_ids = set(ordered.index[:scenario_count])
        selected = predictions[predictions["scenario_id"].isin(selected_ids)]
        metrics = ranking_metrics(selected, "prediction_fcm_soft_memory")
        rows.append(
            {
                "scenario_count": scenario_count,
                "coverage": scenario_count / len(ordered),
                "minimum_confidence": float(ordered.iloc[scenario_count - 1]["confidence"]),
                **metrics,
            }
        )
    return pd.DataFrame(rows)


def transformed_episode_responses(
    episodes: pd.DataFrame,
    executions: pd.DataFrame,
    specifications: dict[str, Any],
    *,
    scale_floor: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    run_input = pd.DataFrame(
        {
            f"before__{name}": _numeric(executions, name)
            for name in specifications
        },
        index=executions.index,
    )
    transformed_runs = transform_values(run_input, specifications, "before__")
    condition_key = (
        executions["source_id"].astype(str)
        + "::"
        + executions["condition_id"].astype(str)
    )
    condition_medians = transformed_runs.groupby(condition_key).transform("median")
    residuals = transformed_runs - condition_medians
    scale_rows: list[dict[str, Any]] = []
    scales: dict[str, float] = {}
    for name in specifications:
        values = residuals[name].dropna().to_numpy(dtype=float)
        if values.size:
            center = float(np.median(values))
            raw_scale = float(1.4826 * np.median(np.abs(values - center)))
        else:
            raw_scale = float("nan")
        scale = max(raw_scale if np.isfinite(raw_scale) else 0.0, scale_floor)
        scales[name] = scale
        scale_rows.append(
            {
                "feature": name,
                "family": str(specifications[name]["family"]),
                "transform": str(specifications[name]["transform"]),
                "raw_null_scale": raw_scale,
                "applied_null_scale": scale,
                "floor_applied": not np.isfinite(raw_scale) or raw_scale < scale_floor,
            }
        )
    before = transform_values(episodes, specifications, "before__")
    after = transform_values(episodes, specifications, "after__")
    response = episodes[
        [
            "source_id",
            "scenario_id",
            "component_match_id",
            "mitigation_action",
            "target_log2_gain",
        ]
    ].copy()
    for name in specifications:
        response[f"response__{name}"] = (before[name] - after[name]) / scales[name]
    return response, pd.DataFrame(scale_rows)


def final_panel_graph(
    episodes: pd.DataFrame,
    *,
    panel_name: str,
    specifications: dict[str, Any],
    state_contract: dict[str, Any],
    memory: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    states = _state_rows(episodes)
    if len(states) < 3:
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            {"panel": panel_name, "status": "insufficient_states"},
        )
    processor = StatePreprocessor(
        specifications=specifications,
        pca_components=int(state_contract["pca_components"]),
        minimum_active_features=int(state_contract["minimum_active_features"]),
    )
    before_values = processor.fit(states)
    k = _memory_k(len(states), memory)
    fit, fits = fit_best_fcm(
        before_values,
        k=k,
        seeds=[int(value) for value in memory["seeds"]],
        fuzzifier=float(memory["fuzzifier"]),
    )
    after_values = processor.transform(episodes, prefix="after__")
    after_memberships, after_distances = memberships_from_centers(
        after_values,
        fit.centers,
        fuzzifier=float(memory["fuzzifier"]),
    )
    before_by_scenario = {
        scenario: fit.memberships[index]
        for index, scenario in enumerate(states["scenario_id"].astype(str))
    }
    before_memberships = np.vstack(
        [before_by_scenario[str(value)] for value in episodes["scenario_id"]]
    )
    edges = fuzzy_transition_edges(
        before_memberships=before_memberships,
        after_memberships=after_memberships,
        actions=episodes["mitigation_action"].astype(str),
        gains=episodes["target_log2_gain"].to_numpy(dtype=float),
        fuzzifier=float(memory["fuzzifier"]),
    ).assign(panel=panel_name)
    membership_rows: list[dict[str, Any]] = []
    for index, row in episodes.reset_index(drop=True).iterrows():
        payload: dict[str, Any] = {
            "panel": panel_name,
            "scenario_id": row["scenario_id"],
            "mitigation_action": row["mitigation_action"],
            "after_nearest_center_distance": float(np.min(after_distances[index])),
        }
        for context in range(k):
            payload[f"before_context_{context}"] = before_memberships[index, context]
            payload[f"after_context_{context}"] = after_memberships[index, context]
        membership_rows.append(payload)
    memberships = pd.DataFrame(membership_rows)
    active_rows = pd.DataFrame(
        [
            {
                "panel": panel_name,
                "feature": name,
                "family": str(specifications[name]["family"]),
            }
            for name in processor.active_features or []
        ]
    )
    selection_audit = (
        processor.selection_audit.assign(panel=panel_name)
        if processor.selection_audit is not None
        else pd.DataFrame()
    )
    diagnostics = {
        "panel": panel_name,
        "status": "available",
        "scenario_count": len(states),
        "action_count": int(episodes["mitigation_action"].nunique()),
        "k": k,
        "active_feature_count": len(processor.active_features or []),
        "pca_component_count": int(before_values.shape[1]),
        "pca_explained_variance_share": float(
            np.sum(processor.pca.explained_variance_ratio_)
        ),
        **fcm_metrics(before_values, fit),
        **seed_stability(fits),
    }
    return memberships, edges, active_rows, selection_audit, diagnostics


def response_by_transition(
    response: pd.DataFrame,
    memberships: pd.DataFrame,
    *,
    fuzzifier: float,
) -> pd.DataFrame:
    if memberships.empty:
        return pd.DataFrame()
    joined = memberships.merge(
        response,
        on=["scenario_id", "mitigation_action"],
        how="inner",
        validate="one_to_one",
    )
    before_columns = sorted(
        name for name in joined if name.startswith("before_context_")
    )
    after_columns = sorted(
        name for name in joined if name.startswith("after_context_")
    )
    response_columns = sorted(name for name in joined if name.startswith("response__"))
    rows: list[dict[str, Any]] = []
    for action, action_rows in joined.groupby("mitigation_action", sort=True):
        for source, before_name in enumerate(before_columns):
            for destination, after_name in enumerate(after_columns):
                weights = (
                    action_rows[before_name].to_numpy(dtype=float) ** fuzzifier
                ) * (action_rows[after_name].to_numpy(dtype=float) ** fuzzifier)
                if float(np.sum(weights)) <= 0.0:
                    continue
                for response_name in response_columns:
                    location, scale = weighted_location_scale(
                        action_rows[response_name].to_numpy(dtype=float),
                        weights,
                    )
                    rows.append(
                        {
                            "action": action,
                            "source_context": source,
                            "destination_context": destination,
                            "response_feature": response_name.removeprefix("response__"),
                            "response_weighted_mean": location,
                            "response_weighted_stddev": scale,
                            "effective_support": effective_sample_size(weights),
                        }
                    )
    return pd.DataFrame(rows)


def write_readme(
    out_dir: Path,
    summary: dict[str, Any],
    panel_summary: pd.DataFrame,
    metrics: pd.DataFrame,
    prequential_summary: pd.DataFrame,
) -> None:
    def markdown_table(frame: pd.DataFrame, *, decimals: int | None = None) -> str:
        if frame.empty:
            return "Nema redova."
        values = frame.copy()
        if decimals is not None:
            for column in values.select_dtypes(include=[np.number]).columns:
                values[column] = values[column].map(
                    lambda value: f"{value:.{decimals}f}" if pd.notna(value) else ""
                )
        headers = [str(value) for value in values.columns]
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        lines.extend(
            "| " + " | ".join(str(value) for value in row) + " |"
            for row in values.itertuples(index=False, name=None)
        )
        return "\n".join(lines)

    metric_table = (
        markdown_table(metrics, decimals=4)
        if not metrics.empty
        else "Nema evaluabilnih panela."
    )
    panel_table = markdown_table(panel_summary)
    prequential_table = (
        markdown_table(prequential_summary, decimals=4)
        if not prequential_summary.empty
        else "Nema evaluabilnih prequential panela."
    )
    gate = summary["gate"]
    if gate == "GO":
        decision = (
            "Fuzzy lokalna memorija prolazi unaprijed definisani gate nad "
            "primarnim panelom."
        )
    elif gate == "PANEL_EXPANSION_REQUIRED":
        decision = (
            "Implementacijski ugovor je provjerljiv, ali primarni panel nema "
            "dovoljno scenarija za modelski gate. Potrebno je ciljano proširenje "
            "istog action seta."
        )
    else:
        decision = (
            "Primarni panel ima dovoljan obim, ali fuzzy memorija nije zadovoljila "
            "prediktivni gate prema jednostavnim baselineima."
        )
    readme = f"""# Lokalno adaptivna fuzzy memorija intervencija

## Odluka

**{gate}**

{decision}

FCM u ovom eksperimentu ne imenuje fizičke pritiske. Koristi se samo kao meki
indeks početnih post-execution stanja. Procjena se daje isključivo za akcije
opažene u historijskim epizodama sa dovoljnom lokalnom podrškom.

## Jedinica analize

Jedan red predstavlja scenario-akcija epizodu. Tri fizička ponavljanja svakog
uslova agregiraju se medijanom. Target je:

```text
log2(median(T_baseline) / median(T_action))
```

Before-state koristi samo dokaz stressed izvršenja. After-state, fizički response
i gain nisu modelski ulazi. Jednaki result signature i sva tri završena
ponavljanja obavezni su za primarni skup.

## Pokrivenost panela

{panel_table}

## LOSO poređenje

{metric_table}

Primarni baseline je prosjek po akciji. Dodatno se porede k-nearest neighbors,
tvrda K-means memorija i FCM soft memorija. Podjela je leave-one-scenario-out,
a preprocessing, imputacija, skaliranje, PCA i FCM fituju se samo na trening
scenarijima svakog folda.

## Prequential lokalna provjera

{prequential_table}

Scenario postaje dostupan memoriji tek nakon sto su zavrseni baseline i svi
action uslovi tog scenarioa. Pri koraku `t` koriste se samo scenarioi sa ranijim
vremenom potpune dostupnosti. Ishodi trenutnog scenarioa dodaju se memoriji tek
nakon predikcije, pa se cold start i apstinencija mjere eksplicitno.

Svaki kNN red u `prequential_predictions.csv` sadrzi i serijalizovan trag
najblizih ranijih scenarioa: identitet scenarioa, udaljenost, tezinu i tada
dostupne ishode po akciji. Time se rang moze provjeriti bez ponovnog fitovanja.

Redovi `own_available` prikazuju stvarni cold start i pokrivenost svakog modela.
Redovi `fcm_matched` porede sve modele samo na identicnim scenarijima za koje je
FCM dao procjenu, kako razlicita apstinencija ne bi iskrivila poređenje kvaliteta.

## Apstinencija

Svaka FCM procjena sadrži broj opaženih epizoda, efektivnu fuzzy podršku,
udaljenost do najbližeg centra i status dostupnosti. Nepoznata ili nedovoljno
podržana akcija dobija `insufficient_local_evidence` umjesto procjene.

## Izlazi

- `episodes.csv`: stroge intervencijske epizode sa before i after dokazima.
- `panel_coverage.csv`: provjera zajedničkog action seta po scenariju.
- `predictions.csv`: leakage-safe LOSO predikcije i lokalna podrška.
- `model_metrics.csv`: action-selection metrike.
- `scenario_metrics.csv`: uparene metrike po scenariju.
- `selective_coverage.csv`: quality-coverage kriva za apstinenciju.
- `prequential_predictions.csv`: vremenski uredjene predikcije bez buduceg
  dokaza i provjerljiv trag kNN susjeda.
- `prequential_model_summary.csv`: cold start, pokrivenost i konacne metrike.
- `prequential_learning_curve.csv`: razvoj pokrivenosti, Top-1 i regreta.
- `prequential_quality_coverage.csv`: kvalitet nakon selekcije po pouzdanosti.
- `episode_responses.csv`: fizičke before-after promjene odvojene od gaina.
- `feature_selection_audit.csv`: dostupnost, varijacija i odluka za svaku
  kandidatsku kolonu po panelu.
- `fuzzy_transition_edges.csv`: fuzzy graf opaženih prijelaza.
- `fuzzy_transition_responses.csv`: response komponente po fuzzy prijelazu.
- `analysis_summary.json`: autoritativna gate odluka.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")


def analyze(contract_path: Path, out_dir: Path) -> dict[str, Any]:
    contract = read_yaml(contract_path)
    state_contract = contract["state_representation"]
    specifications = state_contract["features"]
    feature_names = list(specifications)
    episode_frames: list[pd.DataFrame] = []
    execution_frames: list[pd.DataFrame] = []
    missing_sources: list[str] = []
    for source in contract["sources"]:
        index_dir = resolve_path(source["index_dir"])
        if not (index_dir / "execution_features.csv").exists():
            if bool(source.get("required", True)):
                raise FileNotFoundError(
                    f"Required fuzzy-memory source is missing: {index_dir}"
                )
            missing_sources.append(str(source["id"]))
            continue
        episodes, executions = build_source_episodes(
            source,
            feature_names,
            int(contract["repetitions_per_condition"]),
        )
        episode_frames.append(episodes)
        execution_frames.append(executions)
    episodes = pd.concat(episode_frames, ignore_index=True)
    executions = pd.concat(execution_frames, ignore_index=True)
    strict = episodes[
        episodes["completed"]
        & episodes["result_equal"]
        & episodes["target_log2_gain"].notna()
    ].copy()

    coverage_frames: list[pd.DataFrame] = []
    prediction_frames: list[pd.DataFrame] = []
    metric_frames: list[pd.DataFrame] = []
    scenario_metric_frames: list[pd.DataFrame] = []
    selective_frames: list[pd.DataFrame] = []
    prequential_prediction_frames: list[pd.DataFrame] = []
    prequential_summary_frames: list[pd.DataFrame] = []
    prequential_learning_frames: list[pd.DataFrame] = []
    prequential_quality_frames: list[pd.DataFrame] = []
    membership_frames: list[pd.DataFrame] = []
    edge_frames: list[pd.DataFrame] = []
    active_feature_frames: list[pd.DataFrame] = []
    feature_selection_frames: list[pd.DataFrame] = []
    graph_diagnostics: list[dict[str, Any]] = []
    panel_episode_map: dict[str, pd.DataFrame] = {}
    panel_rows: list[dict[str, Any]] = []
    memory = contract["memory"]
    gate_contract = contract["gate"]

    minimum_evaluation_scenarios = max(
        5,
        int(memory["minimum_observed_support"]) + 1,
    )
    for panel_name, panel in contract["panels"].items():
        selected, coverage = panel_episodes(strict, panel)
        coverage["panel"] = panel_name
        coverage_frames.append(coverage)
        panel_episode_map[panel_name] = selected
        distinct_rankings, rank_reversals = (
            count_rank_reversals(selected)
            if not selected.empty
            else (0, 0)
        )
        scenario_count = int(selected["scenario_id"].nunique())
        panel_rows.append(
            {
                "panel": panel_name,
                "scenario_count": scenario_count,
                "action_count": int(selected["mitigation_action"].nunique())
                if not selected.empty
                else 0,
                "episode_count": len(selected),
                "distinct_ranking_count": distinct_rankings,
                "pairwise_rank_reversal_count": rank_reversals,
                "evaluation_status": (
                    "evaluated"
                    if scenario_count >= minimum_evaluation_scenarios
                    else "insufficient_scenarios"
                ),
            }
        )
        if scenario_count >= minimum_evaluation_scenarios:
            predictions, metrics, per_scenario = evaluate_panel(
                selected,
                panel_name=panel_name,
                actions=[str(value) for value in panel["actions"]],
                specifications=specifications,
                state_contract=state_contract,
                memory=memory,
                random_seed=int(gate_contract["random_seed"]),
            )
            prediction_frames.append(predictions)
            metric_frames.append(metrics)
            scenario_metric_frames.append(per_scenario)
            selective_frames.append(
                selective_coverage_curve(predictions).assign(panel=panel_name)
            )
            prequential = evaluate_prequential_panel(
                selected,
                panel_name=panel_name,
                actions=[str(value) for value in panel["actions"]],
                specifications=specifications,
                state_contract=state_contract,
                memory=memory,
                random_seed=int(gate_contract["random_seed"]),
            )
            prequential_summary, prequential_learning, prequential_quality = (
                summarize_prequential_predictions(prequential)
            )
            prequential_prediction_frames.append(prequential)
            prequential_summary_frames.append(prequential_summary)
            prequential_learning_frames.append(prequential_learning)
            prequential_quality_frames.append(prequential_quality)
        (
            memberships,
            edges,
            active_features,
            feature_selection,
            diagnostics,
        ) = final_panel_graph(
            selected,
            panel_name=panel_name,
            specifications=specifications,
            state_contract=state_contract,
            memory=memory,
        )
        if not memberships.empty:
            membership_frames.append(memberships)
        if not edges.empty:
            edge_frames.append(edges)
        if not active_features.empty:
            active_feature_frames.append(active_features)
        if not feature_selection.empty:
            feature_selection_frames.append(feature_selection)
        graph_diagnostics.append(diagnostics)

    panel_summary = pd.DataFrame(panel_rows)
    predictions = (
        pd.concat(prediction_frames, ignore_index=True)
        if prediction_frames
        else pd.DataFrame()
    )
    metrics = (
        pd.concat(metric_frames, ignore_index=True)
        if metric_frames
        else pd.DataFrame()
    )
    per_scenario = (
        pd.concat(scenario_metric_frames, ignore_index=True)
        if scenario_metric_frames
        else pd.DataFrame()
    )
    selective = (
        pd.concat(selective_frames, ignore_index=True)
        if selective_frames
        else pd.DataFrame()
    )
    prequential_predictions = (
        pd.concat(prequential_prediction_frames, ignore_index=True)
        if prequential_prediction_frames
        else pd.DataFrame()
    )
    prequential_summary = (
        pd.concat(prequential_summary_frames, ignore_index=True)
        if prequential_summary_frames
        else pd.DataFrame()
    )
    prequential_learning = (
        pd.concat(prequential_learning_frames, ignore_index=True)
        if prequential_learning_frames
        else pd.DataFrame()
    )
    prequential_quality = (
        pd.concat(prequential_quality_frames, ignore_index=True)
        if prequential_quality_frames
        else pd.DataFrame()
    )
    memberships = (
        pd.concat(membership_frames, ignore_index=True)
        if membership_frames
        else pd.DataFrame()
    )
    edges = (
        pd.concat(edge_frames, ignore_index=True)
        if edge_frames
        else pd.DataFrame()
    )
    active_features = (
        pd.concat(active_feature_frames, ignore_index=True)
        if active_feature_frames
        else pd.DataFrame()
    )
    feature_selection = (
        pd.concat(feature_selection_frames, ignore_index=True)
        if feature_selection_frames
        else pd.DataFrame()
    )
    response, null_scales = transformed_episode_responses(
        strict,
        executions,
        specifications,
        scale_floor=float(gate_contract["response_null_scale_floor"]),
    )
    transition_responses = (
        pd.concat(
            [
                response_by_transition(
                    response[
                        response["scenario_id"].isin(
                            set(panel_episode_map[panel_name]["scenario_id"])
                        )
                    ],
                    memberships[memberships["panel"].eq(panel_name)],
                    fuzzifier=float(memory["fuzzifier"]),
                ).assign(panel=panel_name)
                for panel_name in memberships["panel"].unique()
            ],
            ignore_index=True,
        )
        if not memberships.empty
        else pd.DataFrame()
    )

    primary_panel = str(contract["primary_panel"])
    primary_row = panel_summary.set_index("panel").loc[primary_panel]
    primary_scenarios = int(primary_row["scenario_count"])
    bootstrap: dict[str, Any] = {}
    checks: dict[str, bool] = {
        "primary_panel_has_minimum_scenarios": primary_scenarios
        >= int(gate_contract["minimum_primary_scenarios"]),
        "primary_panel_has_distinct_rankings": int(
            primary_row["distinct_ranking_count"]
        )
        >= int(gate_contract["minimum_distinct_rankings"]),
        "primary_panel_has_rank_reversals": int(
            primary_row["pairwise_rank_reversal_count"]
        )
        >= int(gate_contract["minimum_pairwise_rank_reversals"]),
    }
    if not checks["primary_panel_has_minimum_scenarios"]:
        gate = "PANEL_EXPANSION_REQUIRED"
    else:
        primary_metrics = metrics[metrics["panel"].eq(primary_panel)].set_index("model")
        primary_scenarios_frame = per_scenario[per_scenario["panel"].eq(primary_panel)]
        bootstrap = bootstrap_model_difference(
            primary_scenarios_frame,
            candidate="fcm_soft_memory",
            baseline="action_median",
            samples=int(gate_contract["bootstrap_samples"]),
            seed=int(gate_contract["random_seed"]),
        )
        pairwise_improvement = float(
            primary_metrics.loc["fcm_soft_memory", "pairwise_accuracy"]
            - primary_metrics.loc["action_median", "pairwise_accuracy"]
        )
        checks.update(
            {
                "fcm_pairwise_improves_over_action_median": pairwise_improvement
                >= float(
                    gate_contract[
                        "minimum_fcm_pairwise_improvement_over_action_median"
                    ]
                ),
                "fcm_regret_lower_than_action_median": float(
                    primary_metrics.loc["fcm_soft_memory", "mean_regret"]
                )
                < float(primary_metrics.loc["action_median", "mean_regret"]),
                "fcm_not_worse_than_knn": float(
                    primary_metrics.loc["fcm_soft_memory", "pairwise_accuracy"]
                )
                >= float(primary_metrics.loc["knn", "pairwise_accuracy"])
                and float(primary_metrics.loc["fcm_soft_memory", "mean_regret"])
                <= float(primary_metrics.loc["knn", "mean_regret"]),
                "bootstrap_pairwise_superiority": float(
                    bootstrap["pairwise_delta_ci95"][0]
                )
                > 0.0,
                "bootstrap_regret_superiority": float(
                    bootstrap["regret_delta_ci95"][1]
                )
                < 0.0,
            }
        )
        required = [
            "primary_panel_has_distinct_rankings",
            "primary_panel_has_rank_reversals",
            "fcm_pairwise_improves_over_action_median",
            "fcm_regret_lower_than_action_median",
            "fcm_not_worse_than_knn",
        ]
        if bool(gate_contract.get("require_bootstrap_superiority", False)):
            required.extend(
                ["bootstrap_pairwise_superiority", "bootstrap_regret_superiority"]
            )
        gate = "GO" if all(checks[name] for name in required) else "NO_GO"

    summary = {
        "contract_version": contract["contract_version"],
        "gate": gate,
        "primary_panel": primary_panel,
        "source_count": len(contract["sources"]),
        "loaded_source_count": len(episode_frames),
        "missing_optional_sources": missing_sources,
        "execution_count": len(executions),
        "episode_count": len(episodes),
        "strict_episode_count": len(strict),
        "scenario_count": int(strict["scenario_id"].nunique()),
        "panel_count": len(contract["panels"]),
        "primary_panel_scenario_count": primary_scenarios,
        "checks": checks,
        "bootstrap_vs_action_median": bootstrap,
        "prequential_primary_panel": (
            prequential_summary[
                prequential_summary["panel"].eq(primary_panel)
            ].to_dict(orient="records")
            if not prequential_summary.empty
            else []
        ),
        "graph_diagnostics": graph_diagnostics,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    strict.to_csv(out_dir / "episodes.csv", index=False)
    pd.concat(coverage_frames, ignore_index=True).to_csv(
        out_dir / "panel_coverage.csv", index=False
    )
    panel_summary.to_csv(out_dir / "panel_summary.csv", index=False)
    predictions.to_csv(out_dir / "predictions.csv", index=False)
    metrics.to_csv(out_dir / "model_metrics.csv", index=False)
    per_scenario.to_csv(out_dir / "scenario_metrics.csv", index=False)
    selective.to_csv(out_dir / "selective_coverage.csv", index=False)
    prequential_predictions.to_csv(
        out_dir / "prequential_predictions.csv", index=False
    )
    prequential_summary.to_csv(
        out_dir / "prequential_model_summary.csv", index=False
    )
    prequential_learning.to_csv(
        out_dir / "prequential_learning_curve.csv", index=False
    )
    prequential_quality.to_csv(
        out_dir / "prequential_quality_coverage.csv", index=False
    )
    response.to_csv(out_dir / "episode_responses.csv", index=False)
    null_scales.to_csv(out_dir / "response_null_scales.csv", index=False)
    memberships.to_csv(out_dir / "state_memberships.csv", index=False)
    edges.to_csv(out_dir / "fuzzy_transition_edges.csv", index=False)
    transition_responses.to_csv(
        out_dir / "fuzzy_transition_responses.csv", index=False
    )
    active_features.to_csv(out_dir / "active_state_features.csv", index=False)
    feature_selection.to_csv(
        out_dir / "feature_selection_audit.csv", index=False
    )
    (out_dir / "analysis_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_readme(
        out_dir,
        summary,
        panel_summary,
        metrics,
        prequential_summary,
    )
    return summary


def main() -> int:
    args = parse_args()
    summary = analyze(args.contract, args.out_dir)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["gate"] in {"GO", "PANEL_EXPANSION_REQUIRED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
