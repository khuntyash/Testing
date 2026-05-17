# AWS Burst Runbook (50 Concurrent Jobs)

Use this runbook when queue pressure rises quickly and latency SLOs are at risk.

## Baseline

- API tasks: 2
- Worker tasks autoscale: 4 -> 50
- `MAX_ACTIVE_JOBS_GLOBAL`: near worker capacity + 20-30% headroom
- `MAX_ACTIVE_JOBS_PER_USER`: 4-8
- `DISTRIBUTED_PDF_FANOUT=0` by default

## 1) Confirm queue pressure

```bash
curl -sS https://api.zerolabelcropper.com/api/admin/ops/metrics \
  -H "Authorization: Bearer <admin_token>"
```

Watch:
- `queue.queued`
- `queue.oldest_queued_age_sec`
- `queue.failed_24h`

## 2) Confirm autoscaling path is healthy

```bash
python scripts/ops/publish_queue_metrics_cloudwatch.py \
  --base-url https://api.zerolabelcropper.com \
  --token "<admin_token>" \
  --region ap-south-1 \
  --cluster cropperhub-cluster \
  --service cropperhub-worker-svc
```

```bash
python scripts/ops/configure_ecs_queue_autoscaling.py \
  --region ap-south-1 \
  --cluster cropperhub-cluster \
  --service cropperhub-worker-svc \
  --min-capacity 4 \
  --max-capacity 50 \
  --depth-up-threshold 25 \
  --age-up-threshold 120 \
  --depth-down-threshold 4
```

## 3) Emergency degraded mode (temporary)

When queue age keeps growing:

- Lower `MAX_ACTIVE_JOBS_PER_USER` (for example `6 -> 2`)
- Keep global cap steady to protect existing backlog throughput
- Keep fan-out disabled unless backlog is mostly giant PDFs and queue depth is low

## 4) Recovery criteria

Recover normal limits only when:

- `oldest_queued_age_sec < 120` for 15+ minutes
- failure rate normalizes
- synthetic flow check passes repeatedly

## 5) Post-incident checklist

- Attach queue/age/error graphs to incident notes
- Capture which limit changes were made and when reverted
- Update alarm thresholds if scaling reacted too slowly or oscillated
