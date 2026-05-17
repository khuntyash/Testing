"""
Run:  cd backend && python -m uvicorn server:app --reload --port 8000
Vite proxies /api -> http://127.0.0.1:8000
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import shutil
import tempfile
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("labelhub")

import fitz
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

from auth_store import (
    DB_PATH,
    add_wallet_credit,
    count_admin_wallet_credit_audit,
    authenticate_user,
    count_admin_role_audit,
    count_users,
    create_session,
    create_user,
    delete_session,
    get_user_id_by_email,
    get_session_user,
    get_wallet,
    init_db,
    list_admin_wallet_credit_audit,
    list_admin_role_audit,
    list_admin_role_audit_cursor,
    list_users,
    list_users_cursor,
    set_user_admin_role,
    set_users_admin_role_bulk,
    spend_wallet_coins,
    update_user_name,
)
from history_store import (
    aggregate_crop_totals_for_users,
    count_admin_crop_jobs,
    count_active_jobs,
    count_crop_jobs_for_user,
    create_crop_job,
    get_admin_metrics,
    get_user_dashboard_metrics,
    list_admin_crop_jobs,
    get_crop_job_for_user,
    init_history_db,
    list_crop_jobs_for_user,
    mark_crop_job_failed,
    mark_crop_job_started,
    mark_crop_job_success,
    reconcile_stale_processing_jobs,
)
from meesho_service import process_uploaded_paths as process_meesho_uploaded_paths
from flipkart_service import process_uploaded_paths as process_flipkart_uploaded_paths
from label_ocr_service import HEADERS as OCR_MASTER_HEADERS, build_csv_bytes
from task_queue import (
    _download_s3_uri_to_file,
    fail_orphan_running_tasks,
    redis_ocr_master_lookup_enabled,
    SUPPORTED_OCR_PLATFORMS,
    count_admin_ocr_tasks,
    count_admin_return_tasks,
    get_customer_history_by_suborder,
    get_latest_successful_ocr_result_for_user,
    get_latest_suspicious_profile_result_for_user,
    get_suspicious_profile_platform_status_for_user,
    get_ocr_master_platform_status_for_user,
    get_task_for_user,
    lookup_idempotent_task_id,
    get_or_create_idempotent_task,
    get_task_public_for_user,
    get_queue_metrics,
    init_task_queue_db,
    list_admin_ocr_tasks,
    list_admin_return_tasks,
    read_admin_ocr_task_rows,
    read_admin_return_task_rows,
    get_analysis_artifact_snapshot_bytes_for_user,
    delete_stored_task_result,
    purge_finished_crop_artifacts,
    start_embedded_worker,
    sync_recent_user_tasks_from_redis,
    upload_task_inputs_to_s3,
)
from hybrid.database import check_database_ready
from hybrid.runtime import get_runtime_backends
from hybrid.storage import S3ArtifactStore, parse_s3_uri_to_bucket_key

app = FastAPI(title="LabelHub crop API")

def _env_flag(name: str, default: str = "") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        value = int(default)
    else:
        try:
            value = int(raw)
        except Exception:
            value = int(default)
    if minimum is not None:
        value = max(minimum, value)
    return value


BASELINE_WORKER_TASKS = _env_int("BASELINE_WORKER_TASKS", 4, minimum=1)
BASELINE_ACTIVE_JOBS_PER_WORKER = _env_int("BASELINE_ACTIVE_JOBS_PER_WORKER", 12, minimum=1)
BASELINE_ACTIVE_JOBS_HEADROOM_PERCENT = _env_int("BASELINE_ACTIVE_JOBS_HEADROOM_PERCENT", 25, minimum=0)
_baseline_capacity = BASELINE_WORKER_TASKS * BASELINE_ACTIVE_JOBS_PER_WORKER
_baseline_headroom = int((_baseline_capacity * BASELINE_ACTIVE_JOBS_HEADROOM_PERCENT) / 100)
DEFAULT_MAX_ACTIVE_JOBS_GLOBAL = max(20, _baseline_capacity + _baseline_headroom)

MAX_UPLOAD_FILES = int(os.getenv("MAX_UPLOAD_FILES", "0"))
MAX_UPLOAD_BYTES_PER_FILE = int(os.getenv("MAX_UPLOAD_BYTES_PER_FILE", "0"))
MAX_UPLOAD_TOTAL_BYTES = int(os.getenv("MAX_UPLOAD_TOTAL_BYTES", "0"))
MAX_UPLOAD_TOTAL_PAGES = int(os.getenv("MAX_UPLOAD_TOTAL_PAGES", "0"))
MAX_ACTIVE_JOBS_GLOBAL = _env_int("MAX_ACTIVE_JOBS_GLOBAL", DEFAULT_MAX_ACTIVE_JOBS_GLOBAL, minimum=1)
MAX_ACTIVE_JOBS_PER_USER = _env_int("MAX_ACTIVE_JOBS_PER_USER", 6, minimum=0)
STALE_JOB_MINUTES = int(os.getenv("STALE_JOB_MINUTES", "20"))
DOWNLOAD_RETENTION_HOURS = int(os.getenv("DOWNLOAD_RETENTION_HOURS", "24"))
DOWNLOAD_EXPIRY_MODE = (os.getenv("DOWNLOAD_EXPIRY_MODE", "calendar_day") or "calendar_day").strip().lower()
FAIL_ORPHAN_RUNNING_TASKS_ON_STARTUP = (
    os.getenv("FAIL_ORPHAN_RUNNING_TASKS_ON_STARTUP", "").strip().lower() in {"1", "true", "yes"}
)
BASELINE_REQUIRE_REDIS_QUEUE = _env_flag("BASELINE_REQUIRE_REDIS_QUEUE", "1")
BASELINE_REQUIRE_S3_STORAGE = _env_flag("BASELINE_REQUIRE_S3_STORAGE", "1")
BASELINE_REQUIRE_FANOUT_DISABLED = _env_flag("BASELINE_REQUIRE_FANOUT_DISABLED", "1")
BASELINE_REQUIRE_EXTERNAL_WORKERS = _env_flag("BASELINE_REQUIRE_EXTERNAL_WORKERS", "1")
ENFORCE_LATENCY_BASELINE = _env_flag("ENFORCE_LATENCY_BASELINE", "0")


def _use_redis_queue() -> bool:
    return (os.getenv("QUEUE_BACKEND", "sqlite") or "sqlite").strip().lower() == "redis"


def _use_s3_storage() -> bool:
    return (os.getenv("STORAGE_BACKEND", "local") or "local").strip().lower() == "s3"

_maintenance_thread_started = False


# Always merged with CORS_ORIGINS from the environment so a partial ECS value
# (for example only a preview URL) cannot lock out the production SPA domain.
_CANONICAL_CORS_ORIGINS: tuple[str, ...] = (
    "https://zerolabelcropper.com",
    "https://www.zerolabelcropper.com",
    "http://zerolabelcropper.com",
    "http://www.zerolabelcropper.com",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)


def _default_cors_origin_regex() -> str:
    # Permit both apex and subdomains for the production site so CORS does not
    # break when traffic shifts between www/non-www or preview subdomains.
    return r"^https?://([a-zA-Z0-9-]+\.)*zerolabelcropper\.com$"


def _parse_cors_origins() -> list[str]:
    raw = (os.getenv("CORS_ORIGINS", "") or "").strip()
    from_env = [part.strip() for part in raw.split(",") if part.strip()] if raw else []
    merged: list[str] = []
    seen: set[str] = set()
    for origin in [*from_env, *_CANONICAL_CORS_ORIGINS]:
        if origin not in seen:
            seen.add(origin)
            merged.append(origin)
    return merged


def _parse_cors_origin_regex() -> str | None:
    raw = (os.getenv("CORS_ORIGIN_REGEX", "") or "").strip()
    pattern = raw or _default_cors_origin_regex()
    try:
        re.compile(pattern)
    except re.error:
        logger.warning(
            "Invalid CORS_ORIGIN_REGEX %r; using default production pattern",
            pattern,
        )
        pattern = _default_cors_origin_regex()
    return pattern


def _validate_runtime_baseline() -> None:
    runtime_checks = [
        ("redis queue backend", not BASELINE_REQUIRE_REDIS_QUEUE or _use_redis_queue()),
        ("s3 storage backend", not BASELINE_REQUIRE_S3_STORAGE or _use_s3_storage()),
        (
            "fanout disabled",
            not BASELINE_REQUIRE_FANOUT_DISABLED or not _env_flag("DISTRIBUTED_PDF_FANOUT"),
        ),
        (
            "api embedded workers disabled",
            not BASELINE_REQUIRE_EXTERNAL_WORKERS or _env_flag("DISABLE_EMBEDDED_WORKER"),
        ),
    ]
    for label, ok in runtime_checks:
        if ok:
            continue
        message = f"Latency baseline check failed: {label}"
        if ENFORCE_LATENCY_BASELINE:
            raise RuntimeError(message)
        logger.warning("%s (set ENFORCE_LATENCY_BASELINE=1 to hard-fail startup)", message)


def _start_maintenance_loop() -> None:
    global _maintenance_thread_started
    if _maintenance_thread_started:
        return
    _maintenance_thread_started = True

    def _run() -> None:
        while True:
            try:
                reconcile_stale_processing_jobs(max_processing_age_minutes=STALE_JOB_MINUTES)
                # Nightly-style cleanup: cropped label files only (OCR masters / risk CSVs stay).
                purge_finished_crop_artifacts(older_than_hours=DOWNLOAD_RETENTION_HOURS)
            except Exception:
                logger.exception("Maintenance loop iteration failed")
            time.sleep(300)

    import threading

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_utc(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp
    except Exception:
        return None


def _task_download_expired(task: dict) -> bool:
    finished_at = _parse_iso_utc(task.get("finished_at"))
    updated_at = _parse_iso_utc(task.get("updated_at"))
    created_at = _parse_iso_utc(task.get("created_at"))
    anchor = finished_at or updated_at or created_at
    if not anchor:
        return False
    if DOWNLOAD_EXPIRY_MODE in {"calendar_day", "daily", "midnight"}:
        local_anchor = anchor.astimezone()
        next_midnight_local = (local_anchor + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        expires_at = next_midnight_local.astimezone(timezone.utc)
    else:
        retention_hours = max(1, int(DOWNLOAD_RETENTION_HOURS))
        expires_at = anchor + timedelta(hours=retention_hours)
    return datetime.now(timezone.utc) > expires_at


def _cleanup_task_output_artifacts(task: dict) -> None:
    result_path = str(task.get("result_path") or "").strip()
    if result_path:
        delete_stored_task_result(result_path)
    payload = task.get("payload") or {}
    output_dir = str(payload.get("output_dir") or "").strip()
    if output_dir:
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass


def _form_bool(v: str | None) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _form_int(v: str | None, default: int = 0, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(str(v or "").strip() or str(default))
    except Exception:
        value = int(default)
    if minimum is not None:
        value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


PREMIUM_CROP_COIN_COST_PER_LABEL = max(0, int(os.getenv("PREMIUM_CROP_COIN_COST_PER_LABEL", "1") or 1))


def _premium_crop_options_enabled(options: dict | None) -> bool:
    if not isinstance(options, dict):
        return False
    separate_pincodes = str(options.get("separate_pincodes") or options.get("separatePincodes") or "").strip()
    return bool(
        _form_bool(str(options.get("detect_suspicious") or "0"))
        or _form_bool(str(options.get("mark_suspicious_preview") or "0"))
        or _form_bool(str(options.get("separate_multi_order_by_customer") or "0"))
        or _form_bool(str(options.get("mark_loyal_customer") or "0"))
        or _form_bool(str(options.get("mark_loyal_customer_preview") or "0"))
        or separate_pincodes
    )


def _ensure_premium_wallet_capacity(user_id: int, *, total_pages: int, options: dict | None) -> None:
    if not _premium_crop_options_enabled(options):
        return
    required = max(0, int(total_pages or 0)) * PREMIUM_CROP_COIN_COST_PER_LABEL
    if required <= 0:
        return
    wallet = get_wallet(int(user_id))
    balance = int((wallet or {}).get("balance") or 0)
    if balance < required:
        raise HTTPException(
            402,
            f"Not enough coins for premium crop. Required {required}, available {balance}.",
        )


def _extract_bearer_token(auth_header: str | None) -> str:
    if not auth_header:
        return ""
    value = auth_header.strip()
    if not value.lower().startswith("bearer "):
        return ""
    return value[7:].strip()


def _require_session_user(auth_header: str | None) -> dict:
    token = _extract_bearer_token(auth_header)
    user = get_session_user(token)
    if not user:
        raise HTTPException(401, "Unauthorized")
    return user


def _require_admin_user(auth_header: str | None) -> dict:
    user = _require_session_user(auth_header)
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin access required.")
    return user


def _enrich_admin_users(rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    ids = [int(r.get("id") or 0) for r in rows if int(r.get("id") or 0) > 0]
    totals_by_user = aggregate_crop_totals_for_users(ids)
    out: list[dict] = []
    for row in rows:
        uid = int(row.get("id") or 0)
        totals = totals_by_user.get(uid) or {}
        has_master_ocr_data = False
        has_suspicious_customer_data = False
        suspicious_platform_status: dict = {}
        platform_status: dict = {}
        if uid > 0:
            try:
                if redis_ocr_master_lookup_enabled():
                    sync_recent_user_tasks_from_redis(uid, limit=120)
            except Exception:
                logger.exception("admin Redis task sync failed user_id=%s", uid)
            try:
                platform_status = get_ocr_master_platform_status_for_user(uid)
            except Exception:
                platform_status = {}
            try:
                has_master_ocr_data = bool(get_latest_successful_ocr_result_for_user(uid))
            except Exception:
                has_master_ocr_data = False
            if not has_master_ocr_data and platform_status:
                has_master_ocr_data = any(
                    bool((platform_status.get(p) or {}).get("available"))
                    for p in SUPPORTED_OCR_PLATFORMS
                )
            try:
                has_suspicious_customer_data = bool(get_latest_suspicious_profile_result_for_user(uid))
            except Exception:
                has_suspicious_customer_data = False
            try:
                suspicious_platform_status = get_suspicious_profile_platform_status_for_user(uid)
            except Exception:
                suspicious_platform_status = {}
            if not has_suspicious_customer_data and suspicious_platform_status:
                has_suspicious_customer_data = any(
                    bool((suspicious_platform_status.get(p) or {}).get("available"))
                    for p in SUPPORTED_OCR_PLATFORMS
                )
        per_platform_flags: dict[str, bool] = {}
        per_platform_counts: dict[str, int] = {}
        suspicious_platform_flags: dict[str, bool] = {}
        suspicious_platform_counts: dict[str, int] = {}
        for platform in SUPPORTED_OCR_PLATFORMS:
            info = (platform_status or {}).get(platform) or {}
            per_platform_flags[f"has_{platform}_master_ocr_data"] = bool(info.get("available"))
            per_platform_counts[f"{platform}_master_records"] = int(info.get("row_count") or 0)
            suspicious_info = (suspicious_platform_status or {}).get(platform) or {}
            suspicious_platform_flags[f"has_{platform}_suspicious_customer_data"] = bool(
                suspicious_info.get("available")
            )
            suspicious_platform_counts[f"{platform}_suspicious_records"] = int(
                suspicious_info.get("row_count") or 0
            )
        out.append(
            {
                **row,
                "total_labels_processed": int(totals.get("labels", 0)),
                "risky_customer_count": int(totals.get("risky", 0)),
                "has_master_ocr_data": has_master_ocr_data,
                "has_suspicious_customer_data": has_suspicious_customer_data,
                **per_platform_flags,
                **per_platform_counts,
                **suspicious_platform_flags,
                **suspicious_platform_counts,
            }
        )
    return out


def _normalize_admin_users_sort(value: str | None) -> str:
    allowed = {
        "default",
        "labels_desc",
        "labels_asc",
        "risky_desc",
        "risky_asc",
        "email_desc",
        "email_asc",
    }
    clean = (value or "").strip().lower()
    return clean if clean in allowed else "default"


def _list_all_users_for_query(clean_query: str) -> list[dict]:
    rows: list[dict] = []
    cursor: int | None = None
    while True:
        batch, next_cursor = list_users_cursor(query=clean_query, limit=100, cursor=cursor)
        if not batch:
            break
        rows.extend(batch)
        if next_cursor is None:
            break
        cursor = next_cursor
    return rows


def _sort_admin_users(rows: list[dict], users_sort: str) -> list[dict]:
    if users_sort == "default" or len(rows) <= 1:
        return rows
    out = list(rows)
    reverse = users_sort.endswith("_desc")
    if users_sort.startswith("labels_"):
        out.sort(
            key=lambda row: (
                int(row.get("total_labels_processed") or 0),
                int(row.get("id") or 0),
            ),
            reverse=reverse,
        )
        return out
    if users_sort.startswith("risky_"):
        out.sort(
            key=lambda row: (
                int(row.get("risky_customer_count") or 0),
                int(row.get("id") or 0),
            ),
            reverse=reverse,
        )
        return out
    out.sort(
        key=lambda row: (
            str(row.get("email") or "").lower(),
            int(row.get("id") or 0),
        ),
        reverse=reverse,
    )
    return out


def _safe_pdf_page_count(pdf_bytes: bytes) -> int:
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return int(doc.page_count)
    except Exception:
        return 0


def _safe_pdf_page_count_from_path(path: str) -> int:
    try:
        with fitz.open(path) as doc:
            return int(doc.page_count)
    except Exception:
        return 0


def _ensure_enqueue_capacity(user_id: int, platform: str) -> None:
    # Opportunistically reconcile stale processing jobs before capacity checks
    # so interrupted/reloaded runs do not block fresh uploads for long.
    try:
        reconcile_stale_processing_jobs(max_processing_age_minutes=STALE_JOB_MINUTES)
    except Exception:
        logger.exception("Failed to reconcile stale jobs before enqueue capacity check")
    global_active = count_active_jobs()
    if global_active >= MAX_ACTIVE_JOBS_GLOBAL:
        raise HTTPException(429, "System is currently at capacity. Please retry in a few minutes.")
    user_active = count_active_jobs(user_id=int(user_id))
    if MAX_ACTIVE_JOBS_PER_USER > 0 and user_active >= MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(429, "You already have too many active jobs. Wait for existing jobs to finish.")
    platform_active = count_active_jobs(user_id=int(user_id), platform=platform)
    if MAX_ACTIVE_JOBS_PER_USER > 0 and platform_active >= MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(429, f"Too many active {platform} jobs for this account.")


def _enqueue_auto_ocr_from_crop(
    *,
    user_id: int,
    source_job_id: int,
    source_platform: str,
    input_paths: list[str],
    input_file_rows: list[dict],
    total_input_pages: int,
) -> str:
    if not input_paths:
        return ""
    ocr_idem_key = f"auto-ocr-crop:{int(user_id)}:{int(source_job_id)}"
    existing_ocr_task = lookup_idempotent_task_id(
        user_id=int(user_id),
        task_type="ocr_csv",
        idem_key=ocr_idem_key,
    )
    if existing_ocr_task:
        logger.info(
            "Auto OCR deduped user_id=%s source_crop_job_id=%s task_id=%s",
            int(user_id),
            int(source_job_id),
            existing_ocr_task,
        )
        return existing_ocr_task
    ocr_tmpdir = tempfile.mkdtemp(prefix="auto_ocr_from_crop_")
    ocr_tmp_path = Path(ocr_tmpdir)
    ocr_job_id: int | None = None
    copied_paths: list[str] = []
    try:
        for idx, src in enumerate(input_paths):
            copied = ocr_tmp_path / f"in_{idx}.pdf"
            shutil.copy2(src, copied)
            copied_paths.append(str(copied))
        options = {
            "column_preset": "standard_v1",
            "custom_columns": "",
            "stored_on_server_only": True,
            "auto_collected_from_crop": True,
            "source_crop_job_id": int(source_job_id),
            "source_platform": source_platform,
        }
        ocr_job_id = create_crop_job(
            user_id=int(user_id),
            platform="ocr_labels",
            sort_by="standard_v1",
            layout="csv",
            options=options,
        )
        mark_crop_job_started(ocr_job_id)
        payload = {
            "output_dir": ocr_tmpdir,
            "input_paths": copied_paths,
            "input_files": input_file_rows or [],
            "total_input_files": len(input_file_rows or []),
            "total_input_pages": int(total_input_pages or 0),
            "max_workers": min(8, max(1, (os.cpu_count() or 4))),
            "options": options,
        }
        _attach_remote_task_inputs(payload, user_id=int(user_id))
        if _use_redis_queue() and _use_s3_storage() and not (payload.get("input_s3_keys") or []):
            logger.error(
                "Auto OCR has no input_s3_keys after upload; remote worker cannot read PDFs. user_id=%s ocr_job_id=%s",
                int(user_id),
                int(ocr_job_id),
            )
        task_id, _ = get_or_create_idempotent_task(
            user_id=int(user_id),
            job_id=int(ocr_job_id),
            task_type="ocr_csv",
            idem_key=ocr_idem_key,
            payload=payload,
            reuse_on_idem_key_match=True,
        )
        # Only delete local OCR uploads once they are mirrored to object storage.
        # Redis-queue + missing S3 keys would otherwise leave workers with dead paths
        # and silently skip master CSV generation for every user.
        if _use_redis_queue() and _use_s3_storage() and bool(payload.get("input_s3_keys")):
            shutil.rmtree(ocr_tmpdir, ignore_errors=True)
        logger.info(
            "Auto OCR enqueued user_id=%s ocr_job_id=%s task_id=%s s3_inputs=%s",
            int(user_id),
            int(ocr_job_id),
            task_id,
            bool(payload.get("input_s3_keys")),
        )
        return task_id
    except Exception:
        if ocr_job_id is not None:
            try:
                mark_crop_job_failed(
                    int(ocr_job_id),
                    error_message="Auto OCR enqueue failed.",
                    duration_ms=0,
                    input_files=input_file_rows or [],
                )
            except Exception:
                logger.exception("Could not mark auto OCR job %s as failed", ocr_job_id)
        shutil.rmtree(ocr_tmpdir, ignore_errors=True)
        raise


async def _prepare_uploaded_pdf_payload(files: list[UploadFile], *, tmp_prefix: str) -> tuple[str, list[str], list[dict], int]:
    if not files:
        raise HTTPException(400, "No files uploaded")
    if MAX_UPLOAD_FILES > 0 and len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(413, f"Too many files. Maximum allowed is {MAX_UPLOAD_FILES}.")
    tmpdir = tempfile.mkdtemp(prefix=tmp_prefix)
    tmp_path = Path(tmpdir)
    input_paths: list[str] = []
    input_file_rows: list[dict] = []
    total_pages = 0
    total_bytes = 0
    try:
        for i, upload in enumerate(files):
            filename = upload.filename or f"in_{i}.pdf"
            name = filename.lower()
            if upload.content_type not in ("application/pdf", "application/octet-stream") and not name.endswith(".pdf"):
                raise HTTPException(400, f"Not a PDF: {filename}")
            raw = await upload.read()
            if not raw:
                raise HTTPException(400, f"Empty file: {filename}")
            if MAX_UPLOAD_BYTES_PER_FILE > 0 and len(raw) > MAX_UPLOAD_BYTES_PER_FILE:
                raise HTTPException(413, f"{filename} exceeds max file size limit.")
            total_bytes += len(raw)
            if MAX_UPLOAD_TOTAL_BYTES > 0 and total_bytes > MAX_UPLOAD_TOTAL_BYTES:
                raise HTTPException(413, "Upload payload exceeds total size limit.")
            page_count = _safe_pdf_page_count(raw)
            if page_count <= 0:
                raise HTTPException(400, f"Unreadable PDF: {filename}")
            total_pages += page_count
            if MAX_UPLOAD_TOTAL_PAGES > 0 and total_pages > MAX_UPLOAD_TOTAL_PAGES:
                raise HTTPException(413, f"Total page count exceeds limit ({MAX_UPLOAD_TOTAL_PAGES}).")
            path = tmp_path / f"in_{i}.pdf"
            path.write_bytes(raw)
            input_paths.append(str(path))
            input_file_rows.append({"file_name": filename, "input_pages": page_count})
        return tmpdir, input_paths, input_file_rows, total_pages
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


def _attach_remote_task_inputs(payload: dict, *, user_id: int) -> None:
    if not (_use_redis_queue() and _use_s3_storage()):
        return
    input_paths = [str(path) for path in (payload.get("input_paths") or []) if str(path).strip()]
    if not input_paths:
        return
    upload_batch_id = payload.get("upload_batch_id") or f"upload-{int(time.time())}-{os.urandom(4).hex()}"
    payload["upload_batch_id"] = upload_batch_id
    uploaded = upload_task_inputs_to_s3(
        task_id=str(upload_batch_id),
        input_paths=input_paths,
        user_id=int(user_id),
    )
    if uploaded:
        payload["input_s3_keys"] = uploaded


async def _prepare_uploaded_excel_file(upload: UploadFile, *, tmp_prefix: str) -> tuple[str, str]:
    filename = upload.filename or "returns.xlsx"
    lower = filename.lower()
    allowed = {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/octet-stream",
    }
    if upload.content_type not in allowed and not (lower.endswith(".xlsx") or lower.endswith(".xls")):
        raise HTTPException(400, f"Not an Excel file: {filename}")
    raw = await upload.read()
    if not raw:
        raise HTTPException(400, "Uploaded return Excel is empty.")
    if MAX_UPLOAD_BYTES_PER_FILE > 0 and len(raw) > MAX_UPLOAD_BYTES_PER_FILE:
        raise HTTPException(413, "Return Excel exceeds max file size limit.")
    tmpdir = tempfile.mkdtemp(prefix=tmp_prefix)
    suffix = ".xlsx" if lower.endswith(".xlsx") else ".xls"
    out_path = Path(tmpdir) / f"returns{suffix}"
    out_path.write_bytes(raw)
    return tmpdir, str(out_path)


class AuthPayload(BaseModel):
    email: str
    password: str
    name: str | None = None


class ProfilePayload(BaseModel):
    name: str


class AdminRolePayload(BaseModel):
    is_admin: bool


class AdminBulkRolePayload(BaseModel):
    user_ids: list[int]
    is_admin: bool


class WalletSpendPayload(BaseModel):
    amount: int
    note: str | None = None


class AdminWalletCreditPayload(BaseModel):
    target_user_id: int | None = None
    target_email: str | None = None
    amount: int
    note: str | None = None


app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_origin_regex=_parse_cors_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Expose redirect Location so browsers can read it when using fetch(..., redirect="manual").
    expose_headers=["Location", "Content-Disposition"],
)


@app.on_event("startup")
def on_startup():
    _validate_runtime_baseline()
    init_db()
    init_history_db()
    init_task_queue_db()
    if FAIL_ORPHAN_RUNNING_TASKS_ON_STARTUP:
        cleaned_running = fail_orphan_running_tasks()
        if cleaned_running:
            logger.warning("Marked %s orphan running queue task(s) as failed on startup", cleaned_running)
    reconciled = reconcile_stale_processing_jobs(max_processing_age_minutes=STALE_JOB_MINUTES)
    if reconciled:
        logger.warning("Reconciled %s stale processing jobs on startup", reconciled)
    # Clean old crop artifacts on startup, but keep history/task rows intact.
    purge_finished_crop_artifacts(older_than_hours=DOWNLOAD_RETENTION_HOURS)
    start_embedded_worker()
    _start_maintenance_loop()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/ready")
def ready():
    runtime = get_runtime_backends()
    ok, detail = check_database_ready(runtime.db_backend, DB_PATH)
    if not ok:
        raise HTTPException(503, f"Database unavailable: {detail}")
    return {"ok": True}


@app.get("/api/admin/ops/metrics")
def admin_ops_metrics(authorization: str | None = Header(default=None)):
    _require_admin_user(authorization)
    return {
        "queue": get_queue_metrics(),
        "limits": {
            "max_upload_files": MAX_UPLOAD_FILES,
            "max_upload_bytes_per_file": MAX_UPLOAD_BYTES_PER_FILE,
            "max_upload_total_bytes": MAX_UPLOAD_TOTAL_BYTES,
            "max_upload_total_pages": MAX_UPLOAD_TOTAL_PAGES,
            "max_active_jobs_global": MAX_ACTIVE_JOBS_GLOBAL,
            "max_active_jobs_per_user": MAX_ACTIVE_JOBS_PER_USER,
            "stale_job_minutes": STALE_JOB_MINUTES,
        },
        "baseline": {
            "enforce": ENFORCE_LATENCY_BASELINE,
            "require_redis_queue": BASELINE_REQUIRE_REDIS_QUEUE,
            "require_s3_storage": BASELINE_REQUIRE_S3_STORAGE,
            "require_fanout_disabled": BASELINE_REQUIRE_FANOUT_DISABLED,
            "require_external_workers": BASELINE_REQUIRE_EXTERNAL_WORKERS,
            "default_max_active_jobs_global": DEFAULT_MAX_ACTIVE_JOBS_GLOBAL,
            "max_active_jobs_global": MAX_ACTIVE_JOBS_GLOBAL,
            "max_active_jobs_per_user": MAX_ACTIVE_JOBS_PER_USER,
        },
    }


@app.get("/api/admin/ops/runtime")
def admin_ops_runtime(authorization: str | None = Header(default=None)):
    _require_admin_user(authorization)
    runtime = get_runtime_backends()
    return {
        "db_backend": runtime.db_backend,
        "queue_backend": runtime.queue_backend,
        "storage_backend": runtime.storage_backend,
        "api_platform": runtime.api_platform,
    }


@app.post("/api/auth/signup")
def auth_signup(payload: AuthPayload):
    try:
        user = create_user(payload.name or "", payload.email or "", payload.password or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    token = create_session(user["id"])
    return {
        "user": {
            "email": user["email"],
            "name": user["name"],
            "is_admin": bool(user.get("is_admin")),
            "is_premium": bool(user.get("is_premium")),
        },
        "token": token,
    }


@app.post("/api/auth/login")
def auth_login(payload: AuthPayload):
    user = authenticate_user(payload.email or "", payload.password or "")
    if not user:
        raise HTTPException(401, "Invalid email or password.")
    token = create_session(user["id"])
    return {
        "user": {
            "email": user["email"],
            "name": user["name"],
            "is_admin": bool(user.get("is_admin")),
            "is_premium": bool(user.get("is_premium")),
        },
        "token": token,
    }


@app.get("/api/auth/me")
def auth_me(authorization: str | None = Header(default=None)):
    user = _require_session_user(authorization)
    return {
        "user": {
            "email": user["email"],
            "name": user["name"],
            "is_admin": bool(user.get("is_admin")),
            "is_premium": bool(user.get("is_premium")),
        }
    }


@app.post("/api/auth/logout")
def auth_logout(authorization: str | None = Header(default=None)):
    token = _extract_bearer_token(authorization)
    delete_session(token)
    return {"ok": True}


@app.patch("/api/auth/profile")
def auth_update_profile(payload: ProfilePayload, authorization: str | None = Header(default=None)):
    user = _require_session_user(authorization)
    try:
        updated = update_user_name(user["id"], payload.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "user": {
            "email": updated["email"],
            "name": updated["name"],
            "is_admin": bool(updated.get("is_admin")),
            "is_premium": bool(updated.get("is_premium")),
        }
    }


@app.get("/api/wallet")
def user_wallet(authorization: str | None = Header(default=None)):
    user = _require_session_user(authorization)
    try:
        wallet = get_wallet(int(user["id"]))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return wallet


@app.post("/api/wallet/spend")
def user_wallet_spend(payload: WalletSpendPayload, authorization: str | None = Header(default=None)):
    user = _require_session_user(authorization)
    try:
        result = spend_wallet_coins(
            user_id=int(user["id"]),
            amount=int(payload.amount or 0),
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@app.get("/api/admin/metrics")
def admin_metrics(authorization: str | None = Header(default=None)):
    _require_admin_user(authorization)
    try:
        return {"metrics": get_admin_metrics()}
    except Exception:
        # Keep admin usable if metrics aggregation hits transient DB/filesystem issues.
        logger.exception("admin metrics failed")
        return {
            "metrics": {
                "total_users": 0,
                "total_jobs": 0,
                "total_success": 0,
                "total_failed": 0,
                "jobs_today": 0,
                "active_users_7d": 0,
                "manual_high_risk_customers_total": 0,
                "manual_high_risk_suborders_total": 0,
                "manual_high_risk_customers_7d": 0,
                "manual_high_risk_suborders_7d": 0,
                "degraded": True,
            }
        }


@app.get("/api/admin/jobs")
def admin_jobs(
    authorization: str | None = Header(default=None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    _require_admin_user(authorization)
    jobs = list_admin_crop_jobs(limit=limit, offset=offset)
    total = count_admin_crop_jobs()
    return {"jobs": jobs, "total": total}


@app.get("/api/admin/users")
def admin_users(
    authorization: str | None = Header(default=None),
    query: str = Query("", max_length=120),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query("default", max_length=24),
):
    _require_admin_user(authorization)
    clean_query = (query or "").strip()
    users_sort = _normalize_admin_users_sort(sort)
    if users_sort == "default":
        users = _enrich_admin_users(list_users(query=clean_query, limit=limit, offset=offset))
    else:
        all_rows = _sort_admin_users(
            _enrich_admin_users(_list_all_users_for_query(clean_query)),
            users_sort,
        )
        safe_offset = max(int(offset), 0)
        users = all_rows[safe_offset : safe_offset + int(limit)]
    total = count_users(query=clean_query)
    return {"users": users, "total": total}


@app.get("/api/admin/users/cursor")
def admin_users_cursor(
    authorization: str | None = Header(default=None),
    query: str = Query("", max_length=120),
    limit: int = Query(20, ge=1, le=100),
    cursor: int | None = Query(default=None),
    sort: str = Query("default", max_length=24),
):
    _require_admin_user(authorization)
    clean_query = (query or "").strip()
    users_sort = _normalize_admin_users_sort(sort)
    if users_sort == "default":
        users, next_cursor = list_users_cursor(query=clean_query, limit=limit, cursor=cursor)
        users = _enrich_admin_users(users)
    else:
        all_rows = _sort_admin_users(
            _enrich_admin_users(_list_all_users_for_query(clean_query)),
            users_sort,
        )
        safe_cursor = max(int(cursor or 0), 0)
        safe_limit = max(int(limit), 1)
        users = all_rows[safe_cursor : safe_cursor + safe_limit]
        next_cursor = safe_cursor + safe_limit if (safe_cursor + safe_limit) < len(all_rows) else None
    total = count_users(query=clean_query)
    return {
        "users": users,
        "total": total,
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor is not None),
    }


def _attachment_csv_response(content: bytes, attachment_filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{attachment_filename}"',
            "Cache-Control": "no-store",
        },
    )


def _admin_risk_csv_download_response(result_path: str, attachment_filename: str, *, db_fallback: bytes | None = None):
    """Local path or s3:// — suspicious profile CSV for admin download."""
    source = (result_path or "").strip()
    if not source:
        if db_fallback:
            return _attachment_csv_response(db_fallback, attachment_filename)
        raise HTTPException(404, "No suspicious customer data file found for this user.")
    if source.lower().startswith("s3://"):
        cleanup = tempfile.mkdtemp(prefix="risk_csv_dl_")
        try:
            _bucket, obj_key = parse_s3_uri_to_bucket_key(source)
            base_name = (obj_key.rsplit("/", 1)[-1] if obj_key else "") or "suspicious.csv"
            local = Path(cleanup) / base_name
            _download_s3_uri_to_file(source, str(local))
            data = local.read_bytes()
        except Exception:
            if db_fallback:
                return _attachment_csv_response(db_fallback, attachment_filename)
            raise HTTPException(404, "Suspicious customer data file is no longer available.") from None
        finally:
            shutil.rmtree(cleanup, ignore_errors=True)
        return _attachment_csv_response(data, attachment_filename)
    output_path = Path(source)
    if not output_path.is_file():
        if db_fallback:
            return _attachment_csv_response(db_fallback, attachment_filename)
        raise HTTPException(404, "Suspicious customer data file is no longer available.")
    return FileResponse(
        path=str(output_path),
        media_type="text/csv; charset=utf-8",
        filename=attachment_filename,
        headers={"Cache-Control": "no-store"},
    )


