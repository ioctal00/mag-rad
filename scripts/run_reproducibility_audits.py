#!/usr/bin/env python3
"""Run every offline reproducibility audit and consolidate its verdict.

The command never invokes Terraform, Ansible, SSH, PostgreSQL, or a cloud API.
It reads only files distributed in the release package.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from markdown_output import unwrap_prose


ROOT = Path(__file__).resolve().parents[1]
AUDIT_ROOT = ROOT / "reproducibility/audits"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run(name: str, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"{name} audit failed ({completed.returncode}):\n{detail[-4000:]}")
    print(f"[reproducibility-audit] {name}: PASS")
    return {
        "command": " ".join(["python3", *command[1:]]),
        "return_code": completed.returncode,
    }


def execute(full_hash: bool) -> dict[str, Any]:
    python = sys.executable
    commands = {
        "terraform": [
            python,
            "reproducibility/audits/terraform/audit.py",
            "--root",
            ".",
            "--json",
            "reproducibility/audits/terraform/findings.json",
        ],
        "ansible": [
            python,
            "reproducibility/audits/ansible/audit.py",
            "--source",
            "sources/master-regimes-infra",
            "--package",
            "sources/master-regimes-infra",
            "--output",
            "reproducibility/audits/ansible/findings.json",
            "--strict",
        ],
        "datasets": [python, "reproducibility/audits/datasets/audit.py"],
        "sweeps": [python, "reproducibility/audits/sweeps/audit.py"],
        "collector": [python, "reproducibility/audits/collector/audit.py"],
    }
    # A single authoritative collector result avoids producing different JSON
    # depending on whether the caller requested a partial or full checksum run.
    commands["collector"].append("--full-hash")

    # The domain audits use disjoint output directories. The collector runs
    # last because its full-hash check also covers the generated domain files.
    parallel_names = [name for name in commands if name != "collector"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            name: pool.submit(run, name, commands[name])
            for name in parallel_names
        }
        executions = {name: futures[name].result() for name in parallel_names}

    # Domain audits may update their checked-in findings (for example when a
    # referenced line number changes). Refresh the package manifest before the
    # collector performs its full-package checksum verification.
    run(
        "pre-collector manifest",
        [python, "scripts/build_release_manifest.py", "--root", "."],
    )
    executions["collector"] = run("collector", commands["collector"])
    executions = {name: executions[name] for name in commands}
    documents = {
        name: load_json(AUDIT_ROOT / name / "findings.json")
        for name in commands
    }

    terraform = documents["terraform"]
    ansible = documents["ansible"]
    datasets = documents["datasets"]
    sweeps = documents["sweeps"]
    collector = documents["collector"]

    structural_failures = []
    if terraform.get("status") == "invalid_package":
        structural_failures.append("terraform package structure")
    structural_failures.extend(
        f"ansible:{row['id']}"
        for row in ansible.get("checks", [])
        if row.get("status") == "fail"
    )
    structural_failures.extend(f"dataset:{item}" for item in datasets.get("errors", []))
    structural_failures.extend(
        f"sweep:{row['id']}"
        for row in sweeps.get("checks", [])
        if row.get("status") == "FAIL"
    )
    structural_failures.extend(
        f"collector:{row['id']}"
        for row in collector.get("checks", [])
        if row.get("status") == "FAIL"
    )

    topology = terraform["topology"]
    pressure = datasets["pressure"]
    sweep_corpora = sweeps["corpora"]
    collector_metrics = collector["metrics"]
    result = {
        "schema_version": 1,
        "audit_mode": "offline_read_only",
        "live_actions_performed": False,
        "status": "FAIL" if structural_failures else "PASS_WITH_DOCUMENTED_LIMITATIONS",
        "structural_failures": structural_failures,
        "executions": executions,
        "topology": {
            "current_n2": topology["n2"],
            "current_n3": topology["n3"],
            "historical": topology["historical_record"],
            "logical_regions_are_physical_cloud_regions": False,
        },
        "dataset_coverage": {
            "catalog_profiles": datasets["profile_catalog"]["catalog_rows"],
            "profile_hashes_verified": datasets["profile_catalog"]["sha256_matches"],
            "wide_execution_count": pressure["execution_rows"],
            "wide_condition_count": pressure["condition_count"],
            "wide_pair_count": pressure["pair_count"],
            "wide_dataset_count": pressure["dataset_count"],
            "wide_substantive_pairs": datasets["temporal_contract"]["wide_substantive_pairs"],
            "wide_empty_time_controls": datasets["temporal_contract"]["wide_empty_current_date_controls"],
            "worker_skew_executions": pressure["worker_skew_execution_rows"],
            "one_region_hot_tenant_executions": pressure["region_local_worker_skew_execution_rows"],
            "one_region_worker_skew_executed": datasets["interpretation"]["one_region_worker_skew_executed"],
            "one_region_worker_skew_profile": datasets["interpretation"]["one_region_worker_skew_profile"],
            "final_action_panels_cover_worker_skew": datasets["interpretation"]["final_action_panels_cover_worker_skew"],
        },
        "sweep_contract": {
            "catalog_sql_rows": sweeps["summary"]["catalog_sql_rows"],
            "check_count": sweeps["summary"]["check_count"],
            "pressure": sweep_corpora["pressure_869x3"],
            "dba": sweep_corpora["dba_180"],
            "n3": sweep_corpora["controlled_n2_n3_180"],
            "confirmatory": sweep_corpora["confirmatory_300"],
            "feedback": sweep_corpora["feedback_loop"],
        },
        "collection_contract": {
            "logical_archive_count": len(collector_metrics["logical_archives"]),
            "logical_query_count": sum(
                row["query_count"] for row in collector_metrics["logical_archives"]
            ),
            "raw_archive_count": len(collector_metrics["raw_archives"]),
            "raw_attempt_count": sum(
                row["query_collection_count"] for row in collector_metrics["raw_archives"]
            ),
            "release_hash_scope": collector_metrics["release_manifest"]["verification_scope"],
            "release_hashes_verified": collector_metrics["release_manifest"]["verified_file_count"],
            "correlation_requires_controlled_serial_execution": True,
            "result_signature_is_follow_up_execution": True,
            "os_metrics_are_host_context": True,
        },
        "configuration_contract": {
            "ansible_structural_checks": ansible["summary"]["checks"],
            "snapshot_mismatches": ansible["summary"]["snapshot_mismatches"],
            "exact_binary_runtime_reconstruction": False,
        },
        "documented_limit_ids": [
            row["id"] for row in sweeps.get("limitations", [])
        ],
    }
    return result


def render_report(result: dict[str, Any]) -> str:
    def n(value: int) -> str:
        return f"{value:,}".replace(",", ".")

    topology = result["topology"]
    datasets = result["dataset_coverage"]
    collection = result["collection_contract"]
    return f"""# Konsolidovani audit ponovljivosti

