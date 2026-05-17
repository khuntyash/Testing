from __future__ import annotations

import argparse
import os
import tempfile


def _env_role() -> str:
    role = (os.getenv("WORKER_QUEUE_ROLE", "all") or "all").strip().lower()
    return role if role in {"realtime", "bulk", "all"} else "all"


def _check_temp_dir() -> None:
    from runtime_io import worker_temp_base_dir

    base = worker_temp_base_dir()
    if not os.path.isdir(base):
        raise RuntimeError(f"worker temp base is missing: {base}")
    probe = tempfile.NamedTemporaryFile(prefix="health_probe_", dir=base, delete=True)
    probe.close()


def _check_redis() -> None:
    redis_url = (os.getenv("REDIS_URL", "") or "").strip().strip("\"'")
    if not redis_url:
        raise RuntimeError("REDIS_URL is not configured")
    try:
        import redis  # type: ignore
    except Exception as exc:
        raise RuntimeError("redis package is not available") from exc
    client = redis.from_url(redis_url, decode_responses=True)
    if not client.ping():
        raise RuntimeError("redis ping failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker container health probe")
    parser.add_argument("--role", default="", help="Expected queue role for this container")
    args = parser.parse_args()

    expected = (args.role or "").strip().lower()
    actual = _env_role()
    if expected and expected in {"realtime", "bulk"} and actual != expected:
        raise RuntimeError(f"worker role mismatch: expected={expected} actual={actual}")

    _check_temp_dir()
    _check_redis()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
