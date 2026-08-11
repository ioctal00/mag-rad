.PHONY: doctor init-smoke render-smoke test lint thesis-lint check-thesis clean-run-validate clean-run-render clean-run-dry-run clean-run-start clean-run-probe-dry-run clean-run-probe-start clean-run-index clean-run-rerun-plan wan-run-validate wan-run-render wan-run-dry-run wan-run-start wan-run-probe-start wan-run-index region-imbalance-run-validate region-imbalance-run-render region-imbalance-run-start region-imbalance-run-probe-start region-imbalance-run-index region-asymmetry-run-validate region-asymmetry-run-render region-asymmetry-run-dry-run region-asymmetry-run-start region-asymmetry-run-probe-start region-asymmetry-run-index region-asymmetry-run-script skew-replacement-rerun validation-holdout-validate validation-holdout-render validation-holdout-dry-run validation-holdout-start validation-holdout-probe-start validation-holdout-index validation-holdout-script companion-runs-overnight logical-run-index feature-matrix clustering-dataset clustering-ready-gates corpus-coverage-gate baseline-coverage-report nplusone-contract-gate clustering-ready-audit collector-correctness-audit reproducibility-package repeatability-selection repeatability-dry-run repeatability-local-gate repeatability-infra-dry-run repeatability-smoke-infra-dry-run repeatability-smoke-start repeatability-start repeatability-index repeatability-rerun-plan repeatability-feature-matrix repeatability-analyze confirmatory-skew-plan confirmatory-skew-local-gate confirmatory-skew-capability-review confirmatory-skew-execution-review confirmatory-skew-analysis guided-example-evidence guided-example-final-audit thesis-numeric-consistency-audit thesis-claim-evidence-audit thesis-local-reproduction thesis-finalization-audit stats-ceb-local-gate stats-ceb-validate stats-ceb-render stats-ceb-infra-dry-run stats-ceb-start stats-ceb-index stats-ceb-feature-matrix stats-ceb-analyze stats-ceb-representation-audit semantic-v2-feature-audit semantic-v2-model-freeze semantic-v2-final-consistency semantic-v2-thesis-claims semantic-v2-thesis-results semantic-v2-thesis-defense semantic-v2-release-audit stats-ceb-v2-prepare-selection stats-ceb-v2-local-gate stats-ceb-v2-validate stats-ceb-v2-render stats-ceb-v2-infra-dry-run stats-ceb-v2-start stats-ceb-v2-index stats-ceb-v2-feature-matrix stats-ceb-v2-analyze stats-ceb-v2b-prepare-selection stats-ceb-v2b-local-gate stats-ceb-v2b-validate stats-ceb-v2b-render stats-ceb-v2b-infra-dry-run stats-ceb-v2b-start stats-ceb-v2b-index stats-ceb-v2b-feature-matrix stats-ceb-v2b-analyze stats-ceb-full-prepare-selection stats-ceb-full-local-gate stats-ceb-full-validate stats-ceb-full-render stats-ceb-full-infra-dry-run stats-ceb-full-start stats-ceb-full-index stats-ceb-full-feature-matrix stats-ceb-full-analyze stats-ceb-fuzzifier-sensitivity stats-ceb-full-run stats-ceb-recovery-contract-audit stats-ceb-recovery-local-gate stats-ceb-recovery-validate stats-ceb-recovery-render stats-ceb-recovery-infra-dry-run stats-ceb-recovery-start stats-ceb-recovery-index stats-ceb-recovery-feature-matrix stats-ceb-recovery-analyze stats-ceb-recovery-script pressure-smoke-validate pressure-smoke-render pressure-smoke-infra-dry-run pressure-smoke-start pressure-smoke-index pressure-smoke-feature-matrix pressure-smoke-analyze pressure-program-build pressure-program-dry-run pressure-program-start pressure-program-status pressure-raw-consolidate pressure-raw-explore pressure-mitigation-action-audit pressure-mitigation-correctness-prepare pressure-mitigation-correctness-local-gate pressure-mitigation-correctness-dry-run pressure-mitigation-correctness-start pressure-mitigation-correctness-status pressure-mitigation-correctness-analyze pressure-colocation-gain-model remote-edge-probe-validate remote-edge-probe-render remote-edge-probe-local-gate remote-edge-probe-infra-dry-run remote-edge-probe-start remote-edge-probe-index remote-edge-probe-analyze feedback-loop-analysis

UV_CACHE_DIR ?= $(CURDIR)/tmp/.uv-cache
export UV_CACHE_DIR

feedback-loop-analysis:
	uv run python analysis/scripts/agent/112_feedback_loop_analysis.py
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q tests/test_feedback_loop_analysis.py

THESIS_RUFF_SCOPE := \
	analysis/scripts/agent/38_collector_correctness_audit.py \
	analysis/scripts/agent/39_review_collector_selection.py \
	analysis/scripts/agent/40_build_reproducibility_package.py \
	analysis/scripts/agent/45_repeatability_thesis_figures.py \
	analysis/scripts/agent/46_repeatability_thesis_tables.py \
	analysis/scripts/agent/47_collector_correctness_thesis_tables.py \
	analysis/scripts/agent/48_reproducibility_thesis_tables.py \
	analysis/scripts/agent/49_thesis_numeric_consistency_audit.py \
	analysis/scripts/agent/50_thesis_claim_evidence_audit.py \
	analysis/scripts/agent/51_thesis_local_reproduction.py \
	analysis/scripts/agent/52_thesis_finalization_audit.py \
	analysis/scripts/agent/53_build_confirmatory_skew_plan.py \
	analysis/scripts/agent/54_confirmatory_skew_local_readiness.py \
	analysis/scripts/agent/55_confirmatory_skew_capability_review.py \
	analysis/scripts/agent/56_confirmatory_skew_execution_review.py \
	analysis/scripts/agent/57_confirmatory_skew_analysis.py \
	analysis/scripts/agent/58_build_guided_example_evidence.py \
	analysis/scripts/agent/59_guided_example_final_audit.py \
	analysis/scripts/agent/60_representation_geometry_audit.py \
	analysis/scripts/agent/61_feature_semantic_contract_audit.py \
	analysis/scripts/agent/62_freeze_semantic_v2_model.py \
	analysis/scripts/agent/63_semantic_v2_holdout_analysis.py \
	analysis/scripts/agent/64_semantic_v2_final_consistency.py \
	analysis/scripts/agent/65_semantic_v2_thesis_claim_audit.py \
	analysis/scripts/agent/66_semantic_v2_thesis_results_package.py \
	analysis/scripts/agent/67_semantic_v2_appendix_defense_audit.py \
	analysis/scripts/agent/68_semantic_v2_final_release_audit.py \
	analysis/scripts/agent/69_fuzzifier_sensitivity_audit.py \
	analysis/scripts/agent/70_stats_ceb_extended_recovery.py \
	src/master_regimes/collector_audit.py \
	src/master_regimes/confirmatory_skew.py \
	src/master_regimes/extract/query_sweep_index.py \
	src/master_regimes/feature_matrix.py \
	src/master_regimes/representation_audit.py \
	src/master_regimes/stats_ceb.py \
	tests/test_collector_audit.py \
	tests/test_confirmatory_skew.py \
	tests/test_confirmatory_skew_analysis.py \
	tests/test_confirmatory_skew_execution_review.py \
	tests/test_representation_audit.py \
	tests/test_semantic_v2_consistency.py \
	tests/test_stats_ceb.py \
	tests/test_stats_ceb_recovery.py \
	tests/test_stats_ceb_plan21.py \
	tests/test_guided_example_evidence.py \
	tests/test_query_sweep_index.py \
	tests/test_reproducibility_package.py

