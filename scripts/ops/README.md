# Ops Scripts

- `backup_sqlite.sh` / `backup_sqlite.ps1`: create compressed SQLite backup.
- `restore_sqlite.sh` / `restore_sqlite.ps1`: restore SQLite backup.
- `ops_guard_check.py`: health + queue guard checks for cron alerting.
- `autoscale_workers.py`: simple queue-driven worker scaling command.
- `publish_queue_metrics_cloudwatch.py`: push queue depth/age metrics to CloudWatch.
- `configure_ecs_queue_autoscaling.py`: configure ECS worker autoscaling from queue alarms.
- `synthetic_flow_check.py`: synthetic auth -> crop -> poll -> download path validation.
- `migrate_sqlite_to_postgres.py`: baseline data migration utility.
- `probe_redis_queue.py`: Redis queue connectivity probe.
- `probe_r2_storage.py`: R2 object storage connectivity probe.
- `canary_gate_check.py`: canary promotion gate check.

