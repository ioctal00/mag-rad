SHELL := /bin/bash

.PHONY: validate render topology-list generated-tree config-validate config-render test lint configure-env configure-env-check doctor ansible-deps repo-sync-psql-benchmarks repo-sync-psql-benchmarks-all repo-sync-psql-benchmarks-analytics eu-vps-single-up eu-vps-single-down eu-vps-single-plan eu-vps-single-apply eu-vps-single-ansible eu-vps-single-explain-smoke eu-vps-single-explain-run eu-vps-single-initial-explain eu-vps-single-query-collect eu-vps-single-query-sweep eu-vps-single-dataset-apply eu-vps-single-database-sweep eu-vps-single-corpus-run eu-vps-single-sweep-static eu-vps-single-hardware-snapshot eu-us-gac-vps-up eu-us-gac-vps-down eu-us-gac-vps-plan eu-us-gac-vps-apply eu-us-gac-vps-ansible eu-us-gac-vps-ping eu-us-gac-vps-tools-sync eu-us-gac-vps-cloudb-web-deploy eu-us-gac-vps-apps-deploy eu-us-gac-vps-fdw-bootstrap eu-us-gac-vps-etl-bootstrap eu-us-gac-vps-network-default-reset eu-us-gac-vps-corpus-run eu-us-gac-vps-stats-ceb-prepare eu-us-apac-gac-vps-extend eu-us-apac-gac-vps-apac-down eu-us-apac-gac-vps-ping eu-us-apac-gac-vps-tools-sync eu-us-apac-gac-vps-corpus-run stats-ceb-correctness-dry-run confirmatory-skew-capability-smoke confirmatory-skew-experiment single-eu-doctor single-eu-validate single-eu-render single-eu-install single-eu-drift-check single-eu-tf-init single-eu-tf-plan single-eu-tf-show-plan single-eu-tf-apply single-eu-tf-output single-eu-tf-destroy-plan single-eu-tf-show-destroy-plan single-eu-destroy single-eu-down single-eu-wait-ssh single-eu-wait-cloud-init single-eu-inventory single-eu-ping single-eu-ansible single-eu-postgres-reinstall single-eu-verify single-eu-datagen-deploy single-eu-bench-deploy single-eu-tools-deploy single-eu-cloudb-web-deploy single-eu-manifest single-eu-explain-smoke single-eu-explain-run single-eu-initial-explain single-eu-query-collect single-eu-query-sweep single-eu-dataset-apply single-eu-database-sweep single-eu-corpus-run single-eu-sweep-static single-eu-hardware-snapshot single-eu-gac-fdw-bootstrap single-eu-gac-etl-bootstrap single-eu-network-default-reset single-eu-up

UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
export UV_CACHE_DIR
ANSIBLE_LOCAL_TEMP ?= /tmp/ansible-local
export ANSIBLE_LOCAL_TEMP
MASTER_REGIMES_ENV_FILE ?= $(HOME)/.config/master-regimes-infra/env
export MASTER_REGIMES_ENV_FILE
BASH_ENV ?= $(MASTER_REGIMES_ENV_FILE)
export BASH_ENV

TOPOLOGY ?= eu-vps-single
GENERATED_DIR ?= $(CURDIR)/generated
GENERATED_SYSTEMS_DIR ?= $(GENERATED_DIR)/systems
GENERATED_RUNS_DIR ?= $(GENERATED_DIR)/runs
GENERATED_TFPLANS_DIR ?= $(GENERATED_DIR)/terraform-plans

ifeq ($(TOPOLOGY),eu-vps-single)
TOPOLOGY_SYSTEM ?= configs/systems/eu-vps-single.yml
TOPOLOGY_OUT ?= $(GENERATED_SYSTEMS_DIR)/eu-vps-single
else ifeq ($(TOPOLOGY),eu-us-gac-vps)
TOPOLOGY_SYSTEM ?= configs/systems/eu-us-gac-vps.yml
TOPOLOGY_OUT ?= $(GENERATED_SYSTEMS_DIR)/eu-us-gac-vps
else ifeq ($(TOPOLOGY),eu-us-apac-gac-vps)
TOPOLOGY_SYSTEM ?= configs/systems/eu-us-apac-gac-vps.yml
TOPOLOGY_OUT ?= $(GENERATED_SYSTEMS_DIR)/eu-us-apac-gac-vps
else
$(error Unknown TOPOLOGY=$(TOPOLOGY). Supported: eu-vps-single, eu-us-gac-vps, eu-us-apac-gac-vps)
endif

