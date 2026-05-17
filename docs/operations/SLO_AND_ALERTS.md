# SLO and Alert Baseline

This baseline is the minimum operational contract before opening production traffic.

## Service level objectives

- API availability: 99.9% (30-day rolling)
- Successful crop completion rate: >= 99.5%
- p95 crop queue wait time: <= 120 seconds
- p95 task completion time (standard jobs): <= 15 minutes
- Worker error rate: <= 1% over 15 minutes
- Data recovery objective (RPO): <= 24 hours
- Recovery objective (RTO): <= 60 minutes

## Alert thresholds

- API `/api/ready` failing for 2 consecutive checks
- CPU > 85% for 10 minutes
- Memory > 85% for 10 minutes
- Disk usage > 80% warning, > 90% critical
- Queue `queued > 200` for 10 minutes
- Oldest queued task age > 5 minutes warning, > 15 minutes critical
- Queue `failed_24h > 2%` of total processed
- Synthetic flow check failed 2 times in a row
- Backup run missing in last 24 hours

## Runbook references

- Production deploy: `DEPLOY_PRODUCTION.md`
- Hybrid cutover: `docs/deployment/HYBRID_CUTOVER_RUNBOOK.md`
- Capacity plan: `docs/operations/CAPACITY_WORKSHEET.md`
- AWS burst handling: `docs/operations/AWS_BURST_RUNBOOK.md`
- Backup scripts: `scripts/ops/backup_sqlite.ps1`, `scripts/ops/backup_sqlite.sh`

## Daily checks

- Check `/api/admin/ops/metrics` queue trend
- Validate worker logs for crash loops
- Check CloudWatch `CropperHub/Queue` metrics for depth/age trends
- Confirm free disk headroom > 20%
- Confirm latest backup artifact exists and is non-empty

