#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

from markdown_output import unwrap_prose


ROOT = Path(__file__).resolve().parents[1]
QUERY_CATALOG = ROOT / "reproducibility/query-catalog.csv"
DATASET_CATALOG = ROOT / "reproducibility/dataset-catalog.csv"
QUERY_ID = re.compile(r"^(q\d{2}_[a-z0-9_]+?)__")

INTENTS = {
    "q01_event_value_desc": "događaji sa najvećim vrijednostima",
    "q02_event_value_asc": "događaji sa najmanjim vrijednostima",
    "q03_event_recent": "najnoviji događaji nakon vremenske granice",
    "q04_event_oldest": "najstariji događaji nakon vremenske granice",
    "q05_event_deviation": "događaji sa najvećim odstupanjem vrijednosti",
    "q06_tenant_sum": "tenant grupe sa najvećim zbirom vrijednosti",
    "q07_tenant_count": "tenant grupe sa najvećim brojem događaja",
    "q08_tenant_avg": "tenant grupe sa najvećim prosjekom vrijednosti",
    "q09_tenant_max": "tenant grupe sa najvećom pojedinačnom vrijednošću",
    "q10_tenant_min": "tenant grupe rangirane po najmanjoj vrijednosti",
    "q11_tenant_high_count": "broj visokovrijednih događaja po tenantu",
    "q12_tenant_user_sum": "zbir vrijednosti po tenant-user grupi",
    "q13_tenant_user_count": "broj događaja po tenant-user grupi",
    "q14_tenant_day_sum": "dnevni zbir po tenantu",
    "q15_tenant_day_count": "dnevni broj događaja po tenantu",
    "q16_event_value_squared": "događaji rangirani kvadratom vrijednosti",
    "q17_event_log_value": "događaji rangirani logaritmom vrijednosti",
    "q18_event_recent_high_value": "noviji visokovrijedni događaji",
    "q19_event_old_low_value": "stariji niskovrijedni događaji",
    "q20_event_tenant_weighted": "događaji s tenant-ponderisanom vrijednošću",
    "q21_tenant_value_range": "raspon vrijednosti po tenantu",
    "q22_tenant_distinct_users": "broj različitih korisnika po tenantu",
    "q23_tenant_even_user_count": "broj događaja parnih korisnika po tenantu",
    "q24_tenant_midband_sum": "zbir srednjeg raspona vrijednosti po tenantu",
    "q25_tenant_day_avg": "dnevni prosjek po tenantu",
    "q26_tenant_hour_count": "satni broj događaja po tenantu",
    "q27_user_sum": "zbir vrijednosti po korisniku",
    "q28_user_count": "broj događaja po korisniku",
    "q29_user_value_range": "raspon vrijednosti po korisniku",
    "q30_user_day_sum": "dnevni zbir po korisniku",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def query_name(row: dict[str, str]) -> str:
    match = QUERY_ID.match(Path(row["sql_path"]).name)
    return match.group(1) if match else ""


def select_query_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        name = query_name(row)
        if not name:
            continue
        path = row["sql_path"]
        action = row["mitigation_action"] or "baseline"
        if name.startswith(tuple(f"q{i:02d}_" for i in range(1, 16))):
            if row["rendered_corpus"] != "n3-topology-memory-v1":
                continue
            if "/n2_control/" in path and action in {"baseline", "regional_topk_candidates"}:
                selected.append({**row, "public_panel": "final-panel-n2", "query_name": name, "public_action": action})
            elif "/phase_b_baseline/" in path and action == "baseline":
                selected.append({**row, "public_panel": "final-panel-n3", "query_name": name, "public_action": action})
            elif "/phase_b_actions/" in path and action == "regional_topk_candidates":
                selected.append({**row, "public_panel": "final-panel-n3", "query_name": name, "public_action": action})
        elif name.startswith(tuple(f"q{i:02d}_" for i in range(16, 31))):
            if row["rendered_corpus"] == "confirmatory-action-replication-v1" and action in {"baseline", "regional_topk_candidates"}:
                selected.append({**row, "public_panel": "confirmatory-panel-n3", "query_name": name, "public_action": action})
    expected = 15 * 2 + 15 * 2 + 15 * 2
    if len(selected) != expected:
        raise ValueError(f"Expected {expected} curated query rows, got {len(selected)}")
    return sorted(selected, key=lambda row: (row["public_panel"], row["query_name"], row["public_action"]))


def build_queries() -> None:
    rows = read_csv(QUERY_CATALOG)
    selected = select_query_rows(rows)
    output = ROOT / "queries/instances"
    if output.exists():
        shutil.rmtree(output)
    index: list[dict[str, str]] = []
    for row in selected:
        source = ROOT / row["sql_path"]
        action_name = "regional-topk" if row["public_action"] == "regional_topk_candidates" else "baseline"
        relative = Path("queries/instances") / row["public_panel"] / f"{row['query_name']}__{action_name}.sql"
        destination = ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        index.append(
            {
                "query_id": row["query_name"],
                "analytical_intent": INTENTS[row["query_name"]],
                "panel": row["public_panel"],
                "topology_id": row["topology_id"],
                "dataset_profile_id": row["dataset_profile_id"],
                "sql_variant": action_name,
                "sql_path": relative.as_posix(),
                "sql_sha256": sha256(destination),
                "authoritative_source_path": row["sql_path"],
                "parameter_json": row["parameter_json"],
                "unchanged_sql_actions": "increase_gac_work_mem;mitigate_remote_path_bundle" if action_name == "baseline" else "",
            }
        )
    fields = list(index[0])
    write_csv(ROOT / "queries/thesis-query-index.csv", index, fields)

    templates = []
    base = ROOT / "sources/master-regimes/workloads/templates"
    for path in sorted(base.rglob("*")):
        if path.suffix.lower() not in {".j2", ".sql"}:
            continue
        templates.append(
            {
                "template_id": path.name.removesuffix(".sql.j2").removesuffix(".j2").removesuffix(".sql"),
                "family": path.relative_to(base).parts[0],
                "template_path": path.relative_to(ROOT).as_posix(),
            }
        )
    write_csv(ROOT / "queries/template-index.csv", templates, ["template_id", "family", "template_path"])

    lines = [
        "# SQL upiti korišteni u radu",
        "",
        "Ovdje se direktno nalaze čitljive kopije SQL instanci označenih sa `q01` do `q30`.",
        "Kopije su izvedene iz autoritativnih renderovanih corpusa i njihov SHA-256 je u",
        "[`thesis-query-index.csv`](thesis-query-index.csv).",
        "",
        "- [`instances/final-panel-n2/`](instances/final-panel-n2/) sadrži N2 oblike `q01`-`q15`.",
        "- [`instances/final-panel-n3/`](instances/final-panel-n3/) sadrži N3 oblike `q01`-`q15`.",
        "- [`instances/confirmatory-panel-n3/`](instances/confirmatory-panel-n3/) sadrži nove `q16`-`q30`.",
        "- [`template-index.csv`](template-index.csv) vodi do svih Jinja/SQL šablona u izvornom snapshotu.",
        "- Puni katalog svih 3.819 renderovanih SQL fajlova ostaje u",
        "  [`reproducibility/query-catalog.csv`](../reproducibility/query-catalog.csv).",
        "",
        "Svaki upit ima `baseline` i `regional-topk` SQL. Akcije `work_mem` i udaljena",
        "mitigacija ne mijenjaju SQL tekst, pa koriste isti `baseline` fajl uz drugačiji runtime ugovor.",
        "",
        "## Važna napomena o oznakama",
        "",
        "Broj poput `q07` nije globalni identitet kroz sve corpuse. U završnom i N3 panelu",
        "oznaka je `q07_tenant_count`; stariji karakterizacijski corpus ima zaseban šablon",
        "`q07_global_user_segment_join`. Zato u citatima i indeksima uvijek treba koristiti puni naziv",
        "i corpus, a ne samo redni broj.",
        "",
        "## q01-q30",
        "",
        "| Upit | Analitička namjera |",
        "| --- | --- |",
    ]
    lines.extend(f"| `{name}` | {INTENTS[name]} |" for name in sorted(INTENTS))
    (ROOT / "queries/README.md").write_text(
        unwrap_prose("\n".join(lines) + "\n"), encoding="utf-8"
    )


def build_datasets() -> None:
    rows = read_csv(DATASET_CATALOG)
    fields = list(rows[0])
    write_csv(ROOT / "datasets/dataset-index.csv", rows, fields)
    text = """# Skupovi podataka

Ovaj direktorij je kratki ulaz u sintetičke skupove stvarno povezane s
objavljenim SQL instancama. Potpuni ugovor svakog skupa nalazi se u
[`dataset-index.csv`](dataset-index.csv), a YAML profili u
[`sources/master-regimes/datasets/profiles/`](../sources/master-regimes/datasets/profiles/).

Skup podataka nije objavljen kao PostgreSQL dump. Ponovljiva konstrukcija
sastoji se od DDL-a, generatora, profila, sjemena, `base_time_unix`, regionalnih
raspona i shard ugovora.

## Šema i generator

- [`minimal_schema.sql`](../sources/citus-datagen/sql/minimal_schema.sql) je
  izvršivi DDL: tabele, indeksi, distribucijski ključevi, kolokacija i
  referentna tabela.
- [`current-schema-erd.svg`](../sources/citus-datagen/diagrams/current-schema-erd.svg)
  prikazuje isti ugovor kao ER dijagram.
- [`sources/citus-datagen/`](../sources/citus-datagen/) sadrži generator i
  naredbe za učitavanje.
- [`dataset-index.csv`](dataset-index.csv) povezuje eksperimentalni
  `dataset_id` sa profilom, sjemenom, vremenskim osloncem, brojem shardova i
  ugovorom regenerisanja.

DDL je zajednička osnova, dok YAML profil određuje obim, regionalne raspone,
neravnomjernost, sjeme i `base_time_unix`. Zbog toga sam DDL nije dovoljan za
ponavljanje konkretnog eksperimentalnog skupa.

## Profili koje je važno razlikovati

| Vrsta | Primjer profila | Značenje |
| --- | --- | --- |
| balansiran | `pilot-balanced-v1` | približno jednak regionalni obim i bez namjernog hot-tenanta |
| regionalno nebalansiran | `pilot-region-imbalanced-v1` | različit obim redova između EU i US |
| globalni hot-tenant | `pilot-skew-heavy-v1` | neravnomjerna frekvencija tenant ključeva u cijelom skupu |
| lokalno asimetričan | `pilot-region-local-skew-asymmetric-medium-v1` | EU hot-tenant opterećenje uz uniformniji US; worker/task neravnomjernost se mjeri iz izvršenja |
| N2/N3 topology isolation | `topology-isolation-*-n2/n3-v1` | upareni profili za kontrolisanu promjenu broja logičkih regiona |

Lokalno asimetričan profil ne mijenja broj shardova po workeru. Oznaka worker
skew odnosi se na opaženu neravnomjernost redova, taskova ili vremena rada koja
nastaje iz hot-tenant podataka i stvarnog placementa.

Vremenski presjeci i poznati stariji izuzeci objedinjeni su u
[`temporal-validity-audit-v1`](../releases/temporal-validity-audit-v1/). Glavni
noviji paneli koriste verzionisani `base_time_unix`; zajednički stariji korpus
modela F19 i F21-dev ima
slabiji temporalni ugovor i u radu se tumači samo kao arhivirani deskriptivni
dokaz.
"""
    (ROOT / "datasets/README.md").write_text(unwrap_prose(text), encoding="utf-8")


def build_corpora() -> None:
    rows = [
        ("clean-run-v1", "završna F19 karakterizacija i historijska F21-dev ablacija", "artifacts/rendered-corpora/clean-run-v1", "releases/rq-alignment-v2"),
        ("pressure-raw-v1", "široki intervencijski corpus", "artifacts/rendered-corpora/pressure-raw-v1", "artifacts/results/pressure-actionability-v1"),
        ("dba-local-memory-v1", "završni DBA panel", "artifacts/rendered-corpora/dba-local-memory-v1", "releases/consolidated-evaluation-v1"),
        ("n3-topology-memory-v1", "kontrolisani N2/N3 panel", "artifacts/rendered-corpora/n3-topology-memory-v1", "releases/consolidated-evaluation-v1"),
        ("confirmatory-action-replication-v1", "potvrdni panel q16-q30", "artifacts/rendered-corpora/confirmatory-action-replication-v1", "releases/confirmatory-action-replication-v1"),
        ("feedback-loop-v1", "longitudinalne DBA putanje", "artifacts/rendered-corpora/feedback-loop-v1", "releases/feedback-loop-analysis-v1"),
        ("region-asymmetry-companion-v1", "regionalna asimetrija", "artifacts/rendered-corpora/region-asymmetry-companion-v1", "artifacts/features/clean-run-v1-region-asymmetry"),
        ("wan-latency-companion-v1", "mrežna osjetljivost", "artifacts/rendered-corpora/wan-latency-companion-v1", "artifacts/logical-indexes/clean-run-v1-wan-latency.tar.gz"),
        ("repeatability-v1", "ponovljivost odabranih stanja", "artifacts/rendered-corpora/repeatability-v1", "artifacts/results/repeatability-v1"),
        ("validation-holdout-v1", "validacijski holdout", "artifacts/rendered-corpora/validation-holdout-v1", "artifacts/features/clean-run-v1-validation-holdout"),
        ("confirmatory-skew-v1", "potvrdni skew panel", "artifacts/rendered-corpora/confirmatory-skew-v1", "artifacts/features/confirmatory-skew-v1"),
        ("stats-ceb-semantic-v2b-holdout", "vanjski semantic holdout", "artifacts/rendered-corpora/stats-ceb-semantic-v2b-holdout", "artifacts/features/stats-ceb-semantic-v2b-holdout"),
        ("stats-ceb-full-no-refit-v1", "puni STATS-CEB audit", "artifacts/rendered-corpora/stats-ceb-full-no-refit-v1", "artifacts/features/stats-ceb-full-no-refit-v1"),
        ("pressure-raw-v1-n3-colocation-holdout", "historijski N3 colocation holdout", "artifacts/rendered-corpora/pressure-raw-v1-n3-colocation-holdout", "artifacts/results/pressure-actionability-v1"),
    ]
    for _, _, sql_root, result_root in rows:
        if not (ROOT / sql_root).exists():
            raise ValueError(f"Missing rendered corpus root: {sql_root}")
        if not (ROOT / result_root).exists():
            raise ValueError(f"Missing corpus result root: {result_root}")
    fields = ["corpus_id", "role", "rendered_sql_root", "result_root"]
    write_csv(ROOT / "corpora/corpus-index.csv", [dict(zip(fields, row)) for row in rows], fields)
    table = [
        "# Eksperimentalni corpusi",
        "",
        "Ovaj direktorij povezuje naziv corpusa sa tačnim SQL ulazom i rezultatom.",
        "Interni razvojni manifesti ostaju u izvornom snapshotu, dok su ovdje izdvojeni",
        "samo corpusi potrebni za čitanje i provjeru rada.",
        "",
        "| Corpus | Uloga | SQL | Rezultat |",
        "| --- | --- | --- | --- |",
    ]
    for corpus, role, sql_root, result_root in rows:
        table.append(f"| `{corpus}` | {role} | [`SQL`](../{sql_root}) | [`izlaz`](../{result_root}) |")
    table.extend([
        "",
        "Mašinski čitljiva verzija tabele je u [`corpus-index.csv`](corpus-index.csv).",
        "Pojedinačne SQL instance mogu se tražiti kroz [`queries/`](../queries/).",
    ])
    (ROOT / "corpora/README.md").write_text(
        unwrap_prose("\n".join(table) + "\n"), encoding="utf-8"
    )


def main() -> int:
    build_queries()
    build_datasets()
    build_corpora()
    print("[navigation] queries=90 datasets=packaged corpora=14")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
