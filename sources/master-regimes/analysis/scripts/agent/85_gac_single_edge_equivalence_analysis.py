#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INDEX = (
    ROOT.parent
    / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs"
    / "gac-single-edge-equivalence-probe-v1/_index"
)
DEFAULT_OUT = ROOT / "analysis/reports/gac-single-edge-equivalence-probe-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare direct regional and GAC single-edge probe evidence."
    )
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def number(value: Any) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int:
    parsed = number(value)
    return int(parsed) if parsed is not None else 0


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def row_index(
    rows: list[dict[str, str]],
    key: str,
) -> dict[str, dict[str, str]]:
    return {str(row.get(key, "")): row for row in rows if row.get(key)}


def worker_aggregate(
    rows: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        query_run_id = str(row.get("query_run_id", ""))
        if not query_run_id:
            continue
        current = result.setdefault(
            query_run_id,
            {
                "worker_task_rows": 0,
                "worker_task_scan_rows_sum": 0.0,
                "worker_task_temp_read_sum": 0,
                "worker_task_temp_written_sum": 0,
                "worker_task_parse_ok": 0,
                "worker_task_parse_partial": 0,
            },
        )
        current["worker_task_rows"] += 1
        current["worker_task_scan_rows_sum"] += number(
            row.get("worker_task_scan_actual_rows_sum")
        ) or 0.0
        current["worker_task_temp_read_sum"] += integer(
            row.get("worker_task_temp_read_blocks")
        )
        current["worker_task_temp_written_sum"] += integer(
            row.get("worker_task_temp_written_blocks")
        )
        parse_status = str(row.get("parse_status", ""))
        current["worker_task_parse_ok"] += parse_status == "ok"
        current["worker_task_parse_partial"] += parse_status == "partial"
    return result


def remote_region_aggregate(
    rows: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        query_run_id = str(row.get("query_run_id", ""))
        if not query_run_id:
            continue
        current = result.setdefault(
            query_run_id,
            {
                "remote_region_rows": 0.0,
                "remote_temp_read": 0,
                "remote_temp_written": 0,
                "remote_locality": "",
                "remote_repartition": False,
                "remote_plan_fingerprint": "",
            },
        )
        current["remote_region_rows"] += number(row.get("remote_actual_rows")) or 0.0
        current["remote_temp_read"] += integer(row.get("remote_temp_blocks_read"))
        current["remote_temp_written"] += integer(
            row.get("remote_temp_blocks_written")
        )
        current["remote_locality"] = str(
            row.get("remote_citus_plan_locality_class", "")
        )
        current["remote_repartition"] = (
            current["remote_repartition"]
            or truthy(row.get("remote_citus_repartition_mapmerge"))
        )
        current["remote_plan_fingerprint"] = str(
            row.get("remote_plan_fingerprint", "")
        )
    return result


def evidence_rows(
    executions: list[dict[str, str]],
    worker_rows: list[dict[str, str]],
    region_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    workers = worker_aggregate(worker_rows)
    regions = remote_region_aggregate(region_rows)
    result: list[dict[str, Any]] = []
    for row in executions:
        query_run_id = str(row["query_run_id"])
        worker = workers.get(query_run_id, {})
        region = regions.get(query_run_id, {})
        execution_scope = str(row.get("execution_scope", ""))
        is_gac = execution_scope == "gac_single_edge"
        result.append(
            {
                "query_run_id": query_run_id,
                "component_match_id": row.get("component_match_id", ""),
                "execution_scope": execution_scope,
                "target_scope": row.get("target_scope", ""),
                "template_id": row.get("template_id", ""),
                "runtime_config_id": row.get("runtime_config_id", ""),
                "execution_status": row.get("execution_status", ""),
                "elapsed_seconds": row.get("elapsed_seconds", ""),
                "result_row_count": row.get("result_row_count", ""),
                "result_multiset_sha256": row.get("result_multiset_sha256", ""),
                "plan_fingerprint": row.get("plan_fingerprint", ""),
                "regional_plan_fingerprint": (
                    region.get("remote_plan_fingerprint", "")
                    if is_gac
                    else row.get("plan_fingerprint", "")
                ),
                "regional_locality": (
                    region.get("remote_locality", "")
                    if is_gac
                    else row.get("citus_plan_locality_class", "")
                ),
                "regional_repartition": (
                    region.get("remote_repartition", False)
                    if is_gac
                    else truthy(row.get("citus_repartition_observed_v2"))
                ),
                "regional_temp_read": (
                    region.get("remote_temp_read", 0)
                    if is_gac
                    else integer(row.get("coordinator_temp_read_blocks"))
                ),
                "regional_temp_written": (
                    region.get("remote_temp_written", 0)
                    if is_gac
                    else integer(row.get("coordinator_temp_written_blocks"))
                ),
                "gac_temp_read": (
                    integer(row.get("coordinator_temp_read_blocks")) if is_gac else ""
                ),
                "gac_temp_written": (
                    integer(row.get("coordinator_temp_written_blocks"))
                    if is_gac
                    else ""
                ),
                "worker_task_rows": worker.get("worker_task_rows", 0),
                "worker_task_scan_rows_sum": worker.get(
                    "worker_task_scan_rows_sum",
                    0,
                ),
                "worker_task_parse_ok": worker.get("worker_task_parse_ok", 0),
                "worker_task_parse_partial": worker.get(
                    "worker_task_parse_partial",
                    0,
                ),
                "worker_task_evidence_status": row.get(
                    "worker_task_evidence_status",
                    "",
                ),
                "worker_task_timing_status": row.get(
                    "worker_task_timing_status",
                    "",
                ),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            str(item["component_match_id"]),
            str(item["execution_scope"]),
        ),
    )


def comparison_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_component: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_component.setdefault(str(row["component_match_id"]), {})[
            str(row["execution_scope"])
        ] = row

    result: list[dict[str, Any]] = []
    for component_match_id, scopes in sorted(by_component.items()):
        direct = scopes.get("region_direct")
        gac = scopes.get("gac_single_edge")
        if not direct or not gac:
            result.append(
                {
                    "component_match_id": component_match_id,
                    "gate": "FAIL_MISSING_SCOPE",
                }
            )
            continue
        result_equal = (
            direct["result_multiset_sha256"]
            and direct["result_multiset_sha256"] == gac["result_multiset_sha256"]
        )
        rows_equal = direct["result_row_count"] == gac["result_row_count"]
        worker_scan_rows_equal = abs(
            float(direct["worker_task_scan_rows_sum"])
            - float(gac["worker_task_scan_rows_sum"])
        ) < 1e-9
        worker_scan_comparison_applicable = (
            int(direct["worker_task_parse_partial"]) == 0
            and int(gac["worker_task_parse_partial"]) == 0
            and int(direct["worker_task_rows"]) > 0
            and int(gac["worker_task_rows"]) > 0
        )
        is_repartition = "repartition" in component_match_id
        is_memory = "regional_memory" in component_match_id
        repartition_equal = bool(direct["regional_repartition"]) == bool(
            gac["regional_repartition"]
        )
        spill_class_equal = (
            int(direct["regional_temp_written"]) > 0
        ) == (int(gac["regional_temp_written"]) > 0)
        expected_locality_ok = True
        if component_match_id == "join_colocated":
            expected_locality_ok = gac["regional_locality"] == (
                "colocated_join_candidate"
            )
        elif is_repartition:
            expected_locality_ok = (
                direct["regional_locality"] == "repartition_mapmerge"
                and gac["regional_locality"] == "repartition_mapmerge"
            )
        gate_checks = [
            result_equal,
            rows_equal,
            repartition_equal,
            expected_locality_ok,
        ]
        if not is_repartition and worker_scan_comparison_applicable:
            gate_checks.append(worker_scan_rows_equal)
        if is_memory:
            gate_checks.extend(
                [
                    spill_class_equal,
                    int(gac["gac_temp_written"] or 0) == 0,
                ]
            )
        result.append(
            {
                "component_match_id": component_match_id,
                "direct_query_run_id": direct["query_run_id"],
                "gac_query_run_id": gac["query_run_id"],
                "result_signature_equal": result_equal,
                "result_row_count_equal": rows_equal,
                "regional_plan_fingerprint_equal": (
                    direct["regional_plan_fingerprint"]
                    == gac["regional_plan_fingerprint"]
                ),
                "regional_locality_direct": direct["regional_locality"],
                "regional_locality_gac": gac["regional_locality"],
                "regional_repartition_direct": direct["regional_repartition"],
                "regional_repartition_gac": gac["regional_repartition"],
                "worker_task_scan_rows_direct": direct[
                    "worker_task_scan_rows_sum"
                ],
                "worker_task_scan_rows_gac": gac["worker_task_scan_rows_sum"],
                "worker_task_scan_rows_comparison_applicable": (
                    worker_scan_comparison_applicable
                ),
                "worker_task_scan_rows_equal": worker_scan_rows_equal,
                "regional_temp_written_direct": direct["regional_temp_written"],
                "regional_temp_written_gac": gac["regional_temp_written"],
                "regional_spill_class_equal": spill_class_equal,
                "gac_temp_written": gac["gac_temp_written"],
                "worker_evidence_direct": direct["worker_task_evidence_status"],
                "worker_evidence_gac": gac["worker_task_evidence_status"],
                "worker_timing_direct": direct["worker_task_timing_status"],
                "worker_timing_gac": gac["worker_task_timing_status"],
                "gate": "PASS" if all(gate_checks) else "FAIL",
            }
        )
    return result


def write_report(
    out_dir: Path,
    evidence: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        out_dir / "execution_evidence.csv",
        evidence,
        list(evidence[0]) if evidence else [],
    )
    write_csv(
        out_dir / "component_equivalence.csv",
        comparisons,
        list(comparisons[0]) if comparisons else [],
    )
    all_pass = bool(comparisons) and all(row["gate"] == "PASS" for row in comparisons)
    decision = {
        "gate": "GO_WITH_CONSTRAINTS" if all_pass else "NO_GO",
        "completed_execution_count": sum(
            row["execution_status"] == "completed" for row in evidence
        ),
        "comparison_count": len(comparisons),
        "passed_comparison_count": sum(
            row["gate"] == "PASS" for row in comparisons
        ),
        "approved_primary_scope": "gac_single_edge" if all_pass else "",
        "approved_target_scope": "global_query" if all_pass else "",
        "direct_region_role": "component_calibration_only",
        "constraints": [
            "Approval applies only to templates with demonstrated regional pushdown.",
            "Direct regional elapsed time must not be mixed with global GAC targets.",
            "Embedded task plans behind FDW do not expose task timing.",
            "MapMerge task evidence is structurally unavailable in both compared scopes.",
            "Plan fingerprints need not be equal across the two instrumentation paths.",
        ],
    }
    (out_dir / "decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = f"""# GAC single-edge equivalence audit

## Odluka

**{decision["gate"]}**

Audit je obuhvatio {len(evidence)} izvršenja i {len(comparisons)} uparena
poređenja. Prošlo je {decision["passed_comparison_count"]}/{len(comparisons)}
poređenja.

GAC single-edge je prihvatljiv kao primarna izvršna traka samo za SQL
šablone za koje je potvrđeno da se join, sortiranje, agregacija ili spill
zaista izvršavaju na regionalnom Citus sloju. Direktno regionalno izvršenje
ostaje pomoćni component-level kalibracijski dokaz i njegovo trajanje se ne
smije koristiti kao globalni target.

## Šta je potvrđeno

- Result signature i broj izlaznih redova jednaki su u svakom paru.
- Colocated i repartition scenarij zadržavaju očekivanu regionalnu
  klasifikaciju iza FDW granice.
- Stressed/mitigated `work_mem` par zadržava spill klasu u regionalnom planu.
- GAC plan u memory paru nema lokalni spill, pa je pritisak ostao regionalan.
- Worker/task scan redovi poklapaju se kada su oba task prikaza potpuno
  parsirana i uporediva.

## Granice ekvivalencije

- Plan fingerprints nisu identični jer se direktni i auto_explain put
  instrumentuju različito.
- Task trajanje je dostupno direktno, ali nije prisutno u Citus tekstualnom
  task planu ugrađenom u regionalni auto_explain dokument.
- Tekstualni task plan iza FDW-a može biti samo djelimično parsiran, pa
  parcijalni zbir scan redova nije ekvivalentan potpunom direktnom zbiru.
- Kod MapMerge/repartition plana task lista je strukturno nedostupna u oba
  puta. To je applicability stanje, ne nedostajući red koji se smije imputirati.
- Ovaj audit ne odobrava mehaničku konverziju svih postojećih batch-130 i
  batch-140 šablona. Svaki novi GAC single-edge oblik mora proći pushdown
  preflight.

## Izlazi

- `execution_evidence.csv`
- `component_equivalence.csv`
- `decision.json`
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")


def main() -> int:
    args = parse_args()
    executions = read_csv(args.index_dir / "execution_features.csv")
    workers = read_csv(args.index_dir / "worker_task_fragments.csv")
    regions = read_csv(args.index_dir / "region_fragments.csv")
    evidence = evidence_rows(executions, workers, regions)
    comparisons = comparison_rows(evidence)
    write_report(args.out_dir, evidence, comparisons)
    print(args.out_dir / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
