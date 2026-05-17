from __future__ import annotations

import json
import logging
import os
import re
import hashlib
import csv
import shutil
import socket
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, TypeVar

import fitz

from auth_store import DB_PATH, spend_wallet_coins
from db_compat import connect_db, is_postgres_backend
from flipkart_service import process_uploaded_paths as process_flipkart_uploaded_paths
from history_store import mark_crop_job_failed, mark_crop_job_success
from label_ocr_service import (
    HEADERS as OCR_MASTER_HEADERS,
    OcrSetupError,
    _extract_suborder_id,
    build_csv_bytes,
    deduplicate_records,
    extract_records_from_pdfs,
    parse_required_fields,
)
from meesho_service import process_uploaded_paths as process_meesho_uploaded_paths
from return_analysis_service import analyze_returns_against_orders

logger = logging.getLogger("labelhub.tasks")
T = TypeVar("T")

TASK_STATUSES = {"queued", "running", "success", "failed", "cancelled", "expired"}
PUBLIC_TASK_TYPES = {"ocr_csv", "ocr_excel", "crop_meesho", "crop_flipkart", "return_analysis"}
INTERNAL_TASK_TYPES = {"crop_meesho_chunk", "crop_flipkart_chunk", "crop_finalize"}
TASK_TYPES = {*PUBLIC_TASK_TYPES, *INTERNAL_TASK_TYPES}
TASK_DB_LOCK_RETRY_ATTEMPTS = max(1, int(os.getenv("TASK_DB_LOCK_RETRY_ATTEMPTS", "6") or 6))
TASK_DB_LOCK_RETRY_BASE_DELAY_SEC = max(0.01, float(os.getenv("TASK_DB_LOCK_RETRY_BASE_DELAY_SEC", "0.05") or 0.05))
TASK_DB_LOCK_RETRY_MAX_DELAY_SEC = max(
    TASK_DB_LOCK_RETRY_BASE_DELAY_SEC,
    float(os.getenv("TASK_DB_LOCK_RETRY_MAX_DELAY_SEC", "0.6") or 0.6),
)
PDF_FANOUT_MIN_PAGES = max(1, int(os.getenv("PDF_FANOUT_MIN_PAGES", "200") or 200))
PDF_FANOUT_CHUNKS = max(2, min(16, int(os.getenv("PDF_FANOUT_CHUNKS", "4") or 4)))
PDF_FANOUT_CHUNK_MAX_PAGES = max(1, int(os.getenv("PDF_FANOUT_CHUNK_MAX_PAGES", "150") or 150))
PDF_FANOUT_FINALIZER_WAIT_SEC = max(30, int(os.getenv("PDF_FANOUT_FINALIZER_WAIT_SEC", "3600") or 3600))
PROGRESS_PERSIST_MIN_INTERVAL_SEC = max(
    0.0,
    float(os.getenv("TASK_PROGRESS_PERSIST_MIN_INTERVAL_SEC", "1.2") or 1.2),
)
PROGRESS_PERSIST_MIN_STEP = max(1, int(os.getenv("TASK_PROGRESS_PERSIST_MIN_STEP", "2") or 2))
PREMIUM_CROP_COIN_COST_PER_LABEL = max(0, int(os.getenv("PREMIUM_CROP_COIN_COST_PER_LABEL", "1") or 1))
ANALYSIS_ARTIFACT_DB_MAX_BYTES = max(128 * 1024, int(os.getenv("ANALYSIS_ARTIFACT_DB_MAX_BYTES", str(20 * 1024 * 1024)) or (20 * 1024 * 1024)))

_embedded_worker_threads: list[threading.Thread] = []
_embedded_worker_stop = threading.Event()
_client_lock = threading.Lock()
_redis_client_singleton = None
_s3_store_singleton = None
_queue_metrics_cache: dict[str, object] = {"ts": 0.0, "payload": None}
_redis_requeue_scan_state: dict[str, float] = {"ts": 0.0}
_progress_update_cache: dict[str, dict[str, object]] = {}
OCR_MASTER_DIR = (Path(DB_PATH).resolve().parent / "ocr_store").resolve()
RISK_STORE_DIR = (Path(DB_PATH).resolve().parent / "risk_store").resolve()
RISK_ACTIVATION_SCORE = float(os.getenv("RISK_ACTIVATION_SCORE", "8"))
RISK_MEDIUM_SCORE = float(os.getenv("RISK_MEDIUM_SCORE", "8"))
RISK_HIGH_SCORE = float(os.getenv("RISK_HIGH_SCORE", "20"))
LOYAL_RETURN_RATE_THRESHOLD_PERCENT = float(os.getenv("LOYAL_RETURN_RATE_THRESHOLD_PERCENT", "17"))


def _use_redis_queue() -> bool:
    return (os.getenv("QUEUE_BACKEND", "sqlite") or "sqlite").strip().lower() == "redis"


def redis_ocr_master_lookup_enabled() -> bool:
    """Read OCR task completion from Redis when workers use the same Redis.

    The API ECS task sometimes omits ``QUEUE_BACKEND=redis`` even though OCR
    completion state lives in Redis. If ``REDIS_URL`` is set, default to
    resolving master OCR from Redis unless ``OCR_MASTER_REDIS_LOOKUP`` is
    explicitly disabled (0/false/no/off).
    """
    if not (os.getenv("REDIS_URL") or "").strip():
        return False
    v = (os.getenv("OCR_MASTER_REDIS_LOOKUP", "1") or "1").strip().lower()
    if v in {"0", "false", "no", "off"}:
        return False
    return True


def _use_s3_storage() -> bool:
    return (os.getenv("STORAGE_BACKEND", "local") or "local").strip().lower() == "s3"


def _env_flag(name: str, default: str = "") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


def _distributed_pdf_fanout_enabled() -> bool:
    # Hard-disabled: selected options must always run on a single deterministic
    # full-fidelity path (no fan-out shortcuts).
    return False


def _normalize_sort_by(value: object, default: str = "") -> str:
    return (str(value or default or "").strip().lower())


def _needs_global_finalizer_pass(task_type: object, sort_by: object) -> bool:
    normalized_task_type = str(task_type or "").strip()
    normalized_sort_by = _normalize_sort_by(sort_by)
    if normalized_task_type in {"crop_flipkart", "crop_flipkart_chunk"}:
        return True
    return normalized_task_type in {"crop_meesho", "crop_meesho_chunk"} and normalized_sort_by in {
        "sku",
        "delivery",
        "size",
        "color",
    }


def _redis_client():
    global _redis_client_singleton
    if _redis_client_singleton is not None:
        return _redis_client_singleton
    redis_url = os.getenv("REDIS_URL", "").strip().strip("\"'")
    if not redis_url:
        raise RuntimeError("REDIS_URL is required when QUEUE_BACKEND=redis")
    try:
        import redis  # type: ignore
    except Exception as exc:
        raise RuntimeError("redis package is not installed") from exc
    with _client_lock:
        if _redis_client_singleton is None:
            _redis_client_singleton = redis.from_url(redis_url, decode_responses=True)
    return _redis_client_singleton


def _redis_queue_name() -> str:
    return os.getenv("REDIS_QUEUE_NAME", "labelhub:tasks").strip() or "labelhub:tasks"


def _redis_task_key(task_id: str) -> str:
    return f"{_redis_queue_name()}:task:{task_id}"


def _redis_user_tasks_key(user_id: int) -> str:
    return f"{_redis_queue_name()}:user:{int(user_id)}:tasks"


def _redis_idem_key(user_id: int, task_type: str, idem_key: str) -> str:
    digest = hashlib.sha256((idem_key or "").encode("utf-8")).hexdigest()
    return f"{_redis_queue_name()}:idem:{int(user_id)}:{task_type}:{digest}"


def _normalize_redis_task(data: dict) -> dict:
    payload = data.get("payload") or {}
    summary = data.get("summary") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload or "{}")
        except Exception:
            payload = {}
    if isinstance(summary, str):
        try:
            summary = json.loads(summary or "{}")
        except Exception:
            summary = {}
    return {
        "task_id": str(data.get("task_id") or ""),
        "user_id": int(data.get("user_id") or 0),
        "job_id": int(data.get("job_id") or 0),
        "task_type": str(data.get("task_type") or ""),
        "status": str(data.get("status") or "queued"),
        "progress": int(data.get("progress") or 0),
        "message": str(data.get("message") or ""),
        "error": str(data.get("error") or ""),
        "payload": payload,
        "summary": summary,
        "result_path": str(data.get("result_path") or ""),
        "attempts": int(data.get("attempts") or 0),
        "worker_id": str(data.get("worker_id") or ""),
        "lease_expires_at": str(data.get("lease_expires_at") or ""),
        "created_at": str(data.get("created_at") or ""),
        "updated_at": str(data.get("updated_at") or ""),
        "started_at": str(data.get("started_at") or ""),
        "finished_at": str(data.get("finished_at") or ""),
    }


def _redis_get_task(task_id: str) -> dict | None:
    raw = _redis_client().get(_redis_task_key(task_id))
    if not raw:
        return None
    try:
        return _normalize_redis_task(json.loads(raw))
    except Exception:
        logger.exception("Failed to decode Redis task %s", task_id)
        return None


def _redis_put_task(task: dict) -> None:
    clean = _normalize_redis_task(task)
    _redis_client().set(_redis_task_key(clean["task_id"]), json.dumps(clean, ensure_ascii=True))


def _is_past_iso(ts: str) -> bool:
    raw = str(ts or "").strip()
    if not raw:
        return False
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")) < _utc_now()
    except Exception:
        return False


def _maybe_requeue_expired_redis_tasks() -> int:
    """Best-effort repair for stale Redis running tasks with expired leases."""
    if not _use_redis_queue():
        return 0
    cooldown_sec = max(2.0, float(os.getenv("REDIS_REQUEUE_SCAN_COOLDOWN_SEC", "8") or 8))
    now_ts = time.time()
    last_ts = float(_redis_requeue_scan_state.get("ts") or 0.0)
    if now_ts - last_ts < cooldown_sec:
        return 0
    _redis_requeue_scan_state["ts"] = now_ts

    scan_limit = max(100, int(os.getenv("REDIS_REQUEUE_SCAN_LIMIT", "1500") or 1500))
    max_requeue = max(1, int(os.getenv("REDIS_REQUEUE_MAX_PER_SCAN", "30") or 30))
    client = _redis_client()
    queue_name = _redis_queue_name()
    repaired = 0
    scanned = 0
    for key in client.scan_iter(match=f"{queue_name}:task:*", count=200):
        scanned += 1
        if scanned > scan_limit or repaired >= max_requeue:
            break
        raw = client.get(key)
        if not raw:
            continue
        try:
            task = _normalize_redis_task(json.loads(raw))
        except Exception:
            continue
        if task.get("status") != "running":
            continue
        if not _is_past_iso(str(task.get("lease_expires_at") or "")):
            continue
        task["status"] = "queued"
        task["worker_id"] = ""
        task["lease_expires_at"] = ""
        task["message"] = "Requeued after lease timeout"
        task["updated_at"] = _utc_now_iso()
        _redis_put_task(task)
        client.rpush(queue_name, str(task.get("task_id") or ""))
        repaired += 1
    if repaired:
        logger.warning("Requeued %s stale Redis running task(s) after lease timeout", repaired)
    return repaired


def _s3_prefix() -> str:
    return os.getenv("S3_PREFIX", "labelhub/prod").strip().strip("/")


def _s3_key(*parts: object) -> str:
    clean_parts = [str(part).strip().strip("/").replace("\\", "/") for part in parts if str(part).strip()]
    prefix = _s3_prefix()
    return "/".join([part for part in [prefix, *clean_parts] if part])


def _s3_store():
    global _s3_store_singleton
    if _s3_store_singleton is not None:
        return _s3_store_singleton
    from hybrid.storage import S3ArtifactStore

    with _client_lock:
        if _s3_store_singleton is None:
            _s3_store_singleton = S3ArtifactStore()
    return _s3_store_singleton


def upload_task_inputs_to_s3(*, task_id: str, input_paths: list[str], user_id: int) -> list[dict]:
    """Upload local request files so a remote worker can hydrate them."""
    if not _use_s3_storage():
        return []
    store = _s3_store()
    uploaded: list[dict] = []
    for idx, path in enumerate(input_paths or []):
        src = Path(path)
        if not src.exists():
            continue
        key = _s3_key("tasks", task_id, "inputs", f"{idx:03d}-{src.name}")
        store.upload_file(key, str(src))
        uploaded.append({"key": key, "file_name": src.name})
    logger.info("Uploaded %s task input(s) to S3 for task=%s user=%s", len(uploaded), task_id, user_id)
    return uploaded


def _hydrate_s3_inputs_if_needed(task: dict) -> None:
    payload = task.get("payload") or {}
    input_refs = payload.get("input_s3_keys") or []
    if not input_refs:
        return
    store = _s3_store()
    tmpdir = tempfile.mkdtemp(prefix=f"worker_task_{task.get('task_id')}_")
    local_paths: list[str] = []
    for idx, ref in enumerate(input_refs):
        key = str(ref.get("key") if isinstance(ref, dict) else ref).strip()
        if not key:
            continue
        name = str(ref.get("file_name") if isinstance(ref, dict) else f"in_{idx}.pdf").strip() or f"in_{idx}.pdf"
        dest = Path(tmpdir) / f"in_{idx}_{Path(name).name}"
        store.download_to_file(key, str(dest))
        local_paths.append(str(dest))
    if not local_paths:
        raise RuntimeError("Task input files were not available in object storage")
    payload["input_paths"] = local_paths
    payload["output_dir"] = tmpdir
    payload["hydrated_from_s3"] = True
    task["payload"] = payload


def _upload_result_to_s3_if_needed(task: dict, result_path: str) -> str:
    if not (_use_s3_storage() and result_path and Path(result_path).exists()):
        return result_path
    bucket = os.getenv("S3_BUCKET", "").strip()
    key = _s3_key("tasks", task.get("task_id") or uuid.uuid4().hex, "outputs", Path(result_path).name)
    _s3_store().upload_file(key, result_path)
    return f"s3://{bucket}/{key}" if bucket else f"s3:///{key}"


def _download_s3_uri_to_file(uri: str, dest: str) -> None:
    raw = (uri or "").strip()
    if not raw.lower().startswith("s3://"):
        raise RuntimeError(f"Not an s3:// result path: {uri!r}")
    _s3_store().download_s3_uri_to_file(raw, dest)


def _merge_pdf_files(input_paths: list[str], output_path: str) -> None:
    merged = fitz.open()
    try:
        for p in input_paths:
            with fitz.open(p) as doc:
                merged.insert_pdf(doc)
        merged.save(output_path)
    finally:
        merged.close()


