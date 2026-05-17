from __future__ import annotations

import json
import sqlite3
import csv
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from auth_store import DB_PATH

# Crop history rows are retained indefinitely so dashboard/recent-jobs/risk
# insights survive across days. Download artifacts are cleaned separately
# after the configured retention window.
DOWNLOAD_RETENTION_HOURS = 24


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_day_start_utc_iso() -> str:
    local_now = datetime.now().astimezone()
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc).isoformat()


def _purge_previous_day_completed_jobs() -> int:
    """
    Removes previous-day crop history rows and their linked download
    artifacts. Retained as a callable utility for explicit/admin cleanup,
    but it is no longer invoked automatically. Dashboard and recent-jobs
    data is now persistent unless an admin explicitly triggers cleanup.
    """
    threshold_iso = _local_day_start_utc_iso()
    result_paths: list[str] = []
    deleted = 0
    with _db_connect() as conn:
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT t.result_path AS result_path
                FROM processing_tasks t
                WHERE t.task_type IN ('crop_meesho', 'crop_flipkart')
                  AND t.created_at < ?
                  AND COALESCE(t.result_path, '') <> ''
                """,
                (threshold_iso,),
            ).fetchall()
            result_paths = [str(r["result_path"] or "").strip() for r in rows if str(r["result_path"] or "").strip()]
        except sqlite3.Error:
            # processing_tasks may not exist yet during early startup/migrations.
            result_paths = []

        cur = conn.execute(
            """
            DELETE FROM crop_jobs
            WHERE created_at < ?
            """,
            (threshold_iso,),
        )
        deleted = int(cur.rowcount or 0)
        try:
            conn.execute(
                """
                DELETE FROM processing_tasks
                WHERE task_type IN ('crop_meesho', 'crop_flipkart')
                  AND created_at < ?
                """,
                (threshold_iso,),
            )
        except sqlite3.Error:
            pass

    for path in result_paths:
        try:
            if not path:
                continue
            if os.path.isfile(path):
                os.unlink(path)
            elif os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue
    return deleted


def _purge_previous_day_completed_jobs_if_needed() -> None:
    # Daily auto-purge is disabled so dashboard/history/risk-insights data
    # remains persistent. Kept as a no-op shim so existing call sites stay
    # valid without churn.
    return


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _risk_store_dir() -> Path:
    return (Path(DB_PATH).resolve().parent / "risk_store").resolve()


def _parse_iso(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_premium_crop_options_enabled(options: dict | None) -> bool:
    if not isinstance(options, dict):
        return False
    # Keep dashboard premium counts aligned with coin spend rules:
    # only premium risk/split features should be billable.
    separate_pincodes = str(
        options.get("separate_pincodes") or options.get("separatePincodes") or ""
    ).strip()
    return bool(
        options.get("detect_suspicious")
        or options.get("detectSuspicious")
        or options.get("detect_suspicious_enabled")
        or options.get("mark_suspicious_preview")
        or options.get("markSuspiciousPreview")
        or options.get("suspicious_preview_enabled")
        or options.get("separate_multi_order_by_customer")
        or options.get("separateMultiOrderByCustomer")
        or options.get("multi_order_split_enabled")
        or options.get("mark_loyal_customer")
        or options.get("markLoyalCustomer")
        or options.get("loyal_customer_enabled")
        or options.get("mark_loyal_customer_preview")
        or options.get("markLoyalCustomerPreview")
        or options.get("loyal_preview_enabled")
        or options.get("pincode_split_enabled")
        or separate_pincodes
    )


def _download_window_info(*, created_at: str, task_status: str, task_id: str, finished_at: str = "") -> dict:
    # Keep historical rows visible, but expose whether their download window
    # has elapsed so UI can show "Expired" while preserving job history.
    if not task_id or (task_status or "") != "success":
        return {
            "download_available": False,
            "download_expired": False,
            "download_expires_at": "",
        }

    anchor = _parse_iso(finished_at) or _parse_iso(created_at)
    if not anchor:
        return {
            "download_available": True,
            "download_expired": False,
            "download_expires_at": "",
        }
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    expires_at = anchor + timedelta(hours=max(1, int(DOWNLOAD_RETENTION_HOURS)))
    expired = datetime.now(timezone.utc) > expires_at
    return {
        "download_available": not expired,
        "download_expired": expired,
        "download_expires_at": expires_at.isoformat(),
    }


def _effective_crop_status(*, job_status: str, task_status: str) -> str:
    """Prefer queue-task terminal status when history row lags behind.

    In distributed worker mode, queue task completion may succeed even if
    history DB updates fail. This keeps UI status/download behavior aligned
    with the authoritative task state.
    """
    js = (job_status or "").strip().lower()
    ts = (task_status or "").strip().lower()
    if ts in {"success", "failed", "cancelled", "expired"}:
        return ts
    if ts == "running":
        return "processing"
    if ts == "queued":
        return "pending"
    return js


def _resolved_task_fields(*, task_id: str, task_status: str, job_status: str, options: dict | None = None) -> tuple[str, str]:
    """Resolve task linkage with fan-out metadata fallbacks.

    Some distributed/fan-out completions can leave `processing_tasks` join empty
    while `crop_job_metrics.options_json` still has the parent task id.
    """
    opts = options if isinstance(options, dict) else {}
    resolved_task_id = (
        str(task_id or "").strip()
        or str(opts.get("fanout_parent_task_id") or "").strip()
        or str(opts.get("task_id") or "").strip()
    )
    resolved_task_status = str(task_status or "").strip().lower()
    if not resolved_task_status and resolved_task_id and (job_status or "").strip().lower() == "success":
        resolved_task_status = "success"
    return resolved_task_id, resolved_task_status


def _redis_recent_crop_tasks_by_job(user_id: int, *, limit: int = 300) -> dict[int, dict]:
    """Best-effort Redis fallback for history/task linkage in distributed mode."""
    if (os.getenv("QUEUE_BACKEND", "sqlite") or "sqlite").strip().lower() != "redis":
        return {}
    redis_url = (os.getenv("REDIS_URL", "") or "").strip().strip("\"'")
    if not redis_url:
        return {}
    queue_name = (os.getenv("REDIS_QUEUE_NAME", "labelhub:tasks") or "labelhub:tasks").strip() or "labelhub:tasks"
    user_key = f"{queue_name}:user:{int(user_id)}:tasks"
    out: dict[int, dict] = {}
    try:
        import redis  # type: ignore

        client = redis.from_url(redis_url, decode_responses=True)
        task_ids = client.zrevrange(user_key, 0, max(0, int(limit) - 1))
        for task_id in task_ids or []:
            raw = client.get(f"{queue_name}:task:{task_id}")
            if not raw:
                continue
            try:
                task = json.loads(raw)
            except Exception:
                continue
            if str(task.get("task_type") or "") not in {"crop_meesho", "crop_flipkart"}:
                continue
            job_id = int(task.get("job_id") or 0)
            if job_id <= 0 or job_id in out:
                continue
            out[job_id] = {
                "task_id": str(task.get("task_id") or ""),
                "task_status": str(task.get("status") or ""),
                "task_finished_at": str(task.get("finished_at") or ""),
            }
    except Exception:
        return {}
    return out


def _should_hide_expired_success(*, status: str, download_info: dict) -> bool:
    # Expired-success rows are no longer hidden; recent jobs persist
    # across days even if their download artifact was cleaned up.
    return False


def _manual_high_risk_totals() -> tuple[int, int, int, int]:
    store_dir = _risk_store_dir()
    if not store_dir.exists():
        return 0, 0, 0, 0
    customers_total = 0
    suborders_total = 0
    customers_7d = 0
    suborders_7d = 0
    threshold = datetime.now(timezone.utc) - timedelta(days=7)
    for csv_path in store_dir.glob("user_*_risk_profile.csv"):
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    reason = (row.get("last_reason") or "").strip().lower()
                    status = (row.get("last_status") or "").strip().lower()
                    if reason != "manual_marked_by_user" and status != "manual_high_risk":
                        continue
                    customers_total += 1
                    raw_subs = str(row.get("risky_suborders", "")).strip()
                    subs_count = 0
                    if raw_subs:
                        parts = [p.strip() for p in raw_subs.replace(",", "|").split("|")]
                        subs_count = len([p for p in parts if p])
                        suborders_total += subs_count
                    stamp = _parse_iso(str(row.get("updated_at", "")).strip()) or _parse_iso(
                        str(row.get("last_seen_at", "")).strip()
                    )
                    if stamp and stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    if stamp and stamp >= threshold:
                        customers_7d += 1
                        suborders_7d += subs_count
        except Exception:
            continue
    return customers_total, suborders_total, customers_7d, suborders_7d


def init_history_db() -> None:
    with _db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crop_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crop_job_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                input_pages INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES crop_jobs(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crop_job_metrics (
                job_id INTEGER PRIMARY KEY,
                total_input_files INTEGER NOT NULL DEFAULT 0,
                total_input_pages INTEGER NOT NULL DEFAULT 0,
                total_output_pages INTEGER NOT NULL DEFAULT 0,
                total_output_labels INTEGER NOT NULL DEFAULT 0,
                layout TEXT NOT NULL DEFAULT '',
                sort_by TEXT NOT NULL DEFAULT '',
                options_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (job_id) REFERENCES crop_jobs(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crop_jobs_user_created ON crop_jobs(user_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crop_jobs_platform_created ON crop_jobs(platform, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crop_job_files_job_id ON crop_job_files(job_id)")


def create_crop_job(*, user_id: int, platform: str, sort_by: str, layout: str, options: dict | None = None) -> int:
    _purge_previous_day_completed_jobs_if_needed()
    created_at = _utc_now_iso()
    safe_options = json.dumps(options or {}, ensure_ascii=True)
    with _db_connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO crop_jobs (user_id, platform, status, created_at)
            VALUES (?, ?, 'pending', ?)
            """,
            (user_id, platform, created_at),
        )
        job_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO crop_job_metrics (
                job_id, total_input_files, total_input_pages, total_output_pages,
                total_output_labels, layout, sort_by, options_json
            ) VALUES (?, 0, 0, 0, 0, ?, ?, ?)
            """,
            (job_id, layout or "", sort_by or "", safe_options),
        )
    return job_id


def mark_crop_job_started(job_id: int) -> None:
    started_at = _utc_now_iso()
    with _db_connect() as conn:
        conn.execute(
            "UPDATE crop_jobs SET status = 'processing', started_at = ? WHERE id = ?",
            (started_at, job_id),
        )


def _replace_job_files(conn: sqlite3.Connection, job_id: int, input_files: list[dict]) -> None:
    conn.execute("DELETE FROM crop_job_files WHERE job_id = ?", (job_id,))
    created_at = _utc_now_iso()
    for row in input_files:
        file_name = (row.get("file_name") or "").strip() or "unknown.pdf"
        input_pages = int(row.get("input_pages") or 0)
        conn.execute(
            """
            INSERT INTO crop_job_files (job_id, file_name, input_pages, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, file_name, max(0, input_pages), created_at),
        )


