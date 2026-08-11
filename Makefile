.PHONY: verify public-navigation public-audit public-audit-full public-check reproducibility-catalog reproducibility-check reproducibility-audit reproducibility-audit-full retrieval-density-audit source-test examples examples-check extract-indexes extract-raw corpus-list corpus-validate corpus-render corpus-stage corpus-prepare corpus-dry-run corpus-run corpus-index corpus-rerun-plan feature-matrix semantic-matrix semantic-model semantic-rebuild semantic-compare actionability-sync infra-env infra-plan infra-up infra-ping infra-down release-manifest

PYTHON ?= python3
CORPUS ?= clean-run-v1
SOURCE_ROOT := $(CURDIR)/sources
EXPERIMENT_ROOT := $(SOURCE_ROOT)/master-regimes
INFRA_ROOT := $(SOURCE_ROOT)/master-regimes-infra
SOURCE_PYTHON := $(EXPERIMENT_ROOT)/.venv/bin/python
EXPERIMENT_TESTS := \
	tests/test_confirmatory_action_replication.py \
	tests/test_dba_local_memory_panel.py \
	tests/test_n3_topology_memory_experiment.py \
	tests/test_representation_ablation_e1_e4.py \
	tests/test_representation_value_ablation.py
INFRA_TESTS := \
	tests/test_apply_dataset_profile.py \
	tests/test_lab_default_reset_contract.py \
	tests/test_lab_environment_probe.py \
	tests/test_logical_run_index.py \
	tests/test_manage_network_pressure.py \
	tests/test_runtime_order_segments.py

verify:
	$(PYTHON) scripts/build_public_navigation.py
	$(PYTHON) scripts/audit_public_release.py
	$(PYTHON) scripts/verify_reproducibility_catalog.py
	$(PYTHON) scripts/build_release_manifest.py --root .
	$(PYTHON) scripts/run_reproducibility_audits.py
	$(PYTHON) scripts/build_release_manifest.py --root .
	$(PYTHON) scripts/verify_release.py --root .

public-navigation:
	$(PYTHON) scripts/build_public_navigation.py

public-audit:
	$(PYTHON) scripts/audit_public_release.py

public-audit-full:
	$(PYTHON) scripts/audit_public_release.py --archives --history

public-check: public-navigation public-audit

reproducibility-catalog:
	$(PYTHON) scripts/build_reproducibility_catalog.py

reproducibility-check:
	$(PYTHON) scripts/verify_reproducibility_catalog.py

reproducibility-audit:
	$(PYTHON) scripts/run_reproducibility_audits.py

reproducibility-audit-full:
	$(PYTHON) scripts/run_reproducibility_audits.py --full-hash

retrieval-density-audit:
	mkdir -p build/retrieval-density-matplotlib build/.uv-cache
	test -x $(SOURCE_PYTHON) || (cd $(EXPERIMENT_ROOT) && UV_CACHE_DIR=../../build/.uv-cache uv sync --frozen)
	cd $(EXPERIMENT_ROOT) && PYTHONPATH=src MPLCONFIGDIR=../../build/retrieval-density-matplotlib $(SOURCE_PYTHON) \
		../../releases/retrieval-density-geometry-audit-v1/source/116_retrieval_density_geometry_audit.py \
		--project-root . \
		--path-root ../.. \
		--contract configs/validation/confirmatory_action_replication_v1.yml \
		--reference-report ../../releases/retrieval-density-geometry-audit-v1/inputs/reference \
		--final-dba-dir ../../releases/retrieval-density-geometry-audit-v1/inputs/final-dba \
		--topology-dir ../../releases/retrieval-density-geometry-audit-v1/inputs/topology \
		--confirmatory-dir ../../releases/confirmatory-action-replication-v1 \
		--broad-release ../../releases/retrieval-density-geometry-audit-v1/inputs/broad \
		--out-dir ../../build/retrieval-density-geometry-audit-v1

examples:
	$(PYTHON) scripts/build_representative_cases.py \
		--source-root ../master-regimes \
		--output-root examples