def _split_pdf_inputs_to_chunks(input_paths: list[str], output_dir: str, *, desired_chunks: int) -> list[dict]:
    pages: list[tuple[str, int]] = []
    for path in input_paths or []:
        with fitz.open(path) as doc:
            for page_index in range(len(doc)):
                pages.append((path, page_index))
    if not pages:
        return []

    total_pages = len(pages)
    chunk_count = max(1, min(int(desired_chunks), total_pages))
    chunk_size = max(1, (total_pages + chunk_count - 1) // chunk_count)
    chunks: list[dict] = []
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    for chunk_index, start in enumerate(range(0, total_pages, chunk_size)):
        chunk_pages = pages[start:start + chunk_size]
        chunk_path = out_root / f"fanout-chunk-{chunk_index:03d}.pdf"
        out_doc = fitz.open()
        try:
            for src_path, page_index in chunk_pages:
                with fitz.open(src_path) as src_doc:
                    out_doc.insert_pdf(src_doc, from_page=page_index, to_page=page_index)
            out_doc.save(str(chunk_path))
        finally:
            out_doc.close()
        chunks.append(
            {
                "chunk_index": chunk_index,
                "path": str(chunk_path),
                "start_page": start,
                "page_count": len(chunk_pages),
            }
        )
    return chunks

# Skull image stamped on suspicious-customer label pages. We ship a default
# asset alongside the backend so the marker works out-of-the-box, but operators
# can override the path via env in case the asset is moved or replaced.
_DEFAULT_SUSPICIOUS_MARKER_IMAGE = (Path(__file__).resolve().parent / "assets" / "suspicious_skull.png")
SUSPICIOUS_MARKER_IMAGE_PATH = os.getenv(
    "SUSPICIOUS_MARKER_IMAGE_PATH",
    str(_DEFAULT_SUSPICIOUS_MARKER_IMAGE),
)
RISK_PROFILE_FIELDS = [
    "customer_key",
    "Name",
    "Pincode",
    "risk_score",
    "risk_flag",
    "hit_count",
    "risky_orders_count",
    "risky_suborders",
    "last_return_type",
    "last_status",
    "last_reason",
    "last_detailed_reason",
    "first_seen_at",
    "last_seen_at",
    "updated_at",
]

# Canonical column order used when exporting per-split row data to XLSX.
# Mirrors the OCR master schema (matches `parse_required_fields` output) and
# appends light-weight provenance columns. Keep this list stable - downstream
# consumers may read these workbooks.
SPLIT_EXPORT_COLUMNS = [
    "Order_id",
    "Name",
    "Address_1",
    "Address_2",
    "Address_3",
    "District",
    "State",
    "Pincode",
    "Sku",
    "Size",
    "Color",
    "Quantity",
    "Payment_Mode",
    "Courier_Partner",
    "Courier_trans_id",
    # Seller / "Sold by" string lifted from the label when the parser
    # could identify it. Empty string when the source label does not
    # surface a seller line — never None, to keep the export type-stable.
    "Sold_By",
    "Source_PDF",
    "Page_Number",
]

SPLIT_EXPORT_FILENAMES = {
    "suspicious": "Suspicious_Customers.xlsx",
    "multi_order": "Multi_Order_Customers.xlsx",
    "pincode": "Separate_Pincode.xlsx",
}

SPLIT_EXPORT_SHEET_TITLES = {
    "suspicious": "SuspiciousCustomers",
    "multi_order": "MultiOrderCustomers",
    "pincode": "SeparatePincode",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _db_connect():
    return connect_db(DB_PATH)


def _normalize_artifact_platform(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in SUPPORTED_OCR_PLATFORMS:
        return raw
    if raw in {"legacy", "all", "union"}:
        return "legacy"
    return ""


def _analysis_artifact_kind_for_task_type(task_type: str) -> str:
    t = str(task_type or "").strip().lower()
    if t in {"ocr_csv", "ocr_excel"}:
        return "ocr_master"
    if t == "return_analysis":
        return "return_analysis"
    return ""


def _read_result_bytes(source_path: str) -> bytes | None:
    raw = str(source_path or "").strip()
    if not raw:
        return None
    try:
        if raw.lower().startswith("s3://"):
            cleanup_dir = tempfile.mkdtemp(prefix="artifact_snapshot_")
            try:
                from hybrid.storage import parse_s3_uri_to_bucket_key
                _bucket, obj_key = parse_s3_uri_to_bucket_key(raw)
                base_name = (obj_key.rsplit("/", 1)[-1] if obj_key else "") or "artifact.bin"
                local = Path(cleanup_dir) / base_name
                _download_s3_uri_to_file(raw, str(local))
                return local.read_bytes()
            finally:
                shutil.rmtree(cleanup_dir, ignore_errors=True)
        return Path(raw).read_bytes()
    except Exception:
        return None


def _upsert_analysis_artifact_snapshot(
    *,
    user_id: int,
    task_id: str,
    task_type: str,
    artifact_kind: str,
    platform: str,
    source_path: str,
    content_bytes: bytes,
) -> None:
    if not content_bytes:
        return
    if len(content_bytes) > ANALYSIS_ARTIFACT_DB_MAX_BYTES:
        logger.warning(
            "analysis artifact snapshot skipped (too large): user=%s task=%s kind=%s bytes=%s",
            user_id,
            task_id,
            artifact_kind,
            len(content_bytes),
        )
        return
    now_iso = _utc_now_iso()
    content_sha256 = hashlib.sha256(content_bytes).hexdigest()
    with _db_connect() as conn:
        if is_postgres_backend():
            conn.execute(
                """
                INSERT INTO analysis_artifact_snapshots (
                    user_id, task_id, task_type, artifact_kind, platform, source_path,
                    content_bytes, content_sha256, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, artifact_kind, platform)
                DO UPDATE SET
                    task_id = EXCLUDED.task_id,
                    task_type = EXCLUDED.task_type,
                    source_path = EXCLUDED.source_path,
                    content_bytes = EXCLUDED.content_bytes,
                    content_sha256 = EXCLUDED.content_sha256,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    int(user_id),
                    str(task_id or ""),
                    str(task_type or ""),
                    str(artifact_kind or ""),
                    str(platform or ""),
                    str(source_path or ""),
                    bytes(content_bytes),
                    content_sha256,
                    now_iso,
                    now_iso,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO analysis_artifact_snapshots (
                    user_id, task_id, task_type, artifact_kind, platform, source_path,
                    content_bytes, content_sha256, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, artifact_kind, platform)
                DO UPDATE SET
                    task_id = excluded.task_id,
                    task_type = excluded.task_type,
                    source_path = excluded.source_path,
                    content_bytes = excluded.content_bytes,
                    content_sha256 = excluded.content_sha256,
                    updated_at = excluded.updated_at
                """,
                (
                    int(user_id),
                    str(task_id or ""),
                    str(task_type or ""),
                    str(artifact_kind or ""),
                    str(platform or ""),
                    str(source_path or ""),
                    bytes(content_bytes),
                    content_sha256,
                    now_iso,
                    now_iso,
                ),
            )


def _snapshot_task_analysis_artifacts(task: dict, *, result_path: str, summary: dict) -> None:
    task_type = str(task.get("task_type") or "").strip().lower()
    artifact_kind = _analysis_artifact_kind_for_task_type(task_type)
    if not artifact_kind:
        return
    user_id = int(task.get("user_id") or 0)
    if user_id <= 0:
        return
    task_id = str(task.get("task_id") or "").strip()
    if not task_id:
        return
    payload = task.get("payload") or {}
    options = (payload.get("options") if isinstance(payload, dict) else {}) or {}
    if not isinstance(options, dict):
        options = {}
    if not isinstance(summary, dict):
        summary = {}
    platform = _normalize_artifact_platform(
        summary.get("master_platform")
        or summary.get("risk_profile_platform")
        or options.get("source_platform")
    )

    main_bytes = _read_result_bytes(result_path)
    if main_bytes:
        _upsert_analysis_artifact_snapshot(
            user_id=user_id,
            task_id=task_id,
            task_type=task_type,
            artifact_kind=artifact_kind,
            platform=platform,
            source_path=result_path,
            content_bytes=main_bytes,
        )

    # Return-analysis also emits suspicious-customer CSV; persist that too.
    if task_type == "return_analysis":
        risk_path = str((summary or {}).get("risk_profile_path") or "").strip()
        if risk_path:
            risk_bytes = _read_result_bytes(risk_path)
            if risk_bytes:
                _upsert_analysis_artifact_snapshot(
                    user_id=user_id,
                    task_id=task_id,
                    task_type=task_type,
                    artifact_kind="suspicious_customers",
                    platform=_normalize_artifact_platform(summary.get("risk_profile_platform") or options.get("source_platform")),
                    source_path=risk_path,
                    content_bytes=risk_bytes,
                )


def get_analysis_artifact_snapshot_bytes_for_user(
    *,
    user_id: int,
    artifact_kind: str,
    platform: object | None = None,
) -> bytes | None:
    safe_user_id = int(user_id)
    if safe_user_id <= 0:
        return None
    kind = str(artifact_kind or "").strip().lower()
    if not kind:
        return None
    norm_platform = _normalize_artifact_platform(platform)
    with _db_connect() as conn:
        if norm_platform:
            row = conn.execute(
                """
                SELECT content_bytes
                FROM analysis_artifact_snapshots
                WHERE user_id = ? AND artifact_kind = ? AND platform = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (safe_user_id, kind, norm_platform),
            ).fetchone()
            if row and row["content_bytes"] is not None:
                return bytes(row["content_bytes"])
        row = conn.execute(
            """
            SELECT content_bytes
            FROM analysis_artifact_snapshots
            WHERE user_id = ? AND artifact_kind = ?
              AND (platform = '' OR platform = 'legacy')
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (safe_user_id, kind),
        ).fetchone()
        if row and row["content_bytes"] is not None:
            return bytes(row["content_bytes"])
        row = conn.execute(
            """
            SELECT content_bytes
            FROM analysis_artifact_snapshots
            WHERE user_id = ? AND artifact_kind = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (safe_user_id, kind),
        ).fetchone()
    if not row or row["content_bytes"] is None:
        return None
    return bytes(row["content_bytes"])


def _is_db_locked_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "database is locked" in str(exc).lower()


def _run_with_db_lock_retry(operation: str, fn: Callable[[], T]) -> T:
    delay = TASK_DB_LOCK_RETRY_BASE_DELAY_SEC
    for attempt in range(1, TASK_DB_LOCK_RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if not _is_db_locked_error(exc):
                raise
            if attempt >= TASK_DB_LOCK_RETRY_ATTEMPTS:
                logger.error("SQLite lock persisted during %s after %s attempts", operation, attempt)
                raise
            logger.warning(
                "SQLite lock during %s (attempt %s/%s), retrying in %.2fs",
                operation,
                attempt,
                TASK_DB_LOCK_RETRY_ATTEMPTS,
                delay,
            )
            time.sleep(delay)
            delay = min(TASK_DB_LOCK_RETRY_MAX_DELAY_SEC, delay * 2)


def _ensure_ocr_master_dir() -> None:
    OCR_MASTER_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_risk_store_dir() -> None:
    RISK_STORE_DIR.mkdir(parents=True, exist_ok=True)


# Per-platform master OCR layout
# -----------------------------------------------------------------------------
# We keep one master CSV per (user, platform). The legacy file
# ``user_{id}_orders.csv`` continues to be maintained as a UNION across all
# known platform files so that pre-existing consumers (return-analysis, manual
# risk lookup, customer history, loyal-customer evaluation) don't regress when
# they were not platform-aware.
SUPPORTED_OCR_PLATFORMS: tuple[str, ...] = ("meesho", "flipkart")


def _normalize_ocr_platform(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in SUPPORTED_OCR_PLATFORMS:
        return raw
    return ""


_OCR_MASTER_PLATFORM_FILENAME = re.compile(
    r"^user_(?P<uid>\d+)_(?P<plat>meesho|flipkart)_orders\.csv$",
    re.IGNORECASE,
)


def _ocr_master_result_path_is_resolvable(result_path: object) -> bool:
    """True if the API can read this artifact (local file or S3 URI).

    Worker-only POSIX paths in Redis/SQLite must not short-circuit lookups; the
    admin download would 404 while the UI still showed master data available.
    """
    raw = str(result_path or "").strip()
    if not raw:
        return False
    if raw.startswith("s3://"):
        return True
    try:
        return Path(raw).is_file()
    except OSError:
        return False


def _infer_ocr_master_platform_from_result_path(result_path: object) -> str:
    """Parse meesho/flipkart from canonical master filenames (local or s3://…/name)."""
    raw = str(result_path or "").strip()
    if not raw:
        return ""
    # Strip query/fragment if ever present on URIs
    base = raw.split("?", 1)[0].split("#", 1)[0].strip()
    name = Path(base).name
    m = _OCR_MASTER_PLATFORM_FILENAME.match(name)
    if not m:
        return ""
    return _normalize_ocr_platform(m.group("plat"))


def _task_ocr_source_platform(task: dict) -> str:
    """Best-effort platform tag for an OCR task (meesho / flipkart / '')."""
    summary = task.get("summary") or {}
    payload = task.get("payload") or {}
    options = payload.get("options") or {}
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(options, dict):
        options = {}
    tagged = _normalize_ocr_platform(summary.get("master_platform"))
    if tagged:
        return tagged
    tagged = _normalize_ocr_platform(options.get("source_platform"))
    if tagged:
        return tagged
    return _infer_ocr_master_platform_from_result_path(task.get("result_path"))


def _redis_latest_successful_ocr_snapshot(user_id: int, norm_platform: str) -> dict | None:
    """Resolve latest successful OCR master from Redis (worker truth in queue mode)."""
    if not redis_ocr_master_lookup_enabled():
        return None
    try:
        client = _redis_client()
        task_ids = client.zrevrange(_redis_user_tasks_key(int(user_id)), 0, 299)
    except Exception:
        logger.exception("Redis OCR master lookup failed user_id=%s", user_id)
        return None
    scored: list[tuple[str, dict]] = []
    for raw_id in task_ids or []:
        task = _redis_get_task(str(raw_id))
        if not task:
            continue
        if task.get("task_type") not in {"ocr_csv", "ocr_excel"}:
            continue
        if str(task.get("status") or "").lower() != "success":
            continue
        result_path = str(task.get("result_path") or "").strip()
        if not result_path:
            continue
        tp = _task_ocr_source_platform(task)
        if norm_platform and tp != norm_platform:
            continue
        sort_key = str(task.get("finished_at") or task.get("updated_at") or "")
        scored.append((sort_key, task))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    for _sort_key, task in scored:
        result_path = str(task.get("result_path") or "").strip()
        if not _ocr_master_result_path_is_resolvable(result_path):
            continue
        try:
            _sync_local_task_from_redis(task)
        except Exception:
            logger.exception("sync OCR task from redis failed task_id=%s", task.get("task_id"))
        summary = task.get("summary") or {}
        if not isinstance(summary, dict):
            summary = {}
        tp = _task_ocr_source_platform(task)
        return {
            "task_id": str(task.get("task_id") or ""),
            "result_path": result_path,
            "updated_at": str(task.get("updated_at") or task.get("finished_at") or ""),
            "platform": tp or "legacy",
            "summary": summary,
        }
    return None


def _user_ocr_master_csv_path(user_id: int, platform: object | None = None) -> Path:
    """Return the master OCR CSV path for a user.

    Passing a recognized platform (``meesho``/``flipkart``) returns the
    platform-scoped file. Anything else returns the legacy union file path
    (``user_{id}_orders.csv``) for backward compatibility.
    """
    _ensure_ocr_master_dir()
    norm = _normalize_ocr_platform(platform)
    safe_user_id = int(user_id)
    if norm:
        return OCR_MASTER_DIR / f"user_{safe_user_id}_{norm}_orders.csv"
    return OCR_MASTER_DIR / f"user_{safe_user_id}_orders.csv"


def _user_ocr_master_csv_paths_all(user_id: int) -> list[Path]:
    """Return every existing master OCR CSV for ``user_id``.

    Includes the legacy union file plus any supported per-platform files.
    Order is stable: legacy first (kept for tie-breaking), then platforms
    sorted by platform name. Callers should de-duplicate downstream rows.
    """
    paths: list[Path] = []
    legacy = _user_ocr_master_csv_path(int(user_id), None)
    if legacy.exists():
        paths.append(legacy)
    for platform in SUPPORTED_OCR_PLATFORMS:
        candidate = _user_ocr_master_csv_path(int(user_id), platform)
        if candidate.exists():
            paths.append(candidate)
    return paths


def _read_master_rows_all_platforms(user_id: int) -> list[dict]:
    """Read and merge master OCR rows across legacy + per-platform files.

    Rows are de-duplicated by suborder id (Order_id) to prevent inflating
    counts when the legacy union file overlaps with a platform-specific file.
    """
    seen_subs: set[str] = set()
    merged: list[dict] = []
    for path in _user_ocr_master_csv_paths_all(int(user_id)):
        try:
            rows = _read_csv_rows(path)
        except Exception:
            logger.exception("Failed to read master OCR CSV at %s", path)
            continue
        for row in rows:
            sub = _norm_suborder(row.get("Order_id", "") or row.get("Suborder Number", ""))
            if sub:
                if sub in seen_subs:
                    continue
                seen_subs.add(sub)
            merged.append(row)
    return merged


def _normalize_risk_platform(value: object) -> str:
    # Risk-profile platform support mirrors OCR master platform support.
    return _normalize_ocr_platform(value)


def _user_risk_profile_csv_path(user_id: int, platform: object | None = None) -> Path:
    _ensure_risk_store_dir()
    safe_user_id = int(user_id)
    norm = _normalize_risk_platform(platform)
    if norm:
        return RISK_STORE_DIR / f"user_{safe_user_id}_{norm}_suspicious_customers.csv"
    return RISK_STORE_DIR / f"user_{safe_user_id}_suspicious_customers.csv"


def _user_risk_profile_csv_paths_all(user_id: int) -> list[Path]:
    paths: list[Path] = []
    legacy = _user_risk_profile_csv_path(int(user_id), None)
    if legacy.exists():
        paths.append(legacy)
    for platform in SUPPORTED_OCR_PLATFORMS:
        candidate = _user_risk_profile_csv_path(int(user_id), platform)
        if candidate.exists():
            paths.append(candidate)
    return paths


def _path_is_ocr_master(path: str) -> bool:
    p = Path(path or "").resolve()
    try:
        p.relative_to(OCR_MASTER_DIR)
        return True
    except Exception:
        return False


def _path_is_risk_profile_store(path: str) -> bool:
    try:
        Path(path or "").resolve().relative_to(RISK_STORE_DIR)
        return True
    except Exception:
        return False


def _path_should_never_bulk_delete(path: str) -> bool:
    """OCR master CSVs and risk/suspicious profile CSVs are retained; never purged as crop debris."""
    return _path_is_ocr_master(path) or _path_is_risk_profile_store(path)


def delete_stored_task_result(result_path: str) -> None:
    """Delete a task result file from local disk or S3 (crop PDFs, etc.). Never call for master/risk paths."""
    raw = (result_path or "").strip()
    if not raw:
        return
    if raw.lower().startswith("s3://"):
        if not _use_s3_storage():
            return
        try:
            _s3_store().delete_s3_uri(raw)
        except Exception:
            logger.exception("delete_stored_task_result: S3 delete failed for %s", raw)
        return
    try:
        Path(raw).unlink(missing_ok=True)
    except Exception:
        logger.exception("delete_stored_task_result: local unlink failed for %s", raw)


def _read_csv_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    if _path_is_ocr_master(str(path)):
        _ensure_ocr_master_csv_schema(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if not r:
                continue
            rows.append({str(k or "").lstrip("\ufeff").strip(): ("" if v is None else str(v)) for k, v in r.items()})
    return rows


def _ensure_ocr_master_csv_schema(path: Path) -> None:
    """Rewrite legacy OCR master CSVs with the current stable header order."""
    try:
        if not path.exists() or not path.is_file():
            return
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            existing_headers = [str(h or "").lstrip("\ufeff").strip() for h in (reader.fieldnames or [])]
            if existing_headers == list(OCR_MASTER_HEADERS):
                return
            rows = []
            for row in reader:
                if not row:
                    continue
                normalized = {header: "" for header in OCR_MASTER_HEADERS}
                for key, value in row.items():
                    clean_key = str(key or "").lstrip("\ufeff").strip()
                    if clean_key in normalized:
                        normalized[clean_key] = "" if value is None else str(value)
                rows.append(normalized)
        path.write_bytes(build_csv_bytes(rows, column_preset="standard_v1", custom_columns=""))
    except Exception:
        logger.exception("Failed to normalize OCR master CSV schema at %s", path)


def _ocr_master_record_key(record: dict) -> str:
    return "".join(ch for ch in str(record.get("Order_id", "") or "").strip().lower() if ch.isalnum())


def _merge_ocr_master_records(existing_records: list[dict], new_records: list[dict]) -> tuple[list[dict], int]:
    """Merge OCR master rows so a re-uploaded order replaces stale parsed data."""
    merged: list[dict] = []
    index_by_key: dict[str, int] = {}
    replaced = 0
    no_key_counter = 0

    def _normalized_row(row: dict) -> dict:
        normalized = {header: "" for header in OCR_MASTER_HEADERS}
        for key, value in (row or {}).items():
            clean_key = str(key or "").strip()
            if clean_key in normalized:
                normalized[clean_key] = "" if value is None else str(value)
        return normalized

    for row in existing_records or []:
        normalized = _normalized_row(row)
        key = _ocr_master_record_key(normalized)
        if not key:
            key = f"existing-no-order:{no_key_counter}"
            no_key_counter += 1
        if key in index_by_key:
            merged[index_by_key[key]] = normalized
            replaced += 1
            continue
        index_by_key[key] = len(merged)
        merged.append(normalized)

    for row in new_records or []:
        normalized = _normalized_row(row)
        key = _ocr_master_record_key(normalized)
        if not key:
            key = f"new-no-order:{no_key_counter}"
            no_key_counter += 1
        if key in index_by_key:
            merged[index_by_key[key]] = normalized
            replaced += 1
            continue
        index_by_key[key] = len(merged)
        merged.append(normalized)

    return merged, replaced


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for idx, _ in enumerate(reader):
            if idx == 0:
                continue
            count += 1
    return count


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value or "").strip()))
    except Exception:
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value or "").strip())
    except Exception:
        return default


def _norm_text(value: object) -> str:
    return ("" if value is None else str(value)).strip().lower()


def _norm_suborder(value: object) -> str:
    return _norm_text(value).replace(" ", "")


def _norm_pincode(value: object) -> str:
    raw = "".join(ch for ch in _norm_text(value) if ch.isdigit())
    return raw[:6]


def _parse_pincode_list(raw: object) -> set[str]:
    text = str(raw or "").strip()
    if not text:
        return set()
    parts = []
    for token in text.replace("\n", ",").replace("|", ",").split(","):
        token = token.strip()
        if token:
            parts.append(token)
    out = set()
    for p in parts:
        norm = _norm_pincode(p)
        if len(norm) == 6:
            out.add(norm)
    return out


def _option_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _extract_pincodes_from_page_text(text: str) -> set[str]:
    if not text:
        return set()
    import re

    out: set[str] = set()
    for token in re.findall(r"\b(\d{6})\b", text):
        norm = _norm_pincode(token)
        if len(norm) == 6:
            out.add(norm)
    return out


def _customer_key(name: object, pincode: object) -> str:
    safe_name = "".join(ch for ch in _norm_text(name) if ch.isalnum())
    safe_pin = _norm_pincode(pincode)
    if not safe_name and not safe_pin:
        return ""
    return f"{safe_name}|{safe_pin}"


def _customer_key_strict(name: object, pincode: object) -> str:
    """Build a strict customer key that requires both name and pincode."""
    safe_name = "".join(ch for ch in _norm_text(name) if ch.isalnum())
    safe_pin = _norm_pincode(pincode)
    if not safe_name or not safe_pin:
        return ""
    return f"{safe_name}|{safe_pin}"


def _norm_address_for_match(value: object) -> str:
    """Normalize address text for conservative equality checks."""
    return "".join(ch for ch in _norm_text(value) if ch.isalnum())


def _is_practical_name_match(seed_name: object, row_name: object) -> bool:
    """Conservative fallback for small OCR variations in customer names."""
    seed_norm = "".join(ch for ch in _norm_text(seed_name) if ch.isalnum())
    row_norm = "".join(ch for ch in _norm_text(row_name) if ch.isalnum())
    if not seed_norm or not row_norm:
        return False
    if seed_norm == row_norm:
        return True
    # Prefix/containment catches common OCR truncations, but still requires
    # pincode match at call sites to keep false positives low.
    if len(seed_norm) >= 5 and len(row_norm) >= 5:
        if seed_norm.startswith(row_norm) or row_norm.startswith(seed_norm):
            return True
    seed_tokens = [tok for tok in "".join(ch if ch.isalnum() else " " for ch in _norm_text(seed_name)).split() if len(tok) >= 3]
    row_tokens = [tok for tok in "".join(ch if ch.isalnum() else " " for ch in _norm_text(row_name)).split() if len(tok) >= 3]
    if not seed_tokens or not row_tokens:
        return False
    if seed_tokens[0] != row_tokens[0]:
        return False
    overlap = len(set(seed_tokens) & set(row_tokens))
    if overlap >= 2:
        return True
    if overlap == 1 and (len(seed_tokens) == 1 or len(row_tokens) == 1) and len(seed_tokens[0]) >= 5:
        return True
    return False


def _is_risky_return_row(row: dict) -> bool:
    text = " ".join(
        [
            _norm_text(row.get("Type of Return")),
            _norm_text(row.get("Sub Type")),
            _norm_text(row.get("Status")),
            _norm_text(row.get("Return Reason")),
            _norm_text(row.get("Detailed Return Reason")),
        ]
    )
    if not text:
        return False
    markers = [
        "rto",
        "customer return",
        "defective",
        "damaged",
        "broken",
        "missing",
        "wrong",
        "not delivered",
        "quality",
        "different product",
    ]
    return any(m in text for m in markers)


def _is_rto_return_row(row: dict) -> bool:
    text = " ".join(
        [
            _norm_text(row.get("Type of Return")),
            _norm_text(row.get("Sub Type")),
            _norm_text(row.get("Status")),
            _norm_text(row.get("Return Reason")),
            _norm_text(row.get("Detailed Return Reason")),
        ]
    )
    if not text:
        return False
    return "rto" in text or "return to origin" in text


def _risk_event_score(row: dict) -> float:
    text = " ".join(
        [
            _norm_text(row.get("Type of Return")),
            _norm_text(row.get("Sub Type")),
            _norm_text(row.get("Status")),
            _norm_text(row.get("Return Reason")),
            _norm_text(row.get("Detailed Return Reason")),
        ]
    )
    score = 2.0
    if "rto" in text:
        score += 4.0
    if "customer return" in text:
        score += 2.0
    severe_markers = ["defective", "damaged", "broken", "missing", "wrong", "different product", "quality"]
    for marker in severe_markers:
        if marker in text:
            score += 2.0
    if "not delivered" in text:
        score += 1.5
    return round(min(score, 20.0), 2)


def _risk_level(score: float) -> str:
    if score >= RISK_HIGH_SCORE:
        return "HIGH"
    if score >= RISK_MEDIUM_SCORE:
        return "MEDIUM"
    return "LOW"


def _split_suborders(raw: object) -> set[str]:
    text = str(raw or "").strip()
    if not text:
        return set()
    parts = [p.strip() for p in text.replace(",", "|").split("|")]
    return {p for p in (_norm_suborder(x) for x in parts) if p}


def _risk_profile_from_row(row: dict) -> tuple[str, dict] | None:
    key = (str(row.get("customer_key", "")).strip() or _customer_key(row.get("Name", ""), row.get("Pincode", "")))
    fallback_sub = _norm_suborder(row.get("Suborder Number", ""))
    subs = _split_suborders(row.get("risky_suborders", ""))
    if fallback_sub:
        subs.add(fallback_sub)
    if not key:
        if not subs:
            return None
        key = f"suborder:{sorted(subs)[0]}"
    score = _safe_float(row.get("risk_score"), default=0.0)
    if score <= 0:
        score = 10.0 if _norm_text(row.get("risk_flag")) in {"high", "medium"} else 0.0
    now_iso = _utc_now_iso()
    profile = {
        "customer_key": key if not key.startswith("suborder:") else "",
        "Name": str(row.get("Name", "")).strip(),
        "Pincode": str(row.get("Pincode", "")).strip(),
        "risk_score": score,
        "hit_count": max(1, _safe_int(row.get("hit_count"), default=1)),
        "suborders": set(subs),
        "last_return_type": str(row.get("last_return_type", row.get("Type of Return", ""))).strip(),
        "last_status": str(row.get("last_status", row.get("Status", ""))).strip(),
        "last_reason": str(row.get("last_reason", row.get("Return Reason", ""))).strip(),
        "last_detailed_reason": str(row.get("last_detailed_reason", row.get("Detailed Return Reason", ""))).strip(),
        "first_seen_at": str(row.get("first_seen_at", "")).strip() or now_iso,
        "last_seen_at": str(row.get("last_seen_at", "")).strip() or now_iso,
        "updated_at": str(row.get("updated_at", "")).strip() or now_iso,
    }
    return key, profile


def _merge_risk_profile_maps(base: dict[str, dict], incoming: dict[str, dict]) -> dict[str, dict]:
    for key, profile in (incoming or {}).items():
        if key not in base:
            base[key] = {
                **profile,
                "suborders": set(profile.get("suborders") or set()),
            }
            continue
        existing = base[key]
        merged_suborders = set(existing.get("suborders") or set())
        merged_suborders.update(set(profile.get("suborders") or set()))
        # Keep the strongest risk signal in the legacy union view.
        existing_score = _safe_float(existing.get("risk_score"), 0.0)
        incoming_score = _safe_float(profile.get("risk_score"), 0.0)
        keep_incoming = incoming_score >= existing_score
        chosen = profile if keep_incoming else existing
        base[key] = {
            **existing,
            **profile,
            "customer_key": str(chosen.get("customer_key", "")).strip(),
            "Name": str(chosen.get("Name", "")).strip(),
            "Pincode": str(chosen.get("Pincode", "")).strip(),
            "risk_score": max(existing_score, incoming_score),
            "hit_count": max(_safe_int(existing.get("hit_count"), 0), _safe_int(profile.get("hit_count"), 0)),
            "suborders": merged_suborders,
            "first_seen_at": str(existing.get("first_seen_at") or profile.get("first_seen_at") or "").strip(),
            "last_seen_at": str(chosen.get("last_seen_at", "")).strip(),
            "updated_at": str(chosen.get("updated_at", "")).strip(),
            "last_return_type": str(chosen.get("last_return_type", "")).strip(),
            "last_status": str(chosen.get("last_status", "")).strip(),
            "last_reason": str(chosen.get("last_reason", "")).strip(),
            "last_detailed_reason": str(chosen.get("last_detailed_reason", "")).strip(),
        }
    return base


def _load_risk_profiles_from_path(profile_path: Path) -> dict[str, dict]:
    if not profile_path.exists():
        return {}
    rows = _read_csv_rows(profile_path)
    out: dict[str, dict] = {}
    for row in rows:
        parsed = _risk_profile_from_row(row)
        if not parsed:
            continue
        key, profile = parsed
        out[key] = profile
    return out


def _load_risk_profiles(user_id: int, platform: object | None = None) -> dict[str, dict]:
    safe_user_id = int(user_id)
    norm_platform = _normalize_risk_platform(platform)
    profile_path = _user_risk_profile_csv_path(safe_user_id, norm_platform or None)
    if profile_path.exists():
        return _load_risk_profiles_from_path(profile_path)
    # Migration fallback: when a platform-specific file doesn't exist yet,
    # keep reading the legacy union file to avoid empty-risk regressions.
    if norm_platform:
        legacy_path = _user_risk_profile_csv_path(safe_user_id, None)
        if legacy_path.exists():
            return _load_risk_profiles_from_path(legacy_path)
    return {}


def _write_risk_profiles_to_path(profile_path: Path, profiles: dict[str, dict]) -> None:
    out_rows: list[dict] = []
    for _, p in sorted(
        profiles.items(),
        key=lambda kv: (_safe_float(kv[1].get("risk_score"), 0.0), _safe_int(kv[1].get("hit_count"), 0)),
        reverse=True,
    ):
        subs = sorted({s for s in (p.get("suborders") or set()) if s})
        score = _safe_float(p.get("risk_score"), 0.0)
        out_rows.append(
            {
                "customer_key": str(p.get("customer_key", "")).strip(),
                "Name": str(p.get("Name", "")).strip(),
                "Pincode": str(p.get("Pincode", "")).strip(),
                "risk_score": f"{score:.2f}",
                "risk_flag": _risk_level(score),
                "hit_count": _safe_int(p.get("hit_count"), 0),
                "risky_orders_count": len(subs),
                "risky_suborders": "|".join(subs),
                "last_return_type": str(p.get("last_return_type", "")).strip(),
                "last_status": str(p.get("last_status", "")).strip(),
                "last_reason": str(p.get("last_reason", "")).strip(),
                "last_detailed_reason": str(p.get("last_detailed_reason", "")).strip(),
                "first_seen_at": str(p.get("first_seen_at", "")).strip() or _utc_now_iso(),
                "last_seen_at": str(p.get("last_seen_at", "")).strip() or _utc_now_iso(),
                "updated_at": str(p.get("updated_at", "")).strip() or _utc_now_iso(),
            }
        )
    with profile_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RISK_PROFILE_FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)


def _refresh_legacy_risk_profile_union(user_id: int) -> None:
    safe_user_id = int(user_id)
    legacy_path = _user_risk_profile_csv_path(safe_user_id, None)
    merged: dict[str, dict] = {}
    if legacy_path.exists():
        _merge_risk_profile_maps(merged, _load_risk_profiles_from_path(legacy_path))
    for platform in SUPPORTED_OCR_PLATFORMS:
        platform_path = _user_risk_profile_csv_path(safe_user_id, platform)
        if not platform_path.exists():
            continue
        _merge_risk_profile_maps(merged, _load_risk_profiles_from_path(platform_path))
    _write_risk_profiles_to_path(legacy_path, merged)


def _write_risk_profiles(user_id: int, profiles: dict[str, dict], platform: object | None = None) -> None:
    safe_user_id = int(user_id)
    norm_platform = _normalize_risk_platform(platform)
    profile_path = _user_risk_profile_csv_path(safe_user_id, norm_platform or None)
    _write_risk_profiles_to_path(profile_path, profiles)
    if norm_platform:
        _refresh_legacy_risk_profile_union(safe_user_id)


def _manual_risk_stats(user_id: int, platform: object | None = None) -> tuple[int, int]:
    profiles = _load_risk_profiles(int(user_id), platform=platform)
    customers = 0
    suborders: set[str] = set()
    for profile in profiles.values():
        reason = _norm_text(profile.get("last_reason"))
        status = _norm_text(profile.get("last_status"))
        is_manual = reason == "manual_marked_by_user" or status == "manual_high_risk"
        if not is_manual:
            continue
        customers += 1
        suborders.update({s for s in (profile.get("suborders") or set()) if s})
    return customers, len(suborders)


def _customer_blacklist_metrics(
    *,
    user_id: int,
    analysis_rows: list[dict],
    platform: object | None = None,
) -> dict[str, dict[str, float]]:
    """Compute customer return-rate metrics used for blacklist activation.

    Suspicious rule:
      (total_customer_returns / (orders - rto_count)) * 100 >= 60

    Safe-guard:
      when (orders - rto_count) <= 0, ratio is not evaluated and the customer
      is treated as non-suspicious by this rule.
    """
    safe_user_id = int(user_id)
    norm_platform = _normalize_risk_platform(platform)
    master_rows: list[dict] = []
    if norm_platform:
        platform_master_path = _user_ocr_master_csv_path(safe_user_id, norm_platform)
        if platform_master_path.exists():
            master_rows = _read_csv_rows(platform_master_path)
    if not master_rows:
        master_rows = _read_master_rows_all_platforms(safe_user_id)

    total_orders_by_customer: dict[str, int] = {}
    seen_orders_by_customer: dict[str, set[str]] = {}
    for row in master_rows:
        ckey = _customer_key(row.get("Name", ""), row.get("Pincode", ""))
        if not ckey:
            continue
        sub = _norm_suborder(row.get("Order_id", "") or row.get("Suborder Number", ""))
        if not sub:
            continue
        seen = seen_orders_by_customer.setdefault(ckey, set())
        if sub in seen:
            continue
        seen.add(sub)
        total_orders_by_customer[ckey] = total_orders_by_customer.get(ckey, 0) + 1

    rto_count_by_customer: dict[str, int] = {}
    customer_returns_by_customer: dict[str, int] = {}
    seen_return_rows: set[str] = set()
    for row in analysis_rows:
        if _norm_text(row.get("match_status")) != "matched":
            continue
        ckey = _customer_key(row.get("Name", ""), row.get("Pincode", ""))
        if not ckey:
            continue
        sub = _norm_suborder(row.get("Suborder Number", ""))
        awb = _norm_text(row.get("AWB Number", ""))
        fingerprint = "|".join(
            [
                ckey,
                sub,
                awb,
                _norm_text(row.get("Type of Return", "")),
                _norm_text(row.get("Sub Type", "")),
                _norm_text(row.get("Status", "")),
                _norm_text(row.get("Return Reason", "")),
                _norm_text(row.get("Detailed Return Reason", "")),
            ]
        )
        if fingerprint in seen_return_rows:
            continue
        seen_return_rows.add(fingerprint)
        if _is_rto_return_row(row):
            rto_count_by_customer[ckey] = rto_count_by_customer.get(ckey, 0) + 1
        else:
            customer_returns_by_customer[ckey] = customer_returns_by_customer.get(ckey, 0) + 1

    out: dict[str, dict[str, float]] = {}
    for ckey, total_orders in total_orders_by_customer.items():
        rto_count = max(0, int(rto_count_by_customer.get(ckey, 0)))
        customer_returns = max(0, int(customer_returns_by_customer.get(ckey, 0)))
        denominator = int(total_orders) - rto_count
        if denominator <= 0:
            out[ckey] = {
                "total_orders": float(total_orders),
                "rto_count": float(rto_count),
                "customer_returns": float(customer_returns),
                "denominator": float(denominator),
                "return_rate_percent": 0.0,
                "blacklist_by_return_rate": 0.0,
            }
            continue
        return_rate = (float(customer_returns) / float(denominator)) * 100.0
        out[ckey] = {
            "total_orders": float(total_orders),
            "rto_count": float(rto_count),
            "customer_returns": float(customer_returns),
            "denominator": float(denominator),
            "return_rate_percent": round(return_rate, 2),
            "blacklist_by_return_rate": 1.0 if return_rate >= 60.0 else 0.0,
        }
    return out