MASTER_REGIMES_INFRA_DIR ?= ../master-regimes-infra
PRESSURE_SMOKE_MANIFEST ?= workloads/corpus/corpus_manifest.pressure-smoke-v2.yml
PRESSURE_SMOKE_OUT ?= generated/corpus/pressure-smoke-v2
PRESSURE_SMOKE_PLAN ?= ../master-regimes/$(PRESSURE_SMOKE_OUT)/corpus_execution_plan.yml
PRESSURE_SMOKE_LOGICAL_RUN_ID ?= pressure-intervention-smoke-v2
PRESSURE_SMOKE_DRY_RUN_LOGICAL_RUN_ID ?= pressure-intervention-smoke-v2-dry-run
PRESSURE_SMOKE_LABEL ?= pressure-intervention-smoke-v2-attempt-01
PRESSURE_SMOKE_LOGICAL_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(PRESSURE_SMOKE_LOGICAL_RUN_ID)
PRESSURE_SMOKE_FEATURE_DIR ?= analysis/features/$(PRESSURE_SMOKE_LOGICAL_RUN_ID)
PRESSURE_SMOKE_REPORT_DIR ?= analysis/reports/$(PRESSURE_SMOKE_LOGICAL_RUN_ID)
PRESSURE_WORKER_SKEW_PAIRS ?= analysis/reports/confirmatory-skew-v1-capability-smoke/capability_smoke_query_pairs.csv
PRESSURE_WORKER_SKEW_CONFIG ?= $(CURDIR)/configs/validation/pressure_worker_skew_smoke_v1.yml
PRESSURE_WORKER_SKEW_PLAN ?= $(CURDIR)/generated/corpus/pressure-worker-skew-smoke-v1/corpus_execution_plan.yml
PRESSURE_WORKER_SKEW_SELECTION ?= $(CURDIR)/workloads/corpus/pressure_worker_skew_smoke_v1_selection.csv
PRESSURE_WORKER_SKEW_RUN_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/confirmatory-skew-capability-smoke/20260729T161323Z-pressure-worker-skew-target-v3
PRESSURE_WORKER_SKEW_REPORT_DIR ?= $(CURDIR)/analysis/reports/pressure-worker-skew-smoke-v1
PRESSURE_WORKER_SKEW_TARGET ?= $(PRESSURE_WORKER_SKEW_REPORT_DIR)/worker_skew_target.csv
PRESSURE_PROGRAM_CONFIG ?= $(CURDIR)/configs/validation/pressure_intervention_program_v1.yml
PRESSURE_PROGRAM_OUT ?= $(CURDIR)/generated/corpus/pressure-intervention-v1
PRESSURE_PROGRAM_PLAN ?= $(PRESSURE_PROGRAM_OUT)/pressure_intervention_program.yml
PRESSURE_PROGRAM_STATE_DIR ?= $(CURDIR)/generated/pressure-intervention-runs/pressure-intervention-v1
PRESSURE_RAW_PROGRAM ?= $(CURDIR)/generated/corpus/pressure-raw-v1/pressure_raw_program.yml
PRESSURE_RAW_CONSOLIDATED_OUT ?= $(CURDIR)/generated/pressure-raw-runs/_program/pressure-raw-v1
PRESSURE_RAW_BATCH ?= batch-000-collection-smoke
PRESSURE_RAW_STATE_DIR ?=
PRESSURE_RAW_EXPLORATORY_OUT ?= $(CURDIR)/analysis/reports/pressure-raw-v1-exploratory
PRESSURE_MITIGATION_ACTION_CONTRACT ?= $(CURDIR)/configs/validation/mitigation_action_audit_v1.yml
PRESSURE_MITIGATION_ACTION_OUT ?= $(CURDIR)/analysis/reports/pressure-raw-v1-mitigation-action-audit
PRESSURE_CROSS_ACTION_CONTRACT ?= $(CURDIR)/configs/validation/cross_action_feasibility_v1.yml
PRESSURE_CROSS_ACTION_OUT ?= $(CURDIR)/analysis/reports/pressure-raw-v1-cross-action-feasibility
CROSS_ACTION_PILOT_MANIFEST ?= $(CURDIR)/workloads/corpus/corpus_manifest.cross-action-pilot-v1.yml
CROSS_ACTION_PILOT_OUT ?= $(CURDIR)/generated/corpus/cross-action-pilot-v1-20260802-bundled
CROSS_ACTION_PILOT_PLAN ?= $(CROSS_ACTION_PILOT_OUT)/corpus_execution_plan.yml
CROSS_ACTION_PILOT_CONTRACT ?= $(CURDIR)/configs/validation/cross_action_pilot_v1.yml
CROSS_ACTION_PILOT_LOGICAL_RUN_ID ?= cross-action-pilot-v1
CROSS_ACTION_PILOT_RUN_LABEL ?= cross-action-pilot-v1-attempt-01
CROSS_ACTION_PILOT_LOGICAL_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(CROSS_ACTION_PILOT_LOGICAL_RUN_ID)
CROSS_ACTION_PILOT_REPORT_OUT ?= $(CURDIR)/analysis/reports/cross-action-pilot-v1
CROSS_ACTION_PILOT_FEATURE_OUT ?= $(CURDIR)/analysis/features/cross-action-pilot-v1
CROSS_ACTION_PILOT_SMOKE_GROUP ?= cross-action-pilot-v1__raw-small-balanced-v1__runtime-bundle-multi-edge__analytics_clients
CROSS_ACTION_PILOT_SMOKE_LOGICAL_RUN_ID ?= cross-action-pilot-v1-smoke
CROSS_ACTION_PILOT_SMOKE_LABEL ?= cross-action-pilot-v1-smoke-attempt-01
FUZZY_INTERVENTION_MEMORY_CONTRACT ?= $(CURDIR)/configs/models/fuzzy_intervention_memory_v1.yml
FUZZY_INTERVENTION_MEMORY_OUT ?= $(CURDIR)/analysis/reports/fuzzy-intervention-memory-v1
FUZZY_MEMORY_TOPK_MANIFEST ?= $(CURDIR)/workloads/corpus/corpus_manifest.fuzzy-memory-topk-panel-v1.yml
FUZZY_MEMORY_TOPK_OUT ?= $(CURDIR)/generated/corpus/fuzzy-memory-topk-panel-v1
FUZZY_MEMORY_TOPK_PLAN ?= $(FUZZY_MEMORY_TOPK_OUT)/corpus_execution_plan.yml
FUZZY_MEMORY_TOPK_CONTRACT ?= $(CURDIR)/configs/validation/fuzzy_memory_topk_panel_v1.yml
FUZZY_MEMORY_TOPK_REPORT_OUT ?= $(CURDIR)/analysis/reports/fuzzy-memory-topk-panel-v1
FUZZY_MEMORY_TOPK_LOGICAL_RUN_ID ?= fuzzy-memory-topk-panel-v1
FUZZY_MEMORY_TOPK_RUN_LABEL ?= fuzzy-memory-topk-panel-v1-attempt-01
FUZZY_MEMORY_TOPK_LOGICAL_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(FUZZY_MEMORY_TOPK_LOGICAL_RUN_ID)
FUZZY_MEMORY_TOPK_SMOKE_MANIFEST ?= $(CURDIR)/workloads/corpus/corpus_manifest.fuzzy-memory-topk-smoke-v1.yml
FUZZY_MEMORY_TOPK_SMOKE_OUT ?= $(CURDIR)/generated/corpus/fuzzy-memory-topk-smoke-v1
FUZZY_MEMORY_TOPK_SMOKE_PLAN ?= $(FUZZY_MEMORY_TOPK_SMOKE_OUT)/corpus_execution_plan.yml
FUZZY_MEMORY_TOPK_SMOKE_LOGICAL_RUN_ID ?= fuzzy-memory-topk-smoke-v1
FUZZY_MEMORY_TOPK_SMOKE_RUN_LABEL ?= fuzzy-memory-topk-smoke-v1-attempt-01
DBA_MEMORY_PANEL_CONTRACT ?= $(CURDIR)/configs/validation/dba_local_memory_panel_v1.yml
DBA_MEMORY_PANEL_SOURCE_DIR ?= $(CURDIR)/generated/corpus/dba-local-memory-v1-source
DBA_MEMORY_PANEL_MANIFEST ?= $(DBA_MEMORY_PANEL_SOURCE_DIR)/corpus_manifest.yml
DBA_MEMORY_PANEL_OUT ?= $(CURDIR)/generated/corpus/dba-local-memory-v1
DBA_MEMORY_PANEL_PLAN ?= $(DBA_MEMORY_PANEL_OUT)/corpus_execution_plan.yml
DBA_MEMORY_PANEL_LOGICAL_RUN_ID ?= dba-local-memory-panel-v1
DBA_MEMORY_PANEL_RUN_LABEL ?= dba-local-memory-panel-v1-attempt-01
DBA_MEMORY_PANEL_LOGICAL_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(DBA_MEMORY_PANEL_LOGICAL_RUN_ID)
DBA_MEMORY_PANEL_REPORT_OUT ?= $(CURDIR)/analysis/reports/dba-local-memory-panel-v1
REPRESENTATION_VALUE_ABLATION_CONTRACT ?= $(CURDIR)/configs/validation/representation_value_ablation_v1.yml
REPRESENTATION_VALUE_ABLATION_OUT ?= $(CURDIR)/analysis/reports/representation-value-ablation-v1
REPRESENTATION_VALUE_ABLATION_RELEASE_OUT ?= $(CURDIR)/releases/representation-value-ablation-v1
REPRESENTATION_E1_E4_CONTRACT ?= $(CURDIR)/configs/validation/representation_ablation_e1_e4_v1.yml
REPRESENTATION_E1_E4_OUT ?= $(CURDIR)/analysis/reports/representation-ablation-e1-e4-v1
REPRESENTATION_E1_E4_RELEASE_OUT ?= $(CURDIR)/releases/representation-ablation-e1-e4-v1
CONSOLIDATED_EVALUATION_CONTRACT ?= $(CURDIR)/configs/validation/consolidated_evaluation_v1.yml
CONSOLIDATED_EVALUATION_OUT ?= $(CURDIR)/analysis/reports/consolidated-evaluation-v1
CONSOLIDATED_EVALUATION_RELEASE_OUT ?= $(CURDIR)/releases/consolidated-evaluation-v1
CONSOLIDATED_EVALUATION_THESIS_ROOT ?= $(CURDIR)/../master-regimes-thesis
CONSOLIDATED_EVALUATION_MANUSCRIPT_AUDIT ?= $(CURDIR)/analysis/reports/consolidated-evaluation-v1/manuscript_consistency_audit.json
N3_TOPOLOGY_MEMORY_CONTRACT ?= $(CURDIR)/configs/validation/n3_topology_memory_experiment_v1.yml
N3_TOPOLOGY_MEMORY_WORK_DIR ?= $(CURDIR)/generated/corpus/n3-topology-memory-v1
N3_TOPOLOGY_MEMORY_REPORT_OUT ?= $(CURDIR)/analysis/reports/n3-topology-memory-v1
N3_TOPOLOGY_MEMORY_SCRIPT ?= $(CURDIR)/analysis/scripts/agent/104_n3_topology_memory_experiment.py
N3_TOPOLOGY_MEMORY_BLOCKS := n2_control phase_a_baseline phase_a_actions phase_b_baseline phase_b_actions
N3_TOPOLOGY_MEMORY_N2_RUN_ID := n3-topology-memory-v1-n2-control
N3_TOPOLOGY_MEMORY_A_BASELINE_RUN_ID := n3-topology-memory-v1-phase-a-baseline
N3_TOPOLOGY_MEMORY_A_ACTIONS_RUN_ID := n3-topology-memory-v1-phase-a-actions
N3_TOPOLOGY_MEMORY_B_BASELINE_RUN_ID := n3-topology-memory-v1-phase-b-baseline
N3_TOPOLOGY_MEMORY_B_ACTIONS_RUN_ID := n3-topology-memory-v1-phase-b-actions
CONFIRMATORY_ACTION_CONTRACT ?= $(CURDIR)/configs/validation/confirmatory_action_replication_v1.yml
CONFIRMATORY_ACTION_SOURCE_DIR ?= $(CURDIR)/generated/corpus/confirmatory-action-replication-v1-source
CONFIRMATORY_ACTION_MANIFEST ?= $(CONFIRMATORY_ACTION_SOURCE_DIR)/corpus_manifest.yml
CONFIRMATORY_ACTION_OUT ?= $(CURDIR)/generated/corpus/confirmatory-action-replication-v1
CONFIRMATORY_ACTION_PLAN ?= $(CONFIRMATORY_ACTION_OUT)/corpus_execution_plan.yml
CONFIRMATORY_ACTION_LOGICAL_RUN_ID ?= confirmatory-action-replication-v1
CONFIRMATORY_ACTION_RUN_LABEL ?= confirmatory-action-replication-v1-attempt-01
CONFIRMATORY_ACTION_LOGICAL_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(CONFIRMATORY_ACTION_LOGICAL_RUN_ID)
CONFIRMATORY_ACTION_REPORT_OUT ?= $(CURDIR)/analysis/reports/confirmatory-action-replication-v1
CONFIRMATORY_ACTION_RELEASE_OUT ?= $(CURDIR)/releases/confirmatory-action-replication-v1
CONFIRMATORY_ACTION_SCRIPT ?= $(CURDIR)/analysis/scripts/agent/108_confirmatory_action_replication.py
PRESSURE_MITIGATION_CORRECTNESS_CONTRACT ?= $(CURDIR)/configs/validation/mitigation_correctness_recovery_v1.yml
PRESSURE_MITIGATION_CORRECTNESS_OUT ?= $(CURDIR)/analysis/reports/pressure-raw-v1-correctness-recovery
PRESSURE_COLOCATION_GAIN_CONTRACT ?= $(CURDIR)/configs/models/colocation_gain_v1.yml
PRESSURE_COLOCATION_GAIN_OUT ?= $(CURDIR)/analysis/reports/pressure-raw-v1-colocation-gain-model
PRESSURE_COLOCATION_RANKING_CONTRACT ?= $(CURDIR)/configs/models/colocation_ranking_v1.yml
PRESSURE_COLOCATION_RANKING_OUT ?= $(CURDIR)/analysis/reports/pressure-raw-v1-colocation-ranking-robustness
PRESSURE_COLOCATION_ELIGIBILITY_CONTRACT ?= $(CURDIR)/configs/models/colocation_eligibility_v1.yml
PRESSURE_COLOCATION_ELIGIBILITY_OUT ?= $(CURDIR)/analysis/reports/pressure-raw-v1-colocation-eligibility
PRESSURE_N3_HOLDOUT_MANIFEST ?= $(CURDIR)/workloads/corpus/pressure-raw-v1/batch-300-n3-colocation-holdout.yml
PRESSURE_N3_HOLDOUT_OUT ?= $(CURDIR)/generated/corpus/pressure-raw-v1-n3-colocation-holdout
PRESSURE_N3_HOLDOUT_PLAN ?= $(PRESSURE_N3_HOLDOUT_OUT)/corpus_execution_plan.yml
PRESSURE_N3_FREEZE_OUT ?= $(CURDIR)/generated/model-freezes/colocation-ranking-before-n3-v1
PRESSURE_N3_LOGICAL_RUN_ID ?= pressure-raw-v1-n3-colocation-holdout
PRESSURE_N3_RUN_LABEL ?= pressure-raw-v1-n3-colocation-holdout-attempt-01
PRESSURE_N3_LOGICAL_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(PRESSURE_N3_LOGICAL_RUN_ID)
PRESSURE_N3_REPORT_OUT ?= $(CURDIR)/analysis/reports/pressure-raw-v1-n3-colocation-no-refit
PRESSURE_MITIGATION_DECISION_OUT ?= $(CURDIR)/analysis/reports/pressure-raw-v1-mitigation-modeling-decision
PRESSURE_PROFILE_SCORER_CONTRACT ?= $(CURDIR)/configs/models/pressure_profile_scorers_v1.yml
PRESSURE_PROFILE_SCORER_OUT ?= $(CURDIR)/analysis/reports/pressure-raw-v1-pressure-profile-scorers
PRESSURE_PREFLIGHT_SOURCES ?= $(CURDIR)/configs/collection/pressure_probe_preflight_sources.yml
PRESSURE_PREFLIGHT_OUT ?= $(CURDIR)/analysis/reports/pressure-collection-uniformity-preflight-v1
REMOTE_EDGE_PROBE_MANIFEST ?= workloads/corpus/corpus_manifest.remote-edge-collection-probe-v1.yml
REMOTE_EDGE_PROBE_OUT ?= generated/corpus/remote-edge-collection-probe-v1
REMOTE_EDGE_PROBE_PLAN ?= ../master-regimes/$(REMOTE_EDGE_PROBE_OUT)/corpus_execution_plan.yml
REMOTE_EDGE_PROBE_LOGICAL_RUN_ID ?= remote-edge-collection-probe-v1b
REMOTE_EDGE_PROBE_LABEL ?= remote-edge-collection-probe-v1b-attempt-01
REMOTE_EDGE_PROBE_INDEX ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(REMOTE_EDGE_PROBE_LOGICAL_RUN_ID)/_index
REMOTE_EDGE_PROBE_REPORT ?= analysis/reports/remote-edge-collection-probe-v1
PRESSURE_PROGRAM_SEGMENT_ID ?=
PRESSURE_PROGRAM_MAX_SEGMENTS ?=
LOGICAL_RUN_ID ?= plan-c-bounded-pilot
LOGICAL_INDEX ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(LOGICAL_RUN_ID)/_index
FEATURES_OUT ?= analysis/features/$(LOGICAL_RUN_ID)
FEATURE_TOPOLOGY ?= multi_region
REPORT_OUT ?= analysis/reports/$(LOGICAL_RUN_ID)-logical
CORPUS_MANIFEST ?= workloads/corpus/corpus_manifest.plan-c-pilot.yml
CORPUS_COVERAGE ?= workloads/corpus/regime-coverage.yml
CORPUS_INCLUDE_EXECUTION_CLASS ?= pilot
CLEAN_RUN_MANIFEST ?= workloads/corpus/corpus_manifest.clean-run-v1.yml
CLEAN_RUN_OUT ?= generated/corpus/clean-run-v1
CLEAN_RUN_PLAN ?= $(if $(filter /%,$(CLEAN_RUN_OUT)),$(CLEAN_RUN_OUT),../master-regimes/$(CLEAN_RUN_OUT))/corpus_execution_plan.yml
CLEAN_RUN_LOGICAL_RUN_ID ?= clean-run-v1
CLEAN_RUN_DRY_RUN_LOGICAL_RUN_ID ?= $(CLEAN_RUN_LOGICAL_RUN_ID)-dry-run
CLEAN_RUN_LABEL ?= clean-run-v1-attempt-01
CLEAN_RUN_MAX_INSTANCES_PER_CELL ?=
CLEAN_RUN_MAX_INSTANCES_PER_GROUP ?=
CLEAN_RUN_GROUP_ID ?=
CLEAN_RUN_MAX_GROUPS ?=
CLEAN_RUN_RERUN_OF ?=
CLEAN_RUN_DRY_RUN ?= false
CLEAN_RUN_RERUN_LABEL ?= clean-run-v1-rerun-01
CLEAN_RUN_RERUN_PLAN_OUT ?=
CLEAN_RUN_RERUN_STATUSES ?= timeout,failed,missing,interrupted
CLEAN_RUN_RERUN_HARD_TIMEOUT_SECONDS ?= 1800
CLEAN_RUN_RERUN_TIMEOUT_GRACE_SECONDS ?= 30
CLEAN_RUN_PROBE_OUT ?= generated/corpus/clean-run-v1-probe
CLEAN_RUN_PROBE_LABEL ?= clean-run-v1-probe-attempt-01
CLEAN_RUN_PROBE_DRY_RUN_LABEL ?= clean-run-v1-probe-dry-run
CLEAN_RUN_PROBE_LOGICAL_RUN_ID ?= clean-run-v1-probe
CLEAN_RUN_PROBE_DRY_RUN_LOGICAL_RUN_ID ?= $(CLEAN_RUN_PROBE_LOGICAL_RUN_ID)-dry-run
CLEAN_RUN_PROBE_GROUP_ID ?= clean-run-eu-us-gac-v1__pilot-balanced-v1__default__coordinators
CLEAN_RUN_PROBE_MAX_INSTANCES_PER_CELL ?= 1
CLEAN_RUN_PROBE_MAX_INSTANCES_PER_GROUP ?= 1
WAN_RUN_MANIFEST ?= workloads/corpus/corpus_manifest.wan-latency-companion-v1.yml
WAN_RUN_OUT ?= generated/corpus/wan-latency-companion-v1
WAN_RUN_PLAN ?= $(if $(filter /%,$(WAN_RUN_OUT)),$(WAN_RUN_OUT),../master-regimes/$(WAN_RUN_OUT))/corpus_execution_plan.yml
WAN_RUN_LOGICAL_RUN_ID ?= clean-run-v1-wan-latency
WAN_RUN_DRY_RUN_LOGICAL_RUN_ID ?= $(WAN_RUN_LOGICAL_RUN_ID)-dry-run
WAN_RUN_LABEL ?= clean-run-v1-wan-latency-attempt-01
WAN_RUN_MAX_INSTANCES_PER_CELL ?=
WAN_RUN_MAX_INSTANCES_PER_GROUP ?=
WAN_RUN_GROUP_ID ?=
WAN_RUN_MAX_GROUPS ?=
WAN_RUN_DRY_RUN ?= false
WAN_RUN_PROBE_LABEL ?= clean-run-v1-wan-latency-probe-attempt-01
WAN_RUN_PROBE_LOGICAL_RUN_ID ?= clean-run-v1-wan-latency-probe
WAN_RUN_PROBE_GROUP_ID ?= clean-run-eu-us-gac-wan-latency-v1__pilot-balanced-v1__wan_100ms__analytics_clients
WAN_RUN_PROBE_MAX_INSTANCES_PER_CELL ?= 1
WAN_RUN_PROBE_MAX_INSTANCES_PER_GROUP ?= 1
REGION_IMBALANCE_RUN_MANIFEST ?= workloads/corpus/corpus_manifest.regional-imbalance-companion-v1.yml
REGION_IMBALANCE_RUN_OUT ?= generated/corpus/region-imbalance-companion-v1
REGION_IMBALANCE_RUN_PLAN ?= $(if $(filter /%,$(REGION_IMBALANCE_RUN_OUT)),$(REGION_IMBALANCE_RUN_OUT),../master-regimes/$(REGION_IMBALANCE_RUN_OUT))/corpus_execution_plan.yml
REGION_IMBALANCE_RUN_LOGICAL_RUN_ID ?= clean-run-v1-region-imbalance
REGION_IMBALANCE_RUN_LABEL ?= clean-run-v1-region-imbalance-attempt-01
REGION_IMBALANCE_RUN_MAX_INSTANCES_PER_CELL ?=
REGION_IMBALANCE_RUN_MAX_INSTANCES_PER_GROUP ?=
REGION_IMBALANCE_RUN_GROUP_ID ?=
REGION_IMBALANCE_RUN_MAX_GROUPS ?=
REGION_IMBALANCE_RUN_PROBE_LABEL ?= clean-run-v1-region-imbalance-probe-attempt-01
REGION_IMBALANCE_RUN_PROBE_LOGICAL_RUN_ID ?= clean-run-v1-region-imbalance-probe
REGION_IMBALANCE_RUN_PROBE_GROUP_ID ?= clean-run-eu-us-gac-region-imbalance-v1__pilot-region-imbalanced-v1__default__analytics_clients
REGION_IMBALANCE_RUN_PROBE_MAX_INSTANCES_PER_CELL ?= 1
REGION_IMBALANCE_RUN_PROBE_MAX_INSTANCES_PER_GROUP ?= 1
REGION_ASYMMETRY_RUN_MANIFEST ?= workloads/corpus/corpus_manifest.region-asymmetry-companion-v1.yml
REGION_ASYMMETRY_RUN_OUT ?= generated/corpus/region-asymmetry-companion-v1
REGION_ASYMMETRY_RUN_PLAN ?= $(if $(filter /%,$(REGION_ASYMMETRY_RUN_OUT)),$(REGION_ASYMMETRY_RUN_OUT),../master-regimes/$(REGION_ASYMMETRY_RUN_OUT))/corpus_execution_plan.yml
REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID ?= clean-run-v1-region-asymmetry
REGION_ASYMMETRY_RUN_DRY_RUN_LOGICAL_RUN_ID ?= $(REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID)-dry-run
REGION_ASYMMETRY_RUN_LABEL ?= clean-run-v1-region-asymmetry-attempt-01
REGION_ASYMMETRY_RUN_MAX_INSTANCES_PER_CELL ?=
REGION_ASYMMETRY_RUN_MAX_INSTANCES_PER_GROUP ?=
REGION_ASYMMETRY_RUN_GROUP_ID ?=
REGION_ASYMMETRY_RUN_MAX_GROUPS ?=
REGION_ASYMMETRY_RUN_DRY_RUN ?= false
REGION_ASYMMETRY_RUN_PROBE_LABEL ?= clean-run-v1-region-asymmetry-probe-attempt-01
REGION_ASYMMETRY_RUN_PROBE_LOGICAL_RUN_ID ?= clean-run-v1-region-asymmetry-probe
REGION_ASYMMETRY_RUN_PROBE_GROUP_ID ?= clean-run-eu-us-gac-region-asymmetry-v1__pilot-region-local-skew-asymmetric-medium-v1__default__analytics_clients
REGION_ASYMMETRY_RUN_PROBE_MAX_INSTANCES_PER_CELL ?= 1
REGION_ASYMMETRY_RUN_PROBE_MAX_INSTANCES_PER_GROUP ?= 2
VALIDATION_HOLDOUT_MANIFEST ?= workloads/corpus/corpus_manifest.validation-holdout-v1.yml
VALIDATION_HOLDOUT_OUT ?= generated/corpus/validation-holdout-v1
VALIDATION_HOLDOUT_PLAN ?= $(if $(filter /%,$(VALIDATION_HOLDOUT_OUT)),$(VALIDATION_HOLDOUT_OUT),../master-regimes/$(VALIDATION_HOLDOUT_OUT))/corpus_execution_plan.yml
VALIDATION_HOLDOUT_LOGICAL_RUN_ID ?= clean-run-v1-validation-holdout
VALIDATION_HOLDOUT_DRY_RUN_LOGICAL_RUN_ID ?= $(VALIDATION_HOLDOUT_LOGICAL_RUN_ID)-dry-run
VALIDATION_HOLDOUT_LABEL ?= clean-run-v1-validation-holdout-attempt-01
VALIDATION_HOLDOUT_MAX_INSTANCES_PER_CELL ?=
VALIDATION_HOLDOUT_MAX_INSTANCES_PER_GROUP ?=
VALIDATION_HOLDOUT_GROUP_ID ?=
VALIDATION_HOLDOUT_MAX_GROUPS ?=
VALIDATION_HOLDOUT_DRY_RUN ?= false
VALIDATION_HOLDOUT_PROBE_LABEL ?= clean-run-v1-validation-holdout-probe-attempt-01
VALIDATION_HOLDOUT_PROBE_LOGICAL_RUN_ID ?= clean-run-v1-validation-holdout-probe
VALIDATION_HOLDOUT_PROBE_GROUP_ID ?= clean-run-eu-us-gac-validation-holdout-v1__pilot-region-local-skew-asymmetric-medium-v1__wan_100ms__analytics_clients
VALIDATION_HOLDOUT_PROBE_MAX_INSTANCES_PER_CELL ?= 1
VALIDATION_HOLDOUT_PROBE_MAX_INSTANCES_PER_GROUP ?= 2
REPEATABILITY_PLAN ?= $(CURDIR)/generated/corpus/repeatability-v1/corpus_execution_plan.yml
REPEATABILITY_SMOKE_PLAN ?= $(CURDIR)/generated/corpus/repeatability-v1-smoke/corpus_execution_plan.yml
REPEATABILITY_LOGICAL_RUN_ID ?= repeatability-v1
REPEATABILITY_DRY_RUN_LOGICAL_RUN_ID ?= repeatability-v1-dry-run
REPEATABILITY_LABEL ?= repeatability-v1-attempt-01
REPEATABILITY_SMOKE_LOGICAL_RUN_ID ?= repeatability-v1-smoke
REPEATABILITY_SMOKE_DRY_RUN_LOGICAL_RUN_ID ?= repeatability-v1-smoke-dry-run
REPEATABILITY_SMOKE_LABEL ?= repeatability-v1-smoke-attempt-01
REPEATABILITY_LOGICAL_ROOT ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs
REPEATABILITY_INDEX_DIR ?= $(REPEATABILITY_LOGICAL_ROOT)/$(REPEATABILITY_LOGICAL_RUN_ID)/_index
REPEATABILITY_FEATURE_DIR ?= $(CURDIR)/analysis/features/$(REPEATABILITY_LOGICAL_RUN_ID)
REPEATABILITY_REPORT_DIR ?= $(CURDIR)/analysis/reports/$(REPEATABILITY_LOGICAL_RUN_ID)
REPEATABILITY_SELECTION ?= $(CURDIR)/workloads/corpus/repeatability_selection.csv
REPEATABILITY_RERUN_LABEL ?= repeatability-v1-rerun
REPEATABILITY_RERUN_STATUSES ?= timeout,failed,missing,interrupted
REPEATABILITY_RERUN_PLAN_OUT ?=
REPEATABILITY_RERUN_HARD_TIMEOUT_SECONDS ?=
REPEATABILITY_RERUN_TIMEOUT_GRACE_SECONDS ?= 30
CONFIRMATORY_SKEW_CONFIG ?= configs/validation/confirmatory_skew_v1.yml
CONFIRMATORY_SKEW_PLAN ?= $(CURDIR)/generated/corpus/confirmatory-skew-v1/corpus_execution_plan.yml
CONFIRMATORY_SKEW_SELECTION ?= $(CURDIR)/workloads/corpus/confirmatory_skew_v1_selection.csv
CONFIRMATORY_SKEW_REPORT_DIR ?= $(CURDIR)/analysis/reports/confirmatory-skew-v1-local-readiness
CONFIRMATORY_SKEW_CHECKPOINT ?= $(CURDIR)/llmcontext/plans/checkpoints/confirmatory-skew-v1-local-readiness.yml
CONFIRMATORY_SKEW_CAPABILITY_RUN_DIR ?=
CONFIRMATORY_SKEW_CAPABILITY_REPORT_DIR ?= $(CURDIR)/analysis/reports/confirmatory-skew-v1-capability-smoke
CONFIRMATORY_SKEW_CAPABILITY_CHECKPOINT ?= $(CURDIR)/llmcontext/plans/checkpoints/confirmatory-skew-v1-capability-smoke.yml
CONFIRMATORY_SKEW_EXECUTION_RUN_DIR ?=
CONFIRMATORY_SKEW_EXECUTION_REPORT_DIR ?= $(CURDIR)/analysis/reports/confirmatory-skew-v1-execution
CONFIRMATORY_SKEW_EXECUTION_CHECKPOINT ?= $(CURDIR)/llmcontext/plans/checkpoints/confirmatory-skew-v1-execution.yml
CONFIRMATORY_SKEW_ANALYSIS_FEATURE_DIR ?= $(CURDIR)/analysis/features/confirmatory-skew-v1
CONFIRMATORY_SKEW_ANALYSIS_REPORT_DIR ?= $(CURDIR)/analysis/reports/confirmatory-skew-v1-analysis
CONFIRMATORY_SKEW_ANALYSIS_CHECKPOINT ?= $(CURDIR)/llmcontext/plans/checkpoints/confirmatory-skew-v1-analysis.yml
STATS_CEB_SOURCE_LOCK ?= $(CURDIR)/external/stats-ceb/source-lock.yml
STATS_CEB_SELECTION ?= $(CURDIR)/external/stats-ceb/query-selection.yml
STATS_CEB_CACHE ?= $(CURDIR)/tmp/stats-ceb
STATS_CEB_REPORT_DIR ?= $(CURDIR)/analysis/reports/stats-ceb-portability-gate
STATS_CEB_MANIFEST ?= $(CURDIR)/workloads/corpus/corpus_manifest.stats-ceb-portability-v1.yml
STATS_CEB_OUT ?= $(CURDIR)/generated/corpus/stats-ceb-portability-v1
STATS_CEB_PLAN ?= $(STATS_CEB_OUT)/corpus_execution_plan.yml
STATS_CEB_LOGICAL_RUN_ID ?= stats-ceb-portability-v1
STATS_CEB_DRY_RUN_LOGICAL_RUN_ID ?= $(STATS_CEB_LOGICAL_RUN_ID)-dry-run
STATS_CEB_LABEL ?= stats-ceb-portability-v1-attempt-01
STATS_CEB_LOGICAL_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(STATS_CEB_LOGICAL_RUN_ID)
STATS_CEB_FEATURE_DIR ?= $(CURDIR)/analysis/features/$(STATS_CEB_LOGICAL_RUN_ID)
STATS_CEB_ANALYSIS_DIR ?= $(CURDIR)/analysis/reports/$(STATS_CEB_LOGICAL_RUN_ID)
STATS_CEB_REPRESENTATION_AUDIT_DIR ?= $(CURDIR)/analysis/reports/stats-ceb-representation-audit-v1
STATS_CEB_V2_SELECTION ?= $(CURDIR)/external/stats-ceb/query-selection.semantic-v2-holdout.yml
STATS_CEB_V2_REPORT_DIR ?= $(CURDIR)/analysis/reports/stats-ceb-semantic-v2-holdout-gate
STATS_CEB_V2_MANIFEST ?= $(CURDIR)/workloads/corpus/corpus_manifest.stats-ceb-semantic-v2-holdout.yml
STATS_CEB_V2_OUT ?= $(CURDIR)/generated/corpus/stats-ceb-semantic-v2-holdout
STATS_CEB_V2_PLAN ?= $(STATS_CEB_V2_OUT)/corpus_execution_plan.yml
STATS_CEB_V2_LOGICAL_RUN_ID ?= stats-ceb-semantic-v2-holdout
STATS_CEB_V2_DRY_RUN_LOGICAL_RUN_ID ?= $(STATS_CEB_V2_LOGICAL_RUN_ID)-dry-run
STATS_CEB_V2_LABEL ?= stats-ceb-semantic-v2-holdout-attempt-01
STATS_CEB_V2_LOGICAL_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(STATS_CEB_V2_LOGICAL_RUN_ID)
STATS_CEB_V2_FEATURE_DIR ?= $(CURDIR)/analysis/features/$(STATS_CEB_V2_LOGICAL_RUN_ID)
STATS_CEB_V2_ANALYSIS_DIR ?= $(CURDIR)/analysis/reports/$(STATS_CEB_V2_LOGICAL_RUN_ID)
STATS_CEB_V2B_SELECTION ?= $(CURDIR)/external/stats-ceb/query-selection.semantic-v2b-holdout.yml
STATS_CEB_V2B_REPORT_DIR ?= $(CURDIR)/analysis/reports/stats-ceb-semantic-v2b-holdout-gate
STATS_CEB_V2B_MANIFEST ?= $(CURDIR)/workloads/corpus/corpus_manifest.stats-ceb-semantic-v2b-holdout.yml
STATS_CEB_V2B_OUT ?= $(CURDIR)/generated/corpus/stats-ceb-semantic-v2b-holdout
STATS_CEB_V2B_PLAN ?= $(STATS_CEB_V2B_OUT)/corpus_execution_plan.yml
STATS_CEB_V2B_LOGICAL_RUN_ID ?= stats-ceb-semantic-v2b-holdout
STATS_CEB_V2B_DRY_RUN_LOGICAL_RUN_ID ?= $(STATS_CEB_V2B_LOGICAL_RUN_ID)-dry-run
STATS_CEB_V2B_LABEL ?= stats-ceb-semantic-v2b-holdout-attempt-01
STATS_CEB_V2B_LOGICAL_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(STATS_CEB_V2B_LOGICAL_RUN_ID)
STATS_CEB_V2B_FEATURE_DIR ?= $(CURDIR)/analysis/features/$(STATS_CEB_V2B_LOGICAL_RUN_ID)
STATS_CEB_V2B_ANALYSIS_DIR ?= $(CURDIR)/analysis/reports/$(STATS_CEB_V2B_LOGICAL_RUN_ID)
STATS_CEB_FULL_SELECTION ?= $(CURDIR)/external/stats-ceb/query-selection.full-no-refit-v1.yml
STATS_CEB_FULL_REPORT_DIR ?= $(CURDIR)/analysis/reports/stats-ceb-full-no-refit-v1-gate
STATS_CEB_FULL_MANIFEST ?= $(CURDIR)/workloads/corpus/corpus_manifest.stats-ceb-full-no-refit-v1.yml
STATS_CEB_FULL_OUT ?= $(CURDIR)/generated/corpus/stats-ceb-full-no-refit-v1
STATS_CEB_FULL_PLAN ?= $(STATS_CEB_FULL_OUT)/corpus_execution_plan.yml
STATS_CEB_FULL_LOGICAL_RUN_ID ?= stats-ceb-full-no-refit-v1
STATS_CEB_FULL_DRY_RUN_LOGICAL_RUN_ID ?= $(STATS_CEB_FULL_LOGICAL_RUN_ID)-dry-run
STATS_CEB_FULL_LABEL ?= stats-ceb-full-no-refit-v1-attempt-01
STATS_CEB_FULL_LOGICAL_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(STATS_CEB_FULL_LOGICAL_RUN_ID)
STATS_CEB_FULL_FEATURE_DIR ?= $(CURDIR)/analysis/features/$(STATS_CEB_FULL_LOGICAL_RUN_ID)
STATS_CEB_FULL_ANALYSIS_DIR ?= $(CURDIR)/analysis/reports/$(STATS_CEB_FULL_LOGICAL_RUN_ID)
STATS_CEB_FUZZIFIER_AUDIT_DIR ?= $(CURDIR)/analysis/reports/semantic-v2-fuzzifier-sensitivity
STATS_CEB_FULL_EXTERNAL_WEIGHTED ?= $(STATS_CEB_FULL_ANALYSIS_DIR)/full_workload_semantic_weighted.csv
STATS_CEB_RECOVERY_SELECTION ?= $(CURDIR)/external/stats-ceb/query-selection.full-recovery-1800s-v1.yml
STATS_CEB_RECOVERY_REPORT_DIR ?= $(CURDIR)/analysis/reports/stats-ceb-full-recovery-1800s-v1-gate
STATS_CEB_RECOVERY_MANIFEST ?= $(CURDIR)/workloads/corpus/corpus_manifest.stats-ceb-full-recovery-1800s-v1.yml
STATS_CEB_RECOVERY_OUT ?= $(CURDIR)/generated/corpus/stats-ceb-full-recovery-1800s-v1
STATS_CEB_RECOVERY_PLAN ?= $(STATS_CEB_RECOVERY_OUT)/corpus_execution_plan.yml
STATS_CEB_RECOVERY_LOGICAL_RUN_ID ?= stats-ceb-full-recovery-1800s-v1
STATS_CEB_RECOVERY_DRY_RUN_LOGICAL_RUN_ID ?= $(STATS_CEB_RECOVERY_LOGICAL_RUN_ID)-dry-run
STATS_CEB_RECOVERY_LABEL ?= stats-ceb-full-recovery-1800s-v1-attempt-01
STATS_CEB_RECOVERY_LOGICAL_DIR ?= $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs/$(STATS_CEB_RECOVERY_LOGICAL_RUN_ID)
STATS_CEB_RECOVERY_FEATURE_DIR ?= $(CURDIR)/analysis/features/$(STATS_CEB_RECOVERY_LOGICAL_RUN_ID)
STATS_CEB_RECOVERY_ANALYSIS_DIR ?= $(CURDIR)/analysis/reports/$(STATS_CEB_RECOVERY_LOGICAL_RUN_ID)
STATS_CEB_RECOVERY_SUMMARY_DIR ?= $(CURDIR)/analysis/reports/$(STATS_CEB_RECOVERY_LOGICAL_RUN_ID)-summary

