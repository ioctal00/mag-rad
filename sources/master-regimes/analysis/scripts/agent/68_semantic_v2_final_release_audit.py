#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT.parent
THESIS = WORKSPACE / "master-regimes-thesis"
OUT = ROOT / "analysis/reports/semantic-v2-thesis-finalization"
CHECKPOINT = ROOT / "llmcontext/plans/checkpoints/semantic-v2-thesis-release.yml"
CONTRACT = ROOT / "configs/features/feature_semantic_contract_v2.yml"
FREEZE = ROOT / "analysis/reports/semantic-v2-model-freeze"
CONSISTENCY = ROOT / "analysis/reports/semantic-v2-final-consistency"
STATS = ROOT / "analysis/reports/stats-ceb-full-no-refit-v1"
COLLECTOR = (
    ROOT
    / "analysis/reports/collector-correctness-v2/"
    "collector_correctness_summary.json"
)
Q100 = (
    ROOT
    / "analysis/reports/stats-ceb-representation-audit-v1/"
    "q100_feature_distance_audit.csv"
)
THESIS_NUMERIC_AUDIT = (
    ROOT / "analysis/reports/thesis-final-consistency/"
    "numeric_consistency_manifest.json"
)

THESIS_PDF = THESIS / "manuscript/.aux/magistarski-rad.pdf"
THESIS_LOG = THESIS / "manuscript/.aux/magistarski-rad.log"
DEFENSE_PDF = THESIS / "defense/build/odbrana.pdf"
DEFENSE_LOG = THESIS / "defense/build/odbrana.log"