def _master_csv_download_response(output_path: Path, filename: str, *, db_fallback: bytes | None = None):
    """Serve master OCR CSV from local path or s3:// artifact.

    S3: download to a temp file, then always buffer the payload into the HTTP
    response before deleting the temp directory. Returning FileResponse for a
    temp path and deleting it in ``finally`` runs *before* the response body
    is streamed, which produced empty/failed admin downloads in production.
    """
    source_path = str(output_path).strip()
    local_path = Path(source_path)
    cleanup_dir = ""
    if source_path.lower().startswith("s3://"):
        cleanup_dir = tempfile.mkdtemp(prefix="master_csv_download_")
        try:
            _bucket, obj_key = parse_s3_uri_to_bucket_key(source_path)
            base_name = (obj_key.rsplit("/", 1)[-1] if obj_key else "") or "master-orders.csv"
            local_path = Path(cleanup_dir) / base_name
        except Exception:
            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)
            if db_fallback:
                return _attachment_csv_response(db_fallback, filename)
            raise HTTPException(404, "OCR master data file is no longer available.") from None
        try:
            _download_s3_uri_to_file(source_path, str(local_path))
        except Exception:
            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)
            if db_fallback:
                return _attachment_csv_response(db_fallback, filename)
            raise HTTPException(404, "OCR master data file is no longer available.") from None
    if not local_path.exists():
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        if db_fallback:
            return _attachment_csv_response(db_fallback, filename)
        raise HTTPException(404, "OCR master data file is no longer available.")
    try:
        with local_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = [str(h or "").lstrip("\ufeff").strip() for h in (reader.fieldnames or [])]
            if headers == list(OCR_MASTER_HEADERS) and not cleanup_dir:
                return FileResponse(
                    path=str(local_path),
                    media_type="text/csv; charset=utf-8",
                    filename=filename,
                    headers={"Cache-Control": "no-store"},
                )
            rows = []
            for row in reader:
                normalized = {header: "" for header in OCR_MASTER_HEADERS}
                for key, value in (row or {}).items():
                    clean_key = str(key or "").lstrip("\ufeff").strip()
                    if clean_key in normalized:
                        normalized[clean_key] = "" if value is None else str(value)
                rows.append(normalized)
        return _attachment_csv_response(
            build_csv_bytes(rows, column_preset="standard_v1", custom_columns=""),
            filename,
        )
    except Exception:
        logger.exception("Failed to normalize master OCR CSV download: %s", source_path)
        try:
            data = local_path.read_bytes()
            return _attachment_csv_response(data, filename)
        except Exception:
            if db_fallback:
                return _attachment_csv_response(db_fallback, filename)
            raise HTTPException(404, "OCR master data file is no longer available.") from None
    finally:
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


