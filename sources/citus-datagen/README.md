# citus-datagen

Dataset generator for the master-regimes thesis Citus environment.

The generator is intentionally narrow. Its job is not to be a general benchmark-data framework; its job is to make repeatable regional Citus datasets for the `master-regimes` workload and plan-parser pipeline:

- understand FDW, ETL, and merge flows
- play with SQL queries
- inspect `EXPLAIN` plans
- seed a predictable amount of data into the coordinator database

## Current status

The repo currently contains a working CLI plus supporting assets for the current single-region and EU+GAC preparation flow.

Implemented:

- `main.py` CLI entrypoint with `generate`, `load`, and `reset-and-load`
- environment-backed settings loading from `.env.development` and `.env`
- CSV generation for `tenants.csv`, `users.csv`, optional `global_users.csv`, and `events.csv`
- schema bootstrap via [sql/minimal_schema.sql](sql/minimal_schema.sql)
- PostgreSQL load path via `psql` and `\copy`
- C++ `copy_pipe` generator for streaming rows directly into `\copy`
- helper scripts `./bin/load` and `./bin/reset-and-load`
- remote install/env provisioning through `master-regimes-infra` Ansible
- region-to-tenant-range rollout through rendered infra config
- optional non-colocated join stress through `global_users`

## Current target

The generator targets the database created by `master-regimes-infra`:

- infrastructure repository: `../master-regimes-infra`
- database: `app`
- PostgreSQL superuser: `postgres`
- application user: `app`
- direct PostgreSQL port: `5432`
- PgBouncer port: `6432`

For production-like thesis runs, the expected path is:

- the generator is deployed by Ansible to the regional coordinator
- it runs on the node itself
- it generates a region-specific tenant range
- it writes batch files or streams rows through `copy_pipe`
- it loads into PostgreSQL with direct local `psql`

That staged approach is useful because it keeps the first version debuggable:

- generated CSV files can be inspected manually
- failed loads can be retried
- ETL and merge experiments can reuse the same staged files

At the same time, local WSL generation is supported as a development convenience. That is useful when you want to sanity-check output shape without doing a remote deploy first.

## Minimal schema

The current core dataset is still intentionally small, but it now has enough structure for reference staleness and colocated join experiments:

```sql
create table if not exists tenants (
  tenant_id bigint primary key,
  region text not null,
  tenant_tier text not null default 'standard',
  tenant_status text not null default 'active',
  updated_at timestamptz not null default now(),
  dimension_version bigint not null default 1
);

create table if not exists events (
  event_id bigserial,
  tenant_id bigint not null,
  user_id bigint not null,
  value double precision not null,
  created_at timestamptz not null,
  primary key (tenant_id, event_id)
);

create table if not exists users (
  tenant_id bigint not null,
  user_id bigint not null,
  user_segment text not null,
  user_status text not null,
  signup_at timestamptz not null,
  updated_at timestamptz not null,
  primary key (tenant_id, user_id)
);

create table if not exists global_users (
  tenant_id bigint not null,
  user_id bigint not null,
  user_segment text not null,
  user_status text not null,
  home_region text not null,
  signup_at timestamptz not null,
  updated_at timestamptz not null,
  primary key (tenant_id, user_id)
);

select create_reference_table('tenants');
select create_distributed_table('events', 'tenant_id');
select create_distributed_table('users', 'tenant_id', colocate_with => 'events');
select create_distributed_table('global_users', 'user_id');

create index if not exists idx_events_tenant_created_at
  on events (tenant_id, created_at);

create index if not exists idx_users_tenant_segment
  on users (tenant_id, user_segment);

create index if not exists idx_global_users_user_tenant
  on global_users (user_id, tenant_id);
```

Reference SQL lives in [sql/minimal_schema.sql](sql/minimal_schema.sql).

`tenant_id` is the distribution key because it keeps tenant-owned data on the same shard placement. `tenants` is a reference table because it is small lookup data and can be replicated to workers. `events` and `users` are colocated distributed tables, which lets worker-local fact/dimension joins happen inside a regional Citus cluster before the global analytics layer receives partial results. Mutable tenant attributes (`tenant_tier`, `tenant_status`, `updated_at`, `dimension_version`) support stale ETL and eventual-consistency experiments.

`global_users` is an optional sensitivity table controlled by `DATAGEN_ENABLE_GLOBAL_USERS`. It has the same logical `(tenant_id, user_id)` grain as `users`, but is distributed by `user_id`, so joins with `events` intentionally break the `tenant_id` colocation used by the core workload. By default it uses the same per-tenant cardinality as `users`; override `DATAGEN_GLOBAL_USERS_PER_TENANT` when a sweep needs a larger or smaller non-colocated dimension without changing the event/user domain.

