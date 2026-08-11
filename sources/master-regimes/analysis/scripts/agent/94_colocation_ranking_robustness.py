#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import numpy as np
import pandas as pd
import yaml
from scipy.stats import kendalltau, spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    ndcg_score,
    r2_score,
)
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT = ROOT / "configs/models/colocation_ranking_v1.yml"
DEFAULT_OUT = ROOT / "analysis/reports/pressure-raw-v1-colocation-ranking-robustness"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark leakage-safe ranking of colocated-distribution gain."
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--matrix", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def read_contract(path: Path) -> dict[str, Any]:
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    validate_contract(contract)
    return contract


def feature_views(contract: dict[str, Any]) -> dict[str, list[str]]:
    views = {
        str(name): [str(feature) for feature in features]
        for name, features in contract["feature_views"].items()
    }
    if set(views) != {"core", "extended"}:
        raise ValueError("Feature contract must define exactly core and extended views")
    if not set(views["core"]).issubset(views["extended"]):
        raise ValueError("Core features must be a subset of extended features")
    return views


def validate_contract(contract: dict[str, Any]) -> None:
    views = feature_views_unchecked(contract)
    forbidden = tuple(str(value) for value in contract["forbidden_input_patterns"])
    all_features = [feature for features in views.values() for feature in features]
    duplicates = [
        feature for feature in set(all_features) if all_features.count(feature) > 2
    ]
    if duplicates:
        raise ValueError(f"Feature appears unexpectedly often: {duplicates}")
    violations = [
        feature
        for feature in sorted(set(all_features))
        if any(re.search(pattern, feature) for pattern in forbidden)
    ]
    if violations:
        raise ValueError(f"Feature contract violates leakage/topology policy: {violations}")
    transformed = {
        str(feature)
        for names in contract["feature_transforms"].values()
        for feature in names
    }
    if transformed != set(views["extended"]):
        missing = sorted(set(views["extended"]) - transformed)
        extra = sorted(transformed - set(views["extended"]))
        raise ValueError(f"Transform coverage mismatch; missing={missing}, extra={extra}")
    if contract["primary_estimator"] != "ridge":
        raise ValueError("Plan 41 freezes Ridge as the primary estimator")
    if bool(contract["benchmark_policy"]["model_selection_from_intensity_holdout"]):
        raise ValueError("Intensity holdout must not select the final estimator")


def feature_views_unchecked(contract: dict[str, Any]) -> dict[str, list[str]]:
    return {
        str(name): [str(feature) for feature in features]
        for name, features in contract["feature_views"].items()
    }


def feature_transform(contract: dict[str, Any], feature: str) -> str:
    for transform, names in contract["feature_transforms"].items():
        if feature in names:
            return str(transform)
    raise KeyError(feature)


def make_preprocessor(contract: dict[str, Any], names: list[str]) -> ColumnTransformer:
    log_names = [name for name in names if feature_transform(contract, name) == "log1p"]
    identity_names = [
        name for name in names if feature_transform(contract, name) == "identity"
    ]
    transformers: list[tuple[str, Pipeline, list[str]]] = []
    if log_names:
        transformers.append(
            (
                "log1p",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                        (
                            "transform",
                            FunctionTransformer(np.log1p, feature_names_out="one-to-one"),
                        ),
                        ("scaler", StandardScaler()),
                    ]
                ),
                log_names,
            )
        )
    if identity_names:
        transformers.append(
            (
                "identity",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                identity_names,
            )
        )
    return ColumnTransformer(transformers, verbose_feature_names_out=False)


def estimator(contract: dict[str, Any], name: str):
    spec = contract["estimators"][name]
    kind = str(spec["kind"])
    if kind == "median_baseline":
        return DummyRegressor(strategy="median")
    if kind == "ridge":
        return Ridge(alpha=float(spec["alpha"]))
    if kind == "elastic_net":
        return ElasticNet(
            alpha=float(spec["alpha"]),
            l1_ratio=float(spec["l1_ratio"]),
            max_iter=int(spec["max_iter"]),
            random_state=42,
        )
    if kind == "gradient_boosting":
        return GradientBoostingRegressor(
            n_estimators=int(spec["n_estimators"]),
            learning_rate=float(spec["learning_rate"]),
            max_depth=int(spec["max_depth"]),
            min_samples_leaf=int(spec["min_samples_leaf"]),
            loss=str(spec["loss"]),
            random_state=int(spec["random_state"]),
        )
    raise ValueError(f"Unsupported estimator kind: {kind}")


