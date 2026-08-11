#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT.parent
THESIS_ROOT = WORKSPACE / "master-regimes-thesis"
OUT_DIR = ROOT / "analysis/reports/semantic-v2-thesis-finalization"
CHECKPOINT = ROOT / "llmcontext/plans/checkpoints/semantic-v2-thesis-defense.yml"
R0_CHECKPOINT = ROOT / "llmcontext/plans/checkpoints/semantic-v2-thesis-results.yml"
CONTRACT = ROOT / "configs/features/feature_semantic_contract_v2.yml"
MODEL_MANIFEST = (
    ROOT
    / "analysis/reports/semantic-v2-model-freeze/semantic_v2_model_manifest.yml"
)
FINAL_REPORT = ROOT / "analysis/reports/semantic-v2-final-consistency"
V2B_REPORT = ROOT / "analysis/reports/stats-ceb-semantic-v2b-holdout"
SOURCE_LOCK = ROOT / "external/stats-ceb/source-lock.yml"

ACTIVE_TEX = [
    THESIS_ROOT / "manuscript/magistarski-rad.tex",
    THESIS_ROOT / "manuscript/naslovna.tex",
    *sorted((THESIS_ROOT / "manuscript/preliminarne").glob("*.tex")),
    THESIS_ROOT / "manuscript/chapters/01-uvod.tex",
    *sorted((THESIS_ROOT / "manuscript/chapters/reworked").glob("*.tex")),
    *sorted((THESIS_ROOT / "manuscript/appendices").glob("*.tex")),
    *sorted((THESIS_ROOT / "tables").glob("*/*.tex")),
    THESIS_ROOT / "defense/odbrana.tex",
]

TERM_RULES = {
    "OOD": re.compile(
        r"out-of-distribution[^\n]{0,30}(?:-|--)\s*OOD",
        re.IGNORECASE,
    ),
    "FCM": re.compile(r"fuzzy\s+C-means\s*\(FCM\)", re.IGNORECASE),
    "DRF": re.compile(
        r"data reduction factor[^\n]{0,30}(?:-|--)\s*DRF",
        re.IGNORECASE,
    ),
    "ISF": re.compile(
        r"intermediate skew factor[^\n]{0,30}(?:-|--)\s*ISF",
        re.IGNORECASE,
    ),
    "CV": re.compile(
        r"coefficient of variation[^\n]{0,30}(?:-|--)\s*CV",
        re.IGNORECASE,
    ),
    "ARI": re.compile(
        r"adjusted Rand index[^\n]{0,30}(?:-|--)\s*ARI",
        re.IGNORECASE,
    ),
    "NMI": re.compile(
        r"normalized mutual information[^\n]{0,30}(?:-|--)\s*NMI",
        re.IGNORECASE,
    ),
    "MPC": re.compile(
        r"modified partition coefficient[^\n]{0,30}(?:-|--)\s*MPC",
        re.IGNORECASE,
    ),
    "XB": re.compile(
        r"Xie--Beni[^\n]{0,30}\\?\(XB\\?\)",
        re.IGNORECASE,
    ),
}

PRIVACY_RULES = {
    "absolute_local_path": re.compile(r"/home/[^\\s}\\],]+"),
    "private_ipv4": re.compile(
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
    ),
    "unicode_double_quote": re.compile(r"[“”]"),
    "em_dash": re.compile("—"),
    "predikcija": re.compile(r"\bpredikc\w*", re.IGNORECASE),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Plan 28 appendix, reproducibility and defense alignment."
        )
    )
    parser.add_argument(
        "--manual-visual-review-confirmed",
        action="store_true",
        help="Confirm manual visual review of the thesis and defense PDFs.",
    )
    return parser.parse_args()


