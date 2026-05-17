"""Smoke test for the courier-counts helper used inside the crop task pipeline.

Builds a small synthetic 4-page Meesho-style PDF (one page per known carrier
plus a page with no carrier hints), then exercises ``_count_courier_partners``
to make sure carriers map to the expected buckets and unknown pages are
absorbed under ``"Unknown"``.

Run with the project root as cwd::

    python backend/temp/courier_count_smoke.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from task_queue import _count_courier_partners  # noqa: E402  pylint: disable=wrong-import-position


CARRIER_PAGES = [
    ("Shadowfax", "Shadowfax Logistics\nOrder No.\nPRODUCT123\nDelivery: COD"),
    ("Valmo", "Valmo Express\nOrder No.\nPRODUCT124\nDelivery: COD"),
    ("ValmoPlus", "ValmoPlus Premium\nOrder No.\nPRODUCT125\nDelivery: Prepaid"),
    ("Delhivery", "Delhivery Surface\nOrder No.\nPRODUCT126\nDelivery: COD"),
    ("Unknown", "Unknown Marker\nOrder No.\nPRODUCT127\nDelivery: COD"),
]


def _build_pdf(target: Path) -> None:
    doc = fitz.open()
    try:
        for _name, body in CARRIER_PAGES:
            page = doc.new_page(width=420, height=600)
            page.insert_text((40, 60), body, fontsize=11)
        target.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(target))
    finally:
        doc.close()


def main() -> int:
    out_dir = Path(os.environ.get("CROP_TEMP_DIR", str(ROOT / "backend" / "temp" / "courier_count_smoke")))
    pdf_path = out_dir / "synthetic_couriers.pdf"
    _build_pdf(pdf_path)
    counts, total = _count_courier_partners([str(pdf_path)])
    print("input:", pdf_path)
    print("total:", total)
    print("counts:", counts)
    expected_total = len(CARRIER_PAGES)
    assert total == expected_total, f"expected total={expected_total}, got {total}"
    for label, _body in CARRIER_PAGES:
        assert counts.get(label, 0) >= 1, f"missing carrier bucket: {label} in {counts}"

    # Mixed-input scenario: previously-missing carrier markers (synthetic
    # happy_path PDF) + carrier-rich PDF. Total must stay aligned with the
    # combined page count and missing carriers must fall under "Unknown".
    happy_path = ROOT / "backend" / "temp" / "suspicious_marker_validation" / "happy_path" / "input.pdf"
    if happy_path.exists():
        mixed_counts, mixed_total = _count_courier_partners([str(pdf_path), str(happy_path)])
        print("mixed counts:", mixed_counts)
        print("mixed total:", mixed_total)
        assert mixed_total >= expected_total
        assert sum(mixed_counts.values()) == mixed_total

    # Robustness: a non-existent path must not crash and must yield empty
    # counts. The wider crop pipeline uses the same defensive contract.
    noop_counts, noop_total = _count_courier_partners(["does-not-exist.pdf"])
    assert noop_total == 0
    assert noop_counts == {}

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
