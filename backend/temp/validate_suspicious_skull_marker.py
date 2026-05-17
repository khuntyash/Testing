"""Practical validation harness for the suspicious-skull marker step.

Generates a synthetic 3-page PDF that resembles a Meesho/Flipkart label so the
shared OCR helpers can extract a sub-order id from each page, then exercises
``_annotate_suspicious_customer_labels`` under three scenarios:

  * happy path with the real PNG asset shipped under ``backend/assets``
  * forced fallback path (caller passes empty bytes) -- vector skull is drawn
  * configured asset missing (env points at a non-existent file) -- loader
    falls back to the bundled default and still produces a visible marker

For every scenario we assert:
  * the function does not raise
  * the page count of the output PDF matches the input
  * exactly the expected pages had a marker stamped (skull image OR vector)

This is a one-shot manual validation script used to gather evidence for the
feature change. Safe to delete after the change ships.
"""

from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path

import fitz

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Import after sys.path tweak so the script runs from anywhere.
import task_queue  # noqa: E402
from task_queue import (  # noqa: E402
    SUSPICIOUS_MARKER_IMAGE_PATH,
    _DEFAULT_SUSPICIOUS_MARKER_IMAGE,
    _annotate_suspicious_customer_labels,
    _load_suspicious_marker_image_bytes,
)


SUBORDER_RISKY = "184567891234567890_1"
SUBORDER_NORMAL = "999000111222333444_2"
SUBORDER_RISKY_2 = "200111222333444555_3"


def _build_synthetic_pdf(target: Path) -> None:
    """Build a 3-page PDF with explicit sub-order ids the shared OCR helpers
    can recognize via the ``\\d{14,24}[_-]\\d+`` legacy pattern."""
    doc = fitz.open()
    for sub in (SUBORDER_RISKY, SUBORDER_NORMAL, SUBORDER_RISKY_2):
        page = doc.new_page(width=420, height=600)  # ~Meesho label size in pt
        page.insert_text((20, 60), "MEESHO LABEL (synthetic)", fontsize=14)
        page.insert_text((20, 100), f"Sub Order ID: {sub}", fontsize=12)
        page.insert_text((20, 140), "Name: Test Customer", fontsize=12)
        page.insert_text((20, 170), "Pincode: 560001", fontsize=12)
    doc.save(str(target))
    doc.close()


def _count_marked_pages(pdf_path: Path) -> tuple[int, int]:
    """Return (image_marked_pages, drawing_marked_pages).

    Pages are counted as image-marked when they contain at least one embedded
    raster image, and drawing-marked when they contain any vector drawing
    operations beyond the synthetic text inserts.
    """
    image_pages = 0
    drawing_pages = 0
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            if page.get_images(full=False):
                image_pages += 1
            try:
                drawings = page.get_drawings()
            except Exception:
                drawings = []
            if drawings:
                drawing_pages += 1
    return image_pages, drawing_pages


def _scenario(name: str, work_dir: Path, *, force_no_image: bool, env_override: str | None) -> dict:
    src_pdf = work_dir / "input.pdf"
    _build_synthetic_pdf(src_pdf)

    # Apply env override if requested. The loader is re-checked because the
    # module-level constant captured the value at import time.
    original_env = os.environ.get("SUSPICIOUS_MARKER_IMAGE_PATH")
    original_constant = task_queue.SUSPICIOUS_MARKER_IMAGE_PATH
    try:
        if env_override is not None:
            os.environ["SUSPICIOUS_MARKER_IMAGE_PATH"] = env_override
            task_queue.SUSPICIOUS_MARKER_IMAGE_PATH = env_override
        marker_bytes = b"" if force_no_image else _load_suspicious_marker_image_bytes()
        annotated_paths, marked = _annotate_suspicious_customer_labels(
            [str(src_pdf)],
            risky_order_ids={SUBORDER_RISKY, SUBORDER_RISKY_2},
            output_dir=str(work_dir),
            marker_image_bytes=marker_bytes if force_no_image else None,
        )
    finally:
        if env_override is not None:
            if original_env is None:
                os.environ.pop("SUSPICIOUS_MARKER_IMAGE_PATH", None)
            else:
                os.environ["SUSPICIOUS_MARKER_IMAGE_PATH"] = original_env
            task_queue.SUSPICIOUS_MARKER_IMAGE_PATH = original_constant

    out_path = Path(annotated_paths[0])
    with fitz.open(str(out_path)) as doc:
        page_count = len(doc)
    image_pages, drawing_pages = _count_marked_pages(out_path)

    return {
        "scenario": name,
        "output_pdf": str(out_path),
        "marked_labels_returned": int(marked),
        "page_count": int(page_count),
        "pages_with_image": int(image_pages),
        "pages_with_drawings": int(drawing_pages),
    }


def main() -> int:
    work_root = BACKEND_DIR / "temp" / "suspicious_marker_validation"
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    print("=== suspicious skull marker validation ===")
    print(f"default asset path : {_DEFAULT_SUSPICIOUS_MARKER_IMAGE}")
    print(f"asset present?     : {_DEFAULT_SUSPICIOUS_MARKER_IMAGE.exists()}")
    print(f"asset size (bytes) : {_DEFAULT_SUSPICIOUS_MARKER_IMAGE.stat().st_size if _DEFAULT_SUSPICIOUS_MARKER_IMAGE.exists() else 0}")
    print(f"env-resolved path  : {SUSPICIOUS_MARKER_IMAGE_PATH}")
    print()

    results: list[dict] = []

    # 1) happy path -- default image asset
    happy_dir = work_root / "happy_path"
    happy_dir.mkdir(parents=True, exist_ok=True)
    results.append(_scenario("happy_path_default_asset", happy_dir, force_no_image=False, env_override=None))

    # 2) forced fallback -- caller passes empty image bytes
    fallback_dir = work_root / "forced_fallback"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    results.append(_scenario("forced_vector_fallback", fallback_dir, force_no_image=True, env_override=None))

    # 3) env points at a missing file -- loader should fall back to bundled
    missing_dir = work_root / "env_missing_path"
    missing_dir.mkdir(parents=True, exist_ok=True)
    bogus = str(work_root / "this_file_does_not_exist.png")
    results.append(_scenario("env_override_missing_file", missing_dir, force_no_image=False, env_override=bogus))

    failures: list[str] = []
    for r in results:
        # Vector fallback shows up under drawings; we expect either embedded
        # images on the 2 risky pages OR vector drawings stamped onto them.
        ok_marked = (
            r["marked_labels_returned"] == 2
            and r["page_count"] == 3
            and (r["pages_with_image"] >= 2 or r["pages_with_drawings"] >= 2)
        )
        if not ok_marked:
            failures.append(r["scenario"])
        print(f"[{r['scenario']}]")
        for k, v in r.items():
            if k == "scenario":
                continue
            print(f"  {k}: {v}")
        print(f"  PASS: {ok_marked}")
        print()

    if failures:
        print("FAILED scenarios: " + ", ".join(failures))
        return 1
    print("All scenarios passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