def repo_relative(path: Path) -> str:
    return str(path.resolve().relative_to(WORKSPACE.resolve()))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state(path: Path) -> dict[str, Any]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {
        "repository": path.name,
        "head_at_audit": head,
        "working_tree_dirty": bool(status),
        "changed_path_count": len(status),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def quality_class(
    frame: pd.DataFrame,
    membership_threshold: float,
    margin_threshold: float,
    entropy_threshold: float,
) -> np.ndarray:
    membership_ok = frame["max_membership"].to_numpy() >= membership_threshold
    margin_ok = frame["top2_margin"].to_numpy() >= margin_threshold
    entropy_ok = frame["membership_entropy"].to_numpy() < entropy_threshold
    result = np.full(len(frame), "mixed_boundary", dtype=object)
    result[membership_ok & margin_ok & entropy_ok] = "clear_prototype"
    result[~membership_ok & ~margin_ok & ~entropy_ok] = (
        "weak_prototype_coverage"
    )
    return result


def threshold_sensitivity() -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.read_csv(FINAL_REPORT / "baseline_memberships.csv")
    baseline = quality_class(frame, 0.50, 0.15, 1.05)
    rows: list[dict[str, Any]] = []
    for membership in (0.40, 0.45, 0.50, 0.55, 0.60):
        for margin in (0.05, 0.10, 0.15, 0.20, 0.25):
            for entropy in (0.90, 0.975, 1.05, 1.125, 1.20):
                labels = quality_class(frame, membership, margin, entropy)
                counts = pd.Series(labels).value_counts()
                rows.append(
                    {
                        "membership_threshold": membership,
                        "margin_threshold": margin,
                        "entropy_threshold": entropy,
                        "clear_share": counts.get("clear_prototype", 0)
                        / len(frame),
                        "mixed_share": counts.get("mixed_boundary", 0)
                        / len(frame),
                        "weak_coverage_share": counts.get(
                            "weak_prototype_coverage", 0
                        )
                        / len(frame),
                        "agreement_with_baseline": float(
                            np.mean(labels == baseline)
                        ),
                    }
                )
    grid = pd.DataFrame(rows)
    policies = [
        ("liberal", 0.40, 0.05, 1.20),
        ("moderately_liberal", 0.45, 0.10, 1.125),
        ("baseline", 0.50, 0.15, 1.05),
        ("moderately_conservative", 0.55, 0.20, 0.975),
        ("conservative", 0.60, 0.25, 0.90),
    ]
    selected: list[dict[str, Any]] = []
    for name, membership, margin, entropy in policies:
        row = grid[
            grid["membership_threshold"].eq(membership)
            & grid["margin_threshold"].eq(margin)
            & grid["entropy_threshold"].eq(entropy)
        ].iloc[0]
        selected.append({"policy": name, **row.to_dict()})
    return grid, pd.DataFrame(selected)


def membership_quality_table() -> tuple[pd.DataFrame, str]:
    frame = pd.read_csv(FINAL_REPORT / "baseline_memberships.csv")
    frame["quality_class"] = quality_class(frame, 0.50, 0.15, 1.05)
    order = [
        "clear_prototype",
        "mixed_boundary",
        "weak_prototype_coverage",
    ]
    labels = {
        "clear_prototype": "Jasan prototip",
        "mixed_boundary": "Mješovit/granični slučaj",
        "weak_prototype_coverage": "Slaba prototipska pokrivenost",
    }
    rows = []
    for quality in order:
        selected = frame[frame["quality_class"].eq(quality)]
        rows.append(
            {
                "quality_class": quality,
                "label": labels[quality],
                "count": len(selected),
                "share": len(selected) / len(frame),
                "average_max_membership": selected["max_membership"].mean(),
                "average_top2_margin": selected["top2_margin"].mean(),
            }
        )
    summary = pd.DataFrame(rows)
    table_lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Raspodjela kvaliteta fuzzy pripadnosti u glavnom korpusu}",
        r"\label{tab:rq3-membership-quality}",
        r"\small",
        r"\renewcommand{\arraystretch}{1.12}",
        r"\begin{tabularx}{\textwidth}{L{0.38\textwidth}rrrr}",
        r"\toprule",
        (
            r"\textbf{Kategorija} & \textbf{Broj} & \textbf{Udio} & "
            r"\textbf{Prosj. maksimum} & \textbf{Prosj. top-2} \\"
        ),
        r"\midrule",
    ]
    for row in rows:
        table_lines.append(
            f"{row['label']} & {row['count']} & "
            f"{100 * row['share']:.1f}\\% & "
            f"{row['average_max_membership']:.3f} & "
            f"{row['average_top2_margin']:.3f} \\\\"
        )
    table_lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
            r"\end{table}",
            "",
        ]
    )
    return summary, "\n".join(table_lines)