@app.get("/api/admin/users/{user_id}/ocr/master/download")
def admin_user_master_ocr_download(user_id: int, authorization: str | None = Header(default=None)):
    _require_admin_user(authorization)
    safe_user_id = int(user_id)
    if safe_user_id <= 0:
        raise HTTPException(400, "Invalid user id.")
    try:
        sync_recent_user_tasks_from_redis(safe_user_id, limit=120)
    except Exception:
        logger.exception("admin master download: redis sync failed user_id=%s", safe_user_id)
    candidates: list[tuple[str, dict]] = []
    seen_paths: set[str] = set()
    latest = get_latest_successful_ocr_result_for_user(safe_user_id)
    if latest:
        rp = str(latest.get("result_path") or "").strip()
        if rp:
            seen_paths.add(rp)
            candidates.append(("legacy", latest))
    # Union file may be missing even when per-platform masters exist (shared
    # volume on API pod, or only platform-scoped artifacts in object storage).
    for plat in SUPPORTED_OCR_PLATFORMS:
        plat_latest = get_latest_successful_ocr_result_for_user(safe_user_id, platform=plat)
        if not plat_latest:
            continue
        rp = str(plat_latest.get("result_path") or "").strip()
        if not rp or rp in seen_paths:
            continue
        seen_paths.add(rp)
        candidates.append((plat, plat_latest))
    if not candidates:
        db_fallback = get_analysis_artifact_snapshot_bytes_for_user(
            user_id=safe_user_id,
            artifact_kind="ocr_master",
            platform=None,
        )
        if db_fallback:
            filename = f"user-{safe_user_id}-master-orders.csv"
            return _attachment_csv_response(db_fallback, filename)
        raise HTTPException(404, "No OCR master data found for this user.")
    filename = f"user-{safe_user_id}-master-orders.csv"
    db_fallback = get_analysis_artifact_snapshot_bytes_for_user(
        user_id=safe_user_id,
        artifact_kind="ocr_master",
        platform=None,
    )
    for source, candidate in candidates:
        result_path = str(candidate.get("result_path") or "").strip()
        if not result_path:
            continue
        try:
            return _master_csv_download_response(Path(result_path), filename, db_fallback=db_fallback)
        except HTTPException as exc:
            if int(exc.status_code) != 404:
                raise
            logger.warning(
                "admin master download fallback: missing artifact user_id=%s source=%s path=%s",
                safe_user_id,
                source,
                result_path,
            )
            continue
    raise HTTPException(404, "OCR master data file is no longer available.")


