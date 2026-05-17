from __future__ import annotations

import json
import os
import subprocess
import urllib.request


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=8) as res:
        return json.loads(res.read().decode("utf-8"))


def _run_scale(target: int) -> int:
    cmd = os.getenv(
        "AUTOSCALE_COMMAND",
        f"docker compose -f docker-compose.prod.yml up -d --scale worker={target}",
    )
    print(f"[autoscale] executing: {cmd}")
    return subprocess.call(cmd, shell=True)


def main() -> int:
    base = os.getenv("OPS_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.getenv("OPS_BEARER_TOKEN", "").strip()
    current_workers = int(os.getenv("CURRENT_WORKERS", "1"))
    min_workers = int(os.getenv("MIN_WORKERS", "1"))
    max_workers = int(os.getenv("MAX_WORKERS", "10"))
    up_queued = int(os.getenv("SCALE_UP_QUEUED", "500"))
    down_queued = int(os.getenv("SCALE_DOWN_QUEUED", "50"))
    up_oldest_age = int(os.getenv("SCALE_UP_OLDEST_AGE_SEC", "180"))

    metrics = _get_json(f"{base}/api/admin/ops/metrics", token)
    queue = metrics.get("queue") or {}
    queued = int(queue.get("queued") or 0)
    oldest_age = int(queue.get("oldest_queued_age_sec") or 0)

    target = current_workers
    if queued > up_queued or oldest_age > up_oldest_age:
        target = min(max_workers, current_workers + 1)
    elif queued < down_queued:
        target = max(min_workers, current_workers - 1)

    if target == current_workers:
        print(f"[autoscale] no change (workers={current_workers}, queued={queued}, oldest={oldest_age}s)")
        return 0

    rc = _run_scale(target)
    if rc == 0:
        print(f"[autoscale] scaled workers {current_workers} -> {target}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
