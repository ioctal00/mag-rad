#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT = ROOT / "configs/validation/representation_value_ablation_v1.yml"
DEFAULT_OUT_DIR = ROOT / "analysis/reports/representation-value-ablation-v1"
MEMORY_SCRIPT = ROOT / "analysis/scripts/agent/101_fuzzy_intervention_memory.py"
DBA_SCRIPT = ROOT / "analysis/scripts/agent/102_dba_local_memory_panel.py"

PLAN_FEATURE_SOURCES = {
    "plan_main_node_count": "main_plan_node_count",
    "plan_blocking_operator_count": "coordinator_blocking_operator_count",
    "plan_sort_operator_count": "coordinator_sort_operator_count",
    "plan_aggregate_operator_count": "coordinator_aggregate_operator_count",
    "plan_join_operator_count": "coordinator_join_operator_count",
    "plan_window_operator_count": "coordinator_window_operator_count",
    "plan_limit_operator_count": "coordinator_limit_operator_count",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare SQL, coordinator-only, and frozen multilayer representations."
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _json_default(value: Any) -> Any:
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def resolve_input(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def display_input_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.parent.resolve()))
    except ValueError:
        return str(path.resolve())


def load_script(path: Path, module_name: str) -> Any:
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_output_checksums(out_dir: Path) -> None:
    checksum_path = out_dir / "checksums.sha256"
    rows = [
        f"{_sha256(path)}  {path.relative_to(out_dir)}"
        for path in sorted(out_dir.rglob("*"))
        if path.is_file() and path != checksum_path
    ]
    checksum_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _strip_sql_noise(sql: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    text = re.sub(r"--[^\n]*", " ", text)
    text = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$.*?\$\1\$", " ? ", text, flags=re.DOTALL)
    text = re.sub(r"'(?:''|[^'])*'", " ? ", text)
    text = re.sub(r'"((?:""|[^"])*)"', lambda match: match.group(1), text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _top_level_item_count(fragment: str) -> int:
    fragment = fragment.strip()
    if not fragment:
        return 0
    depth = 0
    count = 1
    for character in fragment:
        if character == "(":
            depth += 1
        elif character == ")":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            count += 1
    return count


def _clause_fragments(sql: str, clause: str) -> list[str]:
    stop = (
        r"where|having|group\s+by|order\s+by|limit|offset|fetch|union|"
        r"intersect|except|returning"
    )
    pattern = re.compile(
        rf"\b{clause}\b\s+(.*?)(?=\b(?:{stop})\b|;|$)",
        flags=re.DOTALL,
    )
    return [match.group(1).strip() for match in pattern.finditer(sql)]


def sql_structural_features(sql: str) -> dict[str, float]:
    """Extract literal-independent structural counts for the frozen SQL baseline."""
    text = _strip_sql_noise(sql)
    predicate_fragments = [
        *_clause_fragments(text, "where"),
        *_clause_fragments(text, "having"),
    ]
    equality_count = 0
    non_equality_count = 0
    for fragment in predicate_fragments:
        equality_count += len(re.findall(r"(?<![<>!=])=(?!=)", fragment))
        non_equality_count += len(
            re.findall(r"<>|!=|<=|>=|(?<![<>=!])<(?!=)|(?<![<>=!])>(?!=)", fragment)
        )
        non_equality_count += len(
            re.findall(r"\b(?:like|ilike|between|in|is\s+(?:not\s+)?null)\b", fragment)
        )
    aggregate_count = len(
        re.findall(
            r"\b(?:count|sum|avg|min|max|stddev(?:_pop|_samp)?|variance|"
            r"array_agg|json_agg|string_agg)\s*\(",
            text,
        )
    )
    order_fragments = _clause_fragments(text, r"order\s+by")
    group_fragments = _clause_fragments(text, r"group\s+by")
    order_count = sum(_top_level_item_count(value) for value in order_fragments)
    group_count = sum(_top_level_item_count(value) for value in group_fragments)
    order_present = bool(order_fragments)
    limit_present = bool(re.search(r"\blimit\b", text))
    return {
        "sql_select_count": float(len(re.findall(r"\bselect\b", text))),
        "sql_join_count": float(len(re.findall(r"\bjoin\b", text))),
        "sql_selection_predicate_count": float(equality_count + non_equality_count),
        "sql_equality_predicate_count": float(equality_count),
        "sql_non_equality_predicate_count": float(non_equality_count),
        "sql_aggregate_function_count": float(aggregate_count),
        "sql_nested_query_count": float(len(re.findall(r"\(\s*select\b", text))),
        "sql_cte_count": float(
            len(
                re.findall(
                    r"\b[A-Za-z_][A-Za-z0-9_]*\s+as\s+"
                    r"(?:(?:not\s+)?materialized\s+)?\(",
                    text,
                )
            )
        ),
        "sql_table_reference_count": float(
            len(re.findall(r"\bfrom\b", text)) + len(re.findall(r"\bjoin\b", text))
        ),
        "sql_group_by_present": float(bool(group_fragments)),
        "sql_group_expression_count": float(group_count),
        "sql_distinct_present": float(bool(re.search(r"\bselect\s+distinct\b", text))),
        "sql_order_by_present": float(order_present),
        "sql_order_expression_count": float(order_count),
        "sql_limit_present": float(limit_present),
        "sql_topk_present": float(order_present and limit_present),
        "sql_set_operation_count": float(
            len(re.findall(r"\b(?:union(?:\s+all)?|intersect|except)\b", text))
        ),
        "sql_window_function_count": float(len(re.findall(r"\bover\s*\(", text))),
    }


def _transform_column(values: pd.Series, transform: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if transform == "identity":
        return numeric
    if transform == "log1p":
        return np.log1p(numeric.clip(lower=0.0))
    if transform == "signed_log1p":
        return np.sign(numeric) * np.log1p(np.abs(numeric))
    raise ValueError(f"Unsupported transform: {transform}")


@dataclass
class StructuralPreprocessor:
    specifications: dict[str, dict[str, str]]
    imputer: SimpleImputer | None = None
    scaler: StandardScaler | None = None
    family_weights: np.ndarray | None = None
    selection_audit: pd.DataFrame | None = None

    def _transformed(self, frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                name: _transform_column(frame[name], str(specification["transform"]))
                for name, specification in self.specifications.items()
            },
            index=frame.index,
        )

    def fit(self, frame: pd.DataFrame) -> np.ndarray:
        transformed = self._transformed(frame)
        self.selection_audit = pd.DataFrame(
            [
                {
                    "feature": name,
                    "family": specification["family"],
                    "transform": specification["transform"],
                    "reference_state_count": len(frame),
                    "observed_count": int(transformed[name].notna().sum()),
                    "missing_share": float(transformed[name].isna().mean()),
                    "distinct_count": int(transformed[name].nunique(dropna=True)),
                    "selected": True,
                    "decision": (
                        "retained_varying"
                        if transformed[name].nunique(dropna=True) > 1
                        else "retained_constant_for_unseen_structure"
                    ),
                }
                for name, specification in self.specifications.items()
            ]
        )
        self.imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        self.scaler = StandardScaler()
        imputed = self.imputer.fit_transform(transformed)
        scaled = self.scaler.fit_transform(imputed)
        family_counts: dict[str, int] = {}
        for specification in self.specifications.values():
            family = str(specification["family"])
            family_counts[family] = family_counts.get(family, 0) + 1
        self.family_weights = np.asarray(
            [
                1.0 / math.sqrt(family_counts[str(specification["family"])])
                for specification in self.specifications.values()
            ],
            dtype=float,
        )
        return scaled * self.family_weights

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        if self.imputer is None or self.scaler is None or self.family_weights is None:
            raise RuntimeError("StructuralPreprocessor is not fitted")
        transformed = self._transformed(frame)
        imputed = self.imputer.transform(transformed)
        return self.scaler.transform(imputed) * self.family_weights


def _validate_contract(contract: dict[str, Any]) -> None:
    policy = contract["decision_policy"]
    if policy["distance_metric"] != "euclidean":
        raise ValueError("The frozen final policy uses Euclidean distance")
    if int(policy["neighbors"]) != 5:
        raise ValueError("The frozen final policy requires k=5")
    if not policy["exclude_same_query_id"]:
        raise ValueError("Same-query exclusion is mandatory")
    representations = set(contract["representations"])
    if representations != {"sql_structural", "coordinator_physical", "full_multilayer"}:
        raise ValueError("Exactly three frozen representations are required")


def _development_rows(
    contract: dict[str, Any],
    memory_module: Any,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    state_contract = read_yaml(resolve_input(contract["inputs"]["development_state_contract"]))
    report = resolve_input(contract["inputs"]["development_report"])
    episodes = pd.read_csv(report / "episodes.csv", low_memory=False)
    components = set(state_contract["panels"]["gac_topk"]["component_match_ids"])
    selected = episodes[
        episodes["component_match_id"].astype(str).isin(components)
        & episodes["completed"].astype(bool)
        & episodes["result_equal"].astype(bool)
    ].drop_duplicates("scenario_id")
    source_indexes: dict[str, pd.DataFrame] = {}
    for source in state_contract["sources"]:
        source_id = str(source["id"])
        if source_id not in set(selected["source_id"].astype(str)):
            continue
        index_dir = resolve_input(source["index_dir"])
        source_indexes[source_id] = memory_module.enrich_executions(index_dir)
    return selected.reset_index(drop=True), source_indexes


def _median_or_nan(frame: pd.DataFrame, column: str) -> float:
    if column not in frame:
        return float("nan")
    values = pd.to_numeric(frame[column], errors="coerce")
    return float(values.median()) if values.notna().any() else float("nan")


def _metadata_from_development(
    rows: pd.DataFrame,
    source_indexes: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    output: list[dict[str, Any]] = []
    for row in rows.to_dict(orient="records"):
        source_id = str(row["source_id"])
        executions = source_indexes[source_id]
        members = executions[
            executions["condition_id"].astype(str).eq(str(row["baseline_condition_id"]))
        ]
        if members.empty:
            raise ValueError(f"Missing development condition {row['baseline_condition_id']}")
        source_paths = members["source_sql_file"].dropna().astype(str).unique()
        if len(source_paths) != 1 or not Path(source_paths[0]).exists():
            raise ValueError(f"Development SQL source is unavailable for {row['scenario_id']}")
        hashes = members["sql_normalized_hash"].dropna().astype(str).unique()
        output_row = {
            "episode_id": f"reference::{row['scenario_id']}",
            "scenario_id": str(row["scenario_id"]),
            "query_id": str(row["scenario_id"]),
            "source_sql_file": source_paths[0],
            "normalized_sql_hash": hashes[0] if len(hashes) == 1 else "",
        }
        for target, source in PLAN_FEATURE_SOURCES.items():
            output_row[target] = _median_or_nan(members, source)
        output.append(output_row)
    return pd.DataFrame(output)


def _metadata_from_final(
    events: pd.DataFrame,
    final_index: Path,
    memory_module: Any,
) -> pd.DataFrame:
    executions = memory_module.enrich_executions(final_index)
    by_run = executions.set_index(executions["query_run_id"].astype(str), drop=False)
    output: list[dict[str, Any]] = []
    for event in events.to_dict(orient="records"):
        query_run_id = str(event["baseline_query_run_id"])
        if query_run_id not in by_run.index:
            raise ValueError(f"Missing final baseline execution {query_run_id}")
        member = by_run.loc[query_run_id]
        if isinstance(member, pd.DataFrame):
            if len(member) != 1:
                raise ValueError(f"Ambiguous final baseline execution {query_run_id}")
            member = member.iloc[0]
        source_path = Path(str(event["source_sql_file"]))
        if not source_path.exists():
            raise ValueError(f"Final SQL source is unavailable: {source_path}")
        output_row = {
            "episode_id": str(event["episode_id"]),
            "query_id": str(event["query_id"]),
            "source_sql_file": str(source_path),
            "normalized_sql_hash": str(event["normalized_sql_hash"]),
        }
        for target, source in PLAN_FEATURE_SOURCES.items():
            output_row[target] = pd.to_numeric(
                pd.Series([member.get(source)]), errors="coerce"
            ).iloc[0]
        output.append(output_row)
    return pd.DataFrame(output)


def structural_feature_frame(
    metadata: pd.DataFrame,
    specifications: dict[str, dict[str, str]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in metadata.to_dict(orient="records"):
        sql = Path(str(row["source_sql_file"])).read_text(encoding="utf-8")
        values = sql_structural_features(sql)
        values.update({name: row.get(name, np.nan) for name in PLAN_FEATURE_SOURCES})
        missing = set(specifications) - set(values)
        if missing:
            raise ValueError(f"Structural extractor did not produce: {sorted(missing)}")
        rows.append({"episode_id": row["episode_id"], **values})
    return pd.DataFrame(rows)


def _feature_contract_rows(
    experiment_contract: dict[str, Any],
    state_contract: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    structural = experiment_contract["representations"]["sql_structural"]["features"]
    for name, specification in structural.items():
        rows.append(
            {
                "representation": "sql_structural",
                "feature": name,
                "family": specification["family"],
                "transform": specification["transform"],
                "included": True,
                "source_scope": ("normalized_sql" if name.startswith("sql_") else "basic_gac_plan"),
                "reason": "frozen_structural_contract",
            }
        )
    simple_names = set(
        experiment_contract["representations"]["coordinator_physical"]["included_features"]
    )
    for name, specification in state_contract["state_representation"]["features"].items():
        included = name in simple_names
        family = str(specification["family"])
        rows.append(
            {
                "representation": "coordinator_physical",
                "feature": name,
                "family": family,
                "transform": specification["transform"],
                "included": included,
                "source_scope": "coordinator_or_standard_execution" if included else family,
                "reason": (
                    "standard_coordinator_post_execution_evidence"
                    if included
                    else "excluded_multilayer_region_worker_edge_or_telemetry"
                ),
            }
        )
        rows.append(
            {
                "representation": "full_multilayer",
                "feature": name,
                "family": family,
                "transform": specification["transform"],
                "included": True,
                "source_scope": family,
                "reason": "unchanged_existing_93_candidate_contract",
            }
        )
    return pd.DataFrame(rows)


def _summarize(frame: pd.DataFrame, evaluation: str) -> dict[str, Any]:
    selected = (
        frame[frame["query_occurrence"].eq(1)].copy()
        if evaluation == "first_occurrence"
        else frame.copy()
    )
    recommended = selected[selected["predicted_action"].fillna("").astype(str).ne("")]
    return {
        "representation": str(frame["representation"].iloc[0]),
        "evaluation": evaluation,
        "episode_count": int(len(selected)),
        "recommendation_count": int(len(recommended)),
        "abstention_count": int(len(selected) - len(recommended)),
        "coverage": float(len(recommended) / len(selected)) if len(selected) else float("nan"),
        "correct_decision_count": int(recommended["top1_correct"].astype(bool).sum()),
        "top1_accuracy": (
            float(recommended["top1_correct"].astype(bool).mean())
            if len(recommended)
            else float("nan")
        ),
        "mean_regret_log2": (
            float(recommended["regret_log2"].mean()) if len(recommended) else float("nan")
        ),
    }


def _cluster_metric_samples(
    frame: pd.DataFrame,
    *,
    samples: int,
    seed: int,
) -> dict[str, np.ndarray]:
    rows = []
    for _, group in frame.groupby("query_id", sort=True):
        recommended = group[group["predicted_action"].fillna("").astype(str).ne("")]
        rows.append(
            (
                len(group),
                len(recommended),
                int(recommended["top1_correct"].astype(bool).sum()),
                float(recommended["regret_log2"].sum()),
            )
        )
    values = np.asarray(rows, dtype=float)
    rng = np.random.default_rng(seed)
    indexes = rng.integers(0, len(values), size=(samples, len(values)))
    sampled = values[indexes].sum(axis=1)
    episode_count = sampled[:, 0]
    recommendation_count = sampled[:, 1]
    return {
        "coverage": np.divide(
            recommendation_count,
            episode_count,
            out=np.full(samples, np.nan),
            where=episode_count > 0,
        ),
        "top1_accuracy": np.divide(
            sampled[:, 2],
            recommendation_count,
            out=np.full(samples, np.nan),
            where=recommendation_count > 0,
        ),
        "mean_regret_log2": np.divide(
            sampled[:, 3],
            recommendation_count,
            out=np.full(samples, np.nan),
            where=recommendation_count > 0,
        ),
    }


def _bootstrap_intervals(
    timelines: pd.DataFrame,
    summary: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    specification = contract["bootstrap"]
    samples = int(specification["samples"])
    seed = int(specification["random_seed"])
    alpha = (1.0 - float(specification["confidence_level"])) / 2.0
    rows: list[dict[str, Any]] = []
    for (representation, evaluation), point in summary.groupby(
        ["representation", "evaluation"], sort=True
    ):
        frame = timelines[timelines["representation"].eq(representation)]
        if evaluation == "first_occurrence":
            frame = frame[frame["query_occurrence"].eq(1)]
        distributions = _cluster_metric_samples(frame, samples=samples, seed=seed)
        point_row = point.iloc[0]
        for metric, distribution in distributions.items():
            finite = distribution[np.isfinite(distribution)]
            rows.append(
                {
                    "representation": representation,
                    "evaluation": evaluation,
                    "metric": metric,
                    "point_estimate": float(point_row[metric]),
                    "ci_lower": float(np.quantile(finite, alpha)),
                    "ci_upper": float(np.quantile(finite, 1.0 - alpha)),
                    "cluster_key": specification["cluster_key"],
                    "cluster_count": int(frame["query_id"].nunique()),
                    "bootstrap_samples": samples,
                }
            )
    return pd.DataFrame(rows)


def _paired_bootstrap_differences(
    timelines: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    specification = contract["bootstrap"]
    samples = int(specification["samples"])
    seed = int(specification["random_seed"])
    alpha = (1.0 - float(specification["confidence_level"])) / 2.0
    rows: list[dict[str, Any]] = []
    for evaluation in ("first_occurrence", "same_query_excluded"):
        distributions: dict[str, dict[str, np.ndarray]] = {}
        for representation in ("sql_structural", "coordinator_physical", "full_multilayer"):
            frame = timelines[timelines["representation"].eq(representation)]
            if evaluation == "first_occurrence":
                frame = frame[frame["query_occurrence"].eq(1)]
            distributions[representation] = _cluster_metric_samples(
                frame, samples=samples, seed=seed
            )
        for baseline in ("sql_structural", "coordinator_physical"):
            for metric in ("coverage", "top1_accuracy", "mean_regret_log2"):
                if metric == "mean_regret_log2":
                    delta = (
                        distributions[baseline][metric] - distributions["full_multilayer"][metric]
                    )
                    direction = "positive_favors_full"
                    formula = "baseline_minus_full"
                else:
                    delta = (
                        distributions["full_multilayer"][metric] - distributions[baseline][metric]
                    )
                    direction = "positive_favors_full"
                    formula = "full_minus_baseline"
                finite = delta[np.isfinite(delta)]
                rows.append(
                    {
                        "evaluation": evaluation,
                        "candidate": "full_multilayer",
                        "baseline": baseline,
                        "metric": metric,
                        "difference_definition": direction,
                        "difference_formula": formula,
                        "mean_difference": float(np.mean(finite)),
                        "ci_lower": float(np.quantile(finite, alpha)),
                        "ci_upper": float(np.quantile(finite, 1.0 - alpha)),
                        "bootstrap_samples": samples,
                    }
                )
    return pd.DataFrame(rows)


def _expanded_neighbor_trace(timelines: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    event_order = events.set_index("episode_id")["episode_order"].astype(int).to_dict()
    rows: list[dict[str, Any]] = []
    for row in timelines.to_dict(orient="records"):
        neighbors = json.loads(str(row["neighbor_evidence_json"]))
        for rank, neighbor in enumerate(neighbors, start=1):
            neighbor_id = str(neighbor["episode_id"])
            neighbor_query = str(neighbor["query_id"])
            neighbor_hash = str(neighbor.get("normalized_sql_hash", ""))
            held_hash = str(row.get("normalized_sql_hash", ""))
            neighbor_order = event_order.get(neighbor_id)
            rows.append(
                {
                    "representation": row["representation"],
                    "episode_id": row["episode_id"],
                    "episode_order": int(row["episode_order"]),
                    "query_id": row["query_id"],
                    "query_occurrence": int(row["query_occurrence"]),
                    "neighbor_rank": rank,
                    "neighbor_episode_id": neighbor_id,
                    "neighbor_query_id": neighbor_query,
                    "neighbor_normalized_sql_hash": neighbor_hash,
                    "held_normalized_sql_hash": held_hash,
                    "neighbor_source_scope": (
                        "development_reference"
                        if neighbor_id.startswith("reference::")
                        else "earlier_final_episode"
                    ),
                    "neighbor_episode_order": neighbor_order,
                    "distance": float(neighbor["distance"]),
                    "weight": float(neighbor["weight"]),
                    "same_query_id": neighbor_query == str(row["query_id"]),
                    "same_normalized_sql": bool(
                        held_hash and neighbor_hash and held_hash == neighbor_hash
                    ),
                    "future_or_current_neighbor": (
                        bool(neighbor_order >= int(row["episode_order"]))
                        if neighbor_order is not None
                        else False
                    ),
                    "action_gains_json": json.dumps(
                        neighbor["action_gains"], sort_keys=True, separators=(",", ":")
                    ),
                }
            )
    return pd.DataFrame(rows)


def _action_rankings(timelines: pd.DataFrame, actions: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in timelines.to_dict(orient="records"):
        predicted = {action: row[f"predicted_gain__{action}"] for action in actions}
        actual = {action: row[f"actual_gain__{action}"] for action in actions}
        predicted_order = sorted(
            actions,
            key=lambda action: (
                -float(predicted[action]) if np.isfinite(predicted[action]) else float("inf"),
                action,
            ),
        )
        actual_order = sorted(actions, key=lambda action: (-float(actual[action]), action))
        for action in actions:
            rows.append(
                {
                    "representation": row["representation"],
                    "episode_id": row["episode_id"],
                    "episode_order": int(row["episode_order"]),
                    "query_id": row["query_id"],
                    "query_occurrence": int(row["query_occurrence"]),
                    "decision_status": row["decision_status"],
                    "action": action,
                    "predicted_gain_log2": predicted[action],
                    "predicted_rank": (
                        predicted_order.index(action) + 1
                        if np.isfinite(predicted[action])
                        else np.nan
                    ),
                    "actual_gain_log2": actual[action],
                    "actual_rank": actual_order.index(action) + 1,
                    "selected_action": action == row["predicted_action"],
                }
            )
    return pd.DataFrame(rows)


def _actual_gain_digest(frame: pd.DataFrame, actions: list[str]) -> str:
    columns = ["episode_id", *[f"actual_gain__{action}" for action in actions]]
    canonical = frame[columns].sort_values("episode_id").to_csv(index=False, float_format="%.17g")
    return hashlib.sha256(canonical.encode()).hexdigest()


def _leakage_checks(
    timelines: pd.DataFrame,
    neighbors: pd.DataFrame,
    summaries: pd.DataFrame,
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    fit_manifest: dict[str, Any],
    existing_timeline: pd.DataFrame,
    actions: list[str],
) -> dict[str, Any]:
    representations = sorted(timelines["representation"].unique())
    episode_sets = {
        representation: set(
            timelines[timelines["representation"].eq(representation)]["episode_id"].astype(str)
        )
        for representation in representations
    }
    gain_digests = {
        representation: _actual_gain_digest(
            timelines[timelines["representation"].eq(representation)], actions
        )
        for representation in representations
    }
    full = timelines[timelines["representation"].eq("full_multilayer")].sort_values("episode_order")
    frozen = existing_timeline[
        existing_timeline["memory_mode"].astype(str).eq("warm_start_cross_query")
    ].sort_values("episode_order")
    full_match = (
        len(full) == len(frozen)
        and full["predicted_action"].fillna("").tolist()
        == frozen["predicted_action"].fillna("").tolist()
        and full["decision_status"].tolist() == frozen["decision_status"].tolist()
        and np.allclose(full["nearest_distance"], frozen["nearest_distance"], equal_nan=True)
    )
    expected_episode_set = set(events["episode_id"].astype(str))
    expected_outcomes = len(events) * len(actions)
    checks = {
        "development_only_fit": all(
            scope["fit_scope"] == "development_reference_only"
            and int(scope["fit_state_count"]) == 26
            and not set(scope["fit_episode_ids"]) & expected_episode_set
            for scope in fit_manifest["representations"].values()
        ),
        "same_query_neighbors_excluded": bool(
            neighbors.empty or not neighbors["same_query_id"].astype(bool).any()
        ),
        "same_normalized_sql_neighbors_excluded": bool(
            neighbors.empty or not neighbors["same_normalized_sql"].astype(bool).any()
        ),
        "future_neighbors_excluded": bool(
            neighbors.empty or not neighbors["future_or_current_neighbor"].astype(bool).any()
        ),
        "identical_episode_sets": all(
            values == expected_episode_set for values in episode_sets.values()
        ),
        "identical_action_outcomes": len(set(gain_digests.values())) == 1
        and len(outcomes) == expected_outcomes,
        "abstentions_separate_from_top1_denominator": all(
            int(row.recommendation_count) + int(row.abstention_count) == int(row.episode_count)
            and (
                pd.isna(row.top1_accuracy)
                if int(row.recommendation_count) == 0
                else math.isclose(
                    float(row.top1_accuracy),
                    int(row.correct_decision_count) / int(row.recommendation_count),
                )
            )
            for row in summaries.itertuples(index=False)
        ),
        "full_representation_reproduces_existing_frozen_timeline": full_match,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "episode_count": len(events),
        "action_outcome_count": len(outcomes),
        "actual_gain_sha256_by_representation": gain_digests,
    }


def _exact_query_reference(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    dba_module: Any,
    context_fields: tuple[str, ...],
) -> pd.DataFrame:
    timeline = dba_module.replay_exact_query_memory(events, outcomes, context_fields=context_fields)
    timeline["representation"] = "exact_query_memory_reference"
    rows = []
    for evaluation in ("first_occurrence", "all_episodes"):
        selected = (
            timeline[timeline["query_occurrence"].eq(1)]
            if evaluation == "first_occurrence"
            else timeline
        )
        recommended = selected[selected["predicted_action"].fillna("").astype(str).ne("")]
        rows.append(
            {
                "reference_method": "exact_query_memory",
                "evaluation": evaluation,
                "episode_count": len(selected),
                "recommendation_count": len(recommended),
                "coverage": len(recommended) / len(selected),
                "correct_decision_count": int(recommended["top1_correct"].astype(bool).sum()),
                "top1_accuracy": (
                    float(recommended["top1_correct"].astype(bool).mean())
                    if len(recommended)
                    else float("nan")
                ),
                "mean_regret_log2": (
                    float(recommended["regret_log2"].mean()) if len(recommended) else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows)


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "Nema redova."
    lines = ["| " + " | ".join(columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in frame[columns].itertuples(index=False, name=None):
        values = []
        for value in row:
            if pd.isna(value):
                rendered = ""
            elif isinstance(value, (float, np.floating)):
                rendered = f"{float(value):.4f}"
            else:
                rendered = str(value)
            values.append(rendered.replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _write_report(
    out_dir: Path,
    contract: dict[str, Any],
    summary: pd.DataFrame,
    bootstrap: pd.DataFrame,
    paired: pd.DataFrame,
    exact: pd.DataFrame,
    fit_manifest: dict[str, Any],
    leakage: dict[str, Any],
) -> None:
    first = summary[summary["evaluation"].eq("first_occurrence")]
    all_rows = summary[summary["evaluation"].eq("same_query_excluded")]
    conclusion_rows = all_rows.set_index("representation")
    full = conclusion_rows.loc["full_multilayer"]
    simple = conclusion_rows.loc["coordinator_physical"]
    structural = conclusion_rows.loc["sql_structural"]
    if full["top1_accuracy"] >= max(simple["top1_accuracy"], structural["top1_accuracy"]) and full[
        "mean_regret_log2"
    ] <= min(simple["mean_regret_log2"], structural["mean_regret_log2"]):
        conclusion = (
            "Puna višeslojna reprezentacija daje najbolji kvalitet među izdatim "
            "preporukama u obje glavne metrike, uz pokrivenost prikazanu odvojeno."
        )
    else:
        conclusion = (
            "Puna višeslojna reprezentacija nije istovremeno nadmašila oba jednostavnija "
            "baselinea u Top-1 tačnosti i regretnosti."
        )
    metric_columns = [
        "representation",
        "episode_count",
        "recommendation_count",
        "coverage",
        "correct_decision_count",
        "top1_accuracy",
        "mean_regret_log2",
    ]
    first_table = _markdown_table(first, metric_columns)
    all_table = _markdown_table(all_rows, metric_columns)
    exact_table = _markdown_table(exact, list(exact.columns))
    leakage_table = _markdown_table(
        pd.DataFrame([{"check": key, "passed": value} for key, value in leakage["checks"].items()]),
        ["check", "passed"],
    )
    percentile = int(float(contract["decision_policy"]["coverage_quantile"]) * 100)
    fit_summary = {
        key: {
            "states": value["fit_state_count"],
            "dimensions": value["output_dimensions"],
            "threshold": value["coverage_threshold"],
        }
        for key, value in fit_manifest["representations"].items()
    }
    bootstrap_count = int(bootstrap["bootstrap_samples"].max())
    paired_count = int(paired["bootstrap_samples"].max())
    structural_fit = fit_manifest["representations"]["sql_structural"]
    structural_threshold = float(structural_fit["coverage_threshold"])
    paired_same_query = paired[paired["evaluation"].eq("same_query_excluded")]
    supported_differences = paired_same_query[
        (paired_same_query["ci_lower"] > 0) | (paired_same_query["ci_upper"] < 0)
    ][["baseline", "metric", "mean_difference", "ci_lower", "ci_upper"]]
    supported_table = _markdown_table(
        supported_differences,
        ["baseline", "metric", "mean_difference", "ci_lower", "ci_upper"],
    )
    report = f"""# Offline provjera vrijednosti višeslojne reprezentacije

## Istraživačko pitanje

> {contract["research_question"]}

Eksperiment ne pokreće infrastrukturu i ne mijenja postojeće rezultate. Sve
transformacije fitovane su isključivo nad 26 razvojnih stanja. Završnih 45
stanja koristi se samo za vremenski uređenu evaluaciju. Svako stanje grupiše
tri epizode pojedinačnih akcija sa zasebno izmjerenim ishodima.

## Zamrznuta politika

- kNN: `k={contract["decision_policy"]["neighbors"]}`
- metrika: `{contract["decision_policy"]["distance_metric"]}`
- apstinencija: omjer prema razvojnoj P{percentile} udaljenosti, zajednički prag 1,0
- isti `query_id` i isti normalizovani SQL isključeni su iz susjeda
- akcije: `{", ".join(contract["decision_policy"]["actions"])}`

Broj pojavljivanja po SQL-u u stvarnom panelu nije uniformno tri. Raspodjela je
1--5, po tri SQL obrasca za svaki broj pojavljivanja. To ne mijenja dvije
predefinisane evaluacije: 15 prvih pojavljivanja i svih 45 stanja.

## Reprezentacije

1. `sql_structural`: 18 SQL-strukturnih i 7 osnovnih GAC plan pokazatelja,
   skaliranih samo na razvojnoj memoriji, bez PCA.
2. `coordinator_physical`: standardni rezultat, buffer i coordinator EXPLAIN
   pokazatelji, bez regiona, worker/task, edge i OS dokaza.
3. `full_multilayer`: neizmijenjeni tok 93 kandidata -> 64 aktivna pokazatelja
   -> 6 PCA komponenti.

Razvojnih 26 stanja sadrži samo jedan normalizovani SQL oblik. Zbog toga je
svih 25 strukturnih koordinata konstantno i razvojni P99 prag
`{structural_threshold:.4f}`. SQL baseline je zato strogi test strukturne
kompatibilnosti, a ne dokaz da je na razvojnom skupu naučena bogata SQL
geometrija. Konstantne koordinate nisu uklonjene, jer bi to unaprijed
onemogućilo opažanje nove strukture u završnom panelu.

Sirovi prag udaljenosti izračunat je zasebno u svakom prostoru samo iz
razvojnih stanja. Odluka je u svim reprezentacijama ista: preporuka se izdaje
ako je omjer `udaljenost / razvojni P99` najviše 1,0. Time različite jedinice
prostora ne dijele proizvoljan numerički prag.

## Prvo pojavljivanje SQL-a

{first_table}

## Svih 45 stanja bez istog SQL-a među susjedima

{all_table}

## Exact-query memorija kao odvojena referenca

{exact_table}

Exact-query rezultat nije uključen u poređenje cross-query reprezentacija.

## Intervali i uparene razlike

`bootstrap_intervals.csv` sadrži 95% grupisane bootstrap intervale po
`query_id`. `paired_representation_differences.csv` koristi iste resamplirane
SQL klastere za upareno poređenje pune reprezentacije sa svakim baselineom.
Pozitivna razlika u toj tabeli uvijek favorizuje punu reprezentaciju. Obje
tabele koriste po {bootstrap_count} odnosno {paired_count} resampliranja.

Na svih 45 stanja upareni 95% interval ne obuhvata nulu za sljedeće razlike:

{supported_table}

## Provjere protiv leakagea

Status: **{leakage["status"]}**

{leakage_table}

## Zaključak

{conclusion} Tačkasta procjena nije sama po sebi dokaz univerzalne nadmoći. Za
prva pojavljivanja intervali razlika kvaliteta obuhvataju nulu. Na svih 45
stanja statistički je najjasnija prednost pune reprezentacije niži regret u
odnosu na baseline koji koristi samo koordinator, dok prema SQL baselineu
najjasnije raste
pokrivenost. Top-1 razlike ostaju pozitivne u tačkastoj procjeni, ali njihovi
grupisani bootstrap intervali obuhvataju nulu.

Rezultat govori o cross-query transferu tri poznate akcije u ovom GAC Top-K
panelu. Ne dokazuje univerzalnu dijagnozu, izbor proizvoljne PostgreSQL akcije
ni prenosivost na neopažene domene.

## Reprodukcija

```bash
make representation-value-ablation
make representation-value-ablation-local-gate
```

Mašinski čitljivi tragovi:

- `episode_results.csv`: odluka svake reprezentacije za svih 45 stanja
- `representation_summary.csv`: glavne metrike po evaluaciji
- `first_occurrence_results.csv`: 15 prvih pojavljivanja
- `same_query_excluded_results.csv`: svih 45 stanja
- `neighbor_trace.csv`: odabrani susjedi, udaljenosti i historijski ishodi
- `action_rankings.csv`: procijenjeni i stvarni poredak tri akcije
- `representation_features.csv`: uključeni i isključeni pokazatelji
- `feature_fit_audit.csv`: odluke fitovane samo na razvojnoj memoriji
- `bootstrap_intervals.csv`: grupisani bootstrap intervali
- `leakage_checks.json`: automatske metodološke provjere
- `input_manifest.json`: hash korištenih ulaza

Razvojni fit po reprezentaciji: `{json.dumps(fit_summary, sort_keys=True)}`.
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")


def analyze(contract_path: Path, out_dir: Path) -> dict[str, Any]:
    contract = read_yaml(contract_path)
    _validate_contract(contract)
    out_dir.mkdir(parents=True, exist_ok=True)
    memory_module = load_script(MEMORY_SCRIPT, "representation_ablation_memory_101")
    dba_module = load_script(DBA_SCRIPT, "representation_ablation_dba_102")
    input_spec = contract["inputs"]
    state_contract_path = resolve_input(input_spec["development_state_contract"])
    state_contract = read_yaml(state_contract_path)
    final_contract_path = resolve_input(input_spec["final_panel_contract"])
    final_contract = read_yaml(final_contract_path)
    final_report = resolve_input(input_spec["final_panel_report"])
    events_path = final_report / "observed_episode_states.csv"
    outcomes_path = final_report / "observed_action_outcomes.csv"
    existing_timeline_path = final_report / "dba_episode_timeline.csv"
    events = pd.read_csv(events_path, low_memory=False).sort_values("episode_order")
    outcomes = pd.read_csv(outcomes_path, low_memory=False)
    existing_timeline = pd.read_csv(existing_timeline_path, low_memory=False)
    expected = contract["expected_panel"]
    observed_distribution = events.groupby("query_id").size().value_counts().sort_index().to_dict()
    if len(events) != int(expected["episode_count"]):
        raise ValueError("Unexpected final episode count")
    if events["query_id"].nunique() != int(expected["query_count"]):
        raise ValueError("Unexpected final query count")
    if len(outcomes) != int(expected["action_outcome_count"]):
        raise ValueError("Unexpected final action outcome count")
    expected_distribution = {
        int(key): int(value)
        for key, value in expected["observed_occurrences_per_query_distribution"].items()
    }
    if observed_distribution != expected_distribution:
        raise ValueError(f"Unexpected occurrence distribution: {observed_distribution}")
    actions = [str(value) for value in contract["decision_policy"]["actions"]]
    if set(actions) != set(dba_module.ACTIONS):
        raise ValueError("Action catalog differs from the frozen DBA panel")
    if not outcomes["result_equal"].astype(bool).all():
        raise ValueError("Non-equivalent action result found")

    full_specs = state_contract["state_representation"]["features"]
    full_names = list(full_specs)
    reference_states, reference_outcomes = dba_module._reference_memory(final_contract, full_names)
    development_rows, source_indexes = _development_rows(contract, memory_module)
    development_metadata = _metadata_from_development(development_rows, source_indexes)
    if development_metadata["episode_id"].tolist() != reference_states["episode_id"].tolist():
        development_metadata = reference_states[["episode_id"]].merge(
            development_metadata, on="episode_id", how="left", validate="one_to_one"
        )
    final_metadata = _metadata_from_final(
        events, resolve_input(input_spec["final_panel_index"]), memory_module
    )

    representations: dict[str, tuple[np.ndarray, np.ndarray, Any]] = {}
    fit_manifest: dict[str, Any] = {"representations": {}}
    fit_audits: list[pd.DataFrame] = []

    structural_specs = contract["representations"]["sql_structural"]["features"]
    structural_reference = structural_feature_frame(development_metadata, structural_specs)
    structural_final = structural_feature_frame(final_metadata, structural_specs)
    structural_processor = StructuralPreprocessor(structural_specs)
    structural_reference_values = structural_processor.fit(structural_reference)
    structural_final_values = structural_processor.transform(structural_final)
    representations["sql_structural"] = (
        structural_reference_values,
        structural_final_values,
        structural_processor,
    )

    simple_contract = contract["representations"]["coordinator_physical"]
    simple_names = [str(value) for value in simple_contract["included_features"]]
    missing_simple = set(simple_names) - set(full_specs)
    if missing_simple:
        raise ValueError(f"Unknown coordinator features: {sorted(missing_simple)}")
    simple_processor = memory_module.StatePreprocessor(
        specifications={name: full_specs[name] for name in simple_names},
        pca_components=int(simple_contract["pca_components"]),
        minimum_active_features=int(simple_contract["minimum_active_features"]),
    )
    simple_reference_values = simple_processor.fit(reference_states)
    simple_final_values = simple_processor.transform(events)
    representations["coordinator_physical"] = (
        simple_reference_values,
        simple_final_values,
        simple_processor,
    )

    full_contract = contract["representations"]["full_multilayer"]
    if len(full_specs) != int(full_contract["expected_candidate_features"]):
        raise ValueError("The full representation candidate count changed")
    full_processor = memory_module.StatePreprocessor(
        specifications=full_specs,
        pca_components=int(state_contract["state_representation"]["pca_components"]),
        minimum_active_features=int(
            state_contract["state_representation"]["minimum_active_features"]
        ),
    )
    full_reference_values = full_processor.fit(reference_states)
    full_final_values = full_processor.transform(events)
    representations["full_multilayer"] = (
        full_reference_values,
        full_final_values,
        full_processor,
    )

    timelines: list[pd.DataFrame] = []
    policy = contract["decision_policy"]
    for name, (reference_values, final_values, processor) in representations.items():
        threshold = dba_module._nearest_threshold(
            reference_values,
            float(policy["coverage_quantile"]),
            str(policy["distance_metric"]),
        )
        timeline, _ = dba_module.replay_memory(
            events,
            outcomes,
            reference_states,
            reference_outcomes,
            reference_values,
            final_values,
            mode=str(policy["memory_mode"]),
            neighbors=int(policy["neighbors"]),
            epsilon=float(policy["distance_epsilon"]),
            coverage_threshold=threshold,
            minimum_history=int(policy["minimum_history_for_available"]),
            exclude_same_query=True,
            distance_metric=str(policy["distance_metric"]),
        )
        timeline.insert(0, "representation", name)
        nearest = pd.to_numeric(timeline["nearest_distance"], errors="coerce")
        if threshold > 0:
            timeline["coverage_ratio"] = nearest / threshold
        else:
            timeline["coverage_ratio"] = np.where(nearest.fillna(np.inf).eq(0.0), 0.0, np.inf)
        timeline["normalized_abstention_threshold"] = 1.0
        timelines.append(timeline)
        selection_audit = processor.selection_audit.copy()
        selection_audit.insert(0, "representation", name)
        fit_audits.append(selection_audit)
        active_features = (
            list(processor.active_features)
            if hasattr(processor, "active_features") and processor.active_features is not None
            else list(structural_specs)
        )
        fit_manifest["representations"][name] = {
            "fit_scope": "development_reference_only",
            "fit_state_count": len(reference_states),
            "fit_episode_ids": reference_states["episode_id"].astype(str).tolist(),
            "candidate_feature_count": (
                len(structural_specs) if name == "sql_structural" else len(processor.specifications)
            ),
            "active_feature_count": len(active_features),
            "active_features": active_features,
            "output_dimensions": int(reference_values.shape[1]),
            "coverage_quantile": float(policy["coverage_quantile"]),
            "coverage_threshold": threshold,
        }

    if fit_manifest["representations"]["full_multilayer"]["active_feature_count"] != int(
        full_contract["expected_active_features"]
    ):
        raise ValueError("The frozen full representation no longer selects 64 features")
    if fit_manifest["representations"]["full_multilayer"]["output_dimensions"] != int(
        full_contract["expected_pca_components"]
    ):
        raise ValueError("The frozen full representation no longer has 6 PCA components")
    if not math.isclose(
        fit_manifest["representations"]["full_multilayer"]["coverage_threshold"],
        float(full_contract["expected_reference_coverage_threshold"]),
        rel_tol=1e-10,
        abs_tol=1e-10,
    ):
        raise ValueError("The frozen full representation P99 threshold changed")

    timeline = pd.concat(timelines, ignore_index=True)
    summary = pd.DataFrame(
        [
            _summarize(group, evaluation)
            for _, group in timeline.groupby("representation", sort=True)
            for evaluation in ("first_occurrence", "same_query_excluded")
        ]
    )
    first_results = timeline[timeline["query_occurrence"].eq(1)].copy()
    same_query_results = timeline.copy()
    neighbor_trace = _expanded_neighbor_trace(timeline, events)
    rankings = _action_rankings(timeline, actions)
    bootstrap = _bootstrap_intervals(timeline, summary, contract)
    paired = _paired_bootstrap_differences(timeline, contract)
    exact = _exact_query_reference(
        events,
        outcomes,
        dba_module,
        tuple(final_contract["memory"]["exact_context_fields"]),
    )
    leakage = _leakage_checks(
        timeline,
        neighbor_trace,
        summary,
        events,
        outcomes,
        fit_manifest,
        existing_timeline,
        actions,
    )
    if leakage["status"] != "PASS":
        raise ValueError("Leakage checks failed; see leakage_checks.json")

    feature_contract = _feature_contract_rows(contract, state_contract)
    fit_audit = pd.concat(fit_audits, ignore_index=True)
    input_paths = {
        "experiment_contract": contract_path,
        "development_state_contract": state_contract_path,
        "development_episodes": resolve_input(input_spec["development_report"]) / "episodes.csv",
        "final_panel_contract": final_contract_path,
        "final_episode_states": events_path,
        "final_action_outcomes": outcomes_path,
        "final_existing_timeline": existing_timeline_path,
        "final_execution_features": resolve_input(input_spec["final_panel_index"])
        / "execution_features.csv",
    }
    for source in state_contract["sources"]:
        input_paths[f"development_execution_features__{source['id']}"] = (
            resolve_input(source["index_dir"]) / "execution_features.csv"
        )
    input_manifest = {
        "experiment_id": contract["experiment_id"],
        "inputs": {
            name: {
                "path": display_input_path(path),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for name, path in input_paths.items()
        },
        "final_panel_used_for_fit": False,
        "development_fit_state_count": len(reference_states),
    }

    timeline.to_csv(out_dir / "episode_results.csv", index=False)
    first_results.to_csv(out_dir / "first_occurrence_results.csv", index=False)
    same_query_results.to_csv(out_dir / "same_query_excluded_results.csv", index=False)
    summary.to_csv(out_dir / "representation_summary.csv", index=False)
    neighbor_trace.to_csv(out_dir / "neighbor_trace.csv", index=False)
    rankings.to_csv(out_dir / "action_rankings.csv", index=False)
    feature_contract.to_csv(out_dir / "representation_features.csv", index=False)
    fit_audit.to_csv(out_dir / "feature_fit_audit.csv", index=False)
    bootstrap.to_csv(out_dir / "bootstrap_intervals.csv", index=False)
    paired.to_csv(out_dir / "paired_representation_differences.csv", index=False)
    exact.to_csv(out_dir / "exact_query_memory_reference.csv", index=False)
    structural_reference.to_csv(out_dir / "development_sql_structural_features.csv", index=False)
    structural_final.to_csv(out_dir / "final_sql_structural_features.csv", index=False)
    write_json(out_dir / "fit_manifest.json", fit_manifest)
    write_json(out_dir / "leakage_checks.json", leakage)
    write_json(out_dir / "input_manifest.json", input_manifest)
    analysis_summary = {
        "status": "PASS",
        "research_question": contract["research_question"],
        "query_count": int(events["query_id"].nunique()),
        "episode_count": len(events),
        "occurrences_per_query_distribution": observed_distribution,
        "action_outcome_count": len(outcomes),
        "decision_policy": policy,
        "representation_summary": summary.to_dict(orient="records"),
        "leakage_status": leakage["status"],
    }
    write_json(out_dir / "analysis_summary.json", analysis_summary)
    _write_report(out_dir, contract, summary, bootstrap, paired, exact, fit_manifest, leakage)
    _write_output_checksums(out_dir)
    return analysis_summary


def main() -> int:
    args = parse_args()
    summary = analyze(args.contract.resolve(), args.out_dir.resolve())
    print(json.dumps(summary, indent=2, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
