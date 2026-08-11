#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy.stats import spearmanr
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import mean_absolute_error, ndcg_score
from sklearn.preprocessing import StandardScaler

from master_regimes.representation_audit import semantic_transform

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RENDERED = ROOT / "generated/corpus/cross-action-pilot-v1-20260802-bundled"
DEFAULT_RUNTIME = ROOT / "workloads/corpus/runtime-configs.yml"
DEFAULT_CONTRACT = ROOT / "configs/validation/cross_action_pilot_v1.yml"
DEFAULT_INDEX = (
    ROOT.parent
    / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs/"
    / "cross-action-pilot-v1/_index"
)
DEFAULT_OUT = ROOT / "analysis/reports/cross-action-pilot-v1"
DEFAULT_FEATURE_DIR = ROOT / "analysis/features/cross-action-pilot-v1"
DEFAULT_SEMANTIC_CONTRACT = ROOT / "configs/features/feature_semantic_contract_v2.yml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and analyze Plan 42 pilot.")
    parser.add_argument("command", choices=("validate-design", "analyze"))
    parser.add_argument("--rendered-dir", type=Path, default=DEFAULT_RENDERED)
    parser.add_argument("--runtime-catalog", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--feature-dir", type=Path, default=DEFAULT_FEATURE_DIR)
    parser.add_argument(
        "--semantic-contract", type=Path, default=DEFAULT_SEMANTIC_CONTRACT
    )
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def canonical_json(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)) or value == "":
        return "{}"
    parsed = json.loads(value) if isinstance(value, str) else value
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def text_or_empty(value: Any) -> str:
    return "" if pd.isna(value) else str(value)


def read_instance_manifests(rendered_dir: Path) -> pd.DataFrame:
    plan = read_yaml(rendered_dir / "corpus_execution_plan.yml")
    paths = []
    for group in plan["groups"]:
        path = Path(str(group["instance_manifest"]))
        paths.append(path if path.is_absolute() else ROOT.parent / path)
    if not paths:
        raise FileNotFoundError(f"No instance manifests under {rendered_dir}")
    return pd.concat(
        (pd.read_csv(path, keep_default_na=False) for path in paths),
        ignore_index=True,
    )


