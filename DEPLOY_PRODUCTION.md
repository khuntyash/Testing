# Production Deployment Guide (Low-Cost Growth Plan)

This guide deploys the current system safely and keeps cost increases gradual as users and processing load grow.

## 1) What this deploy setup includes

- `docker-compose.prod.yml`
  - `web` (Nginx + built frontend)
  - `api` (FastAPI)
  - `worker` (background crop processor)
- `backend/Dockerfile` with OCR dependencies (Tesseract)
- `Dockerfile.web` for frontend build + Nginx runtime
- `deploy/nginx/default.conf` reverse proxy + SPA fallback
- `.env.production.example` runtime configuration template
- `docs/operations/SLO_AND_ALERTS.md` SLO and alert thresholds
- `docs/deployment/LAUNCH_CHECKLIST.md` go-live checklist
- `scripts/ops/*` backup/restore/ops guard/autoscaling scripts
- `deploy/hybrid/*` manifests for phase-3 hybrid cutover

## 2) Server recommendation for launch

- 1 Ubuntu VPS (4 vCPU, 8 GB RAM, NVMe SSD)
- Docker + Docker Compose plugin installed
- Domain pointed to server IP

This is enough for launch while keeping monthly cost controlled.

## 3) First-time deployment steps

```bash
# On server
git clone <your-repo-url> app
cd app

cp .env.production.example .env.production
# Edit values inside .env.production (domain/admin email/etc)

docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api
```

## 4) SSL (recommended)

Use Cloudflare proxy or set up a TLS terminator (for example Caddy/Nginx with certbot) in front of this stack.

If you deploy behind `https://your-domain.com`, set:

- `CORS_ORIGINS=https://your-domain.com`

in `.env.production` and restart:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## 5) Cost-growth plan (increase little by little)

### Stage A: Launch (lowest cost)
- 1 API container + 1 Worker container
- 1 VPS (4 vCPU / 8 GB)

### Stage B: Small growth (minimal extra cost)
- Add one more worker replica:

```bash
docker compose -f docker-compose.prod.yml up -d --scale worker=2
```

- Keep same VPS if CPU allows.
- This gives more parallel processing with little/no infra architecture change.

### Stage C: Medium growth
- Increase to 3 workers:

```bash
docker compose -f docker-compose.prod.yml up -d --scale worker=3
```

- If average CPU stays >80%, move to next VPS size (small incremental step).

### Stage D: High growth
- Upgrade VPS class and keep scaling workers gradually.
- At sustained high load, move to Postgres + external queue as a phase-2 architecture.

## 6) Recommended scaling trigger rules

Check every day:

- Queue backlog from `/api/admin/ops/metrics`
- Worker CPU usage
- Average job wait time

Scale up by +1 worker when:

- queue `queued` stays high for 10+ minutes, or
- average wait becomes user-visible/unacceptable.

Scale down by -1 worker when:

- queue stays near zero for most of the day and CPU is low.

This keeps cost increases small and demand-driven.

## 7) Operational commands

```bash
# status
docker compose -f docker-compose.prod.yml ps

# logs
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f worker

# restart services
docker compose -f docker-compose.prod.yml restart

# rolling update after git pull
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

## 8) Backup (mandatory)

Your SQLite DB is stored in Docker volume `app_data`.

At minimum:
- Daily snapshot/backup of Docker volumes
- Keep at least 7 daily backups + 4 weekly backups

## 9) Notes for current architecture

- This app currently uses SQLite + local artifact storage.
- For current codebase, keep one API instance and scale workers gradually.
- Multi-node distributed scaling should be done after migrating to Postgres + external queue.

## 10) Hybrid migration references

When moving to Vercel + managed API + VPS workers, follow:

- `docs/deployment/HYBRID_MIGRATION_RUNBOOK.md`
- `docs/deployment/HYBRID_CUTOVER_RUNBOOK.md`
- `docs/operations/ENVIRONMENT_MATRIX.md`
- `docs/operations/INCIDENT_PLAYBOOKS.md`
- `docs/operations/CAPACITY_WORKSHEET.md`

Useful scripts:

- `python scripts/ops/ops_guard_check.py`
- `python scripts/ops/autoscale_workers.py`
