with tenant_counts as (
  select count(*) as row_count,
         count(*) filter (where tenant_tier = 'enterprise') as enterprise_tenants,
         count(*) filter (where tenant_status = 'suspended') as suspended_tenants,
         max(dimension_version) as max_dimension_version
  from tenants
),
user_counts as (
  select count(*) as row_count,
         min(users_per_tenant) as min_users_per_tenant,
         max(users_per_tenant) as max_users_per_tenant,
         avg(users_per_tenant)::numeric(20,2) as avg_users_per_tenant
  from (
    select tenant_id, count(*) as users_per_tenant
    from users
    group by tenant_id
  ) u
),
global_user_counts as (
  select count(*) as row_count,
         min(users_per_tenant) as min_global_users_per_tenant,
         max(users_per_tenant) as max_global_users_per_tenant,
         avg(users_per_tenant)::numeric(20,2) as avg_global_users_per_tenant
  from (
    select tenant_id, count(*) as users_per_tenant
    from global_users
    group by tenant_id
  ) gu
),
event_counts as (
  select count(*) as row_count,
         min(events_per_tenant) as min_events_per_tenant,
         max(events_per_tenant) as max_events_per_tenant,
         avg(events_per_tenant)::numeric(20,2) as avg_events_per_tenant
  from (
    select tenant_id, count(*) as events_per_tenant
    from events
    group by tenant_id
  ) e
)
select
  (select row_count from tenant_counts) as tenants,
  (select row_count from user_counts) as users,
  (select row_count from global_user_counts) as global_users,
  (select row_count from event_counts) as events,
  (select enterprise_tenants from tenant_counts) as enterprise_tenants,
  (select suspended_tenants from tenant_counts) as suspended_tenants,
  (select max_dimension_version from tenant_counts) as max_dimension_version,
  (select min_users_per_tenant from user_counts) as min_users_per_tenant,
  (select max_users_per_tenant from user_counts) as max_users_per_tenant,
  (select avg_users_per_tenant from user_counts) as avg_users_per_tenant,
  (select min_global_users_per_tenant from global_user_counts) as min_global_users_per_tenant,
  (select max_global_users_per_tenant from global_user_counts) as max_global_users_per_tenant,
  (select avg_global_users_per_tenant from global_user_counts) as avg_global_users_per_tenant,
  (select min_events_per_tenant from event_counts) as min_events_per_tenant,
  (select max_events_per_tenant from event_counts) as max_events_per_tenant,
  (select avg_events_per_tenant from event_counts) as avg_events_per_tenant;