def mark_crop_job_success(
    job_id: int,
    *,
    duration_ms: int,
    total_input_files: int,
    total_input_pages: int,
    total_output_pages: int,
    total_output_labels: int,
    input_files: list[dict],
    sort_by: str,
    layout: str,
    options: dict | None = None,
) -> None:
    finished_at = _utc_now_iso()
    safe_options = json.dumps(options or {}, ensure_ascii=True)
    with _db_connect() as conn:
        conn.execute(
            """
            UPDATE crop_jobs
            SET status = 'success',
                error_message = '',
                finished_at = ?,
                duration_ms = ?
            WHERE id = ?
            """,
            (finished_at, max(0, int(duration_ms)), job_id),
        )
        conn.execute(
            """
            INSERT INTO crop_job_metrics (
                job_id, total_input_files, total_input_pages, total_output_pages,
                total_output_labels, layout, sort_by, options_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                total_input_files = excluded.total_input_files,
                total_input_pages = excluded.total_input_pages,
                total_output_pages = excluded.total_output_pages,
                total_output_labels = excluded.total_output_labels,
                layout = excluded.layout,
                sort_by = excluded.sort_by,
                options_json = excluded.options_json
            """,
            (
                job_id,
                max(0, int(total_input_files)),
                max(0, int(total_input_pages)),
                max(0, int(total_output_pages)),
                max(0, int(total_output_labels)),
                layout or "",
                sort_by or "",
                safe_options,
            ),
        )
        _replace_job_files(conn, job_id, input_files or [])


