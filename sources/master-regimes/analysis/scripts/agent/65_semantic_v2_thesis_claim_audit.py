#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT.parent
THESIS_ROOT = WORKSPACE / "master-regimes-thesis"
DEFAULT_OUT_DIR = ROOT / "analysis/reports/semantic-v2-thesis-finalization"
DEFAULT_CHECKPOINT = (
    ROOT / "llmcontext/plans/checkpoints/semantic-v2-thesis-claims.yml"
)

ACTIVE_TEX = [
    THESIS_ROOT / "manuscript/magistarski-rad.tex",
    THESIS_ROOT / "manuscript/naslovna.tex",
    *sorted((THESIS_ROOT / "manuscript/preliminarne").glob("*.tex")),
    THESIS_ROOT / "manuscript/chapters/01-uvod.tex",
    *sorted((THESIS_ROOT / "manuscript/chapters/reworked").glob("*.tex")),
    *sorted((THESIS_ROOT / "manuscript/appendices").glob("*.tex")),
    *sorted((THESIS_ROOT / "tables").glob("*/*.tex")),
]

SEARCH_TERMS = {
    "legacy_21": re.compile(
        r"21(?:-|[\s~])*"
        r"(?:pokazatelj|dimenzional|feature|indicator|ulaz)",
        re.IGNORECASE,
    ),
    "v1": re.compile(r"\bV1\b"),
    "standard_scaler": re.compile(r"StandardScaler", re.IGNORECASE),
    "universal": re.compile(r"\buniverzal|\buniversal", re.IGNORECASE),
    "pressure_claim": re.compile(
        r"dominant(?:ni|\s+)?\s*(?:pressure|pritis)|"
        r"detektor(?:\s+svih)?\s+pritis|pressure detector",
        re.IGNORECASE,
    ),
    "remote_path_share": re.compile(r"remote\\?_path\\?_share", re.IGNORECASE),
    "corpus_independent": re.compile(
        r"corpus[- ]independent|nezavisn[a-zčćžšđ]* od korpusa",
        re.IGNORECASE,
    ),
}

PROHIBITED_FINAL_PATTERNS = [
    re.compile(
        r"(?:konačn|final)[^\n]{0,90}21(?:-|[\s~])*(?:pokazatelj|dimenzional|feature)",
        re.IGNORECASE,
    ),
    re.compile(r"x\s*(?:_i)?\s*\^\s*\{?21\}?", re.IGNORECASE),
    re.compile(
        r"četiri\s+(?:prirodne|univerzalne)\s+(?:klase|režima)",
        re.IGNORECASE,
    ),
    re.compile(r"FCM[^\n]{0,80}detektor\s+(?:svih\s+)?pritis", re.IGNORECASE),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit final semantic-v2 thesis narrative and claim scope."
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    return parser.parse_args()


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve()))
    except ValueError:
        return str(path)


def context_classification(term: str, line: str) -> tuple[str, str]:
    lowered = line.lower()
    if term in {"legacy_21", "v1", "standard_scaler", "remote_path_share"}:
        if any(
            marker in lowered
            for marker in (
                "v1",
                "ranij",
                "earlier",
                "baseline",
                "ablacij",
                "razvojn",
                "prethod",
                "istorij",
                "unutarplansko",
            )
        ):
            return "legitimate_v1_baseline", "PASS"
    if term == "universal":
        if any(
            marker in lowered
            for marker in (
                "nije",
                "nisu",
                "ne dokazuje",
                "ne predstavlja",
                "ne univerzal",
                "a ne univerzal",
                "niti univerzal",
                "ne treba",
                "ne smiju",
                "niti dokazuje",
                "niti tvrdi",
                "ali ne",
                "bez tvrdnje",
                "ogranič",
                "not ",
                "does not",
            )
        ):
            return "claim_boundary", "PASS"
    if term == "corpus_independent":
        if "normaliz" in lowered and any(
            marker in lowered for marker in ("prototip", "cent", "uslovljen")
        ):
            return "qualified_normalization", "PASS"
    if term == "pressure_claim":
        return "unsupported_pressure_claim", "FAIL"
    return "manual_review", "REVIEW"


