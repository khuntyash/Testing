from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _fetch_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=8) as res:
        return json.loads(res.read().decode("utf-8"))


def main() -> int:
    base = os.getenv("OPS_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.getenv("OPS_BEARER_TOKEN", "").strip()
    max_queued = _env_int("OPS_MAX_QUEUED", 200)
    max_running = _env_int("OPS_MAX_RUNNING", 300)
    max_failed_24h = _env_int("OPS_MAX_FAILED_24H", 50)
    max_oldest_age = _env_int("OPS_MAX_OLDEST_QUEUED_AGE_SEC", 300)

    ready_url = f"{base}/api/ready"
    metrics_url = f"{base}/api/admin/ops/metrics"

    try:
        _fetch_json(ready_url, token="")
    except urllib.error.URLError as exc:
        print(f"[CRITICAL] readiness check failed: {exc}")
        return 2

    try:
        payload = _fetch_json(metrics_url, token=token)
    except urllib.error.URLError as exc:
        print(f"[CRITICAL] metrics check failed: {exc}")
        return 2

    queue = payload.get("queue") or {}
    queued = int(queue.get("queued") or 0)
    running = int(queue.get("running") or 0)
    failed_24h = int(queue.get("failed_24h") or 0)
    oldest_age = int(queue.get("oldest_queued_age_sec") or 0)

    problems: list[str] = []
    if queued > max_queued:
        problems.append(f"queued={queued} > {max_queued}")
    if running > max_running:
        problems.append(f"running={running} > {max_running}")
    if failed_24h > max_failed_24h:
        problems.append(f"failed_24h={failed_24h} > {max_failed_24h}")
    if oldest_age > max_oldest_age:
        problems.append(f"oldest_queued_age_sec={oldest_age} > {max_oldest_age}")

    if problems:
        print("[CRITICAL] " + "; ".join(problems))
        return 2

    print(f"[OK] queued={queued} running={running} failed_24h={failed_24h} oldest_queued_age_sec={oldest_age}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