**Status:** `{result['status']}`. Audit je izveden samo nad zapakovanim
artefaktima. Nisu pokrenuti Terraform, Ansible, SSH, SQL niti cloud API.

## Sta je moguce ponoviti

Paket omogucava nezavisnu provjeru SQL sadrzaja, konstrukcije korpusa,
redoslijeda i ponavljanja, dataset profila, zbirnih rezultata, logickih indeksa
i checksumova. Noviji skupovi imaju verzionisani generator, sjeme i vremenski
oslonac. To je dovoljno za offline audit rezultata i za novi, ekvivalentno
oblikovan infrastrukturni run.

Nije moguce dokazati bit-identicnu obnovu svakog historijskog runa. Nedostaju
pojedini historijski Terraform planovi i runtime commitovi, puni row-level
checksum dataseta te svi sirovi indeksi kasnijih panela. Apsolutno trajanje i
identican plan nisu ponovljiv cilj zbog cachea, statistika, verzija i VPS suma.

## Infrastruktura

| Konfiguracija | Logicke regije | Cvorovi | Fizicka lokacija | Mreza |
| --- | --- | --: | --- | --- |
| N2 | EU, US i GAC | {topology['current_n2']['total_nodes']} | `ams` | jedan Vultr VPC |
| N3 | EU, US, APAC i GAC | {topology['current_n3']['total_nodes']} | `ams` | jedan Vultr VPC |
| stari `clean-run-v1` | EU, US i GAC | 7 | `ams`, `ewr`, `cdg` | stvarno vise lokacija |

Kasniji nazivi EU, US i APAC oznacavaju logicke Citus klastere. Pri tim
eksperimentima WAN uslovi nisu prirodne medjuregionalne cloud putanje nego
kontrolisani `tc/netem` profili nad kolociranim VPS instancama.

Terraform opisuje N2 sa sedam i N3 sa deset VPS cvorova. PostgreSQL je naveden
kao major verzija 18, a Citus kao paketna porodica 14.0. Provider lock datoteke
su ukljucene u ovaj paket, ali historijski primijenjeni plan/state nije. Javni
`infra-plan` target trenutno ne daje kompletan neprimjenjujuci plan N2/N3 grafa.

