# Incident Playbooks

## Queue stuck / backlog spike

Symptoms:
- queued grows continuously
- oldest queued age crosses SLA

Actions:
1. Check worker logs for crashes.
2. Check `/api/admin/ops/metrics`.
3. Confirm CloudWatch queue metrics are publishing (`QueuedDepth`, `OldestQueuedAgeSec`).
4. Trigger worker scale-out policy or manually raise desired count.
5. If still growing, reduce intake by lowering `MAX_ACTIVE_JOBS_PER_USER` temporarily.

## Worker crash loop

Symptoms:
- worker container restarts repeatedly
- task failures spike

Actions:
1. Inspect latest stack trace.
2. Roll back latest deploy if regression.
3. Verify external dependencies (Redis/R2/DB).
4. Restart worker with last known stable image/config.

## Storage outage / artifact download failures

Symptoms:
- task success but download fails
- missing artifact keys

Actions:
1. Check storage provider status.
2. Verify credentials and bucket policy.
3. Retry object upload/download from shell.
4. Switch to fallback serving mode if available.

## DB saturation / auth failures

Symptoms:
- `/api/ready` failing
- rising API latency / failed auth

Actions:
1. Check DB CPU and connection count.
2. Reduce queue throughput temporarily.
3. Scale DB plan or tune connection pooling.
4. If critical, fail over to previous stable DB endpoint.

## Burst mode / degraded mode toggle

Symptoms:
- queue age keeps rising even after worker scale-out
- completion latency misses SLO for > 15 minutes

Actions:
1. Enable degraded mode by reducing `MAX_ACTIVE_JOBS_PER_USER` (for example 6 -> 2).
2. Keep `DISTRIBUTED_PDF_FANOUT=0` unless queue depth is low and large files dominate.
3. Announce temporary throttling to support team/user comms.
4. Recover by gradually restoring per-user concurrency once queue age is stable.