def collision_rows() -> pd.DataFrame:
    audit = pd.read_csv(V2B_REPORT / "holdout_compression_audit.csv")
    collisions = audit[audit["row_count"].gt(1)].copy()
    if len(collisions) != 1:
        raise ValueError(f"Expected one V2 collision group, got {len(collisions)}")
    projection = pd.read_csv(V2B_REPORT / "holdout_projection.csv")
    projection = projection[projection["k"].eq(4)].copy()
    query_ids = {
        int(value)
        for value in str(collisions.iloc[0]["query_ids"]).split(",")
    }
    selected = projection[projection["query_id"].isin(query_ids)].copy()
    if len(selected) != 3:
        raise ValueError("Expected q22/q80/q121 in the collision group")
    selected.insert(0, "rounded_vector_hash", collisions.iloc[0]["rounded_vector_hash"])
    return selected[
        [
            "rounded_vector_hash",
            "query_id",
            "max_membership",
            "top2_membership_margin",
            "plan_fingerprint",
            "remote_plan_fingerprint",
        ]
    ].sort_values("query_id")


def appendix_map(feature_names: list[str]) -> dict[str, Any]:
    return {
        "plan": 28,
        "reading_layers": {
            "main_text": (
                "problem, method, central evidence, guided example and limits"
            ),
            "appendices": (
                "formulas, complete validation, collector contracts and cases"
            ),
            "repository": "machine-readable sources, scripts and manifests",
        },
        "appendices": [
            {
                "appendix": "A",
                "source": (
                    "master-regimes-thesis/manuscript/appendices/"
                    "appendix-a-pokazatelji.tex"
                ),
                "purpose": "complete semantic V2 contract for 19 features",
                "feature_count": len(feature_names),
                "features": feature_names,
                "supporting_table": (
                    "master-regimes-thesis/tables/semantic-v2/"
                    "01-feature-contract.tex"
                ),
            },
            {
                "appendix": "B",
                "source": (
                    "master-regimes-thesis/manuscript/appendices/"
                    "appendix-b-validacija.tex"
                ),
                "purpose": (
                    "k=2..8, ten seeds, hard baselines, leave-family-out, "
                    "threshold sensitivity and plan-vector collisions"
                ),
            },
            {
                "appendix": "C",
                "source": (
                    "master-regimes-thesis/manuscript/appendices/"
                    "appendix-c-prikupljanje-i-ponovljivost.tex"
                ),
                "purpose": (
                    "correlation, state machine, lineage, applicability, "
                    "collector correctness and repeatability"
                ),
            },
            {
                "appendix": "D",
                "source": (
                    "master-regimes-thesis/manuscript/appendices/"
                    "appendix-d-studije-slucaja.tex"
                ),
                "purpose": (
                    "guided cases, B-C/A-D, q100, STATS portability and "
                    "weak coverage"
                ),
            },
        ],
    }


