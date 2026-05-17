from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _parse_cpuset(raw: str) -> set[int]:
    cores: set[int] = set()
    for token in [part.strip() for part in str(raw or "").split(",") if part.strip()]:
        if "-" in token:
            left, right = token.split("-", 1)
            try:
                start = int(left)
                end = int(right)
            except Exception:
                continue
            if end < start:
                start, end = end, start
            for core in range(start, end + 1):
                if core >= 0:
                    cores.add(core)
            continue
        try:
            core = int(token)
        except Exception:
            continue
        if core >= 0:
            cores.add(core)
    return cores


def _ok(name: str, details: str = "") -> dict:
    return {"name": name, "status": "pass", "ok": True, "details": details}


def _fail(name: str, details: str) -> dict:
    return {"name": name, "status": "fail", "ok": False, "details": details}


def _skip(name: str, details: str) -> dict:
    return {"name": name, "status": "skip", "ok": True, "details": details}


def _fetch_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode("utf-8"))


def _run_config_checks(repo_root: Path) -> list[dict]:
    results: list[dict] = []
    env_root = repo_root / "deploy" / "hybrid" / "env"
    rt = _read_env_file(env_root / "worker.realtime.env")
    bulk = _read_env_file(env_root / "worker.bulk.env")
    pin = _read_env_file(env_root / "worker.cpu-pinning.env")

    if not rt:
        results.append(_fail("realtime_env_exists", "deploy/hybrid/env/worker.realtime.env missing or empty"))
    else:
        if rt.get("WORKER_QUEUE_ROLE") == "realtime":
            results.append(_ok("realtime_queue_role", "WORKER_QUEUE_ROLE=realtime"))
        else:
            results.append(_fail("realtime_queue_role", "WORKER_QUEUE_ROLE must be realtime"))
        if rt.get("OCR_EXECUTOR_MODE") == "thread":
            results.append(_ok("realtime_executor_mode", "OCR_EXECUTOR_MODE=thread"))
        else:
            results.append(_fail("realtime_executor_mode", "OCR_EXECUTOR_MODE must be thread"))
        max_active = int(rt.get("OCR_MAX_ACTIVE_PROCESSES") or "0")
        if 1 <= max_active <= 4:
            results.append(_ok("realtime_small_concurrency", f"OCR_MAX_ACTIVE_PROCESSES={max_active}"))
        else:
            results.append(_fail("realtime_small_concurrency", "Expected OCR_MAX_ACTIVE_PROCESSES in range 1..4"))

    if not bulk:
        results.append(_fail("bulk_env_exists", "deploy/hybrid/env/worker.bulk.env missing or empty"))
    else:
        if bulk.get("WORKER_QUEUE_ROLE") == "bulk":
            results.append(_ok("bulk_queue_role", "WORKER_QUEUE_ROLE=bulk"))
        else:
            results.append(_fail("bulk_queue_role", "WORKER_QUEUE_ROLE must be bulk"))
        if bulk.get("OCR_EXECUTOR_MODE") == "process":
            results.append(_ok("bulk_executor_mode", "OCR_EXECUTOR_MODE=process"))
        else:
            results.append(_fail("bulk_executor_mode", "OCR_EXECUTOR_MODE must be process"))
        recycle_limit = int(bulk.get("OCR_PROCESS_RECYCLE_LIMIT") or "0")
        if recycle_limit > 0:
            results.append(_ok("bulk_recycle_limit", f"OCR_PROCESS_RECYCLE_LIMIT={recycle_limit}"))
        else:
            results.append(_fail("bulk_recycle_limit", "OCR_PROCESS_RECYCLE_LIMIT must be > 0"))
        if (bulk.get("OCR_STREAMING_ENABLED") or "").strip() in {"1", "true", "yes"}:
            results.append(_ok("bulk_streaming_enabled", "OCR_STREAMING_ENABLED=1"))
        else:
            results.append(_fail("bulk_streaming_enabled", "OCR_STREAMING_ENABLED must be enabled for bulk"))

    rt_cores = _parse_cpuset(pin.get("WORKER_REALTIME_CPUSET", ""))
    bulk_cores = _parse_cpuset(pin.get("WORKER_BULK_CPUSET", ""))
    if rt_cores and bulk_cores and rt_cores.isdisjoint(bulk_cores):
        results.append(_ok("cpu_pinning_disjoint", f"realtime={sorted(rt_cores)} bulk={sorted(bulk_cores)}"))
    else:
        results.append(_fail("cpu_pinning_disjoint", "Realtime and bulk CPU sets must be non-overlapping and non-empty"))
    return results


