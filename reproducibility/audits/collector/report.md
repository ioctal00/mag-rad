# Evidence collection and indexing audit

**Verdict:** `pass_with_limitations`

This is an offline, read-only audit. It did not connect to infrastructure, execute SQL, or alter the audited repositories. The validator re-read packaged CSV/JSON data and tar archives instead of trusting only the existing summary report.

## Pipeline trace

1. **Planned identity.** The corpus adapter derives a condition identity and an `execution_slot_id = condition_id::repetition`; the sweep writes a completed slot only after an indexable manifest exists and the checkpoint is flushed with `fsync`.
2. **Primary GAC execution.** The runner uploads one rendered SQL file and invokes the benchmark wrapper with `EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)` and `citus.explain_all_tasks=on`. One top-level execution manifest binds the SQL, coordinator, runtime options, query window, status, and artifact paths.
3. **FDW and regional evidence.** The GAC plan exposes FDW `Remote SQL`. For the primary execution path, regional role-scoped `auto_explain` is enabled and unique FDW application names are configured. The runner records each regional PostgreSQL log start line and later copies the appended suffix.
4. **Regional Citus and worker/task evidence.** The indexer classifies regional documents as diagnostic, remote query, or internal statement. Citus task plans embedded in regional JSON/text are parsed into worker fragments linked by query ID and regional plan ID.
5. **Edge and OS context.** Optional SSH probes collect route, RTT, qdisc, and interface context. Optional samplers bracket the query window and read host `/proc` counters. These are node/window observations, not process-level SQL attribution.
6. **Result validation.** Optional stream signatures compute ordered and multiset SHA-256 summaries. They run after the primary EXPLAIN execution, so they are follow-up validation under the same intended context rather than a transactionally identical observation.
7. **Retry consolidation.** Physical attempts remain in `query_attempts.csv`. Resolution groups the declared logical fields, ranks completed attempts above timeouts/failures/missing rows, and uses the latest attempt within the best status.
8. **Typed evidence status.** The final index distinguishes `available`, `missing_unexpected`, `not_applicable`, `structurally_unavailable_repartition`, and unavailable timing in embedded task plans.

## Validator checks

| Check | Status | Result |
| --- | --- | --- |
| `source-snapshots` | **PASS** | 8 collector/indexer source files and repository provenance entries checked. |
| `release-hashes` | **PASS** | 6474 files verified (all scope). |
| `logical-index-graph` | **PASS** | 9 logical archives checked; 3185 query rows inspected. |
| `raw-artifact-presence` | **PASS** | 9 raw archives checked; 3145 query directories inspected. |
| `published-correctness-gate` | **PASS** | Published gate reports 2603/2603 complete queries and 2 resolved retries. |
| `equivalence-table-consistency` | **PASS** | 13 feedback-loop equivalence rows and 16 N3 pairs checked. |
| `correlation-concurrency-boundary` | **WARN** | Unique FDW application names are configured, but the indexer does not filter parsed log documents by that identity. |
| `host-attribution-boundary` | **WARN** | CPU, steal, interface, TCP, disk, and qdisc evidence is host/window scoped, not query-process scoped. |

## Packaged logical indexes

| Archive | Queries | Features | Plans | Regions | Workers | Attempts | Retries | Status |
| --- | --: | --: | --: | --: | --: | --: | --: | --- |
| `clean-run-v1-region-asymmetry-skew-rerun.tar.gz` | 294 | 294 | 4936 | 666 | 11082 | 294 | 0 | canonical |
| `clean-run-v1-region-asymmetry.tar.gz` | 150 | 150 | 2960 | 378 | 10794 | 150 | 0 | canonical |
| `clean-run-v1-validation-holdout.tar.gz` | 195 | 195 | 5868 | 426 | 8610 | 197 | 2 | canonical |
| `clean-run-v1-wan-latency.tar.gz` | 16 | 16 | 618 | 24 | 644 | 20 | 0 | canonical |
| `clean-run-v1.tar.gz` | 1964 | 1964 | 56045 | 2938 | 67976 | 1964 | 0 | canonical |
| `pressure-raw-v1-n3-colocation-holdout.tar.gz` | 96 | 96 | 0 | 432 | 7056 | 0 | 0 | derived/partial |
| `repeatability-v1.tar.gz` | 328 | 328 | 13684 | 588 | 15654 | 328 | 0 | canonical |
| `stats-ceb-full-no-refit-v1.tar.gz` | 130 | 130 | 12564 | 498 | 9302 | 292 | 146 | canonical |
| `stats-ceb-semantic-v2b-holdout.tar.gz` | 12 | 12 | 828 | 48 | 966 | 12 | 0 | canonical |