@app.get("/api/admin/users/{user_id}/ocr/master/{platform}/download")
def admin_user_master_ocr_download_by_platform(
    user_id: int,
    platform: str,
    authorization: str | None = Header(default=None),
):
    """Per-platform variant of the master OCR download.

    Returns 400 for unknown platform values, 404 when no platform-specific
    master CSV exists yet for the user.
    """
    _require_admin_user(authorization)
    safe_user_id = int(user_id)
    if safe_user_id <= 0:
        raise HTTPException(400, "Invalid user id.")
    safe_platform = (platform or "").strip().lower()
    if safe_platform not in SUPPORTED_OCR_PLATFORMS:
        raise HTTPException(
            400,
            f"Unsupported platform '{platform}'. Allowed: {', '.join(SUPPORTED_OCR_PLATFORMS)}.",
        )
    try:
        sync_recent_user_tasks_from_redis(safe_user_id, limit=120)
    except Exception:
        logger.exception("admin master download: redis sync failed user_id=%s", safe_user_id)
    latest = get_latest_successful_ocr_result_for_user(safe_user_id, platform=safe_platform)
    db_fallback = get_analysis_artifact_snapshot_bytes_for_user(
        user_id=safe_user_id,
        artifact_kind="ocr_master",
        platform=safe_platform,
    )
    if not latest:
        if db_fallback:
            filename = f"user-{safe_user_id}-{safe_platform}-master-orders.csv"
            return _attachment_csv_response(db_fallback, filename)
        raise HTTPException(404, f"No {safe_platform} OCR master data found for this user.")
    result_path = str(latest.get("result_path") or "").strip()
    if not result_path:
        raise HTTPException(404, f"No {safe_platform} OCR master data file found for this user.")
    filename = f"user-{safe_user_id}-{safe_platform}-master-orders.csv"
    return _master_csv_download_response(Path(result_path), filename, db_fallback=db_fallback)


