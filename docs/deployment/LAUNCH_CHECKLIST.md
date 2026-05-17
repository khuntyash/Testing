# Launch Checklist (Phase 1)

Use this checklist before opening production traffic.

## Infrastructure

- [ ] Production host provisioned (4+ vCPU, 8+ GB RAM, SSD)
- [ ] DNS configured for frontend/API domain
- [ ] TLS enabled (Cloudflare proxy or certbot fronting reverse proxy)
- [ ] Host firewall allows only `22`, `80`, `443`

## App configuration

- [ ] `.env.production` created from `.env.production.example`
- [ ] `CORS_ORIGINS` set to production frontend domain
- [ ] `ADMIN_EMAILS` set correctly
- [ ] `DISABLE_EMBEDDED_WORKER=1` confirmed
- [ ] Job limits configured (`MAX_ACTIVE_JOBS_GLOBAL`, `MAX_ACTIVE_JOBS_PER_USER`)

## Runtime checks

- [ ] `docker compose -f docker-compose.prod.yml up -d --build` completes
- [ ] `/api/health` returns `ok=true`
- [ ] `/api/ready` returns `ok=true`
- [ ] Worker logs show task polling without crash loop

## Data safety

- [ ] Daily backup job configured
- [ ] Restore drill executed at least once (`scripts/ops/restore_sqlite.sh`)
- [ ] Backup retention policy documented (7 daily + 4 weekly)

## Monitoring and alerts

- [ ] Queue/API checks wired with `scripts/ops/ops_guard_check.py`
- [ ] CPU/memory/disk alerts enabled
- [ ] Alert destinations configured (email/Slack)

## Go-live signoff

- [ ] One full crop job tested end-to-end
- [ ] Wallet credit/spend flow validated
- [ ] Admin dashboard metrics validated
- [ ] Rollback command path documented