## Runtime model

There are two important execution contexts.

### 1. Local development machine

Used for:

- writing and testing the generator
- generating a small local CSV batch for experimentation
- connecting to the remote coordinator from WSL
- using `psql` or DBeaver over TLS

Typical connection:

- host: coordinator public IPv4
- port: `6432`
- database: `app`
- SSL mode: `verify-ca`
- CA file: `../master-regimes-infra/pki/dev-ca/ca.crt`

### 2. Remote node

Used for:

- generating the actual dataset close to the database
- avoiding large client-side uploads
- preparing region-specific slices such as `EU` or `US`

Planned filesystem layout on the node:

- code: `/opt/citus-datagen`
- generated CSV batches: `/var/lib/citus-datagen/generated/<region>/`
- optional logs: `/var/log/citus-datagen/`

## Environment variables

Copy `.env.example` to `.env` and adjust it for the current target.

```bash
cp .env.example .env
```

The main variables for the first version are:

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `PG_BOUNCER_PORT`
- `POSTGRES_SSL_MODE`
- `POSTGRES_SSL_ROOT_CERT`
- `DATAGEN_REGION`
- `DATAGEN_TENANT_START`
- `DATAGEN_TENANT_END`
- `DATAGEN_OUTPUT_DIR`
- `DATAGEN_LOAD_METHOD`

For quick local experiments on WSL, keep the PostgreSQL values as-is if you only want CSV generation, and shrink the dataset with:

- `DATAGEN_TENANT_START=1`
- `DATAGEN_TENANT_END=3`
- `DATAGEN_EVENTS_PER_TENANT=5`
- `DATAGEN_OUTPUT_DIR=generated/local-eu`

The repo already loads environment values from:

- `.env.development`
- `.env`

with `.env` overriding `.env.development`.

## UV workflow

The intended runtime model for the remote node is:

1. clone the repo to `/opt/citus-datagen`
2. run `uv sync`
3. execute one of the helper scripts under `bin/`

The most important scripts are:

- `./bin/load`
- `./bin/reset-and-load`

Both scripts expect `.venv` to already exist, which is why the remote deploy step should always run `uv sync`.

For generation-only experiments, you can also call the CLI directly:

```bash
uv sync
python main.py generate
```

## `psql` usage

### Remote node, local loopback

When the generator runs on the database node itself, use loopback plus direct PostgreSQL:

```bash
PGPASSWORD='<password>' \
psql \
  -h 127.0.0.1 \
  -p 5432 \
  -U postgres \
  -d app
```

TLS is not necessary for same-node loopback traffic in the current setup. Use direct PostgreSQL on `5432` for datagen because schema initialization runs Citus DDL. Keep PgBouncer on `6432` for regular client traffic and local WSL inspection.

### Local WSL machine, remote coordinator over TLS

```bash
export PGHOST='<coordinator-public-ip>'
export PGPORT='6432'
export PGDATABASE='app'
export PGUSER='postgres'
export PGPASSWORD='<password>'
export PGSSLMODE='verify-ca'
export PGSSLROOTCERT='../master-regimes-infra/pki/dev-ca/ca.crt'

psql
```

Or in one line:

```bash
PGPASSWORD='<password>' \
PGSSLMODE='verify-ca' \
PGSSLROOTCERT='../master-regimes-infra/pki/dev-ca/ca.crt' \
psql -h '<coordinator-public-ip>' -p 6432 -U postgres -d app
```

## Loading strategy for the first simple version

The implementation is intentionally boring:

1. generate `tenants.csv`
2. generate `users.csv`
3. optionally generate `global_users.csv`
4. generate `events.csv`
5. create the schema if needed
6. load with `psql` and `\copy`

Helper commands:

```bash
uv sync
./bin/load
```

`DATAGEN_LOAD_METHOD` controls the load path:

- `csv`: generate `tenants.csv`, `users.csv`, optional `global_users.csv`, and `events.csv`, then load all files
- `sql`: use PostgreSQL `generate_series` batches
- `copy_pipe`: stream rows from the compiled C++ generator into `psql \copy`

Useful sizing variables:

- `DATAGEN_EVENTS_PER_TENANT`: fact-table scale
- `DATAGEN_USERS_PER_TENANT`: colocated user dimension scale and the user id range referenced by generated events
- `DATAGEN_GLOBAL_USERS_PER_TENANT`: optional `global_users` scale; defaults to `DATAGEN_USERS_PER_TENANT`