@app.get("/api/admin/users/{user_id}/risk/suspicious/download")
def admin_user_suspicious_risk_download(user_id: int, authorization: str | None = Header(default=None)):
    _require_admin_user(authorization)
    safe_user_id = int(user_id)
    if safe_user_id <= 0:
        raise HTTPException(400, "Invalid user id.")
    latest = get_latest_suspicious_profile_result_for_user(safe_user_id)
    db_fallback = get_analysis_artifact_snapshot_bytes_for_user(
        user_id=safe_user_id,
        artifact_kind="suspicious_customers",
        platform=None,
    )
    if not latest:
        if db_fallback:
            filename = f"user-{safe_user_id}-suspicious-customers.csv"
            return _attachment_csv_response(db_fallback, filename)
        raise HTTPException(404, "No suspicious customer data found for this user.")
    result_path = str(latest.get("result_path") or "").strip()
    if not result_path:
        raise HTTPException(404, "No suspicious customer data file found for this user.")
    filename = f"user-{safe_user_id}-suspicious-customers.csv"
    return _admin_risk_csv_download_response(result_path, filename, db_fallback=db_fallback)


@app.get("/api/admin/users/{user_id}/risk/suspicious/{platform}/download")
def admin_user_suspicious_risk_download_by_platform(
    user_id: int,
    platform: str,
    authorization: str | None = Header(default=None),
):
    _require_admin_user(authorization)
    safe_user_id = int(user_id)
    if safe_user_id <= 0:
        raise HTTPException(400, "Invalid user id.")
    safe_platform = (platform or "").strip().lower()
    if safe_platform not in SUPPORTED_OCR_PLATFORMS:
        raise HTTPException(
            400,
            f"Unsupported platform '{platform}'. Allowed: {', '.join(SUPPORTED_OCR_PLATFORMS)}.",
        )
    latest = get_latest_suspicious_profile_result_for_user(safe_user_id, platform=safe_platform)
    db_fallback = get_analysis_artifact_snapshot_bytes_for_user(
        user_id=safe_user_id,
        artifact_kind="suspicious_customers",
        platform=safe_platform,
    )
    if not latest:
        if db_fallback:
            filename = f"user-{safe_user_id}-{safe_platform}-suspicious-customers.csv"
            return _attachment_csv_response(db_fallback, filename)
        raise HTTPException(404, f"No {safe_platform} suspicious customer data found for this user.")
    result_path = str(latest.get("result_path") or "").strip()
    if not result_path:
        raise HTTPException(404, f"No {safe_platform} suspicious customer data file found for this user.")
    filename = f"user-{safe_user_id}-{safe_platform}-suspicious-customers.csv"
    return _admin_risk_csv_download_response(result_path, filename, db_fallback=db_fallback)


