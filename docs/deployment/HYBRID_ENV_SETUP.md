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
- `WORKER_IDLE_SLEEP_SEC=0.4`
- `WORKER_LOG_LEVEL=INFO`

Worker-specific:

- keep `DISABLE_EMBEDDED_WORKER=1`
- run using `python worker.py` from `backend`

## 4) Quick startup flow

1. Copy template:
   - `cp .env.production.hybrid.example .env.production`
2. Fill all placeholder values.
3. API deploy:
   - Render/Railway using `deploy/hybrid/render.yaml` or `deploy/hybrid/railway.toml`
4. Worker deploy (VPS):
   - `docker compose -f deploy/hybrid/docker-compose.worker.yml --env-file .env.production up -d`
5. Validate:
   - `GET /api/ready`
   - `GET /api/admin/ops/runtime`
   - Run:
     - `python scripts/ops/probe_redis_queue.py`
     - `python scripts/ops/probe_r2_storage.py`

## 5) Security notes

- Never commit real secrets.
- Rotate Postgres/Redis/R2 credentials periodically.
- Keep worker VPS firewall strict (only required inbound ports).
- Use HTTPS only for frontend and API domains.