## Packaged raw attempts

| Archive | Query directories | Completed | Incomplete | GAC plans | Regional log windows | Result signatures | OS summaries |
| --- | --: | --: | --: | --: | --: | --: | --: |
| `clean-run-v1-region-asymmetry-skew-rerun.tar.gz` | 294 | 294 | 0 | 294 | 294 | 0 | 0 |
| `clean-run-v1-region-asymmetry.tar.gz` | 150 | 150 | 0 | 150 | 150 | 0 | 0 |
| `clean-run-v1-validation-holdout.tar.gz` | 196 | 195 | 1 | 195 | 195 | 0 | 0 |
| `clean-run-v1-wan-latency.tar.gz` | 20 | 16 | 4 | 16 | 20 | 0 | 0 |
| `clean-run-v1.tar.gz` | 1964 | 1964 | 0 | 1964 | 1964 | 0 | 0 |
| `confirmatory-skew-v1.tar.gz` | 48 | 48 | 0 | 48 | 48 | 0 | 0 |
| `repeatability-v1.tar.gz` | 328 | 328 | 0 | 328 | 328 | 0 | 0 |
| `stats-ceb-full-no-refit-v1.tar.gz` | 133 | 130 | 3 | 130 | 132 | 0 | 0 |
| `stats-ceb-semantic-v2b-holdout.tar.gz` | 12 | 12 | 0 | 12 | 12 | 0 | 0 |

## Findings and explicit gaps

### COL-001 [positive] The packaged canonical indexes preserve the query-to-plan-to-region-to-worker graph

**Disposition:** verified

Across standard logical archives, query IDs are unique, features are one-to-one, each query has one main plan, and worker plan IDs resolve to regional plan IDs.

**Recommendation:** Retain these checks as release gates.

Evidence: `master-regimes/src/master_regimes/extract/query_sweep_index.py:487`, `master-thesis-final/artifacts/results/collector-correctness-v2/collector_correctness_summary.json:1`

### COL-002 [positive] Missing, unavailable, and not-applicable evidence are not collapsed into numeric zero

**Disposition:** verified

The index can distinguish absence caused by execution structure from an unexpected collector gap.

**Recommendation:** Keep status columns alongside all derived numeric features.

Evidence: `master-regimes/src/master_regimes/extract/query_sweep_index.py:2178`, `master-regimes/src/master_regimes/extract/query_sweep_index.py:2189`

### COL-003 [positive] Attempt and slot identities support crash-safe resume and deterministic consolidation

**Disposition:** verified

Completed attempts outrank failed or missing attempts, while physical attempts remain auditable.

**Recommendation:** Preserve both query_attempts.csv and resolved_query_status.csv in every public logical run.

Evidence: `master-regimes/src/master_regimes/corpus_adapter.py:554`, `master-regimes-infra/common-scripts/run_query_collection_sweep.py:471`, `master-regimes-infra/common-scripts/index_corpus_run_attempts.py:508`

### COL-004 [medium] Regional auto_explain attribution is window-scoped but not parser-enforced by application name

**Disposition:** open limitation

The runner creates a unique FDW application name, but the indexer ingests every auto_explain document in the captured log suffix. The link is strong only under the declared serial, controlled workload; concurrent regional statements could be misattributed.

**Recommendation:** Persist the PostgreSQL log prefix fields and filter documents by application_name, backend PID, or a query marker before claiming production-grade correlation.

Evidence: `master-regimes-infra/common-scripts/run_query_collection.py:892`, `master-regimes-infra/common-scripts/run_query_collection.py:1077`, `master-regimes/src/master_regimes/extract/query_sweep_index.py:505`

### COL-005 [medium] Result equivalence uses a follow-up SQL execution and the package exposes hashes, not raw rows

**Disposition:** open limitation

The published equality hashes are internally consistent, but they are produced by a second execution after EXPLAIN ANALYZE. Most raw-attempt archives contain neither signature artifacts nor result rows, so an external reader cannot recompute those hashes from the release alone.

