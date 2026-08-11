#!/usr/bin/env python3
"""Build the small, human-readable case package cited by the thesis."""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import math
import re
import shutil
import statistics
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from markdown_output import unwrap_prose


RUNS = Path("generated/feedback-loop-runs")
MAIN_RUN = RUNS / "20260807T123708Z-pressure-feedback-loop-v1"
AGG_RUN = RUNS / "20260807T152322Z-pressure-feedback-loop-aggregate-exact-v1"
N3_QUERY_ROOT = Path("generated/corpus/n3-topology-memory-v1/rendered")
Q08_AUDIT_ROOT = Path("releases/consolidated-evaluation-v1")

Q08_QUERY_CATALOG = (
    {
        "query_id": "q03_event_recent",
        "role": "neighbor",
        "round_id": "phase_a_baseline",
        "analytical_intent": "250 najnovijih događaja nakon granice vremena",
        "cutoff_ts": "2026-06-24 00:00:00+00",
        "limit_k": 250,
        "ordering": "created_at DESC",
    },
    {
        "query_id": "q04_event_oldest",
        "role": "neighbor",
        "round_id": "phase_a_baseline",
        "analytical_intent": "500 najstarijih događaja nakon granice vremena",
        "cutoff_ts": "2026-06-17 00:00:00+00",
        "limit_k": 500,
        "ordering": "created_at ASC",
    },
    {
        "query_id": "q05_event_deviation",
        "role": "neighbor",
        "round_id": "phase_a_baseline",
        "analytical_intent": "50 događaja s najvećim odstupanjem abs(value - 500)",
        "cutoff_ts": "2026-06-30 00:00:00+00",
        "limit_k": 50,
        "ordering": "abs(value - 500) DESC",
    },
    {
        "query_id": "q06_tenant_sum",
        "role": "neighbor",
        "round_id": "phase_a_baseline",
        "analytical_intent": "100 region-tenant grupa s najvećim SUM(value)",
        "cutoff_ts": "2026-06-29 00:00:00+00",
        "limit_k": 100,
        "ordering": "SUM(value) DESC",
    },
    {
        "query_id": "q07_tenant_count",
        "role": "neighbor",
        "round_id": "phase_a_baseline",
        "analytical_intent": "250 region-tenant grupa s najvećim COUNT(*)",
        "cutoff_ts": "2026-06-24 00:00:00+00",
        "limit_k": 250,
        "ordering": "COUNT(*) DESC",
    },
    {
        "query_id": "q08_tenant_avg",
        "role": "target",
        "round_id": "phase_b_baseline",
        "analytical_intent": "500 region-tenant grupa s najvećim AVG(value)",
        "cutoff_ts": "2026-06-17 00:00:00+00",
        "limit_k": 500,
        "ordering": "AVG(value) DESC",
    },
)

Q08_AUDIT_FILES = (
    "q08_neighbors.csv",
    "q08_action_rankings.csv",
    "q08_failure_analysis.json",
)

DATASET_TIME_CONTRACT = {
    "base_time_unix": 1782864000,
    "base_time_utc": "2026-07-01T00:00:00Z",
    "generated_lookback_days": 30,
    "allowed_cutoff_offsets_days": [1, 2, 7, 14, 30],
    "wall_clock_functions_allowed_in_measured_sql": False,
}
WALL_CLOCK_SQL = re.compile(
    r"\b(?:now\s*\(|current_timestamp\b|clock_timestamp\s*\(|"
    r"statement_timestamp\s*\(|transaction_timestamp\s*\()",
    flags=re.IGNORECASE,
)
TIMESTAMPTZ_LITERAL = re.compile(
    r"\btimestamptz\s*'([^']+)'", flags=re.IGNORECASE
)