SYSTEM ?= $(TOPOLOGY_SYSTEM)
OUT ?= $(TOPOLOGY_OUT)
SINGLE_EU_SYSTEM ?= $(TOPOLOGY_SYSTEM)
SINGLE_EU_OUT ?= $(TOPOLOGY_OUT)
SINGLE_EU_TF_DIR ?= terraform/envs/eu
SINGLE_EU_PLAN_FILE ?= $(GENERATED_TFPLANS_DIR)/eu/single-eu.tfplan
SINGLE_EU_PLAN_TEXT ?= $(GENERATED_TFPLANS_DIR)/eu/single-eu.plan.txt
SINGLE_EU_DESTROY_PLAN_FILE ?= $(GENERATED_TFPLANS_DIR)/eu/single-eu-destroy.tfplan
SINGLE_EU_DESTROY_PLAN_TEXT ?= $(GENERATED_TFPLANS_DIR)/eu/single-eu-destroy.plan.txt
SINGLE_EU_ANSIBLE_LIMIT ?= eu
SINGLE_EU_PING_LIMIT ?= $(SINGLE_EU_ANSIBLE_LIMIT)
SINGLE_EU_REINSTALL_LIMIT ?= $(SINGLE_EU_ANSIBLE_LIMIT)
SINGLE_EU_VERIFY_LIMIT ?= $(SINGLE_EU_ANSIBLE_LIMIT)
SINGLE_EU_COORDINATOR_LIMIT ?= eu:&coordinators
SINGLE_EU_DB_LIMIT ?= eu:&db_nodes
SINGLE_EU_TOOL_LIMIT ?= $(SINGLE_EU_ANSIBLE_LIMIT)
SINGLE_EU_EXPLAIN_LIMIT ?= $(SINGLE_EU_ANSIBLE_LIMIT)
RUN_LABEL ?= single-eu
EXPLAIN_RUN_ID ?= $(shell date -u +%Y%m%dT%H%M%SZ)
EXPLAIN_SQL_FILE ?=
EXPLAIN_RUN_DIR ?= $(GENERATED_RUNS_DIR)/ad-hoc-explain/$(EXPLAIN_RUN_ID)
EXPLAIN_SMOKE_SQL ?= SELECT 1;
INITIAL_EXPLAIN_SQL_FILE ?= ../psql-benchmarks/sql/stage_a/a1_rolling_aggregate.sql
INITIAL_EXPLAIN_LABEL ?= minimal-a1
INITIAL_EXPLAIN_VARS ?= lookback_days=30
QUERY_COLLECTION_SQL_FILE ?= ../psql-benchmarks/sql/stage_a/a1_rolling_aggregate.sql
QUERY_COLLECTION_LABEL ?= a1-smoke
QUERY_COLLECTION_VARS ?= lookback_days=30
QUERY_COLLECTION_DB_SNAPSHOTS ?= false
QUERY_COLLECTION_OS_SAMPLER ?= false
SWEEP_STATIC_LABEL ?= sweep-smoke
HARDWARE_SNAPSHOT_LABEL ?= hardware-smoke
QUERY_SWEEP_LABEL ?= query-sweep-smoke
QUERY_SWEEP_INSTANCE_MANIFEST ?=
QUERY_SWEEP_MAX_INSTANCES ?= 2
QUERY_SWEEP_GLOBAL_STATS_SCOPE ?= none
QUERY_SWEEP_TARGET_GROUP ?= coordinators
QUERY_SWEEP_TARGET_HOST ?=
QUERY_SWEEP_CITUS_EXPLAIN_ALL_TASKS ?= true
QUERY_SWEEP_FDW_AUTO_EXPLAIN ?= false
QUERY_SWEEP_HARD_TIMEOUT_SECONDS ?= 0
QUERY_SWEEP_TIMEOUT_GRACE_SECONDS ?= 30
DATASET_PROFILE ?= ../master-regimes/datasets/profiles/smoke.yml
DATASET_REGION ?= eu
DATASET_LOAD_METHOD ?= sql
DATASET_AUDIT_ONLY ?= false
DATABASE_SWEEP_CONFIG ?= configs/sweeps/eu-vps-smoke.yml
DATABASE_SWEEP_LABEL ?= eu-vps-smoke
CORPUS_EXECUTION_PLAN ?= ../master-regimes/generated/corpus/pre-us-pilot/corpus_execution_plan.yml
CORPUS_RUN_LABEL ?= corpus-run
CORPUS_RUN_DRY_RUN ?= false
CORPUS_RUN_GROUP_ID ?=
CORPUS_RUN_MAX_GROUPS ?=
CORPUS_RUN_MAX_INSTANCES_PER_GROUP ?=
CORPUS_LOGICAL_RUN_ID ?=
CORPUS_RERUN_OF ?=
CORPUS_RUN_ROOT ?= generated/runs/corpus-sweeps
CORPUS_LOGICAL_INDEX_DIR ?= $(CORPUS_RUN_ROOT)/_logical-runs/$(CORPUS_LOGICAL_RUN_ID)
CORPUS_RERUN_PLAN_LABEL ?= rerun
CORPUS_RERUN_PLAN_OUT ?=
CORPUS_RERUN_STATUSES ?= timeout,failed,missing,interrupted
CORPUS_RERUN_INCLUDE_MISSING_FROM_PLAN ?= false
CORPUS_RERUN_HARD_TIMEOUT_SECONDS ?=
CORPUS_RERUN_TIMEOUT_GRACE_SECONDS ?= 30
CONFIRMATORY_SKEW_CONFIG ?= ../master-regimes/configs/validation/confirmatory_skew_v1.yml
CONFIRMATORY_SKEW_PLAN ?= ../master-regimes/generated/corpus/confirmatory-skew-v1/corpus_execution_plan.yml
CONFIRMATORY_SKEW_SMOKE_LABEL ?= confirmatory-skew-v1-capability
STATS_CEB_PROFILE ?= ../master-regimes/datasets/profiles/stats-ceb-replicated.yml
STATS_CEB_SELECTION ?= ../master-regimes/external/stats-ceb/query-selection.yml
STATS_CEB_PREPARE_LABEL ?= stats-ceb-portability-v1-prepare
FDW_BOOTSTRAP_LABEL ?= gac-fdw-bootstrap
FDW_BOOTSTRAP_REGION ?= eu
GAC_ETL_BOOTSTRAP_LABEL ?= gac-etl-bootstrap
GAC_ETL_BOOTSTRAP_REGION ?= eu
GAC_ETL_BOOTSTRAP_LOOKBACK_DAYS ?= 30
QUERY_COLLECTION_PROFILING_ARGS = $(if $(filter true yes 1,$(QUERY_COLLECTION_DB_SNAPSHOTS)),--db-snapshots,) $(if $(filter true yes 1,$(QUERY_COLLECTION_OS_SAMPLER)),--os-sampler,)

