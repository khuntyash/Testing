# Monitoring Setup (Phase 1)

## Minimum checks

- Health endpoint: `GET /api/health`
- Ready endpoint: `GET /api/ready`
- Queue metrics: `GET /api/admin/ops/metrics`
- Queue metrics to watch: `queued`, `running`, `oldest_queued_age_sec`, `failed_24h`

## Recommended schedule

- Every 1 minute: `scripts/ops/ops_guard_check.py`
- Every 1 minute: `scripts/ops/publish_queue_metrics_cloudwatch.py`
- Every 5 minutes: CPU/memory/disk checks
- Every 24 hours: backup verification check

## Example cron

```bash
* * * * * cd /opt/cropperhub && OPS_BASE_URL=http://127.0.0.1:8000 OPS_BEARER_TOKEN=<admin_token> python scripts/ops/ops_guard_check.py >> /var/log/cropperhub_ops.log 2>&1
* * * * * cd /opt/cropperhub && OPS_BASE_URL=https://api.zerolabelcropper.com OPS_BEARER_TOKEN=<admin_token> AWS_REGION=ap-south-1 ECS_CLUSTER=cropperhub-cluster ECS_WORKER_SERVICE=cropperhub-worker-svc python scripts/ops/publish_queue_metrics_cloudwatch.py >> /var/log/cropperhub_cw_metrics.log 2>&1
```

## Alert routing

- Email + Slack webhook (or PagerDuty)
- Critical alerts only:
  - readiness failure
  - queue saturation
  - oldest queued age breach
  - backup failure
  - disk critical

## Queue-driven ECS scaling

Configure once:

```bash
AWS_REGION=ap-south-1 ECS_CLUSTER=cropperhub-cluster ECS_WORKER_SERVICE=cropperhub-worker-svc \
WORKER_MIN_CAPACITY=4 WORKER_MAX_CAPACITY=50 \
QUEUE_DEPTH_SCALE_UP=25 QUEUE_AGE_SCALE_UP_SEC=120 QUEUE_DEPTH_SCALE_DOWN=4 \
python scripts/ops/configure_ecs_queue_autoscaling.py
```

## Synthetic user-flow check

Run every 10-15 minutes from a trusted runner:

```bash
OPS_BASE_URL=https://api.zerolabelcropper.com \
SYNTHETIC_USER_EMAIL=<synthetic_user_email> \
SYNTHETIC_USER_PASSWORD=<synthetic_user_password> \
SYNTHETIC_INPUT_PDF=/opt/cropperhub/fixtures/smoke.pdf \
python scripts/ops/synthetic_flow_check.py
```
