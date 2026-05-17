# Environment Matrix

## Development

- API platform: local
- DB backend: sqlite
- Queue backend: sqlite
- Storage backend: local
- Embedded worker: optional

## Staging

- API platform: vps or managed test service
- DB backend: postgres (recommended for migration validation)
- Queue backend: redis
- Storage backend: s3 (R2)
- Embedded worker: disabled

## Production

- Phase 1:
  - API platform: vps
  - DB backend: sqlite
  - Queue backend: sqlite
  - Storage backend: local
- Phase 2/3:
  - API platform: render or railway
  - DB backend: postgres
  - Queue backend: redis
  - Storage backend: s3

## Required environment variables

- Core: `CORS_ORIGINS`, `ADMIN_EMAILS`
- Runtime: `DB_BACKEND`, `QUEUE_BACKEND`, `STORAGE_BACKEND`, `API_PLATFORM`
- Limits: `MAX_ACTIVE_JOBS_GLOBAL`, `MAX_ACTIVE_JOBS_PER_USER`, `STALE_JOB_MINUTES`
- DB: `DATABASE_URL` (postgres mode)
- Queue: `REDIS_URL`, `REDIS_QUEUE_NAME` (redis mode)
- Storage: `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` (s3 mode)