def _build_risk_profile_from_analysis_csv(
    *,
    user_id: int,
    analysis_csv_path: str,
    platform: object | None = None,
) -> dict:
    source_path = Path(analysis_csv_path)
    if not source_path.exists():
        raise ValueError("Return analysis CSV missing for risk profile build.")
    safe_user_id = int(user_id)
    norm_platform = _normalize_risk_platform(platform)
    profile_path = _user_risk_profile_csv_path(safe_user_id, norm_platform or None)
    rows = _read_csv_rows(source_path)
    now_iso = _utc_now_iso()
    blacklist_metrics = _customer_blacklist_metrics(
        user_id=safe_user_id,
        analysis_rows=rows,
        platform=norm_platform or None,
    )
    existing_rows = _read_csv_rows(profile_path)
    if not existing_rows and norm_platform:
        legacy_path = _user_risk_profile_csv_path(safe_user_id, None)
        if legacy_path.exists():
            existing_rows = _read_csv_rows(legacy_path)
    profiles: dict[str, dict] = {}
    suborders_by_key: dict[str, set[str]] = {}

    for row in existing_rows:
        key = (str(row.get("customer_key", "")).strip() or _customer_key(row.get("Name", ""), row.get("Pincode", "")))
        fallback_sub = _norm_suborder(row.get("Suborder Number", ""))
        if not key:
            if fallback_sub:
                key = f"suborder:{fallback_sub}"
            else:
                continue
        existing_suborders = _split_suborders(row.get("risky_suborders", ""))
        if fallback_sub:
            existing_suborders.add(fallback_sub)
        suborders_by_key[key] = existing_suborders
        score = _safe_float(row.get("risk_score"), default=0.0)
        if score <= 0:
            score = 10.0 if _norm_text(row.get("risk_flag")) in {"high", "medium"} else 0.0
        profiles[key] = {
            "customer_key": key if not key.startswith("suborder:") else "",
            "Name": str(row.get("Name", "")).strip(),
            "Pincode": str(row.get("Pincode", "")).strip(),
            "risk_score": score,
            "risk_flag": _risk_level(score),
            "hit_count": max(1, _safe_int(row.get("hit_count"), default=1)),
            "first_seen_at": str(row.get("first_seen_at", "")).strip() or now_iso,
            "last_seen_at": str(row.get("last_seen_at", "")).strip() or now_iso,
            "last_return_type": str(row.get("last_return_type", row.get("Type of Return", ""))).strip(),
            "last_status": str(row.get("last_status", row.get("Status", ""))).strip(),
            "last_reason": str(row.get("last_reason", row.get("Return Reason", ""))).strip(),
            "last_detailed_reason": str(
                row.get("last_detailed_reason", row.get("Detailed Return Reason", ""))
            ).strip(),
            "updated_at": str(row.get("updated_at", "")).strip() or now_iso,
        }

    new_customers = 0
    updated_customers = 0
    for r in rows:
        if _norm_text(r.get("match_status")) != "matched":
            continue
        if not _is_risky_return_row(r):
            continue
        sub = _norm_suborder(r.get("Suborder Number", ""))
        ckey = _customer_key(r.get("Name", ""), r.get("Pincode", ""))
        key = ckey or (f"suborder:{sub}" if sub else "")
        if not key:
            continue
        points = _risk_event_score(r)
        if key not in profiles:
            profiles[key] = {
                "customer_key": ckey,
                "Name": str(r.get("Name", "")).strip(),
                "Pincode": str(r.get("Pincode", "")).strip(),
                "risk_score": 0.0,
                "risk_flag": "LOW",
                "hit_count": 0,
                "first_seen_at": now_iso,
                "last_seen_at": now_iso,
                "last_return_type": "",
                "last_status": "",
                "last_reason": "",
                "last_detailed_reason": "",
                "updated_at": now_iso,
            }
            suborders_by_key[key] = set()
            new_customers += 1
        else:
            updated_customers += 1
        profile = profiles[key]
        profile["risk_score"] = round(_safe_float(profile.get("risk_score")) + points, 2)
        profile["risk_flag"] = _risk_level(_safe_float(profile.get("risk_score")))
        profile["hit_count"] = _safe_int(profile.get("hit_count")) + 1
        profile["last_seen_at"] = now_iso
        profile["updated_at"] = now_iso
        profile["last_return_type"] = str(r.get("Type of Return", "")).strip()
        profile["last_status"] = str(r.get("Status", "")).strip()
        profile["last_reason"] = str(r.get("Return Reason", "")).strip()
        profile["last_detailed_reason"] = str(r.get("Detailed Return Reason", "")).strip()
        if sub:
            suborders_by_key.setdefault(key, set()).add(sub)

    out_rows: list[dict] = []
    risky_orders: set[str] = set()
    risky_customers: set[str] = set()
    for key, profile in sorted(
        profiles.items(),
        key=lambda kv: (_safe_float(kv[1].get("risk_score"), 0.0), _safe_int(kv[1].get("hit_count"), 0)),
        reverse=True,
    ):
        subs = suborders_by_key.get(key, set())
        score = _safe_float(profile.get("risk_score"), 0.0)
        ckey = str(profile.get("customer_key", "")).strip()
        metrics = blacklist_metrics.get(ckey, {}) if ckey else {}
        is_blacklisted_by_rate = bool(int(metrics.get("blacklist_by_return_rate", 0.0)))
        if is_blacklisted_by_rate:
            # Force blacklist activation when customer-return ratio satisfies:
            # (total_customer_returns / (orders - RTO)) * 100 >= 60.
            score = max(score, float(RISK_ACTIVATION_SCORE))
        level = _risk_level(score)
        if score >= RISK_ACTIVATION_SCORE and subs:
            risky_orders.update(subs)
        if score >= RISK_ACTIVATION_SCORE and ckey:
            risky_customers.add(ckey)
        out_rows.append(
            {
                "customer_key": ckey,
                "Name": str(profile.get("Name", "")).strip(),
                "Pincode": str(profile.get("Pincode", "")).strip(),
                "risk_score": f"{score:.2f}",
                "risk_flag": level,
                "hit_count": _safe_int(profile.get("hit_count"), 0),
                "risky_orders_count": len(subs),
                "risky_suborders": "|".join(sorted(subs)),
                "last_return_type": str(profile.get("last_return_type", "")).strip(),
                "last_status": str(profile.get("last_status", "")).strip(),
                "last_reason": str(profile.get("last_reason", "")).strip(),
                "last_detailed_reason": str(profile.get("last_detailed_reason", "")).strip(),
                "first_seen_at": str(profile.get("first_seen_at", "")).strip() or now_iso,
                "last_seen_at": str(profile.get("last_seen_at", "")).strip() or now_iso,
                "updated_at": str(profile.get("updated_at", "")).strip() or now_iso,
            }
        )

    with profile_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RISK_PROFILE_FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)
    if norm_platform:
        _refresh_legacy_risk_profile_union(safe_user_id)
    return {
        "risk_profile_path": str(profile_path),
        "risky_orders_count": len(risky_orders),
        "risky_customers_count": len(risky_customers),
        "risk_rows_count": len(out_rows),
        "risk_profiles_total": len(out_rows),
        "risk_profile_platform": norm_platform or "legacy",
        "new_risky_customers": int(new_customers),
        "existing_risky_customers_updated": int(updated_customers),
        "blacklisted_customers_by_return_rate": sum(
            1
            for row in out_rows
            if int(
                blacklist_metrics.get(str(row.get("customer_key", "")).strip(), {}).get(
                    "blacklist_by_return_rate", 0.0
                )
            )
        ),
        "return_rate_rule_threshold_pct": 60.0,
        "return_rate_rule_denominator": "orders_minus_rto",
        "return_rate_rule_safe_guard": "non_suspicious_when_orders_minus_rto_lte_0",
    }


def _load_user_risk_sets(user_id: int, platform: object | None = None) -> tuple[set[str], set[str]]:
    profiles = _load_risk_profiles(int(user_id), platform=platform)
    if not profiles:
        return set(), set()
    risky_orders: set[str] = set()
    risky_customers: set[str] = set()
    for r in profiles.values():
        score = _safe_float(r.get("risk_score"), 0.0)
        flag = _norm_text(r.get("risk_flag"))
        is_active = score >= RISK_ACTIVATION_SCORE or flag in {"high", "medium"}
        if not is_active:
            continue
        subs = _split_suborders(r.get("risky_suborders", ""))
        legacy_sub = _norm_suborder(r.get("Suborder Number", ""))
        if legacy_sub:
            subs.add(legacy_sub)
        risky_orders.update(subs)
        ckey = (str(r.get("customer_key", "")).strip() or _customer_key(r.get("Name", ""), r.get("Pincode", "")))
        if ckey:
            risky_customers.add(ckey)
    return risky_orders, risky_customers


def _build_today_risky_order_set(
    input_paths: list[str],
    *,
    user_id: int,
    platform: object | None = None,
) -> set[str]:
    risky_orders, risky_customers = _load_user_risk_sets(int(user_id), platform=platform)
    if not risky_orders and not risky_customers:
        return set()
    records, _, _ = extract_records_from_pdfs(input_paths, max_workers=2)
    risky_today: set[str] = set()
    for rec in records:
        oid = _norm_suborder(rec.get("Order_id", ""))
        ckey = _customer_key(rec.get("Name", ""), rec.get("Pincode", ""))
        if not oid:
            continue
        if oid in risky_orders or (ckey and ckey in risky_customers):
            risky_today.add(oid)
    return risky_today


def _master_row_to_purchase_entry(row: dict) -> dict:
    """Map a raw master OCR CSV row into a purchase-history entry.

    Only exposes a stable, UI-friendly subset of fields. Extra unknown columns
    (e.g. new OCR presets) are ignored so upstream schema drift cannot break
    the premium UI.
    """
    return {
        "suborder_id": _norm_suborder(row.get("Order_id", "") or row.get("Suborder Number", "")),
        "name": str(row.get("Name", "")).strip(),
        "address_1": str(row.get("Address_1", "")).strip(),
        "address_2": str(row.get("Address_2", "")).strip(),
        "address_3": str(row.get("Address_3", "")).strip(),
        "district": str(row.get("District", "")).strip(),
        "state": str(row.get("State", "")).strip(),
        "pincode": str(row.get("Pincode", "")).strip(),
        "sku": str(row.get("Sku", "") or row.get("SKU", "")).strip(),
        "payment_mode": str(row.get("Payment_Mode", "") or row.get("Payment Mode", "")).strip(),
        "courier_partner": str(row.get("Courier_Partner", "") or row.get("Courier", "")).strip(),
        "courier_trans_id": str(row.get("Courier_trans_id", "")).strip(),
        "order_date": str(
            row.get("Processed_At", "")
            or row.get("Order Date", "")
            or row.get("Order_Date", "")
        ).strip(),
    }


