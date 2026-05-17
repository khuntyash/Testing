# Hybrid Cutover Runbook (Phase 3)

Target topology:
- Frontend: Vercel
- API: Render/Railway
- Queue: Redis
- Workers: VPS cluster
- Storage: R2
- DB: Postgres

## Cutover strategy

Use staged rollout with strict gates:

1. 10% traffic
2. 50% traffic
3. 100% traffic

Do not move to next step until current stage is stable for at least 30 minutes.

## Stage checks

- `5xx` error rate < 1%
- p95 queue wait under target
- no worker crash loops
- successful artifact download checks
- wallet/transaction writes remain consistent

## Rollback plan

If stage fails:

1. Stop traffic increase
2. Route all traffic to previous stable API deployment
3. Freeze queue intake briefly
4. Drain/verify running jobs
5. Restore prior runtime flags and restart API/worker

## Post-cutover verification

- Full E2E crop flow (meesho + flipkart sample)
- Dashboard totals update
- Wallet deductions and admin credits remain accurate
- Historical job downloads remain accessible