def defense_questions() -> list[dict[str, str]]:
    return [
        {
            "question": "Šta je glavni doprinos rada?",
            "short": (
                "Doprinos je auditabilan postupak koji artefakte GAC, "
                "regionalnih Citus koordinatora i worker/task sloja povezuje "
                "u jednu opservaciju. FCM je završni sažetak, a ne cijeli "
                "doprinos."
            ),
            "extended": (
                "Collector čuva lanac E_i -> Z_i -> x_i^(19) -> u_i^(4). "
                "Audit 2.603 kanonska izvršenja provjerava korelaciju i "
                "primjenjivost, dok planovi ostaju dostupni nakon kompresije."
            ),
            "evidence": "Slika 13 i collector audit 2603/2603",
        },
        {
            "question": "Zašto GAC plan nije dovoljan?",
            "short": (
                "GAC plan završava na FDW granici i ne prikazuje potpunu "
                "raspodjelu taskova i obrađenih redova po workerima."
            ),
            "extended": (
                "U 865 uparenih balanced/skew slučajeva medijana kontrasta "
                "odabranog GAC podprostora je 0.011, a regionalnog/worker "
                "podprostora 0.650; svih 11 SQL porodica ima pozitivan "
                "porodični kontrast."
            ),
            "evidence": "Topološki kontrast: 865 parova, 0.011 naspram 0.650",
        },
        {
            "question": "Zašto finalni model ima 19 pokazatelja?",
            "short": (
                "Izbor je zasnovan na fizičkom značenju, jedinicama, "
                "primjenjivosti, redundanciji i kontrolisanim kontrastima, "
                "ne na nasumičnom izboru ili identitetu SQL šablona."
            ),
            "extended": (
                "Završna reprezentacija uklanja identifikatore i apsolutno "
                "vrijeme, ograničava neograničene omjere, normalizuje ISF/CV "
                "prema topologiji i jednako ponderiše šest porodica."
            ),
            "evidence": "Prilog A i ablacija reprezentacije: 21 -> 19",
        },
        {
            "question": "Šta je q100 pokazao o DRF-u?",
            "short": (
                "Pokazao je da bezdimenzionalan omjer nije automatski "
                "ograničen ni nezavisan od veličine skupa podataka."
            ),
            "extended": (
                "DRF od 1.805.590 činio je 86.61% kvadrirane udaljenosti "
                "empirijskog baselinea. Nakon semantičke transformacije "
                "q100 ostaje neuobičajen na 97.40. percentilu, ali je "
                "unutar P99."
            ),
            "evidence": "Slika q100 ablacije reprezentacije",
        },
        {
            "question": (
                "Zašto završna reprezentacija nije prilagođena "
                "punom STATS-CEB auditu?"
            ),
            "short": (
                "Transformacije su zaključane prije punog audita, koji je "
                "projektovan bez refita centara ili pragova."
            ),
            "extended": (
                "Pokušano je svih 146 objavljenih STATS-CEB upita. Poređenje "
                "je završeno za 132, a 130 potpunih opservacija ostalo je "
                "unutar ranije zamrznute P99 granice. Nakon posmatranja nije "
                "bilo dopušteno mijenjati ugovor."
            ),
            "evidence": (
                "Puni audit bez refita: 130/130 potpunih opservacija "
                "unutar P99"
            ),
        },
        {
            "question": "Zašto FCM ako K-means daje istu tvrdu particiju?",
            "short": (
                "FCM nije zadržan zbog bolje tvrde geometrije, nego zato što "
                "čuva sekundarnu pripadnost i eksplicitno pokazuje miješane "
                "ili slabo pokrivene slučajeve."
            ),
            "extended": (
                "FCM i K-means imaju ARI 1.0, a Ward 0.967 prema FCM-u. "
                "Fuzzy vektor zato dodaje prikaz neodlučnosti bez tvrdnje o "
                "superiornom algoritmu grupisanja."
            ),
            "evidence": "Tabela FCM/K-means/Ward",
        },
        {
            "question": "Zašto k=4 ako je k=3 stabilniji?",
            "short": (
                "k=3 je stabilnija makrostruktura, a k=4 finija operativna "
                "rezolucija koja razdvaja dvije interpretabilne podvrste "
                "udaljenog toka i finalizacije."
            ),
            "extended": (
                "Za k=3 silueta je 0.607 i seed ARI 1.0. Za k=4 silueta je "
                "0.610, prosječni seed ARI 0.893 i minimum 0.559. Zato se "
                "četiri prototipa ne predstavljaju kao jedina prirodna "
                "particija."
            ),
            "evidence": "Prilog B, k=2..8 i deset seedova",
        },
        {
            "question": "Šta znači vanjska medijana članstva 0.365?",
            "short": (
                "Završna geometrija prihvata STATS upite kao pokrivene, ali "
                "postojeći prototipi im često ne daju sigurnu semantičku "
                "dijagnozu."
            ),
            "extended": (
                "Svih 130 potpunih opservacija je unutar P99, ali medijana "
                "u_max je 0.365. Prenosivost reprezentacije je zato jača od "
                "prenosivosti četveroprototipske interpretacije."
            ),
            "evidence": (
                "Puni STATS-CEB audit: 130/130 i medijana u_max=0.365"
            ),
        },
        {
            "question": "Šta collector vidi, a FCM može izgubiti?",
            "short": (
                "Collector zadržava planove, regione, taskove i workere; "
                "FCM vidi samo 19 transformisanih koordinata."
            ),
            "extended": (
                "Među 130 opservacija postoji 128 glavnih planova, ali samo "
                "79 vektorskih grupa. Kolizije čuvaju MapMerge/spill "
                "kategorije, ali gube dio repartition intenziteta i strukture."
            ),
            "evidence": "STATS kompresija 128 planova u 79 vektorskih grupa",
        },
        {
            "question": "Dokazuje li STATS-CEB produkcijsku generalizaciju?",
            "short": (
                "Ne. To je mali, deterministički vanjski workload koji "
                "provjerava ograničenu prenosivost geometrije na fiksnoj "
                "topologiji."
            ),
            "extended": (
                "STATS-CEB koristi real-derived Stack Exchange podatke, ali "
                "ima samo 12 potvrđujućih izvršenja bez refita. Rezultat ne "
                "pokriva različit hardver, više topologija niti produkcijsku "
                "učestalost SQL namjera."
            ),
            "evidence": "Javni STATS-CEB izvor i eksplicitna claim boundary",
        },
        {
            "question": "Šta nije testirano?",
            "short": (
                "Nisu sistematski mijenjani hardver, broj regiona, više "
                "veličina realnog skupa, konkurentnost ni produkcijski "
                "workload."
            ),
            "extended": (
                "Topologija ima dva regiona, hardver je fiksan unutar faze, "
                "a repartition dio H4 slabije je potvrđen od skew dijela. "
                "Zato su H3 i H4 djelimično, a ne potpuno podržane."
            ),
            "evidence": "Poglavlje ograničenja i status hipoteza",
        },
        {
            "question": "Kako bi se sistem proširio u budućem radu?",
            "short": (
                "Prvo bih proširio collector ugovor i vanjsku validaciju, "
                "a tek zatim modele, bez gubitka raw planova."
            ),
            "extended": (
                "Sljedeći koraci su tri ili više regiona, kontrolisani "
                "hardware/concurrency faktori, veći vanjski workload i "
                "poređenje 19-feature sažetka sa strukturnim plan encoderom. "
                "Plan-vector kolizije daju jasan kriterij kada je bogatija "
                "reprezentacija potrebna."
            ),
            "evidence": "Lanac E -> Z -> x^(19) -> u^(4)",
        },
    ]