def model_pipeline(contract: dict[str, Any], model_name: str, names: list[str]):
    if model_name == "median_baseline":
        return estimator(contract, model_name)
    return Pipeline(
        [
            ("preprocess", make_preprocessor(contract, names)),
            ("model", estimator(contract, model_name)),
        ]
    )


def safe_rank_correlation(actual: np.ndarray, predicted: np.ndarray, kind: str) -> float:
    if len(actual) < 2 or len(np.unique(actual)) < 2 or len(np.unique(predicted)) < 2:
        return math.nan
    result = spearmanr(actual, predicted) if kind == "spearman" else kendalltau(actual, predicted)
    return float(result.statistic)


def top_k_recall(actual: np.ndarray, predicted: np.ndarray, k: int) -> float:
    effective_k = min(int(k), len(actual))
    if effective_k == 0:
        return math.nan
    actual_top = set(np.argsort(actual)[-effective_k:])
    predicted_top = set(np.argsort(predicted)[-effective_k:])
    return len(actual_top & predicted_top) / effective_k


def ranking_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    *,
    ndcg_k: int,
    top_k_values: list[int],
) -> dict[str, float]:
    relevance = np.maximum(np.exp2(actual) - 1.0, 0.0)
    effective_ndcg_k = min(int(ndcg_k), len(actual))
    metrics = {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(math.sqrt(mean_squared_error(actual, predicted))),
        "r2": float(r2_score(actual, predicted)) if len(actual) >= 2 else math.nan,
        "spearman": safe_rank_correlation(actual, predicted, "spearman"),
        "kendall": safe_rank_correlation(actual, predicted, "kendall"),
        "ndcg_at_5": float(
            ndcg_score(relevance.reshape(1, -1), predicted.reshape(1, -1), k=effective_ndcg_k)
        ),
    }
    for k in top_k_values:
        metrics[f"top{k}_recall"] = top_k_recall(actual, predicted, k)
    return metrics


def coverage_for_fold(
    contract: dict[str, Any],
    names: list[str],
    train: pd.DataFrame,
    test: pd.DataFrame,
) -> tuple[np.ndarray, float]:
    preprocessor = make_preprocessor(contract, names)
    train_values = np.asarray(preprocessor.fit_transform(train[names]), dtype=float)
    test_values = np.asarray(preprocessor.transform(test[names]), dtype=float)
    if len(train_values) < 2:
        return np.full(len(test_values), math.nan), math.nan
    neighbors = NearestNeighbors(n_neighbors=2, metric="euclidean").fit(train_values)
    train_distances = neighbors.kneighbors(train_values, return_distance=True)[0][:, 1]
    quantile = float(contract["coverage"]["training_nearest_neighbor_quantile"])
    threshold = float(np.quantile(train_distances, quantile, method="linear"))
    test_distances = neighbors.kneighbors(
        test_values, n_neighbors=1, return_distance=True
    )[0][:, 0]
    return test_distances, threshold


def validate_matrix(matrix: pd.DataFrame, contract: dict[str, Any]) -> None:
    required = {
        "pair_id",
        str(contract["target"]["field"]),
        *(item["group_field"] for item in contract["holdouts"]),
        *feature_views(contract)["extended"],
    }
    missing = sorted(required - set(matrix.columns))
    if missing:
        raise ValueError(f"Model matrix is missing columns: {missing}")
    if matrix["pair_id"].duplicated().any():
        raise ValueError("Model matrix must contain one row per counterfactual pair")
    for name in feature_views(contract)["extended"]:
        values = pd.to_numeric(matrix[name], errors="coerce")
        if feature_transform(contract, name) == "log1p" and values.dropna().lt(0).any():
            raise ValueError(f"Feature {name} has negative values under log1p contract")
        matrix[name] = values


