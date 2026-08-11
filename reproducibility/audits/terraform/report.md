# Terraform reproducibility audit

## Scope and verdict

This audit inspected the curated source snapshot and the package's infrastructure/provenance documents. It did not contact Vultr, invoke a Terraform plan/apply, or read private `terraform.tfvars`, state, credentials, PKI, or generated inventory files.

**Verdict:** the package describes the current logical topology and resource graph well enough to create a new equivalent-shaped deployment. It does not yet support an exact reproduction of the historical plans applied for every experiment. One high-severity and four medium-severity gaps remain.

## Actual topology

| Configuration | Logical database regions | Regional nodes | GAC | Total | Physical provider location | Network relationship |
| --- | --- | --: | --: | --: | --- | --- |
| Current N2 | EU, US | 2 coordinators + 4 workers | 1 | 7 | all `ams` | one Vultr VPC |
| Current N3 | EU, US, APAC | 3 coordinators + 6 workers | 1 | 10 | all `ams` | APAC attaches to the EU-created VPC |
| Historical `clean-run-v1` | EU, US | 2 coordinators + 4 workers | 1 | 7 | `ams`, `ewr`, `cdg` | historical multi-location layout |
| Later VPS companion/repeatability runs | EU, US | 2 coordinators + 4 workers | 1 | 7 | all `ams` | colocated logical regions |

The current N2/N3 configurations use VPS instances and plan `vhf-1c-2gb`. The web portal and generic backend count are disabled for the experimental topology. PostgreSQL is declared as major version 18 and the Citus package name as `postgresql-18-citus-14.0`.

Evidence:

- N2 physical/logical declarations: `sources/master-regimes-infra/configs/systems/eu-us-gac-vps.yml:56-81`.
- N3 APAC declaration and explicit colocation rationale: `sources/master-regimes-infra/configs/systems/eu-us-apac-gac-vps.yml:58-88`.
- One coordinator and `worker_count` workers are materialized by the region module: `sources/master-regimes-infra/terraform/modules/region/main.tf:321-400`.
- GAC is a separate optional instance attached to the VPC: `sources/master-regimes-infra/terraform/modules/region/main.tf:499-516`.
- Historical physical-region evidence: `artifacts/results/experimental-reproducibility-v2/infrastructure.csv:2-8`.

The EU stack creates the VPC when no existing ID is supplied. The N2 lifecycle reads that ID/CIDR after the EU apply and injects both into US. N3 repeats this for APAC. Therefore `EU`, `US`, and `APAC` are logical roles in the current configuration, not measurements over naturally distant cloud regions.

Evidence:

- VPC create/reuse rule: `sources/master-regimes-infra/terraform/modules/region/main.tf:14-15` and `sources/master-regimes-infra/terraform/modules/region/main.tf:94-105`.
- US attachment: `sources/master-regimes-infra/common-scripts/up_eu_us_gac_vhp_shared_vpc.sh:206-219`.
- APAC attachment: `sources/master-regimes-infra/common-scripts/extend_eu_us_gac_with_apac.sh:119-145`.

## Findings

### TF-003: provider lock files are packaged

**Severity: INFO**

The release candidate contains all three lock files. EU and US resolve Vultr provider `2.31.2`, while APAC resolves `2.32.0`. The difference is explicit and will be protected by the top-level checksum manifest.

### TF-004: historical applied infrastructure is not exactly archived

**Severity: HIGH**

The package pins the current curated source snapshot at commit `1138de50262b36d86af17259c9fc87fb1fe3dede`, while the historical reproducibility table references several older infrastructure commits. The provenance manifest explicitly states that run-time commits were not recorded unless a run manifest persisted them. Sanitized applied plan JSON/text, non-secret rendered variables, and historical source trees are not packaged.

This does not invalidate measured results. It means the package can reproduce the current infrastructure recipe and inspect recorded hardware evidence, but cannot prove bit-for-bit identity with every historical Terraform plan.

Evidence:

- `config/release-spec.json:3-9`.
- `artifacts/results/experimental-reproducibility-v2/source_manifest.json:67-74`.
- `artifacts/results/experimental-reproducibility-v2/infrastructure.csv:2-9`.
- `docs/05-provenance-and-limits.md:12-17`.

Required correction: package sanitized historical plan output and exact non-secret rendered inputs, or vendor immutable snapshots of referenced source commits.

### TF-005: `infra-plan` covers only the EU anchor stack

**Severity: MEDIUM**