@app.patch("/api/admin/users/{user_id}/role")
def admin_update_user_role(
    user_id: int,
    payload: AdminRolePayload,
    authorization: str | None = Header(default=None),
):
    actor = _require_admin_user(authorization)
    try:
        updated = set_user_admin_role(
            user_id,
            is_admin=bool(payload.is_admin),
            actor_user_id=int(actor["id"]),
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 400
        raise HTTPException(status, message) from exc
    return {"user": updated}


@app.patch("/api/admin/users/roles/bulk")
def admin_update_user_roles_bulk(
    payload: AdminBulkRolePayload,
    authorization: str | None = Header(default=None),
):
    actor = _require_admin_user(authorization)
    try:
        updated = set_users_admin_role_bulk(
            user_ids=payload.user_ids or [],
            is_admin=bool(payload.is_admin),
            actor_user_id=int(actor["id"]),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"users": updated}


@app.post("/api/admin/wallet/credit")
def admin_wallet_credit(
    payload: AdminWalletCreditPayload,
    authorization: str | None = Header(default=None),
):
    actor = _require_admin_user(authorization)
    target_user_id = int(payload.target_user_id or 0)
    if target_user_id <= 0:
        target_user_id = int(get_user_id_by_email(payload.target_email or "") or 0)
    if target_user_id <= 0:
        raise HTTPException(400, "Provide a valid target user id or email.")
    try:
        wallet = add_wallet_credit(
            user_id=target_user_id,
            amount=int(payload.amount or 0),
            note=payload.note,
            actor_user_id=int(actor["id"]),
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 400
        raise HTTPException(status, message) from exc
    return {"target_user_id": target_user_id, "wallet": wallet}


@app.get("/api/admin/wallet/audit")
def admin_wallet_audit(
    authorization: str | None = Header(default=None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    query: str = Query("", max_length=120),
):
    _require_admin_user(authorization)
    clean_query = (query or "").strip() or None
    events = list_admin_wallet_credit_audit(
        limit=limit,
        offset=offset,
        query=clean_query,
    )
    total = count_admin_wallet_credit_audit(query=clean_query)
    return {"events": events, "total": total}


@app.get("/api/admin/role-audit")
def admin_role_audit(
    authorization: str | None = Header(default=None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    actor_query: str = Query("", max_length=120),
    target_query: str = Query("", max_length=120),
    from_date: str = Query("", max_length=40),
    to_date: str = Query("", max_length=40),
):
    _require_admin_user(authorization)
    clean_actor = (actor_query or "").strip() or None
    clean_target = (target_query or "").strip() or None
    clean_from = (from_date or "").strip() or None
    clean_to = (to_date or "").strip() or None
    rows = list_admin_role_audit(
        limit=limit,
        offset=offset,
        actor_query=clean_actor,
        target_query=clean_target,
        from_date=clean_from,
        to_date=clean_to,
    )
    total = count_admin_role_audit(
        actor_query=clean_actor,
        target_query=clean_target,
        from_date=clean_from,
        to_date=clean_to,
    )
    return {"events": rows, "total": total}


@app.get("/api/admin/role-audit/cursor")
def admin_role_audit_cursor_endpoint(
    authorization: str | None = Header(default=None),
    limit: int = Query(20, ge=1, le=100),
    cursor: int | None = Query(default=None),
    actor_query: str = Query("", max_length=120),
    target_query: str = Query("", max_length=120),
    from_date: str = Query("", max_length=40),
    to_date: str = Query("", max_length=40),
):
    _require_admin_user(authorization)
    clean_actor = (actor_query or "").strip() or None
    clean_target = (target_query or "").strip() or None
    clean_from = (from_date or "").strip() or None
    clean_to = (to_date or "").strip() or None
    rows, next_cursor = list_admin_role_audit_cursor(
        limit=limit,
        cursor=cursor,
        actor_query=clean_actor,
        target_query=clean_target,
        from_date=clean_from,
        to_date=clean_to,
    )
    total = count_admin_role_audit(
        actor_query=clean_actor,
        target_query=clean_target,
        from_date=clean_from,
        to_date=clean_to,
    )
    return {
        "events": rows,
        "total": total,
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor is not None),
    }


@app.get("/api/admin/role-audit/export")
def admin_role_audit_export_csv(
    authorization: str | None = Header(default=None),
    actor_query: str = Query("", max_length=120),
    target_query: str = Query("", max_length=120),
    from_date: str = Query("", max_length=40),
    to_date: str = Query("", max_length=40),
    columns: str = Query("", max_length=300),
):
    _require_admin_user(authorization)
    clean_actor = (actor_query or "").strip() or None
    clean_target = (target_query or "").strip() or None
    clean_from = (from_date or "").strip() or None
    clean_to = (to_date or "").strip() or None
    rows = list_admin_role_audit(
        limit=1000,
        offset=0,
        actor_query=clean_actor,
        target_query=clean_target,
        from_date=clean_from,
        to_date=clean_to,
    )
    allowed_columns = [
        "id",
        "created_at",
        "actor_user_id",
        "actor_email",
        "actor_name",
        "target_user_id",
        "target_email",
        "target_name",
        "prev_is_admin",
        "next_is_admin",
    ]
    requested = [c.strip() for c in (columns or "").split(",") if c.strip()]
    final_columns = [c for c in requested if c in allowed_columns]
    if not final_columns:
        final_columns = allowed_columns

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(final_columns)
    for row in rows:
        mapped = {
            "id": row.get("id"),
            "created_at": row.get("created_at"),
            "actor_user_id": row.get("actor_user_id"),
            "actor_email": row.get("actor_email"),
            "actor_name": row.get("actor_name"),
            "target_user_id": row.get("target_user_id"),
            "target_email": row.get("target_email"),
            "target_name": row.get("target_name"),
            "prev_is_admin": bool(row.get("prev_is_admin")),
            "next_is_admin": bool(row.get("next_is_admin")),
        }
        writer.writerow([mapped.get(c) for c in final_columns])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="admin-role-audit.csv"'},
    )


@app.get("/api/admin/ocr/tasks")
def admin_ocr_tasks(
    authorization: str | None = Header(default=None),
    query: str = Query("", max_length=120),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    _require_admin_user(authorization)
    clean_query = (query or "").strip() or None
    rows = list_admin_ocr_tasks(query=clean_query, limit=limit, offset=offset)
    total = count_admin_ocr_tasks(query=clean_query)
    return {"tasks": rows, "total": total}


@app.get("/api/admin/ocr/tasks/{task_id}/rows")
def admin_ocr_task_rows(
    task_id: str,
    authorization: str | None = Header(default=None),
    query: str = Query("", max_length=120),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    _require_admin_user(authorization)
    clean_query = (query or "").strip() or None
    try:
        rows, total = read_admin_ocr_task_rows(
            task_id=task_id,
            query=clean_query,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 400
        raise HTTPException(status, message) from exc
    return {"rows": rows, "total": total}


@app.get("/api/admin/returns/tasks")
def admin_return_tasks(
    authorization: str | None = Header(default=None),
    query: str = Query("", max_length=120),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    _require_admin_user(authorization)
    clean_query = (query or "").strip() or None
    rows = list_admin_return_tasks(query=clean_query, limit=limit, offset=offset)
    total = count_admin_return_tasks(query=clean_query)
    return {"tasks": rows, "total": total}


@app.get("/api/admin/returns/tasks/{task_id}/rows")
def admin_return_task_rows(
    task_id: str,
    authorization: str | None = Header(default=None),
    query: str = Query("", max_length=120),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    _require_admin_user(authorization)
    clean_query = (query or "").strip() or None
    try:
        rows, total = read_admin_return_task_rows(
            task_id=task_id,
            query=clean_query,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 400
        raise HTTPException(status, message) from exc
    return {"rows": rows, "total": total}


@app.get("/api/history/jobs")
def history_jobs(
    authorization: str | None = Header(default=None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    platform: str = Query("", max_length=40),
    status: str = Query("", max_length=20),
    from_date: str = Query("", max_length=40),
    to_date: str = Query("", max_length=40),
    sort: str = Query("newest", pattern="^(newest|oldest)$"),
):
    user = _require_session_user(authorization)
    clean_platform = (platform or "").strip() or None
    clean_status = (status or "").strip() or None
    clean_from = (from_date or "").strip() or None
    clean_to = (to_date or "").strip() or None
    try:
        sync_recent_user_tasks_from_redis(int(user["id"]), limit=max(50, int(limit)))
    except Exception:
        logger.exception("Could not sync recent Redis tasks before history list")
    jobs = list_crop_jobs_for_user(
        user["id"],
        limit=limit,
        offset=offset,
        platform=clean_platform,
        status=clean_status,
        from_date=clean_from,
        to_date=clean_to,
        sort=sort,
    )
    total = count_crop_jobs_for_user(
        user["id"],
        platform=clean_platform,
        status=clean_status,
        from_date=clean_from,
        to_date=clean_to,
    )
    return {"jobs": jobs, "total": total}


@app.get("/api/history/jobs/{job_id}")
def history_job_detail(job_id: int, authorization: str | None = Header(default=None)):
    user = _require_session_user(authorization)
    job = get_crop_job_for_user(user["id"], job_id)
    if not job:
        raise HTTPException(404, "History job not found.")
    return {"job": job}


@app.get("/api/me/dashboard")
def my_dashboard(
    authorization: str | None = Header(default=None),
    recent_limit: int = Query(5, ge=1, le=25),
):
    """Aggregated personal dashboard metrics for the signed-in user.

    Returns overall crop-job counts (success/failed/processing/pending),
    label/page totals, per-platform breakdowns (Meesho/Flipkart/OCR),
    a small ``recent_jobs`` slice, and manual high-risk customer/suborder
    totals derived from the user's risk store. The endpoint is read-only,
    auth-scoped (only the caller's data is returned) and returns zeroed
    counters for new users instead of erroring.
    """
    user = _require_session_user(authorization)
    safe_user_id = int(user.get("id") or 0)
    try:
        data = get_user_dashboard_metrics(safe_user_id, recent_limit=recent_limit)
    except Exception as exc:
        logger.exception("get_user_dashboard_metrics failed for user %s", safe_user_id)
        raise HTTPException(500, "Could not load dashboard metrics.") from exc

    profile = {
        "id": safe_user_id,
        "name": user.get("name") or "",
        "email": user.get("email") or "",
        "is_admin": bool(user.get("is_admin")),
        "created_at": user.get("created_at") or "",
    }
    return {"profile": profile, **data}


@app.post("/api/ocr/labels/excel/start")
async def ocr_labels_to_excel_start(
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    column_preset: str = Query("standard_v1", max_length=40),
    custom_columns: str = Query("", max_length=1000),
    max_workers: int = Query(0, ge=0, le=16),
    files: list[UploadFile] = File(...),
):
    user = _require_session_user(authorization)
    _ensure_enqueue_capacity(int(user["id"]), "ocr_labels")

    clean_preset = (column_preset or "standard_v1").strip() or "standard_v1"
    clean_custom = (custom_columns or "").strip()
    if clean_preset == "custom" and not clean_custom:
        raise HTTPException(400, "custom_columns is required when column_preset=custom")
    tmpdir, input_paths, input_file_rows, total_pages = await _prepare_uploaded_pdf_payload(
        files,
        tmp_prefix="label_ocr_task_",
    )

    options = {
        "column_preset": clean_preset,
        "custom_columns": clean_custom,
        "stored_on_server_only": True,
    }
    job_id = create_crop_job(
        user_id=user["id"],
        platform="ocr_labels",
        sort_by=clean_preset,
        layout="xlsx",
        options=options,
    )
    mark_crop_job_started(job_id)

    safe_workers = int(max_workers or 0)
    if safe_workers <= 0:
        safe_workers = min(8, max(1, (os.cpu_count() or 4)))
    payload = {
        "output_dir": tmpdir,
        "input_paths": input_paths,
        "input_files": input_file_rows,
        "total_input_files": len(input_file_rows),
        "total_input_pages": total_pages,
        "max_workers": safe_workers,
        "options": options,
    }
    _attach_remote_task_inputs(payload, user_id=int(user["id"]))
    try:
        task_id, _ = get_or_create_idempotent_task(
            user_id=int(user["id"]),
            job_id=int(job_id),
            task_type="ocr_csv",
            idem_key=idempotency_key or "",
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if _use_redis_queue():
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "task_id": task_id,
        "job_id": int(job_id),
        "status": "queued",
        "progress": 1,
    }


@app.get("/api/ocr/labels/tasks/{task_id}")
def ocr_labels_task_status(task_id: str, authorization: str | None = Header(default=None)):
    user = _require_session_user(authorization)
    task = get_task_public_for_user(task_id, int(user["id"]))
    if not task or task.get("task_type") not in {"ocr_csv", "ocr_excel"}:
        raise HTTPException(404, "OCR task not found.")
    return {"task": task}


@app.get("/api/ocr/labels/tasks/{task_id}/download")
def ocr_labels_task_download(task_id: str, authorization: str | None = Header(default=None)):
    _require_session_user(authorization)
    raise HTTPException(403, "OCR output is stored on server and is not downloadable by users.")


@app.post("/api/returns/analysis/start")
async def returns_analysis_start(
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    platform: str = Query("", max_length=40),
    file: UploadFile = File(...),
):
    user = _require_session_user(authorization)
    _ensure_enqueue_capacity(int(user["id"]), "return_analysis")
    source_platform = (platform or "").strip().lower()
    if source_platform and source_platform not in SUPPORTED_OCR_PLATFORMS:
        raise HTTPException(
            400,
            f"Unsupported platform '{platform}'. Allowed: {', '.join(SUPPORTED_OCR_PLATFORMS)}.",
        )
    latest_ocr = get_latest_successful_ocr_result_for_user(
        int(user["id"]),
        platform=source_platform or None,
    )
    if not latest_ocr:
        if source_platform:
            raise HTTPException(
                400,
                f"No completed {source_platform} OCR CSV found for this user. Upload {source_platform} labels first.",
            )
        raise HTTPException(400, "No completed OCR CSV found for this user. Upload label PDFs first.")
    returns_tmpdir, returns_path = await _prepare_uploaded_excel_file(file, tmp_prefix="returns_analysis_")
    options = {
        "source_ocr_task_id": latest_ocr["task_id"],
        "source_platform": source_platform or (latest_ocr.get("platform") or ""),
        "stored_on_server_only": True,
    }
    job_id = create_crop_job(
        user_id=user["id"],
        platform="return_analysis",
        sort_by="suborder_match",
        layout="csv",
        options=options,
    )
    mark_crop_job_started(job_id)
    payload = {
        "output_dir": returns_tmpdir,
        "returns_excel_path": returns_path,
        "orders_csv_path": latest_ocr["result_path"],
        "options": options,
    }
    try:
        task_id, _ = get_or_create_idempotent_task(
            user_id=int(user["id"]),
            job_id=int(job_id),
            task_type="return_analysis",
            idem_key=idempotency_key or "",
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"task_id": task_id, "job_id": int(job_id), "status": "queued", "progress": 1}


@app.get("/api/tasks/{task_id}")
def task_status(task_id: str, authorization: str | None = Header(default=None)):
    user = _require_session_user(authorization)
    task = get_task_public_for_user(task_id, int(user["id"]))
    if not task:
        raise HTTPException(404, "Task not found.")
    return {"task": task}


@app.get("/api/tasks/{task_id}/download")
def task_download(
    task_id: str,
    authorization: str | None = Header(default=None),
    proxy: bool = Query(
        False,
        description="If true, stream artifact via API instead of redirecting to object storage URL.",
    ),
    as_json: bool = Query(
        False,
        description="If true, return JSON with a presigned URL instead of HTTP redirect (CORS-safe for SPAs).",
    ),
):
    user = _require_session_user(authorization)
    task = get_task_for_user(task_id, int(user["id"]))
    if not task:
        raise HTTPException(404, "Task not found.")
    if task.get("status") != "success" or not task.get("result_path"):
        raise HTTPException(409, "Task is not completed yet.")
    if task.get("task_type") in {"crop_meesho", "crop_flipkart"} and _task_download_expired(task):
        _cleanup_task_output_artifacts(task)
        if DOWNLOAD_EXPIRY_MODE in {"calendar_day", "daily", "midnight"}:
            detail = "Download expired. Cropped files are available until local midnight only."
        else:
            detail = f"Download expired. Cropped files are available for {DOWNLOAD_RETENTION_HOURS} hours only."
        raise HTTPException(
            410,
            detail,
        )
    if task.get("task_type") in {"ocr_csv", "ocr_excel", "return_analysis"}:
        raise HTTPException(403, "Output is stored on server and is not downloadable by users.")
    result_path = str(task["result_path"] or "")
    if result_path.startswith("s3://"):
        bucket_prefix = f"s3://{os.getenv('S3_BUCKET', '').strip()}/"
        key = result_path[len(bucket_prefix):] if result_path.startswith(bucket_prefix) else result_path.replace("s3://", "", 1).split("/", 1)[-1]
        if not key:
            raise HTTPException(404, "Output file is no longer available.")
        store = S3ArtifactStore()
        authenticated_download_url = f"/api/tasks/{task_id}/download?proxy=1"
        if proxy:
            media_type = "application/zip" if key.lower().endswith(".zip") else "application/pdf"
            filename = "cropped-labels-risk-split.zip" if media_type == "application/zip" else "cropped-labels.pdf"
            body = store.open_stream(key)
            return StreamingResponse(
                body,
                media_type=media_type,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        url = store.presigned_get(key, expires_sec=900)
        if as_json:
            media_type = "application/zip" if key.lower().endswith(".zip") else "application/pdf"
            filename = "cropped-labels-risk-split.zip" if media_type == "application/zip" else "cropped-labels.pdf"
            return {
                "download_url": url,
                "expires_in_sec": 900,
                "use_authenticated_file_download": True,
                "authenticated_download_url": authenticated_download_url,
                "media_type": media_type,
                "file_name": filename,
            }
        return RedirectResponse(url)
    output_path = Path(result_path)
    if not output_path.exists():
        raise HTTPException(404, "Output file is no longer available.")
    if as_json:
        # Local/dev filesystem artifact — SPA should call again without as_json=1.
        return {"download_url": None, "use_authenticated_file_download": True}
    if output_path.suffix.lower() == ".zip":
        media_type = "application/zip"
        filename = "cropped-labels-risk-split.zip"
    else:
        media_type = "application/pdf"
        filename = "cropped-labels.pdf"
    return FileResponse(path=str(output_path), media_type=media_type, filename=filename)


@app.get("/api/history/customer")
def history_customer_by_suborder(
    suborder_id: str = Query(..., min_length=1, max_length=120),
    authorization: str | None = Header(default=None),
):
    """Premium: fetch purchase + return history for the customer behind a suborder.

    Identifies the customer via the user's own master OCR CSV using the same
    normalized name+pincode key used for risk profiling, then aggregates
    every purchase row for that customer and any matching return analysis rows.
    Only the calling user's own master/return data is ever scanned.
    """
    user = _require_session_user(authorization)
    clean_suborder = (suborder_id or "").strip()
    if not clean_suborder:
        raise HTTPException(400, "suborder_id is required.")
    try:
        snapshot = get_customer_history_by_suborder(int(user["id"]), clean_suborder)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"result": snapshot}


@app.post("/api/crop/meesho/start")
async def crop_meesho_start(
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    files: list[UploadFile] = File(...),
    sort_by: str = Form("order_id"),
    layout: str = Form("label_printer"),
    print_datetime: str = Form("0"),
    multi_order_bottom: str = Form("0"),
    custom_message: str = Form(""),
    separate_pincodes: str = Form(""),
    detect_suspicious: str = Form("0"),
    mark_suspicious_preview: str = Form("0"),
    separate_multi_order_by_customer: str = Form("0"),
    mark_loyal_customer: str = Form("0"),
    mark_loyal_customer_preview: str = Form("0"),
    pick_list_enabled: str = Form("0"),
    pick_list_after_orders: str = Form("0"),
):
    user = _require_session_user(authorization)
    _ensure_enqueue_capacity(int(user["id"]), "meesho")
    pick_list_enabled_bool = _form_bool(pick_list_enabled)
    legacy_pick_list_after_orders = _form_int(pick_list_after_orders, 0, minimum=0, maximum=500)
    options = {
        "print_datetime": _form_bool(print_datetime),
        "multi_order_bottom": _form_bool(multi_order_bottom),
        "custom_message": (custom_message or "").strip(),
        "custom_message_enabled": bool((custom_message or "").strip()),
        "separate_pincodes": (separate_pincodes or "").strip(),
        "detect_suspicious": _form_bool(detect_suspicious),
        "mark_suspicious_preview": _form_bool(mark_suspicious_preview),
        "separate_multi_order_by_customer": _form_bool(separate_multi_order_by_customer),
        "mark_loyal_customer": _form_bool(mark_loyal_customer),
        "mark_loyal_customer_preview": _form_bool(mark_loyal_customer_preview),
        "pick_list_enabled": pick_list_enabled_bool,
        "pick_list_after_orders": (
            legacy_pick_list_after_orders if legacy_pick_list_after_orders > 0 else (1 if pick_list_enabled_bool else 0)
        ),
    }
    tmpdir, input_paths, input_file_rows, total_pages = await _prepare_uploaded_pdf_payload(
        files,
        tmp_prefix="meesho_crop_task_",
    )
    try:
        _ensure_premium_wallet_capacity(int(user["id"]), total_pages=total_pages, options=options)
    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    idem_trim = (idempotency_key or "").strip()
    if idem_trim:
        existing_tid = lookup_idempotent_task_id(
            user_id=int(user["id"]),
            task_type="crop_meesho",
            idem_key=idem_trim,
        )
        if existing_tid:
            existing_task = get_task_for_user(existing_tid, int(user["id"]))
            if existing_task:
                shutil.rmtree(tmpdir, ignore_errors=True)
                return {
                    "task_id": existing_tid,
                    "job_id": int(existing_task.get("job_id") or 0),
                    "status": str(existing_task.get("status") or "queued"),
                    "progress": int(existing_task.get("progress") or 1),
                }
    job_id = create_crop_job(
        user_id=user["id"],
        platform="meesho",
        sort_by=sort_by,
        layout=layout,
        options=options,
    )
    mark_crop_job_started(job_id)
    payload = {
        "output_dir": tmpdir,
        "input_paths": input_paths,
        "input_files": input_file_rows,
        "total_input_files": len(input_file_rows),
        "total_input_pages": total_pages,
        "sort_by": sort_by,
        "layout": layout,
        "options": options,
    }
    _attach_remote_task_inputs(payload, user_id=int(user["id"]))
    try:
        task_id, _ = get_or_create_idempotent_task(
            user_id=int(user["id"]),
            job_id=int(job_id),
            task_type="crop_meesho",
            idem_key=idempotency_key or "",
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    task_row = get_task_for_user(task_id, int(user["id"]))
    if task_row:
        job_id = int(task_row.get("job_id") or job_id)
    try:
        _enqueue_auto_ocr_from_crop(
            user_id=int(user["id"]),
            source_job_id=int(job_id),
            source_platform="meesho",
            input_paths=input_paths,
            input_file_rows=input_file_rows,
            total_input_pages=total_pages,
        )
    except Exception:
        logger.exception("Auto OCR enqueue failed for crop task %s", task_id)
    if _use_redis_queue() and _use_s3_storage() and bool(payload.get("input_s3_keys")):
        shutil.rmtree(tmpdir, ignore_errors=True)
    return {"task_id": task_id, "job_id": int(job_id), "status": "queued", "progress": 1}


@app.post("/api/crop/flipkart/start")
async def crop_flipkart_start(
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    files: list[UploadFile] = File(...),
    sort_by: str = Form("sku"),
    layout: str = Form("label_printer"),
    multi_order_bottom: str = Form("0"),
    separate_pincodes: str = Form(""),
    detect_suspicious: str = Form("0"),
    mark_suspicious_preview: str = Form("0"),
    print_datetime: str = Form("0"),
    custom_message: str = Form(""),
    pick_list_enabled: str = Form("0"),
    pick_list_after_orders: str = Form("0"),
    separate_multi_order_by_customer: str = Form("0"),
    mark_loyal_customer: str = Form("0"),
    mark_loyal_customer_preview: str = Form("0"),
):
    user = _require_session_user(authorization)
    _ensure_enqueue_capacity(int(user["id"]), "flipkart")
    pick_list_enabled_bool = _form_bool(pick_list_enabled)
    legacy_pick_list_after_orders = _form_int(pick_list_after_orders, 0, minimum=0, maximum=500)
    options = {
        "multi_order_bottom": _form_bool(multi_order_bottom),
        "separate_pincodes": (separate_pincodes or "").strip(),
        "detect_suspicious": _form_bool(detect_suspicious),
        "mark_suspicious_preview": _form_bool(mark_suspicious_preview),
        "print_datetime": _form_bool(print_datetime),
        "custom_message": (custom_message or "").strip(),
        "custom_message_enabled": bool((custom_message or "").strip()),
        "pick_list_enabled": pick_list_enabled_bool,
        "pick_list_after_orders": (
            legacy_pick_list_after_orders if legacy_pick_list_after_orders > 0 else (1 if pick_list_enabled_bool else 0)
        ),
        "separate_multi_order_by_customer": _form_bool(separate_multi_order_by_customer),
        "mark_loyal_customer": _form_bool(mark_loyal_customer),
        "mark_loyal_customer_preview": _form_bool(mark_loyal_customer_preview),
    }
    tmpdir, input_paths, input_file_rows, total_pages = await _prepare_uploaded_pdf_payload(
        files,
        tmp_prefix="flipkart_crop_task_",
    )
    try:
        _ensure_premium_wallet_capacity(int(user["id"]), total_pages=total_pages, options=options)
    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    idem_trim = (idempotency_key or "").strip()
    if idem_trim:
        existing_tid = lookup_idempotent_task_id(
            user_id=int(user["id"]),
            task_type="crop_flipkart",
            idem_key=idem_trim,
        )
        if existing_tid:
            existing_task = get_task_for_user(existing_tid, int(user["id"]))
            if existing_task:
                shutil.rmtree(tmpdir, ignore_errors=True)
                return {
                    "task_id": existing_tid,
                    "job_id": int(existing_task.get("job_id") or 0),
                    "status": str(existing_task.get("status") or "queued"),
                    "progress": int(existing_task.get("progress") or 1),
                }
    job_id = create_crop_job(
        user_id=user["id"],
        platform="flipkart",
        sort_by=sort_by,
        layout=layout,
        options=options,
    )
    mark_crop_job_started(job_id)
    payload = {
        "output_dir": tmpdir,
        "input_paths": input_paths,
        "input_files": input_file_rows,
        "total_input_files": len(input_file_rows),
        "total_input_pages": total_pages,
        "sort_by": sort_by,
        "layout": layout,
        "options": options,
    }
    _attach_remote_task_inputs(payload, user_id=int(user["id"]))
    try:
        task_id, _ = get_or_create_idempotent_task(
            user_id=int(user["id"]),
            job_id=int(job_id),
            task_type="crop_flipkart",
            idem_key=idempotency_key or "",
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    task_row = get_task_for_user(task_id, int(user["id"]))
    if task_row:
        job_id = int(task_row.get("job_id") or job_id)
    try:
        _enqueue_auto_ocr_from_crop(
            user_id=int(user["id"]),
            source_job_id=int(job_id),
            source_platform="flipkart",
            input_paths=input_paths,
            input_file_rows=input_file_rows,
            total_input_pages=total_pages,
        )
    except Exception:
        logger.exception("Auto OCR enqueue failed for crop task %s", task_id)
    if _use_redis_queue() and _use_s3_storage() and bool(payload.get("input_s3_keys")):
        shutil.rmtree(tmpdir, ignore_errors=True)
    return {"task_id": task_id, "job_id": int(job_id), "status": "queued", "progress": 1}


@app.post("/api/ocr/labels/excel")
async def ocr_labels_to_excel(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    column_preset: str = Query("standard_v1", max_length=40),
    custom_columns: str = Query("", max_length=1000),
    files: list[UploadFile] = File(...),
):
    _require_session_user(authorization)
    raise HTTPException(
        410,
        "Direct OCR file download endpoint is disabled. OCR runs in background and CSV is stored server-side only.",
    )


@app.post("/api/crop/meesho")
async def crop_meesho(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    files: list[UploadFile] = File(...),
    sort_by: str = Form("order_id"),
    layout: str = Form("label_printer"),
    print_datetime: str = Form("0"),
    multi_order_bottom: str = Form("0"),
    custom_message: str = Form(""),
    separate_pincodes: str = Form(""),
    detect_suspicious: str = Form("0"),
    mark_suspicious_preview: str = Form("0"),
    mark_loyal_customer: str = Form("0"),
    mark_loyal_customer_preview: str = Form("0"),
    pick_list_enabled: str = Form("0"),
    pick_list_after_orders: str = Form("0"),
):
    user = _require_session_user(authorization)
    _ensure_enqueue_capacity(int(user["id"]), "meesho")
    start_perf = time.perf_counter()
    pick_list_enabled_bool = _form_bool(pick_list_enabled)
    legacy_pick_list_after_orders = _form_int(pick_list_after_orders, 0, minimum=0, maximum=500)
    options = {
        "print_datetime": _form_bool(print_datetime),
        "multi_order_bottom": _form_bool(multi_order_bottom),
        "custom_message_enabled": bool((custom_message or "").strip()),
        "separate_pincodes": (separate_pincodes or "").strip(),
        "detect_suspicious": _form_bool(detect_suspicious),
        "mark_suspicious_preview": _form_bool(mark_suspicious_preview),
        "mark_loyal_customer": _form_bool(mark_loyal_customer),
        "mark_loyal_customer_preview": _form_bool(mark_loyal_customer_preview),
        "pick_list_enabled": pick_list_enabled_bool,
        "pick_list_after_orders": (
            legacy_pick_list_after_orders if legacy_pick_list_after_orders > 0 else (1 if pick_list_enabled_bool else 0)
        ),
    }
    job_id = create_crop_job(
        user_id=user["id"],
        platform="meesho",
        sort_by=sort_by,
        layout=layout,
        options=options,
    )
    mark_crop_job_started(job_id)

    if not files:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_crop_job_failed(job_id, error_message="No files uploaded", duration_ms=duration_ms, input_files=[])
        raise HTTPException(400, "No files uploaded")
    if MAX_UPLOAD_FILES > 0 and len(files) > MAX_UPLOAD_FILES:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_crop_job_failed(job_id, error_message="Too many files uploaded", duration_ms=duration_ms, input_files=[])
        raise HTTPException(413, f"Too many files. Maximum allowed is {MAX_UPLOAD_FILES}.")
    if MAX_UPLOAD_FILES > 0 and len(files) > MAX_UPLOAD_FILES:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_crop_job_failed(job_id, error_message="Too many files uploaded", duration_ms=duration_ms, input_files=[])
        raise HTTPException(413, f"Too many files. Maximum allowed is {MAX_UPLOAD_FILES}.")
    for f in files:
        name = (f.filename or "").lower()
        if f.content_type not in ("application/pdf", "application/octet-stream") and not name.endswith(
            ".pdf"
        ):
            duration_ms = int((time.perf_counter() - start_perf) * 1000)
            mark_crop_job_failed(
                job_id,
                error_message=f"Not a PDF: {f.filename}",
                duration_ms=duration_ms,
                input_files=[],
            )
            raise HTTPException(400, f"Not a PDF: {f.filename}")

    tmpdir = tempfile.mkdtemp(prefix="meesho_crop_")
    tmp_path = Path(tmpdir)
    input_paths: list[str] = []
    input_file_rows: list[dict] = []
    out_path = str(tmp_path / "output.pdf")
    total_bytes = 0
    total_pages = 0

    try:
        for i, upload in enumerate(files):
            raw = await upload.read()
            if not raw:
                raise HTTPException(400, f"Empty file: {upload.filename}")
            if MAX_UPLOAD_BYTES_PER_FILE > 0 and len(raw) > MAX_UPLOAD_BYTES_PER_FILE:
                raise HTTPException(413, f"{upload.filename} exceeds max file size limit.")
            total_bytes += len(raw)
            if MAX_UPLOAD_TOTAL_BYTES > 0 and total_bytes > MAX_UPLOAD_TOTAL_BYTES:
                raise HTTPException(413, "Upload payload exceeds total size limit.")
            p = tmp_path / f"in_{i}.pdf"
            p.write_bytes(raw)
            input_paths.append(str(p))
            page_count = _safe_pdf_page_count(raw)
            total_pages += page_count
            if MAX_UPLOAD_TOTAL_PAGES > 0 and total_pages > MAX_UPLOAD_TOTAL_PAGES:
                raise HTTPException(413, f"Total page count exceeds limit ({MAX_UPLOAD_TOTAL_PAGES}).")
            input_file_rows.append(
                {
                    "file_name": upload.filename or f"in_{i}.pdf",
                    "input_pages": page_count,
                }
            )

        process_meesho_uploaded_paths(
            input_paths,
            out_path,
            sort_by=sort_by,
            layout=layout,
            print_datetime=_form_bool(print_datetime),
            multi_order_bottom=_form_bool(multi_order_bottom),
            pick_list_enabled=pick_list_enabled_bool,
            pick_list_after_orders=(
                legacy_pick_list_after_orders
                if legacy_pick_list_after_orders > 0
                else (1 if pick_list_enabled_bool else 0)
            ),
            custom_message=custom_message,
        )
        output_pages = _safe_pdf_page_count_from_path(out_path)
        total_input_files = len(input_file_rows)
        total_input_pages = sum(int(row.get("input_pages") or 0) for row in input_file_rows)
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_crop_job_success(
            job_id,
            duration_ms=duration_ms,
            total_input_files=total_input_files,
            total_input_pages=total_input_pages,
            total_output_pages=output_pages,
            total_output_labels=total_input_pages,
            input_files=input_file_rows,
            sort_by=sort_by,
            layout=layout,
            options=options,
        )
        try:
            _enqueue_auto_ocr_from_crop(
                user_id=int(user["id"]),
                source_job_id=int(job_id),
                source_platform="meesho",
                input_paths=input_paths,
                input_file_rows=input_file_rows,
                total_input_pages=total_pages,
            )
        except Exception:
            logger.exception("Auto OCR enqueue failed for sync meesho job %s", job_id)
    except ValueError as e:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_crop_job_failed(job_id, error_message=str(e), duration_ms=duration_ms, input_files=input_file_rows)
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.exception("crop_meesho failed")
        traceback.print_exc()
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_crop_job_failed(job_id, error_message=str(e), duration_ms=duration_ms, input_files=input_file_rows)
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(500, str(e)) from e

    data = Path(out_path).read_bytes()
    background_tasks.add_task(shutil.rmtree, tmpdir, True)

    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="Meesho-labels.pdf"'},
    )


@app.post("/api/crop/flipkart")
async def crop_flipkart(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    files: list[UploadFile] = File(...),
    sort_by: str = Form("sku"),
    layout: str = Form("label_printer"),
    multi_order_bottom: str = Form("0"),
    separate_pincodes: str = Form(""),
    detect_suspicious: str = Form("0"),
    mark_suspicious_preview: str = Form("0"),
    print_datetime: str = Form("0"),
    custom_message: str = Form(""),
    pick_list_enabled: str = Form("0"),
    pick_list_after_orders: str = Form("0"),
):
    user = _require_session_user(authorization)
    _ensure_enqueue_capacity(int(user["id"]), "flipkart")
    start_perf = time.perf_counter()
    pick_list_enabled_bool = _form_bool(pick_list_enabled)
    legacy_pick_list_after_orders = _form_int(pick_list_after_orders, 0, minimum=0, maximum=500)
    options = {
        "multi_order_bottom": _form_bool(multi_order_bottom),
        "separate_pincodes": (separate_pincodes or "").strip(),
        "detect_suspicious": _form_bool(detect_suspicious),
        "mark_suspicious_preview": _form_bool(mark_suspicious_preview),
        "print_datetime": _form_bool(print_datetime),
        "custom_message_enabled": bool((custom_message or "").strip()),
        "pick_list_enabled": pick_list_enabled_bool,
        "pick_list_after_orders": (
            legacy_pick_list_after_orders if legacy_pick_list_after_orders > 0 else (1 if pick_list_enabled_bool else 0)
        ),
    }
    job_id = create_crop_job(
        user_id=user["id"],
        platform="flipkart",
        sort_by=sort_by,
        layout=layout,
        options=options,
    )
    mark_crop_job_started(job_id)

    if not files:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_crop_job_failed(job_id, error_message="No files uploaded", duration_ms=duration_ms, input_files=[])
        raise HTTPException(400, "No files uploaded")
    for f in files:
        name = (f.filename or "").lower()
        if f.content_type not in ("application/pdf", "application/octet-stream") and not name.endswith(
            ".pdf"
        ):
            duration_ms = int((time.perf_counter() - start_perf) * 1000)
            mark_crop_job_failed(
                job_id,
                error_message=f"Not a PDF: {f.filename}",
                duration_ms=duration_ms,
                input_files=[],
            )
            raise HTTPException(400, f"Not a PDF: {f.filename}")

    tmpdir = tempfile.mkdtemp(prefix="flipkart_crop_")
    tmp_path = Path(tmpdir)
    input_paths: list[str] = []
    input_file_rows: list[dict] = []
    out_path = str(tmp_path / "output.pdf")
    total_bytes = 0
    total_pages = 0

    try:
        for i, upload in enumerate(files):
            raw = await upload.read()
            if not raw:
                raise HTTPException(400, f"Empty file: {upload.filename}")
            if MAX_UPLOAD_BYTES_PER_FILE > 0 and len(raw) > MAX_UPLOAD_BYTES_PER_FILE:
                raise HTTPException(413, f"{upload.filename} exceeds max file size limit.")
            total_bytes += len(raw)
            if MAX_UPLOAD_TOTAL_BYTES > 0 and total_bytes > MAX_UPLOAD_TOTAL_BYTES:
                raise HTTPException(413, "Upload payload exceeds total size limit.")
            p = tmp_path / f"in_{i}.pdf"
            p.write_bytes(raw)
            input_paths.append(str(p))
            page_count = _safe_pdf_page_count(raw)
            total_pages += page_count
            if MAX_UPLOAD_TOTAL_PAGES > 0 and total_pages > MAX_UPLOAD_TOTAL_PAGES:
                raise HTTPException(413, f"Total page count exceeds limit ({MAX_UPLOAD_TOTAL_PAGES}).")
            input_file_rows.append(
                {
                    "file_name": upload.filename or f"in_{i}.pdf",
                    "input_pages": page_count,
                }
            )

        process_flipkart_uploaded_paths(
            input_paths,
            out_path,
            layout=layout,
            sort_by=sort_by,
            multi_order_bottom=_form_bool(multi_order_bottom),
            pick_list_enabled=pick_list_enabled_bool,
            pick_list_after_orders=(
                legacy_pick_list_after_orders
                if legacy_pick_list_after_orders > 0
                else (1 if pick_list_enabled_bool else 0)
            ),
            print_datetime=_form_bool(print_datetime),
            custom_message=custom_message,
        )
        output_pages = _safe_pdf_page_count_from_path(out_path)
        total_input_files = len(input_file_rows)
        total_input_pages = sum(int(row.get("input_pages") or 0) for row in input_file_rows)
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_crop_job_success(
            job_id,
            duration_ms=duration_ms,
            total_input_files=total_input_files,
            total_input_pages=total_input_pages,
            total_output_pages=output_pages,
            total_output_labels=total_input_pages,
            input_files=input_file_rows,
            sort_by=sort_by,
            layout=layout,
            options=options,
        )
        try:
            _enqueue_auto_ocr_from_crop(
                user_id=int(user["id"]),
                source_job_id=int(job_id),
                source_platform="flipkart",
                input_paths=input_paths,
                input_file_rows=input_file_rows,
                total_input_pages=total_pages,
            )
        except Exception:
            logger.exception("Auto OCR enqueue failed for sync flipkart job %s", job_id)
    except ValueError as e:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_crop_job_failed(job_id, error_message=str(e), duration_ms=duration_ms, input_files=input_file_rows)
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.exception("crop_flipkart failed")
        traceback.print_exc()
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_crop_job_failed(job_id, error_message=str(e), duration_ms=duration_ms, input_files=input_file_rows)
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(500, str(e)) from e

    data = Path(out_path).read_bytes()
    background_tasks.add_task(shutil.rmtree, tmpdir, True)

    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="Flipkart-labels.pdf"'},
    )