def markdown_defense(questions: list[dict[str, str]]) -> str:
    lines = [
        "# Mapa pitanja za odbranu",
        "",
        "Kratki odgovori su namijenjeni izlaganju od približno 20--30 sekundi. "
        "Proširena verzija se koristi samo kada komisija traži dodatno "
        "obrazloženje.",
        "",
    ]
    for index, item in enumerate(questions, start=1):
        lines.extend(
            [
                f"## {index}. {item['question']}",
                "",
                f"**Kratko:** {item['short']}",
                "",
                f"**Prošireno:** {item['extended']}",
                "",
                f"**Dokaz:** {item['evidence']}",
                "",
            ]
        )
    return "\n".join(lines)


def terminology_audit() -> list[dict[str, Any]]:
    ordered = [
        THESIS_ROOT / "manuscript/preliminarne/sazetak-bs.tex",
        THESIS_ROOT / "manuscript/chapters/01-uvod.tex",
        *sorted((THESIS_ROOT / "manuscript/chapters/reworked").glob("*.tex")),
        *sorted((THESIS_ROOT / "manuscript/appendices").glob("*.tex")),
    ]
    rows: list[dict[str, Any]] = []
    for term, definition in TERM_RULES.items():
        first_occurrence: tuple[Path, int] | None = None
        first_definition: tuple[Path, int] | None = None
        for path in ordered:
            text = path.read_text(encoding="utf-8")
            if first_occurrence is None:
                match = re.search(rf"\b{re.escape(term)}\b", text)
                if match:
                    first_occurrence = (
                        path,
                        text.count("\n", 0, match.start()) + 1,
                    )
            if first_definition is None:
                match = definition.search(text)
                if match:
                    first_definition = (
                        path,
                        text.count("\n", 0, match.start()) + 1,
                    )
        status = "PASS"
        note = "definition precedes or contains first acronym occurrence"
        if first_occurrence is None or first_definition is None:
            status = "FAIL"
            note = "acronym or required English expansion is missing"
        elif ordered.index(first_definition[0]) > ordered.index(first_occurrence[0]):
            status = "FAIL"
            note = "definition appears in a later included source"
        elif (
            first_definition[0] == first_occurrence[0]
            and first_definition[1] > first_occurrence[1]
        ):
            status = "FAIL"
            note = "definition follows first acronym occurrence"
        rows.append(
            {
                "term": term,
                "first_occurrence": (
                    f"{repo_relative(first_occurrence[0])}:{first_occurrence[1]}"
                    if first_occurrence
                    else ""
                ),
                "first_definition": (
                    f"{repo_relative(first_definition[0])}:{first_definition[1]}"
                    if first_definition
                    else ""
                ),
                "status": status,
                "note": note,
            }
        )
    return rows


