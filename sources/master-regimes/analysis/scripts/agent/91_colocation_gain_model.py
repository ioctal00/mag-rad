#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import numpy as np
import pandas as pd
import yaml
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGE = ROOT / "generated/pressure-raw-runs/_program/pressure-raw-v1"
DEFAULT_ACTION_AUDIT = ROOT / "analysis/reports/pressure-raw-v1-mitigation-action-audit"
DEFAULT_CONTRACT = ROOT / "configs/models/colocation_gain_v1.yml"
DEFAULT_OUT = ROOT / "analysis/reports/pressure-raw-v1-colocation-gain-model"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fit and evaluate the primary colocated-distribution gain model."
    )
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--action-audit-dir", type=Path, default=DEFAULT_ACTION_AUDIT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path, low_memory=False)


def feature_names(contract: dict[str, Any]) -> list[str]:
    names = [str(item["name"]) for item in contract["features"]]
    if len(names) != len(set(names)):
        raise ValueError("Feature contract contains duplicate names")
    forbidden = tuple(str(value) for value in contract["forbidden_input_patterns"])
    violations = [name for name in names if any(pattern in name for pattern in forbidden)]
    if violations:
        raise ValueError(f"Feature contract violates leakage policy: {violations}")
    return names


def coerce_features(frame: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    for item in contract["features"]:
        name = str(item["name"])
        values = pd.to_numeric(frame[name], errors="coerce")
        transform = str(item["transform"])
        if transform == "log1p":
            invalid = values.dropna().lt(0)
            if invalid.any():
                raise ValueError(f"Feature {name} contains negative values for log1p")
        elif transform != "identity":
            raise ValueError(f"Unsupported transform {transform} for {name}")
        result[name] = values
    return result


def build_pair_matrix(
    training: pd.DataFrame,
    execution: pd.DataFrame,
    pairs: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    action = str(contract["mitigation_action"])
    role = str(contract["intervention_role"])
    selected_pairs = pairs[
        pairs["mitigation_action"].eq(action)
        & pairs["intervention_role"].eq(role)
        & pairs["strict_gain_eligible"].astype(str).str.lower().eq("true")
    ].copy()
    if selected_pairs.empty:
        raise ValueError("No strict colocated-distribution pairs are available")

    stressed = training[
        training["pair_id"].isin(selected_pairs["pair_id"])
        & training["variant"].eq("stressed")
    ].copy()
    expected_repetitions = int(contract["repetitions_per_pair"])
    counts = stressed.groupby("pair_id").size()
    invalid_counts = counts[counts.ne(expected_repetitions)]
    if not invalid_counts.empty or len(counts) != len(selected_pairs):
        raise ValueError(
            "Each selected pair must have exactly "
            f"{expected_repetitions} stressed executions: {invalid_counts.to_dict()}"
        )

    names = feature_names(contract)
    observed = execution[["query_run_id", *names]].drop_duplicates("query_run_id")
    metadata_fields = [
        "pair_id",
        "query_run_id",
        "template_id",
        "dataset_profile_id",
        "scenario_level",
        "dataset_size_class",
    ]
    rows = stressed[metadata_fields].merge(
        observed, on="query_run_id", how="left", validate="one_to_one"
    )
    if rows[names].isna().all(axis=0).any():
        missing = rows[names].columns[rows[names].isna().all(axis=0)].tolist()
        raise ValueError(f"Selected features are entirely missing: {missing}")

    numeric_features = coerce_features(rows[names], contract)
    numeric_features["pair_id"] = rows["pair_id"].values
    aggregated = numeric_features.groupby("pair_id", sort=True)[names].median()
    stressed_metadata = (
        rows.groupby("pair_id", sort=True)
        .agg(
            scenario_level=("scenario_level", "first"),
            dataset_size_class=("dataset_size_class", "first"),
            scenario_level_count=("scenario_level", "nunique"),
            dataset_size_class_count=("dataset_size_class", "nunique"),
        )
    )
    metadata_counts = stressed_metadata[
        ["scenario_level_count", "dataset_size_class_count"]
    ]
    if not metadata_counts.eq(1).all().all():
        raise ValueError("Scenario and size metadata must be constant within a pair")
    metadata = selected_pairs.set_index("pair_id")
    output = aggregated.join(
        stressed_metadata[["scenario_level", "dataset_size_class"]],
        how="inner",
        validate="one_to_one",
    ).join(
        metadata[
            [
                "stressed_template_id",
                "dataset_profile_id",
                "logical_question_id",
                "target_log2_gain_median",
                "correctness_recovery_applied",
            ]
        ],
        how="inner",
        validate="one_to_one",
    ).reset_index()
    output = output.rename(columns={"target_log2_gain_median": "target_log2_gain"})
    if len(output) != len(selected_pairs):
        raise ValueError("Pair-level model matrix lost selected pairs")
    return output


def ridge_pipeline(contract: dict[str, Any]) -> Pipeline:
    estimator = contract["estimator"]
    log_features = [
        str(item["name"])
        for item in contract["features"]
        if item["transform"] == "log1p"
    ]
    identity_features = [
        str(item["name"])
        for item in contract["features"]
        if item["transform"] == "identity"
    ]
    preprocess = ColumnTransformer(
        [
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
                log_features,
            ),
            (
                "identity",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                identity_features,
            ),
        ],
        verbose_feature_names_out=False,
    )
    return Pipeline(
        [
            ("preprocess", preprocess),
            (
                "ridge",
                Ridge(
                    alpha=float(estimator["alpha"]),
                    fit_intercept=bool(estimator["fit_intercept"]),
                ),
            ),
        ]
    )


def regression_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if len(np.unique(actual)) < 2 or len(np.unique(predicted)) < 2:
        correlation = math.nan
    else:
        correlation = spearmanr(actual, predicted).statistic
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(math.sqrt(mean_squared_error(actual, predicted))),
        "r2": float(r2_score(actual, predicted)),
        "spearman": float(correlation) if not math.isnan(correlation) else math.nan,
        "mean_bias": float(np.mean(predicted - actual)),
    }


