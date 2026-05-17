from __future__ import annotations

import os
from dataclasses import dataclass


def _clean(value: str, default: str) -> str:
    text = (value or "").strip().lower()
    return text or default


@dataclass(frozen=True)
class RuntimeBackends:
    db_backend: str
    queue_backend: str
    storage_backend: str
    api_platform: str


def get_runtime_backends() -> RuntimeBackends:
    return RuntimeBackends(
        db_backend=_clean(os.getenv("DB_BACKEND", "sqlite"), "sqlite"),
        queue_backend=_clean(os.getenv("QUEUE_BACKEND", "sqlite"), "sqlite"),
        storage_backend=_clean(os.getenv("STORAGE_BACKEND", "local"), "local"),
        api_platform=_clean(os.getenv("API_PLATFORM", "vps"), "vps"),
    )

