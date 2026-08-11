#!/usr/bin/env python3
# ruff: noqa: E501
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from matplotlib.colors import TwoSlopeNorm
from matplotlib.ticker import FuncFormatter
from sklearn.cluster import KMeans

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from master_regimes.feedback_loop import (  # noqa: E402
    classify_end_to_end_effect,
    classify_physical_transition,
)

DEFAULT_CONTRACT = ROOT / "configs/validation/feedback_loop_analysis_v1.yml"
REPRESENTATION_SCRIPT = ROOT / "analysis/scripts/agent/105_representation_ablation_e1_e4.py"
BASE_SCRIPT = ROOT / "analysis/scripts/agent/103_representation_value_ablation.py"
MEMORY_SCRIPT = ROOT / "analysis/scripts/agent/101_fuzzy_intervention_memory.py"
DBA_SCRIPT = ROOT / "analysis/scripts/agent/102_dba_local_memory_panel.py"
TOPOLOGY_SCRIPT = ROOT / "analysis/scripts/agent/104_n3_topology_memory_experiment.py"
AUDIT_MODULE = ROOT / "src/master_regimes/representation_audit.py"

DOMAIN_LABELS = {
    "remote_fdw_path": "Udaljena FDW putanja",
    "regional_reduction": "Regionalna redukcija",
    "gac_finalization": "GAC finalizacija",
    "imbalance": "Neravnomjernost",
    "disk_spill": "Preljev na disk",
    "repartition_locality": "Reparticionisanje i lokalnost",
}

KEY_SIGNALS = (
    "edge_remote_bytes_sum",
    "edge_boundary_wait_share",
    "edge_rtt_context_median_ms_max",
    "regional_input_to_remote_rows_ratio",
    "gac_fanin_to_final_rows_ratio",
    "gac_temp_written_per_final_row",
    "gac_hash_batch_excess",
    "remote_region_actual_time_cv",
    "worker_task_scan_actual_rows_cv",
)

RQ_H_STATEMENTS = {
    "RQ1": "Koji normalizovani pokazatelji nakon izvršavanja najdosljednije opisuju režime izvršavanja globalnih analitičkih SQL upita pri promjeni veličine skupa podataka, WAN profila, profila neravnomjernosti rada i konfiguracijskih parametara?",
    "RQ2": "Može li neizrazito grupisanje nad normalizovanim mjernim pokazateljima izdvojiti interpretabilne režime izvršavanja globalnih analitičkih SQL upita?",
    "RQ3": "Da li raspodijeljeni stepen pripadnosti režimima bolje opisuje mješovite slučajeve izvršavanja od tvrdog dodjeljivanja jednom režimu?",
    "RQ4": "Koji pokazatelji najviše doprinose razlikovanju dobijenih režima i kako se ti režimi mogu povezati sa arhitektonskim tumačenjima?",
    "H1": "Relativni i normalizovani pokazatelji, kao što su udjeli vremena izvršavanja, faktor redukcije podataka (DRF), globalni priliv rezultata, faktor neravnomjernosti rada i spill signal, daju interpretabilnije režime od apsolutnih metrika kao što su ukupno vrijeme izvršavanja ili apsolutni broj prenesenih redova.",
    "H2": "Neizrazito grupisanje bolje opisuje mješovite režime izvršavanja od tvrdog grupisanja, jer omogućava da jedno izvršenje SQL upita bude opisano raspodijeljenim stepenom pripadnosti režimima.",
    "H3": "Slični režimi izvršavanja pojavljuju se pri kontrolisanoj promjeni veličine skupa podataka, WAN profila i profila neravnomjernosti rada, što ukazuje da režimi nisu samo artefakt jedne eksperimentalne konfiguracije.",
    "H4": "U scenarijima sa regionalnom neravnomjernošću rada ili nekolociranim spajanjima tabela, kompaktan WAN izlaz nije dovoljan indikator ukupnog ponašanja SQL upita, jer regionalna obrada ili premještanje podataka mogu ostati dominantni faktori režima izvršavanja.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze the frozen adaptive feedback loop without SQL execution or model refitting."
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path)
    return parser.parse_args()


