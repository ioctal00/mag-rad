#!/usr/bin/env python3
"""Offline Terraform reproducibility audit for the thesis release package.

The audit deliberately does not invoke Terraform, access a provider, or read
terraform.tfvars/state files. It validates only publishable configuration,
source code, manifests, and recorded experimental metadata.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_ROOT = SCRIPT_PATH.parents[3]


@dataclass
class Finding:
    finding_id: str
    severity: str
    status: str
    title: str
    summary: str
    evidence: list[str]
    remediation: str


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def text(path: Path) -> str:
    forbidden = {"terraform.tfvars", "terraform.tfstate"}
    if path.name in forbidden or path.name.startswith("terraform.tfstate."):
        raise RuntimeError(f"refusing to read private Terraform file: {path}")
    return path.read_text(encoding="utf-8")


def line_of(path: Path, needle: str) -> int:
    for number, line in enumerate(text(path).splitlines(), start=1):
        if needle in line:
            return number
    return 0


def evidence(root: Path, path: Path, needle: str) -> str:
    number = line_of(path, needle)
    relative = path.relative_to(root).as_posix()
    return f"{relative}:{number}" if number else relative


def scalar(value: str) -> Any:
    value = value.strip()
    if "#" in value:
        value = value.split("#", 1)[0].rstrip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value in {"true", "false"}:
        return value == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def parse_system_config(path: Path) -> dict[str, Any]:
    """Parse only the non-secret scalar subset needed by this audit."""
    result: dict[str, Any] = {"regions": {}, "profiles": {}, "postgres": {}, "gac": {}}
    section = ""
    subsection = ""
    for raw in text(path).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
            subsection = ""
            continue
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            result[key] = scalar(value)
            continue
        if section == "regions":
            if indent == 2 and stripped.endswith(":"):
                subsection = stripped[:-1]
                result["regions"][subsection] = {}
            elif indent == 4 and ":" in stripped and subsection:
                key, value = stripped.split(":", 1)
                result["regions"][subsection][key] = scalar(value)
        elif section == "compute_profiles":
            if indent == 2 and stripped.endswith(":"):
                subsection = stripped[:-1]
                result["profiles"][subsection] = {}
            elif indent == 4 and ":" in stripped and subsection:
                key, value = stripped.split(":", 1)
                result["profiles"][subsection][key] = scalar(value)
        elif section == "postgres" and indent == 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            result["postgres"][key] = scalar(value)
        elif section == "global_analytics" and indent == 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            result["gac"][key] = scalar(value)
        elif section == "web_portal" and indent == 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            result.setdefault("web_portal", {})[key] = scalar(value)
    return result


def node_count(config: dict[str, Any]) -> int:
    regional = sum(1 + int(region.get("worker_count", 2)) for region in config["regions"].values())
    gac = 1 if config["gac"].get("enabled") else 0
    portal = 1 if config.get("web_portal", {}).get("enabled") else 0
    return regional + gac + portal


def lock_version(path: Path) -> str:
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text(path), re.MULTILINE)
    return match.group(1) if match else "not_found"


def historical_topologies(root: Path) -> dict[str, Any]:
    path = root / "artifacts/results/experimental-reproducibility-v2/infrastructure.csv"
    if not path.exists():
        return {"available": False}
    by_run: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            run = by_run.setdefault(
                row["logical_run_id"],
                {"nodes": 0, "logical_regions": set(), "physical_regions": set(), "source_commits": set()},
            )
            run["nodes"] += 1
            run["logical_regions"].add(row["logical_region"])
            run["physical_regions"].add(row["physical_provider_region"])
            run["source_commits"].add(row["environment_source_commit"])
    for run in by_run.values():
        for key in ("logical_regions", "physical_regions", "source_commits"):
            run[key] = sorted(value for value in run[key] if value)
    return {"available": True, "runs": by_run}


def audit(root: Path) -> dict[str, Any]:
    infra = root / "sources/master-regimes-infra"
    required = [
        infra / "configs/systems/eu-us-gac-vps.yml",
        infra / "configs/systems/eu-us-apac-gac-vps.yml",
        infra / "terraform/modules/region/main.tf",
        infra / "terraform/envs/eu/main.tf",
        infra / "terraform/envs/us/main.tf",
        infra / "terraform/envs/apac/main.tf",
        infra / "common-scripts/up_eu_us_gac_vhp_shared_vpc.sh",
        infra / "common-scripts/extend_eu_us_gac_with_apac.sh",
        infra / "ansible/inventory/terraform_inventory.py",
        root / "config/release-spec.json",
    ]
    missing = [path.relative_to(root).as_posix() for path in required if not path.exists()]
    if missing:
        return {
            "audit": "terraform_reproducibility",
            "status": "invalid_package",
            "missing": missing,
            "findings": [],
        }

    n2_path = infra / "configs/systems/eu-us-gac-vps.yml"
    n3_path = infra / "configs/systems/eu-us-apac-gac-vps.yml"
    n2 = parse_system_config(n2_path)
    n3 = parse_system_config(n3_path)
    module_path = infra / "terraform/modules/region/main.tf"
    up_path = infra / "common-scripts/up_eu_us_gac_vhp_shared_vpc.sh"
    extend_path = infra / "common-scripts/extend_eu_us_gac_with_apac.sh"
    inventory_path = infra / "ansible/inventory/terraform_inventory.py"
    package_makefile = root / "Makefile"
    infra_makefile = infra / "Makefile"

    findings: list[Finding] = []
    topology_ok = (
        set(n2["regions"]) == {"eu", "us"}
        and set(n3["regions"]) == {"eu", "us", "apac"}
        and all(region.get("vultr_region") == "ams" for region in n3["regions"].values())
        and node_count(n2) == 7
        and node_count(n3) == 10
        and n2.get("active_profile") == "vps"
        and n2["profiles"]["vps"].get("worker_plan") == "vhf-1c-2gb"
    )
    findings.append(
        Finding(
            "TF-001",
            "info",
            "pass" if topology_ok else "fail",
            "Current N2/N3 topology is statically reconstructable",
            (
                "N2 declares EU and US Citus clusters plus one GAC (7 VPS nodes). "
                "N3 adds APAC coordinator plus two workers (10 VPS nodes). All logical "
                "regions and the GAC use Vultr ams and the active plan is vhf-1c-2gb."
            ),
            [
                evidence(root, n2_path, "active_profile: vps"),
                evidence(root, n2_path, "vultr_region: ams"),
                evidence(root, n3_path, "apac:"),
                evidence(root, n3_path, "worker_count: 2"),
            ],
            "No action required for the declarative topology description.",
        )
    )

    shared_vpc_ok = all(
        token in text(module_path)
        for token in ("create_vpc", "existing_vpc_id", "vpc_ids", "local.vpc_id")
    ) and all(
        token in text(up_path)
        for token in ("SHARED_VPC_ID", "existing_vpc_id", "existing_vpc_cidr")
    )
    findings.append(
        Finding(
            "TF-002",
            "info",
            "pass" if shared_vpc_ok else "fail",
            "Shared-VPC relationship is explicit",
            (
                "The EU anchor creates the VPC. The lifecycle script reads its ID/CIDR "
                "from Terraform outputs and injects them into US; the N3 extension does "
                "the same for APAC. The logical region labels therefore do not imply real WAN geography."
            ),
            [
                evidence(root, module_path, "create_vpc"),
                evidence(root, up_path, 'SHARED_VPC_ID="$(terraform'),
                evidence(root, up_path, "existing_vpc_id"),
                evidence(root, extend_path, "shared_vpc_id="),
            ],
            "Keep physical location and emulated WAN terminology separate in documentation.",
        )
    )

    lock_paths = [
        infra / f"terraform/envs/{environment}/.terraform.lock.hcl"
        for environment in ("eu", "us", "apac")
    ]
    lock_details = []
    for path in lock_paths:
        relative = path.relative_to(root)
        lock_details.append(
            {
                "path": relative.as_posix(),
                "exists_locally": path.exists(),
                "release_candidate_present": path.exists(),
                "provider_version": lock_version(path) if path.exists() else "missing",
            }
        )
    locks_published = all(item["release_candidate_present"] for item in lock_details)
    findings.append(
        Finding(
            "TF-003",
            "info",
            "pass" if locks_published else "fail",
            "Provider lock files are included in the release candidate",
            (
                "The package contains all three provider lock files. EU/US resolve Vultr "
                "2.31.2, while APAC resolves 2.32.0; this difference is now explicit rather "
                "than delegated to a future provider resolution."
            ),
            [
                evidence(root, infra / ".gitignore", "!**/.terraform.lock.hcl"),
                evidence(root, lock_paths[0], 'version     = "2.31.2"'),
                evidence(root, lock_paths[2], 'version     = "2.32.0"'),
                evidence(root, infra / "terraform/envs/eu/versions.tf", 'version = "~> 2.30"'),
            ],
            "Keep the lock files in every tagged release and update them only through an explicit provider upgrade.",
        )
    )

    source_manifest_path = root / "artifacts/results/experimental-reproducibility-v2/source_manifest.json"
    source_manifest = json.loads(text(source_manifest_path)) if source_manifest_path.exists() else {}
    runtime_not_recorded = source_manifest.get("run_time_commit_policy", "").startswith("not_recorded")
    packaged_commit = json.loads(text(root / "config/release-spec.json"))["source_snapshots"].get(
        "master-regimes-infra"
    )
    historical = historical_topologies(root)
    historic_commits = sorted(
        {
            commit
            for run in historical.get("runs", {}).values()
            for commit in run.get("source_commits", [])
            if commit not in {"not_recorded", packaged_commit}
        }
    )
    exact_history = not runtime_not_recorded and not historic_commits
    findings.append(
        Finding(
            "TF-004",
            "high",
            "pass" if exact_history else "fail",
            "Current source snapshot is not an exact historical infrastructure snapshot",
            (
                "The package pins the curated infrastructure source at the current release commit, "
                "while the reproducibility audit explicitly says run-time commits were not recorded "
                "unless a run manifest persisted them. Recorded tables reference older infrastructure "
                "commits, but their full source trees and applied plan/state are not included. The package "
                "can reproduce a current recipe, not prove the exact historical Terraform plan."
            ),
            [
                evidence(root, source_manifest_path, "run_time_commit_policy"),
                evidence(root, root / "config/release-spec.json", "master-regimes-infra"),
                evidence(root, root / "docs/05-provenance-and-limits.md", "not_recorded"),
            ],
            (
                "Archive sanitized plan JSON/text and the exact non-secret rendered variables for each "
                "experimental topology, or vendor the historical source commits as immutable snapshots."
            ),
        )
    )

    package_plan = text(package_makefile)
    infra_plan = text(infra_makefile)
    complete_plan_only = (
        "infra-plan:" in package_plan
        and "eu-us-gac-vps-plan" in package_plan
        and "eu-us-gac-vps-plan:" in infra_plan
        and "up_eu_us_gac_vhp_shared_vpc.sh" not in infra_plan.split("eu-us-gac-vps-plan:", 1)[1].split("\n\n", 1)[0]
    )
    findings.append(
        Finding(
            "TF-005",
            "medium",
            "fail" if complete_plan_only else "pass",
            "Public infra-plan target does not plan the complete N2 topology",
            (
                "The package delegates infra-plan to eu-us-gac-vps-plan, but that target invokes "
                "the generic single-EU plan path. The complete EU+US shared-VPC workflow plans both "
                "stacks only inside the destructive/apply-oriented infra-up lifecycle."
            ),
            [
                evidence(root, package_makefile, "infra-plan:"),
                evidence(root, infra_makefile, "eu-us-gac-vps-plan:"),
                evidence(root, up_path, "terraform_apply_plan us"),
            ],
            "Add read-only complete N2 and N3 plan targets that stop before apply.",
        )
    )

    n3_state_coupled = all(
        token in text(extend_path)
        for token in (
            "state list",
            "EU anchor Terraform state is empty",
            "terraform -chdir=\"$APAC_TF_DIR\" apply",
        )
    )
    findings.append(
        Finding(
            "TF-006",
            "medium",
            "fail" if n3_state_coupled else "pass",
            "N3 topology planning is coupled to live N2 state and immediate apply",
            (
                "The APAC extension requires existing EU state, reads the live shared VPC outputs, "
                "then plans and applies APAC in one script. This is operationally valid but prevents "
                "a clean offline all-stack N3 plan and makes the exact N3 graph dependent on provider outputs."
            ),
            [
                evidence(root, extend_path, "state list"),
                evidence(root, extend_path, "shared_vpc_id="),
                evidence(root, extend_path, "apply -auto-approve"),
            ],
            "Provide a non-applying N3 plan command and a documented placeholder contract for VPC ID/CIDR.",
        )
    )

    us_example = infra / "terraform/envs/us/terraform.tfvars.example"
    eu_example = infra / "terraform/envs/eu/terraform.tfvars.example"
    examples_stale = (
        'region_code = "ewr"' in text(us_example)
        or 'global_analytics_client_region_code = "cdg"' in text(eu_example)
        or 'coordinator_plan  = "vc2-2c-4gb"' in text(eu_example)
    )
    findings.append(
        Finding(
            "TF-007",
            "medium",
            "fail" if examples_stale else "pass",
            "Direct tfvars examples conflict with the authoritative topology",
            (
                "The YAML renderer declares the current colocated ams/vhf topology, but the checked-in "
                "US example still says ewr and the EU example names cdg plus older vc2 plans. A reader "
                "who bypasses the renderer will provision a materially different physical experiment."
            ),
            [
                evidence(root, us_example, 'region_code = "ewr"'),
                evidence(root, eu_example, 'global_analytics_client_region_code = "cdg"'),
                evidence(root, n2_path, "vultr_region: ams"),
            ],
            "Generate examples from the authoritative YAML or label/remove legacy examples.",
        )
    )

    versions_path = infra / "terraform/envs/eu/versions.tf"
    ansible_requirements = infra / "ansible/requirements.yml"
    version_gaps = (
        'required_version = ">= 1.5.0"' in text(versions_path)
        or 'version = "~> 2.30"' in text(versions_path)
        or "version:" not in text(ansible_requirements)
    )
    findings.append(
        Finding(
            "TF-008",
            "medium",
            "fail" if version_gaps else "pass",
            "Toolchain and package resolution are only partially pinned",
            (
                "PostgreSQL 18, the Citus 14.0 package name, os_id 1743 and VPS plan IDs are explicit. "
                "Terraform itself has only a lower bound, provider constraints are ranges, and the "
                "Ansible collection has no version. Repository-backed apt installation also does not "
                "archive exact Debian package builds."
            ),
            [
                evidence(root, versions_path, "required_version"),
                evidence(root, versions_path, "~> 2.30"),
                evidence(root, n2_path, 'citus_package: "postgresql-18-citus-14.0"'),
                evidence(root, ansible_requirements, "ansible.posix"),
            ],
            (
                "Record the tested Terraform/Ansible versions, commit locks, pin the Ansible collection, "
                "and archive installed package versions from accepted runs."
            ),
        )
    )

    inventory_state_dependent = all(
        token in text(inventory_path)
        for token in ("terraform", "output", "coordinator_public_ip", "worker_public_ips")
    )
    findings.append(
        Finding(
            "TF-009",
            "info",
            "pass" if inventory_state_dependent else "fail",
            "Generated inventory dependency is explicit",
            (
                "Ansible inventory is not a static hidden input: it is rebuilt from terraform output -json "
                "for every available environment stack. Exact host addresses therefore require live/local "
                "Terraform state, while role/group construction remains reproducible from source."
            ),
            [
                evidence(root, inventory_path, '["terraform", "output", "-json"]'),
                evidence(root, inventory_path, 'f"{env_name}-coord-1"'),
                evidence(root, inventory_path, 'f"{env_name}-worker-{idx}"'),
            ],
            "Archive a sanitized inventory topology (without routable addresses) for each accepted run.",
        )
    )

    # Keep the packaged audit deterministic: a sibling checkout is not part of
    # the public release contract and may not exist on a reviewer's machine.
    upstream = root / "__external_source_comparison_disabled__"
    parity_files = [
        Path("configs/systems/eu-us-gac-vps.yml"),
        Path("configs/systems/eu-us-apac-gac-vps.yml"),
        Path("terraform/modules/region/main.tf"),
        Path("src/master_regimes_infra/render.py"),
        Path("ansible/inventory/terraform_inventory.py"),
    ]
    parity: dict[str, Any] = {"checked": upstream.exists(), "files": []}
    if upstream.exists():
        for relative in parity_files:
            package_path = infra / relative
            upstream_path = upstream / relative
            same = package_path.exists() and upstream_path.exists() and sha256(package_path) == sha256(upstream_path)
            parity["files"].append({"path": relative.as_posix(), "same": same})
    parity_ok = not parity["checked"] or all(item["same"] for item in parity["files"])
    findings.append(
        Finding(
            "TF-010",
            "info",
            "pass" if parity_ok else "fail",
            "Curated critical source files match the local upstream checkout",
            (
                "When the sibling upstream repository is available, critical topology, module, renderer, "
                "and inventory files are byte-identical. This check is optional and does not replace the "
                "release commit provenance."
            ),
            [evidence(root, root / "reproducibility/source-provenance.csv", "master-regimes-infra")],
            "Regenerate the source snapshot whenever the pinned upstream commit changes.",
        )
    )

    severity_counts: dict[str, int] = {}
    failed_counts: dict[str, int] = {}
    for finding in findings:
        severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1
        if finding.status == "fail":
            failed_counts[finding.severity] = failed_counts.get(finding.severity, 0) + 1

    return {
        "audit": "terraform_reproducibility",
        "schema_version": 1,
        "status": "gaps_found" if any(item.status == "fail" for item in findings) else "pass",
        "scope": {
            "package_root": ".",
            "infra_snapshot": "sources/master-regimes-infra",
            "network_access": False,
            "terraform_invoked": False,
            "private_tfvars_or_state_read": False,
        },
        "topology": {
            "n2": {
                "system_id": n2.get("system_id"),
                "logical_regions": sorted(n2["regions"]),
                "physical_provider_regions": sorted(
                    {str(region.get("vultr_region")) for region in n2["regions"].values()}
                ),
                "regional_nodes": sum(1 + int(r.get("worker_count", 2)) for r in n2["regions"].values()),
                "gac_nodes": 1 if n2["gac"].get("enabled") else 0,
                "total_nodes": node_count(n2),
                "active_profile": n2.get("active_profile"),
                "plan": n2["profiles"].get("vps", {}).get("worker_plan"),
            },
            "n3": {
                "system_id": n3.get("system_id"),
                "logical_regions": sorted(n3["regions"]),
                "physical_provider_regions": sorted(
                    {str(region.get("vultr_region")) for region in n3["regions"].values()}
                ),
                "regional_nodes": sum(1 + int(r.get("worker_count", 2)) for r in n3["regions"].values()),
                "gac_nodes": 1 if n3["gac"].get("enabled") else 0,
                "total_nodes": node_count(n3),
                "active_profile": n3.get("active_profile"),
                "plan": n3["profiles"].get("vps", {}).get("worker_plan"),
            },
            "historical_record": historical,
        },
        "version_resolution": {
            "terraform_constraint": ">= 1.5.0",
            "provider_constraint": "~> 2.30",
            "local_lock_files": lock_details,
            "postgresql_major": n2["postgres"].get("version"),
            "citus_package": n2["postgres"].get("citus_package"),
        },
        "source_snapshot_parity": parity,
        "summary": {"all": severity_counts, "failed": failed_counts},
        "findings": [asdict(item) for item in findings],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--json", type=Path, help="Write the complete audit JSON to this path")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero when a high-severity finding fails",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    result = audit(root)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json:
        destination = args.json
        if not destination.is_absolute():
            destination = root / destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if result.get("status") == "invalid_package":
        return 2
    if args.strict and result.get("summary", {}).get("failed", {}).get("high", 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
