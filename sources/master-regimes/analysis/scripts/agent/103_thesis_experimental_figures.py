#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.colors import TwoSlopeNorm
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOCAL_MEMORY_DIR = ROOT / "analysis/reports/dba-local-memory-panel-v1"
DEFAULT_ACTION_AUDIT_DIR = ROOT / "analysis/reports/pressure-raw-v1-mitigation-action-audit"
DEFAULT_FUZZY_MEMORY_DIR = ROOT / "analysis/reports/fuzzy-intervention-memory-v1"
DEFAULT_OUT_DIR = ROOT / "analysis/reports/thesis-experimental-figures"

ACTION_LABELS = {
    "increase_gac_work_mem": "Veći GAC work_mem",
    "regional_topk_candidates": "Regionalni Top-K",
    "mitigate_remote_path_bundle": "Udaljena putanja",
    "use_colocated_distribution": "Kolocirana distribucija",
    "increase_regional_work_mem": "Veći regionalni work_mem",
    "disperse_hot_shards": "Raspored vrućih shardova",
}

ACTION_COLORS = {
    "increase_gac_work_mem": "#7A7A7A",
    "regional_topk_candidates": "#4C78A8",
    "mitigate_remote_path_bundle": "#D55E00",
    "use_colocated_distribution": "#008C95",
    "increase_regional_work_mem": "#CC79A7",
    "disperse_hot_shards": "#7A7A7A",
}

METHOD_COLORS = {
    "static": "#7A7A7A",
    "knn": "#D55E00",
    "kmeans": "#4C78A8",
    "fcm": "#8B6BB1",
    "hierarchical": "#008C95",
}