METRICS = (
    ("elapsed_seconds", "s", "End-to-end trajanje"),
    ("edge_remote_bytes_sum", "bytes", "Procijenjeni udaljeni obim prema GAC-u"),
    ("edge_boundary_wait_share", "ratio", "Udio čekanja na FDW granici"),
    ("edge_rtt_context_median_ms_max", "ms", "Najveći medijan RTT konteksta"),
    (
        "regional_input_to_remote_rows_ratio",
        "ratio",
        "Regionalni ulaz po redu vraćenom GAC-u",
    ),
    (
        "remote_region_has_aggregate_share",
        "ratio",
        "Udio udaljenih grana sa regionalnom agregacijom",
    ),
    (
        "gac_fanin_to_final_rows_ratio",
        "ratio",
        "Broj GAC ulaznih redova po finalnom redu",
    ),
    (
        "gac_temp_written_per_final_row",
        "blocks/row",
        "Privremeni blokovi zapisani po finalnom redu",
    ),
    ("gac_hash_batch_excess", "count", "Dodatne hash serije na GAC-u"),
    ("spill_location_count", "count", "Broj slojeva sa opaženim preljevom"),
)


@dataclass(frozen=True)
class State:
    label: str
    directory: Path
    sweep: Path


@dataclass(frozen=True)
class Case:
    case_id: str
    title: str
    user_scenario: str
    logical_question_id: str
    action_id: str
    run: Path
    before: State
    after: State
    sql_files: tuple[tuple[str, Path], ...]
    result_contract: str
    interpretation: str
    sql_note: str | None = None
    regional_plans: tuple[tuple[str, Path], ...] = ()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def parse_number(value: str | None) -> float | None:
    if value is None or value.strip() in {"", "NA", "nan", "None"}:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def state_rows(source_root: Path, case: Case, state: State) -> list[dict[str, str]]:
    path = source_root / case.run / "states" / state.directory / "raw_signals.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"No state rows in {path}")
    return rows