def run_benchmark(
    matrix: pd.DataFrame,
    contract: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    target = str(contract["target"]["field"])
    y = matrix[target].to_numpy(dtype=float)
    top_k_values = [int(value) for value in contract["ranking_metrics"]["top_k"]]
    ndcg_k = int(contract["ranking_metrics"]["ndcg_k"])
    predictions: list[dict[str, Any]] = []
    fold_metrics: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []

    for holdout in contract["holdouts"]:
        holdout_name = str(holdout["name"])
        group_field = str(holdout["group_field"])
        groups = matrix[group_field].astype(str).to_numpy()
        splitter = LeaveOneGroupOut()
        for fold, (train_index, test_index) in enumerate(
            splitter.split(matrix, y, groups), start=1
        ):
            held_out_group = "|".join(sorted(set(groups[test_index])))
            train = matrix.iloc[train_index]
            test = matrix.iloc[test_index]
            for view_name, names in feature_views(contract).items():
                distances, threshold = coverage_for_fold(contract, names, train, test)
                for position, row_index in enumerate(test_index):
                    coverage_rows.append(
                        {
                            "holdout": holdout_name,
                            "fold": fold,
                            "held_out_group": held_out_group,
                            "feature_view": view_name,
                            "pair_id": matrix.iloc[row_index]["pair_id"],
                            "distance_to_nearest_training": float(distances[position]),
                            "training_p99_nearest_neighbor_distance": threshold,
                            "outside_training_p99": bool(distances[position] > threshold),
                        }
                    )
                for model_name in contract["estimators"]:
                    model = model_pipeline(contract, str(model_name), names)
                    model.fit(train[names], y[train_index])
                    predicted = np.asarray(model.predict(test[names]), dtype=float)
                    metrics = ranking_metrics(
                        y[test_index],
                        predicted,
                        ndcg_k=ndcg_k,
                        top_k_values=top_k_values,
                    )
                    fold_metrics.append(
                        {
                            "holdout": holdout_name,
                            "fold": fold,
                            "held_out_group": held_out_group,
                            "feature_view": view_name,
                            "model": str(model_name),
                            "train_pair_count": len(train_index),
                            "test_pair_count": len(test_index),
                            **metrics,
                        }
                    )
                    for position, row_index in enumerate(test_index):
                        predictions.append(
                            {
                                "holdout": holdout_name,
                                "fold": fold,
                                "held_out_group": held_out_group,
                                "feature_view": view_name,
                                "model": str(model_name),
                                "pair_id": matrix.iloc[row_index]["pair_id"],
                                "actual_log2_gain": y[row_index],
                                "predicted_log2_gain": float(predicted[position]),
                                "actual_speedup": float(np.exp2(y[row_index])),
                                "predicted_speedup": float(np.exp2(predicted[position])),
                            }
                        )

    prediction_frame = pd.DataFrame(predictions)
    fold_frame = pd.DataFrame(fold_metrics)
    coverage_frame = pd.DataFrame(coverage_rows).drop_duplicates(
        ["holdout", "fold", "feature_view", "pair_id"]
    )
    summary_rows: list[dict[str, Any]] = []
    metric_columns = [
        "spearman",
        "kendall",
        "ndcg_at_5",
        *[f"top{k}_recall" for k in top_k_values],
    ]
    for keys, group in prediction_frame.groupby(["holdout", "feature_view", "model"]):
        holdout_name, view_name, model_name = keys
        overall = ranking_metrics(
            group["actual_log2_gain"].to_numpy(),
            group["predicted_log2_gain"].to_numpy(),
            ndcg_k=ndcg_k,
            top_k_values=top_k_values,
        )
        folds = fold_frame[
            fold_frame["holdout"].eq(holdout_name)
            & fold_frame["feature_view"].eq(view_name)
            & fold_frame["model"].eq(model_name)
        ]
        summary = {
            "holdout": holdout_name,
            "feature_view": view_name,
            "model": model_name,
            "pair_count": len(group),
            **{f"oof_{name}": value for name, value in overall.items()},
        }
        for name in metric_columns:
            summary[f"fold_{name}_mean"] = float(folds[name].mean(skipna=True))
        summary_rows.append(summary)
    return prediction_frame, fold_frame, pd.DataFrame(summary_rows), coverage_frame


def feature_view_decision(
    summary: pd.DataFrame,
    contract: dict[str, Any],
) -> tuple[str, pd.DataFrame]:
    primary_model = str(contract["feature_view_decision"]["primary_model"])
    source = summary[summary["model"].eq(primary_model)]
    rows: list[dict[str, Any]] = []
    for holdout in [str(item["name"]) for item in contract["holdouts"]]:
        indexed = source[source["holdout"].eq(holdout)].set_index("feature_view")
        core = indexed.loc["core"]
        extended = indexed.loc["extended"]
        rows.append(
            {
                "holdout": holdout,
                "core_mae": core["oof_mae"],
                "extended_mae": extended["oof_mae"],
                "extended_mae_improvement": core["oof_mae"] - extended["oof_mae"],
                "core_spearman": core["fold_spearman_mean"],
                "extended_spearman": extended["fold_spearman_mean"],
                "extended_spearman_delta": extended["fold_spearman_mean"]
                - core["fold_spearman_mean"],
                "core_ndcg_at_5": core["fold_ndcg_at_5_mean"],
                "extended_ndcg_at_5": extended["fold_ndcg_at_5_mean"],
                "extended_ndcg_delta": extended["fold_ndcg_at_5_mean"]
                - core["fold_ndcg_at_5_mean"],
            }
        )
    audit = pd.DataFrame(rows)
    rule = contract["feature_view_decision"]
    minimum_wins = int(rule["minimum_holdout_wins"])
    maximum_drop = float(rule["maximum_allowed_spearman_drop"])
    mae_wins = int(audit["extended_mae_improvement"].gt(0).sum())
    ndcg_wins = int(audit["extended_ndcg_delta"].gt(0).sum())
    safe_spearman = bool(audit["extended_spearman_delta"].ge(-maximum_drop).all())
    selected = (
        "extended"
        if mae_wins >= minimum_wins and ndcg_wins >= minimum_wins and safe_spearman
        else "core"
    )
    audit["decision"] = selected
    audit["extended_mae_holdout_wins"] = mae_wins
    audit["extended_ndcg_holdout_wins"] = ndcg_wins
    audit["extended_spearman_within_tolerance"] = safe_spearman
    return selected, audit


def final_coverage_reference(
    matrix: pd.DataFrame,
    contract: dict[str, Any],
    names: list[str],
) -> dict[str, Any]:
    preprocessor = make_preprocessor(contract, names)
    values = np.asarray(preprocessor.fit_transform(matrix[names]), dtype=float)
    neighbors = NearestNeighbors(n_neighbors=2).fit(values)
    distances = neighbors.kneighbors(values, return_distance=True)[0][:, 1]
    quantile = float(contract["coverage"]["training_nearest_neighbor_quantile"])
    return {
        "metric": contract["coverage"]["distance"],
        "quantile": quantile,
        "threshold": float(np.quantile(distances, quantile, method="linear")),
        "training_pair_count": len(matrix),
        "minimum": float(np.min(distances)),
        "median": float(np.median(distances)),
        "maximum": float(np.max(distances)),
    }


def write_figure(summary: pd.DataFrame, path: Path) -> None:
    source = summary[summary["feature_view"].eq("core")].copy()
    holdouts = list(source["holdout"].drop_duplicates())
    models = list(source["model"].drop_duplicates())
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    x = np.arange(len(holdouts))
    width = 0.18
    for position, model_name in enumerate(models):
        group = source[source["model"].eq(model_name)].set_index("holdout").loc[holdouts]
        offset = (position - (len(models) - 1) / 2) * width
        axes[0].bar(x + offset, group["fold_spearman_mean"], width, label=model_name)
        axes[1].bar(x + offset, group["fold_ndcg_at_5_mean"], width, label=model_name)
    for axis, title, ylabel in (
        (axes[0], "Rang-korelacija", "Spearman"),
        (axes[1], "Kvalitet vrha rang-liste", "NDCG@5"),
    ):
        axis.set_title(title)
        labels = [
            value.replace("leave_", "").replace("_out", "") for value in holdouts
        ]
        axis.set_xticks(x, labels, rotation=20)
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", alpha=0.2)
    axes[1].legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    view = frame[columns].copy()
    for column in columns:
        if pd.api.types.is_float_dtype(view[column]):
            view[column] = view[column].map(
                lambda value: "NA" if pd.isna(value) else f"{value:.3f}"
            )
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    lines.extend(
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in view.itertuples(index=False, name=None)
    )
    return "\n".join(lines)


def write_report(
    out_dir: Path,
    matrix: pd.DataFrame,
    summary: pd.DataFrame,
    selected_view: str,
    ablation: pd.DataFrame,
    coverage: pd.DataFrame,
) -> None:
    primary = summary[
        summary["model"].eq("ridge") & summary["feature_view"].eq(selected_view)
    ].copy()
    model_table = summary[
        summary["feature_view"].eq(selected_view)
        & summary["holdout"].eq("leave_scenario_level_out")
    ].copy()
    outside = (
        coverage.groupby(["holdout", "feature_view"])["outside_training_p99"]
        .mean()
        .reset_index(name="outside_p99_share")
    )
    primary_table = markdown_table(
        primary,
        [
            "holdout",
            "oof_mae",
            "fold_spearman_mean",
            "fold_kendall_mean",
            "fold_ndcg_at_5_mean",
            "fold_top3_recall_mean",
        ],
    )
    model_table_markdown = markdown_table(
        model_table,
        [
            "model",
            "oof_mae",
            "fold_spearman_mean",
            "fold_kendall_mean",
            "fold_ndcg_at_5_mean",
            "fold_top3_recall_mean",
        ],
    )
    ablation_table = markdown_table(
        ablation,
        [
            "holdout",
            "extended_mae_improvement",
            "extended_spearman_delta",
            "extended_ndcg_delta",
            "decision",
        ],
    )
    coverage_table = markdown_table(
        outside,
        ["holdout", "feature_view", "outside_p99_share"],
    )
    report = f"""# Robustness i rangiranje koristi colocated distribucije

## Zaključani ugovor

- Akcija je unaprijed utvrđena: `use_colocated_distribution`.
- Ulaz čini samo post-execution dokaz opterećenog stanja.
- SQL tekst, šablon, dataset i identiteti nisu modelski ulazi.
- Ridge ostaje primarni estimator. Ostali modeli služe samo provjeri robustnosti.
- Jedinica je `{len(matrix)}` kontrafaktualnih parova, ne 225 ponovljenih runova.
- Tačan speedup je sekundarni izlaz. Primarna praktična svrha je prioritizacija.

## Primarni Ridge rezultat ({selected_view})

{primary_table}

## Mali robustness benchmark na neviđenom intenzitetu

{model_table_markdown}

Benchmark ne bira novi finalni model prema već posmatranom intensity holdoutu.
Pokazuje samo da li zaključak o rangiranju zavisi od Ridge regresije.

## Core naspram extended ulaza

Odabrani produkcijski pogled: `{selected_view}`.

{ablation_table}

OS i mrežna telemetrija ostaju u raw dokazu čak i kada nisu dio odabranog
modelskog ugovora.

## Upozorenje o pokrivenosti

{coverage_table}

P99 je empirijsko upozorenje u standardizovanom prostoru trening folda. Nije
statistička garancija niti formalni detektor novog tipa izvršenja.

## Granica tvrdnje

Model ne bira akciju, ne utvrđuje korijenski uzrok i ne obećava prenos tačnog
speedupa na proizvoljan hardver. Kada su repartition i semantička primjenjivost
colocation akcije već utvrđeni, model rangira koje izvršenje treba prvo
razmotriti.
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")


def write_checksums(out_dir: Path) -> None:
    outputs = sorted(
        path for path in out_dir.iterdir() if path.is_file() and path.name != "checksums.sha256"
    )
    lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in outputs]
    (out_dir / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    contract_path = args.contract.resolve()
    contract = read_contract(contract_path)
    matrix_path = (
        args.matrix.resolve()
        if args.matrix
        else (ROOT / str(contract["source_matrix"])).resolve()
    )
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[RANKING 1/5] validating frozen pair matrix and contracts", flush=True)
    matrix = pd.read_csv(matrix_path, low_memory=False)
    validate_matrix(matrix, contract)

    print("[RANKING 2/5] evaluating fixed estimators on grouped holdouts", flush=True)
    predictions, folds, summary, coverage = run_benchmark(matrix, contract)

    print("[RANKING 3/5] evaluating core versus extended evidence", flush=True)
    selected_view, ablation = feature_view_decision(summary, contract)
    selected_names = feature_views(contract)[selected_view]

    print("[RANKING 4/5] freezing the primary Ridge ranking model", flush=True)
    final_model = model_pipeline(contract, "ridge", selected_names)
    target = str(contract["target"]["field"])
    final_model.fit(matrix[selected_names], matrix[target].to_numpy(dtype=float))
    coverage_reference = final_coverage_reference(matrix, contract, selected_names)
    joblib.dump(final_model, out_dir / "colocation_ranking_model.joblib")

    predictions.to_csv(out_dir / "ranking_predictions.csv", index=False)
    folds.to_csv(out_dir / "ranking_fold_metrics.csv", index=False)
    summary.to_csv(out_dir / "ranking_summary.csv", index=False)
    coverage.to_csv(out_dir / "coverage_predictions.csv", index=False)
    ablation.to_csv(out_dir / "feature_view_ablation.csv", index=False)
    write_figure(summary, out_dir / "ranking_robustness.png")
    write_report(out_dir, matrix, summary, selected_view, ablation, coverage)

    print("[RANKING 5/5] writing manifest and checksums", flush=True)
    manifest = {
        "contract_version": contract["contract_version"],
        "program_id": contract["program_id"],
        "mitigation_action": contract["mitigation_action"],
        "pair_count": len(matrix),
        "primary_estimator": contract["primary_estimator"],
        "benchmark_estimators": list(contract["estimators"]),
        "selected_feature_view": selected_view,
        "selected_feature_count": len(selected_names),
        "selected_feature_names": selected_names,
        "benchmark_policy": contract["benchmark_policy"],
        "holdouts": contract["holdouts"],
        "coverage_reference": coverage_reference,
        "input_scope": "stressed_post_execution_pair_median",
        "raw_sql_in_model": False,
        "action_selector_included": False,
        "frozen_before_n3_holdout": True,
    }
    (out_dir / "benchmark_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_checksums(out_dir)
    print(out_dir / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
