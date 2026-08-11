#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT.parent
THESIS_ROOT = WORKSPACE / "master-regimes-thesis"
FINAL_REPORT = ROOT / "analysis/reports/semantic-v2-final-consistency"
GEOMETRY_REPORT = ROOT / "analysis/reports/stats-ceb-representation-audit-v1"
V2B_REPORT = ROOT / "analysis/reports/stats-ceb-semantic-v2b-holdout"
CLAIMS_CHECKPOINT = (
    ROOT / "llmcontext/plans/checkpoints/semantic-v2-thesis-claims.yml"
)
DEFAULT_OUT_DIR = ROOT / "analysis/reports/semantic-v2-thesis-finalization"
DEFAULT_FIGURE_DIR = THESIS_ROOT / "figures/semantic-v2"
DEFAULT_CHECKPOINT = (
    ROOT / "llmcontext/plans/checkpoints/semantic-v2-thesis-results.yml"
)

COLORS = {
    "ink": "#1c2b30",
    "teal": "#176b61",
    "blue": "#315f7d",
    "amber": "#9a6a20",
    "gray": "#879195",
    "light": "#e9eeee",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build thesis-facing semantic-v2 figures and provenance maps."
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--figure-dir", type=Path, default=DEFAULT_FIGURE_DIR)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument(
        "--manual-visual-review-confirmed",
        action="store_true",
        help=(
            "Confirm that generated PNGs and their placement in the thesis PDF "
            "were reviewed manually."
        ),
    )
    return parser.parse_args()


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve()))
    except ValueError:
        return str(path)


def save_figure(fig: plt.Figure, base: Path) -> None:
    for suffix in (".pdf", ".svg", ".png"):
        target = base.with_suffix(suffix)
        fig.savefig(
            target,
            bbox_inches="tight",
            dpi=180 if suffix == ".png" else None,
        )
        if suffix == ".svg":
            lines = target.read_text(encoding="utf-8").splitlines()
            target.write_text(
                "\n".join(line.rstrip() for line in lines) + "\n",
                encoding="utf-8",
            )
    plt.close(fig)


def setup_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 10.5,
            "axes.labelsize": 10,
            "axes.edgecolor": COLORS["ink"],
            "axes.linewidth": 0.8,
            "xtick.color": COLORS["ink"],
            "ytick.color": COLORS["ink"],
            "text.color": COLORS["ink"],
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def q100_figure(figure_dir: Path) -> None:
    audit = pd.read_csv(GEOMETRY_REPORT / "q100_feature_distance_audit.csv")
    drf = audit.loc[audit["feature"].eq("drf_bytes_proxy")].iloc[0]
    summary = json.loads(
        (GEOMETRY_REPORT / "representation_audit_summary.json").read_text(
            encoding="utf-8"
        )
    )
    q100 = summary["q100"]

    fig, axes = plt.subplots(1, 3, figsize=(10.4, 4.1))
    raw_values = [
        float(drf["training_raw_p99"]),
        float(drf["training_raw_max"]),
        float(drf["q100_raw_value"]),
    ]
    labels = ["P99 glavnog korpusa", "Maksimum glavnog korpusa", "q100"]
    axes[0].barh(
        labels,
        raw_values,
        color=[COLORS["gray"], COLORS["blue"], COLORS["amber"]],
        height=0.58,
    )
    axes[0].set_xscale("log")
    axes[0].set_xlabel("Sirovi DRF, logaritamska osa")
    axes[0].set_title("(a) Neograničeni omjer")
    axes[0].grid(axis="x", color=COLORS["light"], linewidth=0.8)
    for index, value in enumerate(raw_values):
        axes[0].text(
            value * 1.05,
            index,
            f"{value:,.0f}",
            va="center",
            fontsize=8,
        )

    share = float(q100["dominant_feature_squared_distance_share"])
    axes[1].bar(
        ["DRF", "ostalih 20"],
        [share, 1.0 - share],
        color=[COLORS["amber"], COLORS["light"]],
        edgecolor=COLORS["ink"],
        linewidth=0.5,
    )
    axes[1].set_ylim(0, 1)
    axes[1].set_ylabel("Udio kvadrirane udaljenosti reference")
    axes[1].set_title("(b) Dominacija ablacijske reference")
    axes[1].text(0, share + 0.03, f"{share * 100:.1f}%", ha="center")

    percentile = float(q100["semantic_baseline_percentile"])
    axes[2].barh(["q100"], [percentile], color=COLORS["teal"], height=0.35)
    axes[2].axvline(
        0.99,
        color=COLORS["amber"],
        linestyle="--",
        linewidth=1.2,
    )
    axes[2].set_xlim(0.90, 1.005)
    axes[2].set_xlabel("Percentil udaljenosti")
    axes[2].set_title("(c) Pozicija u modelu F19")
    axes[2].text(
        percentile - 0.002,
        0,
        f"{percentile * 100:.1f}. percentil",
        va="center",
        ha="right",
        color="white",
    )
    axes[2].text(0.99, 0.27, "P99", ha="center", color=COLORS["amber"])
    axes[2].grid(axis="x", color=COLORS["light"], linewidth=0.8)
    fig.suptitle(
        "q100: ekstremna redukcija i položaj prema empirijskoj P99 granici",
        fontsize=11,
        fontweight="bold",
    )
    fig.tight_layout()
    save_figure(fig, figure_dir / "01-q100-v1-v2-geometry")


