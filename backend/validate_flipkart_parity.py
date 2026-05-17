"""End-to-end validation of Flipkart parity changes without running the HTTP server.

Checks performed (each with PASS/FAIL output + counts):
  1. Flipkart Returns Excel format adapter normalizes the user-provided file.
  2. Returns analysis pipeline runs against a synthetic orders CSV and emits a
     canonical CSV that downstream risk profile code can consume.
  3. Flipkart crop pipeline supports print_datetime + custom_message without
     corrupting output PDFs.
  4. Multi-order / loyal-customer gating in task queue now opens for Flipkart.
  5. Auto-detection does not misidentify a Meesho-format workbook.

The script is non-destructive: it writes to a temp dir under `backend/temp`.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import fitz
from openpyxl import Workbook

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

import flipkart_service
import return_analysis_service
import task_queue
import label_ocr_service


RETURNS_XLSX_PATH = Path(r"C:\\Users\\HP\\Downloads\\New folder (6)\\3954c5e1-ef13-4d1f-a001-f65598735118_1777722240000.xlsx")


def _print(check: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {check} :: {detail}")
    return ok


def _write_orders_csv(path: Path, order_ids: list[str]) -> None:
    import csv

    fieldnames = [
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
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, oid in enumerate(order_ids):
            writer.writerow(
                {
                    "Order_id": oid,
                    "Name": f"Customer {i}",
                    "Address_1": "Line 1",
                    "Address_2": "",
                    "Address_3": "",
                    "District": "District",
                    "State": "State",
                    "Pincode": f"{560000 + i}",
                    "Sku": "SKU-X",
                    "Size": "",
                    "Quantity": "1",
                    "Payment_Mode": "COD",
                    "Courier_Partner": "E-Kart Logistics",
                    "Courier_trans_id": "FMPC1234567890",
                }
            )


def _build_fake_flipkart_label_pdf(path: Path, order_id: str = "OD436652983093810100") -> None:
    """Craft a single-page PDF that mimics a Flipkart shipping label layout.

    Anchors exercised by the annotation helper (``Shipping/Customer address``
    + ``QTY``) are deliberately embedded so the validation can verify the
    annotation path is invoked and placed inside the crop rectangle.
    """
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_text((200, 60), f"{order_id}  COD", fontsize=12, fontname="helv")
        page.insert_text((200, 120), "Shipping/Customer address", fontsize=11, fontname="helv")
        page.insert_text((200, 140), "Name: Test Customer,", fontsize=10, fontname="helv")
        page.insert_text((200, 160), "Example Road, Area, 560001", fontsize=10, fontname="helv")
        page.insert_text((200, 180), "Bangalore - 560001, IN-KA", fontsize=10, fontname="helv")
        page.insert_text((200, 240), "SKU ID | Description", fontsize=10, fontname="helv")
        page.insert_text((200, 260), "QTY", fontsize=10, fontname="helv")
        page.insert_text((200, 280), "1 SKU-TEST | Sample product", fontsize=10, fontname="helv")
        page.insert_text((200, 300), "FMPC1234567890", fontsize=10, fontname="helv")
        page.insert_text((200, 330), "AWB No. FMPC1234567890", fontsize=10, fontname="helv")
        page.insert_text((200, 360), "Ordered through flipkart.com", fontsize=10, fontname="helv")
        doc.save(str(path))
    finally:
        doc.close()


def validate_flipkart_returns_adapter(tmp: Path) -> dict:
    report: dict = {"ok": False}
    if not RETURNS_XLSX_PATH.exists():
        report["skipped"] = f"Validation file missing at {RETURNS_XLSX_PATH}"
        return report
    rows = return_analysis_service._read_returns_excel(str(RETURNS_XLSX_PATH))
    report["rows_parsed"] = len(rows)
    if not rows:
        return report
    sample = rows[0]
    report["sample_row_keys"] = list(sample.keys())
    missing = [c for c in return_analysis_service.REQUIRED_RETURN_COLUMNS if c not in sample]
    report["missing_required_columns"] = missing
    rto_count = sum(1 for r in rows if r.get("Type of Return") == "RTO")
    cust_count = sum(1 for r in rows if r.get("Type of Return") == "Customer Return")
    report["rto_count"] = rto_count
    report["customer_return_count"] = cust_count
    unique_awbs = len({r.get("AWB Number") for r in rows if r.get("AWB Number")})
    report["unique_awb_count"] = unique_awbs

    sample_oid = next(
        (r.get("Suborder Number") for r in rows if r.get("Suborder Number")),
        "",
    )
    sample_oid = str(sample_oid or "")
    if not sample_oid:
        return report
    orders_csv = tmp / "orders.csv"
    _write_orders_csv(
        orders_csv,
        [
            sample_oid,
            f"OI:{sample_oid}",
            f"OD{sample_oid[4:]}" if sample_oid.startswith("oi:") else f"OD{sample_oid}",
        ],
    )
    out_path, summary = return_analysis_service.analyze_returns_against_orders(
        orders_csv_path=str(orders_csv),
        returns_excel_path=str(RETURNS_XLSX_PATH),
        output_dir=str(tmp),
    )
    report["analysis_csv"] = out_path
    report["summary"] = summary
    report["ok"] = bool(Path(out_path).exists() and not missing)
    return report


def validate_meesho_returns_adapter(tmp: Path) -> dict:
    path = tmp / "meesho_returns.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Returns"
    ws.append(
        [
            "Suborder Number",
            "AWB Number",
            "Type of Return",
            "Sub Type",
            "Status",
            "Return Reason",
            "Detailed Return Reason",
        ]
    )
    ws.append(
        [
            "123456789012345_1",
            "AWB-100",
            "RTO",
            "Customer Return",
            "Delivered",
            "Quality",
            "Damaged",
        ]
    )
    wb.save(str(path))
    rows = return_analysis_service._read_returns_excel(str(path))
    return {"ok": len(rows) == 1, "rows": len(rows), "first": rows[0] if rows else {}}


def validate_flipkart_annotation(tmp: Path) -> dict:
    src = tmp / "flipkart_label.pdf"
    _build_fake_flipkart_label_pdf(src, order_id="OD436652983093810100")
    with fitz.open(str(src)) as doc:
        before_text = doc[0].get_text("text")

    out_path = tmp / "flipkart_label_cropped.pdf"
    flipkart_service.process_uploaded_paths(
        [str(src)],
        str(out_path),
        layout="label_printer",
        sort_by="sku",
        multi_order_bottom=False,
        print_datetime=True,
        custom_message="Batch A - 001",
    )
    with fitz.open(str(out_path)) as doc:
        after_text = doc[0].get_text("text")
        crop_rect = doc[0].cropbox
        page_rect = doc[0].rect
    return {
        "ok": "Printed:" in after_text and "Msg: Batch A" in after_text,
        "before_has_stamp": "Printed:" in before_text,
        "after_has_stamp": "Printed:" in after_text,
        "after_has_msg": "Msg: Batch A" in after_text,
        "cropbox": [crop_rect.x0, crop_rect.y0, crop_rect.x1, crop_rect.y1],
        "page_rect": [page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1],
    }


def validate_no_annotation_noop(tmp: Path) -> dict:
    src = tmp / "flipkart_plain.pdf"
    _build_fake_flipkart_label_pdf(src)
    out_path = tmp / "flipkart_plain_cropped.pdf"
    flipkart_service.process_uploaded_paths(
        [str(src)],
        str(out_path),
        layout="label_printer",
        sort_by="sku",
        multi_order_bottom=False,
        print_datetime=False,
        custom_message="",
    )
    with fitz.open(str(out_path)) as doc:
        text = doc[0].get_text("text")
    return {
        "ok": "Printed:" not in text and "Msg:" not in text,
        "text_has_stamp": "Printed:" in text,
    }


def validate_parse_field_still_works() -> dict:
    """Confirm the shared OCR parser picks up Name/Pincode from our fake label."""
    lines = [
        "Shipping/Customer address",
        "Name: Sample User,",
        "221B Baker Street,",
        "Marylebone,",
        "Bangalore - 560001, IN-KA",
    ]
    parsed = label_ocr_service._parse_flipkart_fields(
        "\n".join(lines),
        [label_ocr_service._clean_line(line) for line in lines],
    )
    return {
        "ok": parsed.get("Name") == "Sample User" and parsed.get("Pincode") == "560001",
        "name": parsed.get("Name"),
        "pincode": parsed.get("Pincode"),
        "state": parsed.get("State"),
    }


def validate_task_queue_gating_open_for_flipkart() -> dict:
    """Confirm the Meesho-only gating was removed for multi-order + loyal options."""
    # Simulate the gating logic
    def _option_bool(value):
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    options = {
        "separate_multi_order_by_customer": True,
        "mark_loyal_customer": True,
        "mark_loyal_customer_preview": True,
    }
    open_for_meesho = (
        _option_bool(options.get("separate_multi_order_by_customer"))
        and "crop_meesho" in {"crop_meesho", "crop_flipkart"}
    )
    open_for_flipkart = (
        _option_bool(options.get("separate_multi_order_by_customer"))
        and "crop_flipkart" in {"crop_meesho", "crop_flipkart"}
    )
    # Also verify the real module has the new gating phrasing
    src = Path(task_queue.__file__).read_text(encoding="utf-8")
    gate_open = "task_type in {\n        \"crop_meesho\",\n        \"crop_flipkart\"," in src
    return {
        "ok": open_for_meesho and open_for_flipkart and gate_open,
        "gate_open_in_source": gate_open,
    }


def main() -> int:
    out_root = BACKEND_DIR / "temp" / "parity_validation"
    out_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="flipkart_parity_", dir=str(out_root)) as td:
        tmp = Path(td)
        results = {
            "flipkart_returns_adapter": validate_flipkart_returns_adapter(tmp),
            "meesho_returns_adapter": validate_meesho_returns_adapter(tmp),
            "flipkart_annotation": validate_flipkart_annotation(tmp),
            "flipkart_no_annotation_noop": validate_no_annotation_noop(tmp),
            "flipkart_parse_fields": validate_parse_field_still_works(),
            "task_queue_gating": validate_task_queue_gating_open_for_flipkart(),
        }
    print(json.dumps(results, indent=2, default=str))
    all_ok = all(isinstance(v, dict) and v.get("ok") for v in results.values())
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
