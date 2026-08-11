# psql-benchmarks

Benchmark and experiment harness for the thesis PostgreSQL/Citus infrastructure.

This repository is the execution/capture harness. It is intentionally separate from:

- `master-regimes`: canonical workload templates, query instances, indexing, feature extraction, models, and final evidence
- `master-regimes-infra`: infrastructure, Terraform, Ansible, PKI, and remote orchestration
- `citus-datagen`: deterministic dataset generation and loading

Current thesis runs should usually reach this repo through `master-regimes-infra` Make targets. `psql-benchmarks` should not become the canonical SQL template catalog.

## Purpose

`psql-benchmarks` answers: "Given an already provisioned cluster and generated dataset, how do different query/analytics strategies behave?"

The first target dataset is produced by `citus-datagen` and currently contains:

```sql
tenants(
  tenant_id bigint primary key,
  region text not null,
  tenant_tier text not null,
  tenant_status text not null,
  updated_at timestamptz not null,
  dimension_version bigint not null
)

events(
  event_id bigint,
  tenant_id bigint not null,
  user_id bigint not null,
  value double precision not null,
  created_at timestamptz not null,
  primary key (tenant_id, event_id)
)

users(
  tenant_id bigint not null,
  user_id bigint not null,
  user_segment text not null,
  user_status text not null,
  signup_at timestamptz not null,
  updated_at timestamptz not null,
  primary key (tenant_id, user_id)
)

global_users(
  tenant_id bigint not null,
  user_id bigint not null,
  user_segment text not null,
  user_status text not null,
  home_region text not null,
  signup_at timestamptz not null,
  updated_at timestamptz not null,
  primary key (tenant_id, user_id)
)
```

Citus shape:

- `tenants` is a reference table
- `events` is distributed by `tenant_id`
- `users` is distributed by `tenant_id` and colocated with `events`
- `global_users` is optional and distributed by `user_id`, so it is not colocated with `events`
- `events` has `idx_events_tenant_created_at` on `(tenant_id, created_at)`
- `users` has `idx_users_tenant_segment` on `(tenant_id, user_segment)`

That means the first query templates should focus on tenant-scoped and time-windowed access before more complicated cross-region strategies are added. Dataset-v2 also enables three important exploratory shapes: colocated `events/users` joins, stale-reference probes through mutable `tenants` attributes, and optional non-colocated `events/global_users` join stress when `DATAGEN_ENABLE_GLOBAL_USERS=true`.

The historical Stage A query suite is documented in [docs/query-suite.md](docs/query-suite.md). It remains useful background, but new master-regimes workload templates live in:

```text
../master-regimes/workloads/templates/
../master-regimes/workloads/suites/
```

The old core suite intentionally stayed small:

- global rolling KPI
- tenant locality aggregate
- cross-tenant global aggregation
- user Top-K
- fact/reference join
- high-value filter aggregate

Additional exploratory probes cover:

- colocated `events/users` segment join
- mutable tenant reference/staleness probe
- dataset shape sanity check
- optional non-colocated `events/global_users` join stress

## Where this tool runs

The same repository should be deployable to multiple node types, but the mode differs by node.

### Coordinator node

Use for:

- local single-region Citus query benchmarks
- Citus metadata snapshots
- distributed `EXPLAIN` profiling
- baseline SQL workload execution through local PostgreSQL or PgBouncer

Expected path:

```text
/opt/psql-benchmarks
```

### Global analytics client

Use for:

- regional-partial live-federation probes
- FDW/federation client orchestration
- ETL/materialization experiments
- later multi-region benchmark runners

This node is optional and may start as a small 1c VM for demos. It should be resized before serious benchmark runs if it becomes a bottleneck.

## Runtime environment

Target OS:

- Ubuntu 24.04 for final runs
- Ubuntu 22.04 is acceptable during current infrastructure bring-up

Python/tooling:

- Python `>=3.12`
- `uv`
- `psql`
- shell utilities for readable wrappers