DECIMAL_COMMA = FuncFormatter(lambda value, _: f"{value:g}".replace(".", ","))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate thesis figures from frozen intervention-memory reports."
    )
    parser.add_argument("--local-memory-dir", type=Path, default=DEFAULT_LOCAL_MEMORY_DIR)
    parser.add_argument("--action-audit-dir", type=Path, default=DEFAULT_ACTION_AUDIT_DIR)
    parser.add_argument("--fuzzy-memory-dir", type=Path, default=DEFAULT_FUZZY_MEMORY_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def _configure_style() -> None:
    font_name = "DejaVu Serif"
    font_candidates = [
        Path.home() / ".local/share/fonts/microsoft-times-new-roman/times.ttf",
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
    ]
    for font_path in font_candidates:
        if font_path.is_file():
            font_manager.fontManager.addfont(font_path)
            font_name = font_manager.FontProperties(fname=font_path).get_name()
            break
    plt.rcParams.update(
        {
            "font.family": font_name,
            "font.size": 10.5,
            "axes.titlesize": 12,
            "axes.labelsize": 10.5,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "figure.dpi": 150,
            "savefig.dpi": 240,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": False,
        }
    )


def _require_columns(frame: pd.DataFrame, columns: set[str], source: Path) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{source} is missing required columns: {missing}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_figure(fig: plt.Figure, out_dir: Path, stem: str) -> list[Path]:
    outputs = [out_dir / f"{stem}.pdf", out_dir / f"{stem}.png"]
    for output in outputs:
        fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return outputs


def plot_intervention_gain_distributions(
    pair_audit_path: Path, out_dir: Path
) -> tuple[list[Path], pd.DataFrame]:
    pairs = pd.read_csv(pair_audit_path, low_memory=False)
    _require_columns(
        pairs,
        {
            "mitigation_action",
            "intervention_role",
            "strict_gain_eligible",
            "target_log2_gain_median",
        },
        pair_audit_path,
    )
    selections = [
        ("use_colocated_distribution", "positive_case", 75),
        ("mitigate_remote_path_bundle", "positive_case", 24),
        ("regional_topk_candidates", "positive_case", 15),
        ("increase_regional_work_mem", "positive_case", 54),
        ("disperse_hot_shards", "positive_case", 49),
    ]
    selected_frames: list[pd.DataFrame] = []
    for action, role, expected_count in selections:
        selected = pairs[
            pairs["mitigation_action"].astype(str).eq(action)
            & pairs["intervention_role"].astype(str).eq(role)
            & pairs["strict_gain_eligible"].astype(str).str.lower().eq("true")
        ].copy()
        if len(selected) != expected_count:
            raise ValueError(
                f"Expected {expected_count} strict {action}/{role} pairs, found {len(selected)}"
            )
        selected["plot_action"] = action
        selected_frames.append(selected)
    plotted = pd.concat(selected_frames, ignore_index=True)
    plotted["target_log2_gain_median"] = pd.to_numeric(
        plotted["target_log2_gain_median"], errors="raise"
    )
    values = [
        plotted.loc[plotted["plot_action"].eq(action), "target_log2_gain_median"].to_numpy(
            dtype=float
        )
        for action, _, _ in selections
    ]

    fig, ax = plt.subplots(figsize=(7.3, 4.35), constrained_layout=True)
    positions = np.arange(len(selections))
    boxplot = ax.boxplot(
        values,
        positions=positions,
        orientation="horizontal",
        widths=0.52,
        whis=(10, 90),
        showfliers=False,
        patch_artist=True,
        medianprops={"color": "#111111", "linewidth": 1.6},
        whiskerprops={"color": "#4B565A", "linewidth": 1.0},
        capprops={"color": "#4B565A", "linewidth": 1.0},
    )
    rng = np.random.default_rng(20260805)
    for position, ((action, _, _), action_values, box) in enumerate(
        zip(selections, values, boxplot["boxes"], strict=True)
    ):
        color = ACTION_COLORS[action]
        box.set_facecolor(color)
        box.set_alpha(0.28)
        jitter = rng.uniform(-0.16, 0.16, len(action_values))
        ax.scatter(
            action_values,
            position + jitter,
            s=13,
            color=color,
            alpha=0.58,
            edgecolors="none",
            zorder=3,
        )
    ax.axvline(0, color="#202629", linewidth=1.0, linestyle="--")
    ax.set_yticks(
        positions,
        [
            f"{ACTION_LABELS[action]}  (n={expected_count})"
            for action, _, expected_count in selections
        ],
    )
    ax.invert_yaxis()
    lower = min(-0.5, min(float(np.min(value)) for value in values) - 0.2)
    upper = max(6.5, max(float(np.max(value)) for value in values) + 0.2)
    ax.set_xlim(lower, upper)
    ax.set_xlabel(r"Dobitak intervencije  $\log_2(T_{prije}/T_{poslije})$")
    ax.set_title("Fizička promjena nije automatski ukupno ubrzanje", loc="left")
    ax.grid(axis="x", color="#D7DDDF", linewidth=0.7, alpha=0.85)

    top = ax.twiny()
    top.set_xlim(ax.get_xlim())
    ticks = np.arange(np.ceil(lower), np.floor(upper) + 1, 1.0)
    top.set_xticks(ticks, [f"{2**tick:.1f}×" if tick < 0 else f"{2**tick:.0f}×" for tick in ticks])
    top.set_xlabel("Približno ubrzanje")
    top.spines["top"].set_visible(True)
    return _write_figure(fig, out_dir, "01-intervention-gain-distributions"), plotted


def plot_final_panel_action_gains(
    outcomes_path: Path, out_dir: Path
) -> tuple[list[Path], pd.DataFrame]:
    outcomes = pd.read_csv(outcomes_path, low_memory=False)
    _require_columns(
        outcomes,
        {
            "episode_order",
            "query_id",
            "region_count",
            "mitigation_action",
            "target_log2_gain",
        },
        outcomes_path,
    )
    actions = [
        "increase_gac_work_mem",
        "regional_topk_candidates",
        "mitigate_remote_path_bundle",
    ]
    outcomes["episode_order"] = pd.to_numeric(outcomes["episode_order"], errors="raise").astype(int)
    outcomes["target_log2_gain"] = pd.to_numeric(outcomes["target_log2_gain"], errors="raise")
    matrix = outcomes.pivot(
        index="mitigation_action", columns="episode_order", values="target_log2_gain"
    ).reindex(index=actions, columns=range(1, 46))
    if matrix.isna().any().any():
        raise ValueError("The final action-gain matrix must be complete (3 actions x 45 states)")

    fig, ax = plt.subplots(figsize=(7.4, 3.85), constrained_layout=True)
    norm = TwoSlopeNorm(vmin=-0.3, vcenter=0.0, vmax=6.0)
    image = ax.imshow(matrix.to_numpy(), aspect="auto", cmap="RdBu_r", norm=norm)
    winners = matrix.to_numpy().argmax(axis=0)
    ax.scatter(
        np.arange(45),
        winners,
        marker="o",
        s=22,
        facecolors="none",
        edgecolors="#111111",
        linewidths=1.0,
    )
    winner_counts = pd.Series(winners).value_counts().to_dict()
    ax.set_yticks(
        np.arange(3),
        [
            f"{ACTION_LABELS[action]}  ({winner_counts.get(index, 0)}/45)"
            for index, action in enumerate(actions)
        ],
    )
    ax.set_xticks(np.arange(0, 45, 5), [str(value) for value in range(1, 46, 5)])
    ax.set_xlabel("Redni broj stanja")
    ax.set_title("Izmjereni dobitak svake akcije kroz završni vremenski panel", loc="left")
    colorbar = fig.colorbar(image, ax=ax, pad=0.02, fraction=0.035)
    colorbar.set_label(r"$\log_2(T_{prije}/T_{poslije})$")

    episode_meta = (
        outcomes[["episode_order", "query_id", "region_count"]]
        .drop_duplicates("episode_order")
        .sort_values("episode_order")
    )
    query_spans = episode_meta.groupby("query_id", sort=False)["episode_order"].agg(["min", "max"])
    top = ax.secondary_xaxis("top")
    top.set_xticks(
        [((row["min"] + row["max"]) / 2.0) - 1.0 for _, row in query_spans.iterrows()],
        [str(query_id).split("_")[0] for query_id in query_spans.index],
        rotation=45,
        ha="left",
    )
    top.set_xlabel("Normalizovani SQL obrazac")
    first_n3 = int(episode_meta.loc[episode_meta["region_count"].eq(3), "episode_order"].min())
    boundary = first_n3 - 1.5
    ax.axvline(boundary, color="#111111", linewidth=1.2, linestyle="--")
    ax.text(
        boundary - 0.35,
        -0.28,
        "N=2",
        ha="right",
        va="center",
        fontsize=8.5,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "pad": 1.2},
    )
    ax.text(
        boundary + 0.35,
        -0.28,
        "N=3",
        ha="left",
        va="center",
        fontsize=8.5,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "pad": 1.2},
    )
    return _write_figure(fig, out_dir, "02-final-panel-action-gains"), outcomes


