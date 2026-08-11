select now() as snapshot_at;

select name,
       setting,
       unit,
       context,
       source
from pg_settings
where name in (
    'citus.enable_stat_counters',
    'citus.stat_tenants_track',
    'citus.force_max_query_parallelization',
    'citus.max_cached_conns_per_worker',
    'citus.max_shared_pool_size',
    'citus.local_shared_pool_size',
    'citus.node_connection_timeout'
)
order by name;

select table_name,
       citus_table_type,
       distribution_column,
       colocation_id,
       table_size,
       shard_count,
       table_owner,
       access_method
from citus_tables
order by table_name;

select nodename,
       nodeport,
       role,
       active
from citus_nodes
order by role, nodename, nodeport;

select nodeid,
       groupid,
       nodename,
       nodeport,
       noderack,
       isactive,
       noderole,
       nodecluster,
       shouldhaveshards
from pg_dist_node
order by nodename, nodeport;

select logicalrelid::regclass as table_name,
       partmethod,
       partkey,
       colocationid,
       repmodel
from pg_dist_partition
order by table_name;

select colocationid,
       shardcount,
       replicationfactor,
       distributioncolumntype::regtype as distribution_column_type,
       distributioncolumncollation
from pg_dist_colocation
order by colocationid;

select logicalrelid::regclass as table_name,
       shardid,
       shardstorage,
       shardminvalue,
       shardmaxvalue
from pg_dist_shard
order by table_name, shardid;

select p.placementid,
       p.shardid,
       s.logicalrelid::regclass as table_name,
       p.shardstate,
       p.shardlength,
       p.groupid,
       n.nodename,
       n.nodeport,
       n.noderole,
       n.isactive,
       n.shouldhaveshards
from pg_dist_placement p
join pg_dist_shard s on s.shardid = p.shardid
join pg_dist_node n on n.groupid = p.groupid
order by table_name, p.shardid, n.nodename, n.nodeport;

select table_name,
       shardid,
       shard_name,
       citus_table_type,
       colocation_id,
       nodename,
       nodeport,
       shard_size
from citus_shards
order by table_name, shardid, nodename, nodeport;

select table_name,
       citus_table_type,
       nodename,
       nodeport,
       count(*) as shard_placements,
       pg_size_pretty(sum(shard_size)) as total_shard_size,
       min(shard_size) as min_shard_bytes,
       max(shard_size) as max_shard_bytes,
       round(avg(shard_size)::numeric, 2) as avg_shard_bytes
from citus_shards
group by table_name, citus_table_type, nodename, nodeport
order by table_name, nodename, nodeport;

select nodename,
       nodeport,
       count(*) as shard_placements,
       count(*) filter (where citus_table_type = 'distributed') as distributed_placements,
       count(*) filter (where citus_table_type = 'reference') as reference_placements,
       pg_size_pretty(sum(shard_size)) as total_shard_size,
       min(shard_size) as min_shard_bytes,
       max(shard_size) as max_shard_bytes,
       round(avg(shard_size)::numeric, 2) as avg_shard_bytes
from citus_shards
group by nodename, nodeport
order by nodename, nodeport;

select oid as database_oid,
       name,
       connection_establishment_succeeded,
       connection_establishment_failed,
       connection_reused,
       query_execution_single_shard,
       query_execution_multi_shard,
       stats_reset
from citus_stat_counters
where name = current_database()
order by name;

select global_pid,
       nodeid,
       is_worker_query,
       datname,
       pid,
       usename,
       application_name,
       client_addr,
       state,
       wait_event_type,
       wait_event,
       query_start,
       state_change,
       query_id
from citus_dist_stat_activity
where datname = current_database()
order by nodeid, is_worker_query, pid;

select global_pid,
       nodeid,
       is_worker_query,
       datname,
       pid,
       usename,
       application_name,
       client_addr,
       state,
       wait_event_type,
       wait_event,
       query_start,
       state_change,
       query_id
from citus_stat_activity
where datname = current_database()
order by nodeid, is_worker_query, pid;

select waiting_gpid,
       blocking_gpid,
       waiting_nodeid,
       blocking_nodeid
from citus_lock_waits
order by waiting_nodeid, blocking_nodeid;

select schemaname,
       tablename,
       attname,
       null_frac,
       avg_width,
       n_distinct,
       correlation
from pg_stats
where tablename in ('events', 'tenants', 'users', 'global_users')
order by tablename, attname;
