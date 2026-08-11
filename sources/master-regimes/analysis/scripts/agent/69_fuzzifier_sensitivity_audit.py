from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.stats import spearmanr
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

from master_regimes.config import load_yaml
from master_regimes.representation_audit import (
    fcm_metrics,
    fit_best_fcm,
    memberships_from_centers,
    seed_stability,
    squared_distances,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FREEZE_DIR = ROOT / "analysis/reports/semantic-v2-model-freeze"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit FCM sensitivity to the fuzzifier without changing the final model."
        )
    )
    parser.add_argument("--freeze-dir", type=Path, default=DEFAULT_FREEZE_DIR)
    parser.add_argument(
        "--fuzzifiers",
        default="1.5,1.7,2.0",
        help="Comma-separated fuzzifier values greater than one.",
    )
    parser.add_argument(
        "--external-weighted",
        type=Path,
        default=None,
        help="Optional semantic weighted matrix projected through frozen centers.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "analysis/reports/semantic-v2-fuzzifier-sensitivity",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_fuzzifiers(value: str) -> list[float]:
    result = sorted({float(item.strip()) for item in value.split(",") if item.strip()})
    if not result or any(item <= 1.0 for item in result):
        raise ValueError("Every fuzzifier must be greater than one")
    return result


def align_to_reference(
    centers: np.ndarray,
    memberships: np.ndarray,
    reference_centers: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    costs = np.sqrt(squared_distances(centers, reference_centers))
    candidate_indices, reference_indices = linear_sum_assignment(costs)
    aligned_centers = np.empty_like(centers)
    aligned_memberships = np.empty_like(memberships)
    shifts = np.empty(len(reference_centers), dtype=float)
    for candidate, reference in zip(
        candidate_indices,
        reference_indices,
        strict=True,
    ):
        aligned_centers[reference] = centers[candidate]
        aligned_memberships[:, reference] = memberships[:, candidate]
        shifts[reference] = costs[candidate, reference]
    return aligned_centers, aligned_memberships, shifts


def membership_summary(memberships: np.ndarray) -> dict[str, float]:
    sorted_memberships = np.sort(memberships, axis=1)
    return {
        "avg_max_membership": float(memberships.max(axis=1).mean()),
        "median_max_membership": float(np.median(memberships.max(axis=1))),
        "avg_top2_margin": float(
            (sorted_memberships[:, -1] - sorted_memberships[:, -2]).mean()
        ),
        "median_top2_margin": float(
            np.median(sorted_memberships[:, -1] - sorted_memberships[:, -2])
        ),
    }


def fixed_center_rows(
    *,
    run_ids: pd.Series,
    values: np.ndarray,
    centers: np.ndarray,
    fuzzifiers: list[float],
    reference_labels: np.ndarray,
    scope: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries: list[dict[str, Any]] = []
    details: list[pd.DataFrame] = []
    reference_memberships, _ = memberships_from_centers(
        values,
        centers,
        fuzzifier=1.7,
    )
    reference_uncertainty = 1.0 - reference_memberships.max(axis=1)
    reference_sorted = np.sort(reference_memberships, axis=1)
    reference_margin = reference_sorted[:, -1] - reference_sorted[:, -2]
    for fuzzifier in fuzzifiers:
        memberships, distances = memberships_from_centers(
            values,
            centers,
            fuzzifier=fuzzifier,
        )
        labels = memberships.argmax(axis=1)
        summary = membership_summary(memberships)
        sorted_memberships = np.sort(memberships, axis=1)
        uncertainty = 1.0 - memberships.max(axis=1)
        margin = sorted_memberships[:, -1] - sorted_memberships[:, -2]
        summaries.append(
            {
                "scope": scope,
                "fuzzifier": fuzzifier,
                "row_count": len(values),
                "hard_label_agreement_with_m1_7": float(
                    np.mean(labels == reference_labels)
                ),
                "ari_with_m1_7": float(
                    adjusted_rand_score(reference_labels, labels)
                ),
                "nmi_with_m1_7": float(
                    normalized_mutual_info_score(reference_labels, labels)
                ),
                "uncertainty_rank_spearman_with_m1_7": float(
                    spearmanr(reference_uncertainty, uncertainty).statistic
                ),
                "top2_margin_rank_spearman_with_m1_7": float(
                    spearmanr(reference_margin, margin).statistic
                ),
                **summary,
            }
        )
        frame = pd.DataFrame(
            {
                "scope": scope,
                "query_run_id": run_ids.astype(str),
                "fuzzifier": fuzzifier,
                "dominant_cluster": labels,
                "nearest_center_distance": distances.min(axis=1),
                "max_membership": memberships.max(axis=1),
            }
        )
        frame["top2_membership_margin"] = (
            sorted_memberships[:, -1] - sorted_memberships[:, -2]
        )
        for cluster in range(centers.shape[0]):
            frame[f"membership_c{cluster}"] = memberships[:, cluster]
        details.append(frame)
    return pd.DataFrame(summaries), pd.concat(details, ignore_index=True)


def main() -> int:
    args = parse_args()
    freeze_dir = args.freeze_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fuzzifiers = parse_fuzzifiers(args.fuzzifiers)
    if 1.7 not in fuzzifiers:
        raise ValueError("The final fuzzifier m=1.7 must be included")

    manifest_path = freeze_dir / "semantic_v2_model_manifest.yml"
    manifest = load_yaml(manifest_path)
    if float(manifest["fuzzifier"]) != 1.7:
        raise ValueError("Frozen final model is expected to use m=1.7")
    if int(manifest["primary_resolution"]) != 4:
        raise ValueError("Fuzzifier audit is defined for frozen k=4")

    weighted_path = ROOT / str(manifest["weighted_matrix"])
    weighted = pd.read_csv(weighted_path)
    features = [str(value) for value in manifest["features"]]
    if list(weighted.columns) != ["query_run_id", *features]:
        raise ValueError("Frozen weighted matrix does not match manifest feature order")
    values = weighted[features].to_numpy(dtype=float)
    seeds = [int(value) for value in manifest["seeds"]]
    frozen_centers_path = freeze_dir / str(
        manifest["models"]["k4"]["center_file"]
    )
    frozen_centers_frame = pd.read_csv(frozen_centers_path)
    frozen_centers = frozen_centers_frame[features].to_numpy(dtype=float)
    frozen_memberships = pd.read_csv(
        freeze_dir / str(manifest["models"]["k4"]["membership_file"])
    )
    frozen_labels = frozen_memberships["dominant_cluster"].to_numpy(dtype=int)

    refit_summaries: list[dict[str, Any]] = []
    refit_seed_rows: list[dict[str, Any]] = []
    for fuzzifier in fuzzifiers:
        best, fits = fit_best_fcm(
            values,
            k=4,
            seeds=seeds,
            fuzzifier=fuzzifier,
        )
        aligned_centers, aligned_memberships, center_shifts = align_to_reference(
            best.centers,
            best.memberships,
            frozen_centers,
        )
        aligned_labels = aligned_memberships.argmax(axis=1)
        metrics = fcm_metrics(values, best)
        refit_summaries.append(
            {
                "fuzzifier": fuzzifier,
                "representative_seed": best.seed,
                "objective": best.objective,
                "iterations": best.iterations,
                "converged": best.converged,
                "hard_label_agreement_with_final": float(
                    np.mean(aligned_labels == frozen_labels)
                ),
                "ari_with_final": float(
                    adjusted_rand_score(frozen_labels, aligned_labels)
                ),
                "nmi_with_final": float(
                    normalized_mutual_info_score(frozen_labels, aligned_labels)
                ),
                "center_shift_mean": float(center_shifts.mean()),
                "center_shift_max": float(center_shifts.max()),
                **metrics,
                **seed_stability(fits),
            }
        )
        for fit in fits:
            aligned_fit_centers, aligned_fit_memberships, fit_shifts = (
                align_to_reference(
                    fit.centers,
                    fit.memberships,
                    frozen_centers,
                )
            )
            del aligned_fit_centers
            labels = aligned_fit_memberships.argmax(axis=1)
            refit_seed_rows.append(
                {
                    "fuzzifier": fuzzifier,
                    "seed": fit.seed,
                    "objective": fit.objective,
                    "iterations": fit.iterations,
                    "converged": fit.converged,
                    "ari_with_final": float(
                        adjusted_rand_score(frozen_labels, labels)
                    ),
                    "nmi_with_final": float(
                        normalized_mutual_info_score(frozen_labels, labels)
                    ),
                    "center_shift_mean": float(fit_shifts.mean()),
                    "center_shift_max": float(fit_shifts.max()),
                }
            )

        if fuzzifier == 1.7 and not np.allclose(
            aligned_centers,
            frozen_centers,
            atol=1.0e-10,
            rtol=1.0e-10,
        ):
            raise ValueError("m=1.7 refit does not reproduce frozen final centers")

    fixed_summary, fixed_details = fixed_center_rows(
        run_ids=weighted["query_run_id"],
        values=values,
        centers=frozen_centers,
        fuzzifiers=fuzzifiers,
        reference_labels=frozen_labels,
        scope="training_baseline_fixed_centers",
    )
    external_summary = pd.DataFrame()
    external_details = pd.DataFrame()
    external_path: Path | None = None
    if args.external_weighted is not None:
        external_path = args.external_weighted.resolve()
        external = pd.read_csv(external_path)
        if list(external.columns) != ["query_run_id", *features]:
            raise ValueError("External weighted matrix does not match frozen features")
        external_values = external[features].to_numpy(dtype=float)
        reference_memberships, _ = memberships_from_centers(
            external_values,
            frozen_centers,
            fuzzifier=1.7,
        )
        external_summary, external_details = fixed_center_rows(
            run_ids=external["query_run_id"],
            values=external_values,
            centers=frozen_centers,
            fuzzifiers=fuzzifiers,
            reference_labels=reference_memberships.argmax(axis=1),
            scope="external_fixed_centers",
        )

    pd.DataFrame(refit_summaries).to_csv(
        out_dir / "fuzzifier_refit_summary.csv",
        index=False,
    )
    pd.DataFrame(refit_seed_rows).to_csv(
        out_dir / "fuzzifier_refit_seed_scores.csv",
        index=False,
    )
    fixed_summary.to_csv(
        out_dir / "fuzzifier_fixed_center_summary.csv",
        index=False,
    )
    fixed_details.to_csv(
        out_dir / "fuzzifier_fixed_center_memberships.csv",
        index=False,
    )
    if not external_summary.empty:
        external_summary.to_csv(
            out_dir / "external_fuzzifier_fixed_center_summary.csv",
            index=False,
        )
        external_details.to_csv(
            out_dir / "external_fuzzifier_fixed_center_memberships.csv",
            index=False,
        )

    summary = {
        "audit_id": "semantic-v2-fuzzifier-sensitivity-v1",
        "fuzzifiers": fuzzifiers,
        "final_fuzzifier": 1.7,
        "primary_resolution": 4,
        "training_rows": len(weighted),
        "feature_count": len(features),
        "seeds": seeds,
        "model_refit_for_sensitivity_only": True,
        "external_rows_used_for_refit": 0,
        "final_model_changed": False,
        "weighted_matrix": str(weighted_path.relative_to(ROOT)),
        "weighted_matrix_sha256": sha256(weighted_path),
        "frozen_manifest_sha256": sha256(manifest_path),
        "external_weighted": (
            portable_path(external_path) if external_path is not None else None
        ),
        "external_weighted_sha256": (
            sha256(external_path) if external_path is not None else None
        ),
    }
    (out_dir / "fuzzifier_sensitivity_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    refit_summary = pd.DataFrame(refit_summaries)
    fixed_summary_by_m = fixed_summary.set_index("fuzzifier")
    external_summary_by_m = (
        external_summary.set_index("fuzzifier")
        if not external_summary.empty
        else pd.DataFrame()
    )
    refit_lines = "\n".join(
        (
            f"- `m={row.fuzzifier:g}`: ARI prema finalnoj particiji "
            f"`{row.ari_with_final:.6f}`, prosjecno maksimalno clanstvo "
            f"`{row.avg_max_membership:.6f}`, prosjecna top-2 margina "
            f"`{row.avg_top2_margin:.6f}`, prosjecni pomak centara "
            f"`{row.center_shift_mean:.6f}`."
        )
        for row in refit_summary.itertuples(index=False)
    )
    fixed_lines = "\n".join(
        (
            f"- `m={fuzzifier:g}`: slaganje dominantnog prototipa "
            f"`{row.hard_label_agreement_with_m1_7:.6f}`, medijana "
            f"maksimalnog clanstva `{row.median_max_membership:.6f}`, "
            f"medijana top-2 margine `{row.median_top2_margin:.6f}`, "
            f"Spearmanov rang neodlucnosti prema `m=1.7` "
            f"`{row.uncertainty_rank_spearman_with_m1_7:.6f}`."
        )
        for fuzzifier, row in fixed_summary_by_m.iterrows()
    )
    external_section = ""
    if not external_summary_by_m.empty:
        external_lines = "\n".join(
            (
                f"- `m={fuzzifier:g}`: slaganje dominantnog prototipa "
                f"`{row.hard_label_agreement_with_m1_7:.6f}`, medijana "
                f"maksimalnog clanstva `{row.median_max_membership:.6f}`, "
                f"medijana top-2 margine `{row.median_top2_margin:.6f}`, "
                f"Spearmanov rang neodlucnosti prema `m=1.7` "
                f"`{row.uncertainty_rank_spearman_with_m1_7:.6f}`."
            )
            for fuzzifier, row in external_summary_by_m.iterrows()
        )
        external_section = f"""
## Vanjska no-refit projekcija

Vanjski redovi nisu korisceni za refit. Isti zamrznuti centri projektovani su
sa tri vrijednosti parametra `m`:

{external_lines}
"""
    (out_dir / "README.md").write_text(
        f"""# Audit osjetljivosti FCM fuzzifiera

## Ugovor

- finalni model ostaje `k=4`, `m=1.7`;
- testirane vrijednosti su `{", ".join(f"{value:g}" for value in fuzzifiers)}`;
- 19 pokazatelja, transformacije, porodične tezine i finalni centri nisu
  promijenjeni;
- refit je izveden samo kao offline analiza osjetljivosti i nije zamijenio
  finalni model;
- vanjski STATS-CEB redovi nisu korisceni za refit.

## Refit na trening korpusu

{refit_lines}

## Fiksni finalni centri na trening korpusu

{fixed_lines}
{external_section}
## Zakljucak

U posmatranom rasponu parametar `m` mijenja ostrinu fuzzy clanstava, ali ne
mijenja dominantni prototip pri projekciji na iste centre. Taj dio je ocekivan:
za netie udaljenosti monotona promjena eksponenta u FCM formuli ne mijenja
najblizi centar, nego samo raspodjelu clanstava. Fiksni-centar audit zato
provjerava osjetljivost fuzzy sigurnosti, a ne stabilnost tvrde oznake.

Refit reprezentativnog rjesenja zadrzava finalnu tvrdu particiju uz male pomake
centara. Pojedinacni seedovi ipak mogu konvergirati ka slabijim lokalnim
rjesenjima, pa rezultat ne ukida potrebu za visestrukim inicijalizacijama.
Finalni izbor `m=1.7` ostaje zakljucan i nije naknadno optimizovan prema
STATS-CEB izlazu.
""",
        encoding="utf-8",
    )
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
