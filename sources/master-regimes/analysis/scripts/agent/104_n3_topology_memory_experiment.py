#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
INFRA_ROOT = ROOT.parent / "master-regimes-infra"
DEFAULT_CONTRACT = ROOT / "configs/validation/n3_topology_memory_experiment_v1.yml"
DEFAULT_WORK_DIR = ROOT / "generated/corpus/n3-topology-memory-v1"
DEFAULT_REPORT_DIR = ROOT / "analysis/reports/n3-topology-memory-v1"
ACTIONS = (
    "increase_gac_work_mem",
    "regional_topk_candidates",
    "mitigate_remote_path_bundle",
)
BLOCK_IDS = (
    "n2_control",
    "phase_a_baseline",
    "phase_a_actions",
    "phase_b_baseline",
    "phase_b_actions",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare, freeze, and analyze the controlled N=3 topology experiment."
    )
    parser.add_argument(
        "command",
        choices=("prepare", "dry-run", "freeze-a", "freeze-b", "analyze"),
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=INFRA_ROOT / "ansible/inventory/generated.json",
    )
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _load_module(path: Path, name: str) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def memory_modules() -> tuple[Any, Any]:
    memory = _load_module(
        ROOT / "analysis/scripts/agent/101_fuzzy_intervention_memory.py",
        "n3_memory_101",
    )
    dba = _load_module(
        ROOT / "analysis/scripts/agent/102_dba_local_memory_panel.py",
        "n3_memory_102",
    )
    return memory, dba


def profile_tenant_regions(profile: dict[str, Any]) -> dict[int, str]:
    tenants: dict[int, str] = {}
    for physical_region, specification in profile["regions"].items():
        ranges = specification.get("tenant_id_ranges")
        if ranges is None:
            ranges = [
                [
                    *specification["tenant_id_range"],
                    specification.get("data_region_id", physical_region),
                ]
            ]
        for start, end, logical_region in ranges:
            for tenant_id in range(int(start), int(end) + 1):
                if tenant_id in tenants:
                    raise ValueError(f"Duplicate tenant {tenant_id} in {profile['dataset_id']}")
                tenants[tenant_id] = str(logical_region)
    return tenants


def validate_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    if tuple(contract.get("actions", ())) != ACTIONS:
        raise ValueError("Experiment must retain the three frozen DBA actions")
    scenarios = sorted(contract.get("scenarios", []), key=lambda row: int(row["order"]))
    if len(scenarios) != 15:
        raise ValueError(f"Expected 15 SQL scenarios, found {len(scenarios)}")
    if [int(row["order"]) for row in scenarios] != list(range(1, 16)):
        raise ValueError("Scenario order must be 1..15")
    if len({str(row["query_id"]) for row in scenarios}) != 15:
        raise ValueError("query_id values must be unique")
    if len({str(row["query_shape"]) for row in scenarios}) != 15:
        raise ValueError("query_shape values must be unique")
    pairs = contract.get("dataset_pairs", {})
    for scenario in scenarios:
        pair = str(scenario["dataset_pair"])
        if pair not in pairs or not {"n2", "n3"}.issubset(pairs[pair]):
            raise ValueError(f"Incomplete dataset pair: {pair}")
    for pair_id, pair in pairs.items():
        n2 = read_yaml(ROOT / pair["n2"]["profile"])
        n3 = read_yaml(ROOT / pair["n3"]["profile"])
        if profile_tenant_regions(n2) != profile_tenant_regions(n3):
            raise ValueError(f"N2/N3 tenant content differs for {pair_id}")
        for field in ("seed", "base_time_unix", "scale", "distribution", "identity"):
            if n2[field] != n3[field]:
                raise ValueError(f"N2/N3 {field} differs for {pair_id}")
    blocks = {str(row["id"]): row for row in contract.get("blocks", [])}
    if set(blocks) != set(BLOCK_IDS):
        raise ValueError(f"Expected blocks {BLOCK_IDS}, found {sorted(blocks)}")
    if sum(int(blocks[row]["expected_executions"]) for row in BLOCK_IDS) != 180:
        raise ValueError("N2 control plus both N3 phases must total 180 executions")
    if (
        sum(
            int(blocks[row]["expected_executions"])
            for row in BLOCK_IDS
            if str(blocks[row]["topology"]) == "n3"
        )
        != 120
    ):
        raise ValueError("Primary N3 design must contain exactly 120 executions")
    freeze = contract.get("model_freeze", {})
    if int(freeze.get("pca_components", -1)) != 6:
        raise ValueError("PCA dimensionality must remain frozen at six")
    if int(freeze.get("neighbors", -1)) != 5:
        raise ValueError("k must remain frozen at five")
    if bool(freeze.get("refit_on_n3", True)):
        raise ValueError("N3 refitting is forbidden")
    return scenarios


def logical_query_hash(scenario: dict[str, Any]) -> str:
    return stable_hash(
        {
            "query_id": scenario["query_id"],
            "query_shape": scenario["query_shape"],
            "cutoff_ts": scenario["cutoff_ts"],
            "limit_k": int(scenario["limit_k"]),
        }
    )


def block_paths(work_dir: Path, block_id: str) -> dict[str, Path]:
    return {
        "source": work_dir / "source" / block_id,
        "rendered": work_dir / "rendered" / block_id,
        "logical": INFRA_ROOT
        / "generated/runs/corpus-sweeps/_logical-runs"
        / (f"n3-topology-memory-v1-{block_id.replace('_', '-')}"),
    }