EU_VPS_SINGLE_ARGS := TOPOLOGY=eu-vps-single SINGLE_EU_SYSTEM=configs/systems/eu-vps-single.yml SINGLE_EU_OUT=$(GENERATED_SYSTEMS_DIR)/eu-vps-single RUN_LABEL=eu-vps-single
EU_US_GAC_VPS_ARGS := TOPOLOGY=eu-us-gac-vps SINGLE_EU_SYSTEM=configs/systems/eu-us-gac-vps.yml SINGLE_EU_OUT=$(GENERATED_SYSTEMS_DIR)/eu-us-gac-vps RUN_LABEL=eu-us-gac-vps SINGLE_EU_ANSIBLE_LIMIT=db_nodes:analytics_clients:web_portals SINGLE_EU_PING_LIMIT=db_nodes:analytics_clients:web_portals SINGLE_EU_REINSTALL_LIMIT=db_nodes SINGLE_EU_VERIFY_LIMIT=db_nodes:analytics_clients SINGLE_EU_COORDINATOR_LIMIT=coordinators SINGLE_EU_DB_LIMIT=db_nodes SINGLE_EU_TOOL_LIMIT=db_nodes:analytics_clients SINGLE_EU_EXPLAIN_LIMIT=coordinators
EU_US_APAC_GAC_VPS_ARGS := TOPOLOGY=eu-us-apac-gac-vps SINGLE_EU_SYSTEM=configs/systems/eu-us-apac-gac-vps.yml SINGLE_EU_OUT=$(GENERATED_SYSTEMS_DIR)/eu-us-apac-gac-vps RUN_LABEL=eu-us-apac-gac-vps SINGLE_EU_ANSIBLE_LIMIT=db_nodes:analytics_clients SINGLE_EU_PING_LIMIT=db_nodes:analytics_clients SINGLE_EU_REINSTALL_LIMIT=db_nodes SINGLE_EU_VERIFY_LIMIT=db_nodes:analytics_clients SINGLE_EU_COORDINATOR_LIMIT=coordinators SINGLE_EU_DB_LIMIT=db_nodes SINGLE_EU_TOOL_LIMIT=db_nodes:analytics_clients SINGLE_EU_EXPLAIN_LIMIT=coordinators

validate:
	uv run master-regimes-infra validate-config --system $(SYSTEM)

render: configure-env-check
	uv run master-regimes-infra render-config --system $(SYSTEM) --out $(OUT)

topology-list:
	@echo "Supported topologies:"
	@echo "  eu-vps-single   -> configs/systems/eu-vps-single.yml"
	@echo "  eu-us-gac-vps   -> configs/systems/eu-us-gac-vps.yml"
	@echo "  eu-us-apac-gac-vps -> configs/systems/eu-us-apac-gac-vps.yml"

generated-tree:
	@find generated -maxdepth 3 -mindepth 1 -type d | sort

config-validate: validate

config-render: render

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest

lint:
	uv run ruff check .

configure-env:
	common-scripts/configure_env.sh

configure-env-check:
	common-scripts/configure_env.sh --only-missing

doctor: single-eu-doctor

ansible-deps:
	common-scripts/run_ansible.sh ansible-galaxy collection install -r requirements.yml

repo-sync-psql-benchmarks: single-eu-inventory
	python3 common-scripts/sync_remote_repo.py \
		--local-dir ../psql-benchmarks \
		--remote-dir /opt/psql-benchmarks \
		--group db_nodes \
		--delete

repo-sync-psql-benchmarks-analytics: single-eu-inventory
	python3 common-scripts/sync_remote_repo.py \
		--local-dir ../psql-benchmarks \
		--remote-dir /opt/psql-benchmarks \
		--group analytics_clients \
		--delete

repo-sync-psql-benchmarks-all: single-eu-wait-cloud-init single-eu-inventory
	python3 common-scripts/sync_remote_repo.py \
		--local-dir ../psql-benchmarks \
		--remote-dir /opt/psql-benchmarks \
		--group db_nodes \
		--delete
	python3 common-scripts/sync_remote_repo.py \
		--local-dir ../psql-benchmarks \
		--remote-dir /opt/psql-benchmarks \
		--group analytics_clients \
		--delete
	common-scripts/run_ansible.sh ansible-playbook playbooks/site.yml --limit 'db_nodes:analytics_clients' --tags psql_benchmarks -e psql_benchmarks_enabled=true -e psql_benchmarks_skip_git_update=true

eu-vps-single-up:
	$(MAKE) single-eu-up $(EU_VPS_SINGLE_ARGS)

eu-vps-single-down:
	$(MAKE) single-eu-down $(EU_VPS_SINGLE_ARGS)

eu-vps-single-plan:
	$(MAKE) single-eu-doctor single-eu-install single-eu-drift-check single-eu-tf-init single-eu-tf-plan single-eu-tf-show-plan $(EU_VPS_SINGLE_ARGS)

