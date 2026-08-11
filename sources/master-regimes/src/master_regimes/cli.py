from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .clustering_dataset import prepare_clustering_dataset
from .corpus_adapter import render_corpus
from .corpus_manifest import validate_corpus_manifest
from .dataset_profile import validate_dataset_profile
from .extract.analytics_client_index import index_analytics_fdw_run
from .extract.explain_json import extract_plan_nodes
from .extract.query_sweep_index import index_query_sweep
from .feature_matrix import build_feature_matrix
from .run_manifest import create_run_manifest
from .stats_ceb import (
    prepare_full_selection,
    prepare_holdout_selection,
    run_admission_gate,
)
from .workload import render_workload

ROOT = Path(__file__).resolve().parents[2]


def _cmd_doctor(_: argparse.Namespace) -> int:
    print(f"repo_root={ROOT}")
    print(f"python={sys.version.split()[0]}")
    print(f"uv={shutil.which('uv') or 'missing'}")
    return 0


def _cmd_init_run(args: argparse.Namespace) -> int:
    run_dir = create_run_manifest(
        root=ROOT,
        system_path=args.system,
        dataset_path=args.dataset,
        sweep_path=args.sweep,
        output_root=args.out,
        run_id=args.run_id,
    )
    print(run_dir)
    return 0


def _cmd_render_workload(args: argparse.Namespace) -> int:
    manifest = render_workload(
        registry_path=args.registry,
        output_dir=args.out,
        max_instances=args.max_instances,
    )
    print(manifest)
    return 0


def _cmd_render_corpus(args: argparse.Namespace) -> int:
    include_execution_classes = {
        value.strip()
        for value in str(args.include_execution_class).split(",")
        if value.strip()
    }
    if "all" in include_execution_classes:
        include_execution_classes = set()
    plan = render_corpus(
        manifest_path=args.manifest,
        output_dir=args.out,
        max_instances_per_cell=args.max_instances_per_cell,
        region=args.region,
        include_execution_classes=include_execution_classes,
    )
    print(plan)
    return 0


def _cmd_extract_plan(args: argparse.Namespace) -> int:
    output = extract_plan_nodes(input_path=args.input, output_path=args.output)
    print(output)
    return 0


def _cmd_index_query_sweep(args: argparse.Namespace) -> int:
    output = index_query_sweep(sweep_dir=args.sweep_dir, out_dir=args.out_dir)
    print(output)
    return 0


def _cmd_index_analytics_fdw(args: argparse.Namespace) -> int:
    output = index_analytics_fdw_run(run_dir=args.run_dir, out_dir=args.out_dir)
    print(output)
    return 0


def _cmd_build_feature_matrix(args: argparse.Namespace) -> int:
    output = build_feature_matrix(
        index_dir=args.index_dir,
        out_dir=args.out_dir,
        schema_path=args.schema,
        topology=args.topology,
    )
    print(output)
    return 0


def _cmd_prepare_clustering_dataset(args: argparse.Namespace) -> int:
    output = prepare_clustering_dataset(
        features_dir=args.features_dir,
        out_dir=args.out_dir,
        max_null_fraction=args.max_null_fraction,
        min_non_null=args.min_non_null,
        add_missing_indicators=not args.no_missing_indicators,
        log_transform=args.log_transform,
    )
    print(output)
    return 0


def _cmd_validate_corpus(args: argparse.Namespace) -> int:
    result = validate_corpus_manifest(args.manifest)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