def privacy_findings() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in ACTIVE_TEX:
        text = path.read_text(encoding="utf-8")
        for rule, pattern in PRIVACY_RULES.items():
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "rule": rule,
                        "file": repo_relative(path),
                        "line": text.count("\n", 0, match.start()) + 1,
                        "value": match.group(0),
                    }
                )
    return findings


def required_content(feature_names: list[str]) -> list[dict[str, str]]:
    paths_and_snippets = [
        (
            THESIS_ROOT / "manuscript/appendices/appendix-a-pokazatelji.tex",
            "01-feature-contract.tex",
            "appendix_a_contract",
        ),
        (
            THESIS_ROOT / "manuscript/appendices/appendix-b-validacija.tex",
            "Poređenje \\(k=2,\\ldots,8\\)",
            "appendix_b_k_range",
        ),
        (
            THESIS_ROOT / "manuscript/appendices/appendix-b-validacija.tex",
            "Osjetljivost prikazne politike",
            "appendix_b_thresholds",
        ),
        (
            THESIS_ROOT / "manuscript/appendices/appendix-b-validacija.tex",
            "Kolizije između planova",
            "appendix_b_collisions",
        ),
        (
            THESIS_ROOT
            / "manuscript/appendices/"
            "appendix-c-prikupljanje-i-ponovljivost.tex",
            "Operativna stanja",
            "appendix_c_state_machine",
        ),
        (
            THESIS_ROOT / "manuscript/appendices/appendix-d-studije-slucaja.tex",
            "1\\,805\\,590",
            "appendix_d_q100",
        ),
        (
            THESIS_ROOT / "manuscript/appendices/appendix-d-studije-slucaja.tex",
            "128 različitih",
            "appendix_d_stats_collision",
        ),
        (
            THESIS_ROOT / "defense/odbrana.tex",
            "19 semantički transformisanih pokazatelja",
            "defense_v2_features",
        ),
        (
            THESIS_ROOT / "defense/odbrana.tex",
            "0.610",
            "defense_k4",
        ),
        (
            THESIS_ROOT / "defense/odbrana.tex",
            "130/130",
            "defense_stats",
        ),
    ]
    rows: list[dict[str, str]] = []
    for path, snippet, check in paths_and_snippets:
        status = "PASS" if snippet in path.read_text(encoding="utf-8") else "FAIL"
        rows.append(
            {
                "check": check,
                "file": repo_relative(path),
                "status": status,
            }
        )
    contract_table = (
        THESIS_ROOT / "tables/semantic-v2/01-feature-contract.tex"
    ).read_text(encoding="utf-8")
    for feature in feature_names:
        rows.append(
            {
                "check": f"feature:{feature}",
                "file": (
                    "master-regimes-thesis/tables/semantic-v2/"
                    "01-feature-contract.tex"
                ),
                "status": (
                    "PASS"
                    if feature in contract_table
                    else "FAIL"
                ),
            }
        )
    return rows