eu-vps-single-apply:
	$(MAKE) single-eu-tf-apply single-eu-wait-cloud-init single-eu-inventory single-eu-ansible single-eu-verify single-eu-manifest $(EU_VPS_SINGLE_ARGS)

eu-vps-single-ansible:
	$(MAKE) single-eu-install single-eu-drift-check single-eu-wait-cloud-init single-eu-inventory single-eu-ansible single-eu-verify single-eu-manifest $(EU_VPS_SINGLE_ARGS)

eu-vps-single-explain-smoke:
	$(MAKE) single-eu-explain-smoke $(EU_VPS_SINGLE_ARGS)

eu-vps-single-explain-run:
	$(MAKE) single-eu-explain-run $(EU_VPS_SINGLE_ARGS)

eu-vps-single-initial-explain:
	$(MAKE) single-eu-initial-explain $(EU_VPS_SINGLE_ARGS)

eu-vps-single-query-collect:
	$(MAKE) single-eu-query-collect $(EU_VPS_SINGLE_ARGS)

eu-vps-single-query-sweep:
	$(MAKE) single-eu-query-sweep $(EU_VPS_SINGLE_ARGS)

eu-vps-single-dataset-apply:
	$(MAKE) single-eu-dataset-apply $(EU_VPS_SINGLE_ARGS)

eu-vps-single-database-sweep:
	$(MAKE) single-eu-database-sweep $(EU_VPS_SINGLE_ARGS)

eu-vps-single-corpus-run:
	$(MAKE) single-eu-corpus-run $(EU_VPS_SINGLE_ARGS)

eu-vps-single-sweep-static:
	$(MAKE) single-eu-sweep-static $(EU_VPS_SINGLE_ARGS)

eu-vps-single-hardware-snapshot:
	$(MAKE) single-eu-hardware-snapshot $(EU_VPS_SINGLE_ARGS)

eu-us-gac-vps-up:
	$(MAKE) ansible-deps
	MASTER_REGIMES_UP_CONFIRM=create-eu-us-gac-vhp-shared-vpc \
		common-scripts/up_eu_us_gac_vhp_shared_vpc.sh

eu-us-gac-vps-down:
	MASTER_REGIMES_DESTROY_CONFIRM=destroy-eu-us-gac-vhp-shared-vpc \
		common-scripts/destroy_eu_us_gac_vhp_shared_vpc.sh

eu-us-gac-vps-plan:
	$(MAKE) single-eu-doctor single-eu-install single-eu-drift-check single-eu-tf-init single-eu-tf-plan single-eu-tf-show-plan $(EU_US_GAC_VPS_ARGS)

eu-us-gac-vps-apply:
	$(MAKE) eu-us-gac-vps-up

eu-us-gac-vps-ansible:
	$(MAKE) single-eu-install single-eu-drift-check single-eu-wait-cloud-init single-eu-inventory single-eu-ansible single-eu-verify single-eu-manifest $(EU_US_GAC_VPS_ARGS)

eu-us-gac-vps-ping:
	$(MAKE) single-eu-ping $(EU_US_GAC_VPS_ARGS)

eu-us-gac-vps-tools-sync:
	$(MAKE) repo-sync-psql-benchmarks-all $(EU_US_GAC_VPS_ARGS)
	$(MAKE) single-eu-datagen-deploy $(EU_US_GAC_VPS_ARGS)

eu-us-gac-vps-cloudb-web-deploy:
	$(MAKE) single-eu-cloudb-web-deploy $(EU_US_GAC_VPS_ARGS)

eu-us-gac-vps-apps-deploy:
	$(MAKE) eu-us-gac-vps-cloudb-web-deploy

eu-us-gac-vps-fdw-bootstrap:
	$(MAKE) single-eu-gac-fdw-bootstrap $(EU_US_GAC_VPS_ARGS)

eu-us-gac-vps-etl-bootstrap:
	$(MAKE) single-eu-gac-etl-bootstrap $(EU_US_GAC_VPS_ARGS)

eu-us-gac-vps-network-default-reset:
	$(MAKE) single-eu-network-default-reset $(EU_US_GAC_VPS_ARGS)

.PHONY: eu-us-gac-vps-lab-environment-probe single-eu-lab-environment-probe
eu-us-gac-vps-lab-environment-probe:
	$(MAKE) single-eu-lab-environment-probe $(EU_US_GAC_VPS_ARGS)

eu-us-gac-vps-stats-ceb-prepare: single-eu-inventory
	python3 common-scripts/apply_stats_ceb_profile.py \
		--profile "$(STATS_CEB_PROFILE)" --region eu \
		--out-root "$(GENERATED_RUNS_DIR)/dataset-loads"
	python3 common-scripts/apply_stats_ceb_profile.py \
		--profile "$(STATS_CEB_PROFILE)" --region us \
		--out-root "$(GENERATED_RUNS_DIR)/dataset-loads"
	python3 common-scripts/run_stats_ceb_fdw_bootstrap.py \
		--profile "$(STATS_CEB_PROFILE)" --region eu \
		--label "$(STATS_CEB_PREPARE_LABEL)" \
		--out-root "$(GENERATED_RUNS_DIR)/fdw-bootstrap"
	python3 common-scripts/run_stats_ceb_fdw_bootstrap.py \
		--profile "$(STATS_CEB_PROFILE)" --region us \
		--label "$(STATS_CEB_PREPARE_LABEL)" \
		--out-root "$(GENERATED_RUNS_DIR)/fdw-bootstrap"
	python3 common-scripts/validate_stats_ceb_correctness.py \
		--profile "$(STATS_CEB_PROFILE)" \
		--selection "$(STATS_CEB_SELECTION)" \
		--label "$(STATS_CEB_PREPARE_LABEL)" \
		--out-root "$(GENERATED_RUNS_DIR)/result-validation"