def controlled_contrast_figure(figure_dir: Path) -> None:
    frame = pd.read_csv(FINAL_REPORT / "controlled_contrast_summary.csv")
    frame["query_shape"] = np.where(
        frame["query_condition_id"].str.startswith("top_tenants"),
        "Top-K",
        "Tenant-point",
    )
    grouped = (
        frame.groupby(["contrast", "query_shape"], as_index=False)
        .agg(
            direct_signal=("median_direct_signal_delta", "median"),
            feature_l2=("median_semantic_feature_l2", "median"),
            membership_l1=("median_membership_l1", "median"),
        )
        .sort_values(["contrast", "query_shape"])
    )
    order = [
        ("B-C_worker_placement", "Top-K"),
        ("B-C_worker_placement", "Tenant-point"),
        ("A-D_regional_asymmetry", "Top-K"),
        ("A-D_regional_asymmetry", "Tenant-point"),
    ]
    lookup = {
        (row.contrast, row.query_shape): row
        for row in grouped.itertuples(index=False)
    }
    labels = [
        "B-C\nTop-K",
        "B-C\nTenant\npoint",
        "A-D\nTop-K",
        "A-D\nTenant\npoint",
    ]
    direct = [float(lookup[key].direct_signal) for key in order]
    feature = [float(lookup[key].feature_l2) for key in order]
    membership = [float(lookup[key].membership_l1) for key in order]
    colors = [
        COLORS["teal"],
        COLORS["gray"],
        COLORS["blue"],
        COLORS["gray"],
    ]

    fig, axes = plt.subplots(1, 3, figsize=(10.4, 4.4), sharex=True)
    series = [
        (direct, "Ciljani fizički signal", "(a) Direktni cilj"),
        (feature, r"$L_2$ pomak u $x_{F19}^{(19)}$", "(b) Prostor F19"),
        (membership, r"$L_1$ pomak u $u_{F19}^{(4)}$", "(c) F19 kompresija"),
    ]
    for axis, (values, ylabel, title) in zip(axes, series, strict=True):
        bars = axis.bar(range(4), values, color=colors, width=0.65)
        axis.set_xticks(range(4), labels)
        axis.tick_params(axis="x", labelsize=8.5)
        axis.set_ylabel(ylabel)
        axis.set_title(title)
        axis.grid(axis="y", color=COLORS["light"], linewidth=0.8)
        for bar, value in zip(bars, values, strict=True):
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values + [0.01]) * 0.03,
                f"{value:.3f}",
                ha="center",
                va="bottom",
                fontsize=7.5,
            )
        axis.set_ylim(0, max(values + [0.01]) * 1.20)
    fig.suptitle(
        "Kontrolisani kontrasti: fizički signal, vektor F19 i njegova članstva",
        fontsize=11,
        fontweight="bold",
    )
    fig.tight_layout()
    save_figure(fig, figure_dir / "02-controlled-topology-contrasts")


