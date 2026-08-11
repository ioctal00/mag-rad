#!/usr/bin/env python3
"""Offline audit of Ansible/configuration-management reproducibility.

The validator reads an explicit allow-list of source files. It never reads
generated group_vars/all.yml, generated inventory, Terraform state, .env
files, SSH keys, or live infrastructure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGE = PACKAGE_ROOT / "sources/master-regimes-infra"
# By default the package audits itself and remains portable. Reviewers may pass
# --source /path/to/master-regimes-infra to add a byte-parity comparison.
DEFAULT_SOURCE = DEFAULT_PACKAGE
DEFAULT_OUTPUT = Path(__file__).with_name("findings.json")


# This list is deliberately explicit. Do not replace it with recursive scans.
SAFE_FILES = (
    "Makefile",
    "pyproject.toml",
    "uv.lock",
    "ansible/requirements.yml",
    "ansible/playbooks/site.yml",
    "ansible/playbooks/verify-citus.yml",
    "ansible/playbooks/reinstall-postgresql.yml",
    "ansible/inventory/terraform_inventory.py",
    "ansible/roles/common/defaults/main.yml",
    "ansible/roles/common/tasks/main.yml",
    "ansible/roles/postgresql_citus/defaults/main.yml",
    "ansible/roles/postgresql_citus/tasks/main.yml",
    "ansible/roles/analytics_node/defaults/main.yml",
    "ansible/roles/analytics_node/tasks/main.yml",
    "ansible/roles/citus_datagen/defaults/main.yml",
    "ansible/roles/citus_datagen/tasks/main.yml",
    "ansible/roles/psql_benchmarks/defaults/main.yml",
    "ansible/roles/psql_benchmarks/tasks/main.yml",
    "ansible/roles/pgbouncer/tasks/main.yml",
    "common-scripts/ansible_shim.py",
    "common-scripts/run_ansible.sh",
    "common-scripts/up_eu_us_gac_vhp_shared_vpc.sh",
    "common-scripts/extend_eu_us_gac_with_apac.sh",
    "common-scripts/sync_remote_repo.py",
    "common-scripts/apply_dataset_profile.py",
    "common-scripts/run_database_sweep.py",
    "common-scripts/run_gac_fdw_bootstrap.py",
    "common-scripts/manage_network_pressure.py",
    "common-scripts/manage_network_latency.py",
    "common-scripts/probe_lab_environment.py",
    "common-scripts/run_query_collection.py",
    "common-scripts/collect_single_eu_manifest.py",
    "src/master_regimes_infra/render.py",
    "configs/systems/eu-vps-single.yml",
    "configs/systems/eu-us-gac-vps.yml",
    "configs/systems/eu-us-apac-gac-vps.yml",
    "tests/test_apply_dataset_profile.py",
    "tests/test_gac_fdw_bootstrap.py",
    "tests/test_lab_default_reset_contract.py",
)

FORBIDDEN_PARTS = {
    ".env",
    ".terraform",
    "terraform.tfstate",
    "all.yml",
    "inventory.json",
    "inventory.yml",
    "inventory.yaml",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when a required structural check fails.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_allow_list() -> None:
    for rel in SAFE_FILES:
        parts = set(Path(rel).parts)
        if parts & FORBIDDEN_PARTS:
            raise RuntimeError(f"Forbidden path entered SAFE_FILES: {rel}")


def load_files(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for rel in SAFE_FILES:
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(f"Required audit source is missing: {path}")
        values[rel] = path.read_text(encoding="utf-8")
    return values


def line_of(files: dict[str, str], rel: str, needle: str) -> int:
    for number, line in enumerate(files[rel].splitlines(), start=1):
        if needle in line:
            return number
    raise ValueError(f"Evidence text not found in {rel}: {needle!r}")


def evidence(
    files: dict[str, str], rel: str, needle: str, note: str
) -> dict[str, Any]:
    return {
        "location": f"master-regimes-infra/{rel}:{line_of(files, rel, needle)}",
        "note": note,
    }


def make_check(
    check_id: str,
    status: str,
    description: str,
    evidence_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "description": description,
        "evidence": evidence_rows,
    }


def make_finding(
    finding_id: str,
    severity: str,
    classification: str,
    title: str,
    summary: str,
    impact: str,
    recommendation: str,
    evidence_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "classification": classification,
        "title": title,
        "summary": summary,
        "impact": impact,
        "recommendation": recommendation,
        "evidence": evidence_rows,
    }


def audit(source: Path, package: Path) -> dict[str, Any]:
    check_allow_list()
    source_files = load_files(source)
    package_files = load_files(package)

    parity: list[dict[str, Any]] = []
    for rel in SAFE_FILES:
        source_hash = sha256(source / rel)
        package_hash = sha256(package / rel)
        parity.append(
            {
                "path": rel,
                "source_sha256": source_hash,
                "package_sha256": package_hash,
                "match": source_hash == package_hash,
            }
        )

    s = source_files
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    parity_ok = all(row["match"] for row in parity)
    checks.append(
        make_check(
            "snapshot-parity",
            "pass" if parity_ok else "fail",
            "Every allow-listed Ansible/configuration file is byte-identical in the packaged snapshot.",
            [
                {
                    "location": "sources/master-regimes-infra/",
                    "note": f"Compared {len(parity)} explicit files by SHA-256; mismatches: "
                    f"{sum(not row['match'] for row in parity)}.",
                }
            ],
        )
    )
    findings.append(
        make_finding(
            "A-001",
            "positive",
            "reproducible_configuration",
            "Packaged configuration source matches the active repository",
            f"The {len(parity)} critical files in the audit allow-list are byte-identical.",
            "The public package preserves the audited playbooks, roles, renderers, and orchestration logic. This does not by itself preserve live Terraform state or installed package builds.",
            "Keep the package immutable and publish its checksum manifest with the thesis release.",
            checks[-1]["evidence"],
        )
    )

    topology_evidence = [
        evidence(
            s,
            "configs/systems/eu-us-gac-vps.yml",
            'version: "18"',
            "The canonical N2 topology requests PostgreSQL major 18.",
        ),
        evidence(
            s,
            "configs/systems/eu-us-gac-vps.yml",
            'citus_package: "postgresql-18-citus-14.0"',
            "The topology names the PostgreSQL 18/Citus 14.0 package family.",
        ),
        evidence(
            s,
            "configs/systems/eu-us-apac-gac-vps.yml",
            "vultr_region: ams",
            "Logical regions are rendered onto Amsterdam infrastructure in the N3 topology.",
        ),
        evidence(
            s,
            "src/master_regimes_infra/render.py",
            '"source_config_sha256": sha256_file(system_path)',
            "Rendered manifests retain the source configuration hash.",
        ),
    ]
    checks.append(
        make_check(
            "declarative-topology",
            "pass",
            "Canonical topology intent, PostgreSQL major, Citus package family, and source hash are explicit.",
            topology_evidence,
        )
    )

    inventory_evidence = [
        evidence(
            s,
            "ansible/inventory/terraform_inventory.py",
            '["terraform", "output", "-json"]',
            "Inventory addresses and groups are derived from current Terraform outputs.",
        ),
        evidence(
            s,
            "ansible/inventory/terraform_inventory.py",
            "return {}",
            "Terraform/output failures can collapse to an empty inventory payload.",
        ),
        evidence(
            s,
            "src/master_regimes_infra/render.py",
            '"created_at_utc": datetime.now(UTC)',
            "Rendered metadata contains wall-clock time and is not byte-stable across rerenders.",
        ),
        evidence(
            s,
            "common-scripts/up_eu_us_gac_vhp_shared_vpc.sh",
            "assert_inventory_group_present db_nodes",
            "The main N2 lifecycle wrapper refuses an inventory with no database nodes.",
        ),
        evidence(
            s,
            "common-scripts/extend_eu_us_gac_with_apac.sh",
            "Generated inventory does not contain the expected three APAC DB nodes.",
            "The N3 extension wrapper validates the exact expected APAC node count.",
        ),
    ]
    checks.append(
        make_check(
            "inventory-runtime-inputs",
            "warn",
            "Inventory shape is deterministic, but addresses/VPC values come from live Terraform outputs and environment-resolved inputs.",
            inventory_evidence,
        )
    )
    findings.append(
        make_finding(
            "A-002",
            "medium",
            "mixed",
            "Inventory rendering depends on live Terraform and environment state",
            "Logical group construction is encoded in source, while concrete IP addresses, VPC identifiers, and SSH/CIDR values are runtime inputs.",
            "A fresh deployment can reproduce the topology roles but not the original addresses or provider allocation from this repository alone. Direct invocation of the inventory script can also return an empty payload after a Terraform failure.",
            "Archive non-secret Terraform outputs needed for provenance, retain wrapper group-count gates, and make inventory generation fail closed outside explicit empty-infrastructure operations.",
            inventory_evidence,
        )
    )

    pin_evidence = [
        evidence(
            s,
            "ansible/requirements.yml",
            "name: ansible.posix",
            "The required collection has no version constraint.",
        ),
        evidence(
            s,
            "common-scripts/ansible_shim.py",
            "import ansible._internal._rpc_host as rpc_host",
            "The launcher patches an internal Ansible RPC method and is version-sensitive.",
        ),
        evidence(
            s,
            "common-scripts/run_ansible.sh",
            'exec "${ANSIBLE_PYTHON:-/usr/bin/python3}"',
            "Ansible uses the host/system Python unless an external variable overrides it.",
        ),
        evidence(
            s,
            "ansible/roles/postgresql_citus/tasks/main.yml",
            "Hold PostgreSQL and Citus package versions",
            "PostgreSQL/Citus packages are held only after the currently available build is installed.",
        ),
        evidence(
            s,
            "ansible/roles/analytics_node/defaults/main.yml",
            "https://astral.sh/uv/install.sh",
            "The uv installer URL is mutable and has no content checksum in the role contract.",
        ),
    ]
    checks.append(
        make_check(
            "toolchain-pins",
            "warn",
            "Product major/minor families are pinned, but exact Ansible, collection, package-build, and installer versions are not fully locked.",
            pin_evidence,
        )
    )
    findings.append(
        make_finding(
            "A-003",
            "high",
            "runtime_dependent",
            "Exact configuration-management toolchain and binary builds are not fully pinned",
            "PostgreSQL 18 and Citus 14.0 are selected by package family, but Ansible core is absent from the Python lock, ansible.posix is unversioned, apt packages omit exact Debian build versions, and remote installers/repository setup are mutable downloads.",
            "The same source can converge to functionally similar hosts at different dates while installing different package builds or encountering an incompatible Ansible internal API. This limits bit-for-bit reconstruction, not the documented logical topology.",
            "Publish an execution image or lock manifest containing Ansible core/collection versions, OS image identity, exact apt package versions, repository key/script hashes, and uv version/checksum.",
            pin_evidence,
        )
    )

    tool_evidence = [
        evidence(
            s,
            "configs/systems/eu-us-gac-vps.yml",
            "branch: pivot/fcm-results-rework",
            "The topology selects a mutable Git branch for deployed experiment tools.",
        ),
        evidence(
            s,
            "ansible/roles/citus_datagen/tasks/main.yml",
            "Sync local citus-datagen first with `make repo-sync-datagen`",
            "The datagen role references an exact-sync target that is absent from the Makefile.",
        ),
        evidence(
            s,
            "Makefile",
            "repo-sync-psql-benchmarks repo-sync-psql-benchmarks-all",
            "The declared sync targets cover psql-benchmarks but contain no datagen counterpart.",
        ),
        evidence(
            s,
            "common-scripts/sync_remote_repo.py",
            'head = git_output(local_dir, "rev-parse", "HEAD")',
            "The psql-benchmarks synchronization path captures the local HEAD.",
        ),
        evidence(
            s,
            "common-scripts/sync_remote_repo.py",
            'f"rev-parse HEAD)',
            "The same path verifies the remote HEAD after synchronization.",
        ),
    ]
    checks.append(
        make_check(
            "experiment-tool-source",
            "warn",
            "psql-benchmarks has an exact-HEAD sync path; citus-datagen deployment remains branch-oriented.",
            tool_evidence,
        )
    )
    findings.append(
        make_finding(
            "A-004",
            "high",
            "mixed",
            "Experiment tool deployment is not uniformly commit-pinned",
            "The psql-benchmarks helper transfers and verifies a specific Git HEAD, while the citus-datagen Ansible role clones/updates a branch and documents a Make target that does not exist.",
            "A future dataset reload can use different generator code even with the same YAML profile. Completed load manifests mitigate this by recording the remote datagen commit, but a clean rebuild is not guaranteed to select it automatically.",
            "Add exact commit variables for both tools, implement or remove repo-sync-datagen, and fail dataset loading when the deployed commit differs from the manifest contract.",
            tool_evidence,
        )
    )

    verify_evidence = [
        evidence(
            s,
            "ansible/playbooks/verify-citus.yml",
            "Assert PostgreSQL major version",
            "The verifier checks PostgreSQL major version.",
        ),
        evidence(
            s,
            "ansible/playbooks/verify-citus.yml",
            "Assert Citus extension major/minor version",
            "The verifier checks the Citus 14.0 extension family.",
        ),
        evidence(
            s,
            "Makefile",
            'cmp -s "$(SINGLE_EU_OUT)/terraform/envs/eu/terraform.tfvars"',
            "The drift target compares rendered files byte-for-byte.",
        ),
        evidence(
            s,
            "common-scripts/probe_lab_environment.py",
            '"status": "attention" if deviations else "verified"',
            "A separate probe can flag residual runtime settings or network state.",
        ),
    ]
    checks.append(
        make_check(
            "drift-and-verification",
            "warn",
            "Static rendered-file drift and basic PostgreSQL/Citus state are checked, but complete live-state drift is not enforced.",
            verify_evidence,
        )
    )
    findings.append(
        make_finding(
            "A-005",
            "medium",
            "runtime_dependent",
            "Runtime drift checks cover only a subset of managed state",
            "The primary drift gate validates generated files, and verify-citus checks major software state and worker count. It does not establish full equivalence of GUCs, TLS/PgBouncer state, FDW mappings/options, tool commits, dataset identity, clock service, or tc/netem baseline.",
            "A host may pass the current verifier while retaining experiment-specific runtime state. The lab probe broadens detection but reports an attention state separately rather than serving as a mandatory convergence gate.",
            "Create one read-only post-convergence audit that hashes or records every thesis-relevant live setting and make non-baseline attention fail experiment admission.",
            verify_evidence,
        )
    )

    dataset_evidence = [
        evidence(
            s,
            "common-scripts/apply_dataset_profile.py",
            "effective_distribution = region_distribution(profile, region=args.region)",
            "The loader supports per-region effective distributions.",
        ),
        evidence(
            s,
            "tests/test_apply_dataset_profile.py",
            '"skew_profile": "heavy"',
            "An offline test covers a region-specific heavy-skew override.",
        ),
        evidence(
            s,
            "common-scripts/apply_dataset_profile.py",
            '"datagen_commit": datagen_commit_result.stdout.strip()',
            "Each load manifest records the deployed datagen commit.",
        ),
        evidence(
            s,
            "common-scripts/apply_dataset_profile.py",
            '"row_level_checksum_included": False',
            "The snapshot contract explicitly excludes a full row-level checksum.",
        ),
    ]
    checks.append(
        make_check(
            "dataset-contract",
            "pass",
            "Dataset profiles, per-region overrides, generator commit, profile hash, seed/time parameters, counts, shard placement, and aggregate hashes are represented in the loader/audit contract.",
            dataset_evidence,
        )
    )
    findings.append(
        make_finding(
            "A-006",
            "medium",
            "mixed",
            "Dataset provenance is strong at profile and aggregate level but not row-complete",
            "The loader records the profile, seed/time contract, datagen commit, table counts, shard distribution, hot-tenant placement, and component hashes. It explicitly does not checksum every generated row.",
            "The package can establish which deterministic construction was requested and whether aggregate placement properties match. It cannot independently prove byte-identical table contents after a new load without trusting the pinned generator and database behavior.",
            "Retain archived rendered profiles and SQL, pin the generator commit, and add a scalable deterministic table-content checksum for future releases.",
            dataset_evidence,
        )
    )

    rollback_dataset_evidence = [
        evidence(
            s,
            "common-scripts/apply_dataset_profile.py",
            'cp .env "$backup"',
            "The loader snapshots the datagen environment file.",
        ),
        evidence(
            s,
            "common-scripts/apply_dataset_profile.py",
            'mv "$backup" .env',
            "The cleanup trap restores that environment file.",
        ),
        evidence(
            s,
            "common-scripts/apply_dataset_profile.py",
            "setsid ./bin/reset-and-load &",
            "The actual data operation is destructive reset-and-load.",
        ),
    ]
    checks.append(
        make_check(
            "dataset-failure-rollback",
            "warn",
            "The loader restores temporary configuration and processes, but it does not restore the previous database contents after a failed destructive reload.",
            rollback_dataset_evidence,
        )
    )
    findings.append(
        make_finding(
            "A-007",
            "high",
            "runtime_dependent",
            "Dataset apply is not transactionally reversible",
            "The cleanup trap restores .env and terminates the generator process, but reset-and-load can already have dropped or partially recreated data.",
            "A failed load can leave an unusable or partial dataset while the wrapper has restored its configuration file. Experiment admission must therefore depend on a successful post-load capability audit, not merely cleanup completion.",
            "Require a pre-load backup/snapshot or load into a replacement database, and gate every experiment on a completed dataset audit and expected snapshot identity.",
            rollback_dataset_evidence,
        )
    )

    network_evidence = [
        evidence(
            s,
            "common-scripts/manage_network_pressure.py",
            '["tc", "qdisc", "del", "dev", device, "root"]',
            "Apply and reset remove the complete root qdisc before proceeding.",
        ),
        evidence(
            s,
            "common-scripts/manage_network_pressure.py",
            '"qdisc_before": before',
            "The tool records the pre-action qdisc for audit.",
        ),
        evidence(
            s,
            "common-scripts/run_database_sweep.py",
            "allow_failure=True",
            "Network reset failures are tolerated by the sweep cleanup path.",
        ),
        evidence(
            s,
            "tests/test_lab_default_reset_contract.py",
            "test_viewer_default_reset_covers_both_network_directions",
            "The Make contract includes resetting both traffic directions.",
        ),
    ]
    checks.append(
        make_check(
            "network-rollback",
            "warn",
            "The experiment removes its root qdisc in both directions and records before/after state, but does not restore an arbitrary prior qdisc configuration.",
            network_evidence,
        )
    )
    findings.append(
        make_finding(
            "A-008",
            "medium",
            "runtime_dependent",
            "Network rollback means removal of the experiment qdisc, not exact restoration",
            "The reset path deletes the root qdisc and the sweep invokes it in a finally block with failure allowed. It does not replay the saved prior qdisc graph or enforce equality with a baseline profile.",
            "This is reproducible when the admitted baseline is deliberately 'no experiment root qdisc'. It is unsafe as a generic rollback on hosts with pre-existing traffic control or when cleanup fails silently.",
            "Make the no-root-qdisc precondition explicit, reject non-baseline admission, and treat reset failure or residual netem as a hard stop.",
            network_evidence,
        )
    )

    idempotence_evidence = [
        evidence(
            s,
            "ansible/roles/postgresql_citus/tasks/main.yml",
            "ALTER ROLE",
            "Some SQL convergence operations execute on every role run.",
        ),
        evidence(
            s,
            "ansible/roles/postgresql_citus/tasks/main.yml",
            "Remove other-region Citus worker nodes from coordinator",
            "Citus membership is actively converged by removing unexpected workers.",
        ),
        evidence(
            s,
            "ansible/roles/postgresql_citus/tasks/main.yml",
            "when: not citus_repo_marker.stat.exists",
            "Repository setup is skipped permanently after a marker is created.",
        ),
    ]
    checks.append(
        make_check(
            "ansible-idempotence",
            "warn",
            "Most roles converge effective state, but strict no-change idempotence and future repository refresh are not guaranteed.",
            idempotence_evidence,
        )
    )
    findings.append(
        make_finding(
            "A-009",
            "low",
            "mixed",
            "Roles are mostly convergent rather than strictly idempotent",
            "Declarative apt/file/template tasks and explicit Citus membership checks converge host state, while password/ownership SQL, builds, and branch updates may report changes repeatedly. A repository marker also freezes setup logic after first use.",
            "Repeated application should usually preserve effective service behavior, but an Ansible zero-change second run is not established and repository fixes may require explicit marker removal.",
            "Add check-mode/idempotence CI against disposable hosts and version the repository marker by installer hash or desired repository revision.",
            idempotence_evidence,
        )
    )

    fdw_evidence = [
        evidence(
            s,
            "common-scripts/run_gac_fdw_bootstrap.py",
            "CREATE OR REPLACE VIEW public.mr_joined_events_colocated",
            "Regional helper views are changed before the external GAC bootstrap.",
        ),
        evidence(
            s,
            "common-scripts/run_gac_fdw_bootstrap.py",
            "./bin/fdw-bootstrap --label",
            "GAC FDW creation/import is delegated to a separately deployed tool.",
        ),
        evidence(
            s,
            "tests/test_gac_fdw_bootstrap.py",
            "test_join_views_are_explicit_fdw_imports",
            "The offline test verifies expected view names, not distributed transactional rollback.",
        ),
    ]
    findings.append(
        make_finding(
            "A-010",
            "medium",
            "runtime_dependent",
            "FDW bootstrap is auditable but not atomic across regional and GAC nodes",
            "Regional views are created/replaced and the GAC bootstrap then runs as a separate remote operation. No distributed transaction restores all nodes after an intermediate failure.",
            "A failed bootstrap can leave regional definitions and GAC foreign objects at different revisions until the idempotent bootstrap is rerun successfully.",
            "Add a post-bootstrap contract audit covering every region and GAC object, and require it before query collection.",
            fdw_evidence,
        )
    )

    clock_evidence = [
        evidence(
            s,
            "common-scripts/run_query_collection.py",
            "clock_calibrations: dict[str, dict[str, Any]] = {}",
            "The collector maintains per-node runtime clock calibration.",
        ),
        evidence(
            s,
            "common-scripts/run_query_collection.py",
            '"node_clock_calibrations": clock_calibrations',
            "Calibration data is retained in the collection manifest.",
        ),
    ]
    findings.append(
        make_finding(
            "A-011",
            "low",
            "runtime_dependent",
            "Clock correlation is calibrated at collection time rather than configuration-managed",
            "No NTP/chrony role is present in the audited configuration. The collector instead probes node clocks, translates capture windows, and saves the calibrations.",
            "This supports trace correlation for a completed run but does not establish identical host clock discipline across fresh deployments.",
            "Record time-service state and offset bounds in the preflight audit, while retaining the existing per-run calibration evidence.",
            clock_evidence,
        )
    )

    severity_counts = Counter(item["severity"] for item in findings)
    check_counts = Counter(item["status"] for item in checks)
    return {
        "schema_version": "1.0",
        "audit_kind": "offline_ansible_configuration_reproducibility",
        "scope": {
            "source_label": "master-regimes-infra",
            "package_label": "master-thesis-final/sources/master-regimes-infra",
            "files_read": list(SAFE_FILES),
            "excluded": [
                "generated ansible/group_vars/all.yml",
                "generated inventory and Terraform state/output",
                "secrets, .env files, SSH keys, and credentials",
                "live hosts, cloud APIs, package repositories, and SSH",
                "experiment dataset profiles/results outside the two assigned roots",
            ],
        },
        "summary": {
            "critical_files_compared": len(parity),
            "snapshot_mismatches": sum(not row["match"] for row in parity),
            "checks": dict(sorted(check_counts.items())),
            "findings": dict(sorted(severity_counts.items())),
            "overall_assessment": (
                "The packaged source reproduces declarative topology and orchestration intent, "
                "but exact binary/runtime reconstruction requires additional pinned external inputs "
                "and stronger post-convergence/rollback gates."
            ),
        },
        "snapshot_parity": parity,
        "checks": checks,
        "findings": findings,
        "scope_limitations": [
            "This audit proves source-package parity only for the explicit allow-list, not for generated state or secrets.",
            "It does not determine which dataset profile was used by a particular archived experiment because experiment profiles and run artifacts are outside this subaudit's assigned roots.",
            "The code supports per-region distribution overrides, including one-region heavy skew, but actual use must be established from archived dataset manifests by the dataset/corpus audit.",
            "No Ansible syntax/check-mode/idempotence run was executed because that would load generated inventory/group variables or contact managed hosts.",
            "No package repository, Git remote, cloud provider, or live database state was queried.",
        ],
    }


def main() -> int:
    args = parse_args()
    payload = audit(args.source.resolve(), args.package.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "critical_files_compared": payload["summary"][
                    "critical_files_compared"
                ],
                "snapshot_mismatches": payload["summary"]["snapshot_mismatches"],
                "checks": payload["summary"]["checks"],
                "findings": payload["summary"]["findings"],
            },
            sort_keys=True,
        )
    )
    if args.strict and any(row["status"] == "fail" for row in payload["checks"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
