# Hybrid Deployment Manifests

This folder contains starter manifests for Phase 3 cutover:

- `vercel.json` for frontend hosting
- `render.yaml` for managed API deployment
- `railway.toml` as an alternative managed API deployment

Workers remain on VPS in this architecture.

Choose one API platform (`Render` or `Railway`) and keep the other as fallback.

Environment setup reference:

- `docs/deployment/HYBRID_ENV_SETUP.md`
- `.env.production.hybrid.example`