def _latest_return_analysis_rows_for_user(user_id: int) -> list[dict]:
    """Return all return-analysis rows from the user's most recent successful task.

    Returns an empty list when no return analysis has been run yet, or when the
    stored CSV is no longer available on disk. This helper intentionally
    swallows I/O errors so the history endpoint degrades gracefully.
    """
    try:
        with _db_connect() as conn:
            row = conn.execute(
                """
                SELECT result_path
                FROM processing_tasks
                WHERE user_id = ?
                  AND task_type = 'return_analysis'
                  AND status = 'success'
                  AND result_path <> ''
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
    except Exception:
        logger.exception("Could not load latest return analysis task for user %s", user_id)
        return []
    if not row:
        return []
    result_path = (row["result_path"] or "").strip()
    if not result_path:
        return []
    p = Path(result_path)
    if not p.exists():
        return []
    try:
        return _read_csv_rows(p)
    except Exception:
        logger.exception("Could not read return analysis CSV at %s", result_path)
        return []


def _return_row_to_entry(row: dict) -> dict:
    """Flatten a return-analysis row into a UI-friendly entry."""
    return {
        "suborder_id": _norm_suborder(row.get("Suborder Number", "")),
        "match_status": str(row.get("match_status", "")).strip(),
        "name": str(row.get("Name", "")).strip(),
        "pincode": str(row.get("Pincode", "")).strip(),
        "sku": str(row.get("Sku", "")).strip(),
        "awb_number": str(row.get("AWB Number", "")).strip(),
        "type_of_return": str(row.get("Type of Return", "")).strip(),
        "sub_type": str(row.get("Sub Type", "")).strip(),
        "status": str(row.get("Status", "")).strip(),
        "return_reason": str(row.get("Return Reason", "")).strip(),
        "detailed_return_reason": str(row.get("Detailed Return Reason", "")).strip(),
    }


def _build_loyal_customer_key_set(user_id: int) -> tuple[set[str], dict]:
    """Compute loyal customers from master orders + latest return-analysis rows.

    Rule:
      loyal if (total_orders - rto_count) > 2 and
      (customer_return_count / (total_orders - rto_count)) * 100 < 17.
    """
    master_rows = _read_master_rows_all_platforms(int(user_id))
    if not master_rows:
        return set(), {
            "evaluated_customers": 0,
            "loyal_customers": 0,
            "return_rows_used": 0,
            "threshold_percent": float(LOYAL_RETURN_RATE_THRESHOLD_PERCENT),
        }

    total_orders_by_customer: dict[str, int] = {}
    suborder_to_customer_key: dict[str, str] = {}
    for row in master_rows:
        name = row.get("Name", "")
        pincode = row.get("Pincode", "")
        customer_key = _customer_key(name, pincode)
        if not customer_key:
            continue
        total_orders_by_customer[customer_key] = total_orders_by_customer.get(customer_key, 0) + 1
        sub = _norm_suborder(row.get("Order_id", "") or row.get("Suborder Number", ""))
        if sub:
            suborder_to_customer_key[sub] = customer_key

    return_rows = _latest_return_analysis_rows_for_user(int(user_id))
    rto_count_by_customer: dict[str, int] = {}
    customer_return_count_by_customer: dict[str, int] = {}
    seen_return_rows: set[str] = set()
    used_rows = 0

    for row in return_rows:
        sub = _norm_suborder(row.get("Suborder Number", ""))
        row_key = _customer_key(row.get("Name", ""), row.get("Pincode", ""))
        customer_key = row_key or suborder_to_customer_key.get(sub, "")
        if not customer_key:
            continue
        awb = _norm_text(row.get("AWB Number", ""))
        row_fingerprint = "|".join(
            [
                customer_key,
                sub,
                awb,
                _norm_text(row.get("Type of Return", "")),
                _norm_text(row.get("Status", "")),
                _norm_text(row.get("Return Reason", "")),
            ]
        )
        if row_fingerprint in seen_return_rows:
            continue
        seen_return_rows.add(row_fingerprint)
        used_rows += 1
        if _is_rto_return_row(row):
            rto_count_by_customer[customer_key] = rto_count_by_customer.get(customer_key, 0) + 1
        else:
            customer_return_count_by_customer[customer_key] = customer_return_count_by_customer.get(customer_key, 0) + 1

    loyal_customer_keys: set[str] = set()
    for customer_key, total_orders in total_orders_by_customer.items():
        rto_count = int(rto_count_by_customer.get(customer_key, 0))
        non_rto_order_base = max(0, int(total_orders) - max(0, rto_count))
        if non_rto_order_base <= 2:
            continue
        customer_returns = int(customer_return_count_by_customer.get(customer_key, 0))
        return_ratio = (float(customer_returns) / float(non_rto_order_base)) * 100.0
        if return_ratio < float(LOYAL_RETURN_RATE_THRESHOLD_PERCENT):
            loyal_customer_keys.add(customer_key)

    return loyal_customer_keys, {
        "evaluated_customers": len(total_orders_by_customer),
        "loyal_customers": len(loyal_customer_keys),
        "return_rows_used": used_rows,
        "threshold_percent": float(LOYAL_RETURN_RATE_THRESHOLD_PERCENT),
    }


def _annotate_loyal_customer_labels(
    input_paths: list[str],
    *,
    loyal_customer_keys: set[str],
    output_dir: str,
    source_platform: str = "",
    force_mark_all: bool = False,
) -> tuple[list[str], int]:
    """Add `*` near customer name on loyal-customer label pages."""
    if not input_paths:
        return [], 0
    if not loyal_customer_keys and not force_mark_all:
        return list(input_paths), 0

    annotated_paths: list[str] = []
    marked_labels = 0
    # Requested visual: black filled star shown after customer name.
    # Draw vector shape (not text glyph) so it never renders as a square.
    star_color = (0.0, 0.0, 0.0)
    # Keep star close to printed-text scale on Flipkart labels.
    star_size = 8.0
    platform_norm = _normalize_ocr_platform(source_platform)
    is_flipkart_platform = platform_norm == "flipkart"
    flipkart_right_shift = 3.5 if is_flipkart_platform else 0.0

    def _find_flipkart_shipping_anchor(page: fitz.Page, text: str) -> fitz.Rect | None:
        # Flipkart labels carry this header above the name/address block.
        # Anchor star/skull placement to this phrase when available.
        if "shipping" not in (text or "").lower():
            return None
        candidates = [
            "Shipping/Customer address",
            "Shipping/Customer Address",
            "Shipping Customer address",
            "Shipping Customer Address",
            "Shipping Address",
        ]
        for phrase in candidates:
            try:
                hits = page.search_for(phrase)
            except Exception:
                hits = []
            if hits:
                return hits[0]
        return None

    def _star_baseline_after_anchor(anchor: fitz.Rect, page_rect: fitz.Rect) -> tuple[float, float]:
        x_after = float(anchor.x1) + 4.0
        y_baseline = float(anchor.y1) - 1.0
        # If right edge is too tight, drop to the next line under the anchor.
        if x_after + star_size > float(page_rect.x1) - 4.0:
            x_after = float(anchor.x0) + 4.0
            y_baseline = float(anchor.y1) + 12.0
        y_baseline = max(float(page_rect.y0) + 10.0, min(y_baseline, float(page_rect.y1) - 6.0))
        return x_after, y_baseline

    def _star_rect_after_anchor(anchor: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
        size = max(8.0, min(10.0, star_size))
        x_after = float(anchor.x1) + 4.0
        y_baseline = float(anchor.y1) - 1.0
        if x_after + size > float(page_rect.x1) - 4.0:
            x_after = float(anchor.x0) + 4.0
            y_baseline = float(anchor.y1) + 12.0
        x0 = x_after + 2.0 + flipkart_right_shift
        y0 = y_baseline - (size * 0.72)
        x0 = max(float(page_rect.x0) + 2.0, min(x0, float(page_rect.x1) - size - 2.0))
        y0 = max(float(page_rect.y0) + 2.0, min(y0, float(page_rect.y1) - size - 2.0))
        return fitz.Rect(x0, y0, x0 + size, y0 + size)

    def _star_rect_near_text(hit: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
        size = max(8.0, min(10.0, star_size))
        x0 = float(hit.x1) + 3.0 + flipkart_right_shift
        y0 = float(hit.y1) - (size * 0.85)
        if x0 + size > float(page_rect.x1) - 2.0:
            x0 = float(hit.x0) + 4.0
            y0 = float(hit.y1) + 10.0 - (size * 0.85)
        if x0 < float(page_rect.x0) + 2.0:
            x0 = float(page_rect.x0) + 2.0
        y0 = max(float(page_rect.y0) + 2.0, min(y0, float(page_rect.y1) - size - 2.0))
        return fitz.Rect(x0, y0, x0 + size, y0 + size)

    def _draw_filled_star(page: fitz.Page, x_after_name: float, y_center: float) -> None:
        import math

        outer = star_size * 0.5
        inner = outer * 0.45
        cx = float(x_after_name) + outer + 1.5
        cy = float(y_center)
        pts: list[fitz.Point] = []
        # 5-point star => 10 alternating outer/inner vertices.
        for i in range(10):
            angle = math.radians(-90 + (i * 36))
            radius = outer if i % 2 == 0 else inner
            pts.append(
                fitz.Point(
                    cx + (radius * math.cos(angle)),
                    cy + (radius * math.sin(angle)),
                )
            )
        shape = page.new_shape()
        shape.draw_polyline(pts + [pts[0]])
        shape.finish(color=star_color, fill=star_color, closePath=True)
        shape.commit()

    for idx, path in enumerate(input_paths):
        out_path = str(Path(output_dir) / f"loyal_marked_{idx}.pdf")
        with fitz.open(path) as doc:
            for page in doc:
                text = page.get_text("text")
                parsed = parse_required_fields(text or "")
                customer_key = _customer_key(parsed.get("Name", ""), parsed.get("Pincode", ""))
                if not force_mark_all and (not customer_key or customer_key not in loyal_customer_keys):
                    continue
                marked_labels += 1
                inserted = False
                name = str(parsed.get("Name", "")).strip()
                page_rect = page.rect
                flipkart_anchor = _find_flipkart_shipping_anchor(page, text) if is_flipkart_platform else None
                if flipkart_anchor is not None:
                    rect = _star_rect_after_anchor(flipkart_anchor, page_rect)
                    cx = (float(rect.x0) + float(rect.x1)) * 0.5
                    cy = (float(rect.y0) + float(rect.y1)) * 0.5
                    _draw_filled_star(page, cx - (star_size * 0.5) - 1.5, cy)
                    inserted = True
                if not inserted and name:
                    hits = page.search_for(name)
                    if hits:
                        hit = hits[0]
                        if is_flipkart_platform:
                            rect = _star_rect_near_text(hit, page_rect)
                            cx = (float(rect.x0) + float(rect.x1)) * 0.5
                            cy = (float(rect.y0) + float(rect.y1)) * 0.5
                            _draw_filled_star(page, cx - (star_size * 0.5) - 1.5, cy)
                        else:
                            text_center_y = (float(hit.y0) + float(hit.y1)) * 0.5
                            _draw_filled_star(page, hit.x1 + 2.0, text_center_y)
                        inserted = True
                if not inserted:
                    name_hits = page.search_for("Name")
                    if name_hits:
                        hit = name_hits[0]
                        if is_flipkart_platform:
                            rect = _star_rect_near_text(hit, page_rect)
                            cx = (float(rect.x0) + float(rect.x1)) * 0.5
                            cy = (float(rect.y0) + float(rect.y1)) * 0.5
                            _draw_filled_star(page, cx - (star_size * 0.5) - 1.5, cy)
                        else:
                            text_center_y = (float(hit.y0) + float(hit.y1)) * 0.5
                            _draw_filled_star(page, hit.x1 + 2.0, text_center_y)
                    else:
                        _draw_filled_star(page, 14, 72)
            doc.save(out_path)
        annotated_paths.append(out_path)

    return annotated_paths, marked_labels


def _load_suspicious_marker_image_bytes() -> bytes:
    """Read the configured skull PNG once. Returns b"" when the asset is missing
    or unreadable so callers can degrade to a vector fallback without crashing.

    Resolution order:
      1. ``SUSPICIOUS_MARKER_IMAGE_PATH`` env override (if set and readable).
      2. ``backend/assets/suspicious_skull.png`` shipped with the repo.
    Any I/O error is logged and swallowed - the marker step must never break
    the crop pipeline just because an icon is missing.
    """
    candidate_paths: list[Path] = []
    raw = (SUSPICIOUS_MARKER_IMAGE_PATH or "").strip()
    if raw:
        candidate_paths.append(Path(raw))
    if _DEFAULT_SUSPICIOUS_MARKER_IMAGE not in candidate_paths:
        candidate_paths.append(_DEFAULT_SUSPICIOUS_MARKER_IMAGE)
    for path in candidate_paths:
        try:
            if path.exists() and path.is_file():
                data = path.read_bytes()
                if data:
                    return data
        except Exception:
            logger.exception("Could not read suspicious marker image at %s", path)
    return b""


def _draw_suspicious_emoji_marker(page: "fitz.Page", rect: "fitz.Rect") -> None:
    """Draw a neutral-face emoji style marker inside the given rectangle."""
    cx = (rect.x0 + rect.x1) / 2.0
    cy = (rect.y0 + rect.y1) / 2.0
    radius = min(rect.width, rect.height) * 0.42
    if radius <= 0:
        return
    stroke = (0.0, 0.0, 0.0)
    fill = (1.0, 1.0, 1.0)
    shape = page.new_shape()
    # Outer face circle.
    shape.draw_circle(fitz.Point(cx, cy), radius)
    shape.finish(color=stroke, fill=fill, width=max(1.2, radius * 0.2))
    # Eyes.
    eye_r = max(0.6, radius * 0.16)
    eye_dx = radius * 0.36
    eye_y = cy - radius * 0.2
    shape.draw_circle(fitz.Point(cx - eye_dx, eye_y), eye_r)
    shape.draw_circle(fitz.Point(cx + eye_dx, eye_y), eye_r)
    shape.finish(color=stroke, fill=stroke)
    # Neutral mouth.
    mouth_half = radius * 0.34
    mouth_y = cy + radius * 0.28
    shape.draw_line(
        fitz.Point(cx - mouth_half, mouth_y),
        fitz.Point(cx + mouth_half, mouth_y),
    )
    shape.finish(color=stroke, width=max(1.1, radius * 0.14))
    shape.commit()


def _annotate_suspicious_customer_labels(
    input_paths: list[str],
    *,
    risky_order_ids: set[str],
    output_dir: str,
    source_platform: str = "",
    marker_image_bytes: bytes | None = None,
    force_mark_all: bool = False,
) -> tuple[list[str], int]:
    """Stamp a neutral-face marker on every suspicious-order label page.

    Mirrors `_annotate_loyal_customer_labels` so suspicious labels carry the
    same kind of visual marker as loyal ones (just a different glyph). The
    rewritten PDFs replace the originals in the pipeline so any downstream
    split/output PDF that contains the page also carries the marker.

    Robustness contract:
      * Always uses vector emoji drawing (no external image dependency).
        Never raises, never aborts the surrounding split.
      * Unreadable source page (text extraction failure) => skip silently.
      * Empty risky set or empty inputs => return the originals untouched.
    """
    if not input_paths:
        return [], 0
    if not risky_order_ids and not force_mark_all:
        return list(input_paths), 0

    annotated_paths: list[str] = []
    marked_labels = 0
    platform_norm = _normalize_ocr_platform(source_platform)
    is_flipkart_platform = platform_norm == "flipkart"
    flipkart_right_shift = 3.5 if is_flipkart_platform else 0.0
    # Keep marker near text scale; Meesho should match loyal-star sizing/placement.
    marker_size = 9.0 if is_flipkart_platform else 8.0

    def _find_flipkart_shipping_anchor(page: fitz.Page, text: str) -> fitz.Rect | None:
        if "shipping" not in (text or "").lower():
            return None
        candidates = [
            "Shipping/Customer address",
            "Shipping/Customer Address",
            "Shipping Customer address",
            "Shipping Customer Address",
            "Shipping Address",
        ]
        for phrase in candidates:
            try:
                hits = page.search_for(phrase)
            except Exception:
                hits = []
            if hits:
                return hits[0]
        return None

    def _marker_rect_after_anchor(anchor: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
        size = max(8.0, min(10.0, marker_size))
        x_after = float(anchor.x1) + 4.0
        y_baseline = float(anchor.y1) - 1.0
        # Match loyal-star placement fallback when right edge is tight.
        if x_after + size > float(page_rect.x1) - 4.0:
            x_after = float(anchor.x0) + 4.0
            y_baseline = float(anchor.y1) + 12.0
        x0 = x_after + 2.0 + flipkart_right_shift
        y0 = y_baseline - (size * 0.72)
        x0 = max(float(page_rect.x0) + 2.0, min(x0, float(page_rect.x1) - size - 2.0))
        y0 = max(float(page_rect.y0) + 2.0, min(y0, float(page_rect.y1) - size - 2.0))
        return fitz.Rect(x0, y0, x0 + size, y0 + size)

    def _marker_rect_near_text(hit: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
        # Align to the same baseline strategy used by loyal star near name.
        size = max(8.0, min(10.0, marker_size))
        x0 = float(hit.x1) + 3.0 + flipkart_right_shift
        y0 = float(hit.y1) - (size * 0.85)
        if x0 + size > float(page_rect.x1) - 2.0:
            x0 = float(hit.x0) + 4.0
            y0 = float(hit.y1) + 10.0 - (size * 0.85)
        if x0 < float(page_rect.x0) + 2.0:
            x0 = float(page_rect.x0) + 2.0
        y0 = max(float(page_rect.y0) + 2.0, min(y0, float(page_rect.y1) - size - 2.0))
        return fitz.Rect(x0, y0, x0 + size, y0 + size)

    def _marker_rect_like_loyal_star(hit: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
        # Mirrors loyal-star placement: right after name, centered on name line.
        # Match Meesho font scale by deriving marker size from detected text box.
        text_h = max(1.0, float(hit.y1) - float(hit.y0))
        size = max(6.0, min(10.5, text_h * 1.05))
        x0 = float(hit.x1) + 2.0
        y_center = (float(hit.y0) + float(hit.y1)) * 0.5
        y0 = y_center - (size * 0.5)
        if x0 + size > float(page_rect.x1) - 2.0:
            x0 = float(hit.x0) + 4.0
        x0 = max(float(page_rect.x0) + 2.0, min(x0, float(page_rect.x1) - size - 2.0))
        y0 = max(float(page_rect.y0) + 2.0, min(y0, float(page_rect.y1) - size - 2.0))
        return fitz.Rect(x0, y0, x0 + size, y0 + size)

    for idx, path in enumerate(input_paths):
        out_path = str(Path(output_dir) / f"suspicious_marked_{idx}.pdf")
        try:
            with fitz.open(path) as doc:
                for page in doc:
                    try:
                        text = page.get_text("text") or ""
                    except Exception:
                        text = ""
                    parsed = parse_required_fields(text or "")
                    name = str(parsed.get("Name", "")).strip()
                    sub = _norm_suborder(parsed.get("Order_id", "") or _extract_suborder_id(text) or "")
                    if not force_mark_all and (not sub or sub not in risky_order_ids):
                        continue
                    page_rect = page.rect
                    flipkart_anchor = _find_flipkart_shipping_anchor(page, text) if is_flipkart_platform else None
                    if flipkart_anchor is not None:
                        target_rect = _marker_rect_after_anchor(flipkart_anchor, page_rect)
                    elif name:
                        try:
                            name_hits = page.search_for(name)
                        except Exception:
                            name_hits = []
                        if name_hits:
                            if is_flipkart_platform:
                                target_rect = _marker_rect_near_text(name_hits[0], page_rect)
                            else:
                                target_rect = _marker_rect_like_loyal_star(name_hits[0], page_rect)
                        else:
                            # If exact name search misses due OCR noise, try label anchor.
                            try:
                                generic_hits = page.search_for("Name")
                            except Exception:
                                generic_hits = []
                            if generic_hits:
                                if is_flipkart_platform:
                                    target_rect = _marker_rect_near_text(generic_hits[0], page_rect)
                                else:
                                    target_rect = _marker_rect_like_loyal_star(generic_hits[0], page_rect)
                            else:
                                x1 = max(page_rect.x0, page_rect.x1 - 6.0)
                                y0 = page_rect.y0 + 6.0
                                x0 = max(page_rect.x0, x1 - marker_size)
                                y1 = min(page_rect.y1, y0 + marker_size)
                                target_rect = fitz.Rect(x0, y0, x1, y1)
                    else:
                        # Fallback when no reliable anchor is available.
                        x1 = max(page_rect.x0, page_rect.x1 - 6.0)
                        y0 = page_rect.y0 + 6.0
                        x0 = max(page_rect.x0, x1 - marker_size)
                        y1 = min(page_rect.y1, y0 + marker_size)
                        target_rect = fitz.Rect(x0, y0, x1, y1)
                    try:
                        _draw_suspicious_emoji_marker(page, target_rect)
                    except Exception:
                        logger.exception(
                            "Vector emoji marker failed on suspicious label %s p=%s",
                            path,
                            page.number,
                        )
                        continue
                    marked_labels += 1
                doc.save(out_path)
        except Exception:
            logger.exception("Suspicious-label annotation skipped for source %s", path)
            annotated_paths.append(path)
            continue
        annotated_paths.append(out_path)

    return annotated_paths, marked_labels


def get_customer_history_by_suborder(user_id: int, suborder_id: str) -> dict:
    """Build a customer history snapshot from a seed suborder ID.

    The flow:
      1. Look up the seed suborder in the user's master OCR CSV to identify the customer.
      2. Compute the normalized customer key (name + pincode). This key groups
         every purchase row that maps to
         the same physical customer.
      3. Walk the master CSV and collect all purchases for that customer.
      4. Load the user's risk profile CSV and surface the matching profile
         (if any) so returns that were already rolled into risk are visible.
      5. Enrich with line-level return rows from the user's latest successful
         return analysis task (when available) for more context.

    Raises ValueError when either the master CSV is missing for the user, or
    the suborder id is not found in that CSV. The caller is expected to map
    this to HTTP 404.
    """
    sub = _norm_suborder(suborder_id)
    if not sub:
        raise ValueError("Suborder ID is required.")

    rows = _read_master_rows_all_platforms(int(user_id))
    if not rows:
        legacy_path = _user_ocr_master_csv_path(int(user_id), None)
        if not legacy_path.exists() and not _user_ocr_master_csv_paths_all(int(user_id)):
            raise ValueError("Master OCR data not found. Upload label PDFs first.")
        raise ValueError("Master OCR data is empty. Upload label PDFs first.")

    matched_row: dict | None = None
    for row in rows:
        row_sub = _norm_suborder(row.get("Order_id", "") or row.get("Suborder Number", ""))
        if row_sub == sub:
            matched_row = row
            break
    if matched_row is None:
        raise ValueError("Suborder ID not found in your master OCR data.")

    matched_entry = _master_row_to_purchase_entry(matched_row)
    customer_key = _customer_key(matched_entry.get("name", ""), matched_entry.get("pincode", ""))
    strict_customer_key = _customer_key_strict(matched_entry.get("name", ""), matched_entry.get("pincode", ""))
    seed_pin = _norm_pincode(matched_entry.get("pincode", ""))
    seed_addr1 = _norm_address_for_match(matched_entry.get("address_1", ""))

    purchase_history: list[dict] = []
    seen_suborders: set[str] = set()
    for row in rows:
        entry = _master_row_to_purchase_entry(row)
        row_strict_key = _customer_key_strict(entry.get("name", ""), entry.get("pincode", ""))
        row_pin = _norm_pincode(entry.get("pincode", ""))
        row_addr1 = _norm_address_for_match(entry.get("address_1", ""))
        matches_customer = False
        # Primary identity: strict normalized name + pincode.
        if strict_customer_key and row_strict_key == strict_customer_key:
            matches_customer = True
        # Fallback (still bounded by pincode): tolerate light OCR variance in
        # name, or exact Address_1 match when present.
        elif seed_pin and row_pin == seed_pin:
            if _is_practical_name_match(matched_entry.get("name", ""), entry.get("name", "")):
                matches_customer = True
            elif seed_addr1 and row_addr1 and row_addr1 == seed_addr1:
                matches_customer = True
        # Last-resort fallback when pincode is unavailable: require both name
        # and Address_1 exact normalized match.
        elif not seed_pin and seed_addr1:
            if _is_practical_name_match(matched_entry.get("name", ""), entry.get("name", "")) and row_addr1 == seed_addr1:
                matches_customer = True
        if not matches_customer and entry.get("suborder_id") == matched_entry.get("suborder_id"):
            matches_customer = True
        if not matches_customer:
            continue
        sub_key = entry.get("suborder_id") or ""
        if sub_key and sub_key in seen_suborders:
            continue
        if sub_key:
            seen_suborders.add(sub_key)
        purchase_history.append(entry)

    # Keep the seed suborder at the top; everything else keeps master CSV order.
    purchase_history.sort(key=lambda e: 0 if e.get("suborder_id") == matched_entry.get("suborder_id") else 1)

    risk_profile = None
    risky_suborders_set: set[str] = set()
    if customer_key:
        profiles = _load_risk_profiles(int(user_id))
        profile = profiles.get(customer_key)
        if profile is not None:
            risky_suborders_set = {s for s in (profile.get("suborders") or set()) if s}
            risk_profile = {
                "customer_key": customer_key,
                "risk_score": float(f"{_safe_float(profile.get('risk_score'), 0.0):.2f}"),
                "risk_flag": _risk_level(_safe_float(profile.get("risk_score"), 0.0)),
                "hit_count": _safe_int(profile.get("hit_count"), 0),
                "risky_orders_count": len(risky_suborders_set),
                "risky_suborders": sorted(risky_suborders_set),
                "last_return_type": str(profile.get("last_return_type", "")).strip(),
                "last_status": str(profile.get("last_status", "")).strip(),
                "last_reason": str(profile.get("last_reason", "")).strip(),
                "last_detailed_reason": str(profile.get("last_detailed_reason", "")).strip(),
                "first_seen_at": str(profile.get("first_seen_at", "")).strip(),
                "last_seen_at": str(profile.get("last_seen_at", "")).strip(),
                "updated_at": str(profile.get("updated_at", "")).strip(),
            }

    # Pull detailed return rows for this customer from the most recent
    # return-analysis output, if one exists. Match by customer_key first, then
    # fall back to suborder membership.
    return_rows_all = _latest_return_analysis_rows_for_user(int(user_id))
    purchase_suborder_set = {e.get("suborder_id") for e in purchase_history if e.get("suborder_id")}
    return_entries: list[dict] = []
    return_seen: set[str] = set()
    for rr in return_rows_all:
        r_name = rr.get("Name", "")
        r_pin = rr.get("Pincode", "")
        r_key = _customer_key(r_name, r_pin)
        r_pin_norm = _norm_pincode(r_pin)
        r_sub = _norm_suborder(rr.get("Suborder Number", ""))
        matches = False
        if customer_key and r_key and r_key == customer_key:
            matches = True
        elif seed_pin and r_pin_norm == seed_pin and _is_practical_name_match(matched_entry.get("name", ""), r_name):
            matches = True
        elif r_sub and (r_sub in purchase_suborder_set or r_sub in risky_suborders_set):
            matches = True
        if not matches:
            continue
        entry = _return_row_to_entry(rr)
        # Deduplicate by (suborder_id, awb_number) so repeated rows collapse.
        dedup_key = f"{entry.get('suborder_id', '')}|{entry.get('awb_number', '')}"
        if dedup_key in return_seen:
            continue
        return_seen.add(dedup_key)
        return_entries.append(entry)

    # Summarize returns: count + risky count from markers we already use.
    risky_return_count = sum(1 for r in return_entries if _is_risky_return_row({
        "Type of Return": r.get("type_of_return", ""),
        "Sub Type": r.get("sub_type", ""),
        "Status": r.get("status", ""),
        "Return Reason": r.get("return_reason", ""),
        "Detailed Return Reason": r.get("detailed_return_reason", ""),
    }))
    return_summary = {
        "total_returns": len(return_entries),
        "risky_returns": risky_return_count,
        "has_return_analysis": bool(return_rows_all),
        "risky_suborders_from_profile": sorted(risky_suborders_set),
    }

    customer_info = {
        "name": matched_entry.get("name", ""),
        "pincode": matched_entry.get("pincode", ""),
        "district": matched_entry.get("district", ""),
        "state": matched_entry.get("state", ""),
        "customer_key": customer_key,
        "address_1": matched_entry.get("address_1", ""),
        "address_2": matched_entry.get("address_2", ""),
        "address_3": matched_entry.get("address_3", ""),
    }

    return {
        "customer": customer_info,
        "source_suborder": matched_entry,
        "purchase_history": purchase_history,
        "purchase_history_count": len(purchase_history),
        "return_history": return_entries,
        "return_summary": return_summary,
        "risk_profile": risk_profile,
    }


def _split_pdf_inputs_by_risk(
    input_paths: list[str],
    *,
    risky_order_ids: set[str],
    selected_pincodes: set[str],
    output_dir: str,
) -> tuple[list[str], list[str], list[str], int, int, int]:
    normal_paths: list[str] = []
    risky_paths: list[str] = []
    pincode_paths: list[str] = []
    total_pages = 0
    risky_pages = 0
    pincode_pages = 0
    for idx, path in enumerate(input_paths):
        with fitz.open(path) as src:
            normal_doc = fitz.open()
            risky_doc = fitz.open()
            pincode_doc = fitz.open()
            try:
                for page_idx in range(len(src)):
                    page = src[page_idx]
                    text = page.get_text("text")
                    # Prefer OCR-field parsing (same extraction basis as the
                    # Excel pipeline), then fall back to raw page-text regex.
                    parsed = parse_required_fields(text or "")
                    sub = _norm_suborder(parsed.get("Order_id", "") or _extract_suborder_id(text) or "")
                    parsed_pin = _norm_pincode(parsed.get("Pincode", ""))
                    page_pincodes = {parsed_pin} if len(parsed_pin) == 6 else set()
                    if not page_pincodes:
                        page_pincodes = _extract_pincodes_from_page_text(text)
                    total_pages += 1
                    if page_pincodes and page_pincodes.intersection(selected_pincodes):
                        pincode_doc.insert_pdf(src, from_page=page_idx, to_page=page_idx)
                        pincode_pages += 1
                    elif sub and sub in risky_order_ids:
                        risky_doc.insert_pdf(src, from_page=page_idx, to_page=page_idx)
                        risky_pages += 1
                    else:
                        normal_doc.insert_pdf(src, from_page=page_idx, to_page=page_idx)
                if len(normal_doc):
                    normal_path = str(Path(output_dir) / f"normal_source_{idx}.pdf")
                    normal_doc.save(normal_path)
                    normal_paths.append(normal_path)
                if len(risky_doc):
                    risky_path = str(Path(output_dir) / f"risky_source_{idx}.pdf")
                    risky_doc.save(risky_path)
                    risky_paths.append(risky_path)
                if len(pincode_doc):
                    pincode_path = str(Path(output_dir) / f"pincode_source_{idx}.pdf")
                    pincode_doc.save(pincode_path)
                    pincode_paths.append(pincode_path)
            finally:
                normal_doc.close()
                risky_doc.close()
                pincode_doc.close()
    return normal_paths, risky_paths, pincode_paths, total_pages, risky_pages, pincode_pages


def _build_customer_address_key(parsed: dict) -> str:
    """Build customer identity from OCR Name + Address_1 only.

    Uses the same parser as the OCR Excel pipeline so behaviour stays consistent
    across features. Empty key means the page lacked enough data to group by
    customer and should fall back to the normal pool.
    """
    import re as _re

    def _clean(value: object) -> str:
        text = "" if value is None else str(value)
        text = _re.sub(r"\s+", " ", text).strip().lower()
        return text

    name = _clean(parsed.get("Name", ""))
    addr1 = _clean(parsed.get("Address_1", ""))
    if not name and not addr1:
        return ""
    # Require both fields to avoid false grouping across different customers.
    if not name or not addr1:
        return ""
    return f"{name}||{addr1}"


def _split_pdf_inputs_by_multi_order_customer(
    input_paths: list[str],
    *,
    output_dir: str,
    file_prefix: str = "multi_order_source",
    rest_prefix: str = "multi_order_rest",
) -> tuple[list[str], list[str], int, int, int]:
    """Two-pass split that groups pages by Name + Address_1 and extracts groups of size >= 2.

    Returns (rest_paths, multi_paths, total_pages, multi_pages, multi_groups).

    - First pass collects per-page customer keys and group counts across ALL inputs.
    - Second pass writes pages whose key has count >= 2 into multi-order PDFs and
      everything else into the "rest" pool, preserving original order.
    """
    page_keys: list[list[str]] = []
    key_counts: dict[str, int] = {}
    for path in input_paths:
        per_pdf: list[str] = []
        try:
            with fitz.open(path) as src:
                for page_idx in range(len(src)):
                    text = src[page_idx].get_text("text") or ""
                    try:
                        parsed = parse_required_fields(text)
                    except Exception:
                        parsed = {}
                    key = _build_customer_address_key(parsed)
                    per_pdf.append(key)
                    if key:
                        key_counts[key] = key_counts.get(key, 0) + 1
        except Exception:
            logger.exception("Multi-order pre-scan failed for %s", path)
            per_pdf = []
        page_keys.append(per_pdf)

    multi_keys: set[str] = {k for k, c in key_counts.items() if c >= 2}

    multi_paths: list[str] = []
    rest_paths: list[str] = []
    total_pages = 0
    multi_pages = 0
    for idx, path in enumerate(input_paths):
        keys = page_keys[idx] if idx < len(page_keys) else []
        try:
            with fitz.open(path) as src:
                multi_doc = fitz.open()
                rest_doc = fitz.open()
                try:
                    for page_idx in range(len(src)):
                        total_pages += 1
                        key = keys[page_idx] if page_idx < len(keys) else ""
                        if key and key in multi_keys:
                            multi_doc.insert_pdf(src, from_page=page_idx, to_page=page_idx)
                            multi_pages += 1
                        else:
                            rest_doc.insert_pdf(src, from_page=page_idx, to_page=page_idx)
                    if len(multi_doc):
                        multi_path = str(Path(output_dir) / f"{file_prefix}_{idx}.pdf")
                        multi_doc.save(multi_path)
                        multi_paths.append(multi_path)
                    if len(rest_doc):
                        rest_path = str(Path(output_dir) / f"{rest_prefix}_{idx}.pdf")
                        rest_doc.save(rest_path)
                        rest_paths.append(rest_path)
                finally:
                    multi_doc.close()
                    rest_doc.close()
        except Exception:
            logger.exception("Multi-order split write failed for %s", path)
            # Fall back: keep this PDF intact in the rest pool.
            rest_paths.append(path)
    return rest_paths, multi_paths, total_pages, multi_pages, len(multi_keys)


def _count_courier_partners(
    input_paths: list[str],
    *,
    prefer_sold_by: bool = False,
) -> tuple[dict[str, int], int]:
    """Count partner/seller occurrences across every page of input PDFs.

    Returns ``(counts, total_pages_scanned)`` where ``counts`` maps a courier
    label (e.g. ``"Shadowfax"``, ``"Valmo"``, ``"E-Kart Logistics"``) to the
    number of label pages assigned to that courier. When ``prefer_sold_by`` is
    true (Flipkart flow), the bucket key prefers ``Sold_By`` and falls back to
    ``Courier_Partner`` so older labels still produce a meaningful split.
    Pages whose text could
    not be parsed - or whose courier could not be identified - fall under
    ``"Unknown"`` so totals always align with the scanned page count.

    Defensive by design: any per-page or per-file failure is absorbed and
    counted as ``Unknown`` rather than aborting the count, matching the
    behaviour of the surrounding crop pipeline. The shared OCR parser is
    reused so detection is consistent with the per-page Excel exports.
    """
    def _normalize_sold_by_label(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        # Flipkart Sold_By OCR may include address tail after comma/newline.
        # Keep only the storefront/company name segment.
        first_line = text.splitlines()[0].strip()
        for sep in (",", ";", "|"):
            if sep in first_line:
                first_line = first_line.split(sep, 1)[0].strip()
        return first_line

    counts: dict[str, int] = {}
    total = 0
    for pdf_path in input_paths or []:
        if not pdf_path:
            continue
        try:
            with fitz.open(pdf_path) as doc:
                page_count = len(doc)
                for idx in range(page_count):
                    total += 1
                    courier = ""
                    text = ""
                    try:
                        text = doc[idx].get_text("text") or ""
                    except Exception:
                        text = ""
                    if text:
                        try:
                            parsed = parse_required_fields(text) or {}
                            courier = (parsed.get("Courier_Partner") or "").strip()
                            sold_by = _normalize_sold_by_label(parsed.get("Sold_By"))
                        except Exception:
                            courier = ""
                            sold_by = ""
                    else:
                        sold_by = ""
                    bucket = (sold_by or courier or "Unknown") if prefer_sold_by else (courier or "Unknown")
                    counts[bucket] = counts.get(bucket, 0) + 1
        except Exception:
            logger.exception("Courier-partner counting failed for %s", pdf_path)
    if total > 0 and not counts:
        counts = {"Unknown": int(total)}
    return counts, total


def _build_split_row(parsed: dict, *, source_pdf: str, page_number: int) -> dict:
    """Project parser output into the canonical SPLIT_EXPORT_COLUMNS schema.

    All values are coerced to strings so the XLSX serialiser produces a
    deterministic, type-stable export. Missing/unknown fields become "".
    """
    row: dict[str, str | int] = {col: "" for col in SPLIT_EXPORT_COLUMNS}
    if isinstance(parsed, dict):
        for col in SPLIT_EXPORT_COLUMNS:
            if col in ("Source_PDF", "Page_Number"):
                continue
            value = parsed.get(col, "")
            row[col] = "" if value is None else str(value)
    row["Source_PDF"] = str(source_pdf or "")
    row["Page_Number"] = int(page_number) if page_number else 0
    return row


def _extract_split_rows_from_pdfs(
    pdf_paths: list[str],
    *,
    source_name_override: dict[str, str] | None = None,
) -> list[dict]:
    """Parse every page of each provided PDF into a SPLIT_EXPORT row.

    The shared OCR parser tolerates malformed labels and returns blanks for
    unknown fields, so this pass never raises on individual pages. PDF-level
    failures (corrupt file, unreadable text) are logged and skipped so a single
    bad source cannot abort the whole Excel export.

    ``source_name_override`` lets the caller supply a friendlier "Source_PDF"
    label (typically the original input file name) keyed by the actual PDF
    path. When unset, the basename of the PDF being read is used.
    """
    rows: list[dict] = []
    for pdf_path in pdf_paths or []:
        if not pdf_path:
            continue
        path_str = str(pdf_path)
        display_name = ""
        if source_name_override:
            display_name = source_name_override.get(path_str, "") or ""
        if not display_name:
            try:
                display_name = Path(path_str).name
            except Exception:
                display_name = path_str
        try:
            with fitz.open(path_str) as src:
                for page_idx in range(len(src)):
                    text = ""
                    try:
                        text = src[page_idx].get_text("text") or ""
                    except Exception:
                        text = ""
                    parsed: dict = {}
                    if text:
                        try:
                            parsed = parse_required_fields(text) or {}
                        except Exception:
                            parsed = {}
                    rows.append(
                        _build_split_row(
                            parsed,
                            source_pdf=display_name,
                            page_number=page_idx + 1,
                        )
                    )
        except Exception:
            logger.exception("Failed to parse split PDF for export: %s", path_str)
    return rows


def _write_split_rows_xlsx(
    rows: list[dict],
    output_path: str,
    *,
    category: str,
) -> None:
    """Persist ``rows`` to an XLSX file using the canonical export schema.

    Always writes the header row, even when ``rows`` is empty, so downstream
    tooling can rely on a stable contract regardless of how many pages matched
    the split criteria. Cell values are written as plain strings (or int for
    Page_Number) to avoid surprise type inference inside Excel/openpyxl.
    """
    from openpyxl import Workbook  # local import keeps cold-start cost flat

    wb = Workbook()
    ws = wb.active
    sheet_title = SPLIT_EXPORT_SHEET_TITLES.get(category, "Split")
    ws.title = (sheet_title or "Split")[:31] or "Split"
    ws.append(list(SPLIT_EXPORT_COLUMNS))
    for row in rows or []:
        ws.append([row.get(col, "") for col in SPLIT_EXPORT_COLUMNS])
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


def _build_split_source_name_map(
    *,
    input_paths: list[str],
    risky_input_paths: list[str],
    pincode_input_paths: list[str],
    multi_order_input_paths: list[str],
) -> dict[str, str]:
    """Map per-category split PDF paths back to the original input file name.

    The split helpers write temporary files named ``<prefix>_<index>.pdf``
    where ``<index>`` is the position in the ORIGINAL ``input_paths`` list
    (risky/pincode) or the post-risk-split normal pool (multi-order). This
    mapping lets the Excel export show the user's actual file name in the
    Source_PDF column instead of an opaque temp file name.
    """
    mapping: dict[str, str] = {}
    if not input_paths:
        return mapping
    original_names = [Path(p).name for p in input_paths]

    def _try_index_from_suffix(stem: str) -> int | None:
        try:
            return int(stem.rsplit("_", 1)[-1])
        except Exception:
            return None

    for split_path in list(risky_input_paths or []) + list(pincode_input_paths or []) + list(
        multi_order_input_paths or []
    ):
        try:
            stem = Path(split_path).stem
        except Exception:
            continue
        idx = _try_index_from_suffix(stem)
        if idx is None:
            continue
        if 0 <= idx < len(original_names):
            mapping[str(split_path)] = original_names[idx]
    return mapping


def init_task_queue_db() -> None:
    _ensure_ocr_master_dir()
    _ensure_risk_store_dir()
    with _db_connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processing_tasks (
                task_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                job_id INTEGER NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                summary_json TEXT NOT NULL DEFAULT '{}',
                result_path TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,
                worker_id TEXT NOT NULL DEFAULT '',
                lease_expires_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (job_id) REFERENCES crop_jobs(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON processing_tasks(status, created_at ASC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON processing_tasks(user_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_job_id ON processing_tasks(job_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_idempotency (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_type TEXT NOT NULL,
                idem_key TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                task_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, task_type, idem_key)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_idem_task_id ON task_idempotency(task_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_artifact_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                artifact_kind TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL DEFAULT '',
                content_bytes BYTEA NOT NULL,
                content_sha256 TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, artifact_kind, platform)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_analysis_snapshot_task ON analysis_artifact_snapshots(task_id, artifact_kind)"
        )


def _local_user_id_exists(conn: sqlite3.Connection, user_id: int) -> bool:
    try:
        row = conn.execute("SELECT 1 FROM users WHERE id = ?", (int(user_id),)).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False


def _local_crop_job_id_exists(conn: sqlite3.Connection, job_id: int) -> bool:
    try:
        row = conn.execute("SELECT 1 FROM crop_jobs WHERE id = ?", (int(job_id),)).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False


def _shadow_insert_local_task(
    *,
    task_id: str,
    user_id: int,
    job_id: int,
    task_type: str,
    payload: dict,
    now_iso: str,
) -> None:
    """Insert a 'shadow' processing_tasks row on the API even when QUEUE_BACKEND=redis.

    The Redis queue/state remains the source of truth for the worker. The local
    SQLite row exists so the API's history list query (which LEFT JOINs
    processing_tasks) can show task_status/finished_at and reveal the Download
    button. Best-effort: errors here must never break enqueue.
    """
    try:
        def _insert() -> None:
            with _db_connect() as conn:
                # Skip silently if FKs would not be satisfied (legacy tasks
                # whose user/crop_job rows live in a different SQLite file).
                if not _local_user_id_exists(conn, user_id):
                    return
                if not _local_crop_job_id_exists(conn, job_id):
                    return
                conn.execute(
                    """
                    INSERT OR IGNORE INTO processing_tasks (
                        task_id, user_id, job_id, task_type, status, progress, message, payload_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'queued', 1, 'Queued', ?, ?, ?)
                    """,
                    (
                        task_id,
                        int(user_id),
                        int(job_id),
                        task_type,
                        json.dumps(payload, ensure_ascii=True),
                        now_iso,
                        now_iso,
                    ),
                )

        _run_with_db_lock_retry("shadow task insert", _insert)
    except Exception:
        logger.exception("shadow_insert_local_task failed task_id=%s job_id=%s", task_id, job_id)


def _sync_local_task_from_redis(task: dict) -> None:
    """Mirror Redis task state into local SQLite (processing_tasks + crop_jobs).

    Each step runs independently and best-effort. The most important step for
    the UI is the crop_jobs mirror, because the history list falls back to
    j.status when no processing_tasks row exists. Failures here MUST NEVER
    break the read path.
    """
    if not task or not task.get("task_id"):
        return

    # Step 1 — mirror into processing_tasks (best-effort).
    try:
        _sync_processing_tasks_row(task)
    except Exception:
        logger.exception(
            "sync_processing_tasks_row failed task_id=%s",
            task.get("task_id"),
        )

    # Step 2 — independently mirror terminal state into crop_jobs so the
    # history UI flips to success/failed even if step 1 failed (e.g. legacy
    # task whose FK references no longer exist).
    terminal = (task.get("status") or "").lower() in {"success", "failed", "cancelled", "expired"}
    if terminal and task.get("task_type") in {"crop_meesho", "crop_flipkart"}:
        try:
            _mirror_terminal_state_to_crop_jobs(task)
        except Exception:
            logger.exception(
                "mirror_terminal_state_to_crop_jobs failed task_id=%s",
                task.get("task_id"),
            )


def _sync_processing_tasks_row(task: dict) -> None:
    summary = task.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}
    status = str(task.get("status") or "queued")
    progress = int(task.get("progress") or 0)
    message = str(task.get("message") or "")[:300]
    error = str(task.get("error") or "")[:1200]
    result_path = str(task.get("result_path") or "")
    summary_json = json.dumps(summary, ensure_ascii=True)
    worker_id = str(task.get("worker_id") or "")
    lease_expires_at = str(task.get("lease_expires_at") or "")
    started_at = str(task.get("started_at") or "")
    finished_at = str(task.get("finished_at") or "")
    updated_at = str(task.get("updated_at") or _utc_now_iso())
    task_id_str = str(task["task_id"])

    def _do_update() -> None:
        with _db_connect() as conn:
            cur = conn.execute(
                """
                UPDATE processing_tasks SET
                    status = ?,
                    progress = ?,
                    message = ?,
                    error = ?,
                    result_path = ?,
                    summary_json = ?,
                    worker_id = ?,
                    lease_expires_at = ?,
                    started_at = CASE WHEN ?='' THEN started_at ELSE ? END,
                    finished_at = CASE WHEN ?='' THEN finished_at ELSE ? END,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (
                    status,
                    progress,
                    message,
                    error,
                    result_path,
                    summary_json,
                    worker_id,
                    lease_expires_at,
                    started_at, started_at,
                    finished_at, finished_at,
                    updated_at,
                    task_id_str,
                ),
            )
            if (cur.rowcount or 0) > 0:
                return
            # Row didn't exist locally. Only insert if FKs will be satisfied;
            # otherwise skip silently — this is a legacy task whose owner/job
            # rows do not exist in this SQLite file.
            user_id = int(task.get("user_id") or 0)
            job_id = int(task.get("job_id") or 0)
            if user_id <= 0 or job_id <= 0:
                return
            if not _local_user_id_exists(conn, user_id) or not _local_crop_job_id_exists(conn, job_id):
                return
            payload = task.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            conn.execute(
                """
                INSERT OR IGNORE INTO processing_tasks (
                    task_id, user_id, job_id, task_type, status, progress, message, error,
                    payload_json, summary_json, result_path, worker_id, lease_expires_at,
                    created_at, updated_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id_str,
                    user_id,
                    job_id,
                    str(task.get("task_type") or ""),
                    status,
                    progress,
                    message,
                    error,
                    json.dumps(payload, ensure_ascii=True),
                    summary_json,
                    result_path,
                    worker_id,
                    lease_expires_at,
                    str(task.get("created_at") or _utc_now_iso()),
                    updated_at,
                    started_at,
                    finished_at,
                ),
            )

    _run_with_db_lock_retry("sync task from redis", _do_update)


def _mirror_terminal_state_to_crop_jobs(task: dict) -> None:
    """Mirror a terminal Redis task state into the local crop_jobs / metrics tables.

    Idempotent and safe to call repeatedly during polling. The worker on a
    remote VPS cannot update Railway's SQLite directly, so the API mirrors
    that state here when the UI polls.
    """
    job_id = int(task.get("job_id") or 0)
    if not job_id:
        return
    status = (task.get("status") or "").lower()
    finished_at = str(task.get("finished_at") or _utc_now_iso())
    error_message = str(task.get("error") or "")[:1200]
    summary = task.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}
    total_input_files = int(summary.get("total_input_files") or 0)
    total_input_pages = int(summary.get("total_input_pages") or 0)
    total_output_pages = int(summary.get("total_output_pages") or 0)
    total_output_labels = int(summary.get("total_output_labels") or 0)

    # Compute duration if started_at is available, otherwise approximate from
    # created_at to finished_at so the UI shows a sane non-zero duration.
    duration_ms = 0
    started_iso = str(task.get("started_at") or "")
    created_iso = str(task.get("created_at") or "")
    try:
        from datetime import datetime as _dt
        end_dt = _dt.fromisoformat(finished_at.replace("Z", "+00:00")) if finished_at else None
        start_dt = None
        if started_iso:
            start_dt = _dt.fromisoformat(started_iso.replace("Z", "+00:00"))
        elif created_iso:
            start_dt = _dt.fromisoformat(created_iso.replace("Z", "+00:00"))
        if end_dt and start_dt:
            duration_ms = max(0, int((end_dt - start_dt).total_seconds() * 1000))
    except Exception:
        duration_ms = 0

    def _update_job_status() -> None:
        with _db_connect() as conn:
            row = conn.execute(
                "SELECT status, started_at FROM crop_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                return
            current = (row["status"] or "").lower()
            # Always allow mirroring success even if currently 'processing'.
            if current == "success" and status != "success":
                return
            if current != status:
                conn.execute(
                    """
                    UPDATE crop_jobs SET
                        status = ?,
                        finished_at = CASE WHEN ?='' THEN finished_at ELSE ? END,
                        error_message = ?,
                        duration_ms = CASE WHEN ?>0 AND duration_ms=0 THEN ? ELSE duration_ms END,
                        started_at = CASE WHEN started_at='' AND ?<>'' THEN ? ELSE started_at END
                    WHERE id = ?
                    """,
                    (
                        status,
                        finished_at, finished_at,
                        error_message,
                        duration_ms, duration_ms,
                        started_iso or created_iso, started_iso or created_iso,
                        job_id,
                    ),
                )
            # Backfill metrics if they're still empty so UI shows pages/labels.
            if status == "success" and (total_input_pages or total_output_labels):
                metric_row = conn.execute(
                    "SELECT total_input_pages, total_output_labels FROM crop_job_metrics WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if metric_row and not (
                    int(metric_row["total_input_pages"] or 0) or int(metric_row["total_output_labels"] or 0)
                ):
                    conn.execute(
                        """
                        UPDATE crop_job_metrics SET
                            total_input_files = CASE WHEN ?>0 THEN ? ELSE total_input_files END,
                            total_input_pages = CASE WHEN ?>0 THEN ? ELSE total_input_pages END,
                            total_output_pages = CASE WHEN ?>0 THEN ? ELSE total_output_pages END,
                            total_output_labels = CASE WHEN ?>0 THEN ? ELSE total_output_labels END
                        WHERE job_id = ?
                        """,
                        (
                            total_input_files, total_input_files,
                            total_input_pages, total_input_pages,
                            total_output_pages, total_output_pages,
                            total_output_labels, total_output_labels,
                            job_id,
                        ),
                    )

    _run_with_db_lock_retry("mirror terminal status to crop_jobs", _update_job_status)


def _enqueue_internal_redis_task(*, user_id: int, job_id: int, task_type: str, payload: dict, message: str = "Queued") -> str:
    if not _use_redis_queue():
        raise RuntimeError("Internal fan-out tasks require Redis queue backend")
    if task_type not in INTERNAL_TASK_TYPES:
        raise ValueError(f"Unsupported internal task type: {task_type}")
    task_id = uuid.uuid4().hex
    now_iso = _utc_now_iso()
    task = {
        "task_id": task_id,
        "user_id": int(user_id),
        "job_id": int(job_id),
        "task_type": task_type,
        "status": "queued",
        "progress": 1,
        "message": message,
        "error": "",
        "payload": payload,
        "summary": {},
        "result_path": "",
        "attempts": 0,
        "worker_id": "",
        "lease_expires_at": "",
        "created_at": now_iso,
        "updated_at": now_iso,
        "started_at": "",
        "finished_at": "",
    }
    client = _redis_client()
    client.set(_redis_task_key(task_id), json.dumps(task, ensure_ascii=True))
    client.rpush(_redis_queue_name(), task_id)
    return task_id


def enqueue_task(*, user_id: int, job_id: int, task_type: str, payload: dict) -> str:
    if task_type not in TASK_TYPES:
        raise ValueError(f"Unsupported task type: {task_type}")
    task_id = uuid.uuid4().hex
    now_iso = _utc_now_iso()
    if _use_redis_queue():
        task = {
            "task_id": task_id,
            "user_id": int(user_id),
            "job_id": int(job_id),
            "task_type": task_type,
            "status": "queued",
            "progress": 1,
            "message": "Queued",
            "error": "",
            "payload": payload,
            "summary": {},
            "result_path": "",
            "attempts": 0,
            "worker_id": "",
            "lease_expires_at": "",
            "created_at": now_iso,
            "updated_at": now_iso,
            "started_at": "",
            "finished_at": "",
        }
        client = _redis_client()
        client.set(_redis_task_key(task_id), json.dumps(task, ensure_ascii=True))
        client.zadd(_redis_user_tasks_key(int(user_id)), {task_id: time.time()})
        client.rpush(_redis_queue_name(), task_id)
        _shadow_insert_local_task(
            task_id=task_id,
            user_id=user_id,
            job_id=job_id,
            task_type=task_type,
            payload=payload,
            now_iso=now_iso,
        )
        start_embedded_worker()
        return task_id

    def _insert() -> None:
        with _db_connect() as conn:
            conn.execute(
                """
                INSERT INTO processing_tasks (
                    task_id, user_id, job_id, task_type, status, progress, message, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', 1, 'Queued', ?, ?, ?)
                """,
                (task_id, int(user_id), int(job_id), task_type, json.dumps(payload, ensure_ascii=True), now_iso, now_iso),
            )

    _run_with_db_lock_retry("enqueue task insert", _insert)
    start_embedded_worker()
    return task_id


def _payload_hash(payload: dict) -> str:
    raw = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_premium_crop_options_enabled(options: dict | None) -> bool:
    if not isinstance(options, dict):
        return False
    separate_pincodes = str(options.get("separate_pincodes") or options.get("separatePincodes") or "").strip()
    return bool(
        _option_bool(options.get("detect_suspicious"))
        or _option_bool(options.get("detect_suspicious_enabled"))
        or _option_bool(options.get("mark_suspicious_preview"))
        or _option_bool(options.get("markSuspiciousPreview"))
        or _option_bool(options.get("suspicious_preview_enabled"))
        or _option_bool(options.get("separate_multi_order_by_customer"))
        or _option_bool(options.get("separateMultiOrderByCustomer"))
        or _option_bool(options.get("multi_order_split_enabled"))
        or _option_bool(options.get("mark_loyal_customer"))
        or _option_bool(options.get("markLoyalCustomer"))
        or _option_bool(options.get("loyal_customer_enabled"))
        or _option_bool(options.get("mark_loyal_customer_preview"))
        or _option_bool(options.get("markLoyalCustomerPreview"))
        or _option_bool(options.get("loyal_preview_enabled"))
        or _option_bool(options.get("pincode_split_enabled"))
        or separate_pincodes
    )


def _apply_premium_crop_billing(task: dict, summary: dict, options: dict) -> dict:
    billing = {
        "premium_billing_attempted": False,
        "premium_billing_applied": False,
        "premium_billing_error": "",
        "premium_coin_cost_per_label": int(PREMIUM_CROP_COIN_COST_PER_LABEL),
        "premium_coins_charged": 0,
    }
    if not _is_premium_crop_options_enabled({**options, **summary}):
        return billing

    label_count = max(
        0,
        int(
            summary.get("total_output_labels")
            or summary.get("total_labels")
            or summary.get("total_input_pages")
            or summary.get("courier_count_total")
            or 0
        ),
    )
    coins = label_count * int(PREMIUM_CROP_COIN_COST_PER_LABEL)
    billing.update(
        {
            "premium_billing_attempted": True,
            "premium_labels_billed": label_count,
            "premium_coins_charged": coins,
        }
    )
    if coins <= 0:
        return billing

    try:
        result = spend_wallet_coins(
            user_id=int(task.get("user_id") or 0),
            amount=coins,
            note=(
                f"{str(task.get('task_type') or 'Crop')} premium crop "
                f"({label_count} label{'s' if label_count != 1 else ''})"
            ),
        )
        if not (isinstance(result, dict) and result.get("ok")):
            billing["premium_billing_error"] = "Insufficient wallet balance."
            return billing
        billing["premium_billing_applied"] = True
    except Exception as exc:
        logger.exception(
            "Premium crop billing failed task_id=%s user_id=%s coins=%s",
            task.get("task_id"),
            task.get("user_id"),
            coins,
        )
        billing["premium_billing_error"] = str(exc)
    return billing


def lookup_idempotent_task_id(*, user_id: int, task_type: str, idem_key: str) -> str:
    """Return an existing task_id bound to this idempotency key, or "" if none."""
    clean_key = (idem_key or "").strip()
    if not clean_key:
        return ""
    if _use_redis_queue():
        client = _redis_client()
        idem_key_redis = _redis_idem_key(int(user_id), task_type, clean_key)
        existing = client.get(idem_key_redis)
        if not existing:
            return ""
        try:
            parsed = json.loads(existing)
        except Exception:
            return ""
        return str(parsed.get("task_id") or "")
    with _db_connect() as conn:
        row = conn.execute(
            """
            SELECT task_id
            FROM task_idempotency
            WHERE user_id = ? AND task_type = ? AND idem_key = ?
            """,
            (int(user_id), task_type, clean_key),
        ).fetchone()
        if not row:
            return ""
        return str(row["task_id"] or "")


def get_or_create_idempotent_task(
    *,
    user_id: int,
    job_id: int,
    task_type: str,
    idem_key: str,
    payload: dict,
    reuse_on_idem_key_match: bool = False,
) -> tuple[str, bool]:
    clean_key = (idem_key or "").strip()
    if not clean_key:
        return enqueue_task(user_id=user_id, job_id=job_id, task_type=task_type, payload=payload), True
    ph = _payload_hash(payload)
    now_iso = _utc_now_iso()
    task_id = uuid.uuid4().hex
    resolved_task_id = ""
    created = False

    if _use_redis_queue():
        client = _redis_client()
        idem_key_redis = _redis_idem_key(int(user_id), task_type, clean_key)
        existing = client.get(idem_key_redis)
        if existing:
            try:
                parsed = json.loads(existing)
            except Exception:
                parsed = {}
            stored_ph = parsed.get("payload_hash") or ""
            if not reuse_on_idem_key_match and stored_ph != ph:
                raise ValueError("Idempotency key already used with different request payload.")
            return str(parsed.get("task_id") or ""), False
        idem_record = json.dumps({"task_id": task_id, "payload_hash": ph}, ensure_ascii=True)
        if not client.set(idem_key_redis, idem_record, nx=True, ex=86400):
            existing_late = client.get(idem_key_redis)
            if not existing_late:
                time.sleep(0.05)
                existing_late = client.get(idem_key_redis)
            if existing_late:
                try:
                    parsed = json.loads(existing_late)
                except Exception:
                    parsed = {}
                stored_ph = parsed.get("payload_hash") or ""
                if not reuse_on_idem_key_match and stored_ph != ph:
                    raise ValueError("Idempotency key already used with different request payload.")
                return str(parsed.get("task_id") or ""), False
            logger.error(
                "Idempotency reservation lost race without record user_id=%s task_type=%s",
                int(user_id),
                task_type,
            )
            raise RuntimeError("Idempotency reservation failed; retry the request.")
        try:
            task = {
                "task_id": task_id,
                "user_id": int(user_id),
                "job_id": int(job_id),
                "task_type": task_type,
                "status": "queued",
                "progress": 1,
                "message": "Queued",
                "error": "",
                "payload": payload,
                "summary": {},
                "result_path": "",
                "attempts": 0,
                "worker_id": "",
                "lease_expires_at": "",
                "created_at": now_iso,
                "updated_at": now_iso,
                "started_at": "",
                "finished_at": "",
            }
            client.set(_redis_task_key(task_id), json.dumps(task, ensure_ascii=True))
            client.zadd(_redis_user_tasks_key(int(user_id)), {task_id: time.time()})
            client.rpush(_redis_queue_name(), task_id)
            _shadow_insert_local_task(
                task_id=task_id,
                user_id=user_id,
                job_id=job_id,
                task_type=task_type,
                payload=payload,
                now_iso=now_iso,
            )
            start_embedded_worker()
            return task_id, True
        except Exception:
            try:
                client.delete(idem_key_redis)
            except Exception:
                logger.exception("Failed to release idempotency key after enqueue error")
            raise

    def _upsert_idempotent() -> None:
        nonlocal resolved_task_id, created
        with _db_connect() as conn:
            row = conn.execute(
                """
                SELECT task_id, payload_hash
                FROM task_idempotency
                WHERE user_id = ? AND task_type = ? AND idem_key = ?
                """,
                (int(user_id), task_type, clean_key),
            ).fetchone()
            if row:
                existing_task_id = row["task_id"]
                if (row["payload_hash"] or "") != ph and not reuse_on_idem_key_match:
                    raise ValueError("Idempotency key already used with different request payload.")
                resolved_task_id = existing_task_id
                created = False
                return
            conn.execute(
                """
                INSERT INTO processing_tasks (
                    task_id, user_id, job_id, task_type, status, progress, message, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', 1, 'Queued', ?, ?, ?)
                """,
                (task_id, int(user_id), int(job_id), task_type, json.dumps(payload, ensure_ascii=True), now_iso, now_iso),
            )
            try:
                conn.execute(
                    """
                    INSERT INTO task_idempotency (user_id, task_type, idem_key, payload_hash, task_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (int(user_id), task_type, clean_key, ph, task_id, now_iso),
                )
            except sqlite3.IntegrityError:
                conn.execute("DELETE FROM processing_tasks WHERE task_id = ?", (task_id,))
                row2 = conn.execute(
                    """
                    SELECT task_id, payload_hash
                    FROM task_idempotency
                    WHERE user_id = ? AND task_type = ? AND idem_key = ?
                    """,
                    (int(user_id), task_type, clean_key),
                ).fetchone()
                if not row2:
                    raise
                if (row2["payload_hash"] or "") != ph and not reuse_on_idem_key_match:
                    raise ValueError("Idempotency key already used with different request payload.")
                resolved_task_id = row2["task_id"]
                created = False
                return
            resolved_task_id = task_id
            created = True

    _run_with_db_lock_retry("idempotent task upsert", _upsert_idempotent)
    if created:
        start_embedded_worker()
    return resolved_task_id, created


def get_task_for_user(task_id: str, user_id: int) -> dict | None:
    if _use_redis_queue():
        task = _redis_get_task(task_id)
        if not task or int(task.get("user_id") or 0) != int(user_id):
            return None
        # Mirror current Redis state into the local processing_tasks/crop_jobs
        # rows so the API's history list (read from SQLite) reflects the
        # actual worker outcome and reveals the Download button.
        _sync_local_task_from_redis(task)
        return task

    with _db_connect() as conn:
        row = conn.execute(
            """
            SELECT task_id, user_id, job_id, task_type, status, progress, message, error, payload_json,
                   summary_json, result_path, attempts, worker_id, lease_expires_at, created_at, updated_at,
                   started_at, finished_at
            FROM processing_tasks
            WHERE task_id = ? AND user_id = ?
            """,
            (task_id, int(user_id)),
        ).fetchone()
    if not row:
        return None
    payload = {}
    summary = {}
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except Exception:
        payload = {}
    try:
        summary = json.loads(row["summary_json"] or "{}")
    except Exception:
        summary = {}
    return {
        "task_id": row["task_id"],
        "user_id": int(row["user_id"]),
        "job_id": int(row["job_id"]),
        "task_type": row["task_type"],
        "status": row["status"],
        "progress": int(row["progress"] or 0),
        "message": row["message"] or "",
        "error": row["error"] or "",
        "payload": payload,
        "summary": summary,
        "result_path": row["result_path"] or "",
        "attempts": int(row["attempts"] or 0),
        "worker_id": row["worker_id"] or "",
        "lease_expires_at": row["lease_expires_at"] or "",
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
        "started_at": row["started_at"] or "",
        "finished_at": row["finished_at"] or "",
    }


def _task_to_public(task: dict) -> dict:
    return {
        "task_id": task["task_id"],
        "job_id": task["job_id"],
        "task_type": task["task_type"],
        "status": task["status"],
        "progress": task["progress"],
        "message": task["message"],
        "error": task["error"],
        "summary": task.get("summary") or {},
        "has_output": bool(task.get("result_path")),
        "created_at": task.get("created_at") or "",
        "updated_at": task.get("updated_at") or "",
    }


def get_task_public_for_user(task_id: str, user_id: int) -> dict | None:
    task = get_task_for_user(task_id, user_id)
    if not task:
        return None
    return _task_to_public(task)


def sync_recent_user_tasks_from_redis(user_id: int, *, limit: int = 50) -> int:
    """Best-effort reconciliation used by history endpoints in Redis mode.

    The history list is served from local SQLite, while remote workers update
    Redis. Polling `/api/tasks/{id}` already mirrors a single task, but users can
    land directly on history after a remote worker finishes. Syncing recent
    public crop tasks here keeps the Download button tied to Redis truth.
    """
    if not redis_ocr_master_lookup_enabled():
        return 0
    try:
        client = _redis_client()
        task_ids = client.zrevrange(_redis_user_tasks_key(int(user_id)), 0, max(0, int(limit) - 1))
    except Exception:
        logger.exception("sync_recent_user_tasks_from_redis failed to list user tasks user_id=%s", user_id)
        return 0

    synced = 0
    for task_id in task_ids or []:
        try:
            task = _redis_get_task(str(task_id))
            if not task:
                continue
            if task.get("task_type") not in {"crop_meesho", "crop_flipkart", "ocr_csv", "ocr_excel"}:
                continue
            _sync_local_task_from_redis(task)
            synced += 1
        except Exception:
            logger.exception("sync_recent_user_tasks_from_redis failed task_id=%s", task_id)
    return synced


def _update_task(task_id: str, **fields) -> None:
    if not fields:
        return
    if _use_redis_queue():
        task = _redis_get_task(task_id)
        if not task:
            return
        for key, value in fields.items():
            if key == "payload_json":
                try:
                    task["payload"] = json.loads(value or "{}")
                except Exception:
                    task["payload"] = {}
            elif key == "summary_json":
                try:
                    task["summary"] = json.loads(value or "{}")
                except Exception:
                    task["summary"] = {}
            else:
                task[key] = value
        task["updated_at"] = _utc_now_iso()
        _redis_put_task(task)
        return

    set_sql = []
    params: list[object] = []
    for k, v in fields.items():
        set_sql.append(f"{k} = ?")
        params.append(v)
    set_sql.append("updated_at = ?")
    params.append(_utc_now_iso())
    params.append(task_id)
    def _do_update() -> None:
        with _db_connect() as conn:
            conn.execute(f"UPDATE processing_tasks SET {', '.join(set_sql)} WHERE task_id = ?", tuple(params))

    _run_with_db_lock_retry("task status update", _do_update)


def _fetch_task_by_id(task_id: str) -> dict | None:
    if _use_redis_queue():
        return _redis_get_task(task_id)

    with _db_connect() as conn:
        row = conn.execute(
            """
            SELECT task_id, user_id, job_id, task_type, status, progress, message, error,
                   payload_json, summary_json, result_path, attempts, worker_id, lease_expires_at,
                   created_at, updated_at, started_at, finished_at
            FROM processing_tasks
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
    if not row:
        return None
    payload = {}
    summary = {}
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except Exception:
        payload = {}
    try:
        summary = json.loads(row["summary_json"] or "{}")
    except Exception:
        summary = {}
    return {
        "task_id": row["task_id"],
        "user_id": int(row["user_id"]),
        "job_id": int(row["job_id"]),
        "task_type": row["task_type"],
        "status": row["status"],
        "progress": int(row["progress"] or 0),
        "message": row["message"] or "",
        "error": row["error"] or "",
        "payload": payload,
        "summary": summary,
        "result_path": row["result_path"] or "",
        "attempts": int(row["attempts"] or 0),
        "worker_id": row["worker_id"] or "",
        "lease_expires_at": row["lease_expires_at"] or "",
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
        "started_at": row["started_at"] or "",
        "finished_at": row["finished_at"] or "",
    }


def _claim_next_task(worker_id: str, lease_seconds: int = 180) -> dict | None:
    now_iso = _utc_now_iso()
    lease_expires = (_utc_now() + timedelta(seconds=max(30, lease_seconds))).isoformat()
    task_id: str = ""

    if _use_redis_queue():
        _maybe_requeue_expired_redis_tasks()
        client = _redis_client()
        queue_name = _redis_queue_name()
        max_claim_attempts = max(1, int(os.getenv("REDIS_CLAIM_ATTEMPTS", "6") or 6))
        for _attempt in range(max_claim_attempts):
            popped = client.blpop(queue_name, timeout=1)
            if not popped:
                return None
            _queue, task_id = popped
            task = _redis_get_task(str(task_id))
            if not task:
                # Queue entry points to missing task metadata; skip safely.
                continue
            status = str(task.get("status") or "").strip().lower()
            claimable = status == "queued" or (status == "running" and _is_past_iso(str(task.get("lease_expires_at") or "")))
            if not claimable:
                # Non-claimable status (already done/active elsewhere) should not block claim loop.
                continue
            task["status"] = "running"
            task["worker_id"] = worker_id
            task["lease_expires_at"] = lease_expires
            task["started_at"] = task.get("started_at") or now_iso
            task["attempts"] = int(task.get("attempts") or 0) + 1
            task["message"] = "Running"
            task["progress"] = max(2, int(task.get("progress") or 0))
            task["updated_at"] = now_iso
            _redis_put_task(task)
            return task
        return None

    def _do_claim() -> bool:
        nonlocal task_id
        with _db_connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT task_id
                FROM processing_tasks
                WHERE status = 'queued'
                   OR (status = 'running' AND lease_expires_at <> '' AND lease_expires_at < ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now_iso,),
            ).fetchone()
            if not row:
                conn.rollback()
                return False
            task_id = row["task_id"]
            conn.execute(
                """
                UPDATE processing_tasks
                SET status = 'running',
                    worker_id = ?,
                    lease_expires_at = ?,
                    started_at = CASE WHEN started_at = '' THEN ? ELSE started_at END,
                    attempts = attempts + 1,
                    message = 'Running',
                    progress = CASE WHEN progress < 2 THEN 2 ELSE progress END,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (worker_id, lease_expires, now_iso, now_iso, task_id),
            )
            conn.commit()
            return True

    try:
        claimed = _run_with_db_lock_retry("task claim", _do_claim)
    except sqlite3.OperationalError as exc:
        if _is_db_locked_error(exc):
            logger.warning("Task claim skipped because DB lock persisted")
            return None
        raise
    if not claimed:
        return None
    return _fetch_task_by_id(task_id)


def _set_failed(task: dict, message: str) -> None:
    _progress_update_cache.pop(task["task_id"], None)
    _update_task(
        task["task_id"],
        status="failed",
        progress=100,
        message="Failed",
        error=(message or "Task failed")[:1200],
        finished_at=_utc_now_iso(),
        lease_expires_at="",
    )


def _set_success(task: dict, *, result_path: str, summary: dict) -> None:
    _progress_update_cache.pop(task["task_id"], None)
    _update_task(
        task["task_id"],
        status="success",
        progress=100,
        message="Completed",
        error="",
        result_path=result_path,
        summary_json=json.dumps(summary or {}, ensure_ascii=True),
        finished_at=_utc_now_iso(),
        lease_expires_at="",
    )
    try:
        _snapshot_task_analysis_artifacts(task, result_path=result_path, summary=summary or {})
    except Exception:
        logger.exception("analysis artifact snapshot failed task_id=%s", task.get("task_id"))


def _set_progress(task_id: str, progress: int, message: str, *, force: bool = False) -> None:
    target_progress = max(0, min(99, int(progress)))
    target_message = (message or "")[:300]
    now_ts = time.time()
    cached = _progress_update_cache.get(task_id) or {}
    last_progress = int(cached.get("progress") or 0)
    last_message = str(cached.get("message") or "")
    last_ts = float(cached.get("ts") or 0.0)
    persist = force
    if not persist:
        if target_progress >= 99 and target_progress >= last_progress:
            persist = True
        elif target_progress >= (last_progress + PROGRESS_PERSIST_MIN_STEP):
            persist = True
        elif target_message and target_message != last_message:
            persist = True
        elif (now_ts - last_ts) >= PROGRESS_PERSIST_MIN_INTERVAL_SEC:
            persist = True
    if persist:
        _update_task(task_id, progress=target_progress, message=target_message)
        _progress_update_cache[task_id] = {
            "progress": target_progress,
            "message": target_message,
            "ts": now_ts,
        }
        return
    # Keep an in-memory watermark so repeated tiny progress ticks do not flood storage.
    _progress_update_cache[task_id] = {
        "progress": max(last_progress, target_progress),
        "message": target_message or last_message,
        "ts": last_ts,
    }


def _safe_pdf_page_count_from_path(path: str) -> int:
    try:
        with fitz.open(path) as doc:
            return int(doc.page_count)
    except Exception:
        return 0


def _cleanup_input_files(payload: dict) -> None:
    for p in payload.get("input_paths") or []:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass


def _crop_turbo_mode_enabled(options: dict | None = None) -> bool:
    # Hard-disabled: turbo mode can skip user-selected processing options.
    # Keep helper for backward compatibility, but always force full processing.
    return False


def _fanout_skip_reason(task: dict) -> str:
    if not _distributed_pdf_fanout_enabled():
        return "disabled"
    if not (_use_redis_queue() and _use_s3_storage()):
        return "requires_redis_and_s3"
    if task.get("task_type") not in {"crop_meesho", "crop_flipkart"}:
        return "unsupported_task_type"
    payload = task.get("payload") or {}
    if payload.get("fanout_parent") or payload.get("fanout_started"):
        return "already_started"
    total_pages = int(payload.get("total_input_pages") or 0)
    if total_pages < PDF_FANOUT_MIN_PAGES:
        return "below_min_pages"
    if (payload.get("layout") or "label_printer").strip() != "label_printer":
        return "unsupported_layout"
    options = payload.get("options") or {}
    premium_split_keys = {
        "detect_suspicious",
        "separate_pincodes",
        "separate_multi_order_by_customer",
        "mark_loyal_customer",
        "mark_loyal_customer_preview",
        "mark_suspicious_preview",
    }
    premium_enabled = any(
        _option_bool(options.get(key)) if key != "separate_pincodes" else bool(str(options.get(key) or "").strip())
        for key in premium_split_keys
    )
    # Premium split mode must stay on the single-job path because fan-out
    # finalization currently merges chunk outputs into a single PDF artifact.
    # Keeping premium jobs out of fan-out guarantees ZIP output semantics.
    if premium_enabled:
        return "premium_split_mode"
    if not payload.get("input_paths"):
        return "missing_inputs"
    return ""


def _desired_fanout_chunks(total_pages: int) -> int:
    if PDF_FANOUT_CHUNK_MAX_PAGES <= 0:
        return PDF_FANOUT_CHUNKS
    by_size = max(1, (int(total_pages) + PDF_FANOUT_CHUNK_MAX_PAGES - 1) // PDF_FANOUT_CHUNK_MAX_PAGES)
    return max(2, min(PDF_FANOUT_CHUNKS, by_size))


def _maybe_start_crop_fanout(task: dict) -> bool:
    reason = _fanout_skip_reason(task)
    if reason:
        if reason not in {"disabled", "below_min_pages", "unsupported_task_type"}:
            logger.info("PDF fan-out skipped task_id=%s reason=%s", task.get("task_id"), reason)
        return False

    payload = task.get("payload") or {}
    task_id = str(task.get("task_id") or "")
    user_id = int(task.get("user_id") or 0)
    job_id = int(task.get("job_id") or 0)
    task_type = str(task.get("task_type") or "")
    total_pages = int(payload.get("total_input_pages") or 0)
    output_dir = payload.get("output_dir") or tempfile.mkdtemp(prefix=f"fanout_parent_{task_id}_")
    chunk_count = _desired_fanout_chunks(total_pages)

    _set_progress(task_id, 5, f"Splitting PDF for {chunk_count} workers")
    chunks = _split_pdf_inputs_to_chunks(
        payload.get("input_paths") or [],
        str(Path(output_dir) / "fanout_chunks"),
        desired_chunks=chunk_count,
    )
    if len(chunks) <= 1:
        return False

    store = _s3_store()
    child_ids: list[str] = []
    child_task_type = "crop_meesho_chunk" if task_type == "crop_meesho" else "crop_flipkart_chunk"
    for chunk in chunks:
        chunk_index = int(chunk["chunk_index"])
        chunk_key = _s3_key("tasks", task_id, "fanout", f"chunk-{chunk_index:03d}.pdf")
        store.upload_file(chunk_key, str(chunk["path"]))
        child_payload = {
            **payload,
            "input_paths": [],
            "input_s3_keys": [{"key": chunk_key, "file_name": f"chunk-{chunk_index:03d}.pdf"}],
            "input_files": [
                {
                    "file_name": f"chunk-{chunk_index:03d}.pdf",
                    "input_pages": int(chunk["page_count"]),
                }
            ],
            "total_input_files": 1,
            "total_input_pages": int(chunk["page_count"]),
            "fanout_parent_task_id": task_id,
            "fanout_chunk_index": chunk_index,
            "fanout_chunk_start_page": int(chunk["start_page"]),
            "options": {
                **(payload.get("options") or {}),
                "__fanout_child": True,
            },
        }
        child_id = _enqueue_internal_redis_task(
            user_id=user_id,
            job_id=job_id,
            task_type=child_task_type,
            payload=child_payload,
            message=f"Queued chunk {chunk_index + 1}/{len(chunks)}",
        )
        child_ids.append(child_id)

    finalizer_payload = {
        "parent_task_id": task_id,
        "child_task_ids": child_ids,
        "task_type": task_type,
        "sort_by": payload.get("sort_by") or "",
        "layout": payload.get("layout") or "",
        "options": payload.get("options") or {},
        "input_files": payload.get("input_files") or [],
        "total_input_files": int(payload.get("total_input_files") or 0),
        "total_input_pages": total_pages,
        "output_dir": tempfile.mkdtemp(prefix=f"fanout_finalize_{task_id}_"),
    }
    finalizer_id = _enqueue_internal_redis_task(
        user_id=user_id,
        job_id=job_id,
        task_type="crop_finalize",
        payload=finalizer_payload,
        message="Waiting for PDF chunks",
    )
    payload["fanout_started"] = True
    payload["fanout_child_task_ids"] = child_ids
    payload["fanout_finalizer_task_id"] = finalizer_id
    payload["fanout_chunk_count"] = len(child_ids)
    _update_task(
        task_id,
        payload_json=json.dumps(payload, ensure_ascii=True),
        progress=8,
        message=f"Split into {len(child_ids)} worker chunks",
    )
    logger.info(
        "PDF fan-out started parent_task_id=%s children=%s finalizer=%s pages=%s",
        task_id,
        len(child_ids),
        finalizer_id,
        total_pages,
    )
    return True


def _process_ocr_task(task: dict) -> tuple[str, dict]:
    payload = task.get("payload") or {}
    output_dir = payload.get("output_dir") or ""
    if not output_dir:
        raise ValueError("OCR task missing output directory")
    user_id = int(task["user_id"])
    options = payload.get("options") or {}
    # source_platform is propagated from the auto-OCR enqueue path. Manually
    # uploaded OCR tasks have no platform and write to the legacy union file.
    source_platform = _normalize_ocr_platform(options.get("source_platform"))
    platform_master_path = _user_ocr_master_csv_path(user_id, source_platform or None)
    legacy_master_path = _user_ocr_master_csv_path(user_id, None)
    output_path = str(platform_master_path)
    max_workers = int(payload.get("max_workers") or 0)
    job_id = int(task["job_id"])
    input_file_rows = payload.get("input_files") or []
    total_input_files = int(payload.get("total_input_files") or len(input_file_rows))
    total_input_pages = int(payload.get("total_input_pages") or 0)
    start_perf = time.perf_counter()
    logger.info(
        "OCR task started task_id=%s files=%s pages=%s workers=%s",
        task.get("task_id"),
        total_input_files,
        total_input_pages,
        max_workers,
    )

    def _progress(stats: dict) -> None:
        processed_files = int(stats.get("processed_files") or 0)
        total_files = max(1, int(stats.get("total_files") or 1))
        pages = int(stats.get("total_pages") or 0)
        pct = int((pages / max(1, total_input_pages)) * 90) if total_input_pages > 0 else int((processed_files / total_files) * 90)
        _set_progress(task["task_id"], max(3, min(95, pct)), f"Processed {processed_files}/{total_files} file(s)")

    records, report_rows, summary = extract_records_from_pdfs(
        payload.get("input_paths") or [],
        max_workers=max_workers,
        progress_callback=_progress,
    )
    processed_at = _utc_now().strftime("%d-%m-%Y")
    dated_records: list[dict] = []
    for rec in records:
        row = dict(rec or {})
        row["Processed_At"] = processed_at
        dated_records.append(row)
    deduped_new_records, dedup_removed_new = deduplicate_records(dated_records)
    existing_records = _read_csv_rows(platform_master_path)
    existing_count = len(existing_records)
    merged_records, replaced_existing_records = _merge_ocr_master_records(existing_records, deduped_new_records)
    dedup_removed_merged = replaced_existing_records
    # Keep a stable master schema so future daily merges are reliable.
    csv_bytes = build_csv_bytes(
        merged_records,
        column_preset="standard_v1",
        custom_columns="",
    )
    Path(output_path).write_bytes(csv_bytes)
    merged_count = len(merged_records)
    appended_rows = max(0, merged_count - existing_count)

    # Refresh the legacy union file as the union of every known per-platform
    # master plus any pre-existing legacy rows. This keeps consumers that
    # were not platform-aware (return analysis, manual-risk lookup, customer
    # history, loyal-customer evaluation) working without regression.
    legacy_existing = _read_csv_rows(legacy_master_path) if (
        source_platform and legacy_master_path.exists() and legacy_master_path != platform_master_path
    ) else []
    union_rows: list[dict] = list(legacy_existing)
    for platform in SUPPORTED_OCR_PLATFORMS:
        platform_path = _user_ocr_master_csv_path(user_id, platform)
        if platform_path == platform_master_path:
            union_rows.extend(merged_records)
        elif platform_path.exists():
            try:
                union_rows.extend(_read_csv_rows(platform_path))
            except Exception:
                logger.exception("Failed to read platform master CSV at %s", platform_path)
    if not source_platform:
        # Manual OCR runs already wrote to the legacy file via merged_records;
        # avoid double-writing.
        union_rows = merged_records
    union_dedup, _ = _merge_ocr_master_records([], union_rows)
    union_bytes = build_csv_bytes(
        union_dedup,
        column_preset="standard_v1",
        custom_columns="",
    )
    Path(legacy_master_path).write_bytes(union_bytes)

    duration_ms = int((time.perf_counter() - start_perf) * 1000)
    _safe_mark_crop_job_success(
        task,
        duration_ms=duration_ms,
        total_input_files=total_input_files,
        total_input_pages=total_input_pages,
        total_output_pages=1,
        total_output_labels=merged_count,
        input_files=input_file_rows,
        sort_by="standard_v1",
        layout="csv",
        options={
            **options,
            "mode": "worker_queue",
            "workers": max_workers,
            "stored_on_server_only": True,
            "deduplicated_new_records": len(deduped_new_records),
            "duplicates_removed_new_batch": int(dedup_removed_new),
            "duplicates_removed_while_merging": int(dedup_removed_merged),
            "replaced_existing_records": int(replaced_existing_records),
            "existing_records_before_merge": existing_count,
            "appended_records": appended_rows,
            "master_records_total": merged_count,
            "master_platform": source_platform or "legacy",
            "union_records_total": len(union_dedup),
            **summary,
        },
    )
    summary_with_dedupe = dict(summary)
    summary_with_dedupe["deduplicated_new_records"] = len(deduped_new_records)
    summary_with_dedupe["duplicates_removed_new_batch"] = int(dedup_removed_new)
    summary_with_dedupe["duplicates_removed_while_merging"] = int(dedup_removed_merged)
    summary_with_dedupe["existing_records_before_merge"] = existing_count
    summary_with_dedupe["appended_records"] = appended_rows
    summary_with_dedupe["master_records_total"] = merged_count
    summary_with_dedupe["master_platform"] = source_platform or "legacy"
    summary_with_dedupe["union_records_total"] = len(union_dedup)
    logger.info(
        "OCR task finished task_id=%s total_ms=%s extracted=%s merged_total=%s",
        task.get("task_id"),
        int((time.perf_counter() - start_perf) * 1000),
        int(len(deduped_new_records)),
        int(merged_count),
    )
    return output_path, summary_with_dedupe


def _process_crop_task(task: dict) -> tuple[str, dict]:
    payload = task.get("payload") or {}
    task_type = task.get("task_type") or ""
    source_platform = (
        "meesho"
        if task_type in {"crop_meesho", "crop_meesho_chunk"}
        else ("flipkart" if task_type in {"crop_flipkart", "crop_flipkart_chunk"} else "")
    )
    task_id = str(task.get("task_id") or "")
    output_dir = payload.get("output_dir") or ""
    if not output_dir:
        raise ValueError("Crop task missing output directory")
    output_path = str(Path(output_dir) / "cropped-output.pdf")
    input_paths = payload.get("input_paths") or []
    input_file_rows = payload.get("input_files") or []
    total_input_files = int(payload.get("total_input_files") or len(input_file_rows))
    total_input_pages = int(payload.get("total_input_pages") or 0)
    options = payload.get("options") or {}
    turbo_mode = _crop_turbo_mode_enabled(options)
    effective_options = dict(options)
    sort_by = _normalize_sort_by(payload.get("sort_by"))
    layout = (payload.get("layout") or "").strip()
    start_perf = time.perf_counter()
    stage_perf = start_perf
    logger.info(
        "Crop task started task_id=%s type=%s files=%s pages=%s suspicious=%s pincode_split=%s multi_order=%s turbo=%s",
        task.get("task_id"),
        task_type,
        total_input_files,
        total_input_pages,
        _option_bool(effective_options.get("detect_suspicious")),
        bool(_parse_pincode_list(effective_options.get("separate_pincodes", ""))),
        _option_bool(effective_options.get("separate_multi_order_by_customer")),
        turbo_mode,
    )
    last_progress = 3

    def _crop_progress(service_pct: int, message: str) -> None:
        nonlocal last_progress
        clamped = max(0, min(100, int(service_pct)))
        mapped = 5 + int((clamped / 100) * 91)  # map service 0..100 -> task 5..96
        final_pct = max(last_progress, min(99, mapped))
        msg = (message or "Processing labels").strip()
        if final_pct > last_progress or msg:
            _set_progress(task_id, final_pct, msg)
        last_progress = max(last_progress, final_pct)

    selected_pincodes = _parse_pincode_list(effective_options.get("separate_pincodes", ""))
    detect_suspicious = _option_bool(effective_options.get("detect_suspicious"))
    pick_list_enabled_requested = _option_bool(effective_options.get("pick_list_enabled"))
    pick_list_after_orders = int(effective_options.get("pick_list_after_orders") or 0)
    if pick_list_enabled_requested and pick_list_after_orders <= 0:
        # Toggle-only mode: enabled checkbox means append one pick-list section
        # after all labels, without requiring a numeric interval from the client.
        pick_list_after_orders = 1
    # These advanced splits rely on the shared OCR parser (`parse_required_fields`)
    # which handles both Meesho and Flipkart layouts, so they are safe for both
    # task types. Gate only on the option being enabled + a known crop task.
    multi_order_enabled = _option_bool(effective_options.get("separate_multi_order_by_customer")) and task_type in {
        "crop_meesho",
        "crop_flipkart",
    }
    loyal_customer_enabled = _option_bool(effective_options.get("mark_loyal_customer")) and task_type in {
        "crop_meesho",
        "crop_flipkart",
    }
    # Preview-only premium toggles must still activate premium split/ZIP mode
    # even when the paired detection switch is off.
    loyal_preview_enabled = _option_bool(effective_options.get("mark_loyal_customer_preview")) and task_type in {
        "crop_meesho",
        "crop_flipkart",
    }
    suspicious_preview_enabled = _option_bool(effective_options.get("mark_suspicious_preview")) and task_type in {
        "crop_meesho",
        "crop_flipkart",
    }
    premium_checks_enabled = bool(
        detect_suspicious
        or selected_pincodes
        or multi_order_enabled
        or loyal_customer_enabled
        or loyal_preview_enabled
        or suspicious_preview_enabled
    )
    risk_eval_error = ""
    loyal_eval_error = ""
    courier_count_error = ""
    courier_counts: dict[str, int] = {}
    courier_count_total = 0
    risky_today_ids: set[str] = set()
    loyal_customer_keys: set[str] = set()
    manual_customers_total = 0
    manual_suborders_total = 0
    if premium_checks_enabled:
        try:
            manual_customers_total, manual_suborders_total = _manual_risk_stats(
                int(task["user_id"]),
                platform=source_platform or None,
            )
        except Exception:
            logger.exception("Manual risk stats load failed for task %s", task.get("task_id"))
    if detect_suspicious:
        try:
            risky_today_ids = _build_today_risky_order_set(
                input_paths,
                user_id=int(task["user_id"]),
                platform=source_platform or None,
            )
        except Exception as exc:
            logger.exception("Risk evaluation failed for task %s", task.get("task_id"))
            risk_eval_error = str(exc)
    if loyal_customer_enabled:
        try:
            loyal_customer_keys, loyal_stats = _build_loyal_customer_key_set(int(task["user_id"]))
        except Exception as exc:
            logger.exception("Loyal-customer evaluation failed for task %s", task.get("task_id"))
            loyal_eval_error = str(exc)
            loyal_stats = {
                "evaluated_customers": 0,
                "loyal_customers": 0,
                "return_rows_used": 0,
                "threshold_percent": float(LOYAL_RETURN_RATE_THRESHOLD_PERCENT),
            }

    # Compute courier-wise label counts BEFORE annotation rewrites the input
    # PDFs. Annotation does not add or remove pages, but reading from the
    # originals avoids any chance that a stamp overlay confuses text
    # extraction. Failure here must not break the crop task: counts simply
    # stay empty and a small error string is surfaced in the summary so the
    # UI can render a "Courier breakdown unavailable" hint instead of crashing.
    if input_paths:
        try:
            courier_counts, courier_count_total = _count_courier_partners(
                list(input_paths),
                prefer_sold_by=(source_platform == "flipkart"),
            )
        except Exception as exc:
            logger.exception(
                "Courier-partner counting failed for task %s", task.get("task_id")
            )
            courier_counts = {}
            courier_count_total = 0
            courier_count_error = str(exc)

    risk_split_summary = {
        "premium_checks_enabled": premium_checks_enabled,
        "risk_split_enabled": bool(risky_today_ids),
        "detect_suspicious_enabled": bool(detect_suspicious),
        "risk_eval_error": risk_eval_error,
        "risky_orders_matched": len(risky_today_ids),
        "risky_pages": 0,
        "pincode_split_enabled": bool(selected_pincodes),
        "selected_pincodes_count": len(selected_pincodes),
        "selected_pincode_pages": 0,
        "normal_pages": total_input_pages,
        "manual_high_risk_customers_total": int(manual_customers_total),
        "manual_high_risk_suborders_total": int(manual_suborders_total),
        # Multi-order split metrics (Meesho-only).
        "multi_order_split_enabled": bool(multi_order_enabled),
        "multi_order_groups": 0,
        "multi_order_matched_labels": 0,
        "multi_order_pages": 0,
        "multi_order_normal_pages": total_input_pages,
        # Loyal-customer star marking metrics (Meesho-only).
        "loyal_customer_enabled": bool(loyal_customer_enabled),
        "loyal_preview_enabled": bool(loyal_preview_enabled),
        "loyal_eval_error": loyal_eval_error,
        "loyal_customers_matched": int(len(loyal_customer_keys)),
        "loyal_customers_evaluated": int(loyal_stats.get("evaluated_customers", 0)) if loyal_customer_enabled else 0,
        "loyal_return_rows_used": int(loyal_stats.get("return_rows_used", 0)) if loyal_customer_enabled else 0,
        "loyal_threshold_percent": float(LOYAL_RETURN_RATE_THRESHOLD_PERCENT),
        "loyal_labels_marked": 0,
        # Suspicious-customer skull marking metrics. Mirrors the loyal flow so
        # downstream consumers can rely on a stable shape regardless of which
        # marker fired during this run.
        "suspicious_marker_enabled": bool(detect_suspicious),
        "suspicious_preview_enabled": bool(suspicious_preview_enabled),
        "suspicious_marker_image_path": str(SUSPICIOUS_MARKER_IMAGE_PATH or ""),
        "suspicious_marker_image_present": bool(_DEFAULT_SUSPICIOUS_MARKER_IMAGE.exists()),
        "suspicious_labels_marked": 0,
        "turbo_mode_enabled": bool(turbo_mode),
        # Premium print extras mirrored in task summary so downstream billing can
        # decide from completed-task metadata without relying on client state.
        "print_datetime_enabled": bool(effective_options.get("print_datetime")),
        "multi_order_bottom_enabled": bool(effective_options.get("multi_order_bottom")),
        "custom_message_enabled": bool((effective_options.get("custom_message") or "").strip()),
        "pick_list_after_orders": int(max(0, pick_list_after_orders)),
        # Courier-wise label counts so clients can verify totals with the
        # delivery personnel after labels are processed. Always present so
        # the frontend can rely on a stable shape even when no courier was
        # detected (in which case all pages fall under "Unknown").
        "courier_counts": dict(courier_counts),
        "courier_count_total": int(courier_count_total),
        "courier_count_error": courier_count_error,
    }

    if loyal_customer_enabled and input_paths and (loyal_customer_keys or loyal_preview_enabled):
        _set_progress(task["task_id"], 33, "Marking loyal customers")
        try:
            input_paths, loyal_labels_marked = _annotate_loyal_customer_labels(
                input_paths,
                loyal_customer_keys=loyal_customer_keys,
                output_dir=output_dir,
                source_platform=source_platform or "",
                force_mark_all=bool(loyal_preview_enabled),
            )
            risk_split_summary["loyal_labels_marked"] = int(loyal_labels_marked)
        except Exception as exc:
            logger.exception("Loyal-customer label annotation failed for task %s", task.get("task_id"))
            risk_split_summary["loyal_eval_error"] = str(exc)
    logger.info(
        "Crop task stage done task_id=%s stage=pre_annotations elapsed_ms=%s",
        task.get("task_id"),
        int((time.perf_counter() - stage_perf) * 1000),
    )
    stage_perf = time.perf_counter()

    # Stamp a skull on every suspicious-order page BEFORE the risk split so
    # the marker travels with the page into `suspicious-labels.pdf`. We
    # deliberately reuse the same "rewrite the input PDFs" pattern used for
    # loyal-customer stars to keep downstream code paths unchanged.
    if detect_suspicious and input_paths and (risky_today_ids or suspicious_preview_enabled):
        _set_progress(task["task_id"], 36, "Marking suspicious customers")
        try:
            input_paths, suspicious_labels_marked = _annotate_suspicious_customer_labels(
                input_paths,
                risky_order_ids=risky_today_ids,
                output_dir=output_dir,
                source_platform=source_platform or "",
                force_mark_all=bool(suspicious_preview_enabled),
            )
            risk_split_summary["suspicious_labels_marked"] = int(suspicious_labels_marked)
        except Exception as exc:
            logger.exception(
                "Suspicious-label skull annotation failed for task %s", task.get("task_id")
            )
            risk_split_summary["suspicious_marker_error"] = str(exc)

    risk_pincode_active = bool(risky_today_ids or selected_pincodes)
    normal_input_paths: list[str] = list(input_paths)
    risky_input_paths: list[str] = []
    pincode_input_paths: list[str] = []
    multi_order_input_paths: list[str] = []
    risky_pages = 0
    pincode_pages = 0
    multi_order_pages = 0
    multi_order_groups = 0

    if risk_pincode_active:
        _set_progress(task["task_id"], 40, "Classifying risky labels")
        (
            normal_input_paths,
            risky_input_paths,
            pincode_input_paths,
            split_total_pages,
            risky_pages,
            pincode_pages,
        ) = _split_pdf_inputs_by_risk(
            input_paths,
            risky_order_ids=risky_today_ids,
            selected_pincodes=selected_pincodes,
            output_dir=output_dir,
        )
        normal_pages_after_risk = max(0, split_total_pages - risky_pages - pincode_pages)
        risk_split_summary["risky_pages"] = risky_pages
        risk_split_summary["selected_pincode_pages"] = pincode_pages
        risk_split_summary["normal_pages"] = normal_pages_after_risk
        risk_split_summary["risk_split_enabled"] = bool(risky_pages)
        risk_split_summary["multi_order_normal_pages"] = normal_pages_after_risk
    logger.info(
        "Crop task stage done task_id=%s stage=risk_split elapsed_ms=%s",
        task.get("task_id"),
        int((time.perf_counter() - stage_perf) * 1000),
    )
    stage_perf = time.perf_counter()

    if multi_order_enabled and normal_input_paths:
        _set_progress(task["task_id"], 47, "Detecting multi-order customers")
        (
            normal_input_paths,
            multi_order_input_paths,
            _multi_total_pages,
            multi_order_pages,
            multi_order_groups,
        ) = _split_pdf_inputs_by_multi_order_customer(
            normal_input_paths,
            output_dir=output_dir,
        )
        risk_split_summary["multi_order_pages"] = multi_order_pages
        risk_split_summary["multi_order_matched_labels"] = multi_order_pages
        risk_split_summary["multi_order_groups"] = multi_order_groups
        risk_split_summary["multi_order_normal_pages"] = max(
            0, int(risk_split_summary.get("multi_order_normal_pages", total_input_pages)) - multi_order_pages
        )
        # Keep the canonical normal_pages metric aligned with post-split pages
        # so total_output_pages accounting stays correct.
        risk_split_summary["normal_pages"] = int(risk_split_summary.get("multi_order_normal_pages", 0))
    logger.info(
        "Crop task stage done task_id=%s stage=multi_order_split elapsed_ms=%s",
        task.get("task_id"),
        int((time.perf_counter() - stage_perf) * 1000),
    )
    stage_perf = time.perf_counter()

    # Premium requests should have deterministic ZIP output even when a split
    # category has zero matches; users still need the premium summary/artifacts.
    split_active = bool(premium_checks_enabled)

    normal_output_path = str(Path(output_dir) / "non-suspicious-labels.pdf")
    risky_output_path = str(Path(output_dir) / "suspicious-labels.pdf")
    pincode_output_path = str(Path(output_dir) / "selected-pincode-labels.pdf")
    multi_order_output_path = str(Path(output_dir) / "multi-order-labels.pdf")
    fanout_child = _option_bool(options.get("__fanout_child"))
    child_annotation_mode = fanout_child and (
        task_type in {"crop_meesho_chunk", "crop_flipkart_chunk"}
    )
    annotation_print_datetime = bool(effective_options.get("print_datetime")) and not child_annotation_mode
    annotation_multi_order_bottom = bool(effective_options.get("multi_order_bottom")) and not child_annotation_mode
    pick_list_enabled = _option_bool(effective_options.get("pick_list_enabled")) and not child_annotation_mode
    pick_list_after_orders = 0 if child_annotation_mode else int(max(0, pick_list_after_orders))
    annotation_custom_message = (
        (effective_options.get("custom_message") or "").strip() if not child_annotation_mode else ""
    )
    global_sort_finalizer_mode = child_annotation_mode and _needs_global_finalizer_pass(task_type, sort_by)

    def _copy_input_pdfs(paths: list[str], dest: str) -> None:
        if not paths:
            raise ValueError("Crop chunk has no input PDFs")
        if len(paths) == 1:
            shutil.copy2(paths[0], dest)
            return
        _merge_pdf_files(paths, dest)

    def _run_meesho(paths: list[str], dest: str) -> None:
        if global_sort_finalizer_mode:
            _copy_input_pdfs(paths, dest)
            return
        process_meesho_uploaded_paths(
            paths,
            dest,
            sort_by=sort_by or "order_id",
            layout=layout or "label_printer",
            print_datetime=annotation_print_datetime,
            multi_order_bottom=annotation_multi_order_bottom,
            pick_list_enabled=pick_list_enabled,
            pick_list_after_orders=pick_list_after_orders,
            custom_message=annotation_custom_message,
            progress_callback=_crop_progress,
        )

    def _run_flipkart(paths: list[str], dest: str) -> None:
        if global_sort_finalizer_mode:
            _copy_input_pdfs(paths, dest)
            return
        process_flipkart_uploaded_paths(
            paths,
            dest,
            layout=layout or "label_printer",
            sort_by=sort_by or "sku",
            multi_order_bottom=annotation_multi_order_bottom,
            pick_list_enabled=pick_list_enabled,
            pick_list_after_orders=pick_list_after_orders,
            print_datetime=annotation_print_datetime,
            custom_message=annotation_custom_message,
            progress_callback=_crop_progress,
        )

    if split_active:
        _set_progress(task["task_id"], 55, "Generating split outputs")
        if task_type in {"crop_meesho", "crop_meesho_chunk"}:
            if normal_input_paths:
                _run_meesho(normal_input_paths, normal_output_path)
            if pincode_input_paths:
                _run_meesho(pincode_input_paths, pincode_output_path)
            if risky_input_paths:
                _run_meesho(risky_input_paths, risky_output_path)
            if multi_order_input_paths:
                _run_meesho(multi_order_input_paths, multi_order_output_path)
        elif task_type in {"crop_flipkart", "crop_flipkart_chunk"}:
            if normal_input_paths:
                _run_flipkart(normal_input_paths, normal_output_path)
            if pincode_input_paths:
                _run_flipkart(pincode_input_paths, pincode_output_path)
            if risky_input_paths:
                _run_flipkart(risky_input_paths, risky_output_path)
            if multi_order_input_paths:
                _run_flipkart(multi_order_input_paths, multi_order_output_path)
        else:
            raise ValueError(f"Unsupported crop task type: {task_type}")

        # Build per-category Excel exports BEFORE writing the ZIP so the
        # workbooks can be archived alongside the cropped PDFs. Every enabled
        # split mode emits a workbook with the canonical header row even when
        # the matched-page set is empty - this keeps the ZIP contract
        # deterministic and lets downstream consumers open the file blindly.
        source_name_map = _build_split_source_name_map(
            input_paths=list(input_paths),
            risky_input_paths=risky_input_paths,
            pincode_input_paths=pincode_input_paths,
            multi_order_input_paths=multi_order_input_paths,
        )
        split_excel_specs: list[tuple[str, str, list[str]]] = []
        if detect_suspicious:
            split_excel_specs.append(
                ("suspicious", str(Path(output_dir) / SPLIT_EXPORT_FILENAMES["suspicious"]), risky_input_paths)
            )
        if multi_order_enabled:
            split_excel_specs.append(
                ("multi_order", str(Path(output_dir) / SPLIT_EXPORT_FILENAMES["multi_order"]), multi_order_input_paths)
            )
        if selected_pincodes:
            split_excel_specs.append(
                ("pincode", str(Path(output_dir) / SPLIT_EXPORT_FILENAMES["pincode"]), pincode_input_paths)
            )

        excel_export_summary: dict[str, dict] = {}
        for category, xlsx_path, source_paths in split_excel_specs:
            try:
                rows = _extract_split_rows_from_pdfs(
                    source_paths,
                    source_name_override=source_name_map,
                )
                _write_split_rows_xlsx(rows, xlsx_path, category=category)
                excel_export_summary[category] = {
                    "row_count": int(len(rows)),
                    "file": Path(xlsx_path).name,
                }
            except Exception as exc:
                logger.exception(
                    "Failed to build split Excel '%s' for task %s",
                    category,
                    task.get("task_id"),
                )
                excel_export_summary[category] = {
                    "row_count": 0,
                    "file": Path(xlsx_path).name,
                    "error": str(exc),
                }
        risk_split_summary["split_excel_exports"] = excel_export_summary
        _set_progress(task["task_id"], 86, "Preparing final ZIP package")

        zip_output = str(Path(output_dir) / "cropped-risk-split.zip")
        platform_labels_name = "Platform_Labels.pdf"
        if task_type == "crop_meesho":
            platform_labels_name = "Meesho_Labels.pdf"
        elif task_type == "crop_flipkart":
            platform_labels_name = "Flipkart_Labels.pdf"
        with zipfile.ZipFile(zip_output, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            if Path(normal_output_path).exists():
                zf.write(normal_output_path, arcname=platform_labels_name)
            if Path(risky_output_path).exists():
                zf.write(risky_output_path, arcname="Suspicious-Labels.pdf")
            if Path(pincode_output_path).exists():
                zf.write(pincode_output_path, arcname="Selected-Pincode-Labels.pdf")
            if Path(multi_order_output_path).exists():
                zf.write(multi_order_output_path, arcname="Multi-Order-Labels.pdf")
            for _category, xlsx_path, _source_paths in split_excel_specs:
                if Path(xlsx_path).exists():
                    zf.write(xlsx_path, arcname=Path(xlsx_path).name)
        output_path = zip_output
    else:
        if task_type in {"crop_meesho", "crop_meesho_chunk"}:
            _run_meesho(input_paths, output_path)
        elif task_type in {"crop_flipkart", "crop_flipkart_chunk"}:
            _run_flipkart(input_paths, output_path)
        else:
            raise ValueError(f"Unsupported crop task type: {task_type}")
    logger.info(
        "Crop task stage done task_id=%s stage=pdf_outputs elapsed_ms=%s split_active=%s",
        task.get("task_id"),
        int((time.perf_counter() - stage_perf) * 1000),
        split_active,
    )
    stage_perf = time.perf_counter()

    output_pages = (
        _safe_pdf_page_count_from_path(output_path)
        if output_path.lower().endswith(".pdf")
        else int(risk_split_summary.get("normal_pages", 0))
        + int(risk_split_summary.get("risky_pages", 0))
        + int(risk_split_summary.get("selected_pincode_pages", 0))
        + int(risk_split_summary.get("multi_order_pages", 0))
    )
    duration_ms = int((time.perf_counter() - start_perf) * 1000)
    summary = {
        "total_input_files": total_input_files,
        "total_input_pages": total_input_pages,
        "total_output_pages": output_pages,
        "total_output_labels": total_input_pages,
        **risk_split_summary,
    }
    billing_summary = (
        _apply_premium_crop_billing(task, summary, effective_options)
        if not _option_bool(options.get("__fanout_child"))
        else {
            "premium_billing_attempted": False,
            "premium_billing_applied": False,
            "premium_billing_error": "",
            "premium_coin_cost_per_label": int(PREMIUM_CROP_COIN_COST_PER_LABEL),
            "premium_coins_charged": 0,
        }
    )
    summary.update(billing_summary)
    if (
        not _option_bool(options.get("__fanout_child"))
        and _is_premium_crop_options_enabled({**effective_options, **summary})
        and int(billing_summary.get("premium_coins_charged") or 0) > 0
        and not bool(billing_summary.get("premium_billing_applied"))
    ):
        billing_error = str(billing_summary.get("premium_billing_error") or "").strip()
        raise RuntimeError(billing_error or "Premium billing failed. Please retry.")

    if not _option_bool(options.get("__fanout_child")):
        _safe_mark_crop_job_success(
            task,
            duration_ms=duration_ms,
            total_input_files=total_input_files,
            total_input_pages=total_input_pages,
            total_output_pages=output_pages,
            total_output_labels=total_input_pages,
            input_files=input_file_rows,
            sort_by=sort_by,
            layout=layout,
            options={
                **effective_options,
                **risk_split_summary,
                **billing_summary,
                "mode": "worker_queue",
                "turbo_requested": bool(turbo_mode),
            },
        )
    logger.info(
        "Crop task finished task_id=%s total_ms=%s output=%s",
        task.get("task_id"),
        int((time.perf_counter() - start_perf) * 1000),
        output_path,
    )
    return output_path, summary


def _process_crop_finalize_task(task: dict) -> tuple[str, dict]:
    payload = task.get("payload") or {}
    parent_task_id = str(payload.get("parent_task_id") or "")
    child_ids = [str(x) for x in (payload.get("child_task_ids") or []) if str(x)]
    if not parent_task_id or not child_ids:
        raise ValueError("Finalize task missing parent or child task ids")
    output_dir = payload.get("output_dir") or tempfile.mkdtemp(prefix=f"fanout_finalize_{parent_task_id}_")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    start_perf = time.perf_counter()
    deadline = time.time() + PDF_FANOUT_FINALIZER_WAIT_SEC
    parent_task = _redis_get_task(parent_task_id) if _use_redis_queue() else None
    if not parent_task:
        raise ValueError("Parent task is no longer available")

    while True:
        children = [_redis_get_task(child_id) for child_id in child_ids]
        missing = [child_id for child_id, child in zip(child_ids, children) if not child]
        if missing:
            raise ValueError(f"Fan-out child task missing: {missing[0]}")
        failed = [child for child in children if child and child.get("status") == "failed"]
        if failed:
            message = failed[0].get("error") or "A PDF chunk failed"
            _safe_mark_crop_job_failed(parent_task, error_message=message, input_files=payload.get("input_files") or [])
            _set_failed(parent_task, message)
            raise ValueError(message)
        done = [child for child in children if child and child.get("status") == "success" and child.get("result_path")]
        progress = 10 + int((len(done) / max(1, len(child_ids))) * 78)
        _update_task(
            parent_task_id,
            progress=max(10, min(92, progress)),
            message=f"Processed {len(done)}/{len(child_ids)} PDF chunks",
        )
        if len(done) == len(child_ids):
            break
        if time.time() > deadline:
            raise TimeoutError("Timed out waiting for PDF chunks to finish")
        time.sleep(2.0)

    ordered_children = sorted(
        (child for child in children if child),
        key=lambda child: int((child.get("payload") or {}).get("fanout_chunk_index") or 0),
    )
    _update_task(parent_task_id, progress=93, message="Collecting chunk outputs")

    def _materialize_child_output(idx: int, child: dict) -> tuple[int, str]:
        result_path = str(child.get("result_path") or "")
        if not result_path:
            raise ValueError(f"Fan-out child {child.get('task_id')} finished without output")
        local_path = str(Path(output_dir) / f"child-{idx:03d}{Path(result_path).suffix or '.pdf'}")
        if result_path.startswith("s3://"):
            _download_s3_uri_to_file(result_path, local_path)
        else:
            shutil.copy2(result_path, local_path)
        return idx, local_path

    local_outputs_by_index: dict[int, str] = {}
    max_download_workers = max(1, min(8, len(ordered_children)))
    with ThreadPoolExecutor(max_workers=max_download_workers) as pool:
        futures = [pool.submit(_materialize_child_output, idx, child) for idx, child in enumerate(ordered_children)]
        for fut in as_completed(futures):
            idx, local_path = fut.result()
            local_outputs_by_index[idx] = local_path
    local_outputs = [local_outputs_by_index[i] for i in range(len(ordered_children))]

    merged_path = str(Path(output_dir) / "fanout-merged.pdf")
    _update_task(parent_task_id, progress=95, message="Merging chunk outputs")
    _merge_pdf_files(local_outputs, merged_path)

    task_type = str(payload.get("task_type") or parent_task.get("task_type") or "")
    default_sort_by = "sku" if task_type == "crop_flipkart" else "order_id"
    sort_by = _normalize_sort_by(payload.get("sort_by"), default_sort_by)
    layout = (payload.get("layout") or "label_printer").strip()
    options = payload.get("options") or {}
    final_path = str(Path(output_dir) / "cropped-output.pdf")

    # Re-run only the global ordering/crop pass when the current platform sorts
    # labels globally. Preserve annotation options so fan-out jobs keep the same
    # visible output contract as non-fan-out runs.
    needs_global_pass = _needs_global_finalizer_pass(task_type, sort_by)
    if not needs_global_pass and _option_bool(options.get("pick_list_enabled")):
        logger.warning(
            "Fan-out finalizer forcing global pass for pick-list task parent_task_id=%s sort_by=%s",
            parent_task_id,
            sort_by,
        )
        needs_global_pass = True
    if needs_global_pass:
        print_datetime = _option_bool(options.get("print_datetime"))
        multi_order_bottom = _option_bool(options.get("multi_order_bottom"))
        pick_list_enabled = _option_bool(options.get("pick_list_enabled"))
        pick_list_after_orders = int(options.get("pick_list_after_orders") or 0)
        custom_message = str(options.get("custom_message") or "").strip()
        if task_type == "crop_meesho":
            process_meesho_uploaded_paths(
                [merged_path],
                final_path,
                sort_by=sort_by or "order_id",
                layout=layout or "label_printer",
                print_datetime=print_datetime,
                multi_order_bottom=multi_order_bottom,
                pick_list_enabled=pick_list_enabled,
                pick_list_after_orders=pick_list_after_orders,
                custom_message=custom_message,
            )
        elif task_type == "crop_flipkart":
            process_flipkart_uploaded_paths(
                [merged_path],
                final_path,
                layout=layout or "label_printer",
                sort_by=sort_by or "sku",
                multi_order_bottom=multi_order_bottom,
                pick_list_enabled=pick_list_enabled,
                pick_list_after_orders=pick_list_after_orders,
                print_datetime=print_datetime,
                custom_message=custom_message,
            )
        else:
            raise ValueError(f"Unsupported fan-out finalizer type: {task_type}")
    else:
        shutil.copy2(merged_path, final_path)

    output_pages = _safe_pdf_page_count_from_path(final_path)
    total_input_files = int(payload.get("total_input_files") or 0)
    total_input_pages = int(payload.get("total_input_pages") or output_pages)
    duration_ms = int((time.perf_counter() - start_perf) * 1000)
    summary = {
        "total_input_files": total_input_files,
        "total_input_pages": total_input_pages,
        "total_output_pages": output_pages,
        "total_output_labels": total_input_pages,
        "fanout_enabled": True,
        "fanout_child_tasks": len(child_ids),
        "fanout_parent_task_id": parent_task_id,
    }
    _safe_mark_crop_job_success(
        parent_task,
        duration_ms=duration_ms,
        total_input_files=total_input_files,
        total_input_pages=total_input_pages,
        total_output_pages=output_pages,
        total_output_labels=total_input_pages,
        input_files=payload.get("input_files") or [],
        sort_by=sort_by,
        layout=layout,
        options={**options, **summary, "mode": "distributed_worker_queue"},
    )
    logger.info(
        "PDF fan-out finalized parent_task_id=%s children=%s total_ms=%s output=%s",
        parent_task_id,
        len(child_ids),
        duration_ms,
        final_path,
    )
    return final_path, summary


def _process_return_analysis_task(task: dict) -> tuple[str, dict]:
    payload = task.get("payload") or {}
    output_dir = payload.get("output_dir") or ""
    if not output_dir:
        raise ValueError("Return analysis task missing output directory")
    returns_path = payload.get("returns_excel_path") or ""
    orders_csv_path = payload.get("orders_csv_path") or ""
    if not returns_path or not orders_csv_path:
        raise ValueError("Return analysis payload missing input file paths")
    start_perf = time.perf_counter()
    options = payload.get("options") or {}
    source_platform = _normalize_risk_platform(options.get("source_platform"))
    output_path, summary = analyze_returns_against_orders(
        orders_csv_path=orders_csv_path,
        returns_excel_path=returns_path,
        output_dir=output_dir,
    )
    risk_profile_summary = _build_risk_profile_from_analysis_csv(
        user_id=int(task["user_id"]),
        analysis_csv_path=output_path,
        platform=source_platform or None,
    )
    duration_ms = int((time.perf_counter() - start_perf) * 1000)
    combined_summary = {**summary, **risk_profile_summary}
    _safe_mark_crop_job_success(
        task,
        duration_ms=duration_ms,
        total_input_files=1,
        total_input_pages=1,
        total_output_pages=1,
        total_output_labels=int(combined_summary.get("matched_returns") or 0),
        input_files=[{"file_name": Path(returns_path).name, "input_pages": 1}],
        sort_by="suborder_match",
        layout="csv",
        options={**combined_summary, "mode": "worker_queue", "stored_on_server_only": True},
    )
    return output_path, combined_summary


def _safe_mark_crop_job_failed(task: dict, *, error_message: str, input_files: list[dict] | None = None) -> None:
    """Best-effort crop history update; never let history write crash the worker loop."""
    try:
        mark_crop_job_failed(
            int(task["job_id"]),
            error_message=error_message,
            duration_ms=0,
            input_files=input_files if input_files is not None else [],
        )
    except Exception:
        logger.exception("Failed to record crop_job failure for task %s job_id=%s", task.get("task_id"), task.get("job_id"))


def _safe_mark_crop_job_success(
    task: dict,
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
    """Best-effort crop history success update; never fail task completion on history DB mismatch."""
    try:
        mark_crop_job_success(
            int(task["job_id"]),
            duration_ms=duration_ms,
            total_input_files=total_input_files,
            total_input_pages=total_input_pages,
            total_output_pages=total_output_pages,
            total_output_labels=total_output_labels,
            input_files=input_files,
            sort_by=sort_by,
            layout=layout,
            options=options or {},
        )
    except Exception:
        logger.exception("Failed to record crop_job success for task %s job_id=%s", task.get("task_id"), task.get("job_id"))


def _process_one_task(task: dict) -> None:
    task_id = task["task_id"]
    payload = task.get("payload") or {}
    task_start_perf = time.perf_counter()
    try:
        _set_progress(task_id, 3, "Starting")
        _hydrate_s3_inputs_if_needed(task)
        payload = task.get("payload") or payload
        if task["task_type"] in {"crop_meesho", "crop_flipkart"} and _maybe_start_crop_fanout(task):
            return
        if task["task_type"] in {"ocr_csv", "ocr_excel"}:
            output_path, summary = _process_ocr_task(task)
        elif task["task_type"] in {"crop_meesho", "crop_flipkart", "crop_meesho_chunk", "crop_flipkart_chunk"}:
            output_path, summary = _process_crop_task(task)
        elif task["task_type"] == "crop_finalize":
            output_path, summary = _process_crop_finalize_task(task)
        elif task["task_type"] == "return_analysis":
            output_path, summary = _process_return_analysis_task(task)
        else:
            raise ValueError(f"Unsupported task_type={task['task_type']}")
        _set_progress(task_id, 97, "Uploading output artifacts")
        output_path = _upload_result_to_s3_if_needed(task, output_path)
        _set_progress(task_id, 99, "Finalizing task")
        if task["task_type"] == "crop_finalize":
            parent_task_id = str((task.get("payload") or {}).get("parent_task_id") or "")
            parent_task = _redis_get_task(parent_task_id) if parent_task_id else None
            if parent_task:
                _set_success(parent_task, result_path=output_path, summary=summary)
        _set_success(task, result_path=output_path, summary=summary)
        logger.info(
            "Task success task_id=%s type=%s elapsed_ms=%s",
            task_id,
            task.get("task_type"),
            int((time.perf_counter() - task_start_perf) * 1000),
        )
    except OcrSetupError as exc:
        if not _option_bool((payload.get("options") or {}).get("__fanout_child")):
            _safe_mark_crop_job_failed(task, error_message=str(exc), input_files=payload.get("input_files") or [])
        _set_failed(task, str(exc))
    except Exception as exc:
        logger.exception("Task failed: %s", task_id)
        if not _option_bool((payload.get("options") or {}).get("__fanout_child")):
            _safe_mark_crop_job_failed(task, error_message=str(exc), input_files=payload.get("input_files") or [])
        _set_failed(task, str(exc))
    finally:
        _cleanup_input_files(payload)


def run_worker_once(worker_id: str) -> bool:
    task = _claim_next_task(worker_id)
    if not task:
        return False
    _process_one_task(task)
    return True


def _worker_loop(worker_id: str, poll_interval_sec: float = 0.6) -> None:
    while not _embedded_worker_stop.is_set():
        try:
            had = run_worker_once(worker_id)
        except sqlite3.OperationalError as exc:
            # SQLite can transiently lock during concurrent writes; keep workers
            # alive and retry instead of crashing the thread.
            if "database is locked" in str(exc).lower():
                logger.warning("Worker %s retrying after DB lock", worker_id)
                had = False
            else:
                logger.exception("Worker %s hit database error", worker_id)
                had = False
        except Exception:
            logger.exception("Worker %s loop error", worker_id)
            had = False
        if not had:
            _embedded_worker_stop.wait(timeout=max(0.2, poll_interval_sec))


def start_embedded_worker() -> None:
    global _embedded_worker_threads
    if os.getenv("DISABLE_EMBEDDED_WORKER", "").strip().lower() in {"1", "true", "yes"}:
        return
    requested = int(os.getenv("EMBEDDED_WORKER_CONCURRENCY", "2") or 2)
    worker_count = max(1, min(8, requested))
    alive_threads = [t for t in _embedded_worker_threads if t and t.is_alive()]
    if len(alive_threads) >= worker_count:
        _embedded_worker_threads = alive_threads
        return
    _embedded_worker_stop.clear()
    _embedded_worker_threads = alive_threads
    worker_ids: list[str] = []
    for _ in range(worker_count - len(alive_threads)):
        worker_id = f"{socket.gethostname()}-embedded-{uuid.uuid4().hex[:8]}"
        t = threading.Thread(target=_worker_loop, args=(worker_id,), daemon=True)
        t.start()
        _embedded_worker_threads.append(t)
        worker_ids.append(worker_id)
    if worker_ids:
        logger.info(
            "Embedded queue workers active=%s started=%s ids=%s",
            len(_embedded_worker_threads),
            len(worker_ids),
            ",".join(worker_ids),
        )


def stop_embedded_worker() -> None:
    global _embedded_worker_threads
    _embedded_worker_stop.set()
    for t in list(_embedded_worker_threads):
        if t and t.is_alive():
            t.join(timeout=2)
    _embedded_worker_threads = []


def fail_orphan_running_tasks(*, error_message: str = "Worker restarted while processing. Please retry.") -> int:
    """Mark running queue tasks as failed after process restarts.

    When the server reloads or crashes, in-flight worker threads are gone and
    their DB rows can remain in ``running``. This helper makes status explicit
    for both queue tasks and linked crop jobs.
    """
    now_iso = _utc_now_iso()
    cleaned = 0
    with _db_connect() as conn:
        rows = conn.execute(
            """
            SELECT task_id, job_id, payload_json
            FROM processing_tasks
            WHERE status = 'running'
            """
        ).fetchall()
        if not rows:
            return 0
        for row in rows:
            task_id = row["task_id"]
            job_id = int(row["job_id"] or 0)
            input_files = []
            try:
                payload = json.loads(row["payload_json"] or "{}")
                input_files = payload.get("input_files") or []
            except Exception:
                input_files = []
            conn.execute(
                """
                UPDATE processing_tasks
                SET status = 'failed',
                    progress = 100,
                    message = 'Failed',
                    error = ?,
                    finished_at = ?,
                    lease_expires_at = '',
                    updated_at = ?
                WHERE task_id = ?
                """,
                (error_message[:1200], now_iso, now_iso, task_id),
            )
            if job_id > 0:
                try:
                    mark_crop_job_failed(
                        job_id,
                        error_message=error_message,
                        duration_ms=0,
                        input_files=input_files,
                    )
                except Exception:
                    logger.exception("Could not mark orphan crop job %s as failed", job_id)
            cleaned += 1
    return cleaned


def purge_finished_tasks(*, older_than_hours: int = 24) -> int:
    """Remove **crop-only** finished tasks and their temp/output files.

    OCR master CSV rows, return-analysis rows, and other durable analytics tasks
    are intentionally **not** deleted here so admin downloads and history stay
    valid. (Callers should prefer ``purge_finished_crop_artifacts`` for the
    nightly cropped-label retention policy.)
    """
    cutoff = (_utc_now() - timedelta(hours=max(1, int(older_than_hours)))).isoformat()
    removed = 0
    with _db_connect() as conn:
        rows = conn.execute(
            """
            SELECT task_id, result_path, payload_json
            FROM processing_tasks
            WHERE task_type IN ('crop_meesho', 'crop_flipkart')
              AND status IN ('success', 'failed', 'cancelled', 'expired')
              AND updated_at < ?
            """,
            (cutoff,),
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except Exception:
                payload = {}
            result_path = (row["result_path"] or "").strip()
            if result_path:
                if not _path_should_never_bulk_delete(result_path):
                    delete_stored_task_result(result_path)
            output_dir = (payload.get("output_dir") or "").strip()
            if output_dir:
                try:
                    shutil.rmtree(output_dir, ignore_errors=True)
                except Exception:
                    pass
            removed += 1
        conn.execute(
            """
            DELETE FROM processing_tasks
            WHERE task_type IN ('crop_meesho', 'crop_flipkart')
              AND status IN ('success', 'failed', 'cancelled', 'expired')
              AND updated_at < ?
            """,
            (cutoff,),
        )
    return removed


def purge_finished_crop_artifacts(*, older_than_hours: int = 24) -> int:
    """Delete stale **cropped label** outputs only (PDF/ZIP and temp dirs).

    Does **not** remove OCR master CSVs, suspicious/risk profile CSVs, or
    other analysis artifacts — those stay for admin export and dashboards.
    Uses ``DOWNLOAD_EXPIRY_MODE`` / midnight boundary when set to calendar day.
    """
    expiry_mode = (os.getenv("DOWNLOAD_EXPIRY_MODE", "calendar_day") or "calendar_day").strip().lower()
    if expiry_mode in {"calendar_day", "daily", "midnight"}:
        local_now = datetime.now().astimezone()
        local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = local_midnight.astimezone(timezone.utc).isoformat()
    else:
        cutoff = (_utc_now() - timedelta(hours=max(1, int(older_than_hours)))).isoformat()
    now_iso = _utc_now_iso()
    cleaned = 0
    with _db_connect() as conn:
        rows = conn.execute(
            """
            SELECT task_id, result_path, payload_json
            FROM processing_tasks
            WHERE task_type IN ('crop_meesho', 'crop_flipkart')
              AND status IN ('success', 'failed', 'cancelled', 'expired')
              AND updated_at < ?
              AND (
                COALESCE(result_path, '') <> ''
                OR COALESCE(payload_json, '') LIKE '%"output_dir"%'
              )
            """,
            (cutoff,),
        ).fetchall()

        for row in rows:
            task_id = str(row["task_id"] or "").strip()
            if not task_id:
                continue
            result_path = str(row["result_path"] or "").strip()
            payload: dict = {}
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except Exception:
                payload = {}
            output_dir = str(payload.get("output_dir") or "").strip()
            removed_any = False

            if result_path:
                try:
                    delete_stored_task_result(result_path)
                    removed_any = True
                except Exception:
                    pass

            if output_dir:
                try:
                    shutil.rmtree(output_dir, ignore_errors=True)
                    removed_any = True
                except Exception:
                    pass

            if "output_dir" in payload:
                payload["output_dir"] = ""
            conn.execute(
                """
                UPDATE processing_tasks
                SET result_path = '', payload_json = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (json.dumps(payload or {}, ensure_ascii=True), now_iso, task_id),
            )
            if removed_any:
                cleaned += 1
    return cleaned


def get_queue_metrics() -> dict:
    now_iso = _utc_now_iso()
    now_dt = _utc_now()

    def _queued_age_sec(iso_stamp: str) -> int:
        text = (iso_stamp or "").strip()
        if not text:
            return 0
        try:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return max(0, int((now_dt - stamp).total_seconds()))
        except Exception:
            return 0

    if _use_redis_queue():
        cache_ttl_sec = max(1.0, float(os.getenv("REDIS_QUEUE_METRICS_CACHE_SEC", "5") or 5))
        now_ts = time.time()
        cached_payload = _queue_metrics_cache.get("payload")
        cached_ts = float(_queue_metrics_cache.get("ts") or 0.0)
        if cached_payload and now_ts - cached_ts <= cache_ttl_sec:
            return dict(cached_payload)

        client = _redis_client()
        queued = int(client.llen(_redis_queue_name()) or 0)
        running = 0
        failed_24h = 0
        oldest_queued_at = ""
        pattern = f"{_redis_queue_name()}:task:*"
        cutoff = _utc_now() - timedelta(days=1)
        scan_limit = max(100, int(os.getenv("REDIS_QUEUE_METRICS_SCAN_LIMIT", "2000") or 2000))
        scanned = 0
        for key in client.scan_iter(match=pattern, count=100):
            scanned += 1
            if scanned > scan_limit:
                break
            raw = client.get(key)
            if not raw:
                continue
            try:
                task = _normalize_redis_task(json.loads(raw))
            except Exception:
                continue
            status = task.get("status")
            if status == "running":
                running += 1
            elif status == "queued":
                created = task.get("created_at") or ""
                if not oldest_queued_at or created < oldest_queued_at:
                    oldest_queued_at = created
            elif status == "failed":
                try:
                    updated = datetime.fromisoformat((task.get("updated_at") or "").replace("Z", "+00:00"))
                    if updated >= cutoff:
                        failed_24h += 1
                except Exception:
                    pass
        payload = {
            "queued": queued,
            "running": running,
            "failed_24h": failed_24h,
            "oldest_queued_at": oldest_queued_at,
            "oldest_queued_age_sec": _queued_age_sec(oldest_queued_at),
            "generated_at": now_iso,
        }
        _queue_metrics_cache["ts"] = now_ts
        _queue_metrics_cache["payload"] = payload
        return payload

    with _db_connect() as conn:
        queued = int(conn.execute("SELECT COUNT(1) AS cnt FROM processing_tasks WHERE status = 'queued'").fetchone()["cnt"])
        running = int(conn.execute("SELECT COUNT(1) AS cnt FROM processing_tasks WHERE status = 'running'").fetchone()["cnt"])
        failed_24h = int(
            conn.execute(
                """
                SELECT COUNT(1) AS cnt
                FROM processing_tasks
                WHERE status = 'failed'
                  AND updated_at >= datetime('now','-1 day')
                """
            ).fetchone()["cnt"]
        )
        oldest_queued = conn.execute(
            """
            SELECT created_at
            FROM processing_tasks
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
    return {
        "queued": queued,
        "running": running,
        "failed_24h": failed_24h,
        "oldest_queued_at": (oldest_queued["created_at"] if oldest_queued else ""),
        "oldest_queued_age_sec": _queued_age_sec(oldest_queued["created_at"] if oldest_queued else ""),
        "generated_at": now_iso,
    }


def get_latest_successful_ocr_result_for_user(
    user_id: int,
    platform: object | None = None,
) -> dict | None:
    """Return the most recent OCR master CSV info for a user.

    When ``platform`` is one of the supported per-platform values
    (e.g. ``meesho``/``flipkart``), only the platform-scoped file is
    consulted. Otherwise the legacy union file is preferred and we fall back
    to the most recent ``processing_tasks`` row that still has a usable
    ``result_path``.
    """
    norm_platform = _normalize_ocr_platform(platform)
    master_path = _user_ocr_master_csv_path(int(user_id), norm_platform or None)
    if master_path.is_file():
        _ensure_ocr_master_csv_schema(master_path)
        updated_at = datetime.fromtimestamp(master_path.stat().st_mtime, tz=timezone.utc).isoformat()
        return {
            "task_id": "",
            "result_path": str(master_path),
            "updated_at": updated_at,
            "platform": norm_platform or "legacy",
            "summary": {"master_records_total": _count_csv_rows(master_path)},
        }
    if redis_ocr_master_lookup_enabled():
        redis_hit = _redis_latest_successful_ocr_snapshot(int(user_id), norm_platform)
        if redis_hit:
            return redis_hit
    # Fallback for distributed deployments where worker artifacts are persisted
    # remotely (e.g. S3) and local CSV files are not shared with the API pod.
    # We still surface the most recent successful OCR task result path so admin
    # status/download flows can resolve the artifact.
    with _db_connect() as conn:
        rows = conn.execute(
            """
            SELECT task_id, result_path, summary_json, payload_json, updated_at
            FROM processing_tasks
            WHERE user_id = ?
              AND task_type IN ('ocr_csv', 'ocr_excel')
              AND status = 'success'
              AND result_path <> ''
            ORDER BY updated_at DESC
            LIMIT 100
            """,
            (int(user_id),),
        ).fetchall()
    if not rows:
        return None
    for row in rows:
        result_path = str(row["result_path"] or "").strip()
        if not result_path:
            continue
        summary = {}
        payload = {}
        try:
            summary = json.loads(row["summary_json"] or "{}")
        except Exception:
            summary = {}
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        row_platform = _normalize_ocr_platform(summary.get("master_platform"))
        if not row_platform:
            row_platform = _normalize_ocr_platform(((payload.get("options") or {}).get("source_platform")))
        if not row_platform:
            row_platform = _infer_ocr_master_platform_from_result_path(result_path)
        # If platform metadata is missing, do not skip: infer may have left
        # row_platform empty; skipping here caused false "no master" in admin.
        if norm_platform and row_platform and row_platform != norm_platform:
            continue
        if not result_path.startswith("s3://") and not Path(result_path).is_file():
            continue
        return {
            "task_id": row["task_id"],
            "result_path": result_path,
            "updated_at": row["updated_at"] or "",
            "platform": row_platform or "legacy",
            "summary": summary,
        }
    if norm_platform:
        # Platform-specific request and no matching artifact exists.
        return None
    with _db_connect() as conn:
        row = conn.execute(
            """
            SELECT task_id, result_path, summary_json, updated_at
            FROM processing_tasks
            WHERE user_id = ?
              AND task_type IN ('ocr_csv', 'ocr_excel')
              AND status = 'success'
              AND result_path <> ''
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()
    if not row:
        return None
    result_path = (row["result_path"] or "").strip()
    if not result_path:
        return None
    if not result_path.startswith("s3://") and not Path(result_path).is_file():
        return None
    summary = {}
    try:
        summary = json.loads(row["summary_json"] or "{}")
    except Exception:
        summary = {}
    return {
        "task_id": row["task_id"],
        "result_path": result_path,
        "updated_at": row["updated_at"] or "",
        "platform": "legacy",
        "summary": summary,
    }


def get_ocr_master_platform_status_for_user(user_id: int) -> dict:
    """Return availability flags + paths for each per-platform OCR master CSV.

    Used by the admin panel to render per-platform download affordances.
    """
    safe_user_id = int(user_id)
    out: dict[str, dict] = {}
    for platform in SUPPORTED_OCR_PLATFORMS:
        path = _user_ocr_master_csv_path(safe_user_id, platform)
        if path.is_file():
            _ensure_ocr_master_csv_schema(path)
            out[platform] = {
                "available": True,
                "path": str(path),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "row_count": _count_csv_rows(path),
            }
        else:
            latest = get_latest_successful_ocr_result_for_user(safe_user_id, platform=platform)
            summary = (latest or {}).get("summary") or {}
            out[platform] = {
                "available": bool(latest),
                "path": str((latest or {}).get("result_path") or ""),
                "updated_at": str((latest or {}).get("updated_at") or ""),
                "row_count": int(summary.get("master_records_total") or 0),
            }
    legacy_path = _user_ocr_master_csv_path(safe_user_id, None)
    if legacy_path.is_file():
        _ensure_ocr_master_csv_schema(legacy_path)
    if legacy_path.is_file():
        out["legacy"] = {
            "available": True,
            "path": str(legacy_path),
            "updated_at": datetime.fromtimestamp(legacy_path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "row_count": _count_csv_rows(legacy_path),
        }
    else:
        latest = get_latest_successful_ocr_result_for_user(safe_user_id, platform=None)
        summary = (latest or {}).get("summary") or {}
        out["legacy"] = {
            "available": bool(latest),
            "path": str((latest or {}).get("result_path") or ""),
            "updated_at": str((latest or {}).get("updated_at") or ""),
            "row_count": int(summary.get("master_records_total") or 0),
        }
    return out


def get_latest_suspicious_profile_result_for_user(
    user_id: int,
    platform: object | None = None,
) -> dict | None:
    norm_platform = _normalize_risk_platform(platform)
    profile_path = _user_risk_profile_csv_path(int(user_id), norm_platform or None)
    if profile_path.exists():
        updated_at = datetime.fromtimestamp(profile_path.stat().st_mtime, tz=timezone.utc).isoformat()
        return {
            "result_path": str(profile_path),
            "updated_at": updated_at,
            "platform": norm_platform or "legacy",
            "summary": {"risk_profiles_total": _count_csv_rows(profile_path)},
        }
    if norm_platform:
        return None
    return None


def get_suspicious_profile_platform_status_for_user(user_id: int) -> dict:
    safe_user_id = int(user_id)
    out: dict[str, dict] = {}
    for platform in SUPPORTED_OCR_PLATFORMS:
        path = _user_risk_profile_csv_path(safe_user_id, platform)
        if path.exists():
            out[platform] = {
                "available": True,
                "path": str(path),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "row_count": _count_csv_rows(path),
            }
        else:
            out[platform] = {
                "available": False,
                "path": "",
                "updated_at": "",
                "row_count": 0,
            }
    legacy_path = _user_risk_profile_csv_path(safe_user_id, None)
    out["legacy"] = {
        "available": legacy_path.exists(),
        "path": str(legacy_path) if legacy_path.exists() else "",
        "updated_at": (
            datetime.fromtimestamp(legacy_path.stat().st_mtime, tz=timezone.utc).isoformat()
            if legacy_path.exists()
            else ""
        ),
        "row_count": _count_csv_rows(legacy_path) if legacy_path.exists() else 0,
    }
    return out


def _list_admin_tasks_by_types(
    *,
    task_types: tuple[str, ...],
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    safe_limit = min(max(int(limit), 1), 100)
    safe_offset = max(int(offset), 0)
    clean_query = (query or "").strip().lower()
    placeholders = ",".join(["?"] * len(task_types))
    where_sql = f"WHERE t.task_type IN ({placeholders})"
    params: list[object] = list(task_types)
    if clean_query:
        pattern = f"%{clean_query}%"
        where_sql += (
            " AND (LOWER(t.task_id) LIKE ? OR LOWER(CAST(t.job_id AS TEXT)) LIKE ? OR "
            "LOWER(u.email) LIKE ? OR LOWER(u.name) LIKE ?)"
        )
        params.extend([pattern, pattern, pattern, pattern])
    with _db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT t.task_id, t.job_id, t.user_id, t.task_type, t.status, t.progress, t.message, t.error,
                   t.result_path, t.created_at, t.updated_at, t.started_at, t.finished_at,
                   u.email AS user_email, u.name AS user_name
            FROM processing_tasks t
            LEFT JOIN users u ON u.id = t.user_id
            {where_sql}
            ORDER BY t.created_at DESC, t.task_id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, safe_limit, safe_offset),
        ).fetchall()
    out = []
    for row in rows:
        result_path = row["result_path"] or ""
        out.append(
            {
                "task_id": row["task_id"],
                "job_id": int(row["job_id"]),
                "user_id": int(row["user_id"]),
                "user_email": row["user_email"] or "",
                "user_name": row["user_name"] or "",
                "task_type": row["task_type"] or "",
                "status": row["status"] or "",
                "progress": int(row["progress"] or 0),
                "message": row["message"] or "",
                "error": row["error"] or "",
                "result_path_exists": bool(result_path and Path(result_path).exists()),
                "created_at": row["created_at"] or "",
                "updated_at": row["updated_at"] or "",
                "started_at": row["started_at"] or "",
                "finished_at": row["finished_at"] or "",
            }
        )
    return out


def _count_admin_tasks_by_types(*, task_types: tuple[str, ...], query: str | None = None) -> int:
    clean_query = (query or "").strip().lower()
    placeholders = ",".join(["?"] * len(task_types))
    where_sql = f"WHERE t.task_type IN ({placeholders})"
    params: list[object] = list(task_types)
    if clean_query:
        pattern = f"%{clean_query}%"
        where_sql += (
            " AND (LOWER(t.task_id) LIKE ? OR LOWER(CAST(t.job_id AS TEXT)) LIKE ? OR "
            "LOWER(u.email) LIKE ? OR LOWER(u.name) LIKE ?)"
        )
        params.extend([pattern, pattern, pattern, pattern])
    with _db_connect() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(1) AS cnt
            FROM processing_tasks t
            LEFT JOIN users u ON u.id = t.user_id
            {where_sql}
            """,
            tuple(params),
        ).fetchone()
    return int(row["cnt"] if row else 0)


def _read_admin_task_rows_by_types(
    *,
    task_types: tuple[str, ...],
    task_label: str,
    task_id: str,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    safe_limit = min(max(int(limit), 1), 500)
    safe_offset = max(int(offset), 0)
    placeholders = ",".join(["?"] * len(task_types))
    with _db_connect() as conn:
        row = conn.execute(
            f"""
            SELECT task_id, user_id, task_type, status, result_path
            FROM processing_tasks
            WHERE task_id = ? AND task_type IN ({placeholders})
            """,
            (task_id, *task_types),
        ).fetchone()
    if not row:
        raise ValueError(f"{task_label} task not found.")
    result_path = (row["result_path"] or "").strip()
    if row["status"] != "success":
        raise ValueError(f"{task_label} task is not completed yet.")
    csv_bytes: bytes | None = None
    if result_path:
        if result_path.startswith("s3://"):
            csv_bytes = _read_result_bytes(result_path)
        else:
            p = Path(result_path)
            if p.exists():
                try:
                    csv_bytes = p.read_bytes()
                except Exception:
                    csv_bytes = None
    if not csv_bytes:
        kind = _analysis_artifact_kind_for_task_type(str(row["task_type"] or ""))
        if kind:
            csv_bytes = get_analysis_artifact_snapshot_bytes_for_user(
                user_id=int(row["user_id"] or 0),
                artifact_kind=kind,
                platform=None,
            )
    if not csv_bytes:
        raise ValueError(f"Stored {task_label} CSV file is not available.")
    clean_query = (query or "").strip().lower()
    all_rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="admin_task_rows_") as td:
        p = Path(td) / "rows.csv"
        p.write_bytes(csv_bytes)
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                normalized = {str(k or "").strip(): ("" if v is None else str(v)) for k, v in (r or {}).items()}
                if clean_query:
                    hay = " ".join(normalized.values()).lower()
                    if clean_query not in hay:
                        continue
                all_rows.append(normalized)
    total = len(all_rows)
    return all_rows[safe_offset : safe_offset + safe_limit], total


def list_admin_ocr_tasks(
    *,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    return _list_admin_tasks_by_types(
        task_types=("ocr_csv", "ocr_excel"),
        query=query,
        limit=limit,
        offset=offset,
    )


def count_admin_ocr_tasks(*, query: str | None = None) -> int:
    return _count_admin_tasks_by_types(task_types=("ocr_csv", "ocr_excel"), query=query)


def read_admin_ocr_task_rows(
    *,
    task_id: str,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    return _read_admin_task_rows_by_types(
        task_types=("ocr_csv", "ocr_excel"),
        task_label="OCR",
        task_id=task_id,
        query=query,
        limit=limit,
        offset=offset,
    )


def list_admin_return_tasks(
    *,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    return _list_admin_tasks_by_types(
        task_types=("return_analysis",),
        query=query,
        limit=limit,
        offset=offset,
    )


def count_admin_return_tasks(*, query: str | None = None) -> int:
    return _count_admin_tasks_by_types(task_types=("return_analysis",), query=query)


def read_admin_return_task_rows(
    *,
    task_id: str,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    return _read_admin_task_rows_by_types(
        task_types=("return_analysis",),
        task_label="return analysis",
        task_id=task_id,
        query=query,
        limit=limit,
        offset=offset,
    )