def reproducibility_report(
    states: list[dict[str, Any]],
    feature_names: list[str],
) -> str:
    source = yaml.safe_load(SOURCE_LOCK.read_text(encoding="utf-8"))
    model = yaml.safe_load(MODEL_MANIFEST.read_text(encoding="utf-8"))
    state_lines = "\n".join(
        f"- `{row['repository']}`: `{row['head_at_audit']}`, "
        f"dirty=`{str(row['working_tree_dirty']).lower()}`"
        for row in states
    )
    return f"""# Audit ponovljivosti završnog semantičkog paketa

## Opseg

Analitička regeneracija ne zahtijeva aktivnu infrastrukturu niti novo SQL
izvršavanje. Autoritativni input su sačuvani raw planovi i normalizovani
indeksi; verzionisani CSV/YAML/PDF izlazi su izvedeni sažeci. Run artefakti
ne sadrže redove koje su upiti vratili iz baze.

## Javni izvor

- STATS-CEB: [{source['title']}]({source['record_url']})
- DOI: `{source['doi']}`
- licenca: `{source['license']}`
- referentni benchmark commit:
  `{source['resources']['expected_results']['commit']}`
- zaključani izvor: `master-regimes/external/stats-ceb/source-lock.yml`

## Zaključani modelski ugovor

- model: `{model['model_id']}`
- trening opservacije: `{model['row_count']}`
- završni pokazatelji: `{len(feature_names)}`
- ugovor: `master-regimes/{model['feature_contract']}`
- SHA-256 ugovora: `{model['feature_contract_sha256']}`
- FCM centri su uslovljeni glavnim korpusom; semantičke transformacije ne
  koriste distribuciju potvrđujućeg STATS-CEB skupa.

## Lokalna regeneracija

```bash
cd master-regimes
uv sync --frozen
make semantic-v2-final-consistency
make semantic-v2-thesis-claims
make semantic-v2-thesis-defense

cd ../master-regimes-thesis
make thesis-check
make defense-check
```

Prve tri komande regenerišu analitičke audite iz postojećih indeksa i
zaključanih modelskih artefakata. Posljednje dvije grade i provjeravaju
rukopis i odbranu. Nijedna komanda ne podiže VPS niti pokreće SQL.

## Snapshot repozitorija

{state_lines}

Ovi hashovi opisuju stanje `HEAD` u trenutku audita. Budući da su radna stabla
bila izmijenjena, ne pripisuju se retroaktivno ranijim eksperimentima.
Plan 29 treba zabilježiti čisti release commit ili tag.

## Privatnost i prenosivost

Objavljeni rukopis i odbrana koriste repo-relative putanje i simboličke nazive
čvorova. Tajne, privatne IP adrese i apsolutne lokalne putanje nisu dio
objavljenog paketa. Raw infrastrukturni izlazi ostaju odvojeni od
verzionisanih analitičkih sažetaka.

## Reprezentativni integritet

- semantički ugovor: `{sha256(CONTRACT)}`
- modelski manifest: `{sha256(MODEL_MANIFEST)}`
- STATS source lock: `{sha256(SOURCE_LOCK)}`
"""