**Recommendation:** Describe this as same-SQL/same-context follow-up validation, and package signature JSON or bounded typed result snapshots for representative cases.

Evidence: `master-regimes-infra/common-scripts/run_query_collection.py:1834`, `psql-benchmarks/src/psql_benchmarks/psql.py:138`, `master-thesis-final/releases/feedback-loop-execution-v1/main/result_equivalence_audit.csv:1`

### COL-006 [medium] OS, network, disk, and VPS steal samples are host-level ambient context

**Disposition:** accepted limitation

Query-window alignment narrows time, but counters still include PostgreSQL background work, other processes, shared interfaces, and hypervisor scheduling. cpu_steal_pct is denied guest CPU time, not SQL CPU consumption.

**Recommendation:** Use these fields only as ambient infrastructure context unless future collection adds PID/cgroup/eBPF attribution.

Evidence: `psql-benchmarks/src/psql_benchmarks/os_sampler.py:20`, `psql-benchmarks/src/psql_benchmarks/os_sampler.py:301`, `master-regimes/src/master_regimes/extract/query_sweep_index.py:1639`

### COL-007 [low] Malformed regional auto_explain JSON is silently discarded

**Disposition:** open gap

Expected-region checks may reveal a missing required plan, but malformed extra/internal documents disappear without a parse-failure row or source offset.

**Recommendation:** Emit a parse-error record with host, log path, line range, and document hash.

Evidence: `master-regimes/src/master_regimes/extract/query_sweep_index.py:459`

### COL-008 [low] Logical retry identity omits the concrete target host

**Disposition:** contract assumption

The key includes target_group, condition, instance, and repetition but not target_host/coordinator. Intended manifests keep the host stable, yet an accidental rerun on another coordinator in the same group could be merged.

**Recommendation:** Add target_host or a topology/coordinator identity to the logical key, or validate it as an immutable context field before resolution.

Evidence: `master-regimes-infra/common-scripts/index_corpus_run_attempts.py:168`

### COL-009 [medium] The release snapshots implementation code but does not prove the exact run-time commit

**Disposition:** open provenance gap

The package is sufficient to inspect current/snapshotted implementation and recorded indexes, but several protocol values are reconstructed_from_versioned_config and the run-time commit policy says not_recorded unless explicitly persisted.

**Recommendation:** Do not describe the package as bit-identical run provenance. Persist repository commits and dirty-state patches in every future execution manifest.

Evidence: `master-thesis-final/reproducibility/source-provenance.csv:1`, `master-thesis-final/artifacts/results/experimental-reproducibility-v2/source_manifest.json:1`, `master-thesis-final/artifacts/results/experimental-reproducibility-v2/collection_protocol.csv:1`

### COL-010 [low] One specialized logical archive is not a full collector index

**Disposition:** explicit packaging gap

The pressure N3 holdout archive has query/features/region/worker tables but no plan_files, query_attempts, or resolved_query_status tables. It supports downstream feature audit, not a complete retry/main-plan audit by itself.

**Recommendation:** Label specialized derived indexes explicitly and provide a manifest linking them to their raw-attempt source archive and canonical logical run.

Evidence: `master-thesis-final/artifacts/logical-indexes/pressure-raw-v1-n3-colocation-holdout.tar.gz:1`

## Public audit sufficiency

The package is sufficient to audit the archived relational graph for the canonical corpus runs: rendered SQL, GAC plans, regional log windows, normalized regional/worker tables, attempt tables, resolution tables, source snapshots, checksums, and a stratified manual audit are present. The independent validator reproduced key one-to-one and parent/child invariants.

It is not sufficient for three stronger claims: (1) production-safe regional statement attribution under concurrent load, (2) independent recomputation of most published result hashes from raw result rows, and (3) proof that the packaged source snapshot is exactly the unmodified code used at run time. The host-level telemetry also cannot attribute CPU, network, or disk consumption to one SQL process.

The 24-row manual review is documented as deterministic stratified sampling, not a probability sample. It supports spot validation but is not a statistical estimate of collector error rate.

## Reproduction

```bash
python3 reproducibility/audits/collector/audit.py
python3 reproducibility/audits/collector/audit.py --full-hash
```

The first command verifies audit-critical release hashes and all logical/raw archive invariants. The second additionally verifies every file listed by `artifacts/release-manifest.json`.
