from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class TaskEnvelope:
    task_id: str
    task_type: str
    payload: dict[str, Any]


class RedisQueueClient:
    def __init__(self, queue_name: str | None = None) -> None:
        self.queue_name = queue_name or os.getenv("REDIS_QUEUE_NAME", "labelhub:tasks")
        redis_url = os.getenv("REDIS_URL", "").strip().strip("\"'")
        if not redis_url:
            raise RuntimeError("REDIS_URL is required for redis queue backend")
        try:
            import redis  # type: ignore
        except Exception as exc:
            raise RuntimeError("redis package is not installed") from exc
        self._client = redis.from_url(redis_url, decode_responses=True)

    def enqueue(self, item: TaskEnvelope) -> None:
        self._client.rpush(
            self.queue_name,
            json.dumps({"task_id": item.task_id, "task_type": item.task_type, "payload": item.payload}),
        )

    def dequeue(self, timeout_sec: int = 5) -> TaskEnvelope | None:
        out = self._client.blpop(self.queue_name, timeout=max(1, int(timeout_sec)))
        if not out:
            return None
        _queue, raw = out
        data = json.loads(raw)
        return TaskEnvelope(
            task_id=str(data.get("task_id") or ""),
            task_type=str(data.get("task_type") or ""),
            payload=data.get("payload") or {},
        )

    def ping(self) -> bool:
        return bool(self._client.ping())