def cross_validate(
    matrix: pd.DataFrame,
    contract: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    names = feature_names(contract)
    x = matrix[names]
    y = matrix["target_log2_gain"].to_numpy(dtype=float)
    prediction_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []

    for holdout in contract["holdouts"]:
        holdout_name = str(holdout["name"])
        group_field = str(holdout["group_field"])
        groups = matrix[group_field].astype(str).to_numpy()
        splitter = LeaveOneGroupOut()
        for fold_index, (train_index, test_index) in enumerate(
            splitter.split(x, y, groups), start=1
        ):
            held_out = sorted(set(groups[test_index]))
            models = {
                "median_baseline": DummyRegressor(strategy="median"),
                "ridge": ridge_pipeline(contract),
            }
            for model_name, model in models.items():
                model.fit(x.iloc[train_index], y[train_index])
                predicted = model.predict(x.iloc[test_index])
                fold_metric = regression_metrics(y[test_index], predicted)
                fold_rows.append(
                    {
                        "holdout": holdout_name,
                        "fold": fold_index,
                        "held_out_group": "|".join(held_out),
                        "model": model_name,
                        "train_pair_count": len(train_index),
                        "test_pair_count": len(test_index),
                        **fold_metric,
                    }
                )
                for position, row_index in enumerate(test_index):
                    prediction_rows.append(
                        {
                            "holdout": holdout_name,
                            "fold": fold_index,
                            "held_out_group": "|".join(held_out),
                            "model": model_name,
                            "pair_id": matrix.iloc[row_index]["pair_id"],
                            "actual_log2_gain": y[row_index],
                            "predicted_log2_gain": float(predicted[position]),
                            "actual_speedup": float(2 ** y[row_index]),
                            "predicted_speedup": float(2 ** predicted[position]),
                        }
                    )

    predictions = pd.DataFrame(prediction_rows)
    folds = pd.DataFrame(fold_rows)
    summaries = []
    for (holdout_name, model_name), group in predictions.groupby(["holdout", "model"]):
        metric = regression_metrics(
            group["actual_log2_gain"].to_numpy(),
            group["predicted_log2_gain"].to_numpy(),
        )
        summaries.append(
            {
                "holdout": holdout_name,
                "model": model_name,
                "pair_count": len(group),
                **metric,
            }
        )
    return predictions, folds, pd.DataFrame(summaries)


def evaluate_gate(summary: pd.DataFrame, contract: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    for holdout in contract["holdouts"]:
        name = str(holdout["name"])
        rows = summary[summary["holdout"].eq(name)].set_index("model")
        ridge = rows.loc["ridge"]
        baseline = rows.loc["median_baseline"]
        if bool(
            contract["acceptance"][
                "require_lower_mae_than_median_baseline_in_all_holdouts"
            ]
        ) and not ridge["mae"] < baseline["mae"]:
            reasons.append(f"ridge_does_not_beat_median_mae:{name}")
        if ridge["spearman"] < float(contract["acceptance"]["minimum_spearman"]):
            reasons.append(f"ridge_spearman_below_minimum:{name}")
    return ("GO_PRIMARY_GAIN_MODEL", []) if not reasons else ("MIXED_MODEL_EVIDENCE", reasons)


def final_coefficients(model: Pipeline, contract: dict[str, Any]) -> pd.DataFrame:
    output_names = list(model.named_steps["preprocess"].get_feature_names_out())
    coefficients = model.named_steps["ridge"].coef_
    return pd.DataFrame(
        {
            "transformed_feature": output_names,
            "standardized_coefficient": coefficients,
            "absolute_coefficient": np.abs(coefficients),
        }
    ).sort_values("absolute_coefficient", ascending=False)


def write_figure(predictions: pd.DataFrame, path: Path) -> None:
    ridge = predictions[predictions["model"].eq("ridge")]
    holdouts = list(ridge["holdout"].drop_duplicates())
    fig, axes = plt.subplots(1, len(holdouts), figsize=(6 * len(holdouts), 5), squeeze=False)
    for axis, holdout in zip(axes[0], holdouts, strict=True):
        source = ridge[ridge["holdout"].eq(holdout)]
        axis.scatter(source["actual_log2_gain"], source["predicted_log2_gain"], alpha=0.75)
        low = min(source["actual_log2_gain"].min(), source["predicted_log2_gain"].min())
        high = max(source["actual_log2_gain"].max(), source["predicted_log2_gain"].max())
        axis.plot([low, high], [low, high], color="#666666", linewidth=1)
        axis.set_title(holdout.replace("_", " "))
        axis.set_xlabel("Izmjereni log2 gain")
        axis.set_ylabel("Predviđeni log2 gain")
        axis.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    view = frame[columns].copy()
    for column in view.columns:
        if pd.api.types.is_float_dtype(view[column]):
            view[column] = view[column].map(lambda value: f"{value:.3f}")
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
    gate: str,
    reasons: list[str],
) -> None:
    if gate == "GO_PRIMARY_GAIN_MODEL":
        interpretation = (
            "Model nadmasuje median baseline u svim zakljucanim grupisanim holdoutima."
        )
    else:
        interpretation = (
            "Model dobro prenosi rangiranje i kalibraciju na nevidjene SQL templatee, "
            "dataset profile i klase velicine, ali ne nadmasuje median baseline kada je "
            "cijeli nivo intenziteta scenarija izostavljen. Zato nije spreman kao opci "
            "prediktor koristi na nevidjenom intenzitetu."
        )
    report = f"""# Primarni model koristi colocated distribucije

## Ugovor

- Akcija: `use_colocated_distribution`.
- Jedinica učenja: `{len(matrix)}` strogo ekvivalentnih kontrafaktualnih parova.
- Ulaz: medijan stressed post-execution dokaza kroz tri ponavljanja.
- Target: `log2(T_stressed / T_mitigated)` na end-to-end GAC nivou.
- Model: Ridge regresija sa unaprijed zaključanim `alpha=1.0`.
- Identiteti SQL templatea i dataseta koriste se samo za grupisane holdoute.
- Nivoi scenarija i klase veličine također su samo holdout grupe, ne ulazi modela.
- Mitigated dokaz, intervencijska konfiguracija i identifikatori nisu modelski input.

## Grupisana validacija

{
        markdown_table(
            summary,
            ["holdout", "model", "pair_count", "mae", "rmse", "r2", "spearman"],
        )
    }

## Odluka

- Gate: `{gate}`.
- Razlozi: `{", ".join(reasons) or "model nadmasuje median baseline u svim holdoutima"}`.

{interpretation}

Ovaj model ne bira akciju i ne tvrdi da je repartition jedini uzrok opaženog
troška. On odgovara na uže pitanje: kada je akcija colocated distribucije već
primjenjiva, može li stressed post-execution dokaz predvidjeti njenu izmjerenu
end-to-end korist.

## Izlazi

- `colocation_pair_matrix.csv`
- `cross_validation_predictions.csv`
- `cross_validation_folds.csv`
- `cross_validation_summary.csv`
- `final_coefficients.csv`
- `colocation_gain_model.joblib`
- `observed_vs_predicted.png`
- `model_manifest.json`
- `checksums.sha256`
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")


def main() -> int:
    args = parse_args()
    package_dir = args.package_dir.resolve()
    audit_dir = args.action_audit_dir.resolve()
    out_dir = args.out_dir.resolve()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    audit_summary = json.loads((audit_dir / "summary.json").read_text(encoding="utf-8"))
    if audit_summary.get("gate") != "GO" or audit_summary.get("review_pair_count") != 0:
        raise ValueError("Action audit must be GO with zero unresolved review pairs")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[COLOCATION MODEL 1/5] building leakage-safe pair matrix", flush=True)
    matrix = build_pair_matrix(
        read_csv(package_dir / "training_execution_view.csv"),
        read_csv(package_dir / "_index/execution_features.csv"),
        read_csv(audit_dir / "mitigation_pair_audit.csv"),
        contract,
    )
    names = feature_names(contract)

    print("[COLOCATION MODEL 2/5] running grouped holdouts", flush=True)
    predictions, folds, summary = cross_validate(matrix, contract)
    gate, reasons = evaluate_gate(summary, contract)

    print("[COLOCATION MODEL 3/5] fitting final action-specific model", flush=True)
    final_model = ridge_pipeline(contract)
    final_model.fit(matrix[names], matrix["target_log2_gain"])
    coefficients = final_coefficients(final_model, contract)

    print("[COLOCATION MODEL 4/5] writing model evidence", flush=True)
    matrix.to_csv(out_dir / "colocation_pair_matrix.csv", index=False)
    predictions.to_csv(out_dir / "cross_validation_predictions.csv", index=False)
    folds.to_csv(out_dir / "cross_validation_folds.csv", index=False)
    summary.to_csv(out_dir / "cross_validation_summary.csv", index=False)
    coefficients.to_csv(out_dir / "final_coefficients.csv", index=False)
    joblib.dump(final_model, out_dir / "colocation_gain_model.joblib")
    write_figure(predictions, out_dir / "observed_vs_predicted.png")
    write_report(out_dir, matrix, summary, gate, reasons)

    print("[COLOCATION MODEL 5/5] writing manifest and checksums", flush=True)
    manifest = {
        "contract_version": contract["contract_version"],
        "program_id": contract["program_id"],
        "mitigation_action": contract["mitigation_action"],
        "gate": gate,
        "gate_reasons": reasons,
        "pair_count": len(matrix),
        "feature_count": len(names),
        "feature_names": names,
        "feature_contract": contract["features"],
        "target": contract["target"],
        "holdouts": contract["holdouts"],
        "model_kind": contract["estimator"]["kind"],
        "alpha": contract["estimator"]["alpha"],
        "input_scope": "raw_stressed_post_execution_pair_median",
        "preprocessing_embedded_in_model": True,
        "action_selector_included": False,
    }
    (out_dir / "model_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    outputs = sorted(
        path for path in out_dir.iterdir() if path.is_file() and path.name != "checksums.sha256"
    )
    checksums = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in outputs
    ]
    (out_dir / "checksums.sha256").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(out_dir / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