def mark_crop_job_failed(
    job_id: int,
    *,
    error_message: str,
    duration_ms: int,
    input_files: list[dict] | None = None,
) -> None:
    finished_at = _utc_now_iso()
    with _db_connect() as conn:
        conn.execute(
            """
            UPDATE crop_jobs
            SET status = 'failed',
                error_message = ?,
                finished_at = ?,
                duration_ms = ?
            WHERE id = ?
            """,
            ((error_message or "Unknown processing error.")[:1200], finished_at, max(0, int(duration_ms)), job_id),
        )
        if input_files is not None:
            _replace_job_files(conn, job_id, input_files)


def list_crop_jobs_for_user(
    user_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
    platform: str | None = None,
    status: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    sort: str = "newest",
) -> list[dict]:
    _purge_previous_day_completed_jobs_if_needed()
    safe_limit = min(max(int(limit), 1), 100)
    safe_offset = max(int(offset), 0)
    order_by = "j.id DESC" if (sort or "newest") != "oldest" else "j.id ASC"
    query = """
        SELECT j.id, j.platform, j.status, j.error_message, j.created_at, j.started_at,
               j.finished_at, j.duration_ms, m.total_input_files, m.total_input_pages,
               m.total_output_pages, m.total_output_labels, m.layout, m.sort_by, m.options_json,
               t.task_id AS task_id, t.status AS task_status, t.finished_at AS task_finished_at
        FROM crop_jobs j
        LEFT JOIN crop_job_metrics m ON m.job_id = j.id
        LEFT JOIN processing_tasks t
          ON t.job_id = j.id
         AND t.user_id = j.user_id
         AND t.task_type IN ('crop_meesho', 'crop_flipkart')
        WHERE j.user_id = ?
    """
    params: list[object] = [user_id]
    if platform:
        query += " AND j.platform = ?"
        params.append(platform)
    if status:
        query += " AND j.status = ?"
        params.append(status)
    if from_date:
        query += " AND j.created_at >= ?"
        params.append(from_date)
    if to_date:
        query += " AND j.created_at <= ?"
        params.append(to_date)
    query += f" ORDER BY {order_by}"

    with _db_connect() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    redis_by_job = _redis_recent_crop_tasks_by_job(user_id, limit=max(200, safe_limit * 6))
    out: list[dict] = []
    for row in rows:
        options = {}
        try:
            options = json.loads(row["options_json"] or "{}")
            if not isinstance(options, dict):
                options = {}
        except Exception:
            options = {}
        redis_task = redis_by_job.get(int(row["id"] or 0)) if redis_by_job else None
        resolved_task_id, resolved_task_status = _resolved_task_fields(
            task_id=str(row["task_id"] or ""),
            task_status=str((redis_task or {}).get("task_status") or row["task_status"] or ""),
            job_status=str(row["status"] or ""),
            options=options,
        )
        resolved_finished_at = str((redis_task or {}).get("task_finished_at") or row["task_finished_at"] or row["finished_at"] or "")
        if redis_task and not str(row["task_id"] or "").strip():
            resolved_task_id = str(redis_task.get("task_id") or resolved_task_id)
        effective_status = _effective_crop_status(
            job_status=str(row["status"] or ""),
            task_status=resolved_task_status,
        )
        download_info = _download_window_info(
            created_at=str(row["created_at"] or ""),
            finished_at=resolved_finished_at,
            task_status=resolved_task_status,
            task_id=resolved_task_id,
        )
        if _should_hide_expired_success(status=str(row["status"] or ""), download_info=download_info):
            continue
        out.append(
            {
                "id": row["id"],
                "platform": row["platform"],
                "status": effective_status,
                "error_message": row["error_message"],
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "duration_ms": row["duration_ms"],
                "total_input_files": row["total_input_files"] or 0,
                "total_input_pages": row["total_input_pages"] or 0,
                "total_output_pages": row["total_output_pages"] or 0,
                "total_output_labels": row["total_output_labels"] or 0,
                "layout": row["layout"] or "",
                "sort_by": row["sort_by"] or "",
                "task_id": resolved_task_id,
                "task_status": resolved_task_status,
                "download_available": bool(download_info["download_available"]),
                "download_expires_at": str(download_info["download_expires_at"]),
                "options": options,
            }
        )
    end = safe_offset + safe_limit
    return out[safe_offset:end]