def _cumulative_mean(values: pd.Series) -> np.ndarray:
    return values.expanding(min_periods=1).mean().to_numpy(dtype=float)


def plot_prequential_learning(
    timeline_path: Path, out_dir: Path
) -> tuple[list[Path], pd.DataFrame]:
    timeline = pd.read_csv(timeline_path, low_memory=False)
    _require_columns(
        timeline,
        {
            "memory_mode",
            "episode_order",
            "region_count",
            "decision_route",
            "predicted_action",
            "actual_best_action",
            "top1_correct",
            "regret_log2",
            "actual_gain__increase_gac_work_mem",
            "actual_gain__regional_topk_candidates",
            "actual_gain__mitigate_remote_path_bundle",
        },
        timeline_path,
    )
    warm = timeline[timeline["memory_mode"].eq("hierarchical_warm_start")].copy()
    warm = warm.sort_values("episode_order").reset_index(drop=True)
    if len(warm) != 45:
        raise ValueError(f"Expected 45 hierarchical warm-start rows, found {len(warm)}")
    warm["predicted_action"] = warm["predicted_action"].fillna("")
    recommended = warm["predicted_action"].ne("")
    top1 = warm["top1_correct"].astype(bool) & recommended
    seen = np.arange(1, len(warm) + 1, dtype=float)
    recommendation_count = recommended.cumsum().to_numpy(dtype=float)
    correct_count = top1.cumsum().to_numpy(dtype=float)
    warm_coverage = recommendation_count / seen
    warm_accuracy = np.divide(
        correct_count,
        recommendation_count,
        out=np.full_like(correct_count, np.nan),
        where=recommendation_count > 0,
    )

    gain_columns = [
        "actual_gain__increase_gac_work_mem",
        "actual_gain__regional_topk_candidates",
        "actual_gain__mitigate_remote_path_bundle",
    ]
    gains = warm[gain_columns].apply(pd.to_numeric, errors="raise")
    static_correct = warm["actual_best_action"].eq("mitigate_remote_path_bundle")
    static_accuracy = static_correct.cumsum().to_numpy(dtype=float) / seen
    static_regret = gains.max(axis=1) - gains["actual_gain__mitigate_remote_path_bundle"]
    warm_regret = pd.to_numeric(warm["regret_log2"], errors="coerce")
    warm_regret_cumulative = _cumulative_mean(warm_regret)
    static_regret_cumulative = _cumulative_mean(static_regret)

    figure_rows = pd.DataFrame(
        {
            "episode_order": warm["episode_order"].astype(int),
            "region_count": warm["region_count"].astype(int),
            "decision_route": warm["decision_route"],
            "recommended": recommended,
            "top1_correct": top1,
            "warm_coverage_cumulative": warm_coverage,
            "warm_top1_cumulative": warm_accuracy,
            "static_top1_cumulative": static_accuracy,
            "warm_regret_cumulative": warm_regret_cumulative,
            "static_regret_cumulative": static_regret_cumulative,
        }
    )

    fig = plt.figure(figsize=(7.4, 5.15), constrained_layout=True)
    grid = fig.add_gridspec(2, 2, height_ratios=[4.0, 1.1])
    ax_quality = fig.add_subplot(grid[0, 0])
    ax_regret = fig.add_subplot(grid[0, 1])
    ax_route = fig.add_subplot(grid[1, :])
    orders = figure_rows["episode_order"].to_numpy(dtype=int)

    ax_quality.plot(
        orders,
        warm_coverage,
        color=METHOD_COLORS["hierarchical"],
        linewidth=1.8,
        linestyle="--",
        label="Pokrivenost hijerarhije",
    )
    ax_quality.plot(
        orders,
        warm_accuracy,
        color=METHOD_COLORS["hierarchical"],
        linewidth=2.1,
        label="Top-1 hijerarhije",
    )
    ax_quality.plot(
        orders,
        static_accuracy,
        color=METHOD_COLORS["static"],
        linewidth=1.7,
        label="Top-1 statičke akcije",
    )
    ax_quality.set_ylim(0.45, 1.02)
    ax_quality.set_ylabel("Kumulativni udio")
    ax_quality.set_xlabel("Obrađena evaluacijska stanja")
    ax_quality.set_title("Kvalitet i pokrivenost", loc="left")
    ax_quality.grid(axis="y", color="#D7DDDF", linewidth=0.7)
    ax_quality.legend(loc="lower right")
    ax_quality.yaxis.set_major_formatter(DECIMAL_COMMA)

    ax_regret.plot(
        orders,
        warm_regret_cumulative,
        color=METHOD_COLORS["hierarchical"],
        linewidth=2.1,
        label="Hijerarhijska memorija",
    )
    ax_regret.plot(
        orders,
        static_regret_cumulative,
        color=METHOD_COLORS["static"],
        linewidth=1.7,
        label="Statička akcija",
    )
    ax_regret.set_ylabel(r"Kumulativni prosječni regret ($\log_2$)")
    ax_regret.set_xlabel("Obrađena evaluacijska stanja")
    ax_regret.set_title("Propušteni dobitak", loc="left")
    ax_regret.grid(axis="y", color="#D7DDDF", linewidth=0.7)
    ax_regret.legend(loc="upper right")
    ax_regret.yaxis.set_major_formatter(DECIMAL_COMMA)

    first_n3 = int(figure_rows.loc[figure_rows["region_count"].eq(3), "episode_order"].min())
    for axis in (ax_quality, ax_regret, ax_route):
        axis.axvline(first_n3 - 0.5, color="#111111", linewidth=1.0, linestyle="--")
    for row in figure_rows.itertuples(index=False):
        if not row.recommended:
            ax_route.scatter(row.episode_order, 0, marker="^", s=38, color="#7A7A7A")
        elif not row.top1_correct:
            ax_route.scatter(row.episode_order, 0, marker="X", s=48, color="#B3261E")
        else:
            color = (
                METHOD_COLORS["knn"]
                if row.decision_route == "cross_query_knn"
                else METHOD_COLORS["kmeans"]
            )
            ax_route.scatter(row.episode_order, 0, marker="o", s=36, color=color)
    ax_route.set_xlim(0.3, 45.7)
    ax_route.set_ylim(-0.6, 0.6)
    ax_route.set_yticks([])
    ax_route.set_xlabel("Redni broj stanja")
    ax_route.set_title("Putanja odluke po stanju", loc="left", fontsize=10.5)
    ax_route.spines["left"].set_visible(False)
    ax_route.spines["bottom"].set_color("#A8B0B3")
    ax_route.legend(
        handles=[
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor=METHOD_COLORS["knn"],
                label="cross-query, tačno",
            ),
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor=METHOD_COLORS["kmeans"],
                label="exact-query, tačno",
            ),
            Line2D(
                [0],
                [0],
                marker="X",
                color="none",
                markerfacecolor="#B3261E",
                markeredgecolor="#B3261E",
                label="pogrešno",
            ),
            Line2D(
                [0],
                [0],
                marker="^",
                color="none",
                markerfacecolor="#7A7A7A",
                markeredgecolor="#7A7A7A",
                label="apstinencija",
            ),
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.40),
        ncol=4,
        frameon=False,
    )
    fig.suptitle(
        "Prequential učenje iz ranijih potpunih evaluacijskih stanja",
        x=0.01,
        ha="left",
    )
    return _write_figure(fig, out_dir, "03-prequential-learning"), figure_rows


