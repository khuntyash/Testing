# Hybrid Environment Setup

This document maps exact variables for:
- Frontend: Vercel
- API: Render (or Railway)
- Workers: VPS
- Shared services: Postgres, Redis, Cloudflare R2

Use this file with `.env.production.hybrid.example`.

## 1) Frontend (Vercel) variables

Set in Vercel Project Settings -> Environment Variables:

- `VITE_API_URL=https://api.yourdomain.com`

Optional Firebase client vars (only if used by your frontend flow):

- `VITE_FIREBASE_API_KEY`
- `VITE_FIREBASE_AUTH_DOMAIN`
- `VITE_FIREBASE_PROJECT_ID`
- `VITE_FIREBASE_APP_ID`

## 2) API (Render/Railway) variables

Set these on managed API service:

- `DB_BACKEND=postgres`
- `QUEUE_BACKEND=redis`
- `STORAGE_BACKEND=s3`
- `API_PLATFORM=render` (or `railway`)
- `DISABLE_EMBEDDED_WORKER=1`
- `CORS_ORIGINS=https://your-frontend-domain.vercel.app,https://your-custom-domain.com`
- `ADMIN_EMAILS=admin@yourdomain.com`
- `DATABASE_URL=postgresql://...`
- `REDIS_URL=redis://...`
- `REDIS_QUEUE_NAME=labelhub:tasks`
- `S3_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com`
- `S3_REGION=auto`
- `S3_BUCKET=<bucket-name>`
- `S3_ACCESS_KEY_ID=<key>`
- `S3_SECRET_ACCESS_KEY=<secret>`
- `S3_PREFIX=labelhub/prod`

Recommended limits:

- `MAX_ACTIVE_JOBS_GLOBAL=400`
- `MAX_ACTIVE_JOBS_PER_USER=10`
- `STALE_JOB_MINUTES=20`
- `DOWNLOAD_RETENTION_HOURS=24`
- `FAIL_ORPHAN_RUNNING_TASKS_ON_STARTUP=true`

## 3) Worker (VPS) variables

Workers must use exactly the same backend/service vars as API:

- `DB_BACKEND`, `QUEUE_BACKEND`, `STORAGE_BACKEND`
- `DATABASE_URL`, `REDIS_URL`
- `S3_*`
- `REDIS_QUEUE_NAME`
- `REDIS_ACTIVE_WORKER_TTL_SEC` (worker heartbeat TTL for active-worker metrics)
- `REDIS_QUEUE_METRICS_ENABLE_DEEP_SCAN` (`0` recommended; enable only for occasional counter reconciliation)
- `WORKER_RUNTIME_METRICS_INTERVAL_SEC` (worker memory/temp sampling interval)
- `QUEUE_STUCK_WARN_SEC` (queue-age threshold used for stuck warning signal)
- `WORKER_IDLE_SLEEP_SEC=0.4`
- `WORKER_LOG_LEVEL=INFO`
- `TASK_LEASE_SECONDS=7200`
- `TASK_LEASE_HEARTBEAT_SEC=60`
- `WORKER_PROFILE` (`realtime` / `bulk` / `balanced`)
- `WORKER_QUEUE_ROLE` (`realtime` / `bulk` / `all`)
- `OCR_EXECUTOR_MODE` (`thread` or `process`)
- `OCR_ISOLATION_MODE` (`auto` / `thread` / `process` / `task_process`)
- `OCR_PROCESS_RECYCLE_LIMIT` (max OCR child tasks before process recycle)
- `OCR_CHILD_TIMEOUT_SEC` (per-file OCR child timeout)
- `WORKER_MAX_TASKS_PER_PROCESS` (optional worker self-recycle guard)
- `OCR_STREAMING_ENABLED` (`1` to stream PDF processing in bounded batches)
- `OCR_PAGE_BATCH_SIZE` (max pages loaded per OCR batch)
- `PDF_RENDER_WINDOW` (sub-window size within each batch for render/OCR loops)
- `OCR_CPU_AFFINITY_ENABLED` (`1` to pin worker process CPU affinity on Linux)
- `OCR_CPU_CORE_GROUPS` (semicolon list, e.g. `role:realtime:0-7;role:bulk:8-15;all:0-15`)
- `OCR_MAX_ACTIVE_PROCESSES` (global/process-profile cap used for OCR process concurrency)
- `WORKER_TEMP_PREFER_RAMDISK=1`
- `WORKER_TEMP_RAMDISK_PATH=/dev/shm`
- `WORKER_TEMP_SUBDIR=cropperhub-worker`
- `WORKER_TEMP_LOG_SELECTION=1`
- optional: `WORKER_TEMP_DIR=/mnt/nvme0n1/tmp/cropperhub` (preferred on NVMe)

Worker-specific:

- keep `DISABLE_EMBEDDED_WORKER=1`
- run using `python worker.py` from `backend`
- prefer split topology:
  - realtime workers: `WORKER_QUEUE_ROLE=realtime`, `WORKER_PROFILE=realtime`, `OCR_EXECUTOR_MODE=thread`
  - bulk OCR workers: `WORKER_QUEUE_ROLE=bulk`, `WORKER_PROFILE=bulk`, `OCR_EXECUTOR_MODE=process`, `OCR_ISOLATION_MODE=process`

## 4) Quick startup flow

1. Copy template:
   - `cp .env.production.hybrid.example .env.production`
2. Fill all placeholder values.
3. API deploy:
   - Render/Railway using `deploy/hybrid/render.yaml` or `deploy/hybrid/railway.toml`
4. Worker deploy (VPS):
   - legacy compose: `docker compose -f deploy/hybrid/docker-compose.worker.yml --env-file .env.production up -d`
   - production-tuned compose (recommended): `docker compose -f docker-compose.worker.yml --env-file .env.production up -d`
   - services include `worker-realtime` and `worker-bulk`
   - role tuning env files:
     - `deploy/hybrid/env/worker.common.env`
     - `deploy/hybrid/env/worker.realtime.env`
     - `deploy/hybrid/env/worker.bulk.env`
     - `deploy/hybrid/env/worker.cpu-pinning.env`
5. Validate:
   - `GET /api/ready`
   - `GET /api/admin/ops/runtime`
   - Run:
     - `python scripts/ops/probe_redis_queue.py`
     - `python scripts/ops/probe_r2_storage.py`
    - `python scripts/ops/benchmark_capacity_matrix.py --base-url https://api.yourdomain.com --clients "20,40,80"`

## 5) Security notes

- Never commit real secrets.
- Rotate Postgres/Redis/R2 credentials periodically.
- Keep worker VPS firewall strict (only required inbound ports).
- Use HTTPS only for frontend and API domains.