def main() -> int:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)

    r0 = yaml.safe_load(R0_CHECKPOINT.read_text(encoding="utf-8"))
    if r0.get("decision") != "GO":
        raise ValueError("Plan 27 R0 must be GO before Plan 28")

    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    feature_names = list(contract["features"])
    if len(feature_names) != 19:
        raise ValueError(f"Expected 19 V2 features, got {len(feature_names)}")

    grid, policies = threshold_sensitivity()
    grid.to_csv(OUT_DIR / "v2_threshold_sensitivity_grid.csv", index=False)
    policies.to_csv(OUT_DIR / "v2_threshold_policies.csv", index=False)
    membership_quality, membership_table = membership_quality_table()
    membership_quality.to_csv(
        OUT_DIR / "v2_membership_quality.csv",
        index=False,
    )
    membership_table_path = (
        THESIS_ROOT / "tables/semantic-v2/04-membership-quality.tex"
    )
    membership_table_path.parent.mkdir(parents=True, exist_ok=True)
    membership_table_path.write_text(
        membership_table,
        encoding="utf-8",
    )
    collisions = collision_rows()
    collisions.to_csv(OUT_DIR / "v2_plan_vector_collisions.csv", index=False)

    appendix = appendix_map(feature_names)
    (OUT_DIR / "appendix_content_map.yml").write_text(
        yaml.safe_dump(appendix, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    questions = defense_questions()
    (OUT_DIR / "defense_question_map.md").write_text(
        markdown_defense(questions),
        encoding="utf-8",
    )

    terminology = terminology_audit()
    write_csv(OUT_DIR / "terminology_audit.csv", terminology)
    privacy = privacy_findings()
    write_csv(
        OUT_DIR / "publication_privacy_audit.csv",
        privacy
        or [
            {
                "rule": "all",
                "file": "",
                "line": "",
                "value": "PASS: no findings",
            }
        ],
    )
    content = required_content(feature_names)
    write_csv(OUT_DIR / "plan28_content_gate.csv", content)

    states = [
        git_state(ROOT),
        git_state(THESIS_ROOT),
        git_state(WORKSPACE / "master-regimes-infra"),
    ]
    (OUT_DIR / "reproducibility_audit.md").write_text(
        reproducibility_report(states, feature_names),
        encoding="utf-8",
    )

    failures = [
        row for row in terminology + content if row["status"] != "PASS"
    ]
    if privacy:
        failures.extend(
            {
                "status": "FAIL",
                "check": f"privacy:{row['rule']}",
            }
            for row in privacy
        )
    visual_status = "PASS" if args.manual_visual_review_confirmed else "HOLD"
    decision = (
        "GO"
        if not failures and args.manual_visual_review_confirmed
        else "HOLD"
    )
    checkpoint = {
        "checkpoint_id": "semantic-v2-thesis-defense",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "plan": 28,
        "status": "completed" if decision == "GO" else "in_progress",
        "gate": "D0",
        "decision": decision,
        "research_freeze": True,
        "infrastructure_used": False,
        "audit": {
            "feature_contract_count": len(feature_names),
            "threshold_grid_points": len(grid),
            "defense_question_count": len(questions),
            "terminology_failures": sum(
                row["status"] != "PASS" for row in terminology
            ),
            "privacy_failures": len(privacy),
            "content_failures": sum(
                row["status"] != "PASS" for row in content
            ),
            "manual_visual_review": visual_status,
        },
        "artifacts": {
            "appendix_map": repo_relative(
                OUT_DIR / "appendix_content_map.yml"
            ),
            "reproducibility_audit": repo_relative(
                OUT_DIR / "reproducibility_audit.md"
            ),
            "defense_questions": repo_relative(
                OUT_DIR / "defense_question_map.md"
            ),
            "terminology_audit": repo_relative(
                OUT_DIR / "terminology_audit.csv"
            ),
            "privacy_audit": repo_relative(
                OUT_DIR / "publication_privacy_audit.csv"
            ),
        },
    }
    CHECKPOINT.write_text(
        yaml.safe_dump(checkpoint, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(CHECKPOINT)
    print(f"D0={decision}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