def _plot_tradeoff_panel(
    ax: plt.Axes,
    points: pd.DataFrame,
    *,
    title: str,
    xlim: tuple[float, float],
    ylim: tuple[float, float],
) -> None:
    for row in points.itertuples(index=False):
        ax.scatter(
            row.coverage,
            row.mean_regret_log2,
            s=105,
            color=row.color,
            marker=row.marker,
            edgecolor="#202629",
            linewidth=0.6,
            zorder=3,
        )
        ax.annotate(
            f"{row.label}\nTop-1={row.top1_accuracy:.3f}".replace(".", ","),
            (row.coverage, row.mean_regret_log2),
            xytext=row.offset,
            textcoords="offset points",
            fontsize=8.5,
            ha=row.ha,
            va=row.va,
        )
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xlabel("Pokrivenost")
    ax.set_ylabel(r"Prosječni propušteni dobitak ($\log_2$)")
    ax.set_title(title, loc="left")
    ax.grid(color="#D7DDDF", linewidth=0.7)
    ax.xaxis.set_major_formatter(DECIMAL_COMMA)
    ax.yaxis.set_major_formatter(DECIMAL_COMMA)


def plot_method_tradeoff(
    fuzzy_summary_path: Path,
    first_occurrence_path: Path,
    out_dir: Path,
) -> tuple[list[Path], pd.DataFrame]:
    fuzzy = pd.read_csv(fuzzy_summary_path, low_memory=False)
    first = pd.read_csv(first_occurrence_path, low_memory=False)
    _require_columns(
        fuzzy,
        {
            "panel",
            "model",
            "evaluation_scope",
            "coverage",
            "top1_accuracy",
            "mean_regret",
        },
        fuzzy_summary_path,
    )
    _require_columns(
        first,
        {"method", "coverage", "top1_accuracy", "mean_regret_log2"},
        first_occurrence_path,
    )
    development = fuzzy[
        fuzzy["panel"].eq("gac_topk") & fuzzy["evaluation_scope"].eq("own_available")
    ].copy()
    development_mapping: dict[str, tuple[str, str, str, tuple[int, int], str, str]] = {
        "action_median": ("Statički medijan", "static", "o", (4, 7), "left", "bottom"),
        "knn": ("kNN", "knn", "o", (4, -4), "left", "top"),
        "kmeans_hard_memory": ("K-means", "kmeans", "s", (-5, -6), "right", "top"),
        "fcm_soft_memory": ("FCM-PCA", "fcm", "D", (6, 8), "left", "bottom"),
    }
    development = development[development["model"].isin(development_mapping)].copy()
    development["label"] = development["model"].map(lambda value: development_mapping[value][0])
    development["color"] = development["model"].map(
        lambda value: METHOD_COLORS[development_mapping[value][1]]
    )
    development["marker"] = development["model"].map(lambda value: development_mapping[value][2])
    development["offset"] = development["model"].map(lambda value: development_mapping[value][3])
    development["ha"] = development["model"].map(lambda value: development_mapping[value][4])
    development["va"] = development["model"].map(lambda value: development_mapping[value][5])
    development["mean_regret_log2"] = pd.to_numeric(development["mean_regret"], errors="raise")
    development["plot_panel"] = "development_26"

    final_mapping: dict[str, tuple[str, str, str, tuple[int, int], str, str]] = {
        "static_action_median": ("Statička akcija", "static", "o", (-5, 6), "right", "bottom"),
        "knn_cold_start_excluding_same_query": ("kNN cold", "knn", "^", (4, -4), "left", "top"),
        "knn_warm_start_excluding_same_query": (
            "kNN warm",
            "hierarchical",
            "o",
            (-5, -6),
            "right",
            "top",
        ),
    }
    first = first[first["method"].isin(final_mapping)].copy()
    first["label"] = first["method"].map(lambda value: final_mapping[value][0])
    first["color"] = first["method"].map(lambda value: METHOD_COLORS[final_mapping[value][1]])
    first["marker"] = first["method"].map(lambda value: final_mapping[value][2])
    first["offset"] = first["method"].map(lambda value: final_mapping[value][3])
    first["ha"] = first["method"].map(lambda value: final_mapping[value][4])
    first["va"] = first["method"].map(lambda value: final_mapping[value][5])
    first["plot_panel"] = "first_occurrence_15"

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 4.15), constrained_layout=True)
    _plot_tradeoff_panel(
        axes[0],
        development,
        title="Razvojni panel: 26 scenarija",
        xlim=(0.72, 1.02),
        ylim=(0.0, 0.84),
    )
    _plot_tradeoff_panel(
        axes[1],
        first,
        title="Prvo pojavljivanje: 15 SQL obrazaca",
        xlim=(0.68, 1.02),
        ylim=(0.0, 0.44),
    )
    fig.suptitle("Kvalitet procjene mora se čitati zajedno sa pokrivenošću", x=0.01, ha="left")
    plotted = pd.concat(
        [
            development[
                ["plot_panel", "model", "coverage", "top1_accuracy", "mean_regret_log2"]
            ].rename(columns={"model": "method"}),
            first[["plot_panel", "method", "coverage", "top1_accuracy", "mean_regret_log2"]],
        ],
        ignore_index=True,
    )
    return _write_figure(fig, out_dir, "04-method-coverage-regret-tradeoff"), plotted


