from __future__ import annotations

import json
import os
import urllib.request


def _read_json(url: str, token: str | None = None) -> dict:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=8) as res:
        return json.loads(res.read().decode("utf-8"))


def main() -> int:
    base = os.getenv("OPS_BASE_URL", "").strip().rstrip("/")
    token = os.getenv("OPS_BEARER_TOKEN", "").strip()
    if not base:
        raise RuntimeError("OPS_BASE_URL is required")
    max_queued = int(os.getenv("CANARY_MAX_QUEUED", "700"))
    max_oldest_age = int(os.getenv("CANARY_MAX_OLDEST_AGE_SEC", "300"))

    _read_json(f"{base}/api/health")
    ready = _read_json(f"{base}/api/ready")
    if not ready.get("ok"):
        raise RuntimeError("Readiness failed")

    metrics = _read_json(f"{base}/api/admin/ops/metrics", token=token)
    queue = metrics.get("queue") or {}
    queued = int(queue.get("queued") or 0)
    oldest_age = int(queue.get("oldest_queued_age_sec") or 0)

    if queued > max_queued:
        raise RuntimeError(f"Canary gate failed: queued={queued} > {max_queued}")
    if oldest_age > max_oldest_age:
        raise RuntimeError(f"Canary gate failed: oldest_queued_age_sec={oldest_age} > {max_oldest_age}")

    print(f"Canary gate passed: queued={queued}, oldest_age={oldest_age}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