def scan_sources() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inventory: list[dict[str, Any]] = []
    prohibited: list[dict[str, Any]] = []
    for path in ACTIVE_TEX:
        if not path.exists():
            raise FileNotFoundError(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            context_window = " ".join(
                lines[max(0, line_number - 3) : min(len(lines), line_number + 1)]
            )
            for term, pattern in SEARCH_TERMS.items():
                if not pattern.search(line):
                    continue
                classification, status = context_classification(
                    term, context_window
                )
                inventory.append(
                    {
                        "file": repo_relative(path),
                        "line": line_number,
                        "term": term,
                        "classification": classification,
                        "status": status,
                        "context": line.strip(),
                    }
                )
            for pattern in PROHIBITED_FINAL_PATTERNS:
                if pattern.search(line):
                    if "V1" in line or "ranij" in line.lower():
                        continue
                    prohibited.append(
                        {
                            "file": repo_relative(path),
                            "line": line_number,
                            "context": line.strip(),
                        }
                    )
    return inventory, prohibited


def evidence_rows() -> list[dict[str, str]]:
    return [
        {
            "element": "RQ1 / H1",
            "status": "supported_with_scope",
            "claim": (
                "Semantički normalizovani relativni pokazatelji daju fizički "
                "čitljiviji modelski prostor od sirovih volumena i vremena."
            ),
            "primary_evidence": (
                "dataset-NMI ablacija baselinea; q100 DRF audit; završna "
                "k=3/4 geometrija"
            ),
            "boundary": (
                "Relativnost nije dovoljna bez ograničenja domena; završna "
                "reprezentacija nije uniformno bolja na svakom P99 skupu."
            ),
        },
        {
            "element": "RQ2",
            "status": "supported_with_two_resolutions",
            "claim": (
                "Korpus pokazuje stabilnu k=3 makrostrukturu i korisnu k=4 "
                "operativnu rezoluciju."
            ),
            "primary_evidence": (
                "k=2..8 audit; deset seedova; K-means i Ward poređenje"
            ),
            "boundary": (
                "Četiri prototipa nisu jedine prirodne niti univerzalne klase."
            ),
        },
        {
            "element": "RQ3 / H2",
            "status": "partially_supported_by_weak_internal_evidence",
            "claim": (
                "Fuzzy članstva čuvaju sekundarnu pripadnost i eksplicitno "
                "označavaju miješane ili slabo pokrivene slučajeve."
            ),
            "primary_evidence": (
                "membership margine i entropija; pressure-family korelacije; "
                "hard clustering poređenje"
            ),
            "boundary": (
                "FCM i K-means daju istu tvrdu particiju; H2 korelacije su "
                "slabe i dijele dio ulaznih pokazatelja."
            ),
        },
        {
            "element": "H3",
            "status": "partially_supported",
            "claim": (
                "Postupak se bez refita projektuje na kontrolisane uslove i "
                "ograničeni nezavisni STATS-CEB workload."
            ),
            "primary_evidence": (
                "validacija 190/195 unutar P99; puni STATS-CEB audit: "
                "130/130 potpunih opservacija unutar P99; "
                "leave-family-out ARI 0.914"
            ),
            "boundary": (
                "Puni STATS audit ima 14 correctness i dva instrumentacijska "
                "timeouta; pet validacijskih slučajeva ostaje blago izvan "
                "završnog P99."
            ),
        },
        {
            "element": "RQ4 / H4",
            "status": "partially_supported",
            "claim": (
                "Regionalni i worker/task pokazatelji otkrivaju raspodjelu "
                "rada slabije izraženu u odabranom GAC sažetku."
            ),
            "primary_evidence": (
                "865 balanced/skew parova; B-C worker placement; "
                "A-D regionalna asimetrija; 62/130 STATS MapMerge planova"
            ),
            "boundary": (
                "CV i ISF ne mjere CPU; worker/task scan detalj postoji samo "
                "za 10/62 STATS MapMerge slučaja; "
                "FCM može sabiti vidljiv fizički kontrast."
            ),
        },
        {
            "element": "Collector contribution",
            "status": "supported",
            "claim": (
                "Jedno globalno izvršenje auditabilno se rekonstruiše kroz "
                "GAC, regionalne i worker/task artefakte."
            ),
            "primary_evidence": (
                "2,603-row lineage audit; 24/24 stratifikovani ručni audit; "
                "repeatability; STATS-CEB adapter"
            ),
            "boundary": (
                "24/24 nije populacijska stopa greške; worker task dokaz nije "
                "uvijek puni JSON plan."
            ),
        },
    ]


def terminology() -> dict[str, Any]:
    return {
        "final_model": "završna semantička reprezentacija",
        "final_feature_count": 19,
        "legacy_model": "empirijski standardizovani baseline",
        "preferred_terms": {
            "OOD": (
                "termin definisati samo radi razgraničenja; empirijski rezultat "
                "opisivati kao izvršenje izvan P99 granice"
            ),
            "ablation": (
                "analiza uklanjanja komponenti (engl. ablation study)"
            ),
            "holdout": "izdvojeni validacijski skup",
            "prediction": "predviđanje",
            "GAC-visible": "pokazatelji vidljivi na GAC sloju",
            "topology-only": "regionalni i worker/task pokazatelji",
            "corpus_conditioned": "prototipi uslovljeni trening korpusom",
        },
        "claim_rules": {
            "normalization": (
                "semantički definisana normalizacija nezavisna od "
                "distribucijskih parametara vanjskog skupa"
            ),
            "prototypes": "FCM prototipi uslovljeni trening korpusom",
            "membership": "geometrijska sličnost, ne vjerovatnoća uzroka",
            "feature_vector": (
                "kompresija punog Z sloja, ne potpuni plan encoder"
            ),
        },
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir.resolve()
    checkpoint = args.checkpoint.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)

    inventory, prohibited = scan_sources()
    write_csv(out_dir / "stale_claim_inventory.csv", inventory)
    write_csv(out_dir / "rq_hypothesis_evidence_map.csv", evidence_rows())
    (out_dir / "terminology_decisions.yml").write_text(
        yaml.safe_dump(terminology(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    review_count = sum(row["status"] == "REVIEW" for row in inventory)
    fail_count = len(prohibited) + sum(
        row["status"] == "FAIL" for row in inventory
    )
    decision = "GO" if fail_count == 0 and review_count == 0 else "HOLD"
    report = f"""# Audit narativa završne semantičke reprezentacije

## Odluka

```text
C0 = {decision}
```

Aktivni rukopis je auditiran kao priča završne semantičke reprezentacije.
Finalni model ima 19 semantički normalizovanih pokazatelja; empirijski
standardizovani baseline sa 21 pokazateljem smije se pojaviti samo u ablaciji.

## Rezultat

- aktivni LaTeX izvori: {len(ACTIVE_TEX)}
- evidentirane ciljane terminološke pojave: {len(inventory)}
- nerazriješene pojave za ručni pregled: {review_count}
- zabranjene ili nekvalifikovane finalne tvrdnje: {fail_count}
- finalna odluka: `{decision}`

## Zaključana granica

Collector rekonstruiše višeslojni dokaz, završna reprezentacija definiše
semantički koordinatni prostor, a FCM daje korpusom uslovljen makroopis.
Pokrivenost prostorom nije isto što i snažno objašnjenje jednim prototipom.
Jednak vektor od 19 pokazatelja ne implicira jednak fizički plan.

Detalji su u:

```text
rq_hypothesis_evidence_map.csv
stale_claim_inventory.csv
terminology_decisions.yml
```
"""
    (out_dir / "narrative_claim_audit.md").write_text(
        report, encoding="utf-8"
    )

    checkpoint_payload = {
        "checkpoint_id": "semantic-v2-thesis-claims",
        "created_at_utc": datetime.now(tz=UTC).isoformat(),
        "plan": 26,
        "status": "completed" if decision == "GO" else "hold",
        "gate": "C0",
        "decision": decision,
        "research_freeze": True,
        "infrastructure_used": False,
        "final_model": {
            "representation": "semantic_v2",
            "feature_count": 19,
            "legacy_v1_feature_count": 21,
            "prototypes": "corpus_conditioned",
        },
        "audit": {
            "active_tex_files": len(ACTIVE_TEX),
            "inventory_rows": len(inventory),
            "manual_review_rows": review_count,
            "prohibited_claims": fail_count,
        },
        "artifacts": {
            "report": repo_relative(out_dir / "narrative_claim_audit.md"),
            "evidence_map": repo_relative(
                out_dir / "rq_hypothesis_evidence_map.csv"
            ),
            "stale_claim_inventory": repo_relative(
                out_dir / "stale_claim_inventory.csv"
            ),
            "terminology": repo_relative(
                out_dir / "terminology_decisions.yml"
            ),
        },
    }
    checkpoint.write_text(
        yaml.safe_dump(checkpoint_payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(out_dir / "narrative_claim_audit.md")
    return 0 if decision == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