The public package maps `make infra-plan` to `eu-us-gac-vps-plan`. That source target uses the generic single-EU plan flow. US is planned only inside the full shared-VPC `infra-up` script, which then applies both plans. A reviewer cannot obtain one non-applying plan of the complete N2 graph using the documented command.

Evidence:

- `Makefile:111-119`.
- `sources/master-regimes-infra/Makefile:222-235`.
- `sources/master-regimes-infra/common-scripts/up_eu_us_gac_vhp_shared_vpc.sh:203-219`.

Required correction: add a complete N2 plan-only target that produces both EU and US plans and stops before apply.

### TF-006: N3 planning requires live N2 state and immediately applies APAC

**Severity: MEDIUM**

The APAC extension rejects an empty EU state, reads live EU VPC outputs, and then plans and applies APAC in the same script. This is a valid incremental deployment workflow, but it is not a clean offline plan of the whole N3 graph.

Evidence:

- `sources/master-regimes-infra/common-scripts/extend_eu_us_gac_with_apac.sh:119-145`.

Required correction: add a non-applying N3 target and a documented placeholder contract for VPC ID/CIDR during static review.

### TF-007: checked-in `tfvars` examples describe a different topology

**Severity: MEDIUM**

The authoritative YAML uses `ams` for EU, US, APAC, and GAC with `vhf-1c-2gb`. The US example still uses `ewr`; the EU example still names GAC `cdg` and older `vc2` plans. The renderer produces the intended values, but direct use of the examples would provision a materially different experiment.

Evidence:

- `sources/master-regimes-infra/terraform/envs/us/terraform.tfvars.example:9-37`.
- `sources/master-regimes-infra/terraform/envs/eu/terraform.tfvars.example:26-43`.
- `sources/master-regimes-infra/configs/systems/eu-us-gac-vps.yml:40-72`.

Required correction: generate examples from the authoritative YAML or label the current examples as legacy physical-region examples.

### TF-008: toolchain resolution is only partially pinned

**Severity: MEDIUM**

The resource plan IDs, OS image ID, PostgreSQL major version, and Citus package name are explicit. Terraform has only a lower-bound version, Vultr uses a range, and `ansible.posix` has no version. The apt repositories can also resolve newer package builds under the same package names.

Evidence:

- `sources/master-regimes-infra/terraform/envs/eu/versions.tf:1-8`.
- `sources/master-regimes-infra/terraform/envs/eu/variables.tf:125-147`.
- `sources/master-regimes-infra/ansible/requirements.yml:1-2`.
- `sources/master-regimes-infra/ansible/roles/postgresql_citus/tasks/main.yml:79-97`.

Required correction: record tested Terraform/Ansible versions, pin the Ansible collection, commit provider locks, and archive installed package versions from accepted runs.

## Inventory and hidden inputs

The generated Ansible inventory is derived from `terraform output -json`, not from a checked-in static host list. It creates stable logical names and groups, but public/private IPs and the VPC CIDR require local/live Terraform state.

Evidence:

- `sources/master-regimes-infra/ansible/inventory/terraform_inventory.py:23-45`.
- `sources/master-regimes-infra/ansible/inventory/terraform_inventory.py:72-120`.
- `sources/master-regimes-infra/ansible/inventory/terraform_inventory.py:152-166`.

The following omitted inputs are expected and do not weaken scientific reproducibility: API credentials, SSH keys, passwords, and reviewer-specific access CIDRs. Provider-assigned resource IDs and IPs are also expected to change for a fresh deployment. In contrast, exact provider/tool versions, accepted plan output, non-secret rendered experimental variables, and the source commit used for each accepted run are scientific provenance and should be archived.

## What the public package can reproduce

| Capability | Status |
| --- | --- |
| Inspect current N2/N3 resource graph | yes |
| Recover logical versus physical region meaning | yes |
| Recreate a fresh same-shaped deployment with new credentials | mostly, after lock/example corrections |
| Generate dynamic Ansible groups after a fresh apply | yes |
| Produce a non-applying complete N2/N3 plan using documented top-level commands | no |
| Reconstruct exact historical IPs/VPC IDs | intentionally no |
| Prove exact historical Terraform plan and provider binary | no |
| Reproduce identical absolute query latency | not guaranteed and not a valid Terraform-level promise |

## Validator

Run from the `master-thesis-final` root:

```bash
python3 reproducibility/audits/terraform/audit.py \
  --json reproducibility/audits/terraform/findings.json
```

Use `--strict` to return a nonzero exit code while high-severity gaps remain. The validator uses only Python's standard library and local publishable files.