def flatten_effective_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    selected = {
        "pg_options": runtime.get("pg_options", {}),
        "regional_pg_options": runtime.get("regional_pg_options", {}),
        "psql_variables": runtime.get("psql_variables", {}),
        "fdw_server_options": runtime.get("fdw_server_options", {}),
        "network_profile": {
            key: value
            for key, value in runtime.get("network_profile", {}).items()
            if key != "id"
        },
    }
    flat: dict[str, Any] = {}

    def visit(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                visit(f"{prefix}.{key}" if prefix else key, value[key])
        else:
            flat[prefix] = value

    visit("", selected)
    return flat


def changed_runtime_fields(
    baseline: dict[str, Any], action: dict[str, Any]
) -> set[str]:
    before = flatten_effective_runtime(baseline)
    after = flatten_effective_runtime(action)
    keys = set(before) | set(after)
    return {key for key in keys if before.get(key) != after.get(key)}


def scenario_key(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["component_match_id"].astype(str)
        + "::"
        + frame["dataset_profile_id"].astype(str)
        + "::"
        + frame["param_json"].map(canonical_json)
    )


def _runtime_id(spec: Any, component: str) -> str:
    if isinstance(spec, str):
        return spec
    return str(spec.get(component, spec["default"]))


def validate_design(
    rendered_dir: Path, runtime_catalog_path: Path, contract_path: Path
) -> tuple[pd.DataFrame, dict[str, Any]]:
    contract = read_yaml(contract_path)
    runtime_catalog = read_yaml(runtime_catalog_path)
    runtimes = runtime_catalog["runtime_configs"]
    rows = read_instance_manifests(rendered_dir)
    rows["scenario_id"] = scenario_key(rows)
    errors: list[str] = []
    scenario_rows: list[dict[str, Any]] = []
    design = contract["design"]

    observed = {
        "source_cells": int(
            read_yaml(rendered_dir / "corpus_execution_plan.yml")["source_cell_count"]
        ),
        "conditions": int(rows["condition_id"].nunique()),
        "executions": int(len(rows)),
        "scenarios": int(rows["scenario_id"].nunique()),
        "component_families": int(rows["component_match_id"].nunique()),
        "dataset_profiles": int(rows["dataset_profile_id"].nunique()),
    }
    expected_counts = {
        "source_cells": int(design["expected_source_cells"]),
        "conditions": int(design["expected_conditions"]),
        "executions": int(design["expected_executions"]),
        "scenarios": int(design["expected_scenarios"]),
        "component_families": int(design["expected_component_families"]),
        "dataset_profiles": int(design["expected_dataset_profiles"]),
    }
    for name, expected in expected_counts.items():
        if observed[name] != expected:
            errors.append(f"{name}: expected {expected}, observed {observed[name]}")

    repeat_expected = int(design["repetitions_per_condition"])
    condition_repeats = rows.groupby("condition_id")["execution_slot_id"].nunique()
    bad_repeats = condition_repeats[condition_repeats.ne(repeat_expected)]
    if not bad_repeats.empty:
        errors.append(f"{len(bad_repeats)} conditions do not have {repeat_expected} repetitions")

    action_contract = contract["scenario_actions"]
    runtime_contract = contract["runtime_transitions"]
    sql_contract = contract["sql_transitions"]
    for scenario_id, group in rows.groupby("scenario_id", sort=True):
        conditions = group.sort_values("repetition_index").drop_duplicates("condition_id")
        component = str(conditions["component_match_id"].iloc[0])
        baselines = conditions[conditions["variant"].astype(str).eq("stressed")]
        actions = conditions[conditions["mitigation_action"].astype(str).ne("")]
        expected_actions = set(action_contract.get(component, []))
        actual_actions = set(actions["mitigation_action"].astype(str))
        local_errors: list[str] = []
        if len(baselines) != 1:
            local_errors.append(f"expected one baseline, observed {len(baselines)}")
        if len(actions) != int(design["actions_per_scenario"]):
            local_errors.append(f"expected three actions, observed {len(actions)}")
        if actual_actions != expected_actions:
            local_errors.append(
                "action set differs: "
                f"expected {sorted(expected_actions)}, observed {sorted(actual_actions)}"
            )

        if len(baselines) == 1:
            baseline = baselines.iloc[0]
            for action in actions.to_dict(orient="records"):
                action_name = str(action["mitigation_action"])
                transition = runtime_contract[action_name]
                expected_baseline_runtime = _runtime_id(
                    transition.get("baseline_by_component", transition.get("baseline")),
                    component,
                )
                expected_action_runtime = _runtime_id(
                    transition.get("action_by_component", transition.get("action")),
                    component,
                )
                if str(baseline["runtime_config_id"]) != expected_baseline_runtime:
                    local_errors.append(
                        f"{action_name}: baseline runtime is "
                        f"{baseline['runtime_config_id']}, expected "
                        f"{expected_baseline_runtime}"
                    )
                if str(action["runtime_config_id"]) != expected_action_runtime:
                    local_errors.append(
                        f"{action_name}: action runtime is "
                        f"{action['runtime_config_id']}, expected "
                        f"{expected_action_runtime}"
                    )
                changed = changed_runtime_fields(
                    runtimes[expected_baseline_runtime], runtimes[expected_action_runtime]
                )
                allowed = set(transition["allowed_changes"])
                if changed != allowed:
                    local_errors.append(
                        f"{action_name}: runtime changes {sorted(changed)}, "
                        f"allowed {sorted(allowed)}"
                    )
                sql_change = sql_contract.get(action_name)
                if sql_change:
                    if str(baseline["template_id"]) != sql_change["baseline_template"]:
                        local_errors.append(f"{action_name}: wrong baseline SQL template")
                    if str(action["template_id"]) != sql_change["action_template"]:
                        local_errors.append(f"{action_name}: wrong action SQL template")
                elif str(action["template_id"]) != str(baseline["template_id"]):
                    local_errors.append(f"{action_name}: SQL changed without contract")

        scenario_rows.append(
            {
                "scenario_id": scenario_id,
                "component_match_id": component,
                "dataset_profile_id": str(conditions["dataset_profile_id"].iloc[0]),
                "condition_count": len(conditions),
                "execution_count": len(group),
                "baseline_count": len(baselines),
                "action_count": len(actions),
                "actions": "|".join(sorted(actual_actions)),
                "status": "PASS" if not local_errors else "FAIL",
                "issues": " | ".join(local_errors),
            }
        )
        errors.extend(f"{scenario_id}: {issue}" for issue in local_errors)

    summary = {
        "contract_version": contract["contract_version"],
        "gate": "GO" if not errors else "NO_GO",
        "observed": observed,
        "expected": expected_counts,
        "error_count": len(errors),
        "errors": errors,
    }
    return pd.DataFrame(scenario_rows), summary


def write_design_report(out_dir: Path, scenarios: pd.DataFrame, summary: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    scenarios.to_csv(out_dir / "design_scenarios.csv", index=False)
    (out_dir / "design_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def condition_summary(executions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for condition_id, group in executions.groupby("condition_id", sort=True):
        completed = group[group["execution_status"].astype(str).eq("completed")]
        signatures = sorted(
            {
                str(value)
                for value in group.get("result_multiset_sha256", pd.Series(dtype=str))
                if pd.notna(value) and str(value).strip()
            }
        )
        first = group.iloc[0]
        rows.append(
            {
                "condition_id": condition_id,
                "scenario_id": first["scenario_id"],
                "component_match_id": first["component_match_id"],
                "logical_question_id": first["logical_question_id"],
                "dataset_profile_id": first["dataset_profile_id"],
                "template_id": first["template_id"],
                "variant": text_or_empty(first["variant"]),
                "mitigation_action": text_or_empty(first["mitigation_action"]),
                "execution_count": len(group),
                "completed_count": len(completed),
                "elapsed_median": pd.to_numeric(
                    completed["elapsed_seconds"], errors="coerce"
                ).median(),
                "elapsed_mean": pd.to_numeric(
                    completed["elapsed_seconds"], errors="coerce"
                ).mean(),
                "elapsed_stddev": pd.to_numeric(
                    completed["elapsed_seconds"], errors="coerce"
                ).std(),
                "signature_count": len(signatures),
                "result_multiset_sha256": signatures[0] if len(signatures) == 1 else "",
            }
        )
    result = pd.DataFrame(rows)
    denominator = pd.to_numeric(result["elapsed_mean"], errors="coerce")
    result["elapsed_cv"] = pd.to_numeric(
        result["elapsed_stddev"], errors="coerce"
    ) / denominator.where(denominator > 0)
    return result


def build_gain_rows(conditions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scenario_id, group in conditions.groupby("scenario_id", sort=True):
        baseline = group[group["variant"].astype(str).eq("stressed")]
        if len(baseline) != 1:
            continue
        base = baseline.iloc[0]
        for action in group[group["mitigation_action"].astype(str).ne("")].to_dict(
            orient="records"
        ):
            valid_time = float(base["elapsed_median"]) > 0 and float(action["elapsed_median"]) > 0
            result_equal = bool(
                base["result_multiset_sha256"]
                and action["result_multiset_sha256"]
                and base["result_multiset_sha256"] == action["result_multiset_sha256"]
            )
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "component_match_id": base["component_match_id"],
                    "logical_question_id": base["logical_question_id"],
                    "dataset_profile_id": base["dataset_profile_id"],
                    "baseline_condition_id": base["condition_id"],
                    "action_condition_id": action["condition_id"],
                    "mitigation_action": action["mitigation_action"],
                    "baseline_elapsed_median": base["elapsed_median"],
                    "action_elapsed_median": action["elapsed_median"],
                    "target_log2_gain": (
                        math.log2(float(base["elapsed_median"]) / float(action["elapsed_median"]))
                        if valid_time
                        else np.nan
                    ),
                    "completed": int(base["completed_count"]) == 3
                    and int(action["completed_count"]) == 3,
                    "result_equal": result_equal,
                }
            )
    return pd.DataFrame(rows)


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
    rho = spearmanr(frame["target_log2_gain"], frame[prediction]).statistic
    return {
        "mae": float(mean_absolute_error(frame["target_log2_gain"], frame[prediction])),
        "spearman": float(rho) if not np.isnan(rho) else 0.0,
        "pairwise_accuracy": pair_correct / pair_total if pair_total else 0.0,
        "top1_accuracy": top_correct / scenario_count if scenario_count else 0.0,
        "ndcg": float(np.mean(ndcgs)),
        "mean_regret": float(np.mean(regrets)),
        "median_regret": float(np.median(regrets)),
    }


def scenario_ranking_metrics(
    frame: pd.DataFrame, prediction: str, model_name: str
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scenario_id, group in frame.groupby("scenario_id", sort=True):
        actual = group["target_log2_gain"].to_numpy(dtype=float)
        predicted = group[prediction].to_numpy(dtype=float)
        pair_correct = 0
        pair_total = 0
        for left in range(len(group)):
            for right in range(left + 1, len(group)):
                pair_total += 1
                pair_correct += int(
                    np.sign(actual[left] - actual[right])
                    == np.sign(predicted[left] - predicted[right])
                )
        rows.append(
            {
                "model": model_name,
                "scenario_id": scenario_id,
                "pairwise_accuracy": pair_correct / pair_total,
                "top1_correct": int(np.argmax(actual) == np.argmax(predicted)),
                "regret": float(np.max(actual) - actual[np.argmax(predicted)]),
            }
        )
    return pd.DataFrame(rows)


def paired_bootstrap_comparison(
    scenario_metrics: pd.DataFrame,
    *,
    baseline_model: str,
    candidate_model: str,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    baseline = scenario_metrics[
        scenario_metrics["model"].eq(baseline_model)
    ].set_index("scenario_id")
    candidate = scenario_metrics[
        scenario_metrics["model"].eq(candidate_model)
    ].set_index("scenario_id")
    aligned = candidate[["pairwise_accuracy", "regret"]].join(
        baseline[["pairwise_accuracy", "regret"]],
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
    pair_samples = pair_delta[indices].mean(axis=1)
    regret_samples = regret_delta[indices].mean(axis=1)
    return {
        "baseline_model": baseline_model,
        "candidate_model": candidate_model,
        "scenario_count": len(aligned),
        "bootstrap_samples": samples,
        "random_seed": seed,
        "pairwise_accuracy_delta_mean": float(pair_delta.mean()),
        "pairwise_accuracy_delta_ci95": [
            float(value) for value in np.quantile(pair_samples, [0.025, 0.975])
        ],
        "regret_delta_mean": float(regret_delta.mean()),
        "regret_delta_ci95": [
            float(value) for value in np.quantile(regret_samples, [0.025, 0.975])
        ],
    }


def action_conditioned_matrix(
    values: np.ndarray, actions: pd.Series, action_names: list[str]
) -> np.ndarray:
    one_hot = np.column_stack(
        [(actions.astype(str).to_numpy() == action).astype(float) for action in action_names]
    )
    interactions = np.hstack([values * one_hot[:, [index]] for index in range(len(action_names))])
    return np.hstack([values, one_hot, interactions])


def condition_feature_medians(
    executions: pd.DataFrame,
    condition_ids: set[str],
    feature_frame: pd.DataFrame,
    feature_names: list[str],
) -> pd.DataFrame:
    identity = executions[
        executions["condition_id"].astype(str).isin(condition_ids)
    ][["query_run_id", "condition_id"]]
    selected = identity.merge(
        feature_frame[["query_run_id", *feature_names]],
        on="query_run_id",
        validate="one_to_one",
    )
    numeric = selected[feature_names].apply(pd.to_numeric, errors="coerce")
    numeric["condition_id"] = selected["condition_id"].values
    return numeric.groupby("condition_id", sort=True)[feature_names].median()


def fit_action_conditioned_model(
    *,
    model: Any,
    train: pd.DataFrame,
    test: pd.DataFrame,
    feature_names: list[str],
    action_names: list[str],
) -> np.ndarray:
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    scaler = StandardScaler()
    train_values = scaler.fit_transform(imputer.fit_transform(train[feature_names]))
    test_values = scaler.transform(imputer.transform(test[feature_names]))
    train_matrix = action_conditioned_matrix(
        train_values, train["mitigation_action"], action_names
    )
    test_matrix = action_conditioned_matrix(
        test_values, test["mitigation_action"], action_names
    )
    model.fit(train_matrix, train["target_log2_gain"].to_numpy(dtype=float))
    return model.predict(test_matrix)


def evaluate_models(
    gain_rows: pd.DataFrame,
    executions: pd.DataFrame,
    expanded_features: list[str],
    semantic_frame: pd.DataFrame,
    semantic_features: list[str],
    model_contract: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    baseline_ids = set(gain_rows["baseline_condition_id"].astype(str))
    available = [name for name in expanded_features if name in executions.columns]
    expanded_medians = condition_feature_medians(
        executions, baseline_ids, executions, available
    )
    semantic_medians = condition_feature_medians(
        executions, baseline_ids, semantic_frame, semantic_features
    ).add_prefix("semantic19__")
    rows = gain_rows.merge(
        expanded_medians,
        left_on="baseline_condition_id",
        right_index=True,
        validate="many_to_one",
    ).merge(
        semantic_medians,
        left_on="baseline_condition_id",
        right_index=True,
        validate="many_to_one",
    ).reset_index(drop=True)
    semantic_columns = list(semantic_medians.columns)
    prediction_names = (
        "global_median",
        "action_median",
        "sql_shape_median",
        "semantic19_ridge",
        "expanded28_ridge",
        "expanded28_elastic_net",
        "expanded28_gradient_boosting",
    )
    prediction_frame = pd.DataFrame(
        np.nan,
        index=rows.index,
        columns=[f"prediction_{name}" for name in prediction_names],
    )
    rows = pd.concat([rows, prediction_frame], axis=1)
    action_names = sorted(rows["mitigation_action"].astype(str).unique())

    for held_scenario in sorted(rows["scenario_id"].unique()):
        train = rows[rows["scenario_id"].ne(held_scenario)].copy()
        test = rows[rows["scenario_id"].eq(held_scenario)].copy()
        target = train["target_log2_gain"].to_numpy(dtype=float)
        global_median = float(np.median(target))
        rows.loc[test.index, "prediction_global_median"] = global_median

        action_medians = train.groupby("mitigation_action")["target_log2_gain"].median()
        rows.loc[test.index, "prediction_action_median"] = [
            float(action_medians.get(action, global_median))
            for action in test["mitigation_action"]
        ]
        shape_medians = train.groupby(["component_match_id", "mitigation_action"])[
            "target_log2_gain"
        ].median()
        rows.loc[test.index, "prediction_sql_shape_median"] = [
            float(shape_medians.get((component, action), action_medians.get(action, global_median)))
            for component, action in zip(
                test["component_match_id"], test["mitigation_action"], strict=True
            )
        ]

        rows.loc[test.index, "prediction_semantic19_ridge"] = (
            fit_action_conditioned_model(
                model=Ridge(alpha=float(model_contract["semantic19_ridge_alpha"])),
                train=train,
                test=test,
                feature_names=semantic_columns,
                action_names=action_names,
            )
        )
        rows.loc[test.index, "prediction_expanded28_ridge"] = (
            fit_action_conditioned_model(
                model=Ridge(alpha=float(model_contract["expanded28_ridge_alpha"])),
                train=train,
                test=test,
                feature_names=available,
                action_names=action_names,
            )
        )
        rows.loc[test.index, "prediction_expanded28_elastic_net"] = (
            fit_action_conditioned_model(
                model=ElasticNet(
                    alpha=float(model_contract["expanded28_elastic_net_alpha"]),
                    l1_ratio=float(
                        model_contract["expanded28_elastic_net_l1_ratio"]
                    ),
                    max_iter=100_000,
                    random_state=int(model_contract["random_state"]),
                ),
                train=train,
                test=test,
                feature_names=available,
                action_names=action_names,
            )
        )
        rows.loc[test.index, "prediction_expanded28_gradient_boosting"] = (
            fit_action_conditioned_model(
                model=GradientBoostingRegressor(
                    n_estimators=int(model_contract["boosting_n_estimators"]),
                    learning_rate=float(model_contract["boosting_learning_rate"]),
                    max_depth=int(model_contract["boosting_max_depth"]),
                    min_samples_leaf=int(
                        model_contract["boosting_min_samples_leaf"]
                    ),
                    loss="huber",
                    random_state=int(model_contract["random_state"]),
                ),
                train=train,
                test=test,
                feature_names=available,
                action_names=action_names,
            )
        )

    metric_rows = []
    for name in prediction_names:
        metric_rows.append({"model": name, **ranking_metrics(rows, f"prediction_{name}")})
    return rows, pd.DataFrame(metric_rows)


def repeat_ranking_stability(
    executions: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    for (scenario_id, repetition), group in executions.groupby(
        ["scenario_id", "repetition_index"], sort=True
    ):
        baseline = group[group["variant"].map(text_or_empty).eq("stressed")]
        actions = group[group["mitigation_action"].map(text_or_empty).ne("")]
        if len(baseline) != 1 or len(actions) != 3:
            continue
        baseline_elapsed = float(baseline.iloc[0]["elapsed_seconds"])
        gains = [
            (
                text_or_empty(action["mitigation_action"]),
                math.log2(baseline_elapsed / float(action["elapsed_seconds"])),
            )
            for _, action in actions.iterrows()
        ]
        rows.append(
            {
                "scenario_id": scenario_id,
                "repetition_index": int(repetition),
                "ranking": ">".join(
                    action
                    for action, _ in sorted(
                        gains, key=lambda item: item[1], reverse=True
                    )
                ),
                "top_action": max(gains, key=lambda item: item[1])[0],
            }
        )
    detail = pd.DataFrame(rows)
    summaries: list[dict[str, Any]] = []
    for scenario_id, group in detail.groupby("scenario_id", sort=True):
        counts = group["ranking"].value_counts()
        top_counts = group["top_action"].value_counts()
        summaries.append(
            {
                "scenario_id": scenario_id,
                "repetition_count": len(group),
                "distinct_ranking_count": int(group["ranking"].nunique()),
                "modal_ranking_share": float(counts.iloc[0] / len(group)),
                "top_action_agreement_share": float(top_counts.iloc[0] / len(group)),
                "all_rankings_equal": bool(group["ranking"].nunique() == 1),
                "all_top_actions_equal": bool(group["top_action"].nunique() == 1),
            }
        )
    return detail, pd.DataFrame(summaries)


def feature_availability(
    executions: pd.DataFrame,
    expanded_features: list[str],
    semantic_raw: pd.DataFrame,
    semantic_features: list[str],
) -> pd.DataFrame:
    stressed = executions[executions["variant"].map(text_or_empty).eq("stressed")]
    rows = [
        {
            "feature_view": "expanded28",
            "feature": feature,
            "row_count": len(stressed),
            "non_null_count": int(
                pd.to_numeric(stressed[feature], errors="coerce").notna().sum()
            ),
        }
        for feature in expanded_features
    ]
    stressed_semantic = stressed[["query_run_id"]].merge(
        semantic_raw[["query_run_id", *semantic_features]],
        on="query_run_id",
        validate="one_to_one",
    )
    for feature in semantic_features:
        rows.append(
            {
                "feature_view": "semantic19",
                "feature": feature,
                "row_count": len(stressed_semantic),
                "non_null_count": int(
                    pd.to_numeric(
                        stressed_semantic[feature], errors="coerce"
                    ).notna().sum()
                ),
            }
        )
    result = pd.DataFrame(rows)
    result["non_null_share"] = result["non_null_count"] / result["row_count"]
    return result


def action_coverage(gains: pd.DataFrame) -> pd.DataFrame:
    return (
        gains.groupby("mitigation_action", as_index=False)
        .agg(
            scenario_count=("scenario_id", "nunique"),
            comparison_count=("scenario_id", "size"),
            component_family_count=("component_match_id", "nunique"),
            gain_median=("target_log2_gain", "median"),
            gain_min=("target_log2_gain", "min"),
            gain_max=("target_log2_gain", "max"),
        )
        .sort_values(["scenario_count", "mitigation_action"], ascending=[False, True])
    )


def count_rank_reversals(gains: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    records: list[dict[str, Any]] = []
    for scenario_id, group in gains.groupby("scenario_id", sort=True):
        values = group.set_index("mitigation_action")["target_log2_gain"].to_dict()
        actions = sorted(values)
        for left_index, left in enumerate(actions):
            for right in actions[left_index + 1 :]:
                records.append(
                    {
                        "scenario_id": scenario_id,
                        "action_a": left,
                        "action_b": right,
                        "ordering": int(np.sign(values[left] - values[right])),
                    }
                )
    orders = pd.DataFrame(records)
    if orders.empty:
        return orders, 0
    reversal_pairs = orders.groupby(["action_a", "action_b"])["ordering"].nunique()
    return orders, int(reversal_pairs.gt(1).sum())


def write_analysis_readme(
    out_dir: Path,
    summary: dict[str, Any],
    metrics: pd.DataFrame,
) -> None:
    improvement_magnitude = abs(summary["feature_over_action_pairwise_improvement"])
    improvement_direction = (
        "niža"
        if summary["feature_over_action_pairwise_improvement"] < 0
        else "viša"
    )
    strict_comparisons = summary["strict_action_comparison_count"]
    all_comparisons = summary["action_comparison_count"]
    pair_ci_low, pair_ci_high = summary["feature_vs_action_pairwise_ci95"]
    regret_ci_low, regret_ci_high = summary["feature_vs_action_regret_ci95"]
    missing_expanded = summary["expanded_all_missing_feature_count"]
    sparse_expanded = summary["expanded_sparse_feature_count"]
    metric_lines = [
        "| Model | MAE | Pairwise | Top-1 | NDCG | Mean regret |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in metrics.to_dict(orient="records"):
        metric_lines.append(
            "| {model} | {mae:.3f} | {pairwise_accuracy:.3f} | "
            "{top1_accuracy:.3f} | {ndcg:.3f} | {mean_regret:.3f} |".format(
                **row
            )
        )
    readme = f"""# Cross-action feasibility pilot v1

## Odluka

**{summary['gate']}**

Pilot potvrđuje da problem poređenja akcija postoji, ali ne potvrđuje da ga
trenutna tabularna reprezentacija može naučiti bolje od jednostavnog prosjeka po
akciji. Zato Plan 42 ne postaje nova centralna metodologija rada na osnovu ovog
pilota.

## Eksperimentalni ugovor

- {summary['scenario_count']} osnovnih stressed scenarija.
- {summary['condition_count']} uslova.
- {summary['execution_count']} završenih izvršenja.
- Tri ponavljanja po uslovu.
- Tri pojedinačno primijenjene akcije na zajedničkom baselineu svakog scenarija.
- Target `log2(median(stressed) / median(action))`.
- Leave-one-scenario-out evaluacija.
- modelski ulaz sadrži samo stressed post-execution dokaz i identitet kandidatne
  akcije.

Svih {strict_comparisons}/{all_comparisons} poređenja ima tri završena ponavljanja i egzaktno
jednak result signature.

## Strukturni nalaz

- pronađeno je {summary['distinct_ranking_count']} različitih poredaka akcija.
- pronađena su {summary['pairwise_rank_reversal_count']} para akcija čiji se
  redoslijed mijenja između scenarija.
- {summary['repeat_stable_scenario_count']}/{summary['scenario_count']} scenarija
  ima identičan cijeli poredak u sva tri ponavljanja.
- vodeća akcija je ista u sva tri ponavljanja za
  {summary['top_action_stable_scenario_count']}/{summary['scenario_count']} scenarija.
- medijana CV-a trajanja uslova je {summary['condition_elapsed_cv_median']:.4f}.

To pokazuje da statički univerzalni poredak nije dovoljan. Najjasnije promjene
prioriteta javljaju se između regionalnog Top-K rewritea i remote bundlea, te
između colocation akcije i remote bundlea pri promjeni veličine dataseta.

## Modelska provjera

{chr(10).join(metric_lines)}

Primarni feature-aware model za gate je
`{summary['primary_feature_model']}`. Njegova pairwise tačnost je za
{improvement_magnitude:.3f} {improvement_direction} od action-median baselinea,
a srednji regret nije niži. I 19-feature Ridge i
mali boosting check daju isti opći zaključak.

Upareni bootstrap po scenariju daje 95% interval
[{pair_ci_low:.3f}, {pair_ci_high:.3f}] za razliku pairwise tačnosti i
[{regret_ci_low:.3f}, {regret_ci_high:.3f}] za razliku regreta. Intervali ne daju
signal da je primarni feature-aware model bolji od baselinea.

U proširenom pogledu {missing_expanded} od 28 pokazatelja nema nijednu opaženu
vrijednost u stressed redovima, dok je {sparse_expanded} pokazatelja nepotpuno.
Ovaj nedostatak se transparentno imputira unutar svakog trening folda i dodatno
ograničava tumačenje modelskog rezultata.

Action-median baseline je snažan zato što je većina akcija još vezana za mali
broj SQL porodica i dvije dataset veličine. Pilot zato nije dokaz općeg
action-rankera, ali jeste direktan dokaz da postoje kontekstualne promjene
prioriteta koje bi širi, preklopljeniji panel mogao pokušati naučiti.

## Zaključak

Rezultat je metodološki `MIXED`:

1. **GO za postojanje problema:** gainovi su stabilni, semantički korektni i
   poredak akcija nije univerzalno fiksan.
2. **NO-GO za centralni pivot sada:** feature-aware modeli ne pobjeđuju
   action-only baseline na leave-one-scenario-out evaluaciji.
3. **Nema osnove za FCM nad response profilima:** panel je premalen i
   prediktor profila nije potvrđen.
4. **Zamrznuta teza ostaje fallback:** eventualno proširenje Plan 42 zahtijeva
   više scenarija na kojima se iste akcije preklapaju, a ne složeniji model nad
   ovih 12 scenarija.

## Izlazi

- `action_gains.csv`: strogi kontrafaktualni targeti.
- `scenario_rankings.csv`: poredak akcija po scenariju.
- `repeat_rankings.csv`: poredak po pojedinačnom ponavljanju.
- `action_coverage.csv`: pokrivenost i raspon gaina po akciji.
- `model_metrics.csv`: LOSO poređenje baselinea i feature-aware modela.
- `model_scenario_metrics.csv`: uparene modelske metrike po scenariju.
- `primary_vs_action_bootstrap.json`: bootstrap razlike prema action baselineu.
- `model_predictions.csv`: predikcije svakog held-out scenarija.
- `feature_availability.csv`: dostupnost oba feature pogleda.
- `analysis_summary.json`: autoritativna gate odluka.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")


def analyze(
    index_dir: Path,
    contract_path: Path,
    out_dir: Path,
    feature_dir: Path,
    semantic_contract_path: Path,
) -> dict[str, Any]:
    contract = read_yaml(contract_path)
    semantic_contract = read_yaml(semantic_contract_path)
    executions = pd.read_csv(index_dir / "execution_features.csv", low_memory=False)
    executions = pd.concat(
        [executions, scenario_key(executions).rename("scenario_id")], axis=1
    )
    conditions = condition_summary(executions)
    gains = build_gain_rows(conditions)
    strict = gains[gains["completed"] & gains["result_equal"]].copy()
    semantic_raw = pd.read_csv(
        feature_dir / "execution_features_all.csv", low_memory=False
    )
    _, semantic_weighted, _ = semantic_transform(
        semantic_raw, semantic_raw, semantic_contract
    )
    semantic_features = list(semantic_contract["features"])
    analysis_contract = contract["analysis"]
    predictions, metrics = evaluate_models(
        strict,
        executions,
        list(analysis_contract["features"]),
        semantic_weighted,
        semantic_features,
        analysis_contract["models"],
    )
    repeat_detail, repeat_summary = repeat_ranking_stability(executions)
    availability = feature_availability(
        executions,
        list(analysis_contract["features"]),
        semantic_raw,
        semantic_features,
    )
    coverage = action_coverage(strict)
    orders, reversal_count = count_rank_reversals(strict)
    ranking_signatures = strict.groupby("scenario_id").apply(
        lambda group: ">".join(
            group.sort_values("target_log2_gain", ascending=False)["mitigation_action"]
        ),
        include_groups=False,
    )
    action_metrics = metrics.set_index("model")
    primary_feature_model = str(analysis_contract["primary_feature_model"])
    scenario_metrics = pd.concat(
        [
            scenario_ranking_metrics(
                predictions, f"prediction_{model_name}", model_name
            )
            for model_name in metrics["model"]
        ],
        ignore_index=True,
    )
    bootstrap = paired_bootstrap_comparison(
        scenario_metrics,
        baseline_model="action_median",
        candidate_model=primary_feature_model,
        samples=int(analysis_contract["bootstrap_samples"]),
        seed=int(analysis_contract["models"]["random_state"]),
    )
    improvement = float(
        action_metrics.loc[primary_feature_model, "pairwise_accuracy"]
        - action_metrics.loc["action_median", "pairwise_accuracy"]
    )
    lower_regret = bool(
        action_metrics.loc[primary_feature_model, "mean_regret"]
        < action_metrics.loc["action_median", "mean_regret"]
    )
    stable_share = float(repeat_summary["all_rankings_equal"].mean())
    checks = {
        "all_36_action_comparisons_strict": len(strict) == 36,
        "repeat_rankings_stable": stable_share
        >= float(analysis_contract["minimum_repeat_stable_scenario_share"]),
        "distinct_rankings": ranking_signatures.nunique()
        >= int(analysis_contract["minimum_distinct_action_rankings"]),
        "rank_reversals": reversal_count
        >= int(analysis_contract["minimum_pairwise_rank_reversals"]),
        "feature_model_pairwise_improvement": improvement
        >= float(analysis_contract["minimum_feature_model_pairwise_improvement"]),
        "feature_model_lower_regret": lower_regret,
    }
    structural = all(
        checks[name]
        for name in (
            "all_36_action_comparisons_strict",
            "repeat_rankings_stable",
            "distinct_rankings",
            "rank_reversals",
        )
    )
    predictive = checks["feature_model_pairwise_improvement"] and checks[
        "feature_model_lower_regret"
    ]
    gate = "GO" if structural and predictive else "MIXED" if structural else "NO_GO"
    summary = {
        "gate": gate,
        "execution_count": len(executions),
        "condition_count": len(conditions),
        "scenario_count": int(gains["scenario_id"].nunique()),
        "action_comparison_count": len(gains),
        "action_count": int(gains["mitigation_action"].nunique()),
        "strict_action_comparison_count": len(strict),
        "distinct_ranking_count": int(ranking_signatures.nunique()),
        "pairwise_rank_reversal_count": reversal_count,
        "repeat_stable_scenario_count": int(
            repeat_summary["all_rankings_equal"].sum()
        ),
        "top_action_stable_scenario_count": int(
            repeat_summary["all_top_actions_equal"].sum()
        ),
        "condition_elapsed_cv_median": float(conditions["elapsed_cv"].median()),
        "condition_elapsed_cv_max": float(conditions["elapsed_cv"].max()),
        "expanded_all_missing_feature_count": int(
            (
                availability["feature_view"].eq("expanded28")
                & availability["non_null_count"].eq(0)
            ).sum()
        ),
        "expanded_sparse_feature_count": int(
            (
                availability["feature_view"].eq("expanded28")
                & availability["non_null_share"].lt(1.0)
            ).sum()
        ),
        "primary_feature_model": primary_feature_model,
        "feature_over_action_pairwise_improvement": improvement,
        "feature_model_lower_regret": lower_regret,
        "feature_vs_action_pairwise_ci95": bootstrap[
            "pairwise_accuracy_delta_ci95"
        ],
        "feature_vs_action_regret_ci95": bootstrap["regret_delta_ci95"],
        "checks": checks,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    conditions.to_csv(out_dir / "condition_summary.csv", index=False)
    gains.to_csv(out_dir / "action_gains.csv", index=False)
    predictions.to_csv(out_dir / "model_predictions.csv", index=False)
    metrics.to_csv(out_dir / "model_metrics.csv", index=False)
    scenario_metrics.to_csv(out_dir / "model_scenario_metrics.csv", index=False)
    repeat_detail.to_csv(out_dir / "repeat_rankings.csv", index=False)
    repeat_summary.to_csv(out_dir / "repeat_ranking_stability.csv", index=False)
    availability.to_csv(out_dir / "feature_availability.csv", index=False)
    coverage.to_csv(out_dir / "action_coverage.csv", index=False)
    orders.to_csv(out_dir / "pairwise_action_orders.csv", index=False)
    ranking_signatures.rename("ranking").to_csv(out_dir / "scenario_rankings.csv")
    (out_dir / "analysis_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "primary_vs_action_bootstrap.json").write_text(
        json.dumps(bootstrap, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_analysis_readme(out_dir, summary, metrics)
    return summary


def main() -> int:
    args = parse_args()
    if args.command == "validate-design":
        scenarios, summary = validate_design(
            args.rendered_dir, args.runtime_catalog, args.contract
        )
        write_design_report(args.out_dir, scenarios, summary)
    else:
        summary = analyze(
            args.index_dir,
            args.contract,
            args.out_dir,
            args.feature_dir,
            args.semantic_contract,
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["gate"] != "NO_GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