Keep `DATAGEN_GLOBAL_USERS_PER_TENANT` equal to `DATAGEN_USERS_PER_TENANT` for a full one-to-one non-colocated stress table. Larger values add unmatched global users and increase dimension size; smaller values intentionally reduce join coverage and should be documented as a selectivity/sensitivity variant.

## C++ `copy_pipe` generator

The C++ generator lives in [tools/cpp](tools/cpp). It writes CSV rows to stdout without a header and is designed to be piped into PostgreSQL/Citus `COPY`.

Install build/runtime tools on Ubuntu 24.04:

```bash
sudo apt update
sudo apt install -y build-essential make postgresql-client
```

Build it:

```bash
make -C tools/cpp
```

Use it through the normal loader:

```env
DATAGEN_LOAD_METHOD=copy_pipe
DATAGEN_DISTRIBUTION=uniform
```

Then run:

```bash
./bin/load
```

For a simple skewed event allocation:

```env
DATAGEN_LOAD_METHOD=copy_pipe
DATAGEN_DISTRIBUTION=hot_tenants
DATAGEN_HOT_TENANT_PCT=1
DATAGEN_HOT_EVENT_PCT=50
```

This means roughly 1% of tenants receive roughly 50% of generated events. The total event count remains `tenant_count * DATAGEN_EVENTS_PER_TENANT`.

If the tables already contain data and you explicitly want a rebuild:

```bash
uv sync
./bin/reset-and-load
```

Example load flow:

```bash
psql -h 127.0.0.1 -p 5432 -U postgres -d app -f sql/minimal_schema.sql

psql -h 127.0.0.1 -p 5432 -U postgres -d app \
  -c "\\copy tenants (tenant_id, region, tenant_tier, tenant_status, updated_at, dimension_version) from '/var/lib/citus-datagen/generated/eu/tenants.csv' csv header"

psql -h 127.0.0.1 -p 5432 -U postgres -d app \
  -c "\\copy users (tenant_id, user_id, user_segment, user_status, signup_at, updated_at) from '/var/lib/citus-datagen/generated/eu/users.csv' csv header"

psql -h 127.0.0.1 -p 5432 -U postgres -d app \
  -c "\\copy global_users (tenant_id, user_id, user_segment, user_status, home_region, signup_at, updated_at) from '/var/lib/citus-datagen/generated/eu/global_users.csv' csv header"

psql -h 127.0.0.1 -p 5432 -U postgres -d app \
  -c "\\copy events (event_id, tenant_id, user_id, value, created_at) from '/var/lib/citus-datagen/generated/eu/events.csv' csv header"
```

## Local WSL experiment flow

The intended real execution target is still the remote node, but a small local generation run is useful while iterating on the generator.

Example:

```bash
cp .env.example .env
```

Then set a tiny dataset in `.env`:

```env
DATAGEN_REGION=eu
DATAGEN_TENANT_START=1
DATAGEN_TENANT_END=3
DATAGEN_EVENTS_PER_TENANT=5
DATAGEN_OUTPUT_DIR=generated/local-eu
```

Generate files locally:

```bash
uv sync
python main.py generate
```

Expected output:

- `generated/local-eu/tenants.csv`
- `generated/local-eu/users.csv`
- `generated/local-eu/global_users.csv` when `DATAGEN_ENABLE_GLOBAL_USERS=true`
- `generated/local-eu/events.csv`

This path does not require a running PostgreSQL connection because `generate` only writes CSV files. Database connectivity is only needed for `load` and `reset-and-load`.

## Region-specific tenant ranges

The generator is expected to receive a region plus tenant boundaries from Ansible. For example:

- EU node: `DATAGEN_REGION=eu`, `DATAGEN_TENANT_START=1`, `DATAGEN_TENANT_END=1000`
- US node: `DATAGEN_REGION=us`, `DATAGEN_TENANT_START=1001`, `DATAGEN_TENANT_END=2000`

That keeps the first version deterministic and easy to reason about.

## Role in the current thesis workflow

`citus-datagen` is not the workload catalog and it is not the run evidence store. The current boundary is:

```text
citus-datagen -> dataset tables and dataset metadata
master-regimes -> workload templates, query instances, feature extraction
master-regimes-infra -> remote deploy, reset-and-load, query/database sweeps
```

Recommended next steps:

- keep dataset profiles controlled by `master-regimes` / `master-regimes-infra` sweep config;
- add post-load validation output when a new dataset capability is introduced;
- keep `global_users` enabled for non-colocated join stress profiles where the workload suite needs it;
- avoid adding query templates here; put them in `../master-regimes/workloads/templates/`.

More detailed notes live in [docs/minimal-dataset.md](docs/minimal-dataset.md).
