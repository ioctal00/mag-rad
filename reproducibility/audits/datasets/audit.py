#!/usr/bin/env python3
"""Offline audit of thesis dataset reproducibility and executed coverage.

The validator reads only the curated reproducibility package and its embedded
source snapshots.  It never connects to PostgreSQL, SSH, Terraform, or cloud
APIs.  Run it from any directory; outputs are written beside this script.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import tarfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
DATASET_CATALOG = ROOT / "reproducibility/dataset-catalog.csv"
QUERY_CATALOG = ROOT / "reproducibility/query-catalog.csv"
PROFILES = ROOT / "sources/master-regimes/datasets/profiles"
PRESSURE = ROOT / "artifacts/rendered-corpora/pressure-raw-v1"
TEMPORAL = ROOT / "releases/temporal-validity-audit-v1/temporal_validity_audit.json"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def scalar(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^\s*{re.escape(key)}:\s*([^#\n,}}]+)", text)
    if match:
        return match.group(1).strip().strip("'\"")
    match = re.search(rf"\b{re.escape(key)}:\s*([^,}}]+)", text)
    return match.group(1).strip().strip("'\"") if match else None


def profile_snapshot(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    region_ranges: dict[str, list[int]] = {}
    current_region: str | None = None
    for line in text.splitlines():
        inline = re.match(
            r"^\s{2}([a-z][a-z0-9_]*):\s*\{[^}]*tenant_id_range:\s*\[(\d+),\s*(\d+)\]",
            line,
        )
        if inline:
            region_ranges[inline.group(1)] = [int(inline.group(2)), int(inline.group(3))]
            continue
        region = re.match(r"^\s{2}([a-z][a-z0-9_]*):\s*$", line)
        if region:
            current_region = region.group(1)
            continue
        tenant_range = re.match(r"^\s+tenant_id_range:\s*\[(\d+),\s*(\d+)\]", line)
        if tenant_range and current_region:
            region_ranges[current_region] = [int(tenant_range.group(1)), int(tenant_range.group(2))]

    def truth(key: str) -> bool | None:
        value = scalar(text, key)
        if value is None:
            return None
        return value.lower() == "true"

    return {
        "dataset_id": scalar(text, "dataset_id"),
        "seed": scalar(text, "seed"),
        "base_time_unix": scalar(text, "base_time_unix"),
        "lookback_days": scalar(text, "lookback_days"),
        "shard_count": scalar(text, "shard_count"),
        "region_ranges": region_ranges,
        "supports_region_imbalance": truth("supports_region_imbalance"),
        "supports_hot_tenant_skew": truth("supports_hot_tenant_skew"),
        "supports_region_local_skew_asymmetry": truth("supports_region_local_skew_asymmetry"),
        "supports_shard_skew": truth("supports_shard_skew"),
    }


def read_archived_loads(archive: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith("dataset_load_manifest.json"):
                continue
            stream = tar.extractfile(member)
            if stream is None:
                continue
            document = json.load(stream)
            env = document.get("datagen_env", {})
            found.append(
                {
                    "archive": str(archive.relative_to(ROOT)),
                    "member": member.name,
                    "dataset_id": document.get("dataset_id"),
                    "region": document.get("region"),
                    "base_time_unix": env.get("DATAGEN_BASE_TIME_UNIX"),
                    "seed": env.get("DATAGEN_RANDOM_SEED"),
                    "lookback_days": env.get("DATAGEN_LOOKBACK_DAYS"),
                    "distribution": env.get("DATAGEN_DISTRIBUTION"),
                    "hot_tenant_pct": env.get("DATAGEN_HOT_TENANT_PCT"),
                    "hot_event_pct": env.get("DATAGEN_HOT_EVENT_PCT"),
                    "tenant_start": env.get("DATAGEN_TENANT_START"),
                    "tenant_end": env.get("DATAGEN_TENANT_END"),
                    "shard_count": document.get("effective_distribution", {}).get("shard_count"),
                }
            )
    return found


def packaged_profile_reference_audit() -> dict[str, Any]:
    pattern = re.compile(r"(?P<ref>(?:\.\./)+datasets/profiles/(?P<name>[A-Za-z0-9_.-]+\.ya?ml))")
    total = broken = fallback = 0
    examples: list[dict[str, str]] = []
    corpus_root = ROOT / "artifacts/rendered-corpora"
    for path in sorted(corpus_root.rglob("*")):
        if path.suffix not in {".yml", ".yaml", ".json"} or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in pattern.finditer(text):
            total += 1
            original = (path.parent / match.group("ref")).resolve()
            if original.exists():
                continue
            broken += 1
            replacement = PROFILES / match.group("name")
            if replacement.exists():
                fallback += 1
            if len(examples) < 8:
                examples.append(
                    {
                        "source": str(path.relative_to(ROOT)),
                        "reference": match.group("ref"),
                        "source_snapshot_fallback": str(replacement.relative_to(ROOT)) if replacement.exists() else "missing",
                    }
                )
    return {
        "references_scanned": total,
        "broken_at_original_relative_location": broken,
        "resolved_by_source_snapshot_basename": fallback,
        "content_missing_after_fallback": broken - fallback,
        "examples": examples,
    }


def make_report(result: dict[str, Any]) -> str:
    blocks = result["evidence_blocks"]
    lines = [
        "# Audit ponovljivosti skupova podataka i stvarnog eksperimentalnog obuhvata",
        "",
        f"**Status:** `{result['status']}`. Audit je potpuno offline; SQL i infrastruktura nisu pokretani.",
        "",
        "## Sažetak",
        "",
        "Glavni empirijski blokovi ne koriste jedan homogeni skup podataka. Zajednički karakterizacijski korpus modela F19 i F21 koristi dvije pilot varijante, sirovi intervencijski program koristi 13 profila, završni DBA panel koristi četiri balansirana profila, a kontrolisani N2/N3 i potvrdni panel koriste posebne topology-isolation parove. To je metodološki prihvatljivo samo ako se zaključci ograniče na ulogu svakog bloka.",
        "",
        "Postoji stvarno izvršen slučaj u kojem je **EU logički region imao hot-tenant raspodjelu, a US region balansiranu raspodjelu**. To je `pilot-region-local-skew-asymmetric-medium-v1`. Profil ima jednak broj tenant-a u oba regiona, ali EU nosi 5% hot tenant-a sa 65% događaja, dok je US uniforman. Ovaj slučaj je prisutan u companion korpusu i u wide worker-data-skew osi. Ipak, profil ne deklarira generički `supports_shard_skew`; termin _worker skew_ ovdje opisuje opaženu posljedicu hot tenant-a i njihovog shard/task rasporeda, a ne različit broj shardova po regionu [sources/master-regimes/datasets/profiles/pilot-region-local-skew-asymmetric-medium.yml:13-28, 38-43, 77-92; artifacts/rendered-corpora/pressure-raw-v1/execution_matrix.csv: redovi sa `dataset_profile_id=pilot-region-local-skew-asymmetric-medium-v1` i `pressure_axis=worker_data_skew`].",
        "",
        "## Skupovi po dokaznom bloku",
        "",
        "| Dokazni blok | Stvarno korišteni skupovi | Jedinice u paketu | Ugovor ponovnog učitavanja |",
        "| --- | --- | --: | --- |",
    ]
    order = [
        "characterization_corpus",
        "wide_intervention_corpus",
        "final_dba_panel",
        "controlled_topology_memory_panel",
        "confirmatory_action_panel",
        "longitudinal_feedback_loop",
        "controlled_skew_validation",
    ]
    labels = {
        "characterization_corpus": "Zajednički F19/F21 karakterizacijski korpus",
        "wide_intervention_corpus": "Široki intervencijski korpus",
        "final_dba_panel": "Završni DBA panel",
        "controlled_topology_memory_panel": "Kontrolisani N2/N3 panel",
        "confirmatory_action_panel": "Potvrdni action panel",
        "longitudinal_feedback_loop": "Longitudinalni feedback loop",
        "controlled_skew_validation": "Potvrdna skew provjera",
    }
    contracts = {
        "characterization_corpus": "Slabiji: arhivirani load manifesti imaju `base_time=0`; tačan savremeni reload nije garantovan.",
        "wide_intervention_corpus": "Jak za 397 sadržajnih parova; 21 `current_date` para su samo prazne no-work kontrole.",
        "final_dba_panel": "Fiksni profil, sjeme, `base_time`, shard count i SQL cutoff.",
        "controlled_topology_memory_panel": "Fiksni upareni N2/N3 profili; isti logički podaci se razdvajaju na tri fizička regiona.",
        "confirmatory_action_panel": "Najjači ugovor: jedan fiksni N3 profil i pet ponavljanja svakog uslova.",
        "longitudinal_feedback_loop": "Interni before/after audit je jak, ali izvorno ime profila, sjeme i shard count nisu zabilježeni.",
        "controlled_skew_validation": "Fiksni pilot profili; razlikuje placement kontrast od regionalnog volumena.",
    }
    for key in order:
        block = blocks[key]
        datasets = ", ".join(f"`{name}` ({count})" for name, count in block["dataset_catalog_rows"].items())
        lines.append(f"| {labels[key]} | {datasets} | {block['catalog_row_count']} kataloških redova | {contracts[key]} |")

    lines.extend(
        [
            "",
            "Broj kataloških redova nije uvijek broj fizičkih izvršenja. Na primjer, potvrdni panel ima 60 SQL-uslov instanci, ali pet ponavljanja, odnosno 300 izvršenja; završni DBA panel ima 60 SQL-uslov instanci i 180 izvršenja. Autoritativni zbirni brojevi su u [reproducibility/evidence-blocks.json:1-53].",
            "",
            "## Parametri i raspodjele",
            "",
            "- Većina novijih sintetičkih profila koristi `base_time_unix=1782864000` (`2026-07-01 00:00:00 UTC`) i `lookback_days=30`. Sjeme 42 koristi pilot porodica, 73 raw i large topology-isolation porodica, 142 medium N3, a 242 large/xlarge N3 porodica [reproducibility/dataset-catalog.csv:3-30].",
            "- Shard count varira sa veličinom: 16, 32 ili 64. Prazna polja za topology-isolation profile u katalogu su greška ekstrakcije iz inline YAML zapisa; sami profili sadrže vrijednosti, npr. 64 za large N3 [reproducibility/dataset-catalog.csv:23-30; sources/master-regimes/datasets/profiles/topology-isolation-large-n3.yml:21].",
            "- `pilot-region-imbalanced-v1` ima EU:US tenant raspon 1800:200 uz balansiranu raspodjelu unutar tenant-a. To je region-level data imbalance, ne hot-tenant ili worker/shard skew [sources/master-regimes/datasets/profiles/pilot-region-imbalanced.yml:13-22, 32-37, 53-60].",
            "- `pilot-skew-heavy-v1` raspoređuje hot tenant-e u cijelom dvoregionalnom profilu. `pilot-region-local-skew-asymmetric-medium-v1` je posebna varijanta u kojoj je EU skewed, a US balanced [sources/master-regimes/datasets/profiles/pilot-region-local-skew-asymmetric-medium.yml:13-28].",
            "- N3 topology-isolation profili nisu 1:1:1 volumenski balansirani po fizičkom regionu: large N3 je 2000:1000:1000 tenant-a. To čuva isti logički N2 skup tako što se raniji US raspon dijeli između US i APAC, a ne uvodi hot-tenant skew [sources/master-regimes/datasets/profiles/topology-isolation-large-n2.yml:13-20; sources/master-regimes/datasets/profiles/topology-isolation-large-n3.yml:13-21, 29-34].",
            "",
            "## Stvarni obuhvat worker i regionalne neravnoteže",
            "",
            f"Wide matrica sadrži {result['pressure']['worker_skew_execution_rows']} izvršenja na osi `worker_data_skew`, od čega {result['pressure']['region_local_worker_skew_execution_rows']} koristi EU-only hot-tenant profil. To odgovara 140 konfiguracija, 70 kontrafaktualnih parova i sedam dataset profila navedenih u manifest auditu [artifacts/rendered-corpora/pressure-raw-v1/manifest_coverage_audit.json:143-171].",
            "",
            "Potvrdni skew panel ne treba opisivati kao još jedan EU-only slučaj. Njegove B/C faze koriste globalni `pilot-skew-heavy` i mijenjaju raspored hot shardova u oba regiona, dok faza D koristi 9:1 regionalni volumen. Time se odvojeno provjeravaju placement-sensitive worker skew i region-level imbalance [reproducibility/query-catalog.csv: redovi sa `evidence_block=controlled_skew_validation`].",
            "",
            "Završni DBA, N2/N3 topology-memory i potvrdni action panel ne koriste hot-tenant/skew profile. Zato njihove action-selection tvrdnje ne obuhvataju worker-skew intervencije [reproducibility/query-catalog.csv: redovi za `final_dba_panel`, `controlled_topology_memory_panel` i `confirmatory_action_panel`].",
            "",
            "## Ponovljivost i granice valjanosti",
            "",
            "1. **Zajednički korpus modela F19 i F21 nije tačno temporalno ponovljiv današnjim ponovnim pokretanjem.** Arhivirani load manifesti imaju `DATAGEN_BASE_TIME_UNIX=0`; generator tada koristi zidni sat. Ipak, arhivirane analize ostaju deskriptivno upotrebljive jer su dataset i SQL u svakom sweepu dijelili isti vremenski oslonac, lag je bio ograničen i NMI sa vremenskim kvartilom je približno nula za oba modela [releases/temporal-validity-audit-v1/temporal_validity_audit.json; sources/citus-datagen/tools/cpp/citus_datagen.cpp:313-317, 428-459].",
            "2. **Wide rezultat nije jednako jak za svih 418 parova.** Svih 418 je rezultatski ekvivalentno, ali 21 `current_date` par je prazna no-work negativna kontrola; 397 parova podržava sadržajna poređenja intervencija [releases/temporal-validity-audit-v1/temporal_validity_audit.json:77-96].",
            "3. **Feedback-loop snapshot nije moguće tačno reloadati iz samog paketa.** `base_time` i lookback su sačuvani, ali izvorno ime profila, sjeme i shard count nisu [reproducibility/dataset-catalog.csv:2; reproducibility/README.md:63-70]. To ne poništava before/after nalaz na istom snapshotu, ali ograničava bit-for-bit reprodukciju dataseta.",
            "4. **Nema row-level checksum cijelog sintetičkog dataseta.** Paket čuva profile, hash profila, SQL hashove i generator source snapshot, ali ne i dump ili checksum svakog reda. Ponovno generisanje je determinističko samo kada su originalni commit generatora, profil, sjeme, `base_time` i način učitavanja poznati [reproducibility/evidence-blocks.json:48-53].",
            "5. **Pripremljeno nije isto što i izvršeno.** Combined holdout, N3 holdout i sentinel batch širokog programa nisu dio 2.607 izvršenja; manifest ih označava kao `prepared_not_executed` ili blokirane [artifacts/rendered-corpora/pressure-raw-v1/manifest_coverage_audit.json:257-296].",
            "",
            "## Integritet paketa za provjeru i ponovno izvođenje",
            "",
            f"Svih {result['profile_catalog']['catalog_rows']} kataloških profila ima dostupan sadržaj i odgovarajući SHA-256. Validator je pronašao {result['profile_references']['broken_at_original_relative_location']} relativnih referenci koje više ne rade iz kurirane lokacije renderovanog korpusa; svih {result['profile_references']['resolved_by_source_snapshot_basename']} može se razriješiti po istom nazivu u `sources/master-regimes/datasets/profiles/`. To je problem prenosivosti putanje, ne nestao dataset profil.",
            "",
            "Vanjski STATS/CEB dump nije ugrađen u paket, ali je izvor zaključan Zenodo identifikatorom i checksumovima [sources/master-regimes/external/stats-ceb/source-lock.yml:1-33].",
            "",
            "## Pokretanje",
            "",
            "```bash",
            "python3 reproducibility/audits/datasets/audit.py",
            "```",
            "",
            "Skripta ponovo generiše `findings.json` i ovaj izvještaj. Izlazni status `PASS_WITH_WARNINGS` znači da su autoritativni katalozi i brojevi konzistentni, ali da postoje dokumentovane granice tačnog ponovnog učitavanja i prenosivosti paketa.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    catalog = rows(DATASET_CATALOG)
    query_catalog = rows(QUERY_CATALOG)

    profile_details: dict[str, dict[str, Any]] = {}
    hash_ok = 0
    missing_profiles: list[str] = []
    hash_mismatches: list[str] = []
    shard_catalog_gaps: list[str] = []
    for item in catalog:
        path = ROOT / item["profile_path"]
        if not path.exists():
            missing_profiles.append(item["dataset_id"])
            continue
        actual = digest(path)
        if actual != item["profile_sha256"]:
            hash_mismatches.append(item["dataset_id"])
        else:
            hash_ok += 1
        if path.suffix in {".yml", ".yaml"} and "datasets/profiles" in item["profile_path"]:
            snapshot = profile_snapshot(path)
            profile_details[item["dataset_id"]] = snapshot
            if not item["shard_count"] and snapshot.get("shard_count"):
                shard_catalog_gaps.append(item["dataset_id"])

    if missing_profiles:
        errors.append(f"Missing cataloged profile content: {missing_profiles}")
    if hash_mismatches:
        errors.append(f"Profile SHA-256 mismatch: {hash_mismatches}")
    if shard_catalog_gaps:
        warnings.append(f"Dataset catalog omitted inline YAML shard_count for: {shard_catalog_gaps}")

    by_block: dict[str, Counter[str]] = defaultdict(Counter)
    query_rows_by_dataset: Counter[str] = Counter()
    for item in query_catalog:
        by_block[item["evidence_block"]][item["dataset_profile_id"]] += 1
        query_rows_by_dataset[item["dataset_profile_id"]] += 1
    evidence_blocks = {
        block: {
            "catalog_row_count": sum(counts.values()),
            "dataset_catalog_rows": dict(sorted(counts.items())),
        }
        for block, counts in sorted(by_block.items())
    }
    catalog_ids = {item["dataset_id"] for item in catalog}
    uncataloged_query_datasets = sorted(set(query_rows_by_dataset) - catalog_ids)
    if uncataloged_query_datasets:
        errors.append(f"Query catalog refers to uncataloged datasets: {uncataloged_query_datasets}")
    for item in catalog:
        expected_rows = int(item["query_catalog_rows"])
        observed_rows = query_rows_by_dataset[item["dataset_id"]]
        if expected_rows != observed_rows:
            errors.append(
                f"Dataset query row count mismatch for {item['dataset_id']}: "
                f"catalog={expected_rows}, query_catalog={observed_rows}"
            )

    local_profile = profile_details["pilot-region-local-skew-asymmetric-medium-v1"]
    if not (
        local_profile["region_ranges"] == {"eu": [1, 800], "us": [10001, 10800]}
        and local_profile["supports_hot_tenant_skew"] is True
        and local_profile["supports_region_local_skew_asymmetry"] is True
        and local_profile["supports_region_imbalance"] is False
        and local_profile["supports_shard_skew"] is False
    ):
        errors.append("Region-local skew profile no longer has the audited EU-only asymmetry contract")
    imbalance_profile = profile_details["pilot-region-imbalanced-v1"]
    if not (
        imbalance_profile["region_ranges"] == {"eu": [1, 1800], "us": [10001, 10200]}
        and imbalance_profile["supports_region_imbalance"] is True
        and imbalance_profile["supports_hot_tenant_skew"] is False
        and imbalance_profile["supports_shard_skew"] is False
    ):
        errors.append("Region-imbalanced profile no longer has the audited 9:1 balanced-within-region contract")
    topology_large_n3 = profile_details["topology-isolation-large-n3-v1"]
    if topology_large_n3["region_ranges"] != {
        "eu": [1, 2000],
        "us": [10001, 11000],
        "apac": [11001, 12000],
    }:
        errors.append("Large N3 topology-isolation region ranges changed")

    matrix = rows(PRESSURE / "execution_matrix.csv")
    pressure_conditions = {item["condition_id"] for item in matrix}
    pressure_pairs = {item["pair_id"] for item in matrix if item["pair_id"]}
    pressure_datasets = {item["dataset_profile_id"] for item in matrix}
    worker_rows = [item for item in matrix if item["pressure_axis"] == "worker_data_skew"]
    local_worker_rows = [
        item for item in worker_rows
        if item["dataset_profile_id"] == "pilot-region-local-skew-asymmetric-medium-v1"
    ]
    as_of_values: Counter[str] = Counter()
    for item in matrix:
        try:
            params = json.loads(item["param_json"])
        except json.JSONDecodeError:
            continue
        if "as_of_unix" in params:
            as_of_values[str(params["as_of_unix"])] += 1

    summary = load_json(PRESSURE / "program_summary.json")
    expected = {
        "execution_rows": 2607,
        "conditions": 869,
        "pairs": 418,
        "datasets": 13,
        "worker_rows": 420,
        "region_local_worker_rows": 60,
    }
    observed = {
        "execution_rows": len(matrix),
        "conditions": len(pressure_conditions),
        "pairs": len(pressure_pairs),
        "datasets": len(pressure_datasets),
        "worker_rows": len(worker_rows),
        "region_local_worker_rows": len(local_worker_rows),
    }
    for key, value in expected.items():
        if observed[key] != value:
            errors.append(f"Pressure matrix {key}: expected {value}, observed {observed[key]}")
    if summary.get("physical_execution_count") != 2607:
        errors.append("program_summary physical_execution_count is not 2607")
    if as_of_values != Counter({"1782864000": 2607}):
        errors.append(f"Wide matrix as_of_unix is not frozen for every row: {dict(as_of_values)}")

    temporal = load_json(TEMPORAL)
    if temporal["legacy_fcm_corpus"]["dataset_base_time_unix_values"] != ["0"]:
        errors.append("Temporal audit no longer records the shared F19/F21 base_time=0")
    if temporal["wide_intervention_program"]["substantive_frozen_or_time_independent_pairs"] != 397:
        errors.append("Temporal audit no longer records 397 substantive wide pairs")
    if temporal["wide_intervention_program"]["dynamic_empty_negative_control_pairs"] != 21:
        errors.append("Temporal audit no longer records 21 empty current_date controls")

    archive_paths = [
        ROOT / "artifacts/raw-attempts/clean-run-v1.tar.gz",
        ROOT / "artifacts/raw-attempts/clean-run-v1-validation-holdout.tar.gz",
        ROOT / "artifacts/raw-attempts/clean-run-v1-region-asymmetry.tar.gz",
        ROOT / "artifacts/raw-attempts/clean-run-v1-region-asymmetry-skew-rerun.tar.gz",
    ]
    archived_loads: list[dict[str, Any]] = []
    for archive in archive_paths:
        if archive.exists():
            archived_loads.extend(read_archived_loads(archive))
        else:
            errors.append(f"Missing archived load evidence: {archive.relative_to(ROOT)}")
    archived_bases = sorted({item["base_time_unix"] for item in archived_loads})
    if archived_bases != ["0"]:
        errors.append(f"Expected archived legacy load base_time only 0, found {archived_bases}")

    local_archived = [
        item for item in archived_loads
        if item["dataset_id"] == "pilot-region-local-skew-asymmetric-medium-v1"
    ]
    local_by_region = {item["region"]: item for item in local_archived}
    if not (
        local_by_region.get("eu", {}).get("distribution") == "hot_tenants"
        and local_by_region.get("us", {}).get("distribution") == "uniform"
    ):
        errors.append("Archived region-local load does not prove EU hot_tenants and US uniform")

    profile_refs = packaged_profile_reference_audit()
    if profile_refs["content_missing_after_fallback"]:
        errors.append("One or more rendered corpus profile references have no packaged source fallback")
    elif profile_refs["broken_at_original_relative_location"]:
        warnings.append(
            f"{profile_refs['broken_at_original_relative_location']} rendered-corpus relative profile references require source-snapshot fallback"
        )

    if any(item["dataset_id"] == "locked_current_dataset_snapshot" for item in catalog):
        warnings.append("Feedback-loop exact original profile, seed and shard count are not recorded")
    warnings.append("No row-level full-dataset checksum or database dump is packaged")
    warnings.append("Exact temporal reload of the shared F19/F21 corpus is weak because archived base_time was wall-clock derived")

    status = "FAIL" if errors else ("PASS_WITH_WARNINGS" if warnings else "PASS")
    result: dict[str, Any] = {
        "audit_id": "dataset-reproducibility-and-coverage-v1",
        "status": status,
        "offline_only": True,
        "sql_executed": False,
        "errors": errors,
        "warnings": warnings,
        "profile_catalog": {
            "catalog_rows": len(catalog),
            "content_present": len(catalog) - len(missing_profiles),
            "sha256_matches": hash_ok,
            "missing_profiles": missing_profiles,
            "hash_mismatches": hash_mismatches,
            "catalog_missing_inline_shard_count": shard_catalog_gaps,
            "parsed_profiles": profile_details,
        },
        "evidence_blocks": evidence_blocks,
        "pressure": {
            "execution_rows": len(matrix),
            "condition_count": len(pressure_conditions),
            "pair_count": len(pressure_pairs),
            "dataset_count": len(pressure_datasets),
            "datasets": sorted(pressure_datasets),
            "worker_skew_execution_rows": len(worker_rows),
            "region_local_worker_skew_execution_rows": len(local_worker_rows),
            "as_of_unix_counts": dict(as_of_values),
            "prepared_not_executed": ["combined_holdout", "n3_holdout", "sentinels"],
        },
        "temporal_contract": {
            "fcm_archived_base_time_values": temporal["legacy_fcm_corpus"]["dataset_base_time_unix_values"],
            "fcm_execution_count": temporal["legacy_fcm_corpus"]["execution_count"],
            "fcm_maximum_lag_hours": temporal["legacy_fcm_corpus"]["maximum_lag_hours"],
            "wide_substantive_pairs": temporal["wide_intervention_program"]["substantive_frozen_or_time_independent_pairs"],
            "wide_empty_current_date_controls": temporal["wide_intervention_program"]["dynamic_empty_negative_control_pairs"],
        },
        "archived_dataset_loads": {
            "manifest_count": len(archived_loads),
            "base_time_values": archived_bases,
            "region_local_skew_loads": local_archived,
            "citations": [
                f"{item['archive']}::{item['member']}:datagen_env"
                for item in local_archived
            ],
        },
        "profile_references": profile_refs,
        "interpretation": {
            "one_region_worker_skew_executed": True,
            "one_region_worker_skew_profile": "pilot-region-local-skew-asymmetric-medium-v1",
            "region_level_imbalance_is_worker_skew": False,
            "hot_tenant_skew_is_generic_shard_count_skew": False,
            "final_action_panels_cover_worker_skew": False,
            "exact_feedback_dataset_reload_guaranteed": False,
            "exact_f19_f21_temporal_reload_guaranteed": False,
            "wide_substantive_pair_validity_retained": True,
        },
        "citations": [
            "reproducibility/dataset-catalog.csv:rows 2-30",
            "reproducibility/query-catalog.csv:identified by evidence_block + dataset_profile_id",
            "artifacts/rendered-corpora/pressure-raw-v1/execution_matrix.csv:identified by execution_slot_id",
            "artifacts/rendered-corpora/pressure-raw-v1/program_summary.json:3-29",
            "artifacts/rendered-corpora/pressure-raw-v1/manifest_coverage_audit.json:143-171,257-296",
            "releases/temporal-validity-audit-v1/temporal_validity_audit.json:13-31,35-96",
            "sources/master-regimes/datasets/profiles/pilot-region-local-skew-asymmetric-medium.yml:13-28,38-43,77-92",
            "sources/master-regimes/datasets/profiles/pilot-region-imbalanced.yml:13-22,32-37,53-60",
            "sources/citus-datagen/tools/cpp/citus_datagen.cpp:313-317,428-459",
        ],
    }

    (OUT / "findings.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "report.md").write_text(make_report(result), encoding="utf-8")
    print(json.dumps({"status": status, "errors": len(errors), "warnings": len(warnings)}, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