def portability_prototype_figure(figure_dir: Path) -> None:
    comparison = pd.read_csv(V2B_REPORT / "holdout_v1_v2_comparison.csv")
    profiles = pd.read_csv(FINAL_REPORT / "prototype_feature_profiles.csv")
    coverage = [
        int((~comparison["v1_ood_above_frozen_p99"].astype(bool)).sum()),
        int((~comparison["v2_ood_above_frozen_p99"].astype(bool)).sum()),
    ]
    family = (
        profiles.groupby(["cluster", "family"], as_index=False)[
            "semantic_deviation"
        ]
        .mean()
        .pivot(index="cluster", columns="family", values="semantic_deviation")
    )
    preferred_order = [
        "remote_fanin_fetch",
        "regional_reduction",
        "normalized_spill_pressure",
        "skew_imbalance",
        "citus_topology_normalized",
        "estimate_error",
    ]
    family = family.reindex(columns=preferred_order)
    family_labels = [
        "udaljeni\ntok",
        "regionalna\nredukcija",
        "spill",
        "neravno-\nmjernost",
        "Citus\ntopologija",
        "greška\nprocjene",
    ]

    fig = plt.figure(figsize=(10.4, 5.0))
    grid = fig.add_gridspec(1, 2, width_ratios=[0.34, 0.66], wspace=0.28)
    axis_coverage = fig.add_subplot(grid[0, 0])
    bars = axis_coverage.bar(
        ["Empirijski\nbaseline", "Finalna\nreprezentacija"],
        coverage,
        color=[COLORS["gray"], COLORS["teal"]],
        width=0.58,
    )
    axis_coverage.set_ylim(0, 12.8)
    axis_coverage.set_ylabel("Izvršenja unutar zamrznutog P99")
    axis_coverage.set_title("(a) Potvrđujući STATS-CEB, n=12")
    axis_coverage.grid(axis="y", color=COLORS["light"], linewidth=0.8)
    for bar, value in zip(bars, coverage, strict=True):
        axis_coverage.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.25,
            f"{value}/12",
            ha="center",
            fontweight="bold",
        )

    axis_profiles = fig.add_subplot(grid[0, 1])
    values = family.to_numpy(dtype=float)
    limit = max(abs(values.min()), abs(values.max()))
    image = axis_profiles.imshow(
        values,
        cmap="RdBu_r",
        vmin=-limit,
        vmax=limit,
        aspect="auto",
    )
    axis_profiles.set_xticks(range(len(family_labels)), family_labels)
    axis_profiles.set_yticks(
        range(len(family.index)),
        [f"P{i}" for i in family.index],
    )
    axis_profiles.set_xlabel("Porodica pokazatelja")
    axis_profiles.set_ylabel("Prototip")
    axis_profiles.set_title("(b) Srednje semantičko odstupanje porodice")
    for row in range(values.shape[0]):
        for column in range(values.shape[1]):
            axis_profiles.text(
                column,
                row,
                f"{values[row, column]:+.2f}",
                ha="center",
                va="center",
                fontsize=7.5,
                color=(
                    "white"
                    if abs(values[row, column]) > limit * 0.55
                    else COLORS["ink"]
                ),
            )
    colorbar = fig.colorbar(
        image,
        ax=axis_profiles,
        fraction=0.046,
        pad=0.04,
    )
    colorbar.set_label("Odstupanje od globalnog prosjeka")
    fig.suptitle(
        "Vanjska pokrivenost i profili prototipa modela F19",
        fontsize=11,
        fontweight="bold",
    )
    save_figure(fig, figure_dir / "03-stats-coverage-and-prototypes")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def source_rows() -> list[dict[str, str]]:
    return [
        {
            "result_question": "reconstruction",
            "claim": "2,603 canonical executions pass lineage contracts",
            "source": (
                "master-regimes/analysis/reports/collector-correctness-v2/"
                "collector_correctness_summary.json"
            ),
            "script": (
                "master-regimes/analysis/scripts/agent/"
                "47_collector_correctness_thesis_tables.py"
            ),
            "thesis_location": "results / reconstruction",
        },
        {
            "result_question": "semantic_space",
            "claim": "k=3/4 geometry, algorithm agreement and leave-family-out",
            "source": (
                "master-regimes/analysis/reports/"
                "semantic-v2-final-consistency/"
            ),
            "script": (
                "master-regimes/analysis/scripts/agent/"
                "64_semantic_v2_final_consistency.py"
            ),
            "thesis_location": "results / semantic representation",
        },
        {
            "result_question": "semantic_space",
            "claim": (
                "q100 DRF contributes 86.6% of the empirical baseline "
                "squared distance"
            ),
            "source": (
                "master-regimes/analysis/reports/"
                "stats-ceb-representation-audit-v1/"
                "q100_feature_distance_audit.csv"
            ),
            "script": (
                "master-regimes/analysis/scripts/agent/"
                "60_representation_geometry_audit.py"
            ),
            "thesis_location": "results / semantic representation",
        },
        {
            "result_question": "semantic_space",
            "claim": "96 conditions and 328 repeatability rows",
            "source": (
                "master-regimes/analysis/reports/semantic-v2-final-consistency/"
                "repeatability_summary.csv"
            ),
            "script": (
                "master-regimes/analysis/scripts/agent/"
                "64_semantic_v2_final_consistency.py"
            ),
            "thesis_location": "results / reconstruction and reliability",
        },
        {
            "result_question": "topology",
            "claim": "865 paired balanced/skew topology contrasts",
            "source": (
                "master-regimes/analysis/reports/semantic-v2-final-consistency/"
                "balanced_skew_summary.csv"
            ),
            "script": (
                "master-regimes/analysis/scripts/agent/"
                "64_semantic_v2_final_consistency.py"
            ),
            "thesis_location": "results / topology",
        },
        {
            "result_question": "topology",
            "claim": "B-C worker and A-D regional controlled contrasts",
            "source": (
                "master-regimes/analysis/reports/semantic-v2-final-consistency/"
                "controlled_contrast_summary.csv"
            ),
            "script": (
                "master-regimes/analysis/scripts/agent/"
                "64_semantic_v2_final_consistency.py"
            ),
            "thesis_location": "results / topology",
        },
        {
            "result_question": "portability",
            "claim": (
                "development ablation compares empirical and final "
                "representation coverage on the 12-query holdout"
            ),
            "source": (
                "master-regimes/analysis/reports/"
                "stats-ceb-semantic-v2b-holdout/"
                "holdout_v1_v2_comparison.csv"
            ),
            "script": (
                "master-regimes/analysis/scripts/agent/"
                "63_semantic_v2_holdout_analysis.py"
            ),
            "thesis_location": "appendix / representation ablation",
        },
        {
            "result_question": "portability",
            "claim": (
                "final representation covers 190/195 validation executions "
                "with five edge cases"
            ),
            "source": (
                "master-regimes/analysis/reports/semantic-v2-final-consistency/"
                "external_ood_cases.csv"
            ),
            "script": (
                "master-regimes/analysis/scripts/agent/"
                "64_semantic_v2_final_consistency.py"
            ),
            "thesis_location": "results / portability",
        },
    ]


