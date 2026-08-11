#!/usr/bin/env python3
"""Verify that the thesis reports the frozen consolidated evaluation exactly."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


def _compact(text: str) -> str:
    without_emphasis = re.sub(r"\\textbf\{([^{}]*)\}", r"\1", text)
    without_stacks = re.sub(r"\\shortstack\{([^{}]*)\}", r"\1", without_emphasis)
    normalized_breaks = without_stacks.replace("\\\\", "; ")
    return " ".join(normalized_breaks.split())


def _decimal(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _contains(text: str, expected: str) -> bool:
    return _compact(expected) in _compact(text)


def verify(release_dir: Path, thesis_root: Path) -> dict[str, object]:
    results_path = thesis_root / "manuscript/chapters/reworked/05-rezultati.tex"
    methods_path = thesis_root / "manuscript/chapters/reworked/03-metodologija.tex"
    design_path = thesis_root / "manuscript/chapters/reworked/04-eksperimentalni-dizajn.tex"
    discussion_path = thesis_root / "manuscript/chapters/reworked/06-diskusija-i-ogranicenja.tex"
    conclusion_path = thesis_root / "manuscript/chapters/reworked/07-zakljucak.tex"
    abstract_path = thesis_root / "manuscript/preliminarne/sazetak-bs.tex"
    paths = [
        results_path,
        methods_path,
        design_path,
        discussion_path,
        conclusion_path,
        abstract_path,
    ]
    missing_files = [str(path) for path in paths if not path.is_file()]
    if missing_files:
        return {"status": "FAIL", "missing_files": missing_files, "checks": {}}

    texts = {path.name: path.read_text(encoding="utf-8") for path in paths}
    results = texts[results_path.name]
    methods = texts[methods_path.name]
    design = texts[design_path.name]
    combined = "\n".join(texts.values())
    numbers = json.loads((release_dir / "manuscript_numbers.json").read_text(encoding="utf-8"))
    summary = pd.read_csv(release_dir / "representation_summary.csv")

    checks: dict[str, bool] = {
        "broad_execution_count": "2.607/2.607" in results,
        "broad_pair_count": "418/418" in results,
        "development_not_final_holdout": _contains(
            design, "Ne predstavljaju završni test."
        ),
        "four_dataset_taxonomy": _contains(
            results, "Stvarni obim i uloga četiri eksperimentalna skupa"
        ),
        "exact_key_defined_as_normalized_sql": _contains(
            methods, "hash normalizovanog SQL-a"
        ),
        "logical_key_not_claimed_as_text_identity": _contains(
            methods, "Ne predstavlja automatsko prepoznavanje jednakog SQL teksta"
        ),
        "p99_not_safety_guarantee": _contains(
            methods, "produkcijska sigurnosna garancija"
        ),
        "phase_b_primary_cross_query": _contains(
            results,
            "pokrivenost 15/15, 12/15 tačnih prvih izbora i prosječni "
            f"propušteni dobitak {_decimal(numbers['r3_e4_regret'], 4)}",
        ),
        "phase_b_static_baseline": _contains(
            results,
            f"Top-1 {_decimal(numbers['topology_static_phase_b_top1'], 3)} i "
            f"propušteni dobitak {_decimal(numbers['topology_static_phase_b_regret'], 4)}",
        ),
        "q08_retained": _contains(
            results,
            f"Propušteni dobitak iznosio je {_decimal(numbers['q08_regret'], 4)}",
        ),
        "q08_without_is_secondary": _contains(
            results,
            f"Bez q08 prosječni propušteni dobitak faze B bio bi "
            f"{_decimal(numbers['q08_regret_without'], 4)}",
        ),
        "abstract_topology_result": _contains(
            texts[abstract_path.name],
            "cross-query memorija pokrila je 15/15 i pravilno rangirala 12/15",
        ),
        "controlled_topology_replaces_mixed_claim": _contains(
            results, "Kontrolisanu topološku tvrdnju daje odvojena Sekcija"
        ),
    }

    for row in summary.itertuples(index=False):
        coverage = f"{int(row.recommendation_count)}/{int(row.episode_count)}"
        top1 = "--" if pd.isna(row.top1_accuracy) else _decimal(float(row.top1_accuracy), 3)
        regret = "--" if pd.isna(row.mean_regret_log2) else _decimal(float(row.mean_regret_log2), 3)
        key = f"representation_{row.evaluation}_{row.representation}"
        checks[key] = _contains(results, f"{coverage}; {top1}; {regret}")

    for figure in (
        "05-representation-ablation.pdf",
        "06-topology-shift-adaptation.pdf",
        "07-q08-failure-case.pdf",
        "08-coverage-regret-curve.pdf",
    ):
        checks[f"figure_{figure}"] = (thesis_root / "diagrams/experimental" / figure).is_file()

    prohibited = {
        "n3_changed_best_action": "N3 promijenio najbolju akciju",
        "correct_abstention_overclaim": "ispravno apstinirao",
        "development_final_holdout": "razvojni finalni holdout",
        "p99_error_probability": "P99 vjerovatnoća greške",
    }
    prohibited_hits = {
        key: phrase
        for key, phrase in prohibited.items()
        if phrase.casefold() in combined.casefold()
    }
    status = "PASS" if all(checks.values()) and not prohibited_hits else "FAIL"
    return {
        "status": status,
        "release_dir": str(release_dir.resolve()),
        "thesis_root": str(thesis_root.resolve()),
        "checks": checks,
        "prohibited_hits": prohibited_hits,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--thesis-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = verify(args.release_dir, args.thesis_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.out)}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