doctor:
	uv run master-regimes doctor

init-smoke:
	uv run master-regimes init-run \
		--system configs/systems/eu-us-gac.example.yml \
		--dataset datasets/profiles/smoke.yml \
		--sweep configs/sweeps/smoke.yml

render-smoke:
	uv run master-regimes render-workload \
		--registry workloads/registry.yml \
		--out runs/smoke-rendered

stats-ceb-local-gate:
	uv run master-regimes stats-ceb-admission \
		--source-lock $(STATS_CEB_SOURCE_LOCK) \
		--selection $(STATS_CEB_SELECTION) \
		--cache $(STATS_CEB_CACHE) \
		--out $(STATS_CEB_REPORT_DIR)

stats-ceb-validate: stats-ceb-local-gate
	uv run master-regimes validate-corpus --manifest $(STATS_CEB_MANIFEST)

stats-ceb-render: stats-ceb-validate
	uv run master-regimes render-corpus \
		--manifest $(STATS_CEB_MANIFEST) \
		--out $(STATS_CEB_OUT) \
		--include-execution-class pilot

stats-ceb-infra-dry-run: stats-ceb-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(STATS_CEB_PLAN) \
		CORPUS_RUN_LABEL=$(STATS_CEB_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_DRY_RUN_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=true

stats-ceb-start: stats-ceb-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(STATS_CEB_PLAN) \
		CORPUS_RUN_LABEL=$(STATS_CEB_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_LOGICAL_RUN_ID)

stats-ceb-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_LOGICAL_RUN_ID)

stats-ceb-feature-matrix: stats-ceb-index
	uv run master-regimes build-feature-matrix \
		--index-dir $(STATS_CEB_LOGICAL_DIR)/_index \
		--out $(STATS_CEB_FEATURE_DIR) \
		--topology multi_region

stats-ceb-analyze: stats-ceb-feature-matrix
	uv run python analysis/scripts/agent/58_stats_ceb_portability_pilot.py \
		--logical-root $(MASTER_REGIMES_INFRA_DIR)/generated/runs/corpus-sweeps/_logical-runs \
		--logical-run-id $(STATS_CEB_LOGICAL_RUN_ID) \
		--feature-dir $(STATS_CEB_FEATURE_DIR) \
		--selection $(STATS_CEB_SELECTION) \
		--out-dir $(STATS_CEB_ANALYSIS_DIR)

stats-ceb-representation-audit:
	uv run python analysis/scripts/agent/60_representation_geometry_audit.py \
		--out-dir $(STATS_CEB_REPRESENTATION_AUDIT_DIR)

semantic-v2-feature-audit:
	uv run python analysis/scripts/agent/61_feature_semantic_contract_audit.py

semantic-v2-model-freeze: semantic-v2-feature-audit
	uv run python analysis/scripts/agent/62_freeze_semantic_v2_model.py

semantic-v2-final-consistency:
	uv run python analysis/scripts/agent/64_semantic_v2_final_consistency.py

semantic-v2-thesis-claims:
	uv run python analysis/scripts/agent/65_semantic_v2_thesis_claim_audit.py

semantic-v2-thesis-results: semantic-v2-thesis-claims
	uv run python analysis/scripts/agent/66_semantic_v2_thesis_results_package.py

semantic-v2-thesis-defense:
	uv run python analysis/scripts/agent/67_semantic_v2_appendix_defense_audit.py

semantic-v2-release-audit:
	uv run python analysis/scripts/agent/68_semantic_v2_final_release_audit.py \
		--manual-visual-review-confirmed

