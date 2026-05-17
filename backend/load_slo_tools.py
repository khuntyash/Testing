from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def _http_get_json(url: str, timeout: float = 8.0) -> tuple[float, int, dict]:
    t0 = time.perf_counter()
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        body = res.read().decode("utf-8")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        return elapsed_ms, int(res.status), parsed


def run_health_load(base_url: str, concurrency: int, requests: int) -> dict:
    latencies: list[float] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futures = [ex.submit(_http_get_json, f"{base_url.rstrip('/')}/api/health") for _ in range(max(1, requests))]
        for f in as_completed(futures):
            try:
                elapsed_ms, status, _ = f.result()
                latencies.append(elapsed_ms)
                if status >= 400:
                    failures += 1
            except urllib.error.URLError:
                failures += 1
            except Exception:
                failures += 1
    p95 = statistics.quantiles(latencies, n=100)[94] if len(latencies) >= 20 else (max(latencies) if latencies else 0.0)
    return {
        "requests": requests,
        "concurrency": concurrency,
        "ok": failures == 0,
        "failure_count": failures,
        "p95_ms": round(p95, 2),
        "avg_ms": round((sum(latencies) / len(latencies)) if latencies else 0.0, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple health endpoint load + SLO check")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=40)
    parser.add_argument("--requests", type=int, default=400)
    parser.add_argument("--p95-target-ms", type=float, default=450.0)
    args = parser.parse_args()
    result = run_health_load(args.base_url, args.concurrency, args.requests)
    result["slo_pass"] = bool(result["failure_count"] == 0 and result["p95_ms"] <= args.p95_target_ms)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["slo_pass"] else 2)


if __name__ == "__main__":
    main()