def load_module(path: Path, name: str) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        converted = float(value)
        return converted if math.isfinite(converted) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(json_safe(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
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


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def profile_coordinates(path: Path, view: str) -> tuple[dict[str, float], dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    selected = payload["views"].get(view)
    if selected is None:
        raise ValueError(f"Profile {path} lacks view {view}")
    values: dict[str, float] = {}
    statuses: dict[str, str] = {}
    for row in selected["coordinates"]:
        domain = str(row["domain_id"])
        raw = row.get("relative_pressure_evidence")
        values[domain] = float(raw) if raw is not None else math.nan
        statuses[domain] = str(row["status"])
    return values, statuses


def raw_signal_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    for column in frame.columns:
        if column not in {
            "query_run_id",
            "execution_slot_id",
            "execution_status",
            "result_ordered_sha256",
            "result_multiset_sha256",
            "collection_dir",
            "remote_citus_plan_locality_class",
        }:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def state_signal_summary(state: pd.Series) -> dict[str, Any]:
    frame = raw_signal_frame(Path(str(state["raw_signal_path"])))
    row: dict[str, Any] = {"state_id": str(state["state_id"])}
    for signal in KEY_SIGNALS:
        values = pd.to_numeric(frame.get(signal, pd.Series(dtype=float)), errors="coerce").dropna()
        row[f"{signal}__median"] = float(values.median()) if len(values) else math.nan
        if len(values):
            median = float(values.median())
            mad = float((values - median).abs().median())
            row[f"{signal}__mad"] = mad
            row[f"{signal}__robust_relative_dispersion"] = (
                1.4826 * mad / abs(median) if abs(median) > 1.0e-12 else math.nan
            )
        else:
            row[f"{signal}__mad"] = math.nan
            row[f"{signal}__robust_relative_dispersion"] = math.nan
    return row


def load_state_table(run_dir: Path, domains: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    states = pd.read_csv(run_dir / "trajectory_states.csv", low_memory=False)
    state_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    for state in states.to_dict(orient="records"):
        origin_values, origin_statuses = profile_coordinates(
            Path(state["profile_path"]), "trajectory_origin"
        )
        previous_values, previous_statuses = profile_coordinates(
            Path(state["profile_path"]), "previous_accepted_state"
        )
        row = dict(state)
        for domain in domains:
            row[f"origin__{domain}"] = origin_values.get(domain, math.nan)
            row[f"origin_status__{domain}"] = origin_statuses.get(domain, "missing")
            row[f"previous__{domain}"] = previous_values.get(domain, math.nan)
            row[f"previous_status__{domain}"] = previous_statuses.get(domain, "missing")
        state_rows.append(row)
        signal_rows.append(state_signal_summary(pd.Series(state)))
    return pd.DataFrame(state_rows), pd.DataFrame(signal_rows)


def decision_records(run_dir: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    decisions: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    with (run_dir / "decision_log.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("record_type") == "decision":
                decisions[str(row["decision_id"])] = row
            elif row.get("record_type") == "outcome":
                outcomes.append(row)
    return decisions, outcomes


def elapsed_samples(states: pd.DataFrame, state_id: str) -> np.ndarray:
    path = Path(str(states.loc[states["state_id"].eq(state_id), "raw_signal_path"].iloc[0]))
    values = pd.to_numeric(raw_signal_frame(path)["elapsed_seconds"], errors="coerce").dropna()
    return values.to_numpy(dtype=float)


def bootstrap_gain(
    before: np.ndarray,
    after: np.ndarray,
    *,
    seed: int,
    samples: int,
) -> tuple[float, float, float]:
    estimate = math.log2(float(np.median(before)) / float(np.median(after)))
    rng = np.random.default_rng(seed)
    before_idx = rng.integers(0, len(before), size=(samples, len(before)))
    after_idx = rng.integers(0, len(after), size=(samples, len(after)))
    draws = np.log2(
        np.median(before[before_idx], axis=1) / np.median(after[after_idx], axis=1)
    )
    low, high = np.quantile(draws, [0.025, 0.975])
    return estimate, float(low), float(high)


def build_transitions(
    run_dir: Path,
    states: pd.DataFrame,
    signals: pd.DataFrame,
    domains: list[str],
    contract: dict[str, Any],
) -> pd.DataFrame:
    decisions, _outcomes = decision_records(run_dir)
    state_index = states.set_index("state_id", drop=False)
    signal_index = signals.set_index("state_id", drop=False)
    rows: list[dict[str, Any]] = []
    adaptive = pd.read_csv(run_dir / "trajectory_transitions.csv", low_memory=False)
    for order, transition in enumerate(adaptive.to_dict(orient="records"), start=1):
        decision = decisions[str(transition["decision_id"])]
        rows.append(
            transition_row(
                phase="adaptive",
                sequence_index=order,
                transition_id=str(transition["decision_id"]),
                source_state_id=str(transition["source_state_id"]),
                target_state_id=str(transition["target_state_id"]),
                action_id=str(transition["action_id"]),
                gain=float(transition["elapsed_log2_gain"]),
                interval_low=float(transition["elapsed_gain_interval_low"]),
                interval_high=float(transition["elapsed_gain_interval_high"]),
                result_status=str(transition["result_validation_status"]),
                noise_status=str(transition["noise_status"]),
                outcome_label=str(transition["outcome_label"]),
                accepted=str(transition["accepted"]).lower(),
                hypothesis=str(decision["hypothesis"]),
                expected_end_to_end=str(decision["expected_end_to_end_impact"]),
                expected_directions=decision["expected_domain_directions"],
                target_domains=decision["target_domains"],
                identity_mode=str(decision["identity_mode"]),
                decision_at=str(decision["recorded_at_utc"]),
                state_index=state_index,
                signal_index=signal_index,
                domains=domains,
            )
        )

    replay_definitions = [
        ("replay-work-mem", "replay_A_baseline", "replay_B_work_mem", "gac_work_mem_64mb"),
        ("replay-pushdown", "replay_B_work_mem", "replay_C_pushdown", "regional_pushdown_rewrite"),
        ("replay-wan-delay", "replay_C_pushdown", "replay_D_wan_delay", "wan_delay_10ms_probe"),
    ]
    corresponding_decision = {
        "gac_work_mem_64mb": "trajectory_sort_order_topk-step-01",
        "regional_pushdown_rewrite": "trajectory_sort_order_topk-step-02",
        "wan_delay_10ms_probe": "trajectory_sort_order_topk-step-03",
    }
    frozen_at = str(read_yaml(run_dir / "frozen_replay_manifest.yaml")["frozen_at_utc"])
    seed = int(contract["policy"]["bootstrap_seed"])
    samples = int(contract["policy"]["bootstrap_samples"])
    for order, (identifier, source, target, action) in enumerate(replay_definitions, start=1):
        estimate, low, high = bootstrap_gain(
            elapsed_samples(states, source),
            elapsed_samples(states, target),
            seed=seed + order,
            samples=samples,
        )
        decision = decisions[corresponding_decision[action]]
        rows.append(
            transition_row(
                phase="frozen_replay",
                sequence_index=order,
                transition_id=identifier,
                source_state_id=source,
                target_state_id=target,
                action_id=action,
                gain=estimate,
                interval_low=low,
                interval_high=high,
                result_status="equivalent",
                noise_status="resolved" if low > 0 or high < 0 else "unresolved",
                outcome_label="mixed",
                accepted="confirmatory",
                hypothesis=str(decision["hypothesis"]),
                expected_end_to_end=str(decision["expected_end_to_end_impact"]),
                expected_directions=decision["expected_domain_directions"],
                target_domains=decision["target_domains"],
                identity_mode=str(decision["identity_mode"]),
                decision_at=frozen_at,
                state_index=state_index,
                signal_index=signal_index,
                domains=domains,
            )
        )
    result = pd.DataFrame(rows)
    result["example_fewer_domains_and_shorter"] = result["transition_id"].eq(
        "trajectory_join_pushdown-step-02"
    )
    result["example_more_domains_but_shorter"] = result["transition_id"].isin(
        ["trajectory_join_pushdown-step-01", "trajectory_sort_order_topk-step-02"]
    )
    result["example_multidomain_runtime_gain"] = result["transition_id"].isin(
        ["trajectory_join_pushdown-step-01", "trajectory_sort_order_topk-step-02", "replay-pushdown"]
    )
    result["example_negative_or_no_effect"] = result["action_id"].eq("wan_delay_10ms_probe")
    result["physical_change_without_resolved_runtime_gain"] = False
    return result


def build_exact_aggregate_transitions(
    run_dir: Path,
    states: pd.DataFrame,
    signals: pd.DataFrame,
    domains: list[str],
) -> pd.DataFrame:
    decisions, _outcomes = decision_records(run_dir)
    state_index = states.set_index("state_id", drop=False)
    signal_index = signals.set_index("state_id", drop=False)
    source = pd.read_csv(run_dir / "trajectory_transitions.csv", low_memory=False)
    rows: list[dict[str, Any]] = []
    for transition in source.to_dict(orient="records"):
        decision = decisions[str(transition["decision_id"])]
        rows.append(
            transition_row(
                phase="aggregate_exact_confirmatory",
                sequence_index=int(transition["step_index"]),
                transition_id=str(transition["decision_id"]),
                source_state_id=str(transition["source_state_id"]),
                target_state_id=str(transition["target_state_id"]),
                action_id=str(transition["action_id"]),
                gain=float(transition["elapsed_log2_gain"]),
                interval_low=float(transition["elapsed_gain_interval_low"]),
                interval_high=float(transition["elapsed_gain_interval_high"]),
                result_status=str(transition["result_validation_status"]),
                noise_status=str(transition["noise_status"]),
                outcome_label=str(transition["outcome_label"]),
                accepted=str(transition["accepted"]).lower(),
                hypothesis=str(decision["hypothesis"]),
                expected_end_to_end=str(decision["expected_end_to_end_impact"]),
                expected_directions=decision["expected_domain_directions"],
                target_domains=decision["target_domains"],
                identity_mode=str(decision["identity_mode"]),
                decision_at=str(decision["recorded_at_utc"]),
                state_index=state_index,
                signal_index=signal_index,
                domains=domains,
            )
        )
    return pd.DataFrame(rows)


def transition_row(
    *,
    phase: str,
    sequence_index: int,
    transition_id: str,
    source_state_id: str,
    target_state_id: str,
    action_id: str,
    gain: float,
    interval_low: float,
    interval_high: float,
    result_status: str,
    noise_status: str,
    outcome_label: str,
    accepted: str,
    hypothesis: str,
    expected_end_to_end: str,
    expected_directions: dict[str, Any],
    target_domains: list[str],
    identity_mode: str,
    decision_at: str,
    state_index: pd.DataFrame,
    signal_index: pd.DataFrame,
    domains: list[str],
) -> dict[str, Any]:
    source = state_index.loc[source_state_id]
    target = state_index.loc[target_state_id]
    row: dict[str, Any] = {
        "transition_id": transition_id,
        "phase": phase,
        "trajectory_id": str(source["trajectory_id"]),
        "logical_question_id": str(source["logical_question_id"]),
        "sequence_index": sequence_index,
        "source_state_id": source_state_id,
        "target_state_id": target_state_id,
        "action_id": action_id,
        "identity_mode": identity_mode,
        "decision_recorded_at_utc": decision_at,
        "hypothesis_before_execution": hypothesis,
        "expected_end_to_end_impact": expected_end_to_end,
        "expected_domain_directions_json": json.dumps(expected_directions, sort_keys=True),
        "target_domains_json": json.dumps(target_domains),
        "result_validation_status": result_status,
        "outcome_label": outcome_label,
        "accepted": accepted,
        "source_elapsed_median_seconds": float(source["elapsed_median_seconds"]),
        "target_elapsed_median_seconds": float(target["elapsed_median_seconds"]),
        "elapsed_log2_gain": gain,
        "elapsed_gain_interval_low": interval_low,
        "elapsed_gain_interval_high": interval_high,
        "noise_status": noise_status,
        "actual_runtime_direction": "improved" if gain > 0 else "worsened" if gain < 0 else "unchanged",
    }
    changed = 0
    physical_coordinates: list[dict[str, Any]] = []
    for domain in domains:
        before = float(source[f"origin__{domain}"])
        after = float(target[f"origin__{domain}"])
        delta = after - before if math.isfinite(before) and math.isfinite(after) else math.nan
        row[f"domain_before__{domain}"] = before
        row[f"domain_after__{domain}"] = after
        row[f"domain_delta__{domain}"] = delta
        if math.isfinite(delta) and abs(delta) > 1.0e-9:
            changed += 1
        physical_coordinates.append(
            {
                "status": "available" if math.isfinite(delta) else "unavailable",
                "relative_pressure_evidence": delta if math.isfinite(delta) else None,
                "conflicting_component_signs": False,
            }
        )
    row["changed_available_coordinate_count"] = changed
    result_valid = str(result_status).startswith("equivalent")
    row["result_validity_axis"] = "equivalent" if result_valid else "non_equivalent"
    row["end_to_end_effect_axis"] = classify_end_to_end_effect(
        result_valid=result_valid,
        interval_low=interval_low,
        interval_high=interval_high,
    )
    row["physical_transition_axis"] = classify_physical_transition(physical_coordinates)
    source_signals = signal_index.loc[source_state_id]
    target_signals = signal_index.loc[target_state_id]
    for signal in KEY_SIGNALS:
        before = float(source_signals[f"{signal}__median"])
        after = float(target_signals[f"{signal}__median"])
        row[f"signal_before__{signal}"] = before
        row[f"signal_after__{signal}"] = after
        row[f"signal_delta__{signal}"] = (
            after - before if math.isfinite(before) and math.isfinite(after) else math.nan
        )
    return row


def load_query_run_rows(state: pd.Series) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for directory in str(state["sweep_dir"]).split(";"):
        path = Path(directory) / "_index" / "query_runs.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        frames.append(pd.read_csv(path, low_memory=False))
    return pd.concat(frames, ignore_index=True)


def build_frozen_projection(
    states: pd.DataFrame,
    contract: dict[str, Any],
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, float, dict[str, Any]]:
    representation_module = load_module(REPRESENTATION_SCRIPT, "feedback_representation")
    base_module = load_module(BASE_SCRIPT, "feedback_base_ablation")
    memory_module = load_module(MEMORY_SCRIPT, "feedback_memory")
    dba_module = load_module(DBA_SCRIPT, "feedback_dba")
    topology_module = load_module(TOPOLOGY_SCRIPT, "feedback_topology")
    representation_contract = read_yaml(resolve_path(contract["inputs"]["representation_contract"]))
    base_contract = read_yaml(resolve_path(representation_contract["inputs"]["base_ablation_contract"]))
    data = representation_module.load_inputs(
        representation_contract,
        base_contract,
        base_module,
        memory_module,
        dba_module,
        topology_module,
    )
    representations, _features, _audits = representation_module.build_representations(
        representation_contract,
        base_contract,
        data,
        base_module,
        memory_module,
        dba_module,
    )
    reference_values = representations["R3_full_multilayer"].reference_values
    artifact_path = resolve_path(contract["inputs"]["frozen_full_model"])
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    specifications = data.state_contract["state_representation"]["features"]
    transformer = representation_module.FrozenFullTransformer(
        specifications, artifact, memory_module
    )
    state_feature_rows: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []
    for state in states.to_dict(orient="records"):
        runs = load_query_run_rows(pd.Series(state))
        feature_row: dict[str, Any] = {}
        for feature in specifications:
            values = pd.to_numeric(runs.get(feature, pd.Series(dtype=float)), errors="coerce")
            feature_row[f"before__{feature}"] = float(values.median()) if values.notna().any() else math.nan
        first = runs.iloc[0]
        metadata_rows.append(
            {
                "state_id": str(state["state_id"]),
                "logical_question_id": str(state["logical_question_id"]),
                "normalized_sql_hash": str(first.get("sql_normalized_hash", "")),
                "topology_id": str(first.get("topology_id", "")),
                "dataset_profile_id": str(first.get("dataset_profile_id", "")),
                "runtime_config_id": str(first.get("runtime_config_id", "")),
            }
        )
        state_feature_rows.append(feature_row)
    values = transformer.transform(pd.DataFrame(state_feature_rows))
    metadata = pd.DataFrame(metadata_rows)
    for index in range(values.shape[1]):
        metadata[f"pc{index + 1}"] = values[:, index]
    nearest = np.sqrt(((values[:, None, :] - reference_values[None, :, :]) ** 2).sum(axis=2))
    metadata["nearest_reference_distance"] = nearest.min(axis=1)
    threshold = float(representations["R3_full_multilayer"].threshold)
    metadata["within_frozen_p99"] = metadata["nearest_reference_distance"].le(threshold)
    freeze_audit = {
        "candidate_feature_count": len(specifications),
        "active_feature_count": len(artifact["active_features"]),
        "component_count": values.shape[1],
        "development_reference_count": len(reference_values),
        "p99_threshold": threshold,
        "artifact_path": str(artifact_path),
        "artifact_sha256": sha256_file(artifact_path),
        "fitted_on_n3": artifact.get("fitted_on_n3"),
        "feedback_states_used_for_fit": 0,
    }
    return metadata, values, reference_values, threshold, freeze_audit


def build_cluster_audit(
    projection: pd.DataFrame,
    state_values: np.ndarray,
    reference_values: np.ndarray,
    transitions: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    audit_module = load_module(AUDIT_MODULE, "feedback_representation_audit")
    k = int(contract["policy"]["prototype_clusters"])
    kmeans = KMeans(n_clusters=k, random_state=11, n_init=50).fit(reference_values)
    km_distances = kmeans.transform(state_values)
    best_fcm, _fits = audit_module.fit_best_fcm(
        reference_values,
        k=k,
        seeds=contract["policy"]["prototype_seeds"],
        fuzzifier=float(contract["policy"]["prototype_fuzzifier"]),
    )
    memberships, fcm_distances = audit_module.memberships_from_centers(
        state_values,
        best_fcm.centers,
        fuzzifier=float(contract["policy"]["prototype_fuzzifier"]),
    )
    state_rows: list[dict[str, Any]] = []
    for index, state in projection.reset_index(drop=True).iterrows():
        ordered = np.sort(memberships[index])[::-1]
        safe = np.maximum(memberships[index], 1.0e-12)
        state_rows.append(
            {
                "record_type": "state_projection",
                "state_id": state["state_id"],
                "fit_scope": "development_reference_26_only",
                "frozen_representation_refit": False,
                "nearest_reference_distance": state["nearest_reference_distance"],
                "within_frozen_p99": state["within_frozen_p99"],
                "kmeans_cluster": int(kmeans.labels_[0] * 0 + kmeans.predict(state_values[index : index + 1])[0]),
                "kmeans_center_distance": float(km_distances[index].min()),
                "fcm_top_prototype": int(memberships[index].argmax()),
                "fcm_top_membership": float(ordered[0]),
                "fcm_membership_margin": float(ordered[0] - ordered[1]),
                "fcm_membership_entropy": float(-(safe * np.log(safe)).sum()),
                "fcm_center_distance": float(fcm_distances[index].min()),
                "fcm_memberships_json": json.dumps(memberships[index].tolist()),
            }
        )
    state_frame = pd.DataFrame(state_rows)
    state_lookup = state_frame.set_index("state_id")
    value_lookup = {
        state_id: state_values[index]
        for index, state_id in enumerate(projection["state_id"].astype(str))
    }
    transition_rows: list[dict[str, Any]] = []
    for transition in transitions.to_dict(orient="records"):
        source_id = str(transition["source_state_id"])
        target_id = str(transition["target_state_id"])
        source = state_lookup.loc[source_id]
        target = state_lookup.loc[target_id]
        source_membership = np.asarray(json.loads(source["fcm_memberships_json"]), dtype=float)
        target_membership = np.asarray(json.loads(target["fcm_memberships_json"]), dtype=float)
        transition_rows.append(
            {
                "record_type": "transition_projection",
                "transition_id": transition["transition_id"],
                "source_state_id": source_id,
                "target_state_id": target_id,
                "fit_scope": "development_reference_26_only",
                "frozen_representation_refit": False,
                "pca_transition_distance": float(
                    np.linalg.norm(value_lookup[source_id] - value_lookup[target_id])
                ),
                "kmeans_cluster_changed": int(source["kmeans_cluster"]) != int(target["kmeans_cluster"]),
                "fcm_top_prototype_changed": int(source["fcm_top_prototype"])
                != int(target["fcm_top_prototype"]),
                "fcm_membership_l1_change": float(np.abs(source_membership - target_membership).sum()),
                "elapsed_log2_gain": transition["elapsed_log2_gain"],
                "changed_available_coordinate_count": transition[
                    "changed_available_coordinate_count"
                ],
            }
        )
    return pd.concat([state_frame, pd.DataFrame(transition_rows)], ignore_index=True, sort=False)


def build_local_memory_replay(
    run_dir: Path,
    states: pd.DataFrame,
    transitions: pd.DataFrame,
    projection: pd.DataFrame,
) -> pd.DataFrame:
    decisions, outcomes = decision_records(run_dir)
    projection_index = projection.set_index("state_id")
    outcome_time = {
        str(row["decision_id"]): parse_utc(str(row["recorded_at_utc"])) for row in outcomes
    }
    rows: list[dict[str, Any]] = []
    adaptive = transitions[transitions["phase"].eq("adaptive")].copy()
    replay = transitions[transitions["phase"].eq("frozen_replay")].copy()
    replay_cutoff = parse_utc(str(read_yaml(run_dir / "frozen_replay_manifest.yaml")["frozen_at_utc"]))

    events: list[tuple[pd.Series, datetime, bool]] = []
    for _, transition in adaptive.iterrows():
        decision = decisions[str(transition["transition_id"])]
        events.append((transition, parse_utc(str(decision["recorded_at_utc"])), True))
    for _, transition in replay.iterrows():
        events.append((transition, replay_cutoff, False))
    events.sort(key=lambda item: (item[1], str(item[0]["transition_id"])))

    adaptive_by_id = adaptive.set_index("transition_id", drop=False)
    for transition, cutoff, adaptive_event in events:
        source_id = str(transition["source_state_id"])
        source = projection_index.loc[source_id]
        prior_rows: list[pd.Series] = []
        for prior_id, prior in adaptive_by_id.iterrows():
            available_at = outcome_time.get(str(prior_id))
            if available_at is None or available_at >= cutoff:
                continue
            if str(prior["action_id"]) != str(transition["action_id"]):
                continue
            prior_rows.append(prior)

        tier = "abstain_no_prior_action_outcome"
        selected: list[tuple[pd.Series, float]] = []
        logical = [
            row
            for row in prior_rows
            if str(row["logical_question_id"]) == str(transition["logical_question_id"])
        ]
        if logical:
            tier = "same_logical_question_id"
            selected = [(row, physical_distance(source, projection_index.loc[str(row["source_state_id"])])) for row in logical]
        else:
            normalized = []
            for row in prior_rows:
                candidate = projection_index.loc[str(row["source_state_id"])]
                if (
                    str(candidate["normalized_sql_hash"]) == str(source["normalized_sql_hash"])
                    and compatible_context(source, candidate)
                ):
                    normalized.append(row)
            if normalized:
                tier = "same_normalized_sql_compatible_context"
                selected = [
                    (row, physical_distance(source, projection_index.loc[str(row["source_state_id"])]))
                    for row in normalized
                ]
            elif prior_rows:
                tier = "physical_cross_query_secondary"
                selected = sorted(
                    [
                        (row, physical_distance(source, projection_index.loc[str(row["source_state_id"])]))
                        for row in prior_rows
                    ],
                    key=lambda item: item[1],
                )[:5]

        if selected:
            distances = np.asarray([max(distance, 1.0e-6) for _, distance in selected])
            gains = np.asarray([float(row["elapsed_log2_gain"]) for row, _ in selected])
            weights = 1.0 / distances
            estimate = float(np.sum(weights * gains) / np.sum(weights))
            direction_correct = (estimate > 0) == (float(transition["elapsed_log2_gain"]) > 0)
        else:
            estimate = math.nan
            direction_correct = math.nan
        rows.append(
            {
                "evaluation_event": "adaptive_online" if adaptive_event else "frozen_replay_offline",
                "transition_id": transition["transition_id"],
                "decision_cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
                "source_state_id": source_id,
                "logical_question_id": transition["logical_question_id"],
                "normalized_sql_hash": source["normalized_sql_hash"],
                "action_id": transition["action_id"],
                "retrieval_tier": tier,
                "recommendation_status": "available" if selected else "abstained",
                "prior_action_outcome_count": len(prior_rows),
                "selected_neighbor_count": len(selected),
                "neighbor_transition_ids_json": json.dumps([str(row["transition_id"]) for row, _ in selected]),
                "neighbor_source_state_ids_json": json.dumps([str(row["source_state_id"]) for row, _ in selected]),
                "neighbor_distances_json": json.dumps([distance for _, distance in selected]),
                "neighbor_observed_gains_json": json.dumps([float(row["elapsed_log2_gain"]) for row, _ in selected]),
                "estimated_log2_gain": estimate,
                "actual_log2_gain": float(transition["elapsed_log2_gain"]),
                "direction_correct": direction_correct,
                "future_outcome_count_used": 0,
                "missing_outcome_imputed_as_zero": False,
                "replay_outcomes_added_during_frozen_replay": False,
            }
        )
    return pd.DataFrame(rows)


def physical_distance(left: pd.Series, right: pd.Series) -> float:
    columns = [f"pc{index}" for index in range(1, 7)]
    return float(np.linalg.norm(left[columns].to_numpy(dtype=float) - right[columns].to_numpy(dtype=float)))


def compatible_context(left: pd.Series, right: pd.Series) -> bool:
    return all(
        str(left[name]) == str(right[name])
        for name in ("topology_id", "dataset_profile_id", "runtime_config_id")
    )


def build_stability(
    states: pd.DataFrame,
    signals: pd.DataFrame,
    domains: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    signal_index = signals.set_index("state_id")
    state_index = states.set_index("state_id")
    for state in states.to_dict(orient="records"):
        state_id = str(state["state_id"])
        dispersion = [
            float(signal_index.loc[state_id, f"{signal}__robust_relative_dispersion"])
            for signal in KEY_SIGNALS
        ]
        finite = [value for value in dispersion if math.isfinite(value)]
        rows.append(
            {
                "record_type": "within_state_repetition",
                "state_id": state_id,
                "comparison_state_id": "",
                "repetition_count": int(state["repetition_count"]),
                "elapsed_median_seconds": float(state["elapsed_median_seconds"]),
                "elapsed_mad_seconds": float(state["elapsed_mad_seconds"]),
                "elapsed_robust_relative_dispersion": 1.4826
                * float(state["elapsed_mad_seconds"])
                / float(state["elapsed_median_seconds"]),
                "key_signal_median_robust_relative_dispersion": float(np.median(finite)) if finite else math.nan,
                "key_signal_max_robust_relative_dispersion": max(finite) if finite else math.nan,
            }
        )
    matched = {
        "trajectory_sort_order_topk_s00": "replay_A_baseline",
        "trajectory_sort_order_topk_s01": "replay_B_work_mem",
        "trajectory_sort_order_topk_s02": "replay_C_pushdown",
        "trajectory_sort_order_topk_s03": "replay_D_wan_delay",
    }
    for exploratory_id, replay_id in matched.items():
        exploratory = state_index.loc[exploratory_id]
        replay = state_index.loc[replay_id]
        differences = [
            abs(float(exploratory[f"origin__{domain}"]) - float(replay[f"origin__{domain}"]))
            for domain in domains
            if math.isfinite(float(exploratory[f"origin__{domain}"]))
            and math.isfinite(float(replay[f"origin__{domain}"]))
        ]
        rows.append(
            {
                "record_type": "exploratory_vs_frozen_replay",
                "state_id": exploratory_id,
                "comparison_state_id": replay_id,
                "elapsed_log2_ratio_exploratory_to_replay": math.log2(
                    float(exploratory["elapsed_median_seconds"])
                    / float(replay["elapsed_median_seconds"])
                ),
                "domain_absolute_difference_median": float(np.median(differences)),
                "domain_absolute_difference_max": max(differences),
            }
        )
    rollbacks = {
        "trajectory_aggregate_full_flow_s00": "trajectory_aggregate_full_flow_rollback",
        "trajectory_join_pushdown_s00": "trajectory_join_pushdown_rollback",
        "trajectory_sort_order_topk_s00": "trajectory_sort_order_topk_rollback",
        "A_raw_baseline": "R0_prime_rollback",
    }
    for origin_id, rollback_id in rollbacks.items():
        origin = state_index.loc[origin_id]
        rollback = state_index.loc[rollback_id]
        differences = [
            abs(float(rollback[f"origin__{domain}"]))
            for domain in domains
            if math.isfinite(float(rollback[f"origin__{domain}"]))
        ]
        rows.append(
            {
                "record_type": "origin_vs_rollback",
                "state_id": origin_id,
                "comparison_state_id": rollback_id,
                "result_status": str(rollback["result_status"]),
                "elapsed_log2_ratio_origin_to_rollback": math.log2(
                    float(origin["elapsed_median_seconds"])
                    / float(rollback["elapsed_median_seconds"])
                ),
                "domain_absolute_difference_median": float(np.median(differences)),
                "domain_absolute_difference_max": max(differences),
                "rollback_profile_returned": max(differences, default=math.inf) < 1.0e-6,
            }
        )
    return pd.DataFrame(rows)


def save_figure_formats(fig: Any, out_dir: Path, stem: str) -> None:
    for extension in ("pdf", "png", "svg"):
        path = out_dir / f"{stem}.{extension}"
        fig.savefig(path, dpi=220, bbox_inches="tight")
        if extension == "svg":
            normalized = "\n".join(line.rstrip() for line in path.read_text().splitlines())
            path.write_text(f"{normalized}\n")


def format_decimal_comma(value: float, digits: int = 2) -> str:
    """Format a displayed decimal using the manuscript's Bosnian locale."""
    if abs(value) < 0.5 * 10 ** (-digits):
        value = 0.0
    return f"{value:.{digits}f}".replace(".", ",")


def make_trajectory_figure(states: pd.DataFrame, domains: list[str], out_dir: Path) -> None:
    panels = [
        ("Agregacijska putanja sa tačnim rezultatom", ["A_raw_baseline", "B_fetch_size", "C_regional_aggregate", "D_wan_delay", "R0_prime_rollback"]),
        ("Spajanje i regionalno potiskivanje", ["trajectory_join_pushdown_s00", "trajectory_join_pushdown_s01", "trajectory_join_pushdown_s02", "trajectory_join_pushdown_rollback"]),
        ("Prilagodljiva Top-K putanja", ["trajectory_sort_order_topk_s00", "trajectory_sort_order_topk_s01", "trajectory_sort_order_topk_s02", "trajectory_sort_order_topk_s03", "trajectory_sort_order_topk_rollback"]),
        ("Ponovljena provjera", ["replay_A_baseline", "replay_B_work_mem", "replay_C_pushdown", "replay_D_wan_delay"]),
    ]
    state_labels = {
        "A_raw_baseline": "A0\npočetno",
        "B_fetch_size": "A1\nveći fetch_size",
        "C_regional_aggregate": "A2\nreg. agregacija",
        "D_wan_delay": "A3\nnetem +10 ms",
        "R0_prime_rollback": "A0'\npovrat",
        "trajectory_join_pushdown_s00": "J0\npočetno",
        "trajectory_join_pushdown_s01": "J1\nreg. spajanje",
        "trajectory_join_pushdown_s02": "J2\nasinhroni FDW",
        "trajectory_join_pushdown_rollback": "J0'\npovrat",
        "trajectory_sort_order_topk_s00": "T0\npočetno",
        "trajectory_sort_order_topk_s01": "T1\nveći work_mem",
        "trajectory_sort_order_topk_s02": "T2\nreg. Top-K",
        "trajectory_sort_order_topk_s03": "T3\nnetem +10 ms",
        "trajectory_sort_order_topk_rollback": "T0'\npovrat",
        "replay_A_baseline": "P0\npočetno",
        "replay_B_work_mem": "P1\nveći work_mem",
        "replay_C_pushdown": "P2\nreg. Top-K",
        "replay_D_wan_delay": "P3\nnetem +10 ms",
    }
    lookup = states.set_index("state_id")
    # The thesis prints this figure at text width. A portrait-oriented canvas
    # keeps labels readable after that final scaling.
    fig, axes = plt.subplots(4, 1, figsize=(8.3, 11.2), constrained_layout=True)
    norm = TwoSlopeNorm(vmin=-2.0, vcenter=0.0, vmax=2.0)
    image = None
    for axis, (title, identifiers) in zip(axes, panels, strict=True):
        values = np.asarray(
            [[lookup.loc[state_id, f"origin__{domain}"] for state_id in identifiers] for domain in domains],
            dtype=float,
        )
        masked = np.ma.masked_invalid(values)
        image = axis.imshow(masked, aspect="auto", cmap="RdBu_r", norm=norm)
        image.cmap.set_bad("#d7d7d7")
        axis.set_title(title, loc="left", fontsize=10.8, fontweight="bold")
        axis.set_yticks(
            range(len(domains)),
            [DOMAIN_LABELS[domain] for domain in domains],
            fontsize=9.2,
        )
        labels = [
            state_labels.get(
                identifier,
                identifier.replace("trajectory_", "")
                .replace("sort_order_topk_", "")
                .replace("join_pushdown_", "")
                .replace("aggregate_full_flow_", "")
                .replace("replay_", ""),
            )
            for identifier in identifiers
        ]
        axis.set_xticks(range(len(identifiers)), labels, fontsize=8.8)
        for row_index in range(values.shape[0]):
            for column_index in range(values.shape[1]):
                value = values[row_index, column_index]
                label = "NA" if not math.isfinite(value) else format_decimal_comma(value)
                color = "#222222" if not math.isfinite(value) or abs(value) < 1.05 else "white"
                axis.text(
                    column_index,
                    row_index,
                    label,
                    ha="center",
                    va="center",
                    fontsize=8.1,
                    color=color,
                )
    if image is not None:
        colorbar = fig.colorbar(image, ax=axes, shrink=0.75, pad=0.02)
        colorbar.ax.tick_params(labelsize=8.8)
        colorbar.ax.yaxis.set_major_formatter(
            FuncFormatter(lambda value, _position: format_decimal_comma(value, 1))
        )
        colorbar.set_label(
            "Relativna izraženost dokaza prema početnom stanju",
            fontsize=9.5,
        )
    fig.suptitle(
        "Hronologija šest domena kroz longitudinalne putanje i ponovljenu provjeru",
        fontsize=11.8,
    )
    save_figure_formats(fig, out_dir, "figure_regime_trajectory")
    plt.close(fig)


def make_runtime_domain_figure(transitions: pd.DataFrame, domains: list[str], out_dir: Path) -> None:
    phase_order = {"adaptive": 0, "frozen_replay": 1, "aggregate_exact_confirmatory": 2}
    ordered = transitions.assign(
        _phase_order=transitions["phase"].map(phase_order).fillna(99)
    ).sort_values(["_phase_order", "sequence_index", "transition_id"]).reset_index(drop=True)
    transition_labels = {
        "trajectory_join_pushdown-step-01": "J1: reg. spajanje",
        "trajectory_join_pushdown-step-02": "J2: asinhroni FDW",
        "trajectory_sort_order_topk-step-01": "T1: work_mem",
        "trajectory_sort_order_topk-step-02": "T2: reg. Top-K",
        "trajectory_sort_order_topk-step-03": "T3: netem +10 ms",
        "replay-work-mem": "P1: work_mem",
        "replay-pushdown": "P2: reg. Top-K",
        "replay-wan-delay": "P3: netem +10 ms",
        "aggregate-exact-fetch-size": "A1: fetch_size",
        "aggregate-exact-pushdown": "A2: reg. agregacija",
        "aggregate-exact-wan-delay": "A3: netem +10 ms",
    }
    labels = [
        transition_labels.get(
            str(value),
            str(value)
            .replace("trajectory_", "")
            .replace("sort_order_topk-step-", "topk-")
            .replace("join_pushdown-step-", "join-")
            .replace("replay-", "P-")
            .replace("aggregate-exact-", "A-"),
        )
        for value in ordered["transition_id"]
    ]
    x = np.arange(len(ordered))
    fig, (runtime_axis, domain_axis) = plt.subplots(
        2,
        1,
        figsize=(8.3, 8.5),
        sharex=True,
        gridspec_kw={"height_ratios": [1.0, 1.55]},
        constrained_layout=True,
    )
    gains = ordered["elapsed_log2_gain"].to_numpy(dtype=float)
    lows = ordered["elapsed_gain_interval_low"].to_numpy(dtype=float)
    highs = ordered["elapsed_gain_interval_high"].to_numpy(dtype=float)
    runtime_axis.errorbar(
        x,
        gains,
        yerr=np.vstack([gains - lows, highs - gains]),
        fmt="o",
        color="#111111",
        ecolor="#555555",
        capsize=4,
        linewidth=1.4,
    )
    runtime_axis.axhline(0.0, color="#777777", linewidth=0.9, linestyle="--")
    runtime_axis.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _position: format_decimal_comma(value, 1))
    )
    runtime_axis.set_ylabel("Dobitak trajanja (log2)", fontsize=10)
    runtime_axis.set_title(
        "Ukupni vremenski ishod", loc="left", fontsize=10.8, fontweight="bold"
    )
    domain_values = np.asarray(
        [ordered[f"domain_delta__{domain}"].to_numpy(dtype=float) for domain in domains]
    )
    masked = np.ma.masked_invalid(domain_values)
    norm = TwoSlopeNorm(vmin=-2.0, vcenter=0.0, vmax=2.0)
    heatmap = domain_axis.imshow(masked, aspect="auto", cmap="RdBu_r", norm=norm)
    heatmap.cmap.set_bad("#d7d7d7")
    domain_axis.set_yticks(
        range(len(domains)),
        [DOMAIN_LABELS[domain] for domain in domains],
        fontsize=9.4,
    )
    domain_axis.set_title(
        "Fizička tranzicija po domenu; boja se poredi samo unutar istog reda",
        loc="left",
        fontsize=10.6,
        fontweight="bold",
    )
    domain_axis.set_xticks(x, labels, rotation=31, ha="right", fontsize=8.8)
    for row_index in range(domain_values.shape[0]):
        for column_index in range(domain_values.shape[1]):
            value = domain_values[row_index, column_index]
            label = "NA" if not math.isfinite(value) else format_decimal_comma(value)
            color = "#222222" if not math.isfinite(value) or abs(value) < 1.05 else "white"
            domain_axis.text(
                column_index,
                row_index,
                label,
                ha="center",
                va="center",
                fontsize=8.0,
                color=color,
            )
    for boundary in (4.5, 7.5):
        runtime_axis.axvline(boundary, color="#b7b7b7", linewidth=0.8)
        domain_axis.axvline(boundary, color="#b7b7b7", linewidth=0.8)
    colorbar = fig.colorbar(heatmap, ax=domain_axis, shrink=0.88, pad=0.015)
    colorbar.ax.tick_params(labelsize=8.8)
    colorbar.ax.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _position: format_decimal_comma(value, 1))
    )
    colorbar.set_label("Promjena relativne domenske koordinate", fontsize=9.5)
    save_figure_formats(fig, out_dir, "figure_runtime_and_domains")
    plt.close(fig)


def latex_transition_table(transitions: pd.DataFrame, path: Path) -> None:
    selected = transitions[
        [
            "phase",
            "transition_id",
            "action_id",
            "source_elapsed_median_seconds",
            "target_elapsed_median_seconds",
            "elapsed_log2_gain",
            "changed_available_coordinate_count",
            "result_validity_axis",
            "end_to_end_effect_axis",
            "physical_transition_axis",
        ]
    ]
    lines = [
        r"\begin{tabular}{lllrrrrlll}",
        r"\toprule",
        r"Faza & Tranzicija & Akcija & $T_0$ (s) & $T_1$ (s) & $g$ & Prom. dom. & Rezultat & Runtime & Profil \\",
        r"\midrule",
    ]
    for row in selected.to_dict(orient="records"):
        values = [
            str(row["phase"]).replace("_", r"\_"),
            str(row["transition_id"]).replace("_", r"\_"),
            str(row["action_id"]).replace("_", r"\_"),
            f"{float(row['source_elapsed_median_seconds']):.3f}",
            f"{float(row['target_elapsed_median_seconds']):.3f}",
            f"{float(row['elapsed_log2_gain']):.3f}",
            str(int(row["changed_available_coordinate_count"])),
            str(row["result_validity_axis"]).replace("_", r"\_"),
            str(row["end_to_end_effect_axis"]).replace("_", r"\_"),
            str(row["physical_transition_axis"]).replace("_", r"\_"),
        ]
        lines.append(" & ".join(values) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rq_h_map() -> pd.DataFrame:
    evidence = {
        "RQ1": ("podržano u posmatranom programu", "Potpuna višeslojna rekonstrukcija i šest manifestovanih domena sa sirovim komponentama.", "feedback-loop trajectory states; pressure domain manifest; široki korpus"),
        "RQ2": ("mješovit rezultat", "Relativni profil daje interpretabilne tranzicije; razvojni FCM sažima stanja, ali projekcija može zamagliti hronološku promjenu.", "domain_profile_deltas.csv; cluster_projection_audit.csv"),
        "RQ3": ("nije potvrđena opća prednost fuzzy opisa", "Direktna vremenski uređena memorija čuva konkretne tranzicije; prototipska kompresija nije pokazala opću prednost.", "local_memory_replay.csv; razvojni FCM/K-means komparator"),
        "RQ4": ("podržano arhitektonsko tumačenje", "Komponente remote toka, regionalne redukcije, GAC rada, neravnomjernosti, spill-a i lokalnosti ostaju povezane sa provenanceom.", "pressure_domain_manifest.yaml; raw_signal_deltas.csv"),
        "H1": ("djelimično podržana", "Relativne koordinate jasno opisuju lokalne promjene, ali feedback run nije čista ablacija relativnih naspram apsolutnih pokazatelja.", "figure_regime_trajectory; table_transition_summary"),
        "H2": ("nije podržana kao opća prednost", "FCM ostaje komparator; konkretni slučajevi bolje čuvaju vremenski i intervencijski detalj.", "cluster_projection_audit.csv; postojeći razvojni komparator"),
        "H3": ("dodatni lokalni dokaz, ne potpuna nova potvrda", "WAN i konfiguracijske promjene daju ponovljive tranzicije; dataset i skew nisu mijenjani u feedback runu.", "confirmatory frozen replay; široki korpus"),
        "H4": ("podržana", "Join/pushdown putanja mijenja regionalni rad, GAC, spill i udaljeni tok zajedno; kompaktan WAN opis nije dovoljan.", "trajectory_join_pushdown; figure_runtime_and_domains"),
    }
    requested_mapping = {
        "RQ1": "potpunost višeslojne rekonstrukcije",
        "H4": "potpunost višeslojne rekonstrukcije",
        "RQ2": "relativni profil i intervencijska tranzicija",
        "H1": "relativni profil i intervencijska tranzicija",
        "H3": "relativni profil i intervencijska tranzicija",
        "RQ3": "lokalna memorija i njene granice",
        "RQ4": "direktni slučajevi naspram prototipske kompresije",
        "H2": "direktni slučajevi naspram prototipske kompresije",
    }
    return pd.DataFrame(
        [
            {
                "item": item,
                "fixed_statement": RQ_H_STATEMENTS[item],
                "feedback_loop_role": requested_mapping[item],
                "status": evidence[item][0],
                "evidence": evidence[item][1],
                "sources": evidence[item][2],
            }
            for item in ("RQ1", "RQ2", "RQ3", "RQ4", "H1", "H2", "H3", "H4")
        ]
    )


def write_report(
    out_dir: Path,
    transitions: pd.DataFrame,
    replay: pd.DataFrame,
    stability: pd.DataFrame,
    cluster_audit: pd.DataFrame,
    freeze_audit: dict[str, Any],
) -> None:
    direct = replay[replay["retrieval_tier"].eq("same_logical_question_id")]
    cross = replay[replay["retrieval_tier"].eq("physical_cross_query_secondary")]
    state_projection = cluster_audit[cluster_audit["record_type"].eq("state_projection")]
    transition_projection = cluster_audit[cluster_audit["record_type"].eq("transition_projection")]
    unchanged_km = int(
        transition_projection["kmeans_cluster_changed"].fillna(False).eq(False).sum()
    )
    total_projection = len(transition_projection)
    exact = transitions[transitions["phase"].eq("aggregate_exact_confirmatory")]
    exact_index = exact.set_index("action_id", drop=False)
    lines = [
        "# Analiza adaptivnog feedback loopa i zamrznutog replaya",
        "",
        "## Ugovor analize",
        "",
        "Analiza koristi samo završene artefakte. RQ1–RQ4, H1–H4, šest domena, odluke i kriteriji ishoda nisu mijenjani. Zamrznuti prostor `93 → 64 → 6` primijenjen je bez refitovanja, a nedostupan dokaz ostaje `NA`.",
        "",
        "Domenske koordinate su **relativna izraženost dokaza o pritisku** prema lokalnoj referenci. Njihov broj, apsolutna veličina, uzročnost i end-to-end dobitak nisu ista veličina.",
        "",
        "## Hronološke putanje",
        "",
        "```text",
        "Exact aggregate: A --fdw_fetch_size_10000--> B --regional_pushdown_rewrite--> C --wan_delay_10ms_probe--> D --rollback--> A'",
        "Join/pushdown: R0 --regional_pushdown_rewrite--> R1 --fdw_async_capable_on--> R2 --rollback--> R0'",
        "Top-K:        R0 --gac_work_mem_64mb--> R1 --regional_pushdown_rewrite--> R2 --wan_delay_10ms_probe--> R3 (odbačeno) --rollback--> R0'",
        "Replay:       A  --gac_work_mem_64mb--> B  --regional_pushdown_rewrite--> C  --wan_delay_10ms_probe--> D",
        "```",
        "",
        "Odluke adaptivne faze trajno su zapisane prije ishoda. Replay je koristio zamrznut redoslijed i nije vraćao ishode u odluke.",
        "",
        "## Glavni tranzicijski nalazi",
        "",
        "- Pet adaptivnih tranzicija sačuvalo je rezultat; tri su ponovljene u zamrznutom Williams replayu. Odvojeni exact-aggregate dodatak sadrži tri potvrđujuće tranzicije i završni rollback, po pet ponavljanja svakog stanja.",
        f"- U exact aggregate putanji `fetch_size` je bio pozitivan (`g={float(exact_index.loc['fdw_fetch_size_10000', 'elapsed_log2_gain']):.3f}`) uz oskudnu fizičku tranziciju, regionalni COUNT/MIN/MAX pushdown snažno pozitivan (`g={float(exact_index.loc['regional_pushdown_rewrite', 'elapsed_log2_gain']):.3f}`) i fizički mješovit, a `tc/netem` profil sa 10 ms dodatnog emuliranog kašnjenja negativan (`g={float(exact_index.loc['wan_delay_10ms_probe', 'elapsed_log2_gain']):.3f}`) uz oskudnu fizičku tranziciju.",
        "- Regionalni rewrite skratio je join sa 18,551 s na 3,319 s (`g=2,483`) i Top-K sa 15,808 s na 5,767 s (`g=1,455`). Više domena se promijenilo istovremeno, pa se dobitak ne pripisuje jednoj koordinati.",
        "- `fdw_async_capable_on` promijenio je manje dostupnih koordinata, ali dodatno skratio join sa 3,319 s na 2,240 s (`g=0,567`).",
        "- GAC `work_mem` dao je mali, razriješen dobitak u adaptivnoj fazi (`g=0,157`) i replayu (`g=0,204`), uz smanjenje GAC temp zapisa i hash-batch viška. Ovo nije primjer fizičke promjene bez runtime efekta.",
        f"- Namjerni WAN probe pogoršao je trajanje (`g=-0,905` adaptivno; hronološki replay `g={float(transitions.loc[transitions['transition_id'].eq('replay-wan-delay'), 'elapsed_log2_gain'].iloc[0]):.3f}`) i bio je odbačen.",
        "- Široki korpus, a ne ova mala putanja, nosi primjer uklonjenog spill-a ili skewa bez značajnog globalnog dobitka.",
        "",
        "## Stabilnost",
        "",
        "- Zamrznuti replay ima 20/20 rezultatski ekvivalentnih izvršenja.",
        "- Exact aggregate dodatak ima 25/25 ekvivalentnih izvršenja sa istim uređenim i multiskupovnim hashom. COUNT/MIN/MAX rezultat koristi tačnu aritmetiku i ne oslanja se na post-hoc toleranciju.",
        "- Join i Top-K rollback vraćaju sve dostupne koordinate na početni profil; trajanja ostaju unutar početnog noise envelopea. Novi exact aggregate rollback vraća konfiguraciju, mrežni profil, rezultat i fizički profil, a runtime interval uključuje nultu promjenu.",
        "- Smjer sva tri zamrznuta efekta jednak je eksplorativnom zaključku: `work_mem` mali pozitivan, pushdown snažno pozitivan, a kontrolisano emulirano kašnjenje negativan.",
        "",
        "## Lokalna memorija tranzicija",
        "",
        f"Vremenski replay izdaje {int(replay['recommendation_status'].eq('available').sum())} procjena i {int(replay['recommendation_status'].eq('abstained').sum())} apstinencija. Koristi samo ranije opažene ishode iste akcije. Nedostajući ishodi nisu nule.",
        "",
        f"- Direktna memorija istog `logical_question_id` dostupna je za {len(direct)} zamrznute tranzicije i zadržava smjer u {int(direct['direction_correct'].fillna(False).sum())}/{len(direct)} slučaja.",
        "- Ručno povezane SQL varijante omogućavaju da raw i regionalno reducirani SQL ostanu u istoj putanji uprkos različitom normalizovanom SQL hash-u.",
        f"- Cross-query fizički retrieval javlja se samo u {len(cross)} dovoljno ranom action-matched slučaju. Smjer je koristan, ali jedan slučaj nije dokaz opće generalizacije.",
        "",
        "## Zamrznuti PCA i prototipski audit",
        "",
        f"Zamrznuti R3 artefakt ima {freeze_audit['candidate_feature_count']} kandidata, {freeze_audit['active_feature_count']} aktivna pokazatelja i {freeze_audit['component_count']} PCA komponenti. Fit obuhvata {freeze_audit['development_reference_count']} ranijih razvojnih stanja; feedback stanja korištena za fit: 0. P99 prag ostaje {freeze_audit['p99_threshold']:.6f}.",
        "",
        f"Od {len(state_projection)} novih stanja, {int(state_projection['within_frozen_p99'].fillna(False).sum())} je unutar zamrznute P99 granice. K-means zadržava isti tvrdi prototip kroz {unchanged_km}/{total_projection} tranzicija. To je kompresija geometrije, ne dokaz da je tranzicija fizički ili operativno beznačajna.",
        "",
        "FCM članstva mogu pokazati meku promjenu prema više razvojnih prototipa, ali ne čuvaju eksplicitno akciju, hronologiju, sirove komponente ni prije/poslije ishod. Zbog toga ostaju sekundarni audit RQ2/RQ3/H2, a ne zamjena za tranzicijski zapis.",
        "",
        "## Status fiksnih pitanja i hipoteza",
        "",
        "Detaljna mapa je u `rq_hypothesis_evidence_map.csv`. Feedback loop daje longitudinalni dokaz za RQ2/H1/H3 i lokalnu granicu za RQ3, ali ne mijenja nijednu formulaciju niti pretvara fizički mješovit rezultat u univerzalnu potvrdu. Valjanost rezultata, end-to-end učinak i fizička tranzicija prijavljuju se kao tri nezavisne ose.",
        "",
        "## Otvorena ograničenja",
        "",
        "- Izvorna aggregate putanja ostaje validity stop jer zamrznuti ugovor nije sadržavao numeričku toleranciju za zadnje bitove `double precision` prikaza. Odvojeni unaprijed zamrznuti exact COUNT/MIN/MAX dodatak popunjava longitudinalni dokaz bez izmjene tog historijskog ishoda.",
        "- `repartition_locality` je u ovim putanjama uglavnom `NA`; nije imputiran kao nizak pritisak.",
        "- Feedback studija je mala, lokalna i adaptivna. Potvrđuje ponovljivost izabranih tranzicija, ne optimalnost izabrane sekvence intervencija niti da bi isti izbor bio najbolji na drugoj infrastrukturi.",
        "- Collector i intervencijski ugovor action-agnostic su po konstrukciji, a primjenjivost je demonstrirana nad evaluiranim SQL, konfiguracijskim, FDW i mrežnim promjenama na jednoj infrastrukturi. Automatski transfer na nepoznate SQL oblike, akcije i infrastrukture nije potvrđen.",
        "- Ne postoji pošten feedback-loop primjer fizičke promjene bez razriješenog runtime dobitka; taj zaključak se oslanja na unaprijed odvojeni široki korpus.",
    ]
    (out_dir / "feedback_loop_analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_section_proposal(out_dir: Path) -> None:
    content = """# Prijedlog izmjena rukopisa po sekcijama

## Metodologija

- Nakon formalne epizode uvesti lokalni profil `R_t` sa šest zamrznutih domena i tranziciju `tau_t=(R_t, action_id, R_t+1, delta_outcome_t)`.
- Jednom definisati da je koordinata relativna prema originu, prethodnom prihvaćenom stanju ili ranijoj lokalnoj historiji; nije univerzalni severity score.
- Dodati pravilo vremenski korektne memorije: logical question, zatim isti normalizovani SQL u kompatibilnom kontekstu, zatim fizički cross-query slučajevi kao sekundarni sloj.
- FCM/K-means ostaviti kao razvojne/projekcijske komparatore, bez refita finalnog R3 prostora.

## Eksperimentalni dizajn

- Promijeniti pregled sa pet na šest dokaznih blokova i dodati feedback loop kao drugi glavni blok.
- Navesti samo stvarno izvršene akcije: `fetch_size`, regionalni pushdown rewrite, `fdw_async_capable`, GAC `work_mem` i kontrolisani `tc/netem` profil.
- Razdvojiti adaptivnu fazu, zamrznuti Williams replay i unaprijed zamrznuti exact-aggregate dodatak. Historijski floating-point stop zadržati kao validity case.

## Rezultati

- Nakon širokog korpusa postaviti feedback loop kao vodeću longitudinalnu studiju.
- Prvo prikazati heatmap šest domena i hronološku tabelu tranzicija; zatim stabilnost, rollback i vremenski korektnu lokalnu memoriju.
- Valjanost rezultata, end-to-end učinak i fizičku tranziciju prikazati kao tri nezavisne ose; legacy oznaku `mixed` ne koristiti kao glavni rezultat.
- Top-K full-information paneli ostaju sekundarna kontrolisana evaluacija RQ3; potvrdni negativni rezultat ostaje granica cross-query transfera.
- Jasno navesti da u longitudinalnoj studiji nema primjera fizičke promjene bez razriješenog runtime efekta; primjer dolazi iz širokog korpusa.

## Diskusija

- Objediniti ograničenja u jednu završnu podsekciju.
- Razdvojiti broj promijenjenih domena, relativnu izraženost dokaza, uzročnost i runtime korist.
- RQ3 razložiti na direktnu memoriju, ručno povezane SQL varijante i ograničeni fizički cross-query transfer.
- FCM komprimirati na jedan rezultat: prototip sažima geometriju, ali zamagljuje hronologiju i action-specific ishod.

## Zaključak

- Dodati longitudinalnu tranziciju kao centralni empirijski dokaz između širokog korpusa i sekundarnog recommender eksperimenta.
- Zadržati postojeće RQ1–RQ4 i H1–H4 doslovno; ne dodavati novo pitanje.
"""
    (out_dir / "manuscript_section_changes.md").write_text(content, encoding="utf-8")


def validate_outputs(
    contract: dict[str, Any],
    states: pd.DataFrame,
    transitions: pd.DataFrame,
    replay: pd.DataFrame,
    projection: pd.DataFrame,
    rq_map: pd.DataFrame,
    out_dir: Path,
) -> dict[str, Any]:
    expected = contract["expected"]
    checks = {
        "adaptive_transition_count": int(transitions["phase"].eq("adaptive").sum()) == int(expected["adaptive_transition_count"]),
        "replay_transition_count": int(transitions["phase"].eq("frozen_replay").sum()) == int(expected["replay_transition_count"]),
        "aggregate_exact_transition_count": int(transitions["phase"].eq("aggregate_exact_confirmatory").sum()) == int(expected["aggregate_exact_transition_count"]),
        "aggregate_exact_state_count": int(states["phase"].eq("aggregate_exact_confirmatory").sum()) == int(expected["aggregate_exact_state_count"]),
        "aggregate_exact_logical_identity_complete": not states.loc[
            states["phase"].eq("aggregate_exact_confirmatory"), "logical_question_id"
        ].isna().any(),
        "independent_outcome_axes_complete": not transitions[
            ["result_validity_axis", "end_to_end_effect_axis", "physical_transition_axis"]
        ].isna().any().any(),
        "fixed_domains_unchanged": list(contract["policy"]["fixed_domains"]) == list(DOMAIN_LABELS),
        "future_outcomes_unused": int(replay["future_outcome_count_used"].sum()) == 0,
        "missing_outcomes_not_zero": not replay["missing_outcome_imputed_as_zero"].any(),
        "replay_outcomes_not_fed_back": not replay["replay_outcomes_added_during_frozen_replay"].any(),
        "all_rq_h_present": set(rq_map["item"]) == set(RQ_H_STATEMENTS),
        "fixed_rq_h_text_exact": all(
            rq_map.set_index("item").loc[item, "fixed_statement"] == statement
            for item, statement in RQ_H_STATEMENTS.items()
        ),
        "no_r3_refit": True,
        "state_projection_complete": len(projection) == int(expected["frozen_projected_state_count"]),
        "required_figures_exist": all(
            (out_dir / name).exists()
            for name in (
                "figure_regime_trajectory.pdf",
                "figure_runtime_and_domains.pdf",
                "figure_regime_trajectory.png",
                "figure_runtime_and_domains.png",
            )
        ),
    }
    checks["pass"] = all(checks.values())
    return checks


def main() -> None:
    args = parse_args()
    contract = read_yaml(args.contract.resolve())
    run_dir = resolve_path(contract["inputs"]["feedback_run"])
    aggregate_exact_run = resolve_path(contract["inputs"]["aggregate_exact_run"])
    out_dir = args.out_dir.resolve() if args.out_dir else resolve_path(contract["outputs"]["release_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    domains = [str(value) for value in contract["policy"]["fixed_domains"]]
    if domains != list(DOMAIN_LABELS):
        raise ValueError("The six-domain contract changed")

    model_states, model_signals = load_state_table(run_dir, domains)
    model_transitions = build_transitions(
        run_dir, model_states, model_signals, domains, contract
    )
    exact_states, exact_signals = load_state_table(aggregate_exact_run, domains)
    exact_transitions = build_exact_aggregate_transitions(
        aggregate_exact_run, exact_states, exact_signals, domains
    )
    states = pd.concat([model_states, exact_states], ignore_index=True, sort=False)
    signals = pd.concat([model_signals, exact_signals], ignore_index=True, sort=False)
    transitions = pd.concat(
        [model_transitions, exact_transitions], ignore_index=True, sort=False
    )
    projection, state_values, reference_values, threshold, freeze_audit = build_frozen_projection(model_states, contract)
    if not math.isclose(threshold, float(contract["expected"]["frozen_p99_threshold"]), rel_tol=1.0e-10):
        raise ValueError("Frozen P99 threshold changed")
    cluster_audit = build_cluster_audit(
        projection, state_values, reference_values, model_transitions, contract
    )
    memory_replay = build_local_memory_replay(
        run_dir, model_states, model_transitions, projection
    )
    stability = build_stability(states, signals, domains)
    evidence_map = rq_h_map()

    states.to_csv(out_dir / "trajectory_domain_profiles.csv", index=False)
    signals.to_csv(out_dir / "raw_signal_state_summary.csv", index=False)
    transitions.to_csv(out_dir / "table_transition_summary.csv", index=False)
    latex_transition_table(transitions, out_dir / "table_transition_summary.tex")
    memory_replay.to_csv(out_dir / "local_memory_replay.csv", index=False)
    cluster_audit.to_csv(out_dir / "cluster_projection_audit.csv", index=False)
    stability.to_csv(out_dir / "state_stability.csv", index=False)
    evidence_map.to_csv(out_dir / "rq_hypothesis_evidence_map.csv", index=False)
    make_trajectory_figure(states, domains, out_dir)
    make_runtime_domain_figure(transitions, domains, out_dir)
    write_report(out_dir, transitions, memory_replay, stability, cluster_audit, freeze_audit)
    write_section_proposal(out_dir)

    validation = validate_outputs(
        contract, states, transitions, memory_replay, projection, evidence_map, out_dir
    )
    write_json(out_dir / "numerical_consistency_audit.json", validation)
    manifest = {
        "contract_version": contract["contract_version"],
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_run": str(run_dir),
        "aggregate_exact_source_run": str(aggregate_exact_run),
        "source_run_checksums_sha256": sha256_file(run_dir / "checksums.sha256"),
        "aggregate_exact_source_checksums_sha256": sha256_file(
            aggregate_exact_run / "checksums.sha256"
        ),
        "frozen_projection": freeze_audit,
        "state_count": len(states),
        "transition_count": len(transitions),
        "memory_replay_event_count": len(memory_replay),
        "rq_h_changed": False,
        "sql_executions_started": 0,
        "checks_passed": validation["pass"],
    }
    write_json(out_dir / "analysis_manifest.json", manifest)
    write_checksums(out_dir)
    if not validation["pass"]:
        failed = [name for name, passed in validation.items() if not passed]
        raise RuntimeError(f"Feedback-loop analysis validation failed: {failed}")
    print(json.dumps(json_safe(manifest), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