stats-ceb-v2-prepare-selection: semantic-v2-model-freeze
	uv run master-regimes stats-ceb-prepare-holdout \
		--source-lock $(STATS_CEB_SOURCE_LOCK) \
		--development-selection $(STATS_CEB_SELECTION) \
		--cache $(STATS_CEB_CACHE) \
		--selection $(STATS_CEB_V2_SELECTION) \
		--selected-query-dir $(CURDIR)/external/stats-ceb/selected-queries \
		--fragments-dir $(CURDIR)/workloads/templates/stats-ceb/fragments \
		--seed stats-ceb-semantic-v2-holdout \
		--table-count-quotas 2:2,3:3,4:3,5:2,6:2

stats-ceb-v2-local-gate: stats-ceb-v2-prepare-selection
	uv run master-regimes stats-ceb-admission \
		--source-lock $(STATS_CEB_SOURCE_LOCK) \
		--selection $(STATS_CEB_V2_SELECTION) \
		--cache $(STATS_CEB_CACHE) \
		--out $(STATS_CEB_V2_REPORT_DIR)

stats-ceb-v2-validate: stats-ceb-v2-local-gate
	uv run master-regimes validate-corpus --manifest $(STATS_CEB_V2_MANIFEST)

stats-ceb-v2-render: stats-ceb-v2-validate
	uv run master-regimes render-corpus \
		--manifest $(STATS_CEB_V2_MANIFEST) \
		--out $(STATS_CEB_V2_OUT) \
		--include-execution-class pilot

stats-ceb-v2-infra-dry-run: stats-ceb-v2-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(STATS_CEB_V2_PLAN) \
		CORPUS_RUN_LABEL=$(STATS_CEB_V2_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_V2_DRY_RUN_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=true

stats-ceb-v2-start: stats-ceb-v2-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(STATS_CEB_V2_PLAN) \
		CORPUS_RUN_LABEL=$(STATS_CEB_V2_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_V2_LOGICAL_RUN_ID)

stats-ceb-v2-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_V2_LOGICAL_RUN_ID)

stats-ceb-v2-feature-matrix: stats-ceb-v2-index
	uv run master-regimes build-feature-matrix \
		--index-dir $(STATS_CEB_V2_LOGICAL_DIR)/_index \
		--out $(STATS_CEB_V2_FEATURE_DIR) \
		--topology multi_region

stats-ceb-v2-analyze: stats-ceb-v2-feature-matrix
	uv run python analysis/scripts/agent/63_semantic_v2_holdout_analysis.py \
		--logical-index $(STATS_CEB_V2_LOGICAL_DIR)/_index \
		--feature-dir $(STATS_CEB_V2_FEATURE_DIR) \
		--selection $(STATS_CEB_V2_SELECTION) \
		--out-dir $(STATS_CEB_V2_ANALYSIS_DIR)

stats-ceb-v2b-prepare-selection: semantic-v2-model-freeze
	uv run master-regimes stats-ceb-prepare-holdout \
		--source-lock $(STATS_CEB_SOURCE_LOCK) \
		--development-selection $(STATS_CEB_SELECTION) \
		--exclude-selection $(STATS_CEB_V2_SELECTION) \
		--cache $(STATS_CEB_CACHE) \
		--selection $(STATS_CEB_V2B_SELECTION) \
		--selected-query-dir $(CURDIR)/external/stats-ceb/selected-queries \
		--fragments-dir $(CURDIR)/workloads/templates/stats-ceb/fragments \
		--seed stats-ceb-semantic-v2b-holdout \
		--selection-id stats-ceb-semantic-v2b-holdout \
		--table-count-quotas 2:1,3:3,4:4,5:2,6:2

stats-ceb-v2b-local-gate: stats-ceb-v2b-prepare-selection
	uv run master-regimes stats-ceb-admission \
		--source-lock $(STATS_CEB_SOURCE_LOCK) \
		--selection $(STATS_CEB_V2B_SELECTION) \
		--cache $(STATS_CEB_CACHE) \
		--out $(STATS_CEB_V2B_REPORT_DIR)

stats-ceb-v2b-validate: stats-ceb-v2b-local-gate
	uv run master-regimes validate-corpus --manifest $(STATS_CEB_V2B_MANIFEST)

stats-ceb-v2b-render: stats-ceb-v2b-validate
	uv run master-regimes render-corpus \
		--manifest $(STATS_CEB_V2B_MANIFEST) \
		--out $(STATS_CEB_V2B_OUT) \
		--include-execution-class pilot

stats-ceb-v2b-infra-dry-run: stats-ceb-v2b-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(STATS_CEB_V2B_PLAN) \
		CORPUS_RUN_LABEL=$(STATS_CEB_V2B_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_V2B_DRY_RUN_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=true

stats-ceb-v2b-start: stats-ceb-v2b-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(STATS_CEB_V2B_PLAN) \
		CORPUS_RUN_LABEL=$(STATS_CEB_V2B_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_V2B_LOGICAL_RUN_ID)

stats-ceb-v2b-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_V2B_LOGICAL_RUN_ID)

stats-ceb-v2b-feature-matrix: stats-ceb-v2b-index
	uv run master-regimes build-feature-matrix \
		--index-dir $(STATS_CEB_V2B_LOGICAL_DIR)/_index \
		--out $(STATS_CEB_V2B_FEATURE_DIR) \
		--topology multi_region

stats-ceb-v2b-analyze: stats-ceb-v2b-feature-matrix
	uv run python analysis/scripts/agent/63_semantic_v2_holdout_analysis.py \
		--logical-index $(STATS_CEB_V2B_LOGICAL_DIR)/_index \
		--feature-dir $(STATS_CEB_V2B_FEATURE_DIR) \
		--selection $(STATS_CEB_V2B_SELECTION) \
		--out-dir $(STATS_CEB_V2B_ANALYSIS_DIR)

stats-ceb-full-prepare-selection:
	uv run master-regimes stats-ceb-prepare-full \
		--source-lock $(STATS_CEB_SOURCE_LOCK) \
		--development-selection $(STATS_CEB_SELECTION) \
		--cache $(STATS_CEB_CACHE) \
		--selection $(STATS_CEB_FULL_SELECTION) \
		--selected-query-dir $(CURDIR)/external/stats-ceb/selected-queries \
		--fragments-dir $(CURDIR)/workloads/templates/stats-ceb/fragments \
		--selection-id $(STATS_CEB_FULL_LOGICAL_RUN_ID)

stats-ceb-full-local-gate: stats-ceb-full-prepare-selection
	uv run master-regimes stats-ceb-admission \
		--source-lock $(STATS_CEB_SOURCE_LOCK) \
		--selection $(STATS_CEB_FULL_SELECTION) \
		--cache $(STATS_CEB_CACHE) \
		--out $(STATS_CEB_FULL_REPORT_DIR)

stats-ceb-full-validate: stats-ceb-full-local-gate
	uv run master-regimes validate-corpus --manifest $(STATS_CEB_FULL_MANIFEST)

stats-ceb-full-render: stats-ceb-full-validate
	uv run master-regimes render-corpus \
		--manifest $(STATS_CEB_FULL_MANIFEST) \
		--out $(STATS_CEB_FULL_OUT) \
		--include-execution-class pilot

stats-ceb-full-infra-dry-run: stats-ceb-full-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(STATS_CEB_FULL_PLAN) \
		CORPUS_RUN_LABEL=$(STATS_CEB_FULL_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_FULL_DRY_RUN_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=true

stats-ceb-full-start: stats-ceb-full-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(STATS_CEB_FULL_PLAN) \
		CORPUS_RUN_LABEL=$(STATS_CEB_FULL_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_FULL_LOGICAL_RUN_ID)

stats-ceb-full-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_FULL_LOGICAL_RUN_ID)

stats-ceb-full-feature-matrix: stats-ceb-full-index
	uv run master-regimes build-feature-matrix \
		--index-dir $(STATS_CEB_FULL_LOGICAL_DIR)/_index \
		--out $(STATS_CEB_FULL_FEATURE_DIR) \
		--topology multi_region

stats-ceb-full-analyze: stats-ceb-full-feature-matrix
	uv run python analysis/scripts/agent/63_semantic_v2_holdout_analysis.py \
		--logical-index $(STATS_CEB_FULL_LOGICAL_DIR)/_index \
		--feature-dir $(STATS_CEB_FULL_FEATURE_DIR) \
		--selection $(STATS_CEB_FULL_SELECTION) \
		--out-dir $(STATS_CEB_FULL_ANALYSIS_DIR) \
		--logical-run-id $(STATS_CEB_FULL_LOGICAL_RUN_ID) \
		--artifact-prefix full_workload \
		--report-title "STATS-CEB semantic-v2 full no-refit audit" \
		--scope-statement "fiksnoj EU+US+GAC topologiji"

stats-ceb-fuzzifier-sensitivity:
	uv run python analysis/scripts/agent/69_fuzzifier_sensitivity_audit.py \
		--fuzzifiers 1.5,1.7,2.0 \
		--out-dir $(STATS_CEB_FUZZIFIER_AUDIT_DIR) \
		$(if $(wildcard $(STATS_CEB_FULL_EXTERNAL_WEIGHTED)),--external-weighted $(STATS_CEB_FULL_EXTERNAL_WEIGHTED),)

stats-ceb-full-run:
	$(MAKE) stats-ceb-full-start
	$(MAKE) stats-ceb-full-analyze
	$(MAKE) stats-ceb-fuzzifier-sensitivity

stats-ceb-recovery-contract-audit:
	uv run python analysis/scripts/agent/70_stats_ceb_extended_recovery.py \
		--selection $(STATS_CEB_RECOVERY_SELECTION) \
		--source-selection $(STATS_CEB_FULL_SELECTION) \
		--manifest $(STATS_CEB_RECOVERY_MANIFEST) \
		--primary-logical-dir $(STATS_CEB_FULL_LOGICAL_DIR) \
		--primary-analysis-dir $(STATS_CEB_FULL_ANALYSIS_DIR) \
		--out-dir $(STATS_CEB_RECOVERY_SUMMARY_DIR) \
		--preflight-only

stats-ceb-recovery-local-gate: stats-ceb-recovery-contract-audit
	uv run master-regimes stats-ceb-admission \
		--source-lock $(STATS_CEB_SOURCE_LOCK) \
		--selection $(STATS_CEB_RECOVERY_SELECTION) \
		--cache $(STATS_CEB_CACHE) \
		--out $(STATS_CEB_RECOVERY_REPORT_DIR)

stats-ceb-recovery-validate: stats-ceb-recovery-local-gate
	uv run master-regimes validate-corpus --manifest $(STATS_CEB_RECOVERY_MANIFEST)

stats-ceb-recovery-render: stats-ceb-recovery-validate
	uv run master-regimes render-corpus \
		--manifest $(STATS_CEB_RECOVERY_MANIFEST) \
		--out $(STATS_CEB_RECOVERY_OUT) \
		--include-execution-class pilot