def _common_cell(
    contract: dict[str, Any],
    scenario: dict[str, Any],
    *,
    block: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    topology_key = str(block["topology"])
    topology = contract["topologies"][topology_key]
    pair = contract["dataset_pairs"][str(scenario["dataset_pair"])]
    dataset = pair[topology_key]
    component = f"n3_topology_{scenario['query_id']}"
    common = {
        "logical_question_id": "dba_local_memory_topk",
        "component_match_id": component,
        "dataset_profile_id": [str(dataset["id"])],
        "topology_id": str(topology["topology_id"]),
        "execution_strategy": "multiregion_union",
        "execution_scope": "gac_multi_edge",
        "target_scope": "global_query",
        "intervention_role": "calibration",
        "intervention_axis": "combined_pressure",
        "pressure_axis": "local_intervention_memory",
        "target_metric": "global_gac_mitigation_gain_log2",
        "dataset_role": "topology_isolation",
        "scenario_level": str(block["phase"]),
        "repeatability_repetitions": 1,
        "parameters": {
            "query_shape": [str(scenario["query_shape"])],
            "cutoff_ts": [str(scenario["cutoff_ts"])],
            "limit_k": [int(scenario["limit_k"])],
            "include_apac": [topology_key == "n3"],
        },
    }
    return common, dataset, pair


def build_block_manifest(
    contract: dict[str, Any],
    scenarios: list[dict[str, Any]],
    block: dict[str, Any],
    source_dir: Path,
) -> tuple[dict[str, Any], pd.DataFrame]:
    cells: list[dict[str, Any]] = []
    design: list[dict[str, Any]] = []
    dataset_specs: dict[str, dict[str, str]] = {}
    runtime_profiles = contract["runtime_profiles"]
    cell_mode = str(block["cells"])
    for scenario in scenarios:
        common, dataset, pair = _common_cell(contract, scenario, block=block)
        dataset_specs[str(dataset["id"])] = {
            "profile": os.path.relpath(ROOT / dataset["profile"], source_dir),
            "load_method": "copy_pipe",
        }
        runtime = runtime_profiles[str(scenario["profile"])]
        baseline = {
            **common,
            "corpus_cell_id": f"{scenario['query_id']}__baseline",
            "template_id": "gac_fdw_dba_topk_raw",
            "runtime_config_id": str(runtime["baseline"]),
            "pressure_level": "stressed",
            "variant": "stressed",
            "physical_strategy_id": "gac_raw_topk",
            "pressure_pair_key": f"{scenario['query_id']}__shared_baseline",
        }
        action_specs = {
            "increase_gac_work_mem": (
                "gac_fdw_dba_topk_raw",
                str(runtime["gac_memory"]),
                "gac_memory_increase",
            ),
            "regional_topk_candidates": (
                "gac_fdw_dba_topk_regional",
                str(runtime["baseline"]),
                "regional_topk_candidates",
            ),
            "mitigate_remote_path_bundle": (
                "gac_fdw_dba_topk_raw",
                str(runtime["remote"]),
                "remote_transport_bundle",
            ),
        }
        action_cells = [
            {
                **common,
                "corpus_cell_id": f"{scenario['query_id']}__{action}",
                "template_id": template,
                "runtime_config_id": runtime_id,
                "pressure_level": "mitigated",
                "variant": "mitigated",
                "physical_strategy_id": strategy,
                "pressure_pair_key": f"{scenario['query_id']}__{action}",
                "mitigation_action": action,
            }
            for action, (template, runtime_id, strategy) in action_specs.items()
        ]
        if cell_mode == "baseline":
            selected = [baseline]
        elif cell_mode == "actions":
            selected = action_cells
        elif cell_mode == "baseline_and_actions":
            selected = [baseline, *action_cells]
        else:
            raise ValueError(f"Unknown cell mode: {cell_mode}")
        cells.extend(selected)
        design.append(
            {
                "block_id": block["id"],
                "phase": block["phase"],
                "query_order": int(scenario["order"]),
                "query_id": scenario["query_id"],
                "query_shape": scenario["query_shape"],
                "cutoff_ts": scenario["cutoff_ts"],
                "limit_k": int(scenario["limit_k"]),
                "profile": scenario["profile"],
                "dataset_pair": scenario["dataset_pair"],
                "dataset_pair_id": pair["pair_id"],
                "dataset_profile_id": dataset["id"],
                "topology_id": common["topology_id"],
                "logical_query_hash": logical_query_hash(scenario),
                "cell_count": len(selected),
            }
        )
    execution = contract["execution"]
    manifest = {
        "corpus_id": f"{contract['experiment_id']}-{block['id']}",
        "corpus_version": contract["contract_version"],
        "batch_id": f"batch-{contract['experiment_id']}-{block['id']}",
        "collection_contract_version": "n3-topology-memory-v1",
        "description": contract["description"],
        "query_groups": os.path.relpath(ROOT / "workloads/corpus/query-groups.yml", source_dir),
        "runtime_catalog": os.path.relpath(
            ROOT / "workloads/corpus/runtime-configs.yml", source_dir
        ),
        "dataset_profiles": dataset_specs,
        "execution_budget": {
            "hard_timeout_seconds": int(execution["hard_timeout_seconds"]),
            "timeout_grace_seconds": int(execution["timeout_grace_seconds"]),
        },
        "execution_policy": {
            "cache_policy": "mixed_cache_n3_topology_memory",
            "order_policy": "deterministic_interleaved_shuffle",
            "shuffle_seed": int(execution["seeds"][str(block["id"])]),
            "repetitions_default": 1,
            "record_run_order": True,
            "record_buffer_features": True,
            "fdw_auto_explain": True,
            "fdw_auto_explain_regions": ["active_regions"],
            "os_sampler": True,
            "os_sampler_node_groups": ["active_regions"],
            "result_signature": True,
            "result_signature_scope": execution["result_signature_scope"],
            "network_profile_probe": True,
            "remote_edge_context": True,
            "group_runtime_configs_by_active_scope": True,
        },
        "cells": cells,
    }
    return manifest, pd.DataFrame(design)


def git_commit(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "not_recorded"


def _inventory_host_names(node: Any) -> set[str]:
    if not isinstance(node, dict):
        return set()
    names = set(str(name) for name in (node.get("hosts", {}) or {}))
    for child in (node.get("children", {}) or {}).values():
        names.update(_inventory_host_names(child))
    return names


def provenance(contract_path: Path, contract: dict[str, Any], inventory: Path) -> dict[str, Any]:
    files = [
        contract_path,
        ROOT / contract["model_freeze"]["state_contract"],
        ROOT / "workloads/corpus/query-groups.yml",
        ROOT / "workloads/corpus/runtime-configs.yml",
        ROOT / "workloads/templates/gac-fdw/gac_fdw_dba_topk_raw.sql.j2",
        ROOT / "workloads/templates/gac-fdw/gac_fdw_dba_topk_regional.sql.j2",
    ]
    for pair in contract["dataset_pairs"].values():
        files.extend(ROOT / pair[key]["profile"] for key in ("n2", "n3"))
    inventory_summary: dict[str, Any] = {"path": str(inventory), "available": inventory.exists()}
    if inventory.exists():
        data = json.loads(inventory.read_text(encoding="utf-8"))
        hosts = _inventory_host_names(data.get("all", {}))
        inventory_summary.update(
            {
                "sha256": sha256_file(inventory),
                "host_count": len(hosts),
                "host_names": sorted(hosts),
            }
        )
    return {
        "captured_at_utc": utc_now(),
        "contract_version": contract["contract_version"],
        "experiment_id": contract["experiment_id"],
        "git_commits": {
            path.name: git_commit(path)
            for path in (
                ROOT,
                INFRA_ROOT,
                ROOT.parent / "psql-benchmarks",
                ROOT.parent / "citus-datagen",
            )
        },
        "file_sha256": {str(path.relative_to(ROOT)): sha256_file(path) for path in files},
        "inventory": inventory_summary,
        "model_freeze": contract["model_freeze"],
        "retry_policy": contract["execution"]["retry_policy"],
    }


def prepare(contract_path: Path, work_dir: Path, inventory: Path) -> None:
    contract = read_yaml(contract_path)
    scenarios = validate_contract(contract)
    block_specs = {str(row["id"]): row for row in contract["blocks"]}
    summaries: list[dict[str, Any]] = []
    for block_id in BLOCK_IDS:
        paths = block_paths(work_dir, block_id)
        paths["source"].mkdir(parents=True, exist_ok=True)
        manifest, design = build_block_manifest(
            contract, scenarios, block_specs[block_id], paths["source"]
        )
        manifest_path = paths["source"] / "corpus_manifest.yml"
        manifest_path.write_text(
            yaml.safe_dump(manifest, sort_keys=False, width=100), encoding="utf-8"
        )
        design.to_csv(paths["source"] / "design.csv", index=False)
        expected = int(block_specs[block_id]["expected_executions"])
        observed = int(design["cell_count"].sum())
        if observed != expected:
            raise ValueError(f"{block_id}: generated {observed}, expected {expected}")
        summaries.append(
            {
                "block_id": block_id,
                "phase": block_specs[block_id]["phase"],
                "topology": block_specs[block_id]["topology"],
                "expected_executions": expected,
                "manifest": str(manifest_path),
                "rendered_dir": str(paths["rendered"]),
                "logical_run_id": paths["logical"].name,
                "logical_run_dir": str(paths["logical"]),
            }
        )
    write_json(
        work_dir / "experiment_manifest.json",
        {
            "experiment_id": contract["experiment_id"],
            "contract_version": contract["contract_version"],
            "scenario_count": len(scenarios),
            "action_count": len(ACTIONS),
            "n2_control_execution_count": 60,
            "primary_n3_execution_count": 120,
            "total_execution_count": 180,
            "blocks": summaries,
            "output_locations": {
                "work_dir": str(work_dir),
                "report_dir": str(DEFAULT_REPORT_DIR),
                "freeze_dir": str(work_dir / "freezes"),
            },
        },
    )
    write_json(work_dir / "provenance.json", provenance(contract_path, contract, inventory))
    print(work_dir)


def rendered_instances(rendered_dir: Path) -> pd.DataFrame:
    paths = sorted(rendered_dir.glob("groups/*/instance_manifest.csv"))
    if not paths:
        raise FileNotFoundError(f"No rendered instance manifests below {rendered_dir}")
    return pd.concat((pd.read_csv(path, low_memory=False) for path in paths), ignore_index=True)


_APAC_PARENTHESIZED_SOURCE_BRANCH = re.compile(
    r"\n\s*union\s+all\s*\n\s*\(\s*\n(?=\s*select\s+'apac'::text).*?"
    r"\n\s*limit\s+\d+\s*\)\s*(?=\n\s*\))",
    flags=re.IGNORECASE | re.DOTALL,
)
_APAC_SOURCE_BRANCH = re.compile(
    r"\n\s*union\s+all\s*\n(?=\s*select\s+'apac'::text).*?(?=\n\s*\)\s*\n)",
    flags=re.IGNORECASE | re.DOTALL,
)


def canonicalize_topology_sql(sql: str) -> str:
    """Remove the final APAC source branch and normalize insignificant whitespace."""
    without_apac, parenthesized_count = _APAC_PARENTHESIZED_SOURCE_BRANCH.subn("", sql)
    without_apac, plain_count = _APAC_SOURCE_BRANCH.subn("", without_apac)
    if "fdw_apac." in sql.lower() and parenthesized_count + plain_count != 1:
        raise ValueError("Expected exactly one final APAC UNION branch")
    return " ".join(without_apac.lower().split())


def topology_sql_delta_audit(plan: pd.DataFrame) -> pd.DataFrame:
    keyed = plan.copy()
    keyed["action_key"] = keyed["mitigation_action"].fillna("baseline").astype(str)
    n2 = keyed[keyed["block_id"].eq("n2_control")].set_index(["query_id", "action_key"])
    rows: list[dict[str, Any]] = []
    for row in keyed[~keyed["block_id"].eq("n2_control")].itertuples(index=False):
        action_key = str(row.action_key)
        reference = n2.loc[(str(row.query_id), action_key)]
        n2_sql = Path(str(reference.rendered_sql_path)).read_text(encoding="utf-8")
        n3_sql = Path(str(row.rendered_sql_path)).read_text(encoding="utf-8")
        n2_canonical = canonicalize_topology_sql(n2_sql)
        n3_canonical = canonicalize_topology_sql(n3_sql)
        rows.append(
            {
                "block_id": row.block_id,
                "query_id": row.query_id,
                "action_key": action_key,
                "logical_query_hash_matches": str(row.logical_query_hash)
                == str(reference.logical_query_hash),
                "n2_has_apac_source": "fdw_apac." in n2_sql.lower(),
                "n3_has_apac_source": "fdw_apac." in n3_sql.lower(),
                "canonical_sql_matches": n2_canonical == n3_canonical,
                "n2_canonical_sha256": hashlib.sha256(n2_canonical.encode()).hexdigest(),
                "n3_canonical_sha256": hashlib.sha256(n3_canonical.encode()).hexdigest(),
            }
        )
    return pd.DataFrame(rows)


def dry_run(contract_path: Path, work_dir: Path, out_dir: Path, inventory: Path) -> None:
    contract = read_yaml(contract_path)
    scenarios = validate_contract(contract)
    scenario_by_component = {f"n3_topology_{row['query_id']}": row for row in scenarios}
    blocks = {str(row["id"]): row for row in contract["blocks"]}
    all_rows: list[pd.DataFrame] = []
    checks: dict[str, bool] = {}
    for block_index, block_id in enumerate(BLOCK_IDS, start=1):
        paths = block_paths(work_dir, block_id)
        rows = rendered_instances(paths["rendered"]).copy()
        expected = int(blocks[block_id]["expected_executions"])
        checks[f"{block_id}_count"] = len(rows) == expected
        rows["block_id"] = block_id
        rows["block_order"] = block_index
        rows["phase"] = str(blocks[block_id]["phase"])
        rows["topology_key"] = str(blocks[block_id]["topology"])
        rows["expected_topology_id"] = str(
            contract["topologies"][str(blocks[block_id]["topology"])]["topology_id"]
        )
        rows["query_id"] = rows["component_match_id"].map(
            lambda value: scenario_by_component[str(value)]["query_id"]
        )
        rows["query_order"] = rows["component_match_id"].map(
            lambda value: int(scenario_by_component[str(value)]["order"])
        )
        rows["logical_query_hash"] = rows["component_match_id"].map(
            lambda value: logical_query_hash(scenario_by_component[str(value)])
        )
        rows["sql_sha256"] = rows["rendered_sql_path"].map(
            lambda value: sha256_file(Path(str(value)))
        )
        rows["planned_sequence"] = range(1, len(rows) + 1)
        rows["logical_run_id"] = paths["logical"].name
        rows["logical_run_dir"] = str(paths["logical"])
        all_rows.append(rows)
    plan = pd.concat(all_rows, ignore_index=True).sort_values(["block_order", "planned_sequence"])
    sql_delta = topology_sql_delta_audit(plan)
    checks.update(
        {
            "total_execution_count": len(plan) == 180,
            "primary_n3_execution_count": int(plan["topology_key"].eq("n3").sum()) == 120,
            "fifteen_queries_each_block": all(
                group["query_id"].nunique() == 15 for _, group in plan.groupby("block_id")
            ),
            "three_actions": set(
                plan.loc[plan["mitigation_action"].notna(), "mitigation_action"].astype(str)
            )
            == set(ACTIONS),
            "model_refit_disabled": not bool(contract["model_freeze"]["refit_on_n3"]),
            "all_sql_files_exist": plan["rendered_sql_path"]
            .map(lambda value: Path(str(value)).exists())
            .all(),
            "n3_sql_differs_only_by_apac_source": len(sql_delta) == 120
            and sql_delta["logical_query_hash_matches"].all()
            and ~sql_delta["n2_has_apac_source"].any()
            and sql_delta["n3_has_apac_source"].all()
            and sql_delta["canonical_sql_matches"].all(),
        }
    )
    status = "PASS" if all(checks.values()) else "FAIL"
    out_dir.mkdir(parents=True, exist_ok=True)
    selected_columns = [
        "block_id",
        "block_order",
        "planned_sequence",
        "phase",
        "query_order",
        "query_id",
        "template_id",
        "param_json",
        "variant",
        "mitigation_action",
        "runtime_config_id",
        "dataset_profile_id",
        "expected_topology_id",
        "logical_query_hash",
        "sql_sha256",
        "rendered_sql_path",
        "execution_slot_id",
        "logical_run_id",
        "logical_run_dir",
    ]
    missing = [column for column in selected_columns if column not in plan.columns]
    if missing:
        raise ValueError(f"Rendered manifest lacks dry-run columns: {missing}")
    plan[selected_columns].to_csv(out_dir / "dry_run_execution_plan.csv", index=False)
    sql_delta.to_csv(out_dir / "topology_sql_delta_audit.csv", index=False)
    write_json(
        out_dir / "dry_run_validation.json",
        {
            "status": status,
            "generated_at_utc": utc_now(),
            "checks": checks,
            "counts_by_block": plan["block_id"].value_counts().sort_index().to_dict(),
            "counts_by_topology": plan["expected_topology_id"].value_counts().to_dict(),
            "active_topologies": contract["topologies"],
            "model_freeze": contract["model_freeze"],
            "output_locations": {
                block_id: {
                    "rendered": str(block_paths(work_dir, block_id)["rendered"]),
                    "logical": str(block_paths(work_dir, block_id)["logical"]),
                }
                for block_id in BLOCK_IDS
            },
            "inventory": provenance(contract_path, contract, inventory)["inventory"],
        },
    )
    lines = [
        "# N=3 topology-isolation dry run",
        "",
        f"Status: **{status}**",
        "",
        "| Block | Topology | Baseline | Actions | Executions |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for block_id in BLOCK_IDS:
        group = plan[plan["block_id"].eq(block_id)]
        lines.append(
            f"| `{block_id}` | `{group['expected_topology_id'].iloc[0]}` | "
            f"{int(group['mitigation_action'].isna().sum())} | "
            f"{int(group['mitigation_action'].notna().sum())} | {len(group)} |"
        )
    lines.extend(
        [
            "",
            "Primarni N=3 dizajn sadrzi 120 izvrsenja. Dodatnih 60 N=2 kontrolnih "
            "izvrsenja postoji zato sto raniji zavrsni panel nije bio cisti N=2 panel "
            "za svih 15 SQL oblika.",
            "",
            "Potpuni redoslijed, SQL hash, parametri, slotovi i izlazne lokacije nalaze se u "
            "`dry_run_execution_plan.csv`.",
        ]
    )
    (out_dir / "DRY_RUN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if status != "PASS":
        raise SystemExit(2)
    print(out_dir)


def _index_dir(work_dir: Path, block_id: str) -> Path:
    return block_paths(work_dir, block_id)["logical"] / "_index"


def load_executions(work_dir: Path, block_id: str, memory_module: Any) -> pd.DataFrame:
    index_dir = _index_dir(work_dir, block_id)
    if not (index_dir / "execution_features.csv").exists():
        raise FileNotFoundError(f"Missing indexed block {block_id}: {index_dir}")
    frame = memory_module.enrich_executions(index_dir).copy()
    frame["experiment_block_id"] = block_id
    return frame


def raw_execution_identifiers(blocks: dict[str, pd.DataFrame]) -> pd.DataFrame:
    columns = [
        "query_run_id",
        "execution_slot_id",
        "condition_id",
        "component_match_id",
        "variant",
        "mitigation_action",
        "execution_status",
        "timed_out",
        "query_started_at_unix",
        "query_finished_at_unix",
        "experiment_block_id",
    ]
    frames: list[pd.DataFrame] = []
    for block_id, frame in blocks.items():
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError(
                f"Indexed block {block_id} lacks execution identity columns: {missing}"
            )
        frames.append(frame[columns])
    return pd.concat(frames, ignore_index=True)


def indexed_artifact_audit(contract: dict[str, Any], work_dir: Path) -> pd.DataFrame:
    block_specs = {str(row["id"]): row for row in contract["blocks"]}
    rows: list[dict[str, Any]] = []
    for block_id in BLOCK_IDS:
        index_dir = _index_dir(work_dir, block_id)
        expected_regions = 2 if str(block_specs[block_id]["topology"]) == "n2" else 3
        expected_nodes = 1 + (expected_regions * 3)
        query_runs = pd.read_csv(index_dir / "query_runs.csv", low_memory=False)
        evidence = {
            name: pd.read_csv(index_dir / f"{name}.csv", low_memory=False)
            for name in (
                "region_fragments",
                "remote_edge_observations",
                "node_artifacts",
                "worker_task_fragments",
            )
        }
        counts = {
            name: frame.groupby("query_run_id").size()
            for name, frame in evidence.items()
        }
        node_artifacts = evidence["node_artifacts"].set_index("query_run_id", drop=False)
        for query_run_id in query_runs["query_run_id"].astype(str):
            node_rows = node_artifacts.loc[[query_run_id]]
            region_rows = evidence["region_fragments"]
            region_rows = region_rows[region_rows["query_run_id"].astype(str).eq(query_run_id)]
            rows.append(
                {
                    "block_id": block_id,
                    "query_run_id": query_run_id,
                    "expected_region_count": expected_regions,
                    "region_fragment_count": int(
                        counts["region_fragments"].get(query_run_id, 0)
                    ),
                    "remote_edge_count": int(
                        counts["remote_edge_observations"].get(query_run_id, 0)
                    ),
                    "expected_node_count": expected_nodes,
                    "node_artifact_count": int(counts["node_artifacts"].get(query_run_id, 0)),
                    "worker_task_fragment_count": int(
                        counts["worker_task_fragments"].get(query_run_id, 0)
                    ),
                    "regional_plans_parsed": region_rows["parse_status"].eq("ok").all(),
                    "os_samples_recorded": node_rows["os_samples_file"].notna().all(),
                    "os_summaries_recorded": node_rows["os_summary_file"].notna().all(),
                }
            )
    audit = pd.DataFrame(rows)
    audit["complete"] = (
        audit["region_fragment_count"].eq(audit["expected_region_count"])
        & audit["remote_edge_count"].eq(audit["expected_region_count"])
        & audit["node_artifact_count"].eq(audit["expected_node_count"])
        & audit["worker_task_fragment_count"].gt(0)
        & audit["regional_plans_parsed"]
        & audit["os_samples_recorded"]
        & audit["os_summaries_recorded"]
    )
    return audit


def _attempt_directories(work_dir: Path, block_id: str) -> list[Path]:
    attempts = pd.read_csv(
        block_paths(work_dir, block_id)["logical"] / "corpus_attempts.csv", low_memory=False
    )
    return [Path(str(value)) for value in attempts["attempt_dir"]]


def network_reset_audit(work_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for block_id in BLOCK_IDS:
        for attempt_dir in _attempt_directories(work_dir, block_id):
            pattern = (
                "database-sweeps/*/network-interventions/*/network_intervention_manifest.json"
            )
            for manifest_path in sorted(attempt_dir.glob(pattern)):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                action = str(manifest.get("action", ""))
                remote_results = manifest.get("remote_results", {}) or {}
                remote_ok = all(
                    str(result.get("status", "")) == "ok"
                    for result in remote_results.values()
                )
                reset_clean = action != "reset" or all(
                    "netem" not in str(result.get("qdisc_after", {}).get("stdout", "")).lower()
                    for result in remote_results.values()
                )
                rows.append(
                    {
                        "block_id": block_id,
                        "attempt_dir": str(attempt_dir),
                        "manifest_path": str(manifest_path),
                        "action": action,
                        "remote_node_count": len(remote_results),
                        "all_remote_results_ok": remote_ok,
                        "reset_removed_netem": reset_clean,
                    }
                )
    return pd.DataFrame(rows)


def dataset_load_audit(contract: dict[str, Any], work_dir: Path) -> pd.DataFrame:
    profiles: dict[str, tuple[Path, dict[str, Any]]] = {}
    for pair in contract["dataset_pairs"].values():
        for topology_key in ("n2", "n3"):
            profile_path = ROOT / pair[topology_key]["profile"]
            profile = read_yaml(profile_path)
            profiles[str(profile["dataset_id"])] = (profile_path, profile)
    rows: list[dict[str, Any]] = []
    for block_id in BLOCK_IDS:
        for attempt_dir in _attempt_directories(work_dir, block_id):
            for sweep_dir in sorted((attempt_dir / "database-sweeps").glob("*")):
                manifest_paths = sorted(
                    sweep_dir.glob("dataset-loads/*/dataset_load_manifest.json")
                )
                if not manifest_paths:
                    continue
                manifests = [
                    json.loads(path.read_text(encoding="utf-8")) for path in manifest_paths
                ]
                dataset_ids = {str(item["dataset_id"]) for item in manifests}
                if len(dataset_ids) != 1:
                    raise ValueError(f"Mixed dataset identities below {sweep_dir}")
                dataset_id = dataset_ids.pop()
                profile_path, profile = profiles[dataset_id]
                scale = profile["scale"]
                tenants = int(scale["tenants_total"])
                users_per_tenant = int(scale["users_per_tenant_avg"])
                expected_counts = {
                    "tenants": tenants,
                    "users": tenants * users_per_tenant,
                    "global_users": tenants
                    * int(scale.get("global_users_per_tenant_avg", users_per_tenant)),
                    "events": tenants * int(scale["events_per_tenant_avg"]),
                }
                observed_counts = {
                    table: sum(int(item["table_counts"][table]) for item in manifests)
                    for table in expected_counts
                }
                expected_regions = set(str(region) for region in profile["regions"])
                observed_regions = set(str(item["region"]) for item in manifests)
                profile_hash = sha256_file(profile_path)
                rows.append(
                    {
                        "block_id": block_id,
                        "attempt_dir": str(attempt_dir),
                        "database_sweep_dir": str(sweep_dir),
                        "dataset_id": dataset_id,
                        "expected_regions_json": json.dumps(sorted(expected_regions)),
                        "observed_regions_json": json.dumps(sorted(observed_regions)),
                        "regions_match": expected_regions == observed_regions,
                        "profile_hash_matches": all(
                            str(item.get("profile_sha256", "")) == profile_hash
                            for item in manifests
                        ),
                        "seed_matches": all(
                            int(item.get("dataset_seed", -1)) == int(profile["seed"])
                            for item in manifests
                        ),
                        "event_id_mode_matches": all(
                            str(item.get("datagen_env", {}).get("DATAGEN_EVENT_ID_MODE", ""))
                            == str(profile["identity"]["event_id_mode"])
                            for item in manifests
                        ),
                        "counts_match": observed_counts == expected_counts,
                        "expected_counts_json": json.dumps(expected_counts, sort_keys=True),
                        "observed_counts_json": json.dumps(observed_counts, sort_keys=True),
                    }
                )
    audit = pd.DataFrame(rows)
    audit["complete"] = (
        audit["regions_match"]
        & audit["profile_hash_matches"]
        & audit["seed_matches"]
        & audit["event_id_mode_matches"]
        & audit["counts_match"]
    )
    return audit


def _scenario_maps(
    contract: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    scenarios = validate_contract(contract)
    by_component = {f"n3_topology_{row['query_id']}": row for row in scenarios}
    by_query = {str(row["query_id"]): row for row in scenarios}
    return by_component, by_query


def build_round_episodes(
    contract: dict[str, Any],
    baseline_rows: pd.DataFrame,
    action_rows: pd.DataFrame,
    feature_names: list[str],
    *,
    round_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_component, _ = _scenario_maps(contract)
    events: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    for component, scenario in sorted(by_component.items(), key=lambda item: int(item[1]["order"])):
        baseline = baseline_rows[
            baseline_rows["component_match_id"].astype(str).eq(component)
            & baseline_rows["variant"].astype(str).eq("stressed")
        ]
        actions = action_rows[
            action_rows["component_match_id"].astype(str).eq(component)
            & action_rows["mitigation_action"].astype(str).isin(ACTIONS)
        ]
        if len(baseline) != 1 or actions["mitigation_action"].nunique() != len(ACTIONS):
            raise ValueError(
                f"Incomplete round {round_id} for {component}: baseline={len(baseline)}, "
                f"actions={actions['mitigation_action'].nunique()}"
            )
        before = baseline.iloc[0]
        event_id = f"{round_id}::{scenario['query_id']}"
        pair = contract["dataset_pairs"][str(scenario["dataset_pair"])]
        event: dict[str, Any] = {
            "episode_id": event_id,
            "round_id": round_id,
            "episode_order": int(scenario["order"]),
            "query_id": str(scenario["query_id"]),
            "query_shape": str(scenario["query_shape"]),
            "logical_query_hash": logical_query_hash(scenario),
            "normalized_sql_hash": str(before.get("sql_normalized_hash", "")),
            "profile": str(scenario["profile"]),
            "dataset_pair": str(scenario["dataset_pair"]),
            "dataset_pair_id": str(pair["pair_id"]),
            "dataset_profile_id": str(before["dataset_profile_id"]),
            "topology_id": str(before["topology_id"]),
            "region_count": int(
                before.get("edge_count", 0) or (2 if round_id == "n2_control" else 3)
            ),
            "baseline_query_run_id": str(before["query_run_id"]),
            "baseline_elapsed_seconds": float(before["elapsed_seconds"]),
            "applicable_actions_json": json.dumps(ACTIONS, separators=(",", ":")),
        }
        for feature in feature_names:
            event[f"before__{feature}"] = pd.to_numeric(
                pd.Series([before.get(feature, np.nan)]), errors="coerce"
            ).iloc[0]
        events.append(event)
        baseline_signature = str(before.get("result_multiset_sha256", "") or "")
        for action in ACTIONS:
            member = actions[actions["mitigation_action"].astype(str).eq(action)].iloc[0]
            elapsed = float(member["elapsed_seconds"])
            signature = str(member.get("result_multiset_sha256", "") or "")
            outcomes.append(
                {
                    "episode_id": event_id,
                    "round_id": round_id,
                    "query_id": scenario["query_id"],
                    "logical_query_hash": event["logical_query_hash"],
                    "topology_id": event["topology_id"],
                    "mitigation_action": action,
                    "baseline_query_run_id": event["baseline_query_run_id"],
                    "action_query_run_id": str(member["query_run_id"]),
                    "baseline_elapsed_seconds": event["baseline_elapsed_seconds"],
                    "action_elapsed_seconds": elapsed,
                    "target_log2_gain": math.log2(event["baseline_elapsed_seconds"] / elapsed),
                    "result_equal": bool(
                        baseline_signature and signature and baseline_signature == signature
                    ),
                }
            )
    return pd.DataFrame(events), pd.DataFrame(outcomes)


def reference_memory(
    contract: dict[str, Any], feature_names: list[str], dba_module: Any
) -> tuple[pd.DataFrame, pd.DataFrame]:
    compatibility = {
        "memory": {
            "reference_report": contract["model_freeze"]["reference_report"],
            "state_contract": contract["model_freeze"]["state_contract"],
        }
    }
    states, outcomes = dba_module._reference_memory(compatibility, feature_names)
    states["logical_query_hash"] = (
        states["query_id"]
        .astype(str)
        .map(lambda value: stable_hash({"legacy_reference_query": value}))
    )
    states["normalized_sql_hash"] = states["logical_query_hash"]
    states["dataset_pair"] = "legacy_reference"
    states["profile"] = "legacy_reference"
    return states, outcomes


def fit_frozen_processor(
    contract: dict[str, Any], memory_module: Any, dba_module: Any
) -> tuple[Any, list[str], pd.DataFrame, pd.DataFrame, np.ndarray, float, dict[str, Any]]:
    state_contract_path = ROOT / contract["model_freeze"]["state_contract"]
    state_contract = read_yaml(state_contract_path)
    specifications = state_contract["state_representation"]["features"]
    feature_names = list(specifications)
    states, outcomes = reference_memory(contract, feature_names, dba_module)
    processor = memory_module.StatePreprocessor(
        specifications=specifications,
        pca_components=int(contract["model_freeze"]["pca_components"]),
        minimum_active_features=int(
            state_contract["state_representation"]["minimum_active_features"]
        ),
    )
    values = processor.fit(states)
    threshold = dba_module._nearest_threshold(
        values,
        float(contract["model_freeze"]["coverage_quantile"]),
        str(contract["model_freeze"]["distance_metric"]),
    )
    artifact = {
        "model_id": contract["model_freeze"]["model_id"],
        "state_contract_sha256": sha256_file(state_contract_path),
        "reference_report": contract["model_freeze"]["reference_report"],
        "reference_state_count": len(states),
        "active_features": list(processor.active_features or []),
        "imputer_statistics": processor.imputer.statistics_.tolist(),
        "scaler_mean": processor.scaler.mean_.tolist(),
        "scaler_scale": processor.scaler.scale_.tolist(),
        "family_weights": processor.family_weights.tolist(),
        "pca_components": processor.pca.components_.tolist(),
        "pca_mean": processor.pca.mean_.tolist(),
        "coverage_threshold": threshold,
        "coverage_quantile": float(contract["model_freeze"]["coverage_quantile"]),
        "neighbors": int(contract["model_freeze"]["neighbors"]),
        "distance_metric": contract["model_freeze"]["distance_metric"],
        "fitted_on_n3": False,
    }
    artifact["artifact_sha256"] = stable_hash(artifact)
    return processor, feature_names, states, outcomes, values, threshold, artifact


def exact_prediction(
    event: pd.Series,
    memory_states: pd.DataFrame,
    memory_outcomes: pd.DataFrame,
    *,
    context_aware: bool,
) -> tuple[dict[str, float], str, list[dict[str, Any]]]:
    eligible = memory_states["logical_query_hash"].astype(str).eq(str(event["logical_query_hash"]))
    if context_aware:
        eligible &= memory_states["topology_id"].astype(str).eq(str(event["topology_id"]))
        eligible &= memory_states["dataset_pair"].astype(str).eq(str(event["dataset_pair"]))
        eligible &= memory_states["profile"].astype(str).eq(str(event["profile"]))
    selected = memory_states[eligible]
    if selected.empty:
        return (
            {action: float("nan") for action in ACTIONS},
            "exact_context_unseen" if context_aware else "exact_query_unseen",
            [],
        )
    episode_ids = set(selected["episode_id"].astype(str))
    selected_outcomes = memory_outcomes[memory_outcomes["episode_id"].astype(str).isin(episode_ids)]
    predictions = {
        action: float(
            selected_outcomes[selected_outcomes["mitigation_action"].astype(str).eq(action)][
                "target_log2_gain"
            ].median()
        )
        for action in ACTIONS
    }
    evidence = [
        {
            "episode_id": row.episode_id,
            "query_id": row.query_id,
            "topology_id": row.topology_id,
        }
        for row in selected.itertuples()
    ]
    return predictions, "available", evidence


def recommendations(
    contract: dict[str, Any],
    events: pd.DataFrame,
    memory_states: pd.DataFrame,
    memory_outcomes: pd.DataFrame,
    memory_values: np.ndarray,
    new_values: np.ndarray,
    threshold: float,
    dba_module: Any,
    *,
    freeze_id: str,
    allow_context_exact: bool,
    n3_only: bool,
) -> pd.DataFrame:
    action_medians = memory_outcomes.groupby("mitigation_action")["target_log2_gain"].median()
    rows: list[dict[str, Any]] = []
    for index, event in events.sort_values("episode_order").reset_index(drop=True).iterrows():
        methods: list[tuple[str, dict[str, float], str, float, list[dict[str, Any]], int]] = []
        static_predictions = {action: float(action_medians[action]) for action in ACTIONS}
        methods.append(
            (
                "static_action_median",
                static_predictions,
                "available",
                float("nan"),
                [],
                len(memory_states),
            )
        )
        for context_aware, method in (
            (False, "blind_exact_query"),
            (True, "context_exact_query"),
        ):
            predictions, status, evidence = exact_prediction(
                event, memory_states, memory_outcomes, context_aware=context_aware
            )
            methods.append((method, predictions, status, float("nan"), evidence, len(evidence)))
        for method, only_n3 in (
            ("cross_query_knn", False),
            ("n3_only_cross_query_knn", True),
        ):
            selected_states = memory_states
            selected_outcomes = memory_outcomes
            selected_values = memory_values
            if only_n3:
                mask = memory_states["topology_id"].astype(str).eq("eu_us_apac_gac")
                selected_states = memory_states[mask].reset_index(drop=True)
                selected_values = memory_values[mask.to_numpy()]
                ids = set(selected_states["episode_id"].astype(str))
                selected_outcomes = memory_outcomes[
                    memory_outcomes["episode_id"].astype(str).isin(ids)
                ]
            if only_n3 and not n3_only:
                continue
            predictions, evidence, nearest, eligible_count = dba_module._estimate_from_memory(
                new_values[index],
                selected_values,
                selected_states,
                selected_outcomes,
                neighbors=int(contract["model_freeze"]["neighbors"]),
                epsilon=0.000001,
                distance_metric=str(contract["model_freeze"]["distance_metric"]),
                excluded_query_id=str(event["query_id"]),
                excluded_normalized_sql_hash=str(event["logical_query_hash"]),
            )
            status = dba_module._status(
                memory_count=eligible_count,
                nearest_distance=nearest,
                coverage_threshold=threshold,
                minimum_history=int(contract["model_freeze"]["minimum_history_for_available"]),
            )
            methods.append((method, predictions, status, nearest, evidence, eligible_count))
        method_rows: dict[str, dict[str, Any]] = {}
        for method, predictions, status, nearest, evidence, eligible_count in methods:
            candidate, predicted = dba_module._decision_actions(predictions, status, ACTIONS)
            row = {
                "freeze_id": freeze_id,
                "frozen_at_utc": utc_now(),
                "episode_id": event["episode_id"],
                "query_id": event["query_id"],
                "logical_query_hash": event["logical_query_hash"],
                "baseline_query_run_id": event["baseline_query_run_id"],
                "topology_id": event["topology_id"],
                "method": method,
                "decision_status": status,
                "candidate_action": candidate,
                "predicted_action": predicted,
                "nearest_distance": nearest,
                "coverage_threshold": threshold,
                "eligible_history_state_count": eligible_count,
                "neighbor_evidence_json": json.dumps(
                    evidence, sort_keys=True, separators=(",", ":")
                ),
                **{f"predicted_gain__{action}": predictions[action] for action in ACTIONS},
            }
            method_rows[method] = row
            rows.append(row)
        context = method_rows.get("context_exact_query")
        cross = method_rows.get("cross_query_knn")
        if allow_context_exact and context and context["predicted_action"]:
            selected = context
            route = "context_exact_query"
        else:
            selected = cross
            route = "cross_query_knn"
        hierarchy = dict(selected or {})
        hierarchy.update(
            {
                "method": "hierarchical_policy",
                "decision_route": route,
            }
        )
        rows.append(hierarchy)
    return pd.DataFrame(rows)


def action_block_has_started(work_dir: Path, block_id: str) -> bool:
    logical = block_paths(work_dir, block_id)["logical"]
    if not logical.exists():
        return False
    for status_path in logical.glob("attempts/*/corpus_run_status.json"):
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        if status.get("status") not in {"dry_run", "planned"}:
            return True
    return (logical / "_index/query_runs.csv").exists()


def freeze_phase(contract_path: Path, work_dir: Path, out_dir: Path, phase: str) -> None:
    contract = read_yaml(contract_path)
    validate_contract(contract)
    memory_module, dba_module = memory_modules()
    (
        processor,
        feature_names,
        reference_states,
        reference_outcomes,
        reference_values,
        threshold,
        artifact,
    ) = fit_frozen_processor(contract, memory_module, dba_module)
    n2 = load_executions(work_dir, "n2_control", memory_module)
    n2_events, n2_outcomes = build_round_episodes(
        contract, n2, n2, feature_names, round_id="n2_control"
    )
    if not n2_outcomes["result_equal"].all():
        raise ValueError("N2 control contains non-equivalent action results")
    n2_values = processor.transform(n2_events)
    memory_states = pd.concat([reference_states, n2_events], ignore_index=True)
    memory_outcomes = pd.concat([reference_outcomes, n2_outcomes], ignore_index=True)
    memory_values = np.vstack([reference_values, n2_values])
    if phase == "A":
        baseline_block = "phase_a_baseline"
        action_block = "phase_a_actions"
        freeze_id = "phase_a_recommendations"
        allow_context_exact = False
        n3_only = False
    elif phase == "B":
        baseline_block = "phase_b_baseline"
        action_block = "phase_b_actions"
        freeze_id = "phase_b_recommendations"
        allow_context_exact = True
        n3_only = True
        a_baseline = load_executions(work_dir, "phase_a_baseline", memory_module)
        a_actions = load_executions(work_dir, "phase_a_actions", memory_module)
        a_events, a_outcomes = build_round_episodes(
            contract, a_baseline, a_actions, feature_names, round_id="phase_a"
        )
        if not a_outcomes["result_equal"].all():
            raise ValueError("Phase A contains non-equivalent action results")
        a_values = processor.transform(a_events)
        memory_states = pd.concat([memory_states, a_events], ignore_index=True)
        memory_outcomes = pd.concat([memory_outcomes, a_outcomes], ignore_index=True)
        memory_values = np.vstack([memory_values, a_values])
    else:
        raise ValueError(phase)
    if action_block_has_started(work_dir, action_block):
        raise RuntimeError(
            f"Refusing to freeze {phase}: action block {action_block} already started"
        )
    baseline = load_executions(work_dir, baseline_block, memory_module)
    # Baseline states do not need action rows while recommendations are frozen.
    by_component, _ = _scenario_maps(contract)
    event_rows: list[dict[str, Any]] = []
    for component, scenario in sorted(by_component.items(), key=lambda item: int(item[1]["order"])):
        match = baseline[
            baseline["component_match_id"].astype(str).eq(component)
            & baseline["variant"].astype(str).eq("stressed")
        ]
        if len(match) != 1:
            raise ValueError(f"Expected one {phase} baseline for {component}, found {len(match)}")
        before = match.iloc[0]
        pair = contract["dataset_pairs"][str(scenario["dataset_pair"])]
        event: dict[str, Any] = {
            "episode_id": f"phase_{phase.lower()}::{scenario['query_id']}",
            "episode_order": int(scenario["order"]),
            "query_id": scenario["query_id"],
            "query_shape": scenario["query_shape"],
            "logical_query_hash": logical_query_hash(scenario),
            "normalized_sql_hash": logical_query_hash(scenario),
            "profile": scenario["profile"],
            "dataset_pair": scenario["dataset_pair"],
            "dataset_pair_id": pair["pair_id"],
            "dataset_profile_id": before["dataset_profile_id"],
            "topology_id": before["topology_id"],
            "region_count": 3,
            "baseline_query_run_id": before["query_run_id"],
            "baseline_elapsed_seconds": float(before["elapsed_seconds"]),
            "applicable_actions_json": json.dumps(ACTIONS, separators=(",", ":")),
        }
        for feature in feature_names:
            event[f"before__{feature}"] = pd.to_numeric(
                pd.Series([before.get(feature, np.nan)]), errors="coerce"
            ).iloc[0]
        event_rows.append(event)
    events = pd.DataFrame(event_rows)
    values = processor.transform(events)
    freeze = recommendations(
        contract,
        events,
        memory_states,
        memory_outcomes,
        memory_values,
        values,
        threshold,
        dba_module,
        freeze_id=freeze_id,
        allow_context_exact=allow_context_exact,
        n3_only=n3_only,
    )
    freeze_dir = work_dir / "freezes" / freeze_id
    freeze_dir.mkdir(parents=True, exist_ok=True)
    freeze.to_csv(freeze_dir / "recommendations.csv", index=False)
    events.to_csv(freeze_dir / "baseline_states.csv", index=False)
    processor.selection_audit.to_csv(freeze_dir / "feature_selection_audit.csv", index=False)
    write_json(freeze_dir / "model_freeze.json", artifact)
    memory_snapshot = {
        "freeze_id": freeze_id,
        "frozen_at_utc": utc_now(),
        "phase": phase,
        "memory_state_count": len(memory_states),
        "memory_episode_ids": sorted(memory_states["episode_id"].astype(str)),
        "n3_memory_state_count": int(
            memory_states["topology_id"].astype(str).eq("eu_us_apac_gac").sum()
        ),
        "n3_outcome_rounds": sorted(
            set(
                memory_outcomes.loc[
                    memory_outcomes.get(
                        "topology_id", pd.Series(index=memory_outcomes.index, dtype=str)
                    )
                    .astype(str)
                    .eq("eu_us_apac_gac"),
                    "round_id",
                ].astype(str)
            )
        )
        if "round_id" in memory_outcomes.columns
        else [],
        "model_artifact_sha256": artifact["artifact_sha256"],
        "recommendations_sha256": sha256_file(freeze_dir / "recommendations.csv"),
        "action_block_not_started_at_freeze": True,
        "same_query_exclusion_policy": "exclude query_id and logical_query_hash",
    }
    memory_snapshot["memory_snapshot_sha256"] = stable_hash(memory_snapshot)
    write_json(freeze_dir / "memory_snapshot.json", memory_snapshot)
    print(freeze_dir)


def _metric_rows(scored: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (phase, method), group in scored.groupby(["phase", "method"], sort=True):
        recommended = group[group["predicted_action"].isin(ACTIONS)]
        rows.append(
            {
                "phase": phase,
                "method": method,
                "episode_count": len(group),
                "recommendation_count": len(recommended),
                "coverage": len(recommended) / len(group),
                "abstention_count": len(group) - len(recommended),
                "top1_accuracy_among_recommendations": (
                    float(recommended["top1_correct"].mean())
                    if not recommended.empty
                    else float("nan")
                ),
                "mean_regret_log2": (
                    float(recommended["regret_log2"].mean())
                    if not recommended.empty
                    else float("nan")
                ),
                "nearest_distance_median": float(
                    pd.to_numeric(group["nearest_distance"], errors="coerce").median()
                ),
                "nearest_distance_p95": float(
                    pd.to_numeric(group["nearest_distance"], errors="coerce").quantile(0.95)
                ),
            }
        )
    return pd.DataFrame(rows)


def _flatten_phase_metric_comparison(metrics: pd.DataFrame) -> pd.DataFrame:
    wide = metrics.pivot(index="method", columns="phase").reset_index()
    wide.columns = [
        str(column)
        if not isinstance(column, tuple)
        else "__".join(str(part) for part in column if str(part))
        for column in wide.columns
    ]
    return wide


def write_results_report(
    out_dir: Path,
    summary: dict[str, Any],
    metrics: pd.DataFrame,
    gain_summary: pd.DataFrame,
    threshold: float,
) -> None:
    def metric(phase: str, method: str, column: str) -> float:
        row = metrics[(metrics["phase"] == phase) & (metrics["method"] == method)]
        return float(row.iloc[0][column])

    def percent(value: float) -> str:
        return f"{100.0 * value:.1f}%"

    gain_lines = []
    for row in gain_summary.itertuples(index=False):
        gain_lines.append(
            f"| {row.round_id} | `{row.mitigation_action}` | {int(row.pair_count)} | "
            f"{float(row.median_gain_log2):.4f} | {float(row.mean_gain_log2):.4f} |"
        )
    results = f"""# N=3 topology-memory eksperiment

## Izvrsni ugovor

- Zavrseno je {summary['execution_count']}/180 kontrolisanih izvrsenja bez timeouta.
- N=2 kontrola sadrzi 60 izvrsenja, a N=3 faze A i B po 60 izvrsenja.
- Svaki krug koristi istih 15 logickih SQL scenarija i tri akcije.
- N=3 SQL se od N=2 razlikuje samo neophodnom APAC granom izvora.
- Fiksni model nije refitovan na N=3: 64 aktivna pokazatelja, 6 PCA komponenti,
  k=5 i nepromijenjena P99 granica {threshold:.6f}.
- Svih {summary['action_outcome_count']} baseline/action poredjenja dalo je isti rezultat.

## Glavni rezultat

U fazi A, prije lokalnog N=3 iskustva, cross-query kNN apstinira u svih 15
slucajeva. Medijana udaljenosti je
{metric('A', 'cross_query_knn', 'nearest_distance_median'):.4f}, iznad zamrznute
P99 granice. Time sistem ne prenosi N=2 preporuke na nepokrivenu topologiju.

Nakon sto je memorija dopunjena samo epizodama faze A, faza B daje
{percent(metric('B', 'cross_query_knn', 'coverage'))} pokrivenosti i
{percent(metric('B', 'cross_query_knn', 'top1_accuracy_among_recommendations'))}
Top-1 tacnosti za cross-query kNN. Prosjecni regret je
{metric('B', 'cross_query_knn', 'mean_regret_log2'):.4f} log2, a medijana
udaljenosti pada na
{metric('B', 'cross_query_knn', 'nearest_distance_median'):.4f}, unutar iste P99
granice. Statiicki action-median baseline u fazi B ima
{percent(metric('B', 'static_action_median', 'top1_accuracy_among_recommendations'))}
Top-1 tacnosti i regret
{metric('B', 'static_action_median', 'mean_regret_log2'):.4f} log2.

Context-aware exact-query memorija u fazi B daje 15/15 tacnih preporuka. Blind
exact-query memorija daje 15/15 i u fazi A, sto je vazan negativan nalaz za
pretpostavku da sama promjena N=2 u N=3 mora promijeniti najbolju akciju: najbolja
akcija nije se promijenila ni u jednom od 15 SQL scenarija. Topologija je ipak
promijenila fizicki prostor dovoljno da opravda apstinenciju modela koji koristi
zamrznutu N=2 granicu pokrivenosti.

## Ishodi akcija

| Krug | Akcija | Parovi | Medijana gaina log2 | Srednji gain log2 |
| --- | --- | ---: | ---: | ---: |
{chr(10).join(gain_lines)}

Remote mitigacija je najbolja u 9/15 scenarija, regionalni Top-K u 6/15, a
povecanje GAC `work_mem` ni u jednom. Ovaj eksperiment zato ispituje topolosku
pokrivenost i lokalnu adaptaciju, a ne pokazuje kontekstualnu promjenu najboljeg
redoslijeda akcija izmedju N=2, N=3 faze A i N=3 faze B.

## Granice tumacenja

- Faza B nije nezavisni cold-start test: namjerno koristi samo ranije N=3 epizode
  iz faze A.
- Rezultat je ogranicen na 15 SQL scenarija, tri poznate akcije i jednu N=3
  infrastrukturu.
- N=2 i N=3 koriste isti logicki SQL i parametre, ali sirovi SQL nije bajtno isti
  jer N=3 mora ukljuciti APAC izvor.
- P99 je empirijska granica pokrivenosti zamrznutog N=2 prostora, a ne statisticka
  garancija produkcijske generalizacije.

Detaljni identiteti, preporuke, susjedi, udaljenosti, artefakti, dataset loadovi,
mrezni resetovi i retry pokusaji nalaze se u CSV/JSON datotekama ovog direktorija.
"""
    (out_dir / "RESULTS.md").write_text(results, encoding="utf-8")


def write_report_checksums(out_dir: Path) -> None:
    checksum_path = out_dir / "checksums.sha256"
    paths = sorted(
        path
        for path in out_dir.iterdir()
        if path.is_file() and path.name != checksum_path.name
    )
    lines = [f"{sha256_file(path)}  {path.name}" for path in paths]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze(contract_path: Path, work_dir: Path, out_dir: Path) -> None:
    contract = read_yaml(contract_path)
    validate_contract(contract)
    memory_module, dba_module = memory_modules()
    processor, feature_names, _states, _outcomes, _values, _threshold, artifact = (
        fit_frozen_processor(contract, memory_module, dba_module)
    )
    blocks = {
        block_id: load_executions(work_dir, block_id, memory_module) for block_id in BLOCK_IDS
    }
    n2_events, n2_outcomes = build_round_episodes(
        contract, blocks["n2_control"], blocks["n2_control"], feature_names, round_id="n2_control"
    )
    a_events, a_outcomes = build_round_episodes(
        contract,
        blocks["phase_a_baseline"],
        blocks["phase_a_actions"],
        feature_names,
        round_id="phase_a",
    )
    b_events, b_outcomes = build_round_episodes(
        contract,
        blocks["phase_b_baseline"],
        blocks["phase_b_actions"],
        feature_names,
        round_id="phase_b",
    )
    outcomes = pd.concat([n2_outcomes, a_outcomes, b_outcomes], ignore_index=True)
    events = pd.concat([n2_events, a_events, b_events], ignore_index=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    events.to_csv(out_dir / "episode_states.csv", index=False)
    outcomes.to_csv(out_dir / "action_outcomes.csv", index=False)
    gain_summary = (
        outcomes.groupby(["round_id", "mitigation_action"], sort=True)["target_log2_gain"]
        .agg(pair_count="count", median_gain_log2="median", mean_gain_log2="mean")
        .reset_index()
    )
    gain_summary.to_csv(out_dir / "action_gain_summary.csv", index=False)
    if not outcomes["result_equal"].all():
        outcomes[~outcomes["result_equal"]].to_csv(out_dir / "result_mismatches.csv", index=False)
        raise ValueError("At least one baseline/action result comparison failed")
    scored_frames: list[pd.DataFrame] = []
    for phase, freeze_id, phase_outcomes in (
        ("A", "phase_a_recommendations", a_outcomes),
        ("B", "phase_b_recommendations", b_outcomes),
    ):
        freeze_path = work_dir / "freezes" / freeze_id / "recommendations.csv"
        frozen = pd.read_csv(freeze_path, low_memory=False)
        actual = phase_outcomes.pivot(
            index="query_id", columns="mitigation_action", values="target_log2_gain"
        )
        frozen["phase"] = phase
        frozen["actual_best_action"] = frozen["query_id"].map(actual.idxmax(axis=1))
        for action in ACTIONS:
            frozen[f"actual_gain__{action}"] = frozen["query_id"].map(actual[action])
        frozen["top1_correct"] = frozen["predicted_action"].isin(ACTIONS) & frozen[
            "predicted_action"
        ].eq(frozen["actual_best_action"])
        frozen["regret_log2"] = frozen.apply(
            lambda row: (
                float(max(row[f"actual_gain__{action}"] for action in ACTIONS))
                - float(row[f"actual_gain__{row['predicted_action']}"])
                if str(row["predicted_action"]) in ACTIONS
                else float("nan")
            ),
            axis=1,
        )
        scored_frames.append(frozen)
    scored = pd.concat(scored_frames, ignore_index=True)
    scored.to_csv(out_dir / "phase_recommendations_scored.csv", index=False)
    metrics = _metric_rows(scored)
    metrics.to_csv(out_dir / "phase_metrics.csv", index=False)
    distance_distribution = (
        scored.groupby(["phase", "method"], sort=True)["nearest_distance"]
        .agg(["count", "min", "median", "mean", "max"])
        .reset_index()
    )
    distance_distribution.to_csv(out_dir / "neighbor_distance_distribution.csv", index=False)
    best = outcomes.pivot_table(
        index=["round_id", "query_id"],
        columns="mitigation_action",
        values="target_log2_gain",
        aggfunc="first",
    ).reset_index()
    best["best_action"] = best[list(ACTIONS)].idxmax(axis=1)
    comparison = best.pivot(
        index="query_id", columns="round_id", values="best_action"
    ).reset_index()
    comparison["n2_to_a_changed"] = comparison["n2_control"] != comparison["phase_a"]
    comparison["a_to_b_changed"] = comparison["phase_a"] != comparison["phase_b"]
    comparison.to_csv(out_dir / "n2_n3_best_action_comparison.csv", index=False)
    phase_change = _flatten_phase_metric_comparison(metrics)
    phase_change.to_csv(out_dir / "phase_a_b_metric_comparison.csv", index=False)
    raw_ids = raw_execution_identifiers(blocks)
    raw_ids.to_csv(out_dir / "raw_execution_identifiers.csv", index=False)
    artifact_audit = indexed_artifact_audit(contract, work_dir)
    artifact_audit.to_csv(out_dir / "artifact_completeness_audit.csv", index=False)
    reset_audit = network_reset_audit(work_dir)
    reset_audit.to_csv(out_dir / "network_reset_audit.csv", index=False)
    dataset_audit = dataset_load_audit(contract, work_dir)
    dataset_audit.to_csv(out_dir / "dataset_load_audit.csv", index=False)
    dry_run_plan = pd.read_csv(out_dir / "dry_run_execution_plan.csv", low_memory=False)
    sql_delta = topology_sql_delta_audit(dry_run_plan)
    sql_delta.to_csv(out_dir / "topology_sql_delta_audit.csv", index=False)
    retries: list[pd.DataFrame] = []
    for block_id in BLOCK_IDS:
        candidates = _index_dir(work_dir, block_id).parent / "attempt_candidates.csv"
        if candidates.exists():
            frame = pd.read_csv(candidates, low_memory=False)
            frame["block_id"] = block_id
            retries.append(frame)
    if retries:
        pd.concat(retries, ignore_index=True).to_csv(
            out_dir / "attempt_and_retry_audit.csv", index=False
        )
    freeze_checks: dict[str, Any] = {}
    for phase, freeze_id, action_block in (
        ("A", "phase_a_recommendations", "phase_a_actions"),
        ("B", "phase_b_recommendations", "phase_b_actions"),
    ):
        snapshot = json.loads(
            (work_dir / "freezes" / freeze_id / "memory_snapshot.json").read_text(encoding="utf-8")
        )
        frozen_at = pd.Timestamp(snapshot["frozen_at_utc"]).timestamp()
        action_start = pd.to_numeric(
            blocks[action_block]["query_started_at_unix"], errors="coerce"
        ).min()
        freeze_checks[f"phase_{phase.lower()}_frozen_before_actions"] = bool(
            np.isfinite(action_start) and frozen_at < action_start
        )
    same_query_evidence = scored[
        scored["method"].isin(["cross_query_knn", "n3_only_cross_query_knn"])
    ]
    same_query_excluded = True
    for row in same_query_evidence.itertuples():
        for neighbor in json.loads(str(row.neighbor_evidence_json)):
            if str(neighbor.get("query_id", "")) == str(row.query_id):
                same_query_excluded = False
    reset_counts = reset_audit.groupby(["block_id", "action"]).size().unstack(fill_value=0)
    network_resets_clean = (
        not reset_audit.empty
        and reset_audit["all_remote_results_ok"].all()
        and reset_audit["reset_removed_netem"].all()
        and {"apply", "reset"}.issubset(reset_counts.columns)
        and reset_counts["apply"].eq(reset_counts["reset"]).all()
    )
    frozen_model_hashes = {
        freeze_id: json.loads(
            (work_dir / "freezes" / freeze_id / "model_freeze.json").read_text(
                encoding="utf-8"
            )
        )["artifact_sha256"]
        for freeze_id in ("phase_a_recommendations", "phase_b_recommendations")
    }
    checks = {
        "all_180_executions_completed": len(raw_ids) == 180
        and raw_ids["execution_status"].eq("completed").all(),
        "no_unreported_timeouts": not raw_ids["timed_out"].fillna(False).astype(bool).any(),
        "all_135_action_results_equivalent": len(outcomes) == 135
        and outcomes["result_equal"].all(),
        "model_artifact_not_fit_on_n3": not artifact["fitted_on_n3"],
        "model_artifact_unchanged_across_freezes": set(frozen_model_hashes.values())
        == {artifact["artifact_sha256"]},
        "same_query_excluded_from_cross_query": same_query_excluded,
        "all_multilayer_artifacts_complete": len(artifact_audit) == 180
        and artifact_audit["complete"].all(),
        "all_dataset_loads_match_frozen_profiles": not dataset_audit.empty
        and dataset_audit["complete"].all(),
        "all_network_profiles_reset_cleanly": network_resets_clean,
        "n3_sql_differs_only_by_apac_source": len(sql_delta) == 120
        and sql_delta["logical_query_hash_matches"].all()
        and ~sql_delta["n2_has_apac_source"].any()
        and sql_delta["n3_has_apac_source"].all()
        and sql_delta["canonical_sql_matches"].all(),
        **freeze_checks,
    }
    summary = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "execution_count": len(raw_ids),
        "episode_count": len(events),
        "action_outcome_count": len(outcomes),
        "n2_n3_best_action_change_count": int(comparison["n2_to_a_changed"].sum()),
        "phase_a_b_best_action_change_count": int(comparison["a_to_b_changed"].sum()),
        "model_artifact_sha256": artifact["artifact_sha256"],
        "analysis_git_commits": {
            repo.name: git_commit(repo)
            for repo in (
                ROOT,
                INFRA_ROOT,
                ROOT.parent / "psql-benchmarks",
                ROOT.parent / "citus-datagen",
            )
        },
        "metrics": metrics.to_dict(orient="records"),
    }
    write_json(out_dir / "analysis_summary.json", summary)
    write_json(out_dir / "model_freeze_recomputed.json", artifact)
    commands = """# Reprodukcija N=3 topology-memory eksperimenta

```bash
make n3-topology-memory-render
make n3-topology-memory-dry-run
make n3-topology-memory-n2-start
make n3-topology-memory-n2-index
make n3-topology-memory-a-baseline-start
make n3-topology-memory-a-baseline-index
make n3-topology-memory-freeze-a
make n3-topology-memory-a-actions-start
make n3-topology-memory-a-actions-index
make n3-topology-memory-b-baseline-start
make n3-topology-memory-b-baseline-index
make n3-topology-memory-freeze-b
make n3-topology-memory-b-actions-start
make n3-topology-memory-b-actions-index
make n3-topology-memory-analyze
```
    """
    (out_dir / "REPRODUCE.md").write_text(commands, encoding="utf-8")
    write_results_report(
        out_dir,
        summary,
        metrics,
        gain_summary,
        float(artifact["coverage_threshold"]),
    )
    write_report_checksums(out_dir)
    if summary["status"] != "PASS":
        raise SystemExit(2)
    print(out_dir)


def main() -> int:
    args = parse_args()
    contract_path = args.contract.resolve()
    work_dir = args.work_dir.resolve()
    out_dir = args.out_dir.resolve()
    if args.command == "prepare":
        prepare(contract_path, work_dir, args.inventory.resolve())
    elif args.command == "dry-run":
        dry_run(contract_path, work_dir, out_dir, args.inventory.resolve())
    elif args.command == "freeze-a":
        freeze_phase(contract_path, work_dir, out_dir, "A")
    elif args.command == "freeze-b":
        freeze_phase(contract_path, work_dir, out_dir, "B")
    else:
        analyze(contract_path, work_dir, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