stats-ceb-correctness-dry-run: single-eu-inventory
	python3 common-scripts/validate_stats_ceb_correctness.py \
		--profile "$(STATS_CEB_PROFILE)" \
		--selection "$(STATS_CEB_SELECTION)" \
		--label "$(STATS_CEB_PREPARE_LABEL)-dry-run" \
		--dry-run \
		--out-root "$(GENERATED_RUNS_DIR)/result-validation"

eu-us-gac-vps-corpus-run:
	$(MAKE) single-eu-corpus-run $(EU_US_GAC_VPS_ARGS)

eu-us-apac-gac-vps-extend: configure-env-check ansible-deps
	MASTER_REGIMES_UP_CONFIRM=extend-eu-us-gac-with-apac \
		common-scripts/extend_eu_us_gac_with_apac.sh

eu-us-apac-gac-vps-apac-down: configure-env-check
	MASTER_REGIMES_DESTROY_CONFIRM=destroy-apac-extension \
		common-scripts/destroy_apac_extension.sh

eu-us-apac-gac-vps-ping:
	$(MAKE) single-eu-inventory $(EU_US_APAC_GAC_VPS_ARGS)
	common-scripts/run_ansible.sh ansible 'db_nodes:analytics_clients' -m ping

eu-us-apac-gac-vps-tools-sync:
	$(MAKE) repo-sync-psql-benchmarks-all $(EU_US_APAC_GAC_VPS_ARGS)
	$(MAKE) single-eu-datagen-deploy $(EU_US_APAC_GAC_VPS_ARGS)

eu-us-apac-gac-vps-corpus-run:
	$(MAKE) single-eu-corpus-run $(EU_US_APAC_GAC_VPS_ARGS)

confirmatory-skew-capability-smoke: single-eu-inventory
	python3 common-scripts/run_confirmatory_skew_capability_smoke.py \
		--config "$(CONFIRMATORY_SKEW_CONFIG)" \
		--plan "$(CONFIRMATORY_SKEW_PLAN)" \
		--label "$(CONFIRMATORY_SKEW_SMOKE_LABEL)"

confirmatory-skew-experiment: single-eu-inventory
	python3 common-scripts/run_confirmatory_skew_experiment.py \
		--config "$(CONFIRMATORY_SKEW_CONFIG)" \
		--plan "$(CONFIRMATORY_SKEW_PLAN)"

single-eu-doctor: configure-env-check
	common-scripts/single_eu_doctor.sh "$(SINGLE_EU_SYSTEM)" "$(SINGLE_EU_TF_DIR)"

single-eu-validate:
	uv run master-regimes-infra validate-config --system $(SINGLE_EU_SYSTEM)

single-eu-render: configure-env-check
	uv run master-regimes-infra render-config --system $(SINGLE_EU_SYSTEM) --out $(SINGLE_EU_OUT)

single-eu-install: single-eu-render
	mkdir -p $(SINGLE_EU_TF_DIR) ansible/group_vars
	install -m 0600 $(SINGLE_EU_OUT)/terraform/envs/eu/terraform.tfvars $(SINGLE_EU_TF_DIR)/terraform.tfvars
	install -m 0600 $(SINGLE_EU_OUT)/ansible/group_vars/all.yml ansible/group_vars/all.yml
	terraform fmt $(SINGLE_EU_OUT)/terraform/envs/eu/terraform.tfvars $(SINGLE_EU_TF_DIR)/terraform.tfvars

single-eu-drift-check: single-eu-render
	terraform fmt $(SINGLE_EU_OUT)/terraform/envs/eu/terraform.tfvars
	@if [[ ! -f "$(SINGLE_EU_TF_DIR)/terraform.tfvars" ]]; then echo "Missing $(SINGLE_EU_TF_DIR)/terraform.tfvars. Run: make single-eu-install"; exit 1; fi
	@cmp -s "$(SINGLE_EU_OUT)/terraform/envs/eu/terraform.tfvars" "$(SINGLE_EU_TF_DIR)/terraform.tfvars" || { echo "Drift: $(SINGLE_EU_TF_DIR)/terraform.tfvars differs from rendered config"; exit 1; }
	@cmp -s "$(SINGLE_EU_OUT)/ansible/group_vars/all.yml" "ansible/group_vars/all.yml" || { echo "Drift: ansible/group_vars/all.yml differs from rendered config"; exit 1; }
	@echo "OK: rendered and installed single-EU config match."

single-eu-tf-init:
	terraform -chdir=$(SINGLE_EU_TF_DIR) init -input=false

single-eu-tf-plan:
	mkdir -p $(dir $(SINGLE_EU_PLAN_FILE))
	terraform -chdir=$(SINGLE_EU_TF_DIR) plan -input=false -out=$(SINGLE_EU_PLAN_FILE)
	terraform -chdir=$(SINGLE_EU_TF_DIR) show -no-color $(SINGLE_EU_PLAN_FILE) > $(SINGLE_EU_PLAN_TEXT)
	@echo "Saved plan: $(SINGLE_EU_PLAN_FILE)"
	@echo "Saved readable plan: $(SINGLE_EU_PLAN_TEXT)"

