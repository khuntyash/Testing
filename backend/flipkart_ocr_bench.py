"""Benchmark Flipkart label OCR parsing coverage on a directory of sample PDFs.

Usage:
    python flipkart_ocr_bench.py "C:\\Users\\HP\\Downloads\\New folder (5)"

Reports per-field non-empty coverage % and a small accuracy heuristic per field.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fitz

from label_ocr_service import parse_required_fields


FIELDS = [
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
    "Quantity",
    "Payment_Mode",
    "Courier_Partner",
    "Courier_trans_id",
]


def looks_valid(field: str, value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return False
    if field == "Order_id":
        return v.startswith("OD") and v[2:].isdigit() and 14 <= len(v[2:]) <= 22
    if field == "Pincode":
        return len(v) == 6 and v.isdigit()
    if field == "Quantity":
        return v.isdigit() and int(v) >= 1
    if field == "Payment_Mode":
        return v.upper() in {"COD", "PREPAID", "EXCHANGE", "PARTIAL COD"}
    if field == "Courier_trans_id":
        return len(v) >= 8 and v.isalnum() and any(c.isdigit() for c in v)
    if field == "Courier_Partner":
        return len(v) >= 3
    if field == "Pincode":
        return len(v) == 6 and v.isdigit()
    return True


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("folder")
    p.add_argument("--max-pages", type=int, default=0)
    p.add_argument("--dump-failed", type=int, default=0,
                   help="Print N failed-page texts to help debug parsing.")
    args = p.parse_args()

    folder = Path(args.folder)
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {folder}")
        return 1

    counters_filled = {f: 0 for f in FIELDS}
    counters_valid = {f: 0 for f in FIELDS}
    total_pages = 0
    failed_dump_remaining = int(args.dump_failed)

    for pdf in pdfs:
        with fitz.open(str(pdf)) as doc:
            for idx, page in enumerate(doc):
                if args.max_pages and total_pages >= args.max_pages:
                    break
                text = page.get_text("text") or ""
                parsed = parse_required_fields(text)
                total_pages += 1
                for f in FIELDS:
                    val = (parsed.get(f) or "").strip()
                    if val:
                        counters_filled[f] += 1
                        if looks_valid(f, val):
                            counters_valid[f] += 1
                missing_critical = not parsed.get("Sku") or not parsed.get("Quantity")
                if missing_critical and failed_dump_remaining > 0:
                    print("=" * 60)
                    print(f"FAILED PAGE: {pdf.name} page {idx + 1}")
                    print(json.dumps(parsed, indent=2))
                    print("--- TEXT ---")
                    print(text[:1500])
                    failed_dump_remaining -= 1

    print(f"\nTotal pages parsed: {total_pages}\n")
    print(f"{'Field':<22}{'Filled %':>10}{'Valid %':>10}")
    for f in FIELDS:
        filled_pct = (counters_filled[f] / total_pages * 100.0) if total_pages else 0
        valid_pct = (counters_valid[f] / total_pages * 100.0) if total_pages else 0
        print(f"{f:<22}{filled_pct:>9.2f}%{valid_pct:>9.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
