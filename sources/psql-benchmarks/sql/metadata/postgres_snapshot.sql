select pg_stat_clear_snapshot();

select now() as snapshot_at;

select name, setting, unit
from pg_settings
where name in (
  'shared_buffers',
  'work_mem',
  'maintenance_work_mem',
  'effective_cache_size',
  'max_connections',
  'idle_session_timeout',
  'statement_timeout',
  'stats_fetch_consistency',
  'track_activities',
  'track_counts',
  'track_io_timing',
  'track_wal_io_timing',
  'compute_query_id',
  'shared_preload_libraries'
)
order by name;

select datname,
       numbackends,
       xact_commit,
       xact_rollback,
       blks_read,
       blks_hit,
       case
         when blks_read + blks_hit = 0 then null
         else round((blks_hit::numeric / (blks_read + blks_hit)) * 100, 3)
       end as buffer_cache_hit_pct,
       tup_returned,
       tup_fetched,
       tup_inserted,
       tup_updated,
       tup_deleted,
       temp_files,
       temp_bytes,
       deadlocks,
       blk_read_time,
       blk_write_time,
       session_time,
       active_time,
       idle_in_transaction_time,
       sessions,
       sessions_abandoned,
       sessions_fatal,
       sessions_killed,
       parallel_workers_to_launch,
       parallel_workers_launched,
       stats_reset
from pg_stat_database
where datname = current_database();

select buffers_clean,
       maxwritten_clean,
       buffers_alloc,
       stats_reset
from pg_stat_bgwriter;

select num_timed,
       num_requested,
       restartpoints_timed,
       restartpoints_req,
       restartpoints_done,
       write_time,
       sync_time,
       buffers_written,
       stats_reset
from pg_stat_checkpointer;

select wal_records,
       wal_fpi,
       wal_bytes,
       wal_buffers_full,
       stats_reset
from pg_stat_wal;

select backend_type,
       object,
       context,
       reads,
       read_bytes,
       read_time,
       writes,
       write_bytes,
       write_time,
       writebacks,
       writeback_time,
       extends,
       extend_bytes,
       extend_time,
       hits,
       evictions,
       reuses,
       fsyncs,
       fsync_time,
       stats_reset
from pg_stat_io
order by backend_type, object, context;

select relid::regclass as table_name,
       seq_scan,
       seq_tup_read,
       idx_scan,
       idx_tup_fetch,
       n_live_tup,
       n_dead_tup,
       n_mod_since_analyze,
       last_vacuum,
       last_autovacuum,
       last_analyze,
       last_autoanalyze,
       vacuum_count,
       autovacuum_count,
       analyze_count,
       autoanalyze_count
from pg_stat_user_tables
where relname in ('events', 'tenants', 'users', 'global_users')
order by relname;

select relid::regclass as table_name,
       indexrelid::regclass as index_name,
       idx_scan,
       idx_tup_read,
       idx_tup_fetch,
       last_idx_scan
from pg_stat_user_indexes
where relname in ('events', 'tenants', 'users', 'global_users')
order by relname, indexrelname;

select relid::regclass as table_name,
       heap_blks_read,
       heap_blks_hit,
       case
         when heap_blks_read + heap_blks_hit = 0 then null
         else round((heap_blks_hit::numeric / (heap_blks_read + heap_blks_hit)) * 100, 3)
       end as heap_hit_pct,
       idx_blks_read,
       idx_blks_hit,
       case
         when idx_blks_read + idx_blks_hit = 0 then null
         else round((idx_blks_hit::numeric / (idx_blks_read + idx_blks_hit)) * 100, 3)
       end as index_hit_pct,
       toast_blks_read,
       toast_blks_hit,
       tidx_blks_read,
       tidx_blks_hit
from pg_statio_user_tables
where relname in ('events', 'tenants', 'users', 'global_users')
order by relname;

select relid::regclass as table_name,
       indexrelid::regclass as index_name,
       idx_blks_read,
       idx_blks_hit,
       case
         when idx_blks_read + idx_blks_hit = 0 then null
         else round((idx_blks_hit::numeric / (idx_blks_read + idx_blks_hit)) * 100, 3)
       end as index_hit_pct
from pg_statio_user_indexes
where relname in ('events', 'tenants', 'users', 'global_users')
order by relname, indexrelname;

select pid,
       usename,
       application_name,
       client_addr,
       state,
       wait_event_type,
       wait_event,
       backend_type,
       query_start
from pg_stat_activity
where datname = current_database()
order by pid;