def figure_inventory() -> dict[str, Any]:
    return {
        "central_figures": [
            {
                "role": "architecture_and_lineage",
                "path": (
                    "master-regimes-thesis/diagrams/09-evidence-lineage.pdf"
                ),
                "source": (
                    "master-regimes-thesis/diagrams/09-evidence-lineage.dot"
                ),
                "tool": "Graphviz",
            },
            {
                "role": "runtime_and_collection",
                "path": (
                    "master-regimes-thesis/diagrams/"
                    "12-guided-query-sequence.pdf"
                ),
                "source": (
                    "master-regimes-thesis/diagrams/"
                    "12-guided-query-sequence.puml"
                ),
                "tool": "PlantUML",
            },
            {
                "role": "information_chain",
                "path": (
                    "master-regimes-thesis/diagrams/"
                    "13-guided-example-pipeline.pdf"
                ),
                "source": (
                    "master-regimes-thesis/diagrams/"
                    "13-guided-example-pipeline.dot"
                ),
                "tool": "Graphviz",
            },
            {
                "role": "controlled_topology_contrasts",
                "path": (
                    "master-regimes-thesis/figures/semantic-v2/"
                    "02-controlled-topology-contrasts.pdf"
                ),
                "source": (
                    "master-regimes/analysis/reports/"
                    "semantic-v2-final-consistency/"
                    "controlled_contrast_summary.csv"
                ),
                "tool": "Matplotlib",
            },
            {
                "role": "full_external_workload_audit",
                "path": (
                    "master-regimes-thesis/figures/semantic-v2/"
                    "04-stats-full-audit.pdf"
                ),
                "source": (
                    "master-regimes/analysis/reports/"
                    "stats-ceb-full-no-refit-v1/"
                ),
                "tool": "Graphviz",
            },
        ],
        "appendix_figures": [
            {
                "role": "q100_representation_ablation",
                "path": (
                    "master-regimes-thesis/figures/semantic-v2/"
                    "01-q100-v1-v2-geometry.pdf"
                ),
                "source": (
                    "master-regimes/analysis/reports/"
                    "stats-ceb-representation-audit-v1/"
                ),
                "tool": "Matplotlib",
            },
        ],
    }