def main() -> int:
    args = parse_args()
    local_memory_dir = args.local_memory_dir.resolve()
    action_audit_dir = args.action_audit_dir.resolve()
    fuzzy_memory_dir = args.fuzzy_memory_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    _configure_style()

    sources = {
        "mitigation_pair_audit": action_audit_dir / "mitigation_pair_audit.csv",
        "observed_action_outcomes": local_memory_dir / "observed_action_outcomes.csv",
        "hierarchical_policy_timeline": local_memory_dir / "hierarchical_policy_timeline.csv",
        "first_occurrence_comparison": local_memory_dir / "first_occurrence_comparison.csv",
        "prequential_model_summary": fuzzy_memory_dir / "prequential_model_summary.csv",
    }
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing figure source files: {missing}")

    outputs: list[Path] = []
    output_paths, broad_points = plot_intervention_gain_distributions(
        sources["mitigation_pair_audit"], out_dir
    )
    outputs.extend(output_paths)
    broad_points.to_csv(out_dir / "01-intervention-gain-points.csv", index=False)

    output_paths, final_gains = plot_final_panel_action_gains(
        sources["observed_action_outcomes"], out_dir
    )
    outputs.extend(output_paths)
    final_gains.to_csv(out_dir / "02-final-panel-action-gains.csv", index=False)

    output_paths, learning_rows = plot_prequential_learning(
        sources["hierarchical_policy_timeline"], out_dir
    )
    outputs.extend(output_paths)
    learning_rows.to_csv(out_dir / "03-prequential-learning-series.csv", index=False)

    output_paths, method_points = plot_method_tradeoff(
        sources["prequential_model_summary"],
        sources["first_occurrence_comparison"],
        out_dir,
    )
    outputs.extend(output_paths)
    method_points.to_csv(out_dir / "04-method-tradeoff-points.csv", index=False)

    manifest: dict[str, Any] = {
        "contract": "thesis_experimental_figures_v1",
        "source_files": {
            name: {"path": str(path), "sha256": _sha256(path)} for name, path in sources.items()
        },
        "generated_files": [path.name for path in outputs],
        "figure_count": 4,
        "broad_pair_count_plotted": int(len(broad_points)),
        "final_decision_state_count": int(final_gains["episode_order"].nunique()),
        "final_action_episode_count": int(len(final_gains)),
        "prequential_decision_state_count": int(len(learning_rows)),
    }
    (out_dir / "figure_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