single-eu-tf-show-plan:
	@if [[ ! -f "$(SINGLE_EU_PLAN_FILE)" ]]; then echo "Missing $(SINGLE_EU_PLAN_FILE). Run: make single-eu-tf-plan"; exit 1; fi
	terraform -chdir=$(SINGLE_EU_TF_DIR) show -no-color $(SINGLE_EU_PLAN_FILE)

single-eu-tf-apply:
	@if [[ ! -f "$(SINGLE_EU_PLAN_FILE)" ]]; then echo "Missing $(SINGLE_EU_PLAN_FILE). Run: make single-eu-tf-plan"; exit 1; fi
	terraform -chdir=$(SINGLE_EU_TF_DIR) apply -auto-approve $(SINGLE_EU_PLAN_FILE)

single-eu-tf-output:
	terraform -chdir=$(SINGLE_EU_TF_DIR) output

single-eu-tf-destroy-plan:
	mkdir -p $(dir $(SINGLE_EU_DESTROY_PLAN_FILE))
	terraform -chdir=$(SINGLE_EU_TF_DIR) plan -destroy -input=false -out=$(SINGLE_EU_DESTROY_PLAN_FILE)
	terraform -chdir=$(SINGLE_EU_TF_DIR) show -no-color $(SINGLE_EU_DESTROY_PLAN_FILE) > $(SINGLE_EU_DESTROY_PLAN_TEXT)
	@echo "Saved destroy plan: $(SINGLE_EU_DESTROY_PLAN_FILE)"
	@echo "Saved readable destroy plan: $(SINGLE_EU_DESTROY_PLAN_TEXT)"

single-eu-tf-show-destroy-plan:
	@if [[ ! -f "$(SINGLE_EU_DESTROY_PLAN_FILE)" ]]; then echo "Missing $(SINGLE_EU_DESTROY_PLAN_FILE). Run: make single-eu-tf-destroy-plan"; exit 1; fi
	terraform -chdir=$(SINGLE_EU_TF_DIR) show -no-color $(SINGLE_EU_DESTROY_PLAN_FILE)

single-eu-tf-destroy:
	@if [[ ! -f "$(SINGLE_EU_DESTROY_PLAN_FILE)" ]]; then echo "Missing $(SINGLE_EU_DESTROY_PLAN_FILE). Run: make single-eu-tf-destroy-plan"; exit 1; fi
	terraform -chdir=$(SINGLE_EU_TF_DIR) apply -auto-approve $(SINGLE_EU_DESTROY_PLAN_FILE)

single-eu-down: configure-env-check single-eu-tf-init single-eu-tf-destroy-plan single-eu-tf-destroy

single-eu-wait-ssh:
	@set -euo pipefail; \
	mapfile -t HOSTS < <(terraform -chdir=$(SINGLE_EU_TF_DIR) output -json ssh_commands | python3 common-scripts/terraform_ssh_hosts.py); \
	if [[ "$${#HOSTS[@]}" -eq 0 ]]; then echo "No SSH hosts found in $(SINGLE_EU_TF_DIR) outputs"; exit 1; fi; \
	common-scripts/wait_for_ssh_hosts.sh "$${HOSTS[@]}"

single-eu-wait-cloud-init: single-eu-wait-ssh
	@set -euo pipefail; \
	mapfile -t HOSTS < <(terraform -chdir=$(SINGLE_EU_TF_DIR) output -json ssh_commands | python3 common-scripts/terraform_ssh_hosts.py); \
	if [[ "$${#HOSTS[@]}" -eq 0 ]]; then echo "No SSH hosts found in $(SINGLE_EU_TF_DIR) outputs"; exit 1; fi; \
	common-scripts/wait_for_cloud_init_hosts.sh "$${HOSTS[@]}"

single-eu-inventory:
	mkdir -p ansible/inventory
	TF_BASE_DIR=$(CURDIR)/terraform python3 ansible/inventory/terraform_inventory.py > ansible/inventory/generated.json

single-eu-ping: single-eu-wait-cloud-init single-eu-inventory
	common-scripts/run_ansible.sh ansible '$(SINGLE_EU_PING_LIMIT)' -m ping

single-eu-ansible: single-eu-wait-cloud-init single-eu-inventory
	common-scripts/run_ansible.sh ansible-playbook playbooks/site.yml --limit '$(SINGLE_EU_ANSIBLE_LIMIT)'

single-eu-postgres-reinstall: single-eu-install single-eu-wait-cloud-init single-eu-inventory
	common-scripts/run_ansible.sh ansible-playbook playbooks/reinstall-postgresql.yml --limit '$(SINGLE_EU_REINSTALL_LIMIT)' -e postgresql_reinstall_confirm=true
	common-scripts/run_ansible.sh ansible-playbook playbooks/site.yml --limit '$(SINGLE_EU_ANSIBLE_LIMIT)'
	common-scripts/run_ansible.sh ansible-playbook playbooks/verify-citus.yml --limit '$(SINGLE_EU_VERIFY_LIMIT)'

single-eu-verify: single-eu-inventory
	common-scripts/run_ansible.sh ansible-playbook playbooks/verify-citus.yml --limit '$(SINGLE_EU_VERIFY_LIMIT)'

single-eu-datagen-deploy: single-eu-wait-cloud-init single-eu-inventory
	common-scripts/run_ansible.sh ansible-playbook playbooks/site.yml --limit '$(SINGLE_EU_COORDINATOR_LIMIT)' --tags citus_datagen -e citus_datagen_enabled=true

