from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def check_database_ready(db_backend: str, sqlite_db_path: Path) -> tuple[bool, str]:
    backend = (db_backend or "").strip().lower()
    if backend in {"", "sqlite"}:
        try:
            with sqlite3.connect(sqlite_db_path, timeout=3) as conn:
                conn.execute("SELECT 1")
            return True, "sqlite-ok"
        except Exception as exc:
            return False, f"sqlite-error: {exc}"

    if backend in {"postgres", "postgresql"}:
        dsn = os.getenv("DATABASE_URL", "").strip()
        if not dsn:
            return False, "postgres-error: DATABASE_URL is not set"
        try:
            import psycopg  # type: ignore
        except Exception:
            return False, "postgres-error: psycopg is not installed"
        try:
            with psycopg.connect(dsn, connect_timeout=5) as conn:  # type: ignore[attr-defined]
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            return True, "postgres-ok"
        except Exception as exc:
            return False, f"postgres-error: {exc}"

    return False, f"unsupported db backend: {backend}"