examples-check:
	$(PYTHON) scripts/build_representative_cases.py \
		--source-root ../master-regimes \
		--output-root examples \
		--check

source-test:
	test -x $(SOURCE_PYTHON) || (cd $(EXPERIMENT_ROOT) && uv sync --frozen)
	cd $(EXPERIMENT_ROOT) && PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(SOURCE_PYTHON) -m pytest -q $(EXPERIMENT_TESTS)
	cd $(INFRA_ROOT) && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(SOURCE_PYTHON) -m pytest -q $(INFRA_TESTS)
	cd $(SOURCE_ROOT)/citus-datagen && PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(SOURCE_PYTHON) -m pytest -q tests/test_tenant_ranges.py
	cd $(SOURCE_ROOT)/psql-benchmarks && PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(SOURCE_PYTHON) -m pytest -q tests/test_os_sampler.py
	$(MAKE) verify

extract-indexes:
	$(PYTHON) scripts/extract_artifacts.py --root . --kind logical-indexes

extract-raw:
	$(PYTHON) scripts/extract_artifacts.py --root . --kind raw-attempts

corpus-list:
	$(PYTHON) scripts/corpus_workflow.py list

corpus-validate:
	$(PYTHON) scripts/corpus_workflow.py validate --corpus $(CORPUS)

corpus-render:
	$(PYTHON) scripts/corpus_workflow.py render --corpus $(CORPUS)

corpus-stage:
	$(PYTHON) scripts/corpus_workflow.py stage --corpus $(CORPUS)

corpus-prepare:
	$(PYTHON) scripts/corpus_workflow.py prepare --corpus $(CORPUS)

corpus-dry-run:
	$(PYTHON) scripts/corpus_workflow.py dry-run --corpus $(CORPUS)

corpus-run:
	$(PYTHON) scripts/corpus_workflow.py run --corpus $(CORPUS) --execute

corpus-index:
	$(PYTHON) scripts/corpus_workflow.py index --corpus $(CORPUS)

corpus-rerun-plan:
	$(PYTHON) scripts/corpus_workflow.py rerun-plan --corpus $(CORPUS)

feature-matrix:
	$(PYTHON) scripts/corpus_workflow.py features --corpus $(CORPUS)

semantic-matrix:
	mkdir -p build/semantic-v2
	cd $(EXPERIMENT_ROOT) && uv run python ../../scripts/build_semantic_matrix.py \
		--out-dir ../../build/semantic-v2

semantic-model:
	mkdir -p build/semantic-v2-model
	cd $(EXPERIMENT_ROOT) && uv run python ../../scripts/reproduce_semantic_model.py \
		--weighted-matrix ../../build/semantic-v2/semantic_v2_weighted.csv \
		--out-dir ../../build/semantic-v2-model

semantic-rebuild: semantic-matrix semantic-model

semantic-compare:
	$(PYTHON) scripts/compare_semantic_outputs.py --root .

actionability-sync:
	$(PYTHON) scripts/sync_actionability_artifacts.py
	$(PYTHON) scripts/sanitize_public_artifacts.py \
		artifacts/results/pressure-actionability-v1 \
		artifacts/rendered-corpora/pressure-raw-v1-n3-colocation-holdout \
		artifacts/logical-indexes/pressure-raw-v1-n3-colocation-holdout.tar.gz

infra-env:
	$(MAKE) -C $(INFRA_ROOT) configure-env-check

infra-plan:
	$(MAKE) -C $(INFRA_ROOT) eu-us-gac-vps-plan

infra-up:
	$(MAKE) -C $(INFRA_ROOT) eu-us-gac-vps-up

infra-ping:
	$(MAKE) -C $(INFRA_ROOT) eu-us-gac-vps-ping

infra-down:
	$(MAKE) -C $(INFRA_ROOT) eu-us-gac-vps-down

release-manifest: public-navigation public-audit reproducibility-audit
	$(PYTHON) scripts/build_release_manifest.py --root .
