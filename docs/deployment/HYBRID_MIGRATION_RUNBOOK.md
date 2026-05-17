# Hybrid Migration Runbook (Phase 2)

This runbook migrates from single-node SQLite/local artifacts to hybrid-ready backends.

## Migration order

1. Enable runtime visibility only (`DB_BACKEND=sqlite`, `QUEUE_BACKEND=sqlite`, `STORAGE_BACKEND=local`)
2. Prepare Postgres and validate connectivity (`DB_BACKEND=postgres` in staging)
3. Prepare Redis queue and validate enqueue/dequeue health
4. Prepare R2 bucket and object access
5. Cut over by feature flags in staging, then production

## Pre-checks

- All containers healthy
- `/api/admin/ops/runtime` returns expected backend modes
- Backup completed within last 24h
- Restore drill passed in last 7 days

## Rollback rule

If any migration step causes:
- job enqueue failures
- download failures
- wallet/auth inconsistency

Then immediately revert runtime flags to previous values and restart API+worker.

## Validation checklist per subsystem

### DB cutover

- Can login/signup/auth-me
- Can create crop job and persist metrics
- Wallet credit/spend works
- Admin pages load without query errors

### Queue cutover

- New tasks enter queue
- Worker dequeues and updates status
- No duplicate task executions
- Queue lag within SLO

### Storage cutover

- Artifacts upload successfully
- Download links resolve correctly
- Retention cleanup does not remove active files

