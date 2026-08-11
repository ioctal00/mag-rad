\set ON_ERROR_STOP on

-- Required psql variables:
--   tenant_start
--   tenant_end
--   update_modulo
--   tenant_tier
--   tenant_status
--
-- Example:
-- psql -d app -f sql/experiments/update_tenant_reference_slice.sql \
--   -v tenant_start=1 \
--   -v tenant_end=10000 \
--   -v update_modulo=20 \
--   -v tenant_tier=enterprise \
--   -v tenant_status=active

update tenants
set tenant_tier = :'tenant_tier',
    tenant_status = :'tenant_status',
    updated_at = statement_timestamp(),
    dimension_version = dimension_version + 1
where tenant_id between :tenant_start and :tenant_end
  and tenant_id % :update_modulo = 0;

select
  count(*) as changed_tenants,
  min(updated_at) as min_updated_at,
  max(updated_at) as max_updated_at,
  max(dimension_version) as max_dimension_version
from tenants
where tenant_id between :tenant_start and :tenant_end
  and tenant_id % :update_modulo = 0;
