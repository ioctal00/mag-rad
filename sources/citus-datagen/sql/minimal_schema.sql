\if :{?datagen_shard_count}
select set_config('citus.shard_count', :'datagen_shard_count', false);
\endif

create table if not exists tenants (
  tenant_id bigint primary key,
  region text not null,
  tenant_tier text not null default 'standard',
  tenant_status text not null default 'active',
  updated_at timestamptz not null default now(),
  dimension_version bigint not null default 1
);

alter table tenants
  add column if not exists tenant_tier text not null default 'standard',
  add column if not exists tenant_status text not null default 'active',
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists dimension_version bigint not null default 1;

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

do $$
begin
  if not exists (
    select 1
    from pg_dist_partition
    where logicalrelid = 'tenants'::regclass
  ) then
    perform create_reference_table('tenants');
  end if;

  if not exists (
    select 1
    from pg_dist_partition
    where logicalrelid = 'events'::regclass
  ) then
    perform create_distributed_table('events', 'tenant_id');
  end if;

  if not exists (
    select 1
    from pg_dist_partition
    where logicalrelid = 'users'::regclass
  ) then
    perform create_distributed_table('users', 'tenant_id', colocate_with => 'events');
  end if;

  if not exists (
    select 1
    from pg_dist_partition
    where logicalrelid = 'global_users'::regclass
  ) then
    perform create_distributed_table('global_users', 'user_id');
  end if;
end $$;

create index if not exists idx_events_tenant_created_at
  on events (tenant_id, created_at);

create index if not exists idx_users_tenant_segment
  on users (tenant_id, user_segment);

create index if not exists idx_global_users_user_tenant
  on global_users (user_id, tenant_id);

create index if not exists idx_global_users_tenant_segment
  on global_users (tenant_id, user_segment);