def _cmd_validate_dataset_profile(args: argparse.Namespace) -> int:
    result = validate_dataset_profile(
        args.profile,
        audit_path=args.audit,
        region=args.region,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


def _cmd_stats_ceb_admission(args: argparse.Namespace) -> int:
    output = run_admission_gate(
        source_lock_path=args.source_lock,
        selection_path=args.selection,
        cache_dir=args.cache,
        out_dir=args.out,
    )
    decision = json.loads((output / "go_no_go.json").read_text(encoding="utf-8"))
    print(output)
    return 0 if decision["decision"] == "GO" else 1


def _cmd_stats_ceb_prepare_holdout(args: argparse.Namespace) -> int:
    quotas: dict[int, int] = {}
    for item in str(args.table_count_quotas).split(","):
        table_count, separator, quota = item.strip().partition(":")
        if not separator:
            raise ValueError(f"Invalid table-count quota {item!r}")
        quotas[int(table_count)] = int(quota)
    output = prepare_holdout_selection(
        source_lock_path=args.source_lock,
        development_selection_path=args.development_selection,
        cache_dir=args.cache,
        selection_path=args.selection,
        selected_query_dir=args.selected_query_dir,
        fragments_dir=args.fragments_dir,
        seed=args.seed,
        table_count_quotas=quotas,
        excluded_selection_paths=args.exclude_selection,
        selection_id=args.selection_id,
    )
    print(output)
    return 0


def _cmd_stats_ceb_prepare_full(args: argparse.Namespace) -> int:
    output = prepare_full_selection(
        source_lock_path=args.source_lock,
        development_selection_path=args.development_selection,
        cache_dir=args.cache,
        selection_path=args.selection,
        selected_query_dir=args.selected_query_dir,
        fragments_dir=args.fragments_dir,
        selection_id=args.selection_id,
    )
    print(output)
    return 0


def _cmd_not_ready(args: argparse.Namespace) -> int:
    print(f"{args.command} is a scaffold command; implement it after smoke artifacts exist.")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="master-regimes")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check local tool availability.")
    doctor.set_defaults(func=_cmd_doctor)

    init_run = sub.add_parser("init-run", help="Create a run directory and run_manifest.yml.")
    init_run.add_argument("--system", type=Path, required=True)
    init_run.add_argument("--dataset", type=Path, required=True)
    init_run.add_argument("--sweep", type=Path, required=True)
    init_run.add_argument("--out", type=Path, default=Path("runs"))
    init_run.add_argument("--run-id", default="")
    init_run.set_defaults(func=_cmd_init_run)

    render = sub.add_parser("render-workload", help="Render SQL templates from registry.yml.")
    render.add_argument("--registry", type=Path, required=True)
    render.add_argument("--out", type=Path, required=True)
    render.add_argument("--max-instances", type=int, default=None)
    render.set_defaults(func=_cmd_render_workload)

    render_corpus_cmd = sub.add_parser(
        "render-corpus",
        help="Render a controlled corpus manifest into infra execution sweep configs.",
    )
    render_corpus_cmd.add_argument("--manifest", type=Path, required=True)
    render_corpus_cmd.add_argument("--out", type=Path, required=True)
    render_corpus_cmd.add_argument("--max-instances-per-cell", type=int, default=None)
    render_corpus_cmd.add_argument("--region", default="eu")
    render_corpus_cmd.add_argument(
        "--include-execution-class",
        default="pilot",
        help="Comma-separated execution_class values to render; default: pilot.",
    )
    render_corpus_cmd.set_defaults(func=_cmd_render_corpus)

    extract = sub.add_parser("extract-plan", help="Flatten one EXPLAIN FORMAT JSON file.")
    extract.add_argument("--input", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)
    extract.set_defaults(func=_cmd_extract_plan)

    index_query = sub.add_parser(
        "index-query-sweep",
        help="Build normalized CSV indexes for one query-sweep artifact directory.",
    )
    index_query.add_argument("--sweep-dir", type=Path, required=True)
    index_query.add_argument("--out-dir", type=Path, default=None)
    index_query.set_defaults(func=_cmd_index_query_sweep)

    index_analytics = sub.add_parser(
        "index-analytics-fdw",
        help="Build normalized CSV indexes for one analytics-client FDW run.",
    )
    index_analytics.add_argument("--run-dir", type=Path, required=True)
    index_analytics.add_argument("--out-dir", type=Path, default=None)
    index_analytics.set_defaults(func=_cmd_index_analytics_fdw)

    build_matrix = sub.add_parser(
        "build-feature-matrix",
        help="Build M0/M1 model matrices and context tables from a normalized _index.",
    )
    build_matrix.add_argument("--index-dir", type=Path, required=True)
    build_matrix.add_argument("--out-dir", type=Path, default=None)
    build_matrix.add_argument("--schema", type=Path, default=None)
    build_matrix.add_argument(
        "--topology",
        default="eu_only",
        choices=("eu_only", "eu_us", "multi_region"),
    )
    build_matrix.set_defaults(func=_cmd_build_feature_matrix)

    clustering_dataset = sub.add_parser(
        "prepare-clustering-dataset",
        help="Apply row/feature quality gates and scaling to feature matrices.",
    )
    clustering_dataset.add_argument("--features-dir", type=Path, required=True)
    clustering_dataset.add_argument("--out-dir", type=Path, default=None)
    clustering_dataset.add_argument("--max-null-fraction", type=float, default=0.8)
    clustering_dataset.add_argument("--min-non-null", type=int, default=2)
    clustering_dataset.add_argument("--no-missing-indicators", action="store_true")
    clustering_dataset.add_argument(
        "--log-transform",
        default="auto",
        choices=("auto", "off"),
    )
    clustering_dataset.set_defaults(func=_cmd_prepare_clustering_dataset)

    validate_corpus = sub.add_parser(
        "validate-corpus",
        help="Validate a controlled corpus manifest against workload/query-group metadata.",
    )
    validate_corpus.add_argument("--manifest", type=Path, required=True)
    validate_corpus.set_defaults(func=_cmd_validate_corpus)

    validate_dataset = sub.add_parser(
        "validate-dataset-profile",
        help="Validate a dataset profile contract and optional capability_audit.json.",
    )
    validate_dataset.add_argument("--profile", type=Path, required=True)
    validate_dataset.add_argument("--audit", type=Path, default=None)
    validate_dataset.add_argument("--region", default="eu")
    validate_dataset.set_defaults(func=_cmd_validate_dataset_profile)

    stats_ceb = sub.add_parser(
        "stats-ceb-admission",
        help="Verify pinned STATS-CEB sources and preregistered pilot queries.",
    )
    stats_ceb.add_argument("--source-lock", type=Path, required=True)
    stats_ceb.add_argument("--selection", type=Path, required=True)
    stats_ceb.add_argument("--cache", type=Path, required=True)
    stats_ceb.add_argument("--out", type=Path, required=True)
    stats_ceb.set_defaults(func=_cmd_stats_ceb_admission)

    stats_ceb_holdout = sub.add_parser(
        "stats-ceb-prepare-holdout",
        help="Materialize a deterministic outcome-blind STATS-CEB holdout.",
    )
    stats_ceb_holdout.add_argument("--source-lock", type=Path, required=True)
    stats_ceb_holdout.add_argument(
        "--development-selection",
        type=Path,
        required=True,
    )
    stats_ceb_holdout.add_argument(
        "--exclude-selection",
        type=Path,
        action="append",
        default=[],
        help="Additional previously observed selection to exclude; repeatable.",
    )
    stats_ceb_holdout.add_argument("--cache", type=Path, required=True)
    stats_ceb_holdout.add_argument("--selection", type=Path, required=True)
    stats_ceb_holdout.add_argument("--selected-query-dir", type=Path, required=True)
    stats_ceb_holdout.add_argument("--fragments-dir", type=Path, required=True)
    stats_ceb_holdout.add_argument(
        "--seed",
        default="stats-ceb-semantic-v2-holdout",
    )
    stats_ceb_holdout.add_argument(
        "--selection-id",
        default="stats-ceb-semantic-v2-holdout",
    )
    stats_ceb_holdout.add_argument(
        "--table-count-quotas",
        default="2:2,3:3,4:3,5:2,6:2",
    )
    stats_ceb_holdout.set_defaults(func=_cmd_stats_ceb_prepare_holdout)

    stats_ceb_full = sub.add_parser(
        "stats-ceb-prepare-full",
        help="Materialize the complete pinned STATS-CEB workload.",
    )
    stats_ceb_full.add_argument("--source-lock", type=Path, required=True)
    stats_ceb_full.add_argument(
        "--development-selection",
        type=Path,
        required=True,
    )
    stats_ceb_full.add_argument("--cache", type=Path, required=True)
    stats_ceb_full.add_argument("--selection", type=Path, required=True)
    stats_ceb_full.add_argument("--selected-query-dir", type=Path, required=True)
    stats_ceb_full.add_argument("--fragments-dir", type=Path, required=True)
    stats_ceb_full.add_argument(
        "--selection-id",
        default="stats-ceb-full-no-refit-v1",
    )
    stats_ceb_full.set_defaults(func=_cmd_stats_ceb_prepare_full)

    for name in ("run-sweep", "extract", "cluster", "report"):
        command = sub.add_parser(name)
        command.set_defaults(func=_cmd_not_ready)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