def list_admin_crop_jobs(*, limit: int = 20, offset: int = 0) -> list[dict]:
    _purge_previous_day_completed_jobs_if_needed()
    safe_limit = min(max(int(limit), 1), 100)
    safe_offset = max(int(offset), 0)
    with _db_connect() as conn:
        rows = conn.execute(
            """
            SELECT j.id, j.user_id, j.platform, j.status, j.error_message, j.created_at, j.duration_ms,
                   m.total_input_files, m.total_input_pages, m.total_output_pages, m.total_output_labels,
                   m.layout, m.sort_by, m.options_json, u.email AS user_email, u.name AS user_name
            FROM crop_jobs j
            LEFT JOIN crop_job_metrics m ON m.job_id = j.id
            LEFT JOIN users u ON u.id = j.user_id
            ORDER BY j.id DESC
            LIMIT ? OFFSET ?
            """,
            (safe_limit, safe_offset),
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        options = {}
        try:
            options = json.loads(row["options_json"] or "{}")
            if not isinstance(options, dict):
                options = {}
        except Exception:
            options = {}
        out.append(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "user_email": row["user_email"] or "",
                "user_name": row["user_name"] or "",
                "platform": row["platform"],
                "status": row["status"],
                "error_message": row["error_message"],
                "created_at": row["created_at"],
                "duration_ms": row["duration_ms"] or 0,
                "total_input_files": row["total_input_files"] or 0,
                "total_input_pages": row["total_input_pages"] or 0,
                "total_output_pages": row["total_output_pages"] or 0,
                "total_output_labels": row["total_output_labels"] or 0,
                "layout": row["layout"] or "",
                "sort_by": row["sort_by"] or "",
                "options": options,
            }
        )
    return out


def count_admin_crop_jobs() -> int:
    _purge_previous_day_completed_jobs_if_needed()
    with _db_connect() as conn:
        row = conn.execute("SELECT COUNT(1) AS cnt FROM crop_jobs").fetchone()
    return int(row["cnt"] if row else 0)