System tools expected on benchmark nodes:

- `postgresql-client`
- `sysstat` for `sar`, `iostat`, `pidstat`
- `procps`
- `iproute2`
- `jq`
- `curl`
- `coreutils`
- optional eBPF tools for profiling-only runs

See [docs/toolset.md](docs/toolset.md).

## Configuration

Copy the example environment:

```bash
cp .env.example .env
```

Important variables:

- `BENCH_NODE_ROLE`
- `BENCH_REGION`
- `BENCH_RUN_DIR`
- `BENCH_APPLICATION_NAME`
- `PGHOST`
- `PGPORT`
- `PGDATABASE`
- `PGUSER`
- `PGPASSWORD`
- `PGSSLMODE`
- `PGSSLROOTCERT`

For coordinator-local execution, prefer direct local PostgreSQL:

```env
PGHOST=127.0.0.1
PGPORT=5432
PGSSLMODE=disable
```

For analytics-client or workstation execution, prefer PgBouncer with TLS:

```env
PGHOST=<coordinator-public-or-private-ip>
PGPORT=6432
PGSSLMODE=verify-ca
PGSSLROOTCERT=/opt/psql-benchmarks/certs/ca.crt
```

Certificates should be deployed by infrastructure automation. The stable development CA currently originates from:

```text
../master-regimes-infra/pki/dev-ca/ca.crt
```

## Benchmark modes

The repository grows around explicit modes, not one hidden "do everything" command.

Implemented first-stage/legacy modes:

- `measure-baseline`: run baseline SQL templates, optionally collect low-overhead OS samples, and write timing summaries
- `profile-baseline`: run representative baseline queries with `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)`
- `snapshot-metadata`: capture PostgreSQL/Citus metadata without running workload queries
- `capture-window`: capture PostgreSQL snapshots and OS counters for a fixed time window without running workload SQL

Current master-regimes query collection is driven by:

- `query-capture-start`
- `query-capture-stop`
- `explain-sql`
- `result-snapshot` (bounded typed rows for explicit correctness recovery only)
- `gac-etl-bootstrap`
- `fdw-bootstrap`

`fdw-bootstrap` accepts repeated `--fdw-server-option NAME=VALUE` arguments for safe `postgres_fdw` server options such as `fetch_size`, `use_remote_estimate`, `fdw_startup_cost` and `fdw_tuple_cost`. In the `master-regimes` corpus flow, `fetch_size` interventions must arrive through this flag, usually via `master-regimes-infra` generated sweep `fdw_server_options`.

The normal `core_v1` collection stores SQL input, query bindings, textual `EXPLAIN`, `EXPLAIN ANALYZE ... FORMAT JSON`, query timing, execution manifest, and FDW remote-plan probes when `Remote SQL` appears in the main plan. OS/network sampling and database-stat snapshots are profiling/debug paths, not the default feature contract for the current thesis pipeline.

See [docs/modes.md](docs/modes.md).

## First-stage program flow

Run this only after infrastructure and `citus-datagen` have already prepared the database.

```bash
cp .env.example .env
uv sync
./bin/snapshot-metadata --label before-baseline
./bin/measure-baseline --label first-baseline
./bin/profile-baseline --label explain-first-baseline
```

For manual Stage A investigation on coordinator and workers:

```bash
./bin/capture-window --label a1-manual --duration 60
```

Then run selected Stage A SQL manually from the coordinator while the capture window is active. See [docs/stage-a-manual-telemetry.md](docs/stage-a-manual-telemetry.md).

Each command writes a separate directory under:

```text
runs/<timestamp>-<mode>-<label>/
```

Important files from `measure-baseline`:

- `results/query_timings.csv`: one row per warmup/measurement execution
- `results/query_timing.csv`: legacy single-row compatibility file for the first measurement only
- `results/query_summary.csv`: mean, median, standard deviation, min, max, p95, p99, coefficient of variation
- `results/<query>.result.csv`: sample result from the first measurement execution; later repetitions write to `/dev/null`
- `metrics/os_samples.jsonl`: raw CPU, memory, network, and disk counter samples
- `metrics/os_summary.json`: first/last counter deltas for host-level CPU busy and CPU steal percentages, network bytes, and disk bytes. CPU steal remains a separate VPS scheduling diagnostic and is not query CPU.
- `snapshots/before_*` and `snapshots/after_*`: PostgreSQL/Citus metadata snapshots

Resource metrics describe the machine where `psql-benchmarks` is running. For server-side CPU/I/O/network measurements, run this on the coordinator or analytics node, not only from the local workstation.

The PostgreSQL snapshots are intentionally database-semantic: they answer what PostgreSQL/Citus did. The OS samples are physical: they answer what the machine spent. Keep those layers separate in analysis. For the current master-regimes core workflow, collect these only when a profiling/debug run explicitly asks for them.

PostgreSQL snapshots currently capture:

- relevant PostgreSQL/Citus configuration from `pg_settings`, including all `citus.%` variables and benchmark-sensitive planner, memory, WAL, I/O, statistics, and autovacuum settings
- database-level counters from `pg_stat_database`
- I/O counters from `pg_stat_io`
- table and index usage for `events`, `tenants`, `users`, and optional `global_users`
- table/index buffer hit behavior from `pg_statio_*`
- WAL, background writer, and checkpointer counters
- live activity/wait-event state from `pg_stat_activity`

## Measurement model

Separate these two run types:

- measurement run: low-overhead counters, no eBPF tracing, no `EXPLAIN ANALYZE` in the main loop
- profiling run: one or a few representative executions with `EXPLAIN ANALYZE` and optional eBPF

Baseline sampling:

- OS counters every `1s`
- PostgreSQL/Citus snapshots before and after each run
- one profiling plan per query template
- optional eBPF windows of `10-60s`

Recommended initial sampling:

- `BENCH_SAMPLE_INTERVAL_SECONDS=1` for normal baseline runs
- `BENCH_SAMPLE_INTERVAL_SECONDS=0.25` for short debugging runs where queries finish very quickly
- `BENCH_SAMPLE_INTERVAL_SECONDS=5` for long runs where overhead and output size matter more than fine time resolution

The current sampler reads kernel counters from procfs/sysfs, so overhead should be small. Do not use `EXPLAIN ANALYZE` or eBPF tracing inside the main latency loop; use `profile-baseline` separately.

Use `BENCH_APPLICATION_NAME` to identify benchmark sessions in `pg_stat_activity` and, later, in logs or query-level statistics.

Captured data should go under:

```text
runs/<timestamp>-<mode>-<label>/
```

The `runs/` directory is local output and should not be committed.

## First query templates

Start with simple templates that match the current dataset:

- tenant time-window aggregate
- region aggregate through `tenants` reference table
- top tenants by event count
- global time-window aggregate
- pushdown-friendly vs pushdown-stress variants

Historical SQL examples live in [sql/baseline/](sql/baseline). New thesis workload templates should be added in `../master-regimes/workloads/templates/` and rendered to an `instance_manifest.csv`.

## Non-goals for the first version

Do not start with:

- a full benchmark framework
- permanent eBPF tracing
- complex dashboarding
- automatic statistical analysis
- multi-region orchestration before the single-region baseline is stable

For legacy local benchmarking, the first useful result is a repeatable run directory with:

- query timings
- query timing summary statistics
- SQL text
- run metadata
- PostgreSQL/Citus metadata snapshots
- CPU, storage I/O, and network byte counters

For the current master-regimes pipeline, the useful result is a query/database sweep in `../master-regimes-infra/generated/runs/**` plus a normalized `_index/` created by `master-regimes index-query-sweep` or the database-sweep indexer. Corpus-level terms such as `corpus_cell_id`, `logical_question_id` and `execution_strategy` are defined in `../master-regimes/docs/corpus-vocabulary.md`; this repo should preserve them as metadata when present, not interpret them as benchmark labels.
