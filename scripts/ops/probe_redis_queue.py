from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from hybrid.queue import RedisQueueClient, TaskEnvelope


def main() -> int:
    client = RedisQueueClient()
    ok = client.ping()
    if not ok:
        raise RuntimeError("Redis ping failed")
    client.enqueue(TaskEnvelope(task_id="probe-task", task_type="probe", payload={"ok": True}))
    item = client.dequeue(timeout_sec=2)
    if not item:
        raise RuntimeError("Redis dequeue failed")
    print(f"Redis probe passed: {item.task_id} {item.task_type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