def count_crop_jobs_for_user(
    user_id: int,
    *,
    platform: str | None = None,
    status: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> int:
    _purge_previous_day_completed_jobs_if_needed()
    query = """
        SELECT j.status, j.created_at, j.finished_at,
               t.task_id AS task_id, t.status AS task_status, t.finished_at AS task_finished_at
        FROM crop_jobs j
        LEFT JOIN processing_tasks t
          ON t.job_id = j.id
         AND t.user_id = j.user_id
         AND t.task_type IN ('crop_meesho', 'crop_flipkart')
        WHERE j.user_id = ?
    """
    params: list[object] = [user_id]
    if platform:
        query += " AND j.platform = ?"
        params.append(platform)
    if status:
        query += " AND j.status = ?"
        params.append(status)
    if from_date:
        query += " AND j.created_at >= ?"
        params.append(from_date)
    if to_date:
        query += " AND j.created_at <= ?"
        params.append(to_date)

    with _db_connect() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    visible = 0
    for row in rows:
        resolved_task_id, resolved_task_status = _resolved_task_fields(
            task_id=str(row["task_id"] or ""),
            task_status=str(row["task_status"] or ""),
            job_status=str(row["status"] or ""),
            options=None,
        )
        effective_status = _effective_crop_status(
            job_status=str(row["status"] or ""),
            task_status=resolved_task_status,
        )
        if status and effective_status != (status or "").strip().lower():
            continue
        download_info = _download_window_info(
            created_at=str(row["created_at"] or ""),
            finished_at=str(row["task_finished_at"] or row["finished_at"] or ""),
            task_status=resolved_task_status,
            task_id=resolved_task_id,
        )
        if _should_hide_expired_success(status=effective_status, download_info=download_info):
            continue
        visible += 1
    return visible


def get_admin_metrics() -> dict:
    _purge_previous_day_completed_jobs_if_needed()
    with _db_connect() as conn:
        total_users = int(conn.execute("SELECT COUNT(1) AS cnt FROM users").fetchone()["cnt"])
        total_jobs = int(conn.execute("SELECT COUNT(1) AS cnt FROM crop_jobs").fetchone()["cnt"])
        total_success = int(
            conn.execute("SELECT COUNT(1) AS cnt FROM crop_jobs WHERE status = 'success'").fetchone()["cnt"]
        )
        total_failed = int(
            conn.execute("SELECT COUNT(1) AS cnt FROM crop_jobs WHERE status = 'failed'").fetchone()["cnt"]
        )
        jobs_today = int(
            conn.execute(
                "SELECT COUNT(1) AS cnt FROM crop_jobs WHERE date(created_at) = date('now')"
            ).fetchone()["cnt"]
        )
        active_users_7d = int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT user_id) AS cnt
                FROM crop_jobs
                WHERE date(created_at) >= date('now','-7 day')
                """
            ).fetchone()["cnt"]
        )
    (
        manual_high_risk_customers_total,
        manual_high_risk_suborders_total,
        manual_high_risk_customers_7d,
        manual_high_risk_suborders_7d,
    ) = _manual_high_risk_totals()

    return {
        "total_users": total_users,
        "total_jobs": total_jobs,
        "total_success": total_success,
        "total_failed": total_failed,
        "jobs_today": jobs_today,
        "active_users_7d": active_users_7d,
        "manual_high_risk_customers_total": int(manual_high_risk_customers_total),
        "manual_high_risk_suborders_total": int(manual_high_risk_suborders_total),
        "manual_high_risk_customers_7d": int(manual_high_risk_customers_7d),
        "manual_high_risk_suborders_7d": int(manual_high_risk_suborders_7d),
    }


def get_crop_job_for_user(user_id: int, job_id: int) -> dict | None:
    _purge_previous_day_completed_jobs_if_needed()
    with _db_connect() as conn:
        row = conn.execute(
            """
            SELECT j.id, j.platform, j.status, j.error_message, j.created_at, j.started_at,
                   j.finished_at, j.duration_ms, m.total_input_files, m.total_input_pages,
                   m.total_output_pages, m.total_output_labels, m.layout, m.sort_by, m.options_json,
                   t.task_id AS task_id, t.status AS task_status, t.finished_at AS task_finished_at
            FROM crop_jobs j
            LEFT JOIN crop_job_metrics m ON m.job_id = j.id
            LEFT JOIN processing_tasks t
              ON t.job_id = j.id
             AND t.user_id = j.user_id
             AND t.task_type IN ('crop_meesho', 'crop_flipkart')
            WHERE j.id = ? AND j.user_id = ?
            """,
            (job_id, user_id),
        ).fetchone()
        if not row:
            return None

        files = conn.execute(
            """
            SELECT file_name, input_pages
            FROM crop_job_files
            WHERE job_id = ?
            ORDER BY id ASC
            """,
            (job_id,),
        ).fetchall()

    options = {}
    try:
        options = json.loads(row["options_json"] or "{}")
        if not isinstance(options, dict):
            options = {}
    except Exception:
        options = {}

    redis_task = _redis_recent_crop_tasks_by_job(user_id, limit=300).get(int(job_id))
    resolved_task_id, resolved_task_status = _resolved_task_fields(
        task_id=str(row["task_id"] or ""),
        task_status=str((redis_task or {}).get("task_status") or row["task_status"] or ""),
        job_status=str(row["status"] or ""),
        options=options,
    )
    resolved_finished_at = str((redis_task or {}).get("task_finished_at") or row["task_finished_at"] or row["finished_at"] or "")
    if redis_task and not str(row["task_id"] or "").strip():
        resolved_task_id = str(redis_task.get("task_id") or resolved_task_id)
    download_info = _download_window_info(
        created_at=str(row["created_at"] or ""),
        finished_at=resolved_finished_at,
        task_status=resolved_task_status,
        task_id=resolved_task_id,
    )
    effective_status = _effective_crop_status(
        job_status=str(row["status"] or ""),
        task_status=resolved_task_status,
    )
    if _should_hide_expired_success(status=effective_status, download_info=download_info):
        return None
    return {
        "id": row["id"],
        "platform": row["platform"],
        "status": effective_status,
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_ms": row["duration_ms"],
        "total_input_files": row["total_input_files"] or 0,
        "total_input_pages": row["total_input_pages"] or 0,
        "total_output_pages": row["total_output_pages"] or 0,
        "total_output_labels": row["total_output_labels"] or 0,
        "layout": row["layout"] or "",
        "sort_by": row["sort_by"] or "",
        "task_id": resolved_task_id,
        "task_status": resolved_task_status,
        "download_available": bool(download_info["download_available"]),
        "download_expires_at": str(download_info["download_expires_at"]),
        "options": options,
        "files": [{"file_name": f["file_name"], "input_pages": f["input_pages"]} for f in files],
    }


def count_active_jobs(*, user_id: int | None = None, platform: str | None = None) -> int:
    query = "SELECT COUNT(1) AS cnt FROM crop_jobs WHERE status IN ('pending', 'processing')"
    params: list[object] = []
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(int(user_id))
    if platform:
        query += " AND platform = ?"
        params.append(platform)
    with _db_connect() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    return int(row["cnt"] if row else 0)


def aggregate_crop_totals_for_users(user_ids: list[int]) -> dict[int, dict[str, int]]:
    clean_ids = sorted({int(uid) for uid in (user_ids or []) if int(uid) > 0})
    if not clean_ids:
        return {}
    placeholders = ",".join("?" for _ in clean_ids)
    with _db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                j.user_id AS user_id,
                COALESCE(
                    SUM(
                        CASE
                            WHEN COALESCE(m.total_output_labels, 0) > 0 THEN m.total_output_labels
                            ELSE COALESCE(m.total_input_pages, 0)
                        END
                    ),
                    0
                ) AS total_labels
            FROM crop_jobs j
            LEFT JOIN crop_job_metrics m ON m.job_id = j.id
            WHERE j.user_id IN ({placeholders})
              AND j.status = 'success'
              AND j.platform IN ('meesho', 'flipkart')
            GROUP BY j.user_id
            """,
            tuple(clean_ids),
        ).fetchall()
        risky_rows = conn.execute(
            f"""
            SELECT j.user_id AS user_id, m.options_json AS options_json
            FROM crop_jobs j
            LEFT JOIN crop_job_metrics m ON m.job_id = j.id
            WHERE j.user_id IN ({placeholders})
              AND j.status = 'success'
              AND j.platform IN ('meesho', 'flipkart')
            """,
            tuple(clean_ids),
        ).fetchall()
    out = {uid: {"labels": 0, "risky": 0} for uid in clean_ids}
    for row in rows:
        uid = int(row["user_id"])
        out[uid]["labels"] = max(0, int(row["total_labels"] or 0))
    for row in risky_rows:
        uid = int(row["user_id"])
        raw_options = row["options_json"] or "{}"
        risky_val = 0
        try:
            options = json.loads(raw_options)
            if isinstance(options, dict):
                risky_val = int(float(options.get("risky_pages") or options.get("risky_orders_matched") or 0))
        except Exception:
            risky_val = 0
        out[uid]["risky"] += max(0, risky_val)
    return out