def _run_live_checks(base_url: str, token: str, min_rt: int, min_bulk: int, max_age: int) -> list[dict]:
    results: list[dict] = []
    metrics_url = f"{base_url.rstrip('/')}/api/admin/ops/metrics"
    try:
        payload = _fetch_json(metrics_url, token)
    except urllib.error.URLError as exc:
        return [_fail("ops_metrics_reachable", f"{exc}")]
    except Exception as exc:  # noqa: BLE001
        return [_fail("ops_metrics_reachable", f"{type(exc).__name__}: {exc}")]

    queue = payload.get("queue") if isinstance(payload, dict) else {}
    if not isinstance(queue, dict):
        return [_fail("ops_metrics_payload", "Missing queue metrics payload")]

    required = [
        "queued_realtime",
        "queued_bulk",
        "active_workers_realtime",
        "active_workers_bulk",
        "oldest_queued_age_sec",
        "ocr_runtime_ms_last",
        "redis_queue_metrics_ms_last",
    ]
    missing = [k for k in required if k not in queue]
    if missing:
        results.append(_fail("queue_metrics_schema", f"Missing keys: {', '.join(missing)}"))
    else:
        results.append(_ok("queue_metrics_schema", "Realtime/bulk + OCR + Redis metrics present"))

    active_rt = int(queue.get("active_workers_realtime") or 0)
    active_bulk = int(queue.get("active_workers_bulk") or 0)
    queued_rt = int(queue.get("queued_realtime") or 0)
    queued_bulk = int(queue.get("queued_bulk") or 0)
    oldest_age = int(queue.get("oldest_queued_age_sec") or 0)

    if active_rt >= min_rt:
        results.append(_ok("worker_heartbeat_realtime", f"active_workers_realtime={active_rt}"))
    else:
        results.append(_fail("worker_heartbeat_realtime", f"active_workers_realtime={active_rt} < {min_rt}"))

    if active_bulk >= min_bulk:
        results.append(_ok("worker_heartbeat_bulk", f"active_workers_bulk={active_bulk}"))
    else:
        results.append(_fail("worker_heartbeat_bulk", f"active_workers_bulk={active_bulk} < {min_bulk}"))

    if queued_rt > 0 and active_rt <= 0:
        results.append(_fail("queue_starvation_realtime", "Realtime queue has backlog but no realtime workers"))
    else:
        results.append(_ok("queue_starvation_realtime", f"queued_realtime={queued_rt}, active={active_rt}"))

    if queued_bulk > 0 and active_bulk <= 0:
        results.append(_fail("queue_starvation_bulk", "Bulk queue has backlog but no bulk workers"))
    else:
        results.append(_ok("queue_starvation_bulk", f"queued_bulk={queued_bulk}, active={active_bulk}"))

    if oldest_age <= max_age:
        results.append(_ok("queue_age_guard", f"oldest_queued_age_sec={oldest_age}"))
    else:
        results.append(_fail("queue_age_guard", f"oldest_queued_age_sec={oldest_age} > {max_age}"))

    ocr_last = int(queue.get("ocr_runtime_ms_last") or 0)
    if ocr_last >= 0:
        results.append(_ok("ocr_execution_metric", f"ocr_runtime_ms_last={ocr_last}"))
    else:
        results.append(_fail("ocr_execution_metric", f"Invalid ocr_runtime_ms_last={ocr_last}"))

    redis_last = int(queue.get("redis_queue_metrics_ms_last") or 0)
    if redis_last >= 0:
        results.append(_ok("redis_metrics_latency", f"redis_queue_metrics_ms_last={redis_last}"))
    else:
        results.append(_fail("redis_metrics_latency", f"Invalid redis_queue_metrics_ms_last={redis_last}"))
    return results


def _run_throughput_check(repo_root: Path, base_url: str, clients: str, min_tps: float) -> dict:
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "ops" / "benchmark_capacity_matrix.py"),
        "--base-url",
        base_url,
        "--clients",
        clients,
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        data = json.loads(out)
        baseline = data.get("selected_baseline") if isinstance(data, dict) else {}
        tps = float((baseline or {}).get("throughput_success_tasks_per_sec") or 0.0)
        if tps >= min_tps:
            return _ok("throughput_validation", f"throughput_success_tasks_per_sec={tps:.3f} (target>={min_tps:.3f})")
        return _fail("throughput_validation", f"throughput_success_tasks_per_sec={tps:.3f} (target>={min_tps:.3f})")
    except subprocess.CalledProcessError as exc:
        details = (exc.output or "").strip().splitlines()[-1] if (exc.output or "").strip() else str(exc)
        return _fail("throughput_validation", f"benchmark command failed: {details}")
    except Exception as exc:  # noqa: BLE001
        return _fail("throughput_validation", f"{type(exc).__name__}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate OCR worker stack config + live metrics")
    parser.add_argument("--base-url", default=os.getenv("OPS_BASE_URL", ""))
    parser.add_argument("--admin-token", default=os.getenv("OPS_BEARER_TOKEN", ""))
    parser.add_argument("--min-active-realtime", type=int, default=1)
    parser.add_argument("--min-active-bulk", type=int, default=1)
    parser.add_argument("--max-oldest-queued-age-sec", type=int, default=300)
    parser.add_argument("--run-throughput", action="store_true")
    parser.add_argument("--throughput-clients", default="20,40")
    parser.add_argument("--min-throughput-success-tps", type=float, default=1.0)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    checks: list[dict] = []
    checks.extend(_run_config_checks(repo_root))

    if (args.base_url or "").strip():
        checks.extend(
            _run_live_checks(
                args.base_url,
                args.admin_token,
                max(0, int(args.min_active_realtime)),
                max(0, int(args.min_active_bulk)),
                max(30, int(args.max_oldest_queued_age_sec)),
            )
        )
    else:
        checks.append(_skip("ops_metrics_reachable", "Skipped live checks (set --base-url or OPS_BASE_URL)"))

    if args.run_throughput:
        checks.append(
            _run_throughput_check(
                repo_root,
                args.base_url,
                args.throughput_clients,
                float(args.min_throughput_success_tps),
            )
        )
    else:
        checks.append(_skip("throughput_validation", "Skipped (pass --run-throughput to execute benchmark)"))

    passed = sum(1 for row in checks if row.get("status") == "pass")
    skipped = sum(1 for row in checks if row.get("status") == "skip")
    failed = sum(1 for row in checks if row.get("status") == "fail")
    out = {"passed": passed, "failed": failed, "skipped": skipped, "checks": checks}
    print(json.dumps(out, indent=2))
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