single-eu-bench-deploy: single-eu-wait-cloud-init single-eu-inventory
	common-scripts/run_ansible.sh ansible-playbook playbooks/site.yml --limit '$(SINGLE_EU_DB_LIMIT)' --tags psql_benchmarks -e psql_benchmarks_enabled=true

single-eu-tools-deploy: single-eu-wait-cloud-init single-eu-inventory
	common-scripts/run_ansible.sh ansible-playbook playbooks/site.yml --limit '$(SINGLE_EU_TOOL_LIMIT)' --tags citus_datagen,psql_benchmarks -e citus_datagen_enabled=true -e psql_benchmarks_enabled=true

single-eu-cloudb-web-deploy: single-eu-install single-eu-drift-check single-eu-wait-cloud-init single-eu-inventory
	common-scripts/run_ansible.sh ansible-playbook playbooks/site.yml --limit 'db_nodes:analytics_clients:web_portals' --tags cloudb_web

single-eu-manifest:
	python3 common-scripts/collect_single_eu_manifest.py --system "$(SINGLE_EU_SYSTEM)" --tf-dir "$(SINGLE_EU_TF_DIR)" --out-dir "$(GENERATED_RUNS_DIR)/infra-manifests" --label "$(RUN_LABEL)"

single-eu-explain-smoke: single-eu-inventory
	common-scripts/run_ansible.sh ansible-playbook playbooks/collect-explain-smoke.yml --limit '$(SINGLE_EU_EXPLAIN_LIMIT)' -e "explain_smoke_sql=$(EXPLAIN_SMOKE_SQL)"