def _user_manual_high_risk_totals(user_id: int) -> tuple[int, int, int, int]:
    """Per-user manual high-risk customer/suborder totals.

    Reads ``user_{id}_suspicious_customers.csv`` (and per-platform variants)
    from ``risk_store/`` and counts rows whose status/reason indicates a
    user-marked manual high risk entry. Returns
    ``(customers_total, suborders_total, customers_7d, suborders_7d)``.
    Any read/parse error is swallowed so the caller never fails because of
    a partially written CSV.
    """
    safe_user_id = int(user_id)
    if safe_user_id <= 0:
        return 0, 0, 0, 0
    store_dir = _risk_store_dir()
    if not store_dir.exists():
        return 0, 0, 0, 0

    candidate_paths: list[Path] = []
    legacy = store_dir / f"user_{safe_user_id}_suspicious_customers.csv"
    if legacy.exists():
        candidate_paths.append(legacy)
    for platform in ("meesho", "flipkart"):
        candidate = store_dir / f"user_{safe_user_id}_{platform}_suspicious_customers.csv"
        if candidate.exists():
            candidate_paths.append(candidate)
    if not candidate_paths:
        return 0, 0, 0, 0

    customers_total = 0
    suborders_total = 0
    customers_7d = 0
    suborders_7d = 0
    threshold = datetime.now(timezone.utc) - timedelta(days=7)
    seen_keys: set[str] = set()
    for csv_path in candidate_paths:
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    reason = (row.get("last_reason") or "").strip().lower()
                    status = (row.get("last_status") or "").strip().lower()
                    if reason != "manual_marked_by_user" and status != "manual_high_risk":
                        continue
                    key = (row.get("customer_key") or "").strip().lower()
                    if key and key in seen_keys:
                        continue
                    if key:
                        seen_keys.add(key)
                    customers_total += 1
                    raw_subs = str(row.get("risky_suborders", "")).strip()
                    subs_count = 0
                    if raw_subs:
                        parts = [p.strip() for p in raw_subs.replace(",", "|").split("|")]
                        subs_count = len([p for p in parts if p])
                        suborders_total += subs_count
                    stamp = _parse_iso(str(row.get("updated_at", "")).strip()) or _parse_iso(
                        str(row.get("last_seen_at", "")).strip()
                    )
                    if stamp and stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    if stamp and stamp >= threshold:
                        customers_7d += 1
                        suborders_7d += subs_count
        except Exception:
            continue
    return customers_total, suborders_total, customers_7d, suborders_7d