def table_inventory() -> dict[str, Any]:
    return {
        "main_tables": [
            "collector correctness and lineage",
            "k=3 versus k=4 and hard baselines",
            "controlled topology contrasts",
            "STATS-CEB portability",
            "claim boundaries",
        ],
        "appendix_only": [
            "representation ablation: empirical reference versus final space",
            "all k=2..8 seed metrics",
            "threshold sensitivity grid",
            "full leave-family-out folds",
            "missingness/applicability matrix",
            "full repeatability stratification",
            "complete transition matrices",
        ],
    }


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir.resolve()
    figure_dir = args.figure_dir.resolve()
    checkpoint = args.checkpoint.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)

    claim_gate = yaml.safe_load(CLAIMS_CHECKPOINT.read_text(encoding="utf-8"))
    if claim_gate.get("decision") != "GO":
        raise ValueError("Plan 26 C0 must be GO before building Plan 27 package")

    setup_style()
    q100_figure(figure_dir)
    controlled_contrast_figure(figure_dir)
    portability_prototype_figure(figure_dir)

    sources = source_rows()
    write_csv(out_dir / "results_source_map.csv", sources)
    (out_dir / "central_figure_inventory.yml").write_text(
        yaml.safe_dump(
            figure_inventory(),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (out_dir / "central_table_inventory.yml").write_text(
        yaml.safe_dump(
            table_inventory(),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    expected = [
        figure_dir / f"{stem}.{suffix}"
        for stem in (
            "01-q100-v1-v2-geometry",
            "02-controlled-topology-contrasts",
            "03-stats-coverage-and-prototypes",
        )
        for suffix in ("pdf", "svg", "png")
    ]
    missing = [
        path for path in expected if not path.exists() or path.stat().st_size == 0
    ]
    missing_sources = [
        row["source"]
        for row in sources
        if not (WORKSPACE / row["source"]).exists()
    ]
    results_text = (
        THESIS_ROOT / "manuscript/chapters/reworked/05-rezultati.tex"
    ).read_text(encoding="utf-8")
    method_text = (
        THESIS_ROOT / "manuscript/chapters/reworked/03-metodologija.tex"
    ).read_text(encoding="utf-8")
    required_results_snippets = [
        r"\subsection{Može li se izvršenje korektno rekonstruisati?}",
        r"\subsection{Da li semantička reprezentacija daje stabilan prostor?}",
        r"\subsection{Otkrivaju li topološki pokazatelji fizičke razlike?}",
        (
            r"\subsection{Prenosi li se postupak na nezavisno "
            r"radno opterećenje?}"
        ),
        "02-controlled-topology-contrasts.pdf",
        "04-stats-full-audit.pdf",
    ]
    required_method_snippets = [
        "09-evidence-lineage.pdf",
        "12-guided-query-sequence.pdf",
        "13-guided-example-pipeline.pdf",
        r"worker\_scan\_rows\_cv\_normalized",
        r"x_C^{(19)}",
        r"u_C^{(4)}",
        r"\phi_+(8000)",
        r"0{,}9295",
    ]
    missing_thesis_snippets = [
        snippet
        for snippet in required_results_snippets
        if snippet not in results_text
    ] + [
        snippet
        for snippet in required_method_snippets
        if snippet not in method_text
    ]
    decision = (
        "GO"
        if (
            not missing
            and not missing_sources
            and not missing_thesis_snippets
            and args.manual_visual_review_confirmed
        )
        else "HOLD"
    )
    manual_status = (
        "PASS" if args.manual_visual_review_confirmed else "PENDING"
    )
    visual_report = f"""# Audit centralnih figura završne reprezentacije

## Odluka

```text
R0 = {decision}
```

- generisani artefakti figura: {len(expected) - len(missing)}/{len(expected)}
- dostupni autoritativni izvori: {len(sources) - len(missing_sources)}/{len(sources)}
- nedostajući obavezni elementi rukopisa: {len(missing_thesis_snippets)}
- ručni vizuelni pregled: {manual_status}
- PDF/SVG i pregledni PNG izvedeni su iz kanonskih CSV ulaza
- Graphviz i PlantUML ostaju izvor za arhitekturu i sekvencijalni tok
- boja je dopunjena oznakama panela, tekstom i brojčanim vrijednostima

## Uslov ručnog pregleda

Tri PNG datoteke moraju biti pregledane u punoj rezoluciji. Završni PDF mora
potvrditi da su natpisi, ose i legende čitljivi i da LaTeX nije odvojio figuru
od njenog tumačenja. Opcija `--manual-visual-review-confirmed` smije se koristiti
tek nakon obje provjere.
"""
    (out_dir / "figure_visual_audit.md").write_text(
        visual_report,
        encoding="utf-8",
    )

    checkpoint_payload = {
        "checkpoint_id": "semantic-v2-thesis-results",
        "created_at_utc": datetime.now(tz=UTC).isoformat(),
        "plan": 27,
        "status": "completed" if decision == "GO" else "hold",
        "gate": "R0",
        "decision": decision,
        "research_freeze": True,
        "infrastructure_used": False,
        "result_structure": [
            "execution_reconstruction",
            "semantic_space_stability",
            "topology_contrasts",
            "external_portability",
        ],
        "guided_example": {
            "reused": True,
            "representation": "x19_semantic_v2",
            "worker_rows_cv_in_model": True,
            "membership_compression_explicit": True,
            "unbounded_ratio_transform_explicit": True,
        },
        "figures": {
            "central_count": 5,
            "appendix_count": 1,
            "generated_supporting_count": 3,
            "missing_artifacts": [repo_relative(path) for path in missing],
            "missing_sources": missing_sources,
            "missing_thesis_snippets": missing_thesis_snippets,
            "manual_visual_review": manual_status.lower(),
        },
        "artifacts": {
            "source_map": repo_relative(out_dir / "results_source_map.csv"),
            "figure_inventory": repo_relative(
                out_dir / "central_figure_inventory.yml"
            ),
            "table_inventory": repo_relative(
                out_dir / "central_table_inventory.yml"
            ),
            "visual_audit": repo_relative(
                out_dir / "figure_visual_audit.md"
            ),
        },
    }
    checkpoint.write_text(
        yaml.safe_dump(checkpoint_payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(out_dir / "figure_visual_audit.md")
    return 0 if decision == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
