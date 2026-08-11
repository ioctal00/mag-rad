#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = ROOT / "sources" / "master-regimes"
INFRA_ROOT = ROOT / "sources" / "master-regimes-infra"
CATALOG_PATH = ROOT / "config" / "corpora.json"


def load_catalog() -> dict[str, dict[str, Any]]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def corpus_spec(corpus_id: str) -> dict[str, Any]:
    catalog = load_catalog()
    if corpus_id not in catalog:
        choices = ", ".join(sorted(catalog))
        raise SystemExit(f"Nepoznat corpus '{corpus_id}'. Dostupno: {choices}")
    return catalog[corpus_id]


def run(command: list[str], *, cwd: Path) -> None:
    display = " ".join(command)
    print(f"[workflow] cwd={cwd}", flush=True)
    print(f"[workflow] $ {display}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def resolved(path: str) -> Path:
    value = ROOT / path
    if not value.exists():
        raise SystemExit(f"Nedostaje: {value}")
    return value.resolve()


def rendered_plan(corpus_id: str, spec: dict[str, Any], fresh: bool) -> Path:
    if fresh:
        candidate = (
            EXPERIMENT_ROOT
            / "generated"
            / "corpus"
            / str(spec["rendered_corpus_id"])
        )
        candidate /= "corpus_execution_plan.yml"
        if not candidate.exists():
            raise SystemExit(
                f"Svjezi plan ne postoji: {candidate}. Prvo pokrenuti render."
            )
        return candidate.resolve()
    return resolved(str(spec["frozen_plan"]))


def stage_frozen_corpora(*, skip: str | None = None) -> None:
    destination_root = EXPERIMENT_ROOT / "generated" / "corpus"
    destination_root.mkdir(parents=True, exist_ok=True)
    staged = 0
    for spec in load_catalog().values():
        rendered_id = str(spec["rendered_corpus_id"])
        if rendered_id == skip:
            continue
        source = (ROOT / str(spec["frozen_plan"])).resolve().parent
        destination = destination_root / rendered_id
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        staged += 1
    print(
        f"[workflow] staged frozen corpora={staged} destination={destination_root}",
        flush=True,
    )


def action_list() -> None:
    print("CORPUS                                      ROLE")
    for corpus_id, spec in load_catalog().items():
        print(f"{corpus_id:<43} {spec['role']}")


def action_validate(corpus_id: str, spec: dict[str, Any]) -> None:
    manifest = spec.get("manifest")
    if not manifest:
        print(
            f"[workflow] {corpus_id} koristi zamrznuti izvedeni plan; "
            "nema samostalan source manifest."
        )
        return
    run(
        [
            "uv",
            "run",
            "master-regimes",
            "validate-corpus",
            "--manifest",
            str(resolved(str(manifest))),
        ],
        cwd=EXPERIMENT_ROOT,
    )


def action_render(corpus_id: str, spec: dict[str, Any]) -> None:
    manifest = spec.get("manifest")
    if not manifest:
        raise SystemExit(
            f"{corpus_id} je izvedeni plan. Koristiti frozen plan iz artifacts/."
        )
    out_dir = (
        EXPERIMENT_ROOT
        / "generated"
        / "corpus"
        / str(spec["rendered_corpus_id"])
    )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run(
        [
            "uv",
            "run",
            "master-regimes",
            "render-corpus",
            "--manifest",
            str(resolved(str(manifest))),
            "--out",
            str(out_dir.resolve()),
        ],
        cwd=EXPERIMENT_ROOT,
    )


def action_prepare(corpus_id: str, spec: dict[str, Any]) -> None:
    target = spec.get("prepare_target")
    if not target:
        print(
            f"[workflow] {corpus_id}: dataset load i FDW/ETL bootstrap "
            "izvrsava corpus runner po segmentu.",
            flush=True,
        )
        return
    run(
        [
            "make",
            str(target),
            f"STATS_CEB_PROFILE={resolved(str(spec['prepare_profile']))}",
            f"STATS_CEB_SELECTION={resolved(str(spec['prepare_selection']))}",
            f"STATS_CEB_PREPARE_LABEL={corpus_id}-reproduction-prepare",
        ],
        cwd=INFRA_ROOT,
    )


def make_corpus_run(
    *,
    corpus_id: str,
    spec: dict[str, Any],
    dry_run: bool,
    execute: bool,
    fresh_plan: bool,
    group_id: str | None,
    max_groups: int | None,
    max_instances_per_group: int | None,
) -> None:
    stage_frozen_corpora(
        skip=str(spec["rendered_corpus_id"]) if fresh_plan else None
    )
    if spec["runner"] == "confirmatory_skew":
        if dry_run:
            raise SystemExit(
                "Confirmatory B/C eksperiment nema genericki dry-run: placement "
                "intervencija se izvodi posebnim runnerom. Koristiti objavljeni "
                "frozen plan i docs/02-corpus-execution.md."
            )
        if not execute:
            raise SystemExit("Cloud izvrsavanje zahtijeva eksplicitni --execute.")
        run(
            [
                "make",
                "confirmatory-skew-experiment",
                f"CONFIRMATORY_SKEW_CONFIG={resolved(str(spec['manifest']))}",
                f"CONFIRMATORY_SKEW_PLAN={rendered_plan(corpus_id, spec, fresh_plan)}",
                "CONFIRMATORY_SKEW_CHECKPOINT="
                + str(
                    resolved(
                        "sources/master-regimes/configs/validation/"
                        "confirmatory-skew-v1-capability-smoke.yml"
                    )
                ),
            ],
            cwd=INFRA_ROOT,
        )
        return

    if not dry_run and not execute:
        raise SystemExit("Cloud izvrsavanje zahtijeva eksplicitni --execute.")

    label = (
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{spec['logical_run_id']}-reproduction"
    )
    command = [
        "make",
        "eu-us-gac-vps-corpus-run",
        f"CORPUS_EXECUTION_PLAN={rendered_plan(corpus_id, spec, fresh_plan)}",
        f"CORPUS_RUN_LABEL={label}",
        f"CORPUS_LOGICAL_RUN_ID={spec['logical_run_id']}",
        f"CORPUS_RUN_DRY_RUN={'true' if dry_run else 'false'}",
    ]
    if group_id:
        command.append(f"CORPUS_RUN_GROUP_ID={group_id}")
    if max_groups is not None:
        command.append(f"CORPUS_RUN_MAX_GROUPS={max_groups}")
    effective_max_instances = (
        max_instances_per_group
        if max_instances_per_group is not None
        else spec.get("default_max_instances_per_group")
    )
    if effective_max_instances is not None:
        command.append(
            f"CORPUS_RUN_MAX_INSTANCES_PER_GROUP={effective_max_instances}"
        )
    run(command, cwd=INFRA_ROOT)


def action_index(spec: dict[str, Any]) -> None:
    if spec["runner"] != "corpus":
        raise SystemExit(
            "Confirmatory experiment koristi vlastiti _logical izlaz i analysis paket."
        )
    run(
        [
            "make",
            "corpus-run-index",
            f"CORPUS_LOGICAL_RUN_ID={spec['logical_run_id']}",
        ],
        cwd=INFRA_ROOT,
    )


def logical_index(spec: dict[str, Any]) -> Path:
    corpus_id = str(spec["logical_run_id"])
    live = (
        INFRA_ROOT
        / "generated"
        / "runs"
        / "corpus-sweeps"
        / "_logical-runs"
        / corpus_id
        / "_index"
    )
    if live.exists():
        return live
    extracted = ROOT / "work" / "logical-runs" / corpus_id / "_index"
    if extracted.exists():
        return extracted
    raise SystemExit(
        "Logical index nije dostupan. Pokrenuti `make extract-indexes` ili "
        "izvrsiti i indeksirati corpus."
    )


def action_features(corpus_id: str, spec: dict[str, Any]) -> None:
    if spec["runner"] != "corpus":
        raise SystemExit(
            "Confirmatory feature matrica je vec ukljucena u artifacts/features/."
        )
    out_dir = ROOT / "work" / "features" / corpus_id
    out_dir.mkdir(parents=True, exist_ok=True)
    run(
        [
            "uv",
            "run",
            "master-regimes",
            "build-feature-matrix",
            "--index-dir",
            str(logical_index(spec)),
            "--out",
            str(out_dir.resolve()),
            "--topology",
            "multi_region",
        ],
        cwd=EXPERIMENT_ROOT,
    )


def action_rerun_plan(corpus_id: str, spec: dict[str, Any]) -> None:
    if spec["runner"] != "corpus":
        raise SystemExit("Confirmatory eksperiment ima vlastiti attempt ledger.")
    logical_run_id = str(spec["logical_run_id"])
    stage_frozen_corpora()
    out_dir = ROOT / "work" / "rerun-plans" / corpus_id
    out_dir.mkdir(parents=True, exist_ok=True)
    run(
        [
            "make",
            "corpus-rerun-plan",
            f"CORPUS_EXECUTION_PLAN={rendered_plan(corpus_id, spec, False)}",
            f"CORPUS_LOGICAL_RUN_ID={logical_run_id}",
            f"CORPUS_RERUN_PLAN_OUT={out_dir.resolve()}",
            "CORPUS_RERUN_STATUSES=timeout,failed,missing,interrupted",
        ],
        cwd=INFRA_ROOT,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kurirani corpus workflow bez narativnih report generatora."
    )
    parser.add_argument(
        "action",
        choices=(
            "list",
            "validate",
            "render",
            "stage",
            "prepare",
            "dry-run",
            "run",
            "index",
            "rerun-plan",
            "features",
        ),
    )
    parser.add_argument("--corpus", default="clean-run-v1")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--fresh-plan", action="store_true")
    parser.add_argument("--group-id")
    parser.add_argument("--max-groups", type=int)
    parser.add_argument("--max-instances-per-group", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.action == "list":
        action_list()
        return 0
    spec = corpus_spec(args.corpus)
    if args.action == "validate":
        action_validate(args.corpus, spec)
    elif args.action == "render":
        action_render(args.corpus, spec)
    elif args.action == "stage":
        stage_frozen_corpora()
    elif args.action == "prepare":
        action_prepare(args.corpus, spec)
    elif args.action in {"dry-run", "run"}:
        make_corpus_run(
            corpus_id=args.corpus,
            spec=spec,
            dry_run=args.action == "dry-run",
            execute=args.execute,
            fresh_plan=args.fresh_plan,
            group_id=args.group_id,
            max_groups=args.max_groups,
            max_instances_per_group=args.max_instances_per_group,
        )
    elif args.action == "index":
        action_index(spec)
    elif args.action == "rerun-plan":
        action_rerun_plan(args.corpus, spec)
    elif args.action == "features":
        action_features(args.corpus, spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
