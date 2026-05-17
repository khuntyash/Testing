"""End-to-end exercise of ``_process_crop_task`` showing courier counts in
the persisted summary and the in-flight task summary.

Why this script exists
----------------------
The crop pipeline is normally driven by the embedded worker reading rows from
the ``processing_tasks`` SQLite table. To prove that the new courier-counts
plumbing is wired correctly into both:

  * the in-flight ``summary`` returned to the client polling the task, and
  * the persisted ``options_json`` / ``summary_json`` rows used by the
    history APIs after the task completes,

we point the auth/labelhub DB to a throwaway file, build a tiny synthetic
multi-courier Meesho PDF, enqueue + run a crop task end-to-end, and inspect
the resulting summary.

Run with the project root as cwd::

    python backend/temp/courier_count_e2e.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

# Build a throwaway DB path BEFORE importing the auth/history modules, then
# monkey-patch the module-level ``DB_PATH`` constants so this smoke test
# never touches the developer's real labelhub.db. Both ``history_store`` and
# ``task_queue`` re-import ``DB_PATH`` from ``auth_store`` so a single patch
# is sufficient.
SCRATCH_DIR = Path(tempfile.mkdtemp(prefix="courier_count_e2e_"))
SCRATCH_DB = SCRATCH_DIR / "labelhub.db"

import auth_store  # noqa: E402

auth_store.DB_PATH = SCRATCH_DB

from auth_store import create_user, init_db as init_auth_db  # noqa: E402
import history_store  # noqa: E402

history_store.DB_PATH = SCRATCH_DB
from history_store import (  # noqa: E402
    create_crop_job,
    get_crop_job_for_user,
    init_history_db,
    mark_crop_job_started,
)
import task_queue  # noqa: E402

task_queue.DB_PATH = SCRATCH_DB
task_queue.OCR_MASTER_DIR = (SCRATCH_DIR / "ocr_store").resolve()
task_queue.RISK_STORE_DIR = (SCRATCH_DIR / "risk_store").resolve()
from task_queue import (  # noqa: E402
    _fetch_task_by_id,
    _process_crop_task,
    enqueue_task,
    init_task_queue_db,
)

CARRIER_PAGES = [
    ("Shadowfax", "Shadowfax Logistics\nOrder No.\nSF12345\nDelivery: COD"),
    ("Valmo", "Valmo Express\nOrder No.\nVL12345\nDelivery: COD"),
    ("ValmoPlus", "ValmoPlus Premium\nOrder No.\nVLP12345\nDelivery: Prepaid"),
    ("Delhivery", "Delhivery Surface\nOrder No.\nDLV12345\nDelivery: COD"),
    ("Unknown", "Generic Marker\nOrder No.\nGEN12345\nDelivery: COD"),
]


def _build_pdf(target: Path) -> int:
    doc = fitz.open()
    try:
        for _name, body in CARRIER_PAGES:
            page = doc.new_page(width=420, height=600)
            page.insert_text((40, 60), body, fontsize=11)
        target.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(target))
        return len(doc)
    finally:
        doc.close()


def main() -> int:
    init_auth_db()
    init_history_db()
    init_task_queue_db()
    user = create_user(
        name="Courier Counts Smoke",
        email="courier-count-e2e@example.com",
        password="example-pass-1",
    )
    user_id = int(user["id"])

    work_dir = SCRATCH_DIR / "task_inputs"
    work_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = work_dir / "synthetic_couriers.pdf"
    page_count = _build_pdf(pdf_path)

    job_id = create_crop_job(
        user_id=user_id,
        platform="meesho",
        sort_by="order_id",
        layout="label_printer",
        options={"smoke_test": True},
    )
    mark_crop_job_started(job_id)
    payload = {
        "output_dir": str(work_dir),
        "input_paths": [str(pdf_path)],
        "input_files": [{"file_name": pdf_path.name, "input_pages": page_count}],
        "total_input_files": 1,
        "total_input_pages": page_count,
        "sort_by": "order_id",
        "layout": "label_printer",
        "options": {},
    }
    task_id = enqueue_task(
        user_id=user_id,
        job_id=job_id,
        task_type="crop_meesho",
        payload=payload,
    )

    task_row = _fetch_task_by_id(task_id)
    assert task_row, "failed to fetch newly-enqueued task"

    output_path, summary = _process_crop_task(task_row)

    print("output_path:", output_path)
    print("summary courier_counts:", summary.get("courier_counts"))
    print("summary courier_count_total:", summary.get("courier_count_total"))
    print("summary courier_count_error:", summary.get("courier_count_error"))

    assert summary.get("courier_count_total") == page_count, summary
    counts = summary.get("courier_counts") or {}
    for label, _body in CARRIER_PAGES:
        assert counts.get(label, 0) >= 1, f"missing carrier bucket: {label} in {counts}"

    job = get_crop_job_for_user(user_id, job_id)
    assert job, "history job not found"
    options = job.get("options") or {}
    print("history options.courier_counts:", options.get("courier_counts"))
    print("history options.courier_count_total:", options.get("courier_count_total"))
    assert options.get("courier_count_total") == page_count, options
    persisted_counts = options.get("courier_counts") or {}
    for label, _body in CARRIER_PAGES:
        assert persisted_counts.get(label, 0) >= 1, persisted_counts

    print("\nFULL SUMMARY:")
    print(json.dumps({k: v for k, v in summary.items() if "courier" in k or "normal" in k}, indent=2))

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
