#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT.parent
DEFAULT_OUT = ROOT / "releases/pressure-actionability-v1"

SOURCE_FILES = {
    "contracts/pressure_raw_collection_v1.yml": (
        ROOT / "configs/collection/pressure_raw_collection_v1.yml"
    ),
    "contracts/mitigation_action_audit_v1.yml": (
        ROOT / "configs/validation/mitigation_action_audit_v1.yml"
    ),
    "contracts/mitigation_correctness_recovery_v1.yml": (
        ROOT / "configs/validation/mitigation_correctness_recovery_v1.yml"
    ),
    "contracts/colocation_gain_v1.yml": ROOT / "configs/models/colocation_gain_v1.yml",
    "contracts/colocation_ranking_v1.yml": (
        ROOT / "configs/models/colocation_ranking_v1.yml"
    ),
    "corpus/consolidation_manifest.json": (
        ROOT
        / "generated/pressure-raw-runs/_program/pressure-raw-v1/"
        "consolidation_manifest.json"
    ),
    "corpus/pressure_raw_program.yml": (
        ROOT / "generated/corpus/pressure-raw-v1/pressure_raw_program.yml"
    ),
    "correctness/correctness_recovery_summary.json": (
        ROOT
        / "analysis/reports/pressure-raw-v1-correctness-recovery/"
        "correctness_recovery_summary.json"
    ),
    "correctness/correctness_recovery_by_action.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-correctness-recovery/"
        "correctness_recovery_by_action.csv"
    ),
    "correctness/correctness_recovery_results.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-correctness-recovery/"
        "correctness_recovery_results.csv"
    ),
    "action_audit/README.md": (
        ROOT / "analysis/reports/pressure-raw-v1-mitigation-action-audit/README.md"
    ),
    "action_audit/summary.json": (
        ROOT / "analysis/reports/pressure-raw-v1-mitigation-action-audit/summary.json"
    ),
    "action_audit/mitigation_action_summary.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-mitigation-action-audit/"
        "mitigation_action_summary.csv"
    ),
    "action_audit/mitigation_policy_summary.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-mitigation-action-audit/"
        "mitigation_policy_summary.csv"
    ),
    "action_audit/mitigation_pair_audit.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-mitigation-action-audit/"
        "mitigation_pair_audit.csv"
    ),
    "action_audit/holdout_feasibility.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-mitigation-action-audit/"
        "holdout_feasibility.csv"
    ),
    "action_audit/mitigation_gain_by_action.png": (
        ROOT
        / "analysis/reports/pressure-raw-v1-mitigation-action-audit/"
        "mitigation_gain_by_action.png"
    ),
    "colocation_model/README.md": (
        ROOT / "analysis/reports/pressure-raw-v1-colocation-gain-model/README.md"
    ),
    "colocation_model/model_manifest.json": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-gain-model/model_manifest.json"
    ),
    "colocation_model/colocation_gain_model.joblib": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-gain-model/"
        "colocation_gain_model.joblib"
    ),
    "colocation_model/colocation_pair_matrix.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-gain-model/"
        "colocation_pair_matrix.csv"
    ),
    "colocation_model/cross_validation_summary.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-gain-model/"
        "cross_validation_summary.csv"
    ),
    "colocation_model/cross_validation_folds.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-gain-model/"
        "cross_validation_folds.csv"
    ),
    "colocation_model/cross_validation_predictions.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-gain-model/"
        "cross_validation_predictions.csv"
    ),
    "colocation_model/final_coefficients.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-gain-model/"
        "final_coefficients.csv"
    ),
    "colocation_model/observed_vs_predicted.png": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-gain-model/"
        "observed_vs_predicted.png"
    ),
    "eligibility/eligibility_manifest.json": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-eligibility/"
        "eligibility_manifest.json"
    ),
    "eligibility/execution_eligibility.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-eligibility/"
        "execution_eligibility.csv"
    ),
    "ranking/benchmark_manifest.json": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-ranking-robustness/"
        "benchmark_manifest.json"
    ),
    "ranking/colocation_ranking_model.joblib": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-ranking-robustness/"
        "colocation_ranking_model.joblib"
    ),
    "ranking/coverage_predictions.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-ranking-robustness/"
        "coverage_predictions.csv"
    ),
    "ranking/feature_view_ablation.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-ranking-robustness/"
        "feature_view_ablation.csv"
    ),
    "ranking/ranking_fold_metrics.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-ranking-robustness/"
        "ranking_fold_metrics.csv"
    ),
    "ranking/ranking_predictions.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-ranking-robustness/"
        "ranking_predictions.csv"
    ),
    "ranking/ranking_robustness.png": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-ranking-robustness/"
        "ranking_robustness.png"
    ),
    "ranking/ranking_summary.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-colocation-ranking-robustness/"
        "ranking_summary.csv"
    ),
    "n3_freeze/batch-300-n3-colocation-holdout.yml": (
        ROOT
        / "generated/model-freezes/colocation-ranking-before-n3-v1/"
        "batch-300-n3-colocation-holdout.yml"
    ),
    "n3_freeze/batch-300-n3-holdout.yml": (
        ROOT
        / "generated/model-freezes/colocation-ranking-before-n3-v1/"
        "batch-300-n3-holdout.yml"
    ),
    "n3_freeze/benchmark_manifest.json": (
        ROOT
        / "generated/model-freezes/colocation-ranking-before-n3-v1/"
        "benchmark_manifest.json"
    ),
    "n3_freeze/colocation_ranking_model.joblib": (
        ROOT
        / "generated/model-freezes/colocation-ranking-before-n3-v1/"
        "colocation_ranking_model.joblib"
    ),
    "n3_freeze/colocation_ranking_v1.yml": (
        ROOT
        / "generated/model-freezes/colocation-ranking-before-n3-v1/"
        "colocation_ranking_v1.yml"
    ),
    "n3_freeze/corpus_execution_plan.yml": (
        ROOT
        / "generated/model-freezes/colocation-ranking-before-n3-v1/"
        "corpus_execution_plan.yml"
    ),
    "n3_freeze/expected_executions.csv": (
        ROOT
        / "generated/model-freezes/colocation-ranking-before-n3-v1/"
        "expected_executions.csv"
    ),
    "n3_freeze/freeze_manifest.json": (
        ROOT
        / "generated/model-freezes/colocation-ranking-before-n3-v1/"
        "freeze_manifest.json"
    ),
    "n3_freeze/training_pair_reference.csv": (
        ROOT
        / "generated/model-freezes/colocation-ranking-before-n3-v1/"
        "training_pair_reference.csv"
    ),
    "n3_result/analysis_manifest.json": (
        ROOT
        / "analysis/reports/pressure-raw-v1-n3-colocation-no-refit/"
        "analysis_manifest.json"
    ),
    "n3_result/n3_bootstrap_intervals.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-n3-colocation-no-refit/"
        "n3_bootstrap_intervals.csv"
    ),
    "n3_result/n3_feature_missingness.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-n3-colocation-no-refit/"
        "n3_feature_missingness.csv"
    ),
    "n3_result/n3_no_refit_ranking.png": (
        ROOT
        / "analysis/reports/pressure-raw-v1-n3-colocation-no-refit/"
        "n3_no_refit_ranking.png"
    ),
    "n3_result/n3_pair_predictions.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-n3-colocation-no-refit/"
        "n3_pair_predictions.csv"
    ),
    "n3_result/n3_pair_ranking.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-n3-colocation-no-refit/"
        "n3_pair_ranking.csv"
    ),
    "n3_result/n3_metrics_by_placement.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-n3-colocation-no-refit/"
        "n3_metrics_by_placement.csv"
    ),
    "n3_result/n3_ranking_metrics.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-n3-colocation-no-refit/"
        "n3_ranking_metrics.csv"
    ),
    "n3_result/n3_result_equivalence.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-n3-colocation-no-refit/"
        "n3_result_equivalence.csv"
    ),
    "n3_result/n3_topology_completeness.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-n3-colocation-no-refit/"
        "n3_topology_completeness.csv"
    ),
    "n3_lineage/corpus_attempts.csv": (
        WORKSPACE
        / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs/"
        "pressure-raw-v1-n3-colocation-holdout/corpus_attempts.csv"
    ),
    "n3_lineage/group_attempts.csv": (
        WORKSPACE
        / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs/"
        "pressure-raw-v1-n3-colocation-holdout/group_attempts.csv"
    ),
    "n3_lineage/logical_run_index_manifest.json": (
        WORKSPACE
        / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs/"
        "pressure-raw-v1-n3-colocation-holdout/logical_run_index_manifest.json"
    ),
    "n3_lineage/resolved_query_status.csv": (
        WORKSPACE
        / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs/"
        "pressure-raw-v1-n3-colocation-holdout/resolved_query_status.csv"
    ),
    "decision/README.md": (
        ROOT
        / "analysis/reports/pressure-raw-v1-mitigation-modeling-decision/README.md"
    ),
    "decision/decision_manifest.json": (
        ROOT
        / "analysis/reports/pressure-raw-v1-mitigation-modeling-decision/"
        "decision_manifest.json"
    ),
    "decision/mitigation_modeling_decisions.csv": (
        ROOT
        / "analysis/reports/pressure-raw-v1-mitigation-modeling-decision/"
        "mitigation_modeling_decisions.csv"
    ),
}