COMMANDS = [
    ("local_reproduction", ROOT, ["make", "thesis-local-reproduction"]),
    ("v2_consistency", ROOT, ["make", "semantic-v2-final-consistency"]),
    ("v2_claims", ROOT, ["make", "semantic-v2-thesis-claims"]),
    (
        "v2_results",
        ROOT,
        [
            "uv",
            "run",
            "python",
            "analysis/scripts/agent/66_semantic_v2_thesis_results_package.py",
            "--manual-visual-review-confirmed",
        ],
    ),
    (
        "v2_appendices_defense",
        ROOT,
        [
            "uv",
            "run",
            "python",
            "analysis/scripts/agent/67_semantic_v2_appendix_defense_audit.py",
            "--manual-visual-review-confirmed",
        ],
    ),
    ("diagrams", THESIS, ["make", "-B", "diagrams"]),
    (
        "thesis_release_build",
        THESIS,
        ["make", "thesis-release-candidate-check"],
    ),
    ("defense_clean", THESIS / "defense", ["make", "clean"]),
    ("defense_build", THESIS, ["make", "defense-check"]),
    (
        "pytest",
        ROOT,
        ["bash", "-lc", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q"],
    ),
    ("ruff", ROOT, ["make", "thesis-lint"]),
    ("diff_master", ROOT, ["git", "diff", "--check"]),
    ("diff_thesis", THESIS, ["git", "diff", "--check"]),
]

SECTIONS = {
    "introduction": THESIS / "manuscript/chapters/01-uvod.tex",
    "method": THESIS / "manuscript/chapters/reworked/03-metodologija.tex",
    "results": THESIS / "manuscript/chapters/reworked/05-rezultati.tex",
    "discussion": (
        THESIS / "manuscript/chapters/reworked/06-diskusija-i-ogranicenja.tex"
    ),
    "conclusion": THESIS / "manuscript/chapters/reworked/07-zakljucak.tex",
}

CLAIMS = [
    (
        "collector",
        "Jedno globalno izvršenje rekonstruiše se kroz više slojeva.",
        "collector_correctness_summary.json",
        "24/24 nije populacijska stopa greške.",
        {
            "introduction": r"povez\w+.*(?:GAC|regional)",
            "method": r"(?:query\\?_run\\?_id|korelacij\w+|korelira te artefakte)",
            "results": r"2603|2\\,603",
            "discussion": r"2603|2\\,603",
            "conclusion": r"auditabiln\w+ opservacij",
        },
    ),
    (
        "rq1_h1",
        "Završni semantički prostor koristi 19 fizički tumačivih pokazatelja.",
        "semantic_v2_model_manifest.yml; consistency_summary.json",
        "Relativan pokazatelj nije automatski ograničen.",
        {
            "introduction": r"19-dimenzional",
            "method": r"semantičk\w+.*19|19.*semantičk",
            "results": r"0[.,]610",
            "discussion": r"19(?:-dimenzional|\s+pokazatelj)",
            "conclusion": r"0[.,]610",
        },
    ),
    (
        "rq2",
        "k=3 je makrostruktura, a k=4 operativna fina rezolucija.",
        "k_summary.csv; k_seed_scores.csv",
        "k=4 nije jedina prirodna niti univerzalna particija.",
        {
            "introduction": r"k=3.*k=4|k=4.*k=3",
            "method": r"fuzzy C-means|FCM",
            "results": r"k=3.*k=4|k=4.*k=3",
            "discussion": r"k=3.*k=4|k=4.*k=3",
            "conclusion": r"k=3.*k=4|k=4.*k=3",
        },
    ),
    (
        "rq3_h2",
        "Fuzzy članstvo čuva sekundarnu pripadnost i neodlučnost.",
        "pressure_uncertainty_summary.csv; algorithm_agreement.csv",
        "Dokaz je slab, interni i konvergentan, bez objektivne nadmoći nad "
        "tvrdim postupcima.",
        {
            "introduction": r"(?:fuzzy|FCM).*prototip",
            "method": r"članstv|pripadnost",
            "results": r"H2.*djelimično podržana.*slab\w+.*intern\w+.*konvergent",
            "discussion": r"konvergent",
            "conclusion": r"H2.*djelimično podržana.*slab\w+.*intern\w+",
        },
    ),
    (
        "h3",
        "No-refit projekcija je ograničeno provjerena izvan korpusa.",
        "full_workload_summary.json; puni STATS-CEB audit",
        "Šesnaest timeouta cenzuriše najskuplji rep workload-a.",
        {
            "introduction": r"pun\w+.*STATS-CEB|STATS-CEB.*pun\w+",
            "method": r"izdvojen\w+.*validacij|bez refit",
            "results": r"130/130|130\}/130",
            "discussion": r"130/130|130\}/130",
            "conclusion": r"130/130|130\}/130",
        },
    ),
    (
        "rq4_h4",
        "Regionalni i worker/task sloj dodaju topološku informaciju.",
        "balanced_skew_summary.csv; controlled_contrast_summary.csv; "
        "full_workload_mapmerge_strata.csv",
        "CV i ISF ne mjere CPU; MapMerge često nema puni worker/task detalj.",
        {
            "introduction": r"865",
            "method": r"(?:ISF|koeficijent varijacije)",
            "results": r"865",
            "discussion": r"865",
            "conclusion": r"(?:radničk|worker/task|worker CV)",
        },
    ),
]

GREP_PATTERNS = {
    "x21": re.compile(r"x(?:_i)?\s*\^\s*\{?\(?21\)?\}?", re.IGNORECASE),
    "final_21": re.compile(
        r"(?:finaln|konačn)[^\n]{0,80}21(?:-|\s)*(?:feature|pokazatelj|dimenz)",
        re.IGNORECASE,
    ),
    "v1_final": re.compile(r"\bV1\b[^\n]{0,50}\bfinal", re.IGNORECASE),
    "universal_taxonomy": re.compile(
        r"universal(?:na|nu|ne)?\s+(?:taxonomy|taksonom)",
        re.IGNORECASE,
    ),
    "pressure_detector": re.compile(
        r"(?:pressure detector|detektor\s+(?:svih\s+)?pritis)",
        re.IGNORECASE,
    ),
    "dominant_cause": re.compile(
        r"(?:dominant cause|dominantn\w+\s+uzrok)",
        re.IGNORECASE,
    ),
    "absolute_home_path": re.compile(r"/home/[A-Za-z0-9_.-]+/"),
    "agent_telemetry": re.compile(
        r"(?:agent telemetry|token usage|utrošeno\s+\d[\d.,]*\s+token)",
        re.IGNORECASE,
    ),
    "todo": re.compile(r"\bTODO\b"),
    "fixme": re.compile(r"\bFIXME\b"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local-only semantic-v2 final release audit."
    )
    parser.add_argument("--out-dir", type=Path, default=OUT)
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--skip-rebuild", action="store_true")
    parser.add_argument("--manual-visual-review-confirmed", action="store_true")
    parser.add_argument("--author-full-read-confirmed", action="store_true")
    parser.add_argument("--administrative-fields-confirmed", action="store_true")
    parser.add_argument("--faculty-rules-confirmed", action="store_true")
    parser.add_argument("--mentor-feedback-reviewed", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def yaml_map(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping in {path}")
    return value


def json_map(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping in {path}")
    return value


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def add_check(
    rows: list[dict[str, Any]],
    check: str,
    passed: bool,
    observed: object,
    expected: object,
    source: str,
) -> None:
    rows.append(
        {
            "check": check,
            "status": "PASS" if passed else "FAIL",
            "observed": observed,
            "expected": expected,
            "source": source,
        }
    )


def run_release_commands() -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    for index, (name, cwd, argv) in enumerate(COMMANDS, start=1):
        print(
            f"[semantic-v2-release] {index}/{len(COMMANDS)} start {name}",
            flush=True,
        )
        started = time.monotonic()
        result = subprocess.run(argv, cwd=cwd, check=False)
        elapsed = time.monotonic() - started
        status = "PASS" if result.returncode == 0 else "FAIL"
        rows.append(
            {
                "step": index,
                "name": name,
                "cwd": str(cwd.relative_to(WORKSPACE)),
                "argv": " ".join(argv),
                "elapsed_seconds": round(elapsed, 3),
                "returncode": result.returncode,
                "status": status,
            }
        )
        print(
            f"[semantic-v2-release] {index}/{len(COMMANDS)} "
            f"{status.lower()} {name} ({elapsed:.1f}s)",
            flush=True,
        )
        if result.returncode:
            return rows, False
    return rows, True


def numeric_audit(out_dir: Path) -> tuple[list[dict[str, Any]], bool]:
    contract = yaml_map(CONTRACT)
    manifest_path = FREEZE / "semantic_v2_model_manifest.yml"
    manifest = yaml_map(manifest_path)
    hashes = json_map(FREEZE / "freeze_sha256.json")
    summary = json_map(CONSISTENCY / "consistency_summary.json")
    holdout = json_map(STATS / "full_workload_summary.json")
    collector = json_map(COLLECTOR)
    thesis_numeric = json_map(THESIS_NUMERIC_AUDIT)
    features = list(contract["features"])
    frozen_features = list(manifest["features"])
    rows: list[dict[str, Any]] = []

    add_check(
        rows,
        "full_thesis_numeric_audit",
        thesis_numeric["status"] == "PASS"
        and thesis_numeric["failure_count"] == 0
        and thesis_numeric["check_count"] >= 39,
        (
            f"status={thesis_numeric['status']}; "
            f"checks={thesis_numeric['check_count']}; "
            f"failures={thesis_numeric['failure_count']}"
        ),
        "status=PASS; checks>=39; failures=0",
        "thesis-final-consistency/numeric_consistency_manifest.json",
    )
    add_check(
        rows,
        "feature_contract_hash",
        sha256(CONTRACT) == hashes["feature_contract_sha256"],
        sha256(CONTRACT),
        hashes["feature_contract_sha256"],
        "feature_semantic_contract_v2.yml; freeze_sha256.json",
    )
    add_check(
        rows,
        "model_manifest_hash",
        sha256(manifest_path) == hashes["manifest_sha256"],
        sha256(manifest_path),
        hashes["manifest_sha256"],
        "semantic_v2_model_manifest.yml; freeze_sha256.json",
    )
    add_check(
        rows,
        "feature_count_and_order",
        features == frozen_features and len(features) == 19,
        f"count={len(features)}; exact_order={features == frozen_features}",
        "count=19; exact_order=True",
        "feature contract; model manifest",
    )
    add_check(
        rows,
        "baseline_scope",
        manifest["row_count"] == 1964,
        manifest["row_count"],
        1964,
        "semantic_v2_model_manifest.yml",
    )
    add_check(
        rows,
        "holdout_no_refit",
        holdout["model_refit_performed"] is False
        and manifest["post_holdout_changes_allowed"] is False,
        (
            f"refit={holdout['model_refit_performed']}; "
            f"post_changes={manifest['post_holdout_changes_allowed']}"
        ),
        "refit=False; post_changes=False",
        "full workload summary; model manifest",
    )
    add_check(
        rows,
        "holdout_hashes",
        holdout["feature_contract_sha256"] == hashes["feature_contract_sha256"]
        and holdout["model_manifest_sha256"] == hashes["manifest_sha256"],
        "contract/model match",
        "contract/model match",
        "full workload summary; freeze hashes",
    )
    add_check(
        rows,
        "promotion",
        summary["all_core_gates_pass"]
        and summary["decision"] == "PROMOTE_V2_WITH_LIMITED_FUZZY_CLAIM",
        summary["decision"],
        "PROMOTE_V2_WITH_LIMITED_FUZZY_CLAIM",
        "consistency_summary.json",
    )
    add_check(
        rows,
        "collector_scope",
        collector["query_count"] == 2603
        and collector["fully_complete_query_count"] == 2603,
        f"{collector['fully_complete_query_count']}/{collector['query_count']}",
        "2603/2603",
        "collector_correctness_summary.json",
    )
    add_check(
        rows,
        "manual_sample",
        collector["manual_correct_link_count"] == 24
        and collector["manual_reviewed_count"] == 24
        and collector["manual_sampling_design"]
        == "deterministic_stratified_not_probability_sample",
        (
            f"{collector['manual_correct_link_count']}/"
            f"{collector['manual_reviewed_count']}; "
            f"{collector['manual_sampling_design']}"
        ),
        "24/24; non-probability sample",
        "collector_correctness_summary.json",
    )

    k = {int(row["k"]): row for row in csv_rows(CONSISTENCY / "k_summary.csv")}
    add_check(
        rows,
        "k3",
        math.isclose(float(k[3]["silhouette_hard_labels"]), 0.606930253688556)
        and math.isclose(float(k[3]["seed_ari_mean"]), 1.0),
        (
            f"silhouette={float(k[3]['silhouette_hard_labels']):.12f}; "
            f"seed_ari={float(k[3]['seed_ari_mean']):.12f}"
        ),
        "0.606930253689; 1.0",
        "k_summary.csv",
    )
    add_check(
        rows,
        "k4",
        math.isclose(float(k[4]["silhouette_hard_labels"]), 0.6095309433990855)
        and math.isclose(
            float(k[4]["modified_partition_coefficient"]),
            0.7783896267552559,
        )
        and math.isclose(float(k[4]["seed_ari_mean"]), 0.8925959119131807),
        (
            f"silhouette={float(k[4]['silhouette_hard_labels']):.12f}; "
            f"MPC={float(k[4]['modified_partition_coefficient']):.12f}; "
            f"seed_ari={float(k[4]['seed_ari_mean']):.12f}"
        ),
        "0.609530943399; 0.778389626755; 0.892595911913",
        "k_summary.csv",
    )

    external = {
        row["dataset"]: row
        for row in csv_rows(CONSISTENCY / "external_projection_summary.csv")
    }
    validation = external["validation_holdout_195"]
    stats = json_map(STATS / "full_workload_summary.json")
    add_check(
        rows,
        "validation_coverage",
        int(validation["v2_within_p99_count"]) == 190
        and int(validation["v2_ood_count"]) == 5,
        (
            f"within={validation['v2_within_p99_count']}; "
            f"ood={validation['v2_ood_count']}"
        ),
        "190; 5",
        "external_projection_summary.csv",
    )
    add_check(
        rows,
        "stats_full_no_refit",
        int(stats["selected_queries"]) == 146
        and int(stats["completed_result_comparisons"]) == 132
        and int(stats["result_mismatch_count"]) == 0
        and int(stats["completed_queries"]) == 130
        and int(stats["k4_within_frozen_p99"]) == 130
        and int(stats["v1_within_frozen_p99"]) == 89
        and math.isclose(
            float(stats["k4_max_membership_median"]),
            0.36522827054511453,
        ),
        (
            f"attempted={stats['selected_queries']}; "
            f"compared={stats['completed_result_comparisons']}; "
            f"mismatch={stats['result_mismatch_count']}; "
            f"complete={stats['completed_queries']}; "
            f"final={stats['k4_within_frozen_p99']}/130; "
            f"baseline={stats['v1_within_frozen_p99']}/130; "
            f"median={float(stats['k4_max_membership_median']):.12f}"
        ),
        (
            "attempted=146; compared=132; mismatch=0; complete=130; "
            "final=130/130; baseline=89/130; median=0.365228270545"
        ),
        "full_workload_summary.json",
    )

    repeatability = csv_rows(CONSISTENCY / "repeatability_summary.csv")[0]
    add_check(
        rows,
        "repeatability",
        int(repeatability["condition_count"]) == 96
        and int(repeatability["row_count"]) == 328
        and math.isclose(
            float(repeatability["p95_mean_feature_l2"]),
            0.00111756276465445,
        )
        and math.isclose(
            float(repeatability["p95_mean_membership_l1"]),
            0.00010042481231334376,
        )
        and math.isclose(
            float(repeatability["minimum_dominant_cluster_agreement"]),
            1.0,
        ),
        (
            f"{repeatability['condition_count']} conditions; "
            f"{repeatability['row_count']} rows; "
            f"feature_p95={repeatability['p95_mean_feature_l2']}; "
            f"membership_p95={repeatability['p95_mean_membership_l1']}; "
            f"agreement={repeatability['minimum_dominant_cluster_agreement']}"
        ),
        "96; 328; feature_p95=0.001117562765; "
        "membership_p95=0.000100424812; 1.0",
        "repeatability_summary.csv",
    )
    drf = next(
        row for row in csv_rows(Q100) if row["feature"] == "drf_bytes_proxy"
    )
    add_check(
        rows,
        "q100_drf",
        math.isclose(float(drf["q100_raw_value"]), 1805590.0)
        and math.isclose(
            float(drf["squared_distance_share"]),
            0.8660952101136259,
        ),
        (
            f"raw={float(drf['q100_raw_value']):.0f}; "
            f"share={float(drf['squared_distance_share']):.12f}"
        ),
        "1805590; 0.866095210114",
        "q100_feature_distance_audit.csv",
    )

    write_csv(out_dir / "final_numeric_checks.csv", rows)
    status = all(row["status"] == "PASS" for row in rows)
    lines = [
        "# Završni numerički audit",
        "",
        f"- Status: **{'PASS' if status else 'FAIL'}**",
        f"- Provjere: {len(rows)}",
        "- Novi SQL runovi: **ne**",
        "- Refit prema holdoutu: **ne**",
        "",
        "| Provjera | Status | Opaženo | Izvor |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{row['check']}` | {row['status']} | {row['observed']} | "
        f"`{row['source']}` |"
        for row in rows
    )
    lines.append("")
    (out_dir / "final_numeric_audit.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    return rows, status


def first_match(path: Path, pattern: str) -> int | None:
    compiled = re.compile(pattern, re.IGNORECASE | re.DOTALL)
    lines = path.read_text(encoding="utf-8").splitlines()
    for index in range(len(lines)):
        if compiled.search(" ".join(lines[index : index + 5])):
            return index + 1
    return None


def claim_matrix(out_dir: Path) -> tuple[list[dict[str, Any]], bool]:
    rows = []
    for claim_id, claim, source, boundary, patterns in CLAIMS:
        row: dict[str, Any] = {"claim_id": claim_id, "claim": claim}
        passed = True
        for section, path in SECTIONS.items():
            line = first_match(path, patterns[section])
            passed = passed and line is not None
            row[section] = (
                f"PASS:{path.relative_to(THESIS)}:{line}"
                if line is not None
                else f"FAIL:{path.relative_to(THESIS)}"
            )
        row.update(
            {
                "authoritative_source": source,
                "boundary": boundary,
                "status": "PASS" if passed else "FAIL",
            }
        )
        rows.append(row)
    write_csv(out_dir / "final_consistency_matrix.csv", rows)
    return rows, all(row["status"] == "PASS" for row in rows)


def active_tex() -> list[Path]:
    manuscript = THESIS / "manuscript"
    pending = [manuscript / "magistarski-rad.tex"]
    result: list[Path] = []
    seen: set[Path] = set()
    pattern = re.compile(r"\\input\{([^}]+)\}")
    while pending:
        path = pending.pop(0).resolve()
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
        for raw in pattern.findall(path.read_text(encoding="utf-8")):
            candidate = (manuscript / raw).with_suffix(".tex").resolve()
            if candidate.exists():
                pending.append(candidate)
    return result


def semantic_grep(out_dir: Path) -> tuple[list[dict[str, Any]], bool]:
    paths = [
        *active_tex(),
        THESIS / "defense/odbrana.tex",
        THESIS / "figures/semantic-v2/README.md",
    ]
    rows = []
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            context = " ".join(
                lines[max(0, line_number - 2) : min(len(lines), line_number + 2)]
            ).lower()
            for finding, pattern in GREP_PATTERNS.items():
                if not pattern.search(line):
                    continue
                justified = False
                reason = ""
                if finding in {"x21", "final_21", "v1_final"} and any(
                    marker in context
                    for marker in (
                        "v1",
                        "ranij",
                        "baseline",
                        "razvojn",
                        "istorij",
                        "prethod",
                    )
                ):
                    justified = True
                    reason = "empirijski baseline zadržan samo u ablaciji"
                if finding in {
                    "universal_taxonomy",
                    "pressure_detector",
                    "dominant_cause",
                } and any(
                    marker in context
                    for marker in (
                        "nije",
                        "ne ",
                        "not ",
                        "does not",
                        "without claiming",
                    )
                ):
                    justified = True
                    reason = "eksplicitna granica tvrdnje"
                rows.append(
                    {
                        "finding": finding,
                        "file": str(path.relative_to(WORKSPACE)),
                        "line": line_number,
                        "status": "PASS" if justified else "FAIL",
                        "justification": reason,
                        "context": line.strip(),
                    }
                )
    write_csv(out_dir / "final_semantic_grep.csv", rows)
    return rows, all(row["status"] == "PASS" for row in rows)


def output(*argv: str) -> str:
    return subprocess.run(
        argv,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def pdfinfo(path: Path) -> dict[str, str]:
    return {
        key.strip(): value.strip()
        for line in output("pdfinfo", str(path)).splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
    }


def unembedded_fonts(path: Path) -> list[str]:
    lines = output("pdffonts", str(path)).splitlines()
    header = lines[0]
    emb, sub, type_start = (
        header.index("emb"),
        header.index("sub"),
        header.index("type"),
    )
    return [
        line[:type_start].strip()
        for line in lines[2:]
        if len(line) > emb and line[emb:sub].strip() == "no"
    ]


def visual_audit(
    out_dir: Path,
    manual_confirmed: bool,
) -> tuple[list[dict[str, Any]], bool]:
    thesis = pdfinfo(THESIS_PDF)
    defense = pdfinfo(DEFENSE_PDF)
    fonts = unembedded_fonts(THESIS_PDF) + unembedded_fonts(DEFENSE_PDF)
    overfull_thesis = len(
        re.findall(
            r"Overfull \\[hv]box",
            THESIS_LOG.read_text(encoding="utf-8", errors="replace"),
        )
    )
    overfull_defense = len(
        re.findall(
            r"Overfull \\[hv]box",
            DEFENSE_LOG.read_text(encoding="utf-8", errors="replace"),
        )
    )
    rows: list[dict[str, Any]] = []
    add_check(
        rows,
        "thesis_pdf",
        int(thesis.get("Pages", "0")) > 0
        and "(A4)" in thesis.get("Page size", ""),
        f"{thesis.get('Pages')} pages; {thesis.get('Page size')}",
        "non-empty A4",
        "thesis PDF",
    )
    add_check(
        rows,
        "defense_pdf",
        12 <= int(defense.get("Pages", "0")) <= 18,
        f"{defense.get('Pages')} slides",
        "12..18",
        "defense PDF",
    )
    add_check(
        rows,
        "metadata",
        all(thesis.get(key) for key in ("Title", "Author", "Subject", "Keywords")),
        "Title, Author, Subject, Keywords populated",
        "all populated",
        "pdfinfo",
    )
    add_check(
        rows,
        "fonts",
        not fonts,
        "all embedded" if not fonts else ", ".join(fonts),
        "all embedded",
        "pdffonts",
    )
    add_check(
        rows,
        "overfull",
        overfull_thesis == 0 and overfull_defense == 0,
        f"thesis={overfull_thesis}; defense={overfull_defense}",
        "0; 0",
        "LaTeX logs",
    )
    add_check(
        rows,
        "manual_visual_review",
        manual_confirmed,
        manual_confirmed,
        True,
        "normal and grayscale contact sheets",
    )
    write_csv(out_dir / "final_visual_checks.csv", rows)
    status = all(row["status"] == "PASS" for row in rows)
    lines = [
        "# Završni vizuelni audit",
        "",
        f"- Status: **{'PASS' if status else 'HOLD'}**",
        f"- Rukopis: {thesis.get('Pages')} stranice",
        f"- Odbrana: {defense.get('Pages')} slajdova",
        f"- Neugrađeni fontovi: {len(fonts)}",
        f"- Overfull elementi: {overfull_thesis + overfull_defense}",
        (
            "- Ručni pregled normalnog i crno-bijelog prikaza: "
            f"**{'PASS' if manual_confirmed else 'PENDING'}**"
        ),
        "",
        "| Provjera | Status | Opaženo |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| `{row['check']}` | {row['status']} | {row['observed']} |"
        for row in rows
    )
    lines.append("")
    (out_dir / "final_visual_audit.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    return rows, status


def placeholders() -> list[dict[str, Any]]:
    rows = []
    for path in [
        THESIS / "manuscript/naslovna.tex",
        THESIS / "manuscript/preliminarne/bibliografska-kartica.tex",
    ]:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if "Naknadno unijeti" in line:
                rows.append(
                    {
                        "file": str(path.relative_to(WORKSPACE)),
                        "line": line_number,
                        "text": line.strip(),
                    }
                )
    return rows


def release_checklist(
    out_dir: Path,
    args: argparse.Namespace,
    automatic_checks: list[tuple[str, bool, str]],
) -> tuple[str, bool]:
    open_fields = placeholders()
    author_checks = [
        (
            "author_full_read",
            args.author_full_read_confirmed,
            "autor pročitao cijeli PDF redom",
        ),
        (
            "administrative_fields",
            args.administrative_fields_confirmed and not open_fields,
            f"imena/datumi/komisija potvrđeni; placeholders={len(open_fields)}",
        ),
        (
            "faculty_rules",
            args.faculty_rules_confirmed,
            "potvrđeni aktuelni fakultetski i PDF/A zahtjevi",
        ),
        (
            "mentor_feedback",
            args.mentor_feedback_reviewed,
            "pregledana aktuelna mentorska povratna informacija",
        ),
    ]
    rows = [
        {
            "scope": "automatic",
            "item": item,
            "status": "PASS" if passed else "FAIL",
            "requirement": requirement,
        }
        for item, passed, requirement in automatic_checks
    ]
    rows.extend(
        {
            "scope": "author",
            "item": item,
            "status": "PASS" if passed else "PENDING",
            "requirement": requirement,
        }
        for item, passed, requirement in author_checks
    )
    automatic_pass = all(passed for _, passed, _ in automatic_checks)
    author_pass = all(passed for _, passed, _ in author_checks)
    decision = (
        "HOLD_TECHNICAL"
        if not automatic_pass
        else "RELEASE_CANDIDATE"
        if author_pass
        else "HOLD_AUTHOR_REVIEW"
    )
    write_csv(out_dir / "release_candidate_checks.csv", rows)
    lines = [
        "# Release-candidate kontrolna lista",
        "",
        f"- Automatski tehnički gate: **{'GO' if automatic_pass else 'HOLD'}**",
        f"- Autorov gate: **{'GO' if author_pass else 'PENDING'}**",
        f"- Odluka F2: **{decision}**",
        "- Formalna predaja: **nije izvršena ovim auditom**",
        "",
        "| Scope | Stavka | Status | Uslov |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {row['scope']} | `{row['item']}` | {row['status']} | "
        f"{row['requirement']} |"
        for row in rows
    )
    if open_fields:
        lines.extend(["", "## Otvorena administrativna mjesta", ""])
        lines.extend(
            f"- `{row['file']}:{row['line']}` - `{row['text']}`"
            for row in open_fields
        )
    lines.extend(
        [
            "",
            "`RELEASE_CANDIDATE` nije isto što i formalna predaja. Autorove",
            "potvrde se ne izvode iz automatskog ili agentskog pregleda.",
            "",
        ]
    )
    (out_dir / "release_candidate_checklist.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    return decision, automatic_pass


def git_head(path: Path) -> str:
    return output("git", "-C", str(path), "rev-parse", "HEAD").strip()


def load_release_commands(path: Path) -> tuple[list[dict[str, Any]], bool]:
    if not path.exists():
        raise SystemExit(
            "--skip-rebuild zahtijeva postojeći final_release_commands.csv"
        )
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(
            "--skip-rebuild ne može koristiti prazan final_release_commands.csv"
        )
    for row in rows:
        row["step"] = int(row["step"])
        row["elapsed_seconds"] = float(row["elapsed_seconds"])
        row["returncode"] = int(row["returncode"])
    return rows, all(row["status"] == "PASS" for row in rows)


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    if args.skip_rebuild:
        command_rows, commands_pass = load_release_commands(
            args.out_dir / "final_release_commands.csv"
        )
    else:
        command_rows, commands_pass = run_release_commands()
    write_csv(args.out_dir / "final_release_commands.csv", command_rows)

    numeric_rows, numeric_pass = numeric_audit(args.out_dir)
    matrix_rows, matrix_pass = claim_matrix(args.out_dir)
    semantic_rows, semantic_pass = semantic_grep(args.out_dir)
    visual_rows, visual_pass = visual_audit(
        args.out_dir,
        args.manual_visual_review_confirmed,
    )
    d0 = yaml_map(
        ROOT / "llmcontext/plans/checkpoints/semantic-v2-thesis-defense.yml"
    )
    formal = json_map(
        THESIS / "manuscript/build/formal-requirements-audit.json"
    )
    decision, automatic_pass = release_checklist(
        args.out_dir,
        args,
        [
            ("release_commands", commands_pass, "sve lokalne komande prolaze"),
            ("numeric_audit", numeric_pass, "hashovi i centralne brojke prolaze"),
            ("claim_matrix", matrix_pass, "tvrdnje ostaju ograničene kroz rad"),
            ("semantic_grep", semantic_pass, "svi pogoci opravdani"),
            ("visual_audit", visual_pass, "PDF i vizuelni pregled prolaze"),
            ("plan28", d0["decision"] == "GO", "D0 = GO"),
            ("formal_audit", formal["status"] == "PASS", "formalni audit prolazi"),
        ],
    )

    checkpoint = {
        "checkpoint_id": "semantic-v2-thesis-release",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "plan": 29,
        "status": "completed",
        "gate": "F2",
        "decision": decision,
        "automatic_gate": "GO" if automatic_pass else "HOLD",
        "research_freeze": True,
        "infrastructure_used": False,
        "new_sql_runs": False,
        "model_refit": False,
        "audit": {
            "commands_passed": sum(row["status"] == "PASS" for row in command_rows),
            "commands_total": len(command_rows),
            "numeric_passed": sum(row["status"] == "PASS" for row in numeric_rows),
            "numeric_total": len(numeric_rows),
            "claim_rows_passed": sum(row["status"] == "PASS" for row in matrix_rows),
            "claim_rows_total": len(matrix_rows),
            "semantic_failures": sum(row["status"] == "FAIL" for row in semantic_rows),
            "visual_passed": sum(row["status"] == "PASS" for row in visual_rows),
            "visual_total": len(visual_rows),
        },
        "artifacts": {
            "consistency_matrix": (
                "master-regimes/analysis/reports/"
                "semantic-v2-thesis-finalization/final_consistency_matrix.csv"
            ),
            "numeric_audit": (
                "master-regimes/analysis/reports/"
                "semantic-v2-thesis-finalization/final_numeric_audit.md"
            ),
            "visual_audit": (
                "master-regimes/analysis/reports/"
                "semantic-v2-thesis-finalization/final_visual_audit.md"
            ),
            "release_checklist": (
                "master-regimes/analysis/reports/"
                "semantic-v2-thesis-finalization/release_candidate_checklist.md"
            ),
        },
    }
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    args.checkpoint.write_text(
        yaml.safe_dump(checkpoint, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    verification_elapsed = time.monotonic() - started
    manifest = {
        "release_audit_id": "semantic-v2-thesis-release-v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": (
            sum(float(row["elapsed_seconds"]) for row in command_rows)
            if args.skip_rebuild
            else verification_elapsed
        ),
        "verification_elapsed_seconds": verification_elapsed,
        "command_manifest_reused": args.skip_rebuild,
        "decision": decision,
        "automatic_gate": checkpoint["automatic_gate"],
        "infrastructure_used": False,
        "new_sql_runs": False,
        "model_refit": False,
        "commands": command_rows,
        "repository_heads": {
            "master-regimes": git_head(ROOT),
            "master-regimes-thesis": git_head(THESIS),
        },
        "frozen_hashes": json_map(FREEZE / "freeze_sha256.json"),
        "outputs": {
            "thesis_pdf_sha256": sha256(THESIS_PDF),
            "defense_pdf_sha256": sha256(DEFENSE_PDF),
        },
    }
    (args.out_dir / "final_release_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[semantic-v2-release] automatic_gate={checkpoint['automatic_gate']}")
    print(f"[semantic-v2-release] F2={decision}")
    print(args.checkpoint)
    return 0 if automatic_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
