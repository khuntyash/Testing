# OCR Worker Deployment (Realtime + Bulk)

This deploys **only external OCR workers** against already-running API, Redis, and Postgres.

## 1) Files used

- `docker-compose.worker.yml`
- `deploy/hybrid/env/worker.common.env`
- `deploy/hybrid/env/worker.realtime.env`
- `deploy/hybrid/env/worker.bulk.env`
- `deploy/hybrid/env/worker.cpu-pinning.env`

## 2) Tune host resources first

- Ensure realtime and bulk CPU sets are disjoint in `deploy/hybrid/env/worker.cpu-pinning.env`.
- Set NVMe temp paths:
  - `WORKER_REALTIME_NVME_TEMP_DIR`
  - `WORKER_BULK_NVME_TEMP_DIR`
- Keep `/dev/shm` available (tmpfs mount is used for fast OCR temp I/O).

## 3) Deploy workers

```bash
docker compose -f docker-compose.worker.yml --env-file .env.production build
docker compose -f docker-compose.worker.yml --env-file .env.production up -d
```

Services:

- `worker-realtime`: thread executor, low latency, smaller OCR concurrency.
- `worker-bulk`: process executor, recycle-enabled, streaming-enabled.

## 4) Verify health + queue split

```bash
docker compose -f docker-compose.worker.yml ps
docker compose -f docker-compose.worker.yml logs worker-realtime --tail=100
docker compose -f docker-compose.worker.yml logs worker-bulk --tail=100
```

Run deployment checks:

```bash
OPS_BASE_URL=https://api.yourdomain.com \
OPS_BEARER_TOKEN=<admin_token> \
python scripts/ops/validate_worker_stack.py
```

Optional throughput run:

```bash
OPS_BASE_URL=https://api.yourdomain.com \
OPS_BEARER_TOKEN=<admin_token> \
python scripts/ops/validate_worker_stack.py --run-throughput --throughput-clients "20,40,80" --min-throughput-success-tps 2.5
```

## 5) Restart behavior and graceful shutdown

- Restart policy: `unless-stopped` (automatic recovery after crash/reboot).
- Realtime stop grace: `90s` (quick drain).
- Bulk stop grace: `300s` (allows longer OCR process completion).
- Bulk worker process recycle:
  - `OCR_PROCESS_RECYCLE_LIMIT=40`
  - `WORKER_MAX_TASKS_PER_PROCESS=80`