single-eu-explain-run: single-eu-inventory
	@if [[ -z "$(EXPLAIN_SQL_FILE)" ]]; then echo "EXPLAIN_SQL_FILE=path/to/query.sql is required"; exit 1; fi
	@set -euo pipefail; \
	SQL_PATH="$(EXPLAIN_SQL_FILE)"; \
	if [[ "$$SQL_PATH" != /* ]]; then SQL_PATH="$(CURDIR)/$$SQL_PATH"; fi; \
	if [[ ! -f "$$SQL_PATH" ]]; then echo "SQL file not found: $$SQL_PATH"; exit 1; fi; \
	mkdir -p "$(EXPLAIN_RUN_DIR)/queries" "$(EXPLAIN_RUN_DIR)/plans"; \
	install -m 0644 "$$SQL_PATH" "$(EXPLAIN_RUN_DIR)/queries/query.sql"; \
	python3 common-scripts/collect_single_eu_manifest.py --system "$(SINGLE_EU_SYSTEM)" --tf-dir "$(SINGLE_EU_TF_DIR)" --out-dir "$(EXPLAIN_RUN_DIR)" --label "explain"; \
	common-scripts/run_ansible.sh ansible-playbook playbooks/collect-explain-smoke.yml --limit '$(SINGLE_EU_EXPLAIN_LIMIT)' -e "explain_sql_file=$$SQL_PATH" -e "explain_smoke_output_dir=$(EXPLAIN_RUN_DIR)/plans"

single-eu-initial-explain: single-eu-inventory
	python3 common-scripts/run_initial_explain.py \
		--sql-file "$(INITIAL_EXPLAIN_SQL_FILE)" \
		--label "$(INITIAL_EXPLAIN_LABEL)" \
		$(foreach var,$(INITIAL_EXPLAIN_VARS),--var $(var))

single-eu-query-collect: single-eu-inventory
	python3 common-scripts/run_query_collection.py \
		--sql-file "$(QUERY_COLLECTION_SQL_FILE)" \
		--label "$(QUERY_COLLECTION_LABEL)" \
		$(QUERY_COLLECTION_PROFILING_ARGS) \
		$(foreach var,$(QUERY_COLLECTION_VARS),--var $(var))

single-eu-query-sweep: single-eu-inventory
	@if [[ -z "$(QUERY_SWEEP_INSTANCE_MANIFEST)" ]]; then echo "QUERY_SWEEP_INSTANCE_MANIFEST=path/to/instance_manifest.csv is required"; exit 1; fi
	python3 common-scripts/run_query_collection_sweep.py \
		--instance-manifest "$(QUERY_SWEEP_INSTANCE_MANIFEST)" \
		--label "$(QUERY_SWEEP_LABEL)" \
		--max-instances "$(QUERY_SWEEP_MAX_INSTANCES)" \
		--global-stats-scope "$(QUERY_SWEEP_GLOBAL_STATS_SCOPE)" \
		--target-group "$(QUERY_SWEEP_TARGET_GROUP)" \
		$(if $(QUERY_SWEEP_TARGET_HOST),--target-host "$(QUERY_SWEEP_TARGET_HOST)",) \
		$(if $(filter-out 0,$(QUERY_SWEEP_HARD_TIMEOUT_SECONDS)),--hard-timeout-seconds "$(QUERY_SWEEP_HARD_TIMEOUT_SECONDS)" --timeout-grace-seconds "$(QUERY_SWEEP_TIMEOUT_GRACE_SECONDS)",) \
		$(if $(filter true yes 1,$(QUERY_SWEEP_FDW_AUTO_EXPLAIN)),--fdw-auto-explain,) \
		$(if $(filter false no 0,$(QUERY_SWEEP_CITUS_EXPLAIN_ALL_TASKS)),--no-citus-explain-all-tasks,)

single-eu-dataset-apply: single-eu-inventory
	python3 common-scripts/apply_dataset_profile.py \
		--profile "$(DATASET_PROFILE)" \
		--region "$(DATASET_REGION)" \
		--load-method "$(DATASET_LOAD_METHOD)" \
		$(if $(filter true yes 1,$(DATASET_AUDIT_ONLY)),--audit-only,)

single-eu-database-sweep: single-eu-inventory
	python3 common-scripts/run_database_sweep.py \
		--sweep "$(DATABASE_SWEEP_CONFIG)" \
		--label "$(DATABASE_SWEEP_LABEL)"

single-eu-corpus-run: $(if $(filter true yes 1,$(CORPUS_RUN_DRY_RUN)),,single-eu-inventory)
	python3 common-scripts/run_corpus_execution_plan.py \
		--plan "$(CORPUS_EXECUTION_PLAN)" \
		--label "$(CORPUS_RUN_LABEL)" \
		$(if $(CORPUS_RUN_GROUP_ID),--group-id "$(CORPUS_RUN_GROUP_ID)",) \
		$(if $(CORPUS_RUN_MAX_GROUPS),--max-groups "$(CORPUS_RUN_MAX_GROUPS)",) \
		$(if $(CORPUS_RUN_MAX_INSTANCES_PER_GROUP),--max-instances-per-group "$(CORPUS_RUN_MAX_INSTANCES_PER_GROUP)",) \
		$(if $(CORPUS_LOGICAL_RUN_ID),--logical-run-id "$(CORPUS_LOGICAL_RUN_ID)",) \
		$(if $(CORPUS_RERUN_OF),--rerun-of "$(CORPUS_RERUN_OF)",) \
		$(if $(filter true yes 1,$(CORPUS_RUN_DRY_RUN)),--dry-run,)

corpus-run-index:
	python3 common-scripts/index_corpus_run_attempts.py \
		--corpus-run-root "$(CORPUS_RUN_ROOT)" \
		--logical-run-id "$(CORPUS_LOGICAL_RUN_ID)"

corpus-rerun-plan:
	python3 common-scripts/build_corpus_rerun_plan.py \
		--source-plan "$(CORPUS_EXECUTION_PLAN)" \
		--logical-index-dir "$(CORPUS_LOGICAL_INDEX_DIR)" \
		--label "$(CORPUS_RERUN_PLAN_LABEL)" \
		--statuses "$(CORPUS_RERUN_STATUSES)" \
		$(if $(CORPUS_RERUN_PLAN_OUT),--out-dir "$(CORPUS_RERUN_PLAN_OUT)",) \
		$(if $(filter true yes 1,$(CORPUS_RERUN_INCLUDE_MISSING_FROM_PLAN)),--include-missing-from-source-plan,) \
		$(if $(CORPUS_RERUN_HARD_TIMEOUT_SECONDS),--hard-timeout-seconds "$(CORPUS_RERUN_HARD_TIMEOUT_SECONDS)" --timeout-grace-seconds "$(CORPUS_RERUN_TIMEOUT_GRACE_SECONDS)",)

single-eu-sweep-static: single-eu-inventory
	python3 common-scripts/run_sweep_static_snapshot.py \
		--label "$(SWEEP_STATIC_LABEL)"

single-eu-hardware-snapshot: single-eu-inventory
	python3 common-scripts/collect_hardware_snapshot.py \
		--label "$(HARDWARE_SNAPSHOT_LABEL)"

single-eu-gac-fdw-bootstrap: single-eu-inventory
	python3 common-scripts/run_gac_fdw_bootstrap.py \
		--label "$(FDW_BOOTSTRAP_LABEL)" \
		--region "$(FDW_BOOTSTRAP_REGION)"

single-eu-gac-etl-bootstrap: single-eu-inventory
	python3 common-scripts/run_gac_etl_bootstrap.py \
		--label "$(GAC_ETL_BOOTSTRAP_LABEL)" \
		--region "$(GAC_ETL_BOOTSTRAP_REGION)" \
		--lookback-days "$(GAC_ETL_BOOTSTRAP_LOOKBACK_DAYS)"

single-eu-network-default-reset: single-eu-inventory
	python3 common-scripts/manage_network_latency.py \
		--action reset \
		--profile-json '{"id":"viewer-default-analytics-egress","scope":"analytics_egress_to_region","target_region_ids":["eu","us","apac"],"configured_delay_ms":0,"configured_jitter_ms":0,"configured_loss_percent":0}' \
		--out-dir "$(GENERATED_RUNS_DIR)/network-default-reset" \
		--label "viewer-default-analytics-egress"
	python3 common-scripts/manage_network_pressure.py \
		--action reset \
		--profile-json '{"id":"viewer-default-region-egress","scope":"region_egress_to_analytics","target_region_ids":["eu","us","apac"],"configured_delay_ms":0,"configured_jitter_ms":0,"configured_loss_percent":0,"configured_bandwidth_mbit":0}' \
		--out-dir "$(GENERATED_RUNS_DIR)/network-default-reset" \
		--label "viewer-default-region-egress"

single-eu-lab-environment-probe: single-eu-inventory
	python3 common-scripts/probe_lab_environment.py \
		--inventory ansible/inventory/generated.json \
		--out-root "$(GENERATED_RUNS_DIR)/lab-environment-probes"

single-eu-up: single-eu-doctor single-eu-install single-eu-drift-check ansible-deps single-eu-tf-init single-eu-tf-plan single-eu-tf-apply single-eu-wait-cloud-init single-eu-inventory single-eu-ansible single-eu-verify single-eu-manifest