REPOSITORIES = {
    "master-regimes": ROOT,
    "master-regimes-infra": WORKSPACE / "master-regimes-infra",
    "psql-benchmarks": WORKSPACE / "psql-benchmarks",
    "citus-datagen": WORKSPACE / "citus-datagen",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze the curated pressure-actionability evidence package."
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--evidence-commit", required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def copy_sources(out_dir: Path) -> list[dict[str, Any]]:
    inventory = []
    for relative, source in SOURCE_FILES.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = out_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        inventory.append(
            {
                "path": relative,
                "sha256": sha256(destination),
                "bytes": destination.stat().st_size,
            }
        )
    return inventory


def write_readme(out_dir: Path, manifest: dict[str, Any]) -> None:
    repositories = "\n".join(
        f"- `{name}`: `{value['commit']}` (`{value['branch']}`)"
        for name, value in manifest["source_repositories"].items()
    )
    text = f"""# Pressure actionability v1

Ovo je kurirani dokazni paket za intervencijski i prediktivni dio rada.
Sirovi planovi i indeks izvršenja ostaju izvan Git repozitorija zbog veličine.

## Zaključani izvor

- Commit iz kojeg su generisani dokazi: `{manifest['evidence_generation_commit']}`.
- Program: `pressure-raw-v1`.
- Konsolidovane primarne opservacije: `2607/2607`.
- Kontrafaktualni parovi: `418/418` strogo prihvatljivih.
- Naknadna provjera rezultatske ekvivalentnosti: `83/83` razriješena para.
- Primarna akcija: `use_colocated_distribution`.
- Primarni modelski izlaz: rang prioriteta, uz procijenjeni dobitak kao
  sekundarni izlaz.
- Zamrznuti N=3 test: `96/96` izvršenja i `16/16` parova bez ponovnog učenja.
- N=3 rezultat rangiranja: Spearman `0.844`, Kendall `0.683`, NDCG@5 `0.990`.
- Kalibracija N=3 dobitka nije podržana izvan trening pokrivenosti.

## Repozitoriji

{repositories}

## Sadržaj

- `contracts/`: ugovori prikupljanja, provjere rezultata, akcija i modela.
- `corpus/`: program i konsolidacijski manifest bez velike matrice izvršenja.
- `correctness/`: tipizirane odluke za 83 ranije izdvojena para.
- `action_audit/`: finalni pregled svih 418 parova.
- `colocation_model/`: matrica od 75 parova, grupisani izdvojeni skupovi i
  serijalizovani model.
- `eligibility/`: deterministički sloj primjenjivosti colocation akcije.
- `ranking/`: isti foldovi za baseline, Ridge, ElasticNet i plitki gradient
  boosting, te core/extended ablation.
- `n3_freeze/`: model, preprocessing, P99 prag, ugovori i 96 očekivanih
  izvršenja zaključani prije N=3 testa.
- `n3_result/`: no-refit rangiranje, kalibracija, potpunost topologije i
  rezultatska ekvivalentnost.
- `n3_lineage/`: pokušaji i kanonski resolver, uključujući ciljani retry jednog
  nepotpunog dokaznog slota.
- `decision/`: zaključana podjela na prediktivni rezultat, ograničene studije,
  kalibracije i negativne rezultate.

`checksums.sha256` provjerava svaki fajl paketa osim samog spiska. Provjera se
pokreće iz korijena ovog direktorija komandom:

```bash
sha256sum -c checksums.sha256
```
"""
    (out_dir / "README.md").write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir.resolve()
    evidence_commit = git(ROOT, "rev-parse", args.evidence_commit)
    git(ROOT, "merge-base", "--is-ancestor", evidence_commit, "HEAD")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    inventory = copy_sources(out_dir)
    ranking_manifest = json.loads(
        (out_dir / "ranking/benchmark_manifest.json").read_text(encoding="utf-8")
    )
    n3_manifest = json.loads(
        (out_dir / "n3_result/analysis_manifest.json").read_text(encoding="utf-8")
    )
    freeze_manifest = json.loads(
        (out_dir / "n3_freeze/freeze_manifest.json").read_text(encoding="utf-8")
    )
    if ranking_manifest.get("primary_estimator") != "ridge":
        raise ValueError("Plan 41 release requires Ridge as the primary estimator")
    if ranking_manifest.get("selected_feature_view") != "extended":
        raise ValueError("Plan 41 release requires the selected extended feature view")
    if n3_manifest.get("no_refit_verified") is not True:
        raise ValueError("N=3 release evidence does not verify the no-refit contract")
    if n3_manifest.get("model_sha256_before") != n3_manifest.get(
        "model_sha256_after"
    ):
        raise ValueError("N=3 model changed during the no-refit evaluation")
    if n3_manifest.get("execution_count") != 96 or n3_manifest.get("pair_count") != 16:
        raise ValueError("N=3 release evidence has unexpected coverage")
    if n3_manifest.get("technical_gate") != "GO":
        raise ValueError("N=3 technical gate is not GO")
    expected_scope = (
        "descriptive_ranking_on_16_out_of_coverage_n3_pairs_"
        "not_production_generalization"
    )
    if n3_manifest.get("interpretation_scope") != expected_scope:
        raise ValueError("N=3 interpretation scope is not sufficiently constrained")
    bootstrap = n3_manifest.get("bootstrap", {})
    if bootstrap.get("resamples") != 10_000:
        raise ValueError("N=3 release requires 10,000 bootstrap resamples")
    if {row.get("metric") for row in bootstrap.get("intervals", [])} != {
        "spearman",
        "ndcg_at_5",
    }:
        raise ValueError("N=3 release is missing ranking uncertainty intervals")
    placements = n3_manifest.get("placement_metrics", [])
    if {row.get("placement_profile") for row in placements} != {
        "balanced",
        "apac_dominant",
    }:
        raise ValueError("N=3 release is missing placement-stratified metrics")
    if any(int(row.get("pair_count", 0)) != 8 for row in placements):
        raise ValueError("N=3 placement profiles must each contain eight pairs")
    if freeze_manifest.get("no_refit") is not True:
        raise ValueError("N=3 freeze manifest permits refitting")
    manifest = {
        "release_contract": "pressure-actionability-release-v1",
        "evidence_generation_commit": evidence_commit,
        "source_repositories": {
            name: {
                "commit": git(repo, "rev-parse", "HEAD"),
                "branch": git(repo, "branch", "--show-current"),
            }
            for name, repo in REPOSITORIES.items()
        },
        "evidence": {
            "execution_count": 2607,
            "condition_count": 869,
            "counterfactual_pair_count": 418,
            "strict_pair_count": 418,
            "correctness_recovery_pair_count": 83,
            "colocation_pair_count": 75,
            "colocation_model_gate": "MIXED_MODEL_EVIDENCE",
            "primary_operational_output": "ranking",
            "primary_estimator": ranking_manifest["primary_estimator"],
            "selected_feature_view": ranking_manifest["selected_feature_view"],
            "benchmark_estimators": ranking_manifest["benchmark_estimators"],
            "n3_execution_count": n3_manifest["execution_count"],
            "n3_pair_count": n3_manifest["pair_count"],
            "n3_no_refit_verified": n3_manifest["no_refit_verified"],
            "n3_ranking_support": n3_manifest["ranking_support"],
            "n3_outside_training_p99_count": n3_manifest[
                "outside_training_p99_count"
            ],
            "n3_interpretation_scope": n3_manifest["interpretation_scope"],
            "n3_bootstrap": n3_manifest["bootstrap"],
            "n3_placement_metrics": n3_manifest["placement_metrics"],
            "n3_ranking_metrics": n3_manifest["ranking_metrics"],
        },
        "files": inventory,
    }
    write_readme(out_dir, manifest)
    manifest["files"].append(
        {
            "path": "README.md",
            "sha256": sha256(out_dir / "README.md"),
            "bytes": (out_dir / "README.md").stat().st_size,
        }
    )
    (out_dir / "release_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    files = sorted(
        path
        for path in out_dir.rglob("*")
        if path.is_file() and path.name != "checksums.sha256"
    )
    checksums = [
        f"{sha256(path)}  {path.relative_to(out_dir)}"
        for path in files
    ]
    (out_dir / "checksums.sha256").write_text(
        "\n".join(checksums) + "\n", encoding="utf-8"
    )
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