def get_user_dashboard_metrics(user_id: int, *, recent_limit: int = 5) -> dict:
    """Aggregate per-user dashboard metrics from ``crop_jobs``/``crop_job_metrics``.

    Returns a dict with overall counts (success/failed/processing/pending),
    label/page totals, per-platform breakdowns, ``recent_jobs`` (most recent
    successful or otherwise visible runs), and manual high-risk totals
    derived from the user's risk-store CSV. The function is read-only and
    quietly returns zeroed structures when the user has no history yet.

    Crop history rows are retained indefinitely, so this matches the
    History UI exactly without filtering anything out for age.
    """
    _purge_previous_day_completed_jobs_if_needed()
    safe_user_id = int(user_id)
    safe_recent = max(1, min(int(recent_limit or 5), 25))

    base_summary = {
        "total_jobs": 0,
        "success_jobs": 0,
        "failed_jobs": 0,
        "processing_jobs": 0,
        "pending_jobs": 0,
        "total_input_pages": 0,
        "total_output_labels": 0,
        "total_input_files": 0,
        "jobs_today": 0,
        "jobs_7d": 0,
        "last_activity_at": "",
        "suspicious_pages_total": 0,
        "pincode_pages_total": 0,
        "normal_pages_total": 0,
        "premium_labels_billed": 0,
    }

    if safe_user_id <= 0:
        return {
            "summary": base_summary,
            "platforms": [],
            "recent_jobs": [],
            "manual_high_risk": {
                "customers_total": 0,
                "suborders_total": 0,
                "customers_7d": 0,
                "suborders_7d": 0,
            },
        }

    today_iso_prefix = datetime.now(timezone.utc).date().isoformat()
    last_7d_threshold = datetime.now(timezone.utc) - timedelta(days=7)

    with _db_connect() as conn:
        rows = conn.execute(
            """
            SELECT j.id, j.platform, j.status, j.error_message, j.created_at, j.started_at,
                   j.finished_at, j.duration_ms,
                   m.total_input_files, m.total_input_pages,
                   m.total_output_pages, m.total_output_labels,
                   m.layout, m.sort_by, m.options_json,
                   t.task_id AS task_id, t.status AS task_status,
                   t.finished_at AS task_finished_at
            FROM crop_jobs j
            LEFT JOIN crop_job_metrics m ON m.job_id = j.id
            LEFT JOIN processing_tasks t
              ON t.job_id = j.id
             AND t.user_id = j.user_id
             AND t.task_type IN ('crop_meesho', 'crop_flipkart')
            WHERE j.user_id = ?
            ORDER BY j.id DESC
            """,
            (safe_user_id,),
        ).fetchall()

    summary = dict(base_summary)
    platform_acc: dict[str, dict] = {}
    recent_visible: list[dict] = []
    last_activity_dt: datetime | None = None

    for row in rows:
        status = _effective_crop_status(
            job_status=str(row["status"] or ""),
            task_status=str(row["task_status"] or ""),
        )
        download_info = _download_window_info(
            created_at=str(row["created_at"] or ""),
            finished_at=str(row["task_finished_at"] or row["finished_at"] or ""),
            task_status=str(row["task_status"] or ""),
            task_id=str(row["task_id"] or ""),
        )
        if _should_hide_expired_success(status=status, download_info=download_info):
            continue

        try:
            options = json.loads(row["options_json"] or "{}")
            if not isinstance(options, dict):
                options = {}
        except Exception:
            options = {}

        platform = (row["platform"] or "unknown").strip().lower() or "unknown"
        plat_entry = platform_acc.setdefault(
            platform,
            {
                "platform": platform,
                "total_jobs": 0,
                "success_jobs": 0,
                "failed_jobs": 0,
                "processing_jobs": 0,
                "pending_jobs": 0,
                "total_input_pages": 0,
                "total_output_labels": 0,
                "total_input_files": 0,
                "suspicious_buyers_total": 0,
                "suspicious_pages_total": 0,
                "pincode_pages_total": 0,
                "normal_pages_total": 0,
                "premium_labels_billed": 0,
                "last_run_at": "",
            },
        )

        input_files = max(0, int(row["total_input_files"] or 0))
        input_pages = max(0, int(row["total_input_pages"] or 0))
        output_labels = max(0, int(row["total_output_labels"] or 0))

        try:
            risky_pages = int(float(options.get("risky_pages") or 0))
        except Exception:
            risky_pages = 0
        try:
            pincode_pages = int(float(options.get("selected_pincode_pages") or 0))
        except Exception:
            pincode_pages = 0
        try:
            normal_pages = int(float(options.get("normal_pages") or 0))
        except Exception:
            normal_pages = 0
        try:
            suspicious_buyers = int(float(options.get("risky_orders_matched") or 0))
        except Exception:
            suspicious_buyers = 0

        summary["total_jobs"] += 1
        plat_entry["total_jobs"] += 1
        if status == "success":
            summary["success_jobs"] += 1
            plat_entry["success_jobs"] += 1
            summary["total_input_pages"] += input_pages
            summary["total_output_labels"] += output_labels
            summary["total_input_files"] += input_files
            plat_entry["total_input_pages"] += input_pages
            plat_entry["total_output_labels"] += output_labels
            plat_entry["total_input_files"] += input_files
            summary["suspicious_pages_total"] += max(0, risky_pages)
            summary["pincode_pages_total"] += max(0, pincode_pages)
            summary["normal_pages_total"] += max(0, normal_pages)
            plat_entry["suspicious_buyers_total"] += max(0, suspicious_buyers)
            plat_entry["suspicious_pages_total"] += max(0, risky_pages)
            plat_entry["pincode_pages_total"] += max(0, pincode_pages)
            plat_entry["normal_pages_total"] += max(0, normal_pages)
            if platform in {"meesho", "flipkart"} and _is_premium_crop_options_enabled(options):
                billed_labels = output_labels if output_labels > 0 else input_pages
                billed_labels = max(0, int(billed_labels))
                summary["premium_labels_billed"] += billed_labels
                plat_entry["premium_labels_billed"] += billed_labels
        elif status == "failed":
            summary["failed_jobs"] += 1
            plat_entry["failed_jobs"] += 1
        elif status == "processing":
            summary["processing_jobs"] += 1
            plat_entry["processing_jobs"] += 1
        elif status == "pending":
            summary["pending_jobs"] += 1
            plat_entry["pending_jobs"] += 1

        created_text = str(row["created_at"] or "").strip()
        if created_text.startswith(today_iso_prefix):
            summary["jobs_today"] += 1
        created_dt = _parse_iso(created_text)
        if created_dt and created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        if created_dt and created_dt >= last_7d_threshold:
            summary["jobs_7d"] += 1
        if created_dt and (last_activity_dt is None or created_dt > last_activity_dt):
            last_activity_dt = created_dt
        if created_text and (
            not plat_entry["last_run_at"] or created_text > plat_entry["last_run_at"]
        ):
            plat_entry["last_run_at"] = created_text

        if len(recent_visible) < safe_recent:
            recent_visible.append(
                {
                    "id": row["id"],
                    "platform": platform,
                    "status": status,
                    "created_at": created_text,
                    "finished_at": str(row["finished_at"] or ""),
                    "duration_ms": int(row["duration_ms"] or 0),
                    "total_input_pages": input_pages,
                    "total_output_labels": output_labels,
                    "total_input_files": input_files,
                    "layout": str(row["layout"] or ""),
                    "sort_by": str(row["sort_by"] or ""),
                    "error_message": str(row["error_message"] or ""),
                    "download_available": bool(download_info["download_available"]),
                }
            )

    if last_activity_dt is not None:
        summary["last_activity_at"] = last_activity_dt.isoformat()

    platforms_sorted = sorted(
        platform_acc.values(),
        key=lambda entry: (-int(entry.get("total_jobs") or 0), entry.get("platform") or ""),
    )

    (
        manual_customers_total,
        manual_suborders_total,
        manual_customers_7d,
        manual_suborders_7d,
    ) = _user_manual_high_risk_totals(safe_user_id)

    return {
        "summary": summary,
        "platforms": platforms_sorted,
        "recent_jobs": recent_visible,
        "manual_high_risk": {
            "customers_total": int(manual_customers_total),
            "suborders_total": int(manual_suborders_total),
            "customers_7d": int(manual_customers_7d),
            "suborders_7d": int(manual_suborders_7d),
        },
    }


def reconcile_stale_processing_jobs(*, max_processing_age_minutes: int = 120) -> int:
    threshold_dt = datetime.now(timezone.utc) - timedelta(minutes=max(5, int(max_processing_age_minutes)))
    threshold_iso = threshold_dt.isoformat()
    finished_at = _utc_now_iso()
    with _db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM crop_jobs
            WHERE status = 'processing'
              AND started_at <> ''
              AND started_at < ?
            """,
            (threshold_iso,),
        ).fetchall()
        stale_ids = [int(r["id"]) for r in rows]
        if not stale_ids:
            return 0
        placeholders = ",".join("?" for _ in stale_ids)
        conn.execute(
            f"""
            UPDATE crop_jobs
            SET status = 'failed',
                error_message = 'Job timed out while processing. Please retry.',
                finished_at = ?,
                duration_ms = CASE
                    WHEN started_at <> '' THEN CAST((julianday(?) - julianday(started_at)) * 86400000 AS INTEGER)
                    ELSE duration_ms
                END
            WHERE id IN ({placeholders})
            """,
            (finished_at, finished_at, *stale_ids),
        )
    return len(stale_ids)