stats-ceb-recovery-infra-dry-run: stats-ceb-recovery-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(STATS_CEB_RECOVERY_PLAN) \
		CORPUS_RUN_LABEL=$(STATS_CEB_RECOVERY_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_RECOVERY_DRY_RUN_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=true

stats-ceb-recovery-start: stats-ceb-recovery-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(STATS_CEB_RECOVERY_PLAN) \
		CORPUS_RUN_LABEL=$(STATS_CEB_RECOVERY_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_RECOVERY_LOGICAL_RUN_ID)

stats-ceb-recovery-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(STATS_CEB_RECOVERY_LOGICAL_RUN_ID)

stats-ceb-recovery-feature-matrix: stats-ceb-recovery-index
	uv run master-regimes build-feature-matrix \
		--index-dir $(STATS_CEB_RECOVERY_LOGICAL_DIR)/_index \
		--out $(STATS_CEB_RECOVERY_FEATURE_DIR) \
		--topology multi_region

stats-ceb-recovery-analyze: stats-ceb-recovery-feature-matrix
	uv run python analysis/scripts/agent/63_semantic_v2_holdout_analysis.py \
		--logical-index $(STATS_CEB_RECOVERY_LOGICAL_DIR)/_index \
		--feature-dir $(STATS_CEB_RECOVERY_FEATURE_DIR) \
		--selection $(STATS_CEB_RECOVERY_SELECTION) \
		--out-dir $(STATS_CEB_RECOVERY_ANALYSIS_DIR) \
		--logical-run-id $(STATS_CEB_RECOVERY_LOGICAL_RUN_ID) \
		--artifact-prefix recovery \
		--report-title "STATS-CEB extended-budget recovery" \
		--scope-statement "fiksnoj EU+US+GAC topologiji"
	uv run python analysis/scripts/agent/70_stats_ceb_extended_recovery.py \
		--selection $(STATS_CEB_RECOVERY_SELECTION) \
		--source-selection $(STATS_CEB_FULL_SELECTION) \
		--manifest $(STATS_CEB_RECOVERY_MANIFEST) \
		--primary-logical-dir $(STATS_CEB_FULL_LOGICAL_DIR) \
		--recovery-logical-dir $(STATS_CEB_RECOVERY_LOGICAL_DIR) \
		--primary-analysis-dir $(STATS_CEB_FULL_ANALYSIS_DIR) \
		--recovery-analysis-dir $(STATS_CEB_RECOVERY_ANALYSIS_DIR) \
		--out-dir $(STATS_CEB_RECOVERY_SUMMARY_DIR)

stats-ceb-recovery-script:
	scripts/run_stats_ceb_extended_recovery.sh

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest

lint:
	uv run ruff check .

thesis-lint:
	uv run ruff check $(THESIS_RUFF_SCOPE)

check-thesis: test thesis-lint thesis-local-reproduction thesis-finalization-audit

clean-run-validate:
	uv run master-regimes validate-corpus --manifest $(CLEAN_RUN_MANIFEST)

clean-run-render: clean-run-validate
	uv run master-regimes render-corpus \
		--manifest $(CLEAN_RUN_MANIFEST) \
		--out $(CLEAN_RUN_OUT) \
		$(if $(CLEAN_RUN_MAX_INSTANCES_PER_CELL),--max-instances-per-cell $(CLEAN_RUN_MAX_INSTANCES_PER_CELL),)

clean-run-dry-run: clean-run-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(CLEAN_RUN_PLAN) \
		CORPUS_RUN_LABEL=$(CLEAN_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(CLEAN_RUN_DRY_RUN_LOGICAL_RUN_ID) \
		$(if $(CLEAN_RUN_GROUP_ID),CORPUS_RUN_GROUP_ID=$(CLEAN_RUN_GROUP_ID),) \
		$(if $(CLEAN_RUN_MAX_GROUPS),CORPUS_RUN_MAX_GROUPS=$(CLEAN_RUN_MAX_GROUPS),) \
		$(if $(CLEAN_RUN_MAX_INSTANCES_PER_GROUP),CORPUS_RUN_MAX_INSTANCES_PER_GROUP=$(CLEAN_RUN_MAX_INSTANCES_PER_GROUP),) \
		$(if $(CLEAN_RUN_RERUN_OF),CORPUS_RERUN_OF=$(CLEAN_RUN_RERUN_OF),) \
		CORPUS_RUN_DRY_RUN=true

clean-run-start: clean-run-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(CLEAN_RUN_PLAN) \
		CORPUS_RUN_LABEL=$(CLEAN_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(CLEAN_RUN_LOGICAL_RUN_ID) \
		$(if $(CLEAN_RUN_GROUP_ID),CORPUS_RUN_GROUP_ID=$(CLEAN_RUN_GROUP_ID),) \
		$(if $(CLEAN_RUN_MAX_GROUPS),CORPUS_RUN_MAX_GROUPS=$(CLEAN_RUN_MAX_GROUPS),) \
		$(if $(CLEAN_RUN_MAX_INSTANCES_PER_GROUP),CORPUS_RUN_MAX_INSTANCES_PER_GROUP=$(CLEAN_RUN_MAX_INSTANCES_PER_GROUP),) \
		$(if $(CLEAN_RUN_RERUN_OF),CORPUS_RERUN_OF=$(CLEAN_RUN_RERUN_OF),) \
		CORPUS_RUN_DRY_RUN=$(CLEAN_RUN_DRY_RUN)

clean-run-probe-dry-run:
	$(MAKE) clean-run-dry-run \
		CLEAN_RUN_OUT=$(CLEAN_RUN_PROBE_OUT) \
		CLEAN_RUN_LABEL=$(CLEAN_RUN_PROBE_DRY_RUN_LABEL) \
		CLEAN_RUN_LOGICAL_RUN_ID=$(CLEAN_RUN_PROBE_LOGICAL_RUN_ID) \
		CLEAN_RUN_DRY_RUN_LOGICAL_RUN_ID=$(CLEAN_RUN_PROBE_DRY_RUN_LOGICAL_RUN_ID) \
		CLEAN_RUN_MAX_INSTANCES_PER_CELL=$(CLEAN_RUN_PROBE_MAX_INSTANCES_PER_CELL) \
		CLEAN_RUN_GROUP_ID=$(CLEAN_RUN_PROBE_GROUP_ID) \
		CLEAN_RUN_MAX_INSTANCES_PER_GROUP=$(CLEAN_RUN_PROBE_MAX_INSTANCES_PER_GROUP)

clean-run-probe-start:
	$(MAKE) clean-run-start \
		CLEAN_RUN_OUT=$(CLEAN_RUN_PROBE_OUT) \
		CLEAN_RUN_LABEL=$(CLEAN_RUN_PROBE_LABEL) \
		CLEAN_RUN_LOGICAL_RUN_ID=$(CLEAN_RUN_PROBE_LOGICAL_RUN_ID) \
		CLEAN_RUN_MAX_INSTANCES_PER_CELL=$(CLEAN_RUN_PROBE_MAX_INSTANCES_PER_CELL) \
		CLEAN_RUN_GROUP_ID=$(CLEAN_RUN_PROBE_GROUP_ID) \
		CLEAN_RUN_MAX_INSTANCES_PER_GROUP=$(CLEAN_RUN_PROBE_MAX_INSTANCES_PER_GROUP)

clean-run-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(CLEAN_RUN_LOGICAL_RUN_ID)

clean-run-rerun-plan: clean-run-index
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-rerun-plan \
		CORPUS_EXECUTION_PLAN=$(CLEAN_RUN_PLAN) \
		CORPUS_LOGICAL_RUN_ID=$(CLEAN_RUN_LOGICAL_RUN_ID) \
		CORPUS_RERUN_PLAN_LABEL=$(CLEAN_RUN_RERUN_LABEL) \
		CORPUS_RERUN_STATUSES=$(CLEAN_RUN_RERUN_STATUSES) \
		CORPUS_RERUN_HARD_TIMEOUT_SECONDS=$(CLEAN_RUN_RERUN_HARD_TIMEOUT_SECONDS) \
		CORPUS_RERUN_TIMEOUT_GRACE_SECONDS=$(CLEAN_RUN_RERUN_TIMEOUT_GRACE_SECONDS) \
		$(if $(CLEAN_RUN_RERUN_PLAN_OUT),CORPUS_RERUN_PLAN_OUT=$(CLEAN_RUN_RERUN_PLAN_OUT),)

wan-run-validate:
	uv run master-regimes validate-corpus --manifest $(WAN_RUN_MANIFEST)

wan-run-render: wan-run-validate
	uv run master-regimes render-corpus \
		--manifest $(WAN_RUN_MANIFEST) \
		--out $(WAN_RUN_OUT) \
		$(if $(WAN_RUN_MAX_INSTANCES_PER_CELL),--max-instances-per-cell $(WAN_RUN_MAX_INSTANCES_PER_CELL),)

wan-run-dry-run: wan-run-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(WAN_RUN_PLAN) \
		CORPUS_RUN_LABEL=$(WAN_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(WAN_RUN_DRY_RUN_LOGICAL_RUN_ID) \
		$(if $(WAN_RUN_GROUP_ID),CORPUS_RUN_GROUP_ID=$(WAN_RUN_GROUP_ID),) \
		$(if $(WAN_RUN_MAX_GROUPS),CORPUS_RUN_MAX_GROUPS=$(WAN_RUN_MAX_GROUPS),) \
		$(if $(WAN_RUN_MAX_INSTANCES_PER_GROUP),CORPUS_RUN_MAX_INSTANCES_PER_GROUP=$(WAN_RUN_MAX_INSTANCES_PER_GROUP),) \
		CORPUS_RUN_DRY_RUN=true

wan-run-start: wan-run-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(WAN_RUN_PLAN) \
		CORPUS_RUN_LABEL=$(WAN_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(WAN_RUN_LOGICAL_RUN_ID) \
		$(if $(WAN_RUN_GROUP_ID),CORPUS_RUN_GROUP_ID=$(WAN_RUN_GROUP_ID),) \
		$(if $(WAN_RUN_MAX_GROUPS),CORPUS_RUN_MAX_GROUPS=$(WAN_RUN_MAX_GROUPS),) \
		$(if $(WAN_RUN_MAX_INSTANCES_PER_GROUP),CORPUS_RUN_MAX_INSTANCES_PER_GROUP=$(WAN_RUN_MAX_INSTANCES_PER_GROUP),) \
		CORPUS_RUN_DRY_RUN=$(WAN_RUN_DRY_RUN)

wan-run-probe-start:
	$(MAKE) wan-run-start \
		WAN_RUN_LABEL=$(WAN_RUN_PROBE_LABEL) \
		WAN_RUN_LOGICAL_RUN_ID=$(WAN_RUN_PROBE_LOGICAL_RUN_ID) \
		WAN_RUN_MAX_INSTANCES_PER_CELL=$(WAN_RUN_PROBE_MAX_INSTANCES_PER_CELL) \
		WAN_RUN_GROUP_ID=$(WAN_RUN_PROBE_GROUP_ID) \
		WAN_RUN_MAX_INSTANCES_PER_GROUP=$(WAN_RUN_PROBE_MAX_INSTANCES_PER_GROUP)

wan-run-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(WAN_RUN_LOGICAL_RUN_ID)

region-imbalance-run-validate:
	uv run master-regimes validate-corpus --manifest $(REGION_IMBALANCE_RUN_MANIFEST)

region-imbalance-run-render: region-imbalance-run-validate
	uv run master-regimes render-corpus \
		--manifest $(REGION_IMBALANCE_RUN_MANIFEST) \
		--out $(REGION_IMBALANCE_RUN_OUT) \
		$(if $(REGION_IMBALANCE_RUN_MAX_INSTANCES_PER_CELL),--max-instances-per-cell $(REGION_IMBALANCE_RUN_MAX_INSTANCES_PER_CELL),)

region-imbalance-run-start: region-imbalance-run-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(REGION_IMBALANCE_RUN_PLAN) \
		CORPUS_RUN_LABEL=$(REGION_IMBALANCE_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(REGION_IMBALANCE_RUN_LOGICAL_RUN_ID) \
		$(if $(REGION_IMBALANCE_RUN_GROUP_ID),CORPUS_RUN_GROUP_ID=$(REGION_IMBALANCE_RUN_GROUP_ID),) \
		$(if $(REGION_IMBALANCE_RUN_MAX_GROUPS),CORPUS_RUN_MAX_GROUPS=$(REGION_IMBALANCE_RUN_MAX_GROUPS),) \
		$(if $(REGION_IMBALANCE_RUN_MAX_INSTANCES_PER_GROUP),CORPUS_RUN_MAX_INSTANCES_PER_GROUP=$(REGION_IMBALANCE_RUN_MAX_INSTANCES_PER_GROUP),)

region-imbalance-run-probe-start:
	$(MAKE) region-imbalance-run-start \
		REGION_IMBALANCE_RUN_LABEL=$(REGION_IMBALANCE_RUN_PROBE_LABEL) \
		REGION_IMBALANCE_RUN_LOGICAL_RUN_ID=$(REGION_IMBALANCE_RUN_PROBE_LOGICAL_RUN_ID) \
		REGION_IMBALANCE_RUN_MAX_INSTANCES_PER_CELL=$(REGION_IMBALANCE_RUN_PROBE_MAX_INSTANCES_PER_CELL) \
		REGION_IMBALANCE_RUN_GROUP_ID=$(REGION_IMBALANCE_RUN_PROBE_GROUP_ID) \
		REGION_IMBALANCE_RUN_MAX_INSTANCES_PER_GROUP=$(REGION_IMBALANCE_RUN_PROBE_MAX_INSTANCES_PER_GROUP)

region-imbalance-run-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(REGION_IMBALANCE_RUN_LOGICAL_RUN_ID)

region-asymmetry-run-validate:
	uv run master-regimes validate-corpus --manifest $(REGION_ASYMMETRY_RUN_MANIFEST)

region-asymmetry-run-render: region-asymmetry-run-validate
	uv run master-regimes render-corpus \
		--manifest $(REGION_ASYMMETRY_RUN_MANIFEST) \
		--out $(REGION_ASYMMETRY_RUN_OUT) \
		$(if $(REGION_ASYMMETRY_RUN_MAX_INSTANCES_PER_CELL),--max-instances-per-cell $(REGION_ASYMMETRY_RUN_MAX_INSTANCES_PER_CELL),)

region-asymmetry-run-dry-run: region-asymmetry-run-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(REGION_ASYMMETRY_RUN_PLAN) \
		CORPUS_RUN_LABEL=$(REGION_ASYMMETRY_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(REGION_ASYMMETRY_RUN_DRY_RUN_LOGICAL_RUN_ID) \
		$(if $(REGION_ASYMMETRY_RUN_GROUP_ID),CORPUS_RUN_GROUP_ID=$(REGION_ASYMMETRY_RUN_GROUP_ID),) \
		$(if $(REGION_ASYMMETRY_RUN_MAX_GROUPS),CORPUS_RUN_MAX_GROUPS=$(REGION_ASYMMETRY_RUN_MAX_GROUPS),) \
		$(if $(REGION_ASYMMETRY_RUN_MAX_INSTANCES_PER_GROUP),CORPUS_RUN_MAX_INSTANCES_PER_GROUP=$(REGION_ASYMMETRY_RUN_MAX_INSTANCES_PER_GROUP),) \
		CORPUS_RUN_DRY_RUN=true

region-asymmetry-run-start: region-asymmetry-run-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(REGION_ASYMMETRY_RUN_PLAN) \
		CORPUS_RUN_LABEL=$(REGION_ASYMMETRY_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID) \
		$(if $(REGION_ASYMMETRY_RUN_GROUP_ID),CORPUS_RUN_GROUP_ID=$(REGION_ASYMMETRY_RUN_GROUP_ID),) \
		$(if $(REGION_ASYMMETRY_RUN_MAX_GROUPS),CORPUS_RUN_MAX_GROUPS=$(REGION_ASYMMETRY_RUN_MAX_GROUPS),) \
		$(if $(REGION_ASYMMETRY_RUN_MAX_INSTANCES_PER_GROUP),CORPUS_RUN_MAX_INSTANCES_PER_GROUP=$(REGION_ASYMMETRY_RUN_MAX_INSTANCES_PER_GROUP),) \
		CORPUS_RUN_DRY_RUN=$(REGION_ASYMMETRY_RUN_DRY_RUN)

region-asymmetry-run-probe-start:
	$(MAKE) region-asymmetry-run-start \
		REGION_ASYMMETRY_RUN_LABEL=$(REGION_ASYMMETRY_RUN_PROBE_LABEL) \
		REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID=$(REGION_ASYMMETRY_RUN_PROBE_LOGICAL_RUN_ID) \
		REGION_ASYMMETRY_RUN_MAX_INSTANCES_PER_CELL=$(REGION_ASYMMETRY_RUN_PROBE_MAX_INSTANCES_PER_CELL) \
		REGION_ASYMMETRY_RUN_GROUP_ID=$(REGION_ASYMMETRY_RUN_PROBE_GROUP_ID) \
		REGION_ASYMMETRY_RUN_MAX_INSTANCES_PER_GROUP=$(REGION_ASYMMETRY_RUN_PROBE_MAX_INSTANCES_PER_GROUP)

region-asymmetry-run-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(REGION_ASYMMETRY_RUN_LOGICAL_RUN_ID)

region-asymmetry-run-script:
	scripts/run_region_asymmetry_150.sh

skew-replacement-rerun:
	scripts/run_skew_replacement_rerun.sh

validation-holdout-validate:
	uv run master-regimes validate-corpus --manifest $(VALIDATION_HOLDOUT_MANIFEST)

validation-holdout-render: validation-holdout-validate
	uv run master-regimes render-corpus \
		--manifest $(VALIDATION_HOLDOUT_MANIFEST) \
		--out $(VALIDATION_HOLDOUT_OUT) \
		$(if $(VALIDATION_HOLDOUT_MAX_INSTANCES_PER_CELL),--max-instances-per-cell $(VALIDATION_HOLDOUT_MAX_INSTANCES_PER_CELL),)

validation-holdout-dry-run: validation-holdout-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(VALIDATION_HOLDOUT_PLAN) \
		CORPUS_RUN_LABEL=$(VALIDATION_HOLDOUT_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(VALIDATION_HOLDOUT_DRY_RUN_LOGICAL_RUN_ID) \
		$(if $(VALIDATION_HOLDOUT_GROUP_ID),CORPUS_RUN_GROUP_ID=$(VALIDATION_HOLDOUT_GROUP_ID),) \
		$(if $(VALIDATION_HOLDOUT_MAX_GROUPS),CORPUS_RUN_MAX_GROUPS=$(VALIDATION_HOLDOUT_MAX_GROUPS),) \
		$(if $(VALIDATION_HOLDOUT_MAX_INSTANCES_PER_GROUP),CORPUS_RUN_MAX_INSTANCES_PER_GROUP=$(VALIDATION_HOLDOUT_MAX_INSTANCES_PER_GROUP),) \
		CORPUS_RUN_DRY_RUN=true

validation-holdout-start: validation-holdout-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(VALIDATION_HOLDOUT_PLAN) \
		CORPUS_RUN_LABEL=$(VALIDATION_HOLDOUT_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(VALIDATION_HOLDOUT_LOGICAL_RUN_ID) \
		$(if $(VALIDATION_HOLDOUT_GROUP_ID),CORPUS_RUN_GROUP_ID=$(VALIDATION_HOLDOUT_GROUP_ID),) \
		$(if $(VALIDATION_HOLDOUT_MAX_GROUPS),CORPUS_RUN_MAX_GROUPS=$(VALIDATION_HOLDOUT_MAX_GROUPS),) \
		$(if $(VALIDATION_HOLDOUT_MAX_INSTANCES_PER_GROUP),CORPUS_RUN_MAX_INSTANCES_PER_GROUP=$(VALIDATION_HOLDOUT_MAX_INSTANCES_PER_GROUP),) \
		CORPUS_RUN_DRY_RUN=$(VALIDATION_HOLDOUT_DRY_RUN)

validation-holdout-probe-start:
	$(MAKE) validation-holdout-start \
		VALIDATION_HOLDOUT_LABEL=$(VALIDATION_HOLDOUT_PROBE_LABEL) \
		VALIDATION_HOLDOUT_LOGICAL_RUN_ID=$(VALIDATION_HOLDOUT_PROBE_LOGICAL_RUN_ID) \
		VALIDATION_HOLDOUT_MAX_INSTANCES_PER_CELL=$(VALIDATION_HOLDOUT_PROBE_MAX_INSTANCES_PER_CELL) \
		VALIDATION_HOLDOUT_GROUP_ID=$(VALIDATION_HOLDOUT_PROBE_GROUP_ID) \
		VALIDATION_HOLDOUT_MAX_INSTANCES_PER_GROUP=$(VALIDATION_HOLDOUT_PROBE_MAX_INSTANCES_PER_GROUP)

validation-holdout-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(VALIDATION_HOLDOUT_LOGICAL_RUN_ID)

validation-holdout-script:
	scripts/run_validation_holdout.sh

companion-runs-overnight:
	scripts/run_companion_overnight.sh

logical-run-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index CORPUS_LOGICAL_RUN_ID=$(LOGICAL_RUN_ID)

feature-matrix:
	uv run master-regimes build-feature-matrix \
		--index-dir $(LOGICAL_INDEX) \
		--out $(FEATURES_OUT) \
		--topology $(FEATURE_TOPOLOGY)

clustering-dataset:
	uv run master-regimes prepare-clustering-dataset \
		--features-dir $(FEATURES_OUT) \
		--out-dir $(FEATURES_OUT)/preprocessed

clustering-ready-gates:
	mkdir -p $(REPORT_OUT)
	uv run python analysis/scripts/agent/10_region_worker_readiness.py \
		--index-dir $(LOGICAL_INDEX) \
		--out $(REPORT_OUT)/10_region_worker_readiness.md
	uv run python analysis/scripts/agent/11_clustering_ready_gate.py \
		--index-dir $(LOGICAL_INDEX) \
		--features-dir $(FEATURES_OUT) \
		--out $(REPORT_OUT)/11_clustering_ready_gate.md

corpus-coverage-gate:
	mkdir -p $(REPORT_OUT)
	uv run python analysis/scripts/agent/12_corpus_coverage_gate.py \
		--index-dir $(LOGICAL_INDEX) \
		--manifest $(CORPUS_MANIFEST) \
		--coverage $(CORPUS_COVERAGE) \
		--include-execution-class $(CORPUS_INCLUDE_EXECUTION_CLASS) \
		--artifacts-dir $(REPORT_OUT) \
		--out $(REPORT_OUT)/12_corpus_coverage_gate.md

baseline-coverage-report:
	mkdir -p $(REPORT_OUT)
	uv run python analysis/scripts/agent/14_baseline_coverage_report.py \
		--index-dir $(LOGICAL_INDEX) \
		--manifest $(CORPUS_MANIFEST) \
		--include-execution-class $(CORPUS_INCLUDE_EXECUTION_CLASS) \
		--out $(REPORT_OUT)/baseline_coverage_report.md \
		--summary-json $(REPORT_OUT)/baseline_coverage_summary.json \
		--regime-csv $(REPORT_OUT)/baseline_regime_audit.csv

nplusone-contract-gate:
	mkdir -p $(REPORT_OUT)
	uv run python analysis/scripts/agent/13_nplusone_contract_audit.py \
		--index-dir $(LOGICAL_INDEX) \
		--features-dir $(FEATURES_OUT) \
		--out $(REPORT_OUT)/13_nplusone_contract_audit.md

clustering-ready-audit: logical-run-index feature-matrix clustering-dataset clustering-ready-gates corpus-coverage-gate baseline-coverage-report nplusone-contract-gate

collector-correctness-audit:
	uv run python analysis/scripts/agent/38_collector_correctness_audit.py
	uv run python analysis/scripts/agent/39_review_collector_selection.py
	uv run python analysis/scripts/agent/38_collector_correctness_audit.py
	uv run python analysis/scripts/agent/47_collector_correctness_thesis_tables.py

reproducibility-package:
	uv run python analysis/scripts/agent/40_build_reproducibility_package.py
	uv run python analysis/scripts/agent/48_reproducibility_thesis_tables.py

thesis-numeric-consistency-audit:
	uv run python analysis/scripts/agent/49_thesis_numeric_consistency_audit.py

thesis-claim-evidence-audit:
	uv run python analysis/scripts/agent/50_thesis_claim_evidence_audit.py

thesis-local-reproduction:
	uv run python analysis/scripts/agent/51_thesis_local_reproduction.py

thesis-finalization-audit:
	uv run python analysis/scripts/agent/52_thesis_finalization_audit.py

repeatability-selection:
	uv run python analysis/scripts/agent/41_build_repeatability_selection.py

repeatability-dry-run: repeatability-selection
	uv run python analysis/scripts/agent/42_build_repeatability_dry_run.py

repeatability-local-gate: repeatability-dry-run
	uv run python analysis/scripts/agent/43_repeatability_dry_run_audit.py

repeatability-infra-dry-run: repeatability-local-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(REPEATABILITY_PLAN) \
		CORPUS_RUN_LABEL=$(REPEATABILITY_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(REPEATABILITY_DRY_RUN_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=true

repeatability-smoke-infra-dry-run: repeatability-local-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(REPEATABILITY_SMOKE_PLAN) \
		CORPUS_RUN_LABEL=$(REPEATABILITY_SMOKE_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(REPEATABILITY_SMOKE_DRY_RUN_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=true

repeatability-smoke-start: repeatability-local-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(REPEATABILITY_SMOKE_PLAN) \
		CORPUS_RUN_LABEL=$(REPEATABILITY_SMOKE_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(REPEATABILITY_SMOKE_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=false

repeatability-start: repeatability-local-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(REPEATABILITY_PLAN) \
		CORPUS_RUN_LABEL=$(REPEATABILITY_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(REPEATABILITY_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=false

repeatability-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(REPEATABILITY_LOGICAL_RUN_ID)

repeatability-rerun-plan: repeatability-index
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-rerun-plan \
		CORPUS_EXECUTION_PLAN=$(REPEATABILITY_PLAN) \
		CORPUS_LOGICAL_RUN_ID=$(REPEATABILITY_LOGICAL_RUN_ID) \
		CORPUS_RERUN_PLAN_LABEL=$(REPEATABILITY_RERUN_LABEL) \
		CORPUS_RERUN_STATUSES=$(REPEATABILITY_RERUN_STATUSES) \
		$(if $(REPEATABILITY_RERUN_PLAN_OUT),CORPUS_RERUN_PLAN_OUT=$(REPEATABILITY_RERUN_PLAN_OUT),) \
		$(if $(REPEATABILITY_RERUN_HARD_TIMEOUT_SECONDS),CORPUS_RERUN_HARD_TIMEOUT_SECONDS=$(REPEATABILITY_RERUN_HARD_TIMEOUT_SECONDS),) \
		CORPUS_RERUN_TIMEOUT_GRACE_SECONDS=$(REPEATABILITY_RERUN_TIMEOUT_GRACE_SECONDS)

repeatability-feature-matrix: repeatability-index
	uv run master-regimes build-feature-matrix \
		--index-dir $(REPEATABILITY_INDEX_DIR) \
		--out $(REPEATABILITY_FEATURE_DIR) \
		--topology multi_region

repeatability-analyze: repeatability-feature-matrix
	uv run python analysis/scripts/agent/44_repeatability_run_analysis.py \
		--logical-root $(REPEATABILITY_LOGICAL_ROOT) \
		--logical-run-id $(REPEATABILITY_LOGICAL_RUN_ID) \
		--feature-dir $(REPEATABILITY_FEATURE_DIR) \
		--out-dir $(REPEATABILITY_REPORT_DIR) \
		--selection $(REPEATABILITY_SELECTION)

confirmatory-skew-plan:
	uv run master-regimes validate-corpus \
		--manifest workloads/corpus/corpus_manifest.confirmatory-skew-v1.yml
	uv run python analysis/scripts/agent/53_build_confirmatory_skew_plan.py \
		--config $(CONFIRMATORY_SKEW_CONFIG) \
		--selection $(CONFIRMATORY_SKEW_SELECTION)

confirmatory-skew-local-gate: confirmatory-skew-plan
	uv run python analysis/scripts/agent/54_confirmatory_skew_local_readiness.py \
		--config $(CONFIRMATORY_SKEW_CONFIG) \
		--plan $(CONFIRMATORY_SKEW_PLAN) \
		--selection $(CONFIRMATORY_SKEW_SELECTION) \
		--out-dir $(CONFIRMATORY_SKEW_REPORT_DIR) \
		--checkpoint $(CONFIRMATORY_SKEW_CHECKPOINT)

confirmatory-skew-capability-review:
	@if [ -z "$(CONFIRMATORY_SKEW_CAPABILITY_RUN_DIR)" ]; then echo "CONFIRMATORY_SKEW_CAPABILITY_RUN_DIR is required"; exit 1; fi
	uv run python analysis/scripts/agent/55_confirmatory_skew_capability_review.py \
		--run-dir "$(CONFIRMATORY_SKEW_CAPABILITY_RUN_DIR)" \
		--config $(CONFIRMATORY_SKEW_CONFIG) \
		--out-dir $(CONFIRMATORY_SKEW_CAPABILITY_REPORT_DIR) \
		--checkpoint $(CONFIRMATORY_SKEW_CAPABILITY_CHECKPOINT)

confirmatory-skew-execution-review:
	@if [ -z "$(CONFIRMATORY_SKEW_EXECUTION_RUN_DIR)" ]; then echo "CONFIRMATORY_SKEW_EXECUTION_RUN_DIR is required"; exit 1; fi
	uv run python analysis/scripts/agent/56_confirmatory_skew_execution_review.py \
		--run-dir "$(CONFIRMATORY_SKEW_EXECUTION_RUN_DIR)" \
		--plan $(CONFIRMATORY_SKEW_PLAN) \
		--out-dir $(CONFIRMATORY_SKEW_EXECUTION_REPORT_DIR) \
		--checkpoint $(CONFIRMATORY_SKEW_EXECUTION_CHECKPOINT)

confirmatory-skew-analysis:
	@if [ -z "$(CONFIRMATORY_SKEW_EXECUTION_RUN_DIR)" ]; then echo "CONFIRMATORY_SKEW_EXECUTION_RUN_DIR is required"; exit 1; fi
	uv run master-regimes build-feature-matrix \
		--index-dir "$(CONFIRMATORY_SKEW_EXECUTION_RUN_DIR)/_logical/_index" \
		--out-dir $(CONFIRMATORY_SKEW_ANALYSIS_FEATURE_DIR) \
		--topology multi_region
	uv run python analysis/scripts/agent/57_confirmatory_skew_analysis.py \
		--run-dir "$(CONFIRMATORY_SKEW_EXECUTION_RUN_DIR)" \
		--feature-dir $(CONFIRMATORY_SKEW_ANALYSIS_FEATURE_DIR) \
		--out-dir $(CONFIRMATORY_SKEW_ANALYSIS_REPORT_DIR) \
		--checkpoint $(CONFIRMATORY_SKEW_ANALYSIS_CHECKPOINT)

guided-example-evidence:
	uv run python analysis/scripts/agent/58_build_guided_example_evidence.py

guided-example-final-audit:
	uv run python analysis/scripts/agent/59_guided_example_final_audit.py

pressure-smoke-validate:
	uv run master-regimes validate-corpus --manifest $(PRESSURE_SMOKE_MANIFEST)

pressure-smoke-render: pressure-smoke-validate
	uv run master-regimes render-corpus \
		--manifest $(PRESSURE_SMOKE_MANIFEST) \
		--out $(PRESSURE_SMOKE_OUT) \
		--include-execution-class pilot

pressure-smoke-infra-dry-run: pressure-smoke-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(PRESSURE_SMOKE_PLAN) \
		CORPUS_RUN_LABEL=$(PRESSURE_SMOKE_LABEL)-dry-run \
		CORPUS_LOGICAL_RUN_ID=$(PRESSURE_SMOKE_DRY_RUN_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=true

pressure-smoke-start: pressure-smoke-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(PRESSURE_SMOKE_PLAN) \
		CORPUS_RUN_LABEL=$(PRESSURE_SMOKE_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(PRESSURE_SMOKE_LOGICAL_RUN_ID)

pressure-smoke-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(PRESSURE_SMOKE_LOGICAL_RUN_ID)

pressure-smoke-feature-matrix: pressure-smoke-index
	uv run master-regimes build-feature-matrix \
		--index-dir $(PRESSURE_SMOKE_LOGICAL_DIR)/_index \
		--out $(PRESSURE_SMOKE_FEATURE_DIR) \
		--topology multi_region

pressure-smoke-analyze: pressure-smoke-feature-matrix
	uv run python analysis/scripts/agent/72_pressure_intervention_analysis.py \
		--feature-dir $(PRESSURE_SMOKE_FEATURE_DIR) \
		--out-dir $(PRESSURE_SMOKE_REPORT_DIR) \
		--worker-skew-pairs $(PRESSURE_WORKER_SKEW_PAIRS) \
		--worker-skew-target $(PRESSURE_WORKER_SKEW_TARGET)

pressure-worker-skew-plan:
	uv run master-regimes validate-corpus \
		--manifest workloads/corpus/corpus_manifest.pressure-worker-skew-smoke-v1.yml
	uv run python analysis/scripts/agent/53_build_confirmatory_skew_plan.py \
		--config $(PRESSURE_WORKER_SKEW_CONFIG) \
		--selection $(PRESSURE_WORKER_SKEW_SELECTION)

pressure-worker-skew-analyze:
	uv run python analysis/scripts/agent/73_pressure_worker_skew_analysis.py \
		--run-dir $(PRESSURE_WORKER_SKEW_RUN_DIR) \
		--out-dir $(PRESSURE_WORKER_SKEW_REPORT_DIR)

pressure-program-build:
	uv run python analysis/scripts/agent/74_build_pressure_intervention_program.py \
		--config $(PRESSURE_PROGRAM_CONFIG) \
		--out-dir $(PRESSURE_PROGRAM_OUT)

pressure-program-dry-run: pressure-program-build
	uv run python analysis/scripts/agent/75_run_pressure_intervention_program.py \
		--program $(PRESSURE_PROGRAM_PLAN) \
		--state-dir $(PRESSURE_PROGRAM_STATE_DIR) \
		--dry-run \
		$(if $(PRESSURE_PROGRAM_SEGMENT_ID),--segment-id "$(PRESSURE_PROGRAM_SEGMENT_ID)",) \
		$(if $(PRESSURE_PROGRAM_MAX_SEGMENTS),--max-segments "$(PRESSURE_PROGRAM_MAX_SEGMENTS)",)

pressure-program-start: pressure-program-build
	uv run python analysis/scripts/agent/75_run_pressure_intervention_program.py \
		--program $(PRESSURE_PROGRAM_PLAN) \
		--state-dir $(PRESSURE_PROGRAM_STATE_DIR) \
		$(if $(PRESSURE_PROGRAM_SEGMENT_ID),--segment-id "$(PRESSURE_PROGRAM_SEGMENT_ID)",) \
		$(if $(PRESSURE_PROGRAM_MAX_SEGMENTS),--max-segments "$(PRESSURE_PROGRAM_MAX_SEGMENTS)",)

pressure-program-status:
	uv run python analysis/scripts/agent/75_run_pressure_intervention_program.py \
		--program $(PRESSURE_PROGRAM_PLAN) \
		--state-dir $(PRESSURE_PROGRAM_STATE_DIR) \
		--status-only

pressure-raw-build:
	uv run python analysis/scripts/agent/76_build_pressure_raw_collection.py

pressure-raw-validate: pressure-raw-build
	uv run python analysis/scripts/agent/77_validate_pressure_raw_collection.py \
		--program $(PRESSURE_RAW_PROGRAM)

pressure-raw-batch-dry-run: pressure-raw-validate
	uv run python analysis/scripts/agent/78_run_pressure_raw_batch.py \
		--program $(PRESSURE_RAW_PROGRAM) \
		--batch-id $(PRESSURE_RAW_BATCH) \
		$(if $(PRESSURE_RAW_STATE_DIR),--state-dir $(PRESSURE_RAW_STATE_DIR),) \
		--dry-run

pressure-raw-batch-start: pressure-raw-validate
	uv run python analysis/scripts/agent/78_run_pressure_raw_batch.py \
		--program $(PRESSURE_RAW_PROGRAM) \
		--batch-id $(PRESSURE_RAW_BATCH) \
		$(if $(PRESSURE_RAW_STATE_DIR),--state-dir $(PRESSURE_RAW_STATE_DIR),)

pressure-raw-batch-status:
	uv run python analysis/scripts/agent/78_run_pressure_raw_batch.py \
		--program $(PRESSURE_RAW_PROGRAM) \
		--batch-id $(PRESSURE_RAW_BATCH) \
		$(if $(PRESSURE_RAW_STATE_DIR),--state-dir $(PRESSURE_RAW_STATE_DIR),) \
		--status-only

pressure-raw-smoke-validate:
	uv run python analysis/scripts/agent/79_validate_pressure_raw_smoke.py

pressure-raw-consolidate-partial:
	uv run python analysis/scripts/agent/86_consolidate_pressure_raw_program.py \
		--program $(PRESSURE_RAW_PROGRAM) \
		--out-dir $(PRESSURE_RAW_CONSOLIDATED_OUT) \
		--allow-incomplete

pressure-raw-consolidate:
	uv run python analysis/scripts/agent/86_consolidate_pressure_raw_program.py \
		--program $(PRESSURE_RAW_PROGRAM) \
		--out-dir $(PRESSURE_RAW_CONSOLIDATED_OUT)

pressure-raw-explore: pressure-raw-consolidate
	uv run python analysis/scripts/agent/87_pressure_raw_exploratory_analysis.py \
		--package-dir $(PRESSURE_RAW_CONSOLIDATED_OUT) \
		--out-dir $(PRESSURE_RAW_EXPLORATORY_OUT)

pressure-mitigation-action-audit: pressure-raw-explore
	uv run python analysis/scripts/agent/88_mitigation_action_audit.py \
		--package-dir $(PRESSURE_RAW_CONSOLIDATED_OUT) \
		--eda-dir $(PRESSURE_RAW_EXPLORATORY_OUT) \
		--contract $(PRESSURE_MITIGATION_ACTION_CONTRACT) \
		--correctness-recovery-dir $(PRESSURE_MITIGATION_CORRECTNESS_OUT) \
		--out-dir $(PRESSURE_MITIGATION_ACTION_OUT)

.PHONY: pressure-profile-scorers pressure-profile-local-gate
pressure-profile-scorers: pressure-mitigation-action-audit
	uv run python analysis/scripts/agent/100_pressure_profile_scorers.py \
		--package-dir $(PRESSURE_RAW_CONSOLIDATED_OUT) \
		--action-audit-dir $(PRESSURE_MITIGATION_ACTION_OUT) \
		--contract $(PRESSURE_PROFILE_SCORER_CONTRACT) \
		--out-dir $(PRESSURE_PROFILE_SCORER_OUT)

pressure-profile-local-gate:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_pressure_profile_scorers.py
	uv run ruff check \
		analysis/scripts/agent/100_pressure_profile_scorers.py \
		tests/test_pressure_profile_scorers.py

.PHONY: pressure-cross-action-feasibility pressure-cross-action-local-gate
pressure-cross-action-feasibility: pressure-mitigation-action-audit
	uv run python analysis/scripts/agent/98_cross_action_feasibility_audit.py \
		--package-dir $(PRESSURE_RAW_CONSOLIDATED_OUT) \
		--action-audit-dir $(PRESSURE_MITIGATION_ACTION_OUT) \
		--contract $(PRESSURE_CROSS_ACTION_CONTRACT) \
		--out-dir $(PRESSURE_CROSS_ACTION_OUT)

pressure-cross-action-local-gate:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_cross_action_feasibility_audit.py
	uv run ruff check \
		analysis/scripts/agent/98_cross_action_feasibility_audit.py \
		tests/test_cross_action_feasibility_audit.py

.PHONY: cross-action-pilot-render cross-action-pilot-design-gate cross-action-pilot-local-gate cross-action-pilot-infra-dry-run cross-action-pilot-smoke-start cross-action-pilot-start cross-action-pilot-index cross-action-pilot-analyze
cross-action-pilot-render:
	uv run master-regimes validate-corpus \
		--manifest $(CROSS_ACTION_PILOT_MANIFEST)
	uv run master-regimes render-corpus \
		--manifest $(CROSS_ACTION_PILOT_MANIFEST) \
		--out $(CROSS_ACTION_PILOT_OUT)

cross-action-pilot-design-gate: cross-action-pilot-render
	uv run python analysis/scripts/agent/99_cross_action_pilot.py validate-design \
		--rendered-dir $(CROSS_ACTION_PILOT_OUT) \
		--runtime-catalog workloads/corpus/runtime-configs.yml \
		--contract $(CROSS_ACTION_PILOT_CONTRACT) \
		--out-dir $(CROSS_ACTION_PILOT_REPORT_OUT)

cross-action-pilot-local-gate: cross-action-pilot-design-gate
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_cross_action_pilot.py \
		tests/test_cross_action_feasibility_audit.py
	uv run ruff check \
		analysis/scripts/agent/98_cross_action_feasibility_audit.py \
		analysis/scripts/agent/99_cross_action_pilot.py \
		src/master_regimes/corpus_adapter.py \
		tests/test_cross_action_feasibility_audit.py \
		tests/test_cross_action_pilot.py

cross-action-pilot-infra-dry-run: cross-action-pilot-design-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(CROSS_ACTION_PILOT_PLAN) \
		CORPUS_RUN_LABEL=$(CROSS_ACTION_PILOT_RUN_LABEL)-dry-run \
		CORPUS_LOGICAL_RUN_ID=$(CROSS_ACTION_PILOT_LOGICAL_RUN_ID)-dry-run \
		CORPUS_RUN_DRY_RUN=true

cross-action-pilot-smoke-start: cross-action-pilot-design-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(CROSS_ACTION_PILOT_PLAN) \
		CORPUS_RUN_LABEL=$(CROSS_ACTION_PILOT_SMOKE_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(CROSS_ACTION_PILOT_SMOKE_LOGICAL_RUN_ID) \
		CORPUS_RUN_GROUP_ID=$(CROSS_ACTION_PILOT_SMOKE_GROUP) \
		CORPUS_RUN_MAX_INSTANCES_PER_GROUP=1

cross-action-pilot-start: cross-action-pilot-design-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(CROSS_ACTION_PILOT_PLAN) \
		CORPUS_RUN_LABEL=$(CROSS_ACTION_PILOT_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(CROSS_ACTION_PILOT_LOGICAL_RUN_ID)

cross-action-pilot-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(CROSS_ACTION_PILOT_LOGICAL_RUN_ID)

cross-action-pilot-analyze: cross-action-pilot-index
	uv run master-regimes build-feature-matrix \
		--index-dir $(CROSS_ACTION_PILOT_LOGICAL_DIR)/_index \
		--out $(CROSS_ACTION_PILOT_FEATURE_OUT) \
		--topology multi_region
	uv run python analysis/scripts/agent/99_cross_action_pilot.py analyze \
		--index-dir $(CROSS_ACTION_PILOT_LOGICAL_DIR)/_index \
		--feature-dir $(CROSS_ACTION_PILOT_FEATURE_OUT) \
		--contract $(CROSS_ACTION_PILOT_CONTRACT) \
		--out-dir $(CROSS_ACTION_PILOT_REPORT_OUT)

.PHONY: fuzzy-intervention-memory fuzzy-intervention-memory-local-gate
fuzzy-intervention-memory:
	uv run python analysis/scripts/agent/101_fuzzy_intervention_memory.py \
		--contract $(FUZZY_INTERVENTION_MEMORY_CONTRACT) \
		--out-dir $(FUZZY_INTERVENTION_MEMORY_OUT)

fuzzy-intervention-memory-local-gate:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_fuzzy_intervention_memory.py
	uv run ruff check \
		analysis/scripts/agent/101_fuzzy_intervention_memory.py \
		src/master_regimes/fuzzy_intervention_memory.py \
		tests/test_fuzzy_intervention_memory.py

.PHONY: fuzzy-memory-topk-render fuzzy-memory-topk-design-gate fuzzy-memory-topk-infra-dry-run fuzzy-memory-topk-smoke-render fuzzy-memory-topk-smoke-start fuzzy-memory-topk-start fuzzy-memory-topk-index fuzzy-memory-topk-analyze
fuzzy-memory-topk-render:
	uv run master-regimes validate-corpus \
		--manifest $(FUZZY_MEMORY_TOPK_MANIFEST)
	uv run master-regimes render-corpus \
		--manifest $(FUZZY_MEMORY_TOPK_MANIFEST) \
		--out $(FUZZY_MEMORY_TOPK_OUT)

fuzzy-memory-topk-design-gate: fuzzy-memory-topk-render
	uv run python analysis/scripts/agent/99_cross_action_pilot.py validate-design \
		--rendered-dir $(FUZZY_MEMORY_TOPK_OUT) \
		--runtime-catalog workloads/corpus/runtime-configs.yml \
		--contract $(FUZZY_MEMORY_TOPK_CONTRACT) \
		--out-dir $(FUZZY_MEMORY_TOPK_REPORT_OUT)

fuzzy-memory-topk-infra-dry-run: fuzzy-memory-topk-design-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(FUZZY_MEMORY_TOPK_PLAN) \
		CORPUS_RUN_LABEL=$(FUZZY_MEMORY_TOPK_RUN_LABEL)-dry-run \
		CORPUS_LOGICAL_RUN_ID=$(FUZZY_MEMORY_TOPK_LOGICAL_RUN_ID)-dry-run \
		CORPUS_RUN_DRY_RUN=true

fuzzy-memory-topk-smoke-render:
	uv run master-regimes validate-corpus \
		--manifest $(FUZZY_MEMORY_TOPK_SMOKE_MANIFEST)
	uv run master-regimes render-corpus \
		--manifest $(FUZZY_MEMORY_TOPK_SMOKE_MANIFEST) \
		--out $(FUZZY_MEMORY_TOPK_SMOKE_OUT)

fuzzy-memory-topk-smoke-start: fuzzy-memory-topk-smoke-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(FUZZY_MEMORY_TOPK_SMOKE_PLAN) \
		CORPUS_RUN_LABEL=$(FUZZY_MEMORY_TOPK_SMOKE_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(FUZZY_MEMORY_TOPK_SMOKE_LOGICAL_RUN_ID)

fuzzy-memory-topk-start: fuzzy-memory-topk-design-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(FUZZY_MEMORY_TOPK_PLAN) \
		CORPUS_RUN_LABEL=$(FUZZY_MEMORY_TOPK_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(FUZZY_MEMORY_TOPK_LOGICAL_RUN_ID)

fuzzy-memory-topk-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(FUZZY_MEMORY_TOPK_LOGICAL_RUN_ID)

fuzzy-memory-topk-analyze: fuzzy-memory-topk-index
	$(MAKE) fuzzy-intervention-memory

.PHONY: dba-memory-panel-prepare dba-memory-panel-render dba-memory-panel-design-gate dba-memory-panel-local-gate dba-memory-panel-infra-dry-run dba-memory-panel-start dba-memory-panel-index dba-memory-panel-analyze
dba-memory-panel-prepare:
	uv run python analysis/scripts/agent/102_dba_local_memory_panel.py prepare \
		--contract $(DBA_MEMORY_PANEL_CONTRACT) \
		--source-dir $(DBA_MEMORY_PANEL_SOURCE_DIR)

dba-memory-panel-render: dba-memory-panel-prepare
	uv run master-regimes validate-corpus \
		--manifest $(DBA_MEMORY_PANEL_MANIFEST)
	uv run master-regimes render-corpus \
		--manifest $(DBA_MEMORY_PANEL_MANIFEST) \
		--out $(DBA_MEMORY_PANEL_OUT)

dba-memory-panel-design-gate: dba-memory-panel-render
	uv run python analysis/scripts/agent/102_dba_local_memory_panel.py validate-design \
		--contract $(DBA_MEMORY_PANEL_CONTRACT) \
		--rendered-dir $(DBA_MEMORY_PANEL_OUT) \
		--out-dir $(DBA_MEMORY_PANEL_REPORT_OUT)

dba-memory-panel-local-gate: dba-memory-panel-design-gate
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_dba_local_memory_panel.py \
		tests/test_fuzzy_intervention_memory.py
	uv run ruff check \
		analysis/scripts/agent/102_dba_local_memory_panel.py \
		tests/test_dba_local_memory_panel.py

dba-memory-panel-infra-dry-run: dba-memory-panel-design-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(DBA_MEMORY_PANEL_PLAN) \
		CORPUS_RUN_LABEL=$(DBA_MEMORY_PANEL_RUN_LABEL)-dry-run \
		CORPUS_LOGICAL_RUN_ID=$(DBA_MEMORY_PANEL_LOGICAL_RUN_ID)-dry-run \
		CORPUS_RUN_DRY_RUN=true

dba-memory-panel-start: dba-memory-panel-design-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(DBA_MEMORY_PANEL_PLAN) \
		CORPUS_RUN_LABEL=$(DBA_MEMORY_PANEL_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(DBA_MEMORY_PANEL_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=false

dba-memory-panel-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(DBA_MEMORY_PANEL_LOGICAL_RUN_ID)

dba-memory-panel-analyze: dba-memory-panel-index
	uv run python analysis/scripts/agent/102_dba_local_memory_panel.py analyze \
		--contract $(DBA_MEMORY_PANEL_CONTRACT) \
		--index-dir $(DBA_MEMORY_PANEL_LOGICAL_DIR)/_index \
		--out-dir $(DBA_MEMORY_PANEL_REPORT_OUT)

.PHONY: n3-topology-memory-prepare n3-topology-memory-render n3-topology-memory-local-gate n3-topology-memory-dry-run n3-topology-memory-infra-dry-run n3-topology-memory-n2-start n3-topology-memory-n2-index n3-topology-memory-a-baseline-start n3-topology-memory-a-baseline-index n3-topology-memory-freeze-a n3-topology-memory-a-actions-start n3-topology-memory-a-actions-index n3-topology-memory-b-baseline-start n3-topology-memory-b-baseline-index n3-topology-memory-freeze-b n3-topology-memory-b-actions-start n3-topology-memory-b-actions-index n3-topology-memory-analyze
n3-topology-memory-prepare:
	uv run python $(N3_TOPOLOGY_MEMORY_SCRIPT) prepare \
		--contract $(N3_TOPOLOGY_MEMORY_CONTRACT) \
		--work-dir $(N3_TOPOLOGY_MEMORY_WORK_DIR) \
		--out-dir $(N3_TOPOLOGY_MEMORY_REPORT_OUT)

n3-topology-memory-render: n3-topology-memory-prepare
	@set -eu; \
	for block in $(N3_TOPOLOGY_MEMORY_BLOCKS); do \
		manifest="$(N3_TOPOLOGY_MEMORY_WORK_DIR)/source/$$block/corpus_manifest.yml"; \
		out="$(N3_TOPOLOGY_MEMORY_WORK_DIR)/rendered/$$block"; \
		uv run master-regimes validate-corpus --manifest "$$manifest"; \
		uv run master-regimes render-corpus --manifest "$$manifest" --out "$$out"; \
	done

n3-topology-memory-local-gate: n3-topology-memory-render
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_n3_topology_memory_experiment.py
	uv run ruff check $(N3_TOPOLOGY_MEMORY_SCRIPT) \
		tests/test_n3_topology_memory_experiment.py

n3-topology-memory-dry-run: n3-topology-memory-local-gate
	uv run python $(N3_TOPOLOGY_MEMORY_SCRIPT) dry-run \
		--contract $(N3_TOPOLOGY_MEMORY_CONTRACT) \
		--work-dir $(N3_TOPOLOGY_MEMORY_WORK_DIR) \
		--out-dir $(N3_TOPOLOGY_MEMORY_REPORT_OUT)

n3-topology-memory-infra-dry-run: n3-topology-memory-dry-run
	@set -eu; \
	for block in $(N3_TOPOLOGY_MEMORY_BLOCKS); do \
		plan="$(N3_TOPOLOGY_MEMORY_WORK_DIR)/rendered/$$block/corpus_execution_plan.yml"; \
		run_id="n3-topology-memory-v1-$$(printf '%s' "$$block" | tr '_' '-')-dry-run"; \
		$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
			CORPUS_EXECUTION_PLAN="$$plan" \
			CORPUS_RUN_LABEL="$$run_id" \
			CORPUS_LOGICAL_RUN_ID="$$run_id" \
			CORPUS_RUN_DRY_RUN=true; \
	done

n3-topology-memory-n2-start: n3-topology-memory-dry-run
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(N3_TOPOLOGY_MEMORY_WORK_DIR)/rendered/n2_control/corpus_execution_plan.yml \
		CORPUS_RUN_LABEL=$(N3_TOPOLOGY_MEMORY_N2_RUN_ID)-attempt-01 \
		CORPUS_LOGICAL_RUN_ID=$(N3_TOPOLOGY_MEMORY_N2_RUN_ID)

n3-topology-memory-n2-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(N3_TOPOLOGY_MEMORY_N2_RUN_ID)

n3-topology-memory-a-baseline-start: n3-topology-memory-dry-run
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(N3_TOPOLOGY_MEMORY_WORK_DIR)/rendered/phase_a_baseline/corpus_execution_plan.yml \
		CORPUS_RUN_LABEL=$(N3_TOPOLOGY_MEMORY_A_BASELINE_RUN_ID)-attempt-01 \
		CORPUS_LOGICAL_RUN_ID=$(N3_TOPOLOGY_MEMORY_A_BASELINE_RUN_ID)

n3-topology-memory-a-baseline-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(N3_TOPOLOGY_MEMORY_A_BASELINE_RUN_ID)

n3-topology-memory-freeze-a: n3-topology-memory-n2-index n3-topology-memory-a-baseline-index
	uv run python $(N3_TOPOLOGY_MEMORY_SCRIPT) freeze-a \
		--contract $(N3_TOPOLOGY_MEMORY_CONTRACT) \
		--work-dir $(N3_TOPOLOGY_MEMORY_WORK_DIR) \
		--out-dir $(N3_TOPOLOGY_MEMORY_REPORT_OUT)

n3-topology-memory-a-actions-start:
	test -s $(N3_TOPOLOGY_MEMORY_WORK_DIR)/freezes/phase_a_recommendations/recommendations.csv
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(N3_TOPOLOGY_MEMORY_WORK_DIR)/rendered/phase_a_actions/corpus_execution_plan.yml \
		CORPUS_RUN_LABEL=$(N3_TOPOLOGY_MEMORY_A_ACTIONS_RUN_ID)-attempt-01 \
		CORPUS_LOGICAL_RUN_ID=$(N3_TOPOLOGY_MEMORY_A_ACTIONS_RUN_ID)

n3-topology-memory-a-actions-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(N3_TOPOLOGY_MEMORY_A_ACTIONS_RUN_ID)

n3-topology-memory-b-baseline-start: n3-topology-memory-a-actions-index
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(N3_TOPOLOGY_MEMORY_WORK_DIR)/rendered/phase_b_baseline/corpus_execution_plan.yml \
		CORPUS_RUN_LABEL=$(N3_TOPOLOGY_MEMORY_B_BASELINE_RUN_ID)-attempt-01 \
		CORPUS_LOGICAL_RUN_ID=$(N3_TOPOLOGY_MEMORY_B_BASELINE_RUN_ID)

n3-topology-memory-b-baseline-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(N3_TOPOLOGY_MEMORY_B_BASELINE_RUN_ID)

n3-topology-memory-freeze-b: n3-topology-memory-a-actions-index n3-topology-memory-b-baseline-index
	uv run python $(N3_TOPOLOGY_MEMORY_SCRIPT) freeze-b \
		--contract $(N3_TOPOLOGY_MEMORY_CONTRACT) \
		--work-dir $(N3_TOPOLOGY_MEMORY_WORK_DIR) \
		--out-dir $(N3_TOPOLOGY_MEMORY_REPORT_OUT)

n3-topology-memory-b-actions-start:
	test -s $(N3_TOPOLOGY_MEMORY_WORK_DIR)/freezes/phase_b_recommendations/recommendations.csv
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(N3_TOPOLOGY_MEMORY_WORK_DIR)/rendered/phase_b_actions/corpus_execution_plan.yml \
		CORPUS_RUN_LABEL=$(N3_TOPOLOGY_MEMORY_B_ACTIONS_RUN_ID)-attempt-01 \
		CORPUS_LOGICAL_RUN_ID=$(N3_TOPOLOGY_MEMORY_B_ACTIONS_RUN_ID)

n3-topology-memory-b-actions-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(N3_TOPOLOGY_MEMORY_B_ACTIONS_RUN_ID)

n3-topology-memory-analyze: n3-topology-memory-b-actions-index
	uv run python $(N3_TOPOLOGY_MEMORY_SCRIPT) analyze \
		--contract $(N3_TOPOLOGY_MEMORY_CONTRACT) \
		--work-dir $(N3_TOPOLOGY_MEMORY_WORK_DIR) \
		--out-dir $(N3_TOPOLOGY_MEMORY_REPORT_OUT)

.PHONY: confirmatory-action-prepare confirmatory-action-render confirmatory-action-design-gate confirmatory-action-local-gate confirmatory-action-infra-dry-run confirmatory-action-start confirmatory-action-index confirmatory-action-analyze confirmatory-action-release
confirmatory-action-prepare:
	uv run python $(CONFIRMATORY_ACTION_SCRIPT) prepare \
		--contract $(CONFIRMATORY_ACTION_CONTRACT) \
		--source-dir $(CONFIRMATORY_ACTION_SOURCE_DIR) \
		--out-dir $(CONFIRMATORY_ACTION_REPORT_OUT)

confirmatory-action-render: confirmatory-action-prepare
	uv run master-regimes validate-corpus --manifest $(CONFIRMATORY_ACTION_MANIFEST)
	uv run master-regimes render-corpus \
		--manifest $(CONFIRMATORY_ACTION_MANIFEST) \
		--out $(CONFIRMATORY_ACTION_OUT)

confirmatory-action-design-gate: confirmatory-action-render
	uv run python $(CONFIRMATORY_ACTION_SCRIPT) validate-design \
		--contract $(CONFIRMATORY_ACTION_CONTRACT) \
		--rendered-dir $(CONFIRMATORY_ACTION_OUT) \
		--out-dir $(CONFIRMATORY_ACTION_REPORT_OUT)

confirmatory-action-local-gate: confirmatory-action-design-gate
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_confirmatory_action_replication.py \
		tests/test_repeatability.py
	uv run ruff check $(CONFIRMATORY_ACTION_SCRIPT) \
		tests/test_confirmatory_action_replication.py \
		src/master_regimes/corpus_adapter.py \
		tests/test_repeatability.py

confirmatory-action-infra-dry-run: confirmatory-action-local-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(CONFIRMATORY_ACTION_PLAN) \
		CORPUS_RUN_LABEL=$(CONFIRMATORY_ACTION_RUN_LABEL)-dry-run \
		CORPUS_LOGICAL_RUN_ID=$(CONFIRMATORY_ACTION_LOGICAL_RUN_ID)-dry-run \
		CORPUS_RUN_DRY_RUN=true

confirmatory-action-start: confirmatory-action-local-gate
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(CONFIRMATORY_ACTION_PLAN) \
		CORPUS_RUN_LABEL=$(CONFIRMATORY_ACTION_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(CONFIRMATORY_ACTION_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=false

confirmatory-action-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(CONFIRMATORY_ACTION_LOGICAL_RUN_ID)

confirmatory-action-analyze: confirmatory-action-index
	uv run python $(CONFIRMATORY_ACTION_SCRIPT) analyze \
		--contract $(CONFIRMATORY_ACTION_CONTRACT) \
		--index-dir $(CONFIRMATORY_ACTION_LOGICAL_DIR)/_index \
		--out-dir $(CONFIRMATORY_ACTION_REPORT_OUT)

confirmatory-action-release: confirmatory-action-index
	uv run python $(CONFIRMATORY_ACTION_SCRIPT) validate-design \
		--contract $(CONFIRMATORY_ACTION_CONTRACT) \
		--rendered-dir $(CONFIRMATORY_ACTION_OUT) \
		--out-dir $(CONFIRMATORY_ACTION_RELEASE_OUT)
	uv run python $(CONFIRMATORY_ACTION_SCRIPT) analyze \
		--contract $(CONFIRMATORY_ACTION_CONTRACT) \
		--index-dir $(CONFIRMATORY_ACTION_LOGICAL_DIR)/_index \
		--out-dir $(CONFIRMATORY_ACTION_RELEASE_OUT)
	cd $(CONFIRMATORY_ACTION_RELEASE_OUT) && sha256sum -c checksums.sha256

.PHONY: representation-value-ablation representation-value-ablation-release representation-value-ablation-local-gate
representation-value-ablation:
	uv run python analysis/scripts/agent/103_representation_value_ablation.py \
		--contract $(REPRESENTATION_VALUE_ABLATION_CONTRACT) \
		--out-dir $(REPRESENTATION_VALUE_ABLATION_OUT)

representation-value-ablation-release:
	uv run python analysis/scripts/agent/103_representation_value_ablation.py \
		--contract $(REPRESENTATION_VALUE_ABLATION_CONTRACT) \
		--out-dir $(REPRESENTATION_VALUE_ABLATION_RELEASE_OUT)

representation-value-ablation-local-gate: representation-value-ablation
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_representation_value_ablation.py \
		tests/test_dba_local_memory_panel.py
	uv run ruff check \
		analysis/scripts/agent/103_representation_value_ablation.py \
		tests/test_representation_value_ablation.py

.PHONY: representation-ablation-e1-e4 representation-ablation-e1-e4-release representation-ablation-e1-e4-local-gate
representation-ablation-e1-e4:
	uv run python analysis/scripts/agent/105_representation_ablation_e1_e4.py \
		--contract $(REPRESENTATION_E1_E4_CONTRACT) \
		--out-dir $(REPRESENTATION_E1_E4_OUT)

representation-ablation-e1-e4-release:
	uv run python analysis/scripts/agent/105_representation_ablation_e1_e4.py \
		--contract $(REPRESENTATION_E1_E4_CONTRACT) \
		--out-dir $(REPRESENTATION_E1_E4_RELEASE_OUT)

representation-ablation-e1-e4-local-gate: representation-ablation-e1-e4
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_representation_ablation_e1_e4.py \
		tests/test_representation_value_ablation.py \
		tests/test_dba_local_memory_panel.py \
		tests/test_n3_topology_memory_experiment.py
	uv run ruff check \
		analysis/scripts/agent/105_representation_ablation_e1_e4.py \
		tests/test_representation_ablation_e1_e4.py

.PHONY: consolidated-evaluation consolidated-evaluation-release consolidated-evaluation-local-gate consolidated-evaluation-manuscript-gate
consolidated-evaluation:
	uv run python analysis/scripts/agent/106_consolidated_evaluation.py \
		--contract $(CONSOLIDATED_EVALUATION_CONTRACT) \
		--out-dir $(CONSOLIDATED_EVALUATION_OUT)

consolidated-evaluation-release:
	uv run python analysis/scripts/agent/106_consolidated_evaluation.py \
		--contract $(CONSOLIDATED_EVALUATION_CONTRACT) \
		--out-dir $(CONSOLIDATED_EVALUATION_RELEASE_OUT)

consolidated-evaluation-local-gate: consolidated-evaluation
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_consolidated_evaluation.py \
		tests/test_representation_ablation_e1_e4.py \
		tests/test_dba_local_memory_panel.py \
		tests/test_n3_topology_memory_experiment.py
	uv run ruff check \
		analysis/scripts/agent/106_consolidated_evaluation.py \
		tests/test_consolidated_evaluation.py

consolidated-evaluation-manuscript-gate:
	uv run python analysis/scripts/agent/107_verify_consolidated_manuscript.py \
		--release-dir $(CONSOLIDATED_EVALUATION_RELEASE_OUT) \
		--thesis-root $(CONSOLIDATED_EVALUATION_THESIS_ROOT) \
		--out $(CONSOLIDATED_EVALUATION_MANUSCRIPT_AUDIT)
	uv run ruff check analysis/scripts/agent/107_verify_consolidated_manuscript.py

pressure-mitigation-correctness-prepare:
	uv run python analysis/scripts/agent/89_mitigation_correctness_recovery.py prepare \
		--action-audit-dir $(PRESSURE_MITIGATION_ACTION_OUT) \
		--contract $(PRESSURE_MITIGATION_CORRECTNESS_CONTRACT) \
		--out-dir $(PRESSURE_MITIGATION_CORRECTNESS_OUT)

pressure-mitigation-correctness-local-gate: pressure-mitigation-correctness-prepare
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_mitigation_correctness_recovery.py \
		tests/test_run_mitigation_correctness_recovery.py
	uv run ruff check \
		analysis/scripts/agent/89_mitigation_correctness_recovery.py \
		analysis/scripts/agent/90_run_mitigation_correctness_recovery.py \
		tests/test_mitigation_correctness_recovery.py \
		tests/test_run_mitigation_correctness_recovery.py

pressure-mitigation-correctness-dry-run: pressure-mitigation-correctness-prepare
	uv run python analysis/scripts/agent/90_run_mitigation_correctness_recovery.py \
		--report-dir $(PRESSURE_MITIGATION_CORRECTNESS_OUT) --dry-run

pressure-mitigation-correctness-start: pressure-mitigation-correctness-prepare
	uv run python analysis/scripts/agent/90_run_mitigation_correctness_recovery.py \
		--report-dir $(PRESSURE_MITIGATION_CORRECTNESS_OUT)

pressure-mitigation-correctness-status:
	uv run python analysis/scripts/agent/90_run_mitigation_correctness_recovery.py \
		--report-dir $(PRESSURE_MITIGATION_CORRECTNESS_OUT) --status-only

pressure-mitigation-correctness-analyze:
	uv run python analysis/scripts/agent/89_mitigation_correctness_recovery.py analyze \
		--contract $(PRESSURE_MITIGATION_CORRECTNESS_CONTRACT) \
		--out-dir $(PRESSURE_MITIGATION_CORRECTNESS_OUT)

pressure-colocation-gain-model: pressure-mitigation-action-audit
	uv run python analysis/scripts/agent/91_colocation_gain_model.py \
		--package-dir $(PRESSURE_RAW_CONSOLIDATED_OUT) \
		--action-audit-dir $(PRESSURE_MITIGATION_ACTION_OUT) \
		--contract $(PRESSURE_COLOCATION_GAIN_CONTRACT) \
		--out-dir $(PRESSURE_COLOCATION_GAIN_OUT)

.PHONY: pressure-colocation-ranking-robustness
pressure-colocation-ranking-robustness: pressure-colocation-gain-model
	uv run python analysis/scripts/agent/94_colocation_ranking_robustness.py \
		--contract $(PRESSURE_COLOCATION_RANKING_CONTRACT) \
		--out-dir $(PRESSURE_COLOCATION_RANKING_OUT)

.PHONY: pressure-colocation-eligibility-audit
pressure-colocation-eligibility-audit: pressure-mitigation-action-audit
	uv run python analysis/scripts/agent/95_colocation_eligibility_audit.py \
		--package-dir $(PRESSURE_RAW_CONSOLIDATED_OUT) \
		--action-audit-dir $(PRESSURE_MITIGATION_ACTION_OUT) \
		--contract $(PRESSURE_COLOCATION_ELIGIBILITY_CONTRACT) \
		--out-dir $(PRESSURE_COLOCATION_ELIGIBILITY_OUT)

.PHONY: pressure-n3-holdout-render pressure-n3-holdout-freeze pressure-n3-local-gate pressure-n3-holdout-infra-dry-run pressure-n3-holdout-start pressure-n3-holdout-index pressure-n3-holdout-analyze
pressure-n3-holdout-render:
	uv run master-regimes validate-corpus \
		--manifest $(PRESSURE_N3_HOLDOUT_MANIFEST)
	uv run master-regimes render-corpus \
		--manifest $(PRESSURE_N3_HOLDOUT_MANIFEST) \
		--out $(PRESSURE_N3_HOLDOUT_OUT)

pressure-n3-holdout-freeze: pressure-colocation-ranking-robustness pressure-n3-holdout-render
	uv run python analysis/scripts/agent/96_freeze_n3_colocation_holdout.py \
		--plan $(PRESSURE_N3_HOLDOUT_PLAN) \
		--out-dir $(PRESSURE_N3_FREEZE_OUT)

pressure-n3-local-gate: pressure-n3-holdout-render
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_n3_colocation_holdout.py \
		tests/test_corpus_adapter.py \
		tests/test_dataset_profile.py
	uv run ruff check \
		analysis/scripts/agent/96_freeze_n3_colocation_holdout.py \
		analysis/scripts/agent/97_n3_colocation_no_refit.py \
		tests/test_n3_colocation_holdout.py \
		src/master_regimes/corpus_adapter.py

pressure-n3-holdout-infra-dry-run: pressure-n3-holdout-freeze
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(PRESSURE_N3_HOLDOUT_PLAN) \
		CORPUS_RUN_LABEL=$(PRESSURE_N3_RUN_LABEL)-dry-run \
		CORPUS_LOGICAL_RUN_ID=$(PRESSURE_N3_LOGICAL_RUN_ID)-dry-run \
		CORPUS_RUN_DRY_RUN=true

pressure-n3-holdout-start: pressure-n3-holdout-freeze
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-apac-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(PRESSURE_N3_HOLDOUT_PLAN) \
		CORPUS_RUN_LABEL=$(PRESSURE_N3_RUN_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(PRESSURE_N3_LOGICAL_RUN_ID) \
		CORPUS_RUN_DRY_RUN=false

pressure-n3-holdout-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(PRESSURE_N3_LOGICAL_RUN_ID)

pressure-n3-holdout-analyze: pressure-n3-holdout-index
	uv run python analysis/scripts/agent/97_n3_colocation_no_refit.py \
		--freeze-dir $(PRESSURE_N3_FREEZE_OUT) \
		--index-dir $(PRESSURE_N3_LOGICAL_DIR)/_index \
		--out-dir $(PRESSURE_N3_REPORT_OUT)

.PHONY: pressure-mitigation-modeling-decision pressure-actionability-release
pressure-mitigation-modeling-decision: pressure-colocation-gain-model
	uv run python analysis/scripts/agent/92_mitigation_modeling_decision.py \
		--action-audit-dir $(PRESSURE_MITIGATION_ACTION_OUT) \
		--colocation-model-dir $(PRESSURE_COLOCATION_GAIN_OUT) \
		--out-dir $(PRESSURE_MITIGATION_DECISION_OUT)

pressure-actionability-release:
	uv run python analysis/scripts/agent/93_freeze_actionability_release.py \
		--evidence-commit HEAD

pressure-collection-preflight:
	uv run python analysis/scripts/agent/83_collection_uniformity_preflight.py \
		--sources $(PRESSURE_PREFLIGHT_SOURCES) \
		--out-dir $(PRESSURE_PREFLIGHT_OUT)

remote-edge-probe-validate:
	uv run master-regimes validate-corpus \
		--manifest $(REMOTE_EDGE_PROBE_MANIFEST)

remote-edge-probe-render: remote-edge-probe-validate
	uv run master-regimes render-corpus \
		--manifest $(REMOTE_EDGE_PROBE_MANIFEST) \
		--out $(REMOTE_EDGE_PROBE_OUT)

remote-edge-probe-local-gate: remote-edge-probe-render
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q \
		tests/test_query_sweep_index.py \
		tests/test_remote_edge_probe_analysis.py
	uv run ruff check \
		analysis/scripts/agent/84_remote_edge_probe_analysis.py \
		tests/test_remote_edge_probe_analysis.py \
		src/master_regimes/extract/query_sweep_index.py \
		tests/test_query_sweep_index.py

remote-edge-probe-infra-dry-run: remote-edge-probe-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(REMOTE_EDGE_PROBE_PLAN) \
		CORPUS_RUN_LABEL=$(REMOTE_EDGE_PROBE_LABEL)-dry-run \
		CORPUS_LOGICAL_RUN_ID=$(REMOTE_EDGE_PROBE_LOGICAL_RUN_ID)-dry-run \
		CORPUS_RUN_DRY_RUN=true

remote-edge-probe-start: remote-edge-probe-render
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) eu-us-gac-vps-corpus-run \
		CORPUS_EXECUTION_PLAN=$(REMOTE_EDGE_PROBE_PLAN) \
		CORPUS_RUN_LABEL=$(REMOTE_EDGE_PROBE_LABEL) \
		CORPUS_LOGICAL_RUN_ID=$(REMOTE_EDGE_PROBE_LOGICAL_RUN_ID)

remote-edge-probe-index:
	$(MAKE) -C $(MASTER_REGIMES_INFRA_DIR) corpus-run-index \
		CORPUS_LOGICAL_RUN_ID=$(REMOTE_EDGE_PROBE_LOGICAL_RUN_ID)

remote-edge-probe-analyze: remote-edge-probe-index
	uv run python analysis/scripts/agent/84_remote_edge_probe_analysis.py \
		--index-dir $(REMOTE_EDGE_PROBE_INDEX) \
		--out-dir $(REMOTE_EDGE_PROBE_REPORT)

.PHONY: feedback-loop-validate feedback-loop-dry-run
FEEDBACK_LOOP_EXPERIMENT_DIR ?= experiments/feedback-loop-v1
FEEDBACK_LOOP_VALIDATOR ?= analysis/scripts/agent/109_feedback_loop_protocol.py

feedback-loop-validate:
	uv run python $(FEEDBACK_LOOP_VALIDATOR) \
		--experiment-dir $(FEEDBACK_LOOP_EXPERIMENT_DIR) \
		--thesis-root ../master-regimes-thesis

feedback-loop-dry-run: feedback-loop-validate
	@printf '%s\n' 'Offline feedback-loop dry-run PASS; no SQL or infrastructure command executed.'

.PHONY: temporal-validity-audit
temporal-validity-audit:
	uv run python analysis/scripts/agent/114_temporal_validity_audit.py

.PHONY: action-selection-sample-size-audit
action-selection-sample-size-audit:
	uv run python analysis/scripts/agent/115_action_selection_sample_size_audit.py