def median_metrics(rows: list[dict[str, str]]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for field, _unit, _description in METRICS:
        values = [parse_number(row.get(field)) for row in rows]
        observed = [value for value in values if value is not None]
        result[field] = statistics.median(observed) if observed else None
    return result


def first_plan(source_root: Path, case: Case, state: State, suffix: str) -> Path:
    root = source_root / case.run / "sweeps" / state.sweep
    matches = sorted(root.rglob(f"*{suffix}"))
    if not matches:
        raise ValueError(f"No {suffix} plan under {root}")
    return matches[0]


def sanitize_text(value: str) -> str:
    value = re.sub(r"/home/[^\s\"']+", "<local-path>", value)

    def replace_ip(match: re.Match[str]) -> str:
        candidate = match.group(0)
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            return candidate
        return "<private-ip>" if address.is_private else candidate

    return re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", replace_ip, value)


def sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def plan_summary(plan: dict[str, Any], depth: int = 0) -> list[str]:
    node_type = str(plan.get("Node Type", "Unknown"))
    provider = plan.get("Custom Plan Provider")
    if provider:
        node_type += f" [{provider}]"
    counters = []
    for key, label in (
        ("Actual Rows", "rows"),
        ("Actual Loops", "loops"),
        ("Task Count", "tasks"),
        ("Disk Usage", "disk-kB"),
        ("HashAgg Batches", "hash-batches"),
    ):
        if key in plan:
            counters.append(f"{label}={plan[key]}")
    suffix = f" ({', '.join(counters)})" if counters else ""
    lines = [f"{'  ' * depth}{node_type}{suffix}"]
    for child in plan.get("Plans", []):
        lines.extend(plan_summary(child, depth + 1))
    return lines


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def clean_text_block(value: str) -> str:
    lines = (line.rstrip() for line in sanitize_text(value).splitlines())
    return "\n".join(lines).rstrip() + "\n"


def cutoff_offset_days(value: str) -> int:
    anchor = datetime.fromtimestamp(DATASET_TIME_CONTRACT["base_time_unix"], tz=UTC)
    cutoff = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    seconds = (anchor - cutoff).total_seconds()
    if seconds < 0 or seconds % 86400 != 0:
        raise ValueError(f"Timestamp is not an integral day offset from dataset anchor: {value}")
    return int(seconds // 86400)


def validate_measured_sql_time_contract(sql: str, label: str) -> list[int]:
    if match := WALL_CLOCK_SQL.search(sql):
        raise ValueError(f"{label}: measured SQL uses live wall clock: {match.group(0)}")
    offsets = [cutoff_offset_days(value) for value in TIMESTAMPTZ_LITERAL.findall(sql)]
    allowed = set(DATASET_TIME_CONTRACT["allowed_cutoff_offsets_days"])
    unexpected = sorted(set(offsets) - allowed)
    if unexpected:
        raise ValueError(f"{label}: cutoff offsets are outside frozen contract: {unexpected}")
    return sorted(set(offsets))


def format_value(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value:.12g}"


def cases() -> tuple[Case, ...]:
    return (
        Case(
            case_id="CASE-AGG-01",
            title="Ponovljeni agregacijski upit i provjera povrata",
            user_scenario="Ponavljanje istog SQL-a u kompatibilnom kontekstu",
            logical_question_id="trajectory_aggregate_exact_full_flow",
            action_id="restore_origin",
            run=AGG_RUN,
            before=State(
                "initial_baseline",
                Path("A_raw_baseline"),
                Path("20260807T152414Z-aggregate-exact-01-a_raw_baseline"),
            ),
            after=State(
                "final_rollback",
                Path("R0_prime_rollback"),
                Path("20260807T154045Z-aggregate-exact-21-r0_prime_rollback"),
            ),
            sql_files=(("query.sql", Path("rendered_sql/gac_fdw_multiregion_event_exact_raw_summary.sql")),),
            result_contract="Isti uređeni i multiskupovni hash u svih deset ponavljanja.",
            interpretation=(
                "Povrat konfiguracije reprodukuje početni fizički profil; mala razlika "
                "trajanja ostaje unutar unaprijed definisanog mjernog šuma."
            ),
        ),
        Case(
            case_id="CASE-JOIN-01",
            title="Regionalno potiskivanje spajanja",
            user_scenario="Različite SQL varijante iste ručno povezane analitičke namjere",
            logical_question_id="trajectory_join_pushdown",
            action_id="regional_pushdown_rewrite",
            run=MAIN_RUN,
            before=State(
                "coordinator_join",
                Path("trajectory_join_pushdown_s00"),
                Path("20260807T124618Z-feedback-loop-b-join-s00"),
            ),
            after=State(
                "regional_join",
                Path("trajectory_join_pushdown_s01"),
                Path("20260807T125847Z-feedback-loop-c-join-s01"),
            ),
            sql_files=(
                ("before.sql", Path("rendered_sql/gac_fdw_coordinator_local_user_join.sql")),
                ("after.sql", Path("rendered_sql/gac_fdw_coordinator_regional_user_join.sql")),
            ),
            result_contract="Uređeni i multiskupovni hash jednaki su prije i poslije preoblikovanja.",
            interpretation=(
                "Join i agregacija prelaze sa GAC-a u regione. Regionalne grane vraćaju "
                "po 11 grupisanih redova umjesto miliona sirovih redova."
            ),
            sql_note=(
                "Predikat `mod(tenant_id, 1::bigint) = 0` namjerno je neselektivan. "
                "On je instancirana vrijednost parametra full-flow šablona i propušta "
                "svaki `tenant_id`; zadržan je jer pripada stvarno izvršenom SQL-u."
            ),
            regional_plans=(
                (
                    "region-before.json",
                    Path(
                        "sweeps/20260807T124618Z-feedback-loop-b-join-s00/_index/"
                        "auto_explain_plans/20260807T124619Z-feedback-loop-b-join-s00__"
                        "trajectory_join_pushdown_s00-r01/auto_explain_eu_022.json"
                    ),
                ),
                (
                    "region-after.json",
                    Path(
                        "sweeps/20260807T125847Z-feedback-loop-c-join-s01/_index/"
                        "auto_explain_plans/20260807T125847Z-feedback-loop-c-join-s01__"
                        "trajectory_join_pushdown_s01-r01/auto_explain_eu_009.json"
                    ),
                ),
            ),
        ),
        Case(
            case_id="CASE-WAN-01",
            title="Isti SQL nakon WAN intervencije",
            user_scenario="Isti SQL nakon deklarisane konfiguracijske intervencije",
            logical_question_id="trajectory_aggregate_exact_full_flow",
            action_id="wan_delay_10ms_probe",
            run=AGG_RUN,
            before=State(
                "regional_aggregate",
                Path("C_regional_aggregate"),
                Path("20260807T152657Z-aggregate-exact-04-c_regional_aggregate"),
            ),
            after=State(
                "regional_aggregate_with_wan_delay",
                Path("D_wan_delay"),
                Path("20260807T152612Z-aggregate-exact-03-d_wan_delay"),
            ),
            sql_files=(("query.sql", Path("rendered_sql/gac_fdw_multiregion_event_exact_regional_summary.sql")),),
            result_contract="Isti uređeni i multiskupovni hash u svih deset ponavljanja.",
            interpretation=(
                "SQL i preneseni obim ostaju isti, dok RTT i čekanje na FDW granici rastu; "
                "time se transportna posljedica odvaja od promjene plana."
            ),
        ),
    )


def build_case(source_root: Path, output_root: Path, case: Case, source_commit: str) -> None:
    destination = output_root / case.case_id
    destination.mkdir(parents=True, exist_ok=True)
    source_files: list[dict[str, str]] = []

    query_cutoff_offsets: set[int] = set()
    for public_name, source_relative in case.sql_files:
        source = source_root / case.run / source_relative
        sql = source.read_text(encoding="utf-8")
        query_cutoff_offsets.update(
            validate_measured_sql_time_contract(sql, f"{case.case_id}/{public_name}")
        )
        shutil.copyfile(source, destination / public_name)
        source_files.append(
            {"path": (case.run / source_relative).as_posix(), "sha256": sha256(source)}
        )

    metric_rows: list[dict[str, Any]] = []
    raw_hashes: dict[str, dict[str, str]] = {}
    for role, state in (("before", case.before), ("after", case.after)):
        rows = state_rows(source_root, case, state)
        medians = median_metrics(rows)
        raw_hashes[role] = {
            "ordered_sha256": rows[0]["result_ordered_sha256"],
            "multiset_sha256": rows[0]["result_multiset_sha256"],
        }
        for field, unit, description in METRICS:
            metric_rows.append(
                {
                    "state": state.label,
                    "role": role,
                    "repetitions": len(rows),
                    "metric": field,
                    "median": format_value(medians[field]),
                    "unit": unit,
                    "meaning": description,
                }
            )
        raw_path = source_root / case.run / "states" / state.directory / "raw_signals.csv"
        source_files.append(
            {"path": raw_path.relative_to(source_root).as_posix(), "sha256": sha256(raw_path)}
        )

        plan_txt = first_plan(source_root, case, state, ".explain.txt")
        plan_json = first_plan(source_root, case, state, ".explain.json")
        (destination / "plans").mkdir(exist_ok=True)
        (destination / "plans" / f"gac-{role}.txt").write_text(
            clean_text_block(plan_txt.read_text(encoding="utf-8")), encoding="utf-8"
        )
        gac_json = sanitize_json(json.loads(plan_json.read_text(encoding="utf-8")))
        (destination / "plans" / f"gac-{role}.json").write_text(
            json.dumps(gac_json, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        source_files.extend(
            [
                {"path": plan_txt.relative_to(source_root).as_posix(), "sha256": sha256(plan_txt)},
                {"path": plan_json.relative_to(source_root).as_posix(), "sha256": sha256(plan_json)},
            ]
        )

    write_csv(
        destination / "metrics.csv",
        metric_rows,
        ["state", "role", "repetitions", "metric", "median", "unit", "meaning"],
    )

    for public_name, source_relative in case.regional_plans:
        source = source_root / case.run / source_relative
        payload = sanitize_json(json.loads(source.read_text(encoding="utf-8")))
        target = destination / "plans" / public_name
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        summary_name = public_name.replace(".json", "-summary.txt")
        summary = plan_summary(payload["Plan"])
        (destination / "plans" / summary_name).write_text(
            "\n".join(summary) + "\n", encoding="utf-8"
        )
        source_files.append(
            {"path": source.relative_to(source_root).as_posix(), "sha256": sha256(source)}
        )

    if raw_hashes["before"] != raw_hashes["after"]:
        raise ValueError(f"{case.case_id}: result hashes differ")

    manifest = {
        "schema_version": 1,
        "case_id": case.case_id,
        "title": case.title,
        "user_scenario": case.user_scenario,
        "logical_question_id": case.logical_question_id,
        "action_id": case.action_id,
        "source_repository_commit": source_commit,
        "source_run": case.run.as_posix(),
        "dataset_time_contract": {
            **DATASET_TIME_CONTRACT,
            "query_cutoff_offsets_days": sorted(query_cutoff_offsets),
        },
        "result_contract": case.result_contract,
        "result_hashes": raw_hashes["before"],
        "source_artifacts": source_files,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    sql_note = f"\n\n## Napomena o SQL-u\n\n{case.sql_note}" if case.sql_note else ""
    readme = f"""# {case.case_id}: {case.title}

## Namjena

{case.user_scenario}.

- `logical_question_id`: `{case.logical_question_id}`
- deklarisana intervencija: `{case.action_id}`
- rezultatska provjera: {case.result_contract}

## Šta je opaženo

{case.interpretation}{sql_note}

## Vremenski ugovor

Skup je generisan oko zamrznutog oslonca `2026-07-01T00:00:00Z`
(`base_time_unix=1782864000`) sa verzionisanim sjemenom i prozorom od 30
dana. Kalendarski datumi u SQL-u su renderovani odmaci od tog oslonca, a ne
datumi izvođenja eksperimenta. Tačni odmaci ovog slučaja zapisani su u
`manifest.json`; mjereni SQL ne koristi `now()` ni `current_timestamp`.

`metrics.csv` sadrži medijane stvarnih ponavljanja. Direktorij `plans/`
sadrži izvorne GAC planske artefakte, a gdje je relevantno i sanitizovane
regionalne `auto_explain` planove sa stvarnim brojem redova i petlji.
Potpuno porijeklo i SHA-256 izvornih artefakata zapisani su u `manifest.json`.

## Granica tumačenja

Ovaj slučaj dokumentuje opaženu tranziciju na evaluiranoj infrastrukturi.
Ne predstavlja univerzalnu preporuku iste intervencije za drugi SQL ili
drugu infrastrukturu.
"""
    (destination / "README.md").write_text(unwrap_prose(readme), encoding="utf-8")


def build_q08_neighbor_catalog(
    source_root: Path, output_root: Path, source_commit: str
) -> None:
    destination = output_root / "Q08-NEIGHBORS"
    query_destination = destination / "queries"
    query_destination.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    source_files: list[dict[str, str]] = []

    for entry in Q08_QUERY_CATALOG:
        query_root = source_root / N3_QUERY_ROOT / str(entry["round_id"])
        matches = sorted(query_root.rglob(f"{entry['query_id']}__baseline*.sql"))
        if len(matches) != 1:
            raise ValueError(
                f"Expected one SQL for {entry['query_id']} in {query_root}, got {matches}"
            )
        source = matches[0]
        sql = source.read_text(encoding="utf-8")
        offsets = validate_measured_sql_time_contract(sql, str(entry["query_id"]))
        if offsets != [cutoff_offset_days(str(entry["cutoff_ts"]))]:
            raise ValueError(f"{entry['query_id']}: catalog cutoff does not match SQL")
        public_name = f"{entry['query_id']}.sql"
        shutil.copyfile(source, query_destination / public_name)
        source_relative = source.relative_to(source_root).as_posix()
        source_hash = sha256(source)
        rows.append(
            {
                **entry,
                "cutoff_offset_days": offsets[0],
                "sql_path": f"queries/{public_name}",
                "source_path": source_relative,
                "source_sha256": source_hash,
            }
        )
        source_files.append({"path": source_relative, "sha256": source_hash})

    for public_name in Q08_AUDIT_FILES:
        source = source_root / Q08_AUDIT_ROOT / public_name
        shutil.copyfile(source, destination / public_name)
        source_files.append(
            {"path": source.relative_to(source_root).as_posix(), "sha256": sha256(source)}
        )

    write_csv(
        destination / "query-index.csv",
        rows,
        [
            "query_id",
            "role",
            "round_id",
            "analytical_intent",
            "cutoff_ts",
            "cutoff_offset_days",
            "limit_k",
            "ordering",
            "sql_path",
            "source_path",
            "source_sha256",
        ],
    )
    manifest = {
        "schema_version": 1,
        "catalog_id": "Q08-NEIGHBORS",
        "source_repository_commit": source_commit,
        "topology_id": "eu_us_apac_gac",
        "target_query_id": "q08_tenant_avg",
        "neighbor_round": "phase_a",
        "target_round": "phase_b",
        "dataset_time_contract": DATASET_TIME_CONTRACT,
        "source_artifacts": source_files,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    table = [
        "| ID | Uloga | Analitička namjera | Granica | Odmak | K | Poredak |",
        "| --- | --- | --- | --- | --: | --: | --- |",
    ]
    for row in rows:
        analytical_intent = str(row["analytical_intent"]).replace("*", r"\*")
        table.append(
            f"| [`{row['query_id']}`]({row['sql_path']}) | {row['role']} | "
            f"{analytical_intent} | `{row['cutoff_ts']}` | "
            f"{row['cutoff_offset_days']} dana | {row['limit_k']} | "
            f"`{row['ordering']}` |"
        )
    readme = """# Q08-NEIGHBORS: tačni SQL identiteti analize greške

Ovaj katalog dokumentuje ciljni upit `q08_tenant_avg` iz N3 faze B i pet
susjeda iz N3 faze A koji su korišteni u procjeni. Svi upiti prvo povezuju
EU, US i APAC granu pomoću `UNION ALL`. Tabela navodi instancirane vremenske
granice, `LIMIT` vrijednosti i primarni ključ sortiranja; SQL datoteke čuvaju
i determinističke sekundarne ključeve.

Datumi su izvedeni iz zamrznutog oslonca skupa
`2026-07-01T00:00:00Z`, a kolona `cutoff_offset_days` u
`query-index.csv` čuva njihov relativni odmak. Oni nisu vezani za datum
pokretanja eksperimenta.

""" + "\n".join(table) + """

## Trag procjene

- `q08_neighbors.csv` sadrži udaljenosti, težine i stvarne dobitke susjeda.
- `q08_action_rankings.csv` sadrži procijenjeni i stvarni poredak akcija.
- `q08_failure_analysis.json` sadrži objedinjenu dijagnozu i doprinos greške
  ukupnom propuštenom dobitku faze B.
- `query-index.csv` i `manifest.json` povezuju javne SQL datoteke s izvornim
  putanjama, commitom i SHA-256 vrijednostima.

Katalog služi provjeri jedne zadržane greške sekundarne memorijske analize.
Ne predstavlja novi reprezentativni korisnički slučaj niti glavni izlaz rada.
"""
    (destination / "README.md").write_text(unwrap_prose(readme), encoding="utf-8")


def write_index(output_root: Path, all_cases: tuple[Case, ...]) -> None:
    rows = [
        {
            "case_id": case.case_id,
            "user_scenario": case.user_scenario,
            "logical_question_id": case.logical_question_id,
            "action_id": case.action_id,
            "path": f"examples/{case.case_id}",
        }
        for case in all_cases
    ]
    write_csv(
        output_root / "case-index.csv",
        rows,
        ["case_id", "user_scenario", "logical_question_id", "action_id", "path"],
    )
    table = [
        "| Case | Korisnički scenario | Intervencija |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        table.append(
            f"| [{row['case_id']}]({row['case_id']}/) | {row['user_scenario']} | "
            f"`{row['action_id']}` |"
        )
    (output_root / "case-index.md").write_text(
        unwrap_prose("\n".join(table) + "\n"), encoding="utf-8"
    )
    (output_root / "README.md").write_text(
        unwrap_prose("""# Reprezentativni slučajevi

Ovaj direktorij je čitljivi ulaz u eksperimentalne artefakte rada. PDF
objašnjava analitičku namjeru i glavni nalaz; ovdje su dostupni puni SQL,
stvarni planski artefakti, medijane pokazatelja i porijeklo izvora.

Svi kurirani slučajevi koriste zamrznuti vremenski oslonac skupa podataka.
Kalendarski literali u SQL-u predstavljaju verzionisane relativne presjeke,
ne vrijeme pokretanja komande. Svaki `manifest.json` navodi oslonac, prozor
generatora i odmake konkretnih upita.

Tri slučaja odgovaraju trima operativnim tokovima:

1. ponavljanje istog SQL-a;
2. isti SQL nakon deklarisane konfiguracijske intervencije;
3. različite SQL varijante iste ručno povezane analitičke namjere.

`CASE-AGG-01` i `CASE-WAN-01` predstavljaju dva javna presjeka iste tačne
agregacijske putanje koja vodi metodološki narativ rada: početno i vraćeno
stanje te WAN tranziciju nakon regionalne redukcije. `CASE-JOIN-01` je
komplementarna planska dubinska studija SQL preoblikovanja.

Počnite od [indeksa slučajeva](case-index.md). Kompletan generisani korpus
ostaje u `artifacts/rendered-corpora/`; nije potreban za razumijevanje ova
tri primjera.

Direktorij [`Q08-NEIGHBORS`](Q08-NEIGHBORS/) zasebno čuva šest tačno
izvršenih SQL iskaza i puni trag najveće greške sekundarne cross-query
procjene. On je auditni katalog, a ne četvrti reprezentativni slučaj.

Direktorij [`PLAN-SOURCE-01`](PLAN-SOURCE-01/) cuva sanitizovane JSON
planove iza PEV2 prikaza iz rukopisa. To su dva nezavisna ilustrativna plana,
ne povezani slojevi istog izvršenja niti ulaz u numeričke rezultate.

## Reprodukcija paketa

```bash
make examples
make examples-check
```

Generator čita samo postojeće artefakte. Ne pokreće SQL niti mijenja
infrastrukturu.
"""),
        encoding="utf-8",
    )


def write_checksums(output_root: Path) -> None:
    checksum_path = output_root / "checksums.sha256"
    rows = []
    for path in sorted(output_root.rglob("*")):
        if path.is_file() and path != checksum_path:
            rows.append(f"{sha256(path)}  {path.relative_to(output_root).as_posix()}")
    checksum_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def validate_public_output(output_root: Path) -> None:
    forbidden = ("/home/", "BEGIN PRIVATE KEY", "password=")
    for path in output_root.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                raise ValueError(f"Forbidden public token {token!r} in {path}")
        for candidate in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if address.is_private:
                raise ValueError(f"Private IP remains in {path}: {candidate}")


MANUALLY_CURATED_DIRECTORIES = {"PLAN-SOURCE-01"}


def build(source_root: Path, output_root: Path) -> None:
    if output_root.exists():
        for child in output_root.iterdir():
            if child.name in MANUALLY_CURATED_DIRECTORIES:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    output_root.mkdir(parents=True, exist_ok=True)
    all_cases = cases()
    source_commit = git_commit(source_root)
    for case in all_cases:
        build_case(source_root, output_root, case, source_commit)
    build_q08_neighbor_catalog(source_root, output_root, source_commit)
    write_index(output_root, all_cases)
    write_checksums(output_root)
    validate_public_output(output_root)


def compare_directories(expected: Path, observed: Path) -> None:
    expected_files = {
        path.relative_to(expected): sha256(path)
        for path in expected.rglob("*")
        if path.is_file() and path.name != "checksums.sha256"
    }
    observed_files = {
        path.relative_to(observed): sha256(path)
        for path in observed.rglob("*")
        if path.is_file()
        and path.name != "checksums.sha256"
        and path.relative_to(observed).parts[0] not in MANUALLY_CURATED_DIRECTORIES
    }
    if expected_files != observed_files:
        missing = sorted(set(expected_files) - set(observed_files))
        extra = sorted(set(observed_files) - set(expected_files))
        changed = sorted(
            key
            for key in set(expected_files) & set(observed_files)
            if expected_files[key] != observed_files[key]
        )
        raise ValueError(
            f"Representative cases are stale: missing={missing}, extra={extra}, "
            f"changed={changed}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="representative-cases-") as tmp:
            candidate = Path(tmp) / "examples"
            build(source_root, candidate)
            compare_directories(candidate, output_root)
        print("[examples] PASS: curated cases and q08 query catalog match their sources")
        return 0
    build(source_root, output_root)
    print(f"[examples] built {len(cases())} cases and q08 query catalog in {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