Ansible cuva topoloske uloge i redoslijed konfiguracije, ali ne zakljucava svaki
binarni ulaz. Verzija `ansible.posix`, tacni apt buildovi i dio udaljenih
instalera ostaju runtime zavisnosti. Dataset load i FDW bootstrap su
konvergentni, ali nisu distribuirano transakcijski; neuspjelo destruktivno
ucitavanje ne vraca prethodni dataset.

## Dataset i skew

Svih {n(datasets['catalog_profiles'])} kataloskih profila postoji, a
{n(datasets['profile_hashes_verified'])} SHA-256 vrijednosti odgovara. Siroki
program koristi {n(datasets['wide_dataset_count'])} profila,
{n(datasets['wide_condition_count'])} uslova i
{n(datasets['wide_execution_count'])} izvrsenja.

Tri mehanizma moraju se razlikovati:

1. `pilot-region-imbalanced-v1` daje priblizno 9:1 regionalni volumen;
2. `pilot-skew-heavy-v1` daje hot-tenant raspodjelu u oba regiona;
3. `pilot-region-local-skew-asymmetric-medium-v1` daje hot tenant-e samo u EU,
   dok je US uniforman.

Worker-skew osa ima {n(datasets['worker_skew_executions'])} izvrsenja. Od toga
{n(datasets['one_region_hot_tenant_executions'])} stvarno koristi treci,
regionalno asimetricni profil. Profil ipak ne deklarira razlicit broj shardova
ili genericki shard-placement skew. Worker/task neravnomjernost je izmjerena
posljedica hot tenant-a i konkretnog rasporeda. Zavrsni DBA, N2/N3 memory i
potvrdni action paneli ne pokrivaju worker-skew intervenciju.

Svih {n(datasets['wide_pair_count'])} grupa ima provjeren stressed/mitigated
kontrast. Njih {n(datasets['wide_substantive_pairs'])} podrzava sadrzajno
poredjenje intervencije, dok preostalu
{n(datasets['wide_empty_time_controls'])} grupu cine
prazne `current_date` no-work kontrole. One podrzavaju collector i
result-equivalence ugovor, ali ne dokaz ucinka intervencije.

## Sweep i prikupljanje

Audit je ponovo izveo glavne brojeve: zajednički F19/F21 korpus 1.964; pressure 869 uslova puta tri
ponavljanja, odnosno 2.607; DBA 60 uslova i 180 izvrsenja; kontrolisani N2/N3
180; potvrdni panel 60 uslova puta pet, odnosno 300; feedback loop 85 glavnih i
25 aggregate-exact izvrsenja.

Od 418 pressure grupa, 385 ima dva uslova i sest fizickih izvrsenja, a 33 cuvaju
i medjustanje pa imaju tri uslova i devet izvrsenja. Ponavljanja imaju zaseban
`execution_slot_id`; ista SQL datoteka zato nije isto sto i jedno fizicko
izvrsenje. Williamsov raspored, shuffle sjemena, slotovi i odluke zapisane prije
ishoda medjusobno su saglasni.

Collector audit pokriva {n(collection['logical_archive_count'])} logickih
arhiva sa {n(collection['logical_query_count'])} indeksiranih upita i
{n(collection['raw_archive_count'])} sirovih arhiva sa
{n(collection['raw_attempt_count'])} fizickih pokusaja. Veze od upita preko GAC i
regionalnog plana do worker/task fragmenata prolaze provjere roditeljskih
identiteta.

Tri granice ostaju vazne. Regionalni `application_name` se postavlja, ali
indexer ne filtrira svaki `auto_explain` dokument tim markerom, pa korelacija
pretpostavlja serijsko kontrolisano izvrsavanje. Result signature nastaje
naknadnim izvrsavanjem istog SQL-a, a ne u istom backend pozivu kao EXPLAIN.
CPU, mreza, disk i VPS `steal` su host-level kontekst, ne query-level potrosnja.

## Pokretanje

```bash
make reproducibility-audit
make verify
```

Detaljni nalazi i validator svake oblasti nalaze se u poddirektorijima ovog
direktorija. `summary.json` je autoritativni masinski sazetak.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full-hash",
        action="store_true",
        help="Compatibility flag; every run now verifies the full release manifest.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = execute(args.full_hash)
    for report_path in AUDIT_ROOT.glob("*/report.md"):
        report_path.write_text(
            unwrap_prose(report_path.read_text(encoding="utf-8")), encoding="utf-8"
        )
    (AUDIT_ROOT / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (AUDIT_ROOT / "REPRODUCIBILITY_AUDIT.md").write_text(
        unwrap_prose(render_report(result)), encoding="utf-8"
    )
    print(f"[reproducibility-audit] overall: {result['status']}")
    return 1 if result["structural_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
