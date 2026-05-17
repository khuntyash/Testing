"""
Flipkart-only PDF crop pipeline.
Uses fixed crop rectangle and SKU sorting for both label-printer and A4 outputs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import os
import re
import tempfile

import fitz


# User-provided fixed crop box.
FLIPKART_LABEL_RECT = fitz.Rect(186, 21, 186 + 224, 21 + 364)
FLIPKART_A4_ROTATE_DEGREES = int(os.getenv("FLIPKART_A4_ROTATE_DEGREES", "0"))


def _emit_progress(progress_callback, pct: int, message: str) -> None:
    if callable(progress_callback):
        progress_callback(max(0, min(100, int(pct))), (message or "").strip())


def _emit_page_progress(
    progress_callback,
    *,
    page_index: int,
    total_pages: int,
    start_pct: int,
    end_pct: int,
    message: str,
) -> None:
    if not callable(progress_callback):
        return
    total = max(1, int(total_pages))
    if page_index + 1 < total and ((page_index + 1) % 40) != 0:
        return
    span = max(0, int(end_pct) - int(start_pct))
    pct = int(start_pct) + int(((page_index + 1) / total) * span)
    _emit_progress(progress_callback, pct, message)


def _clamp_rect_to_page(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    mb = page.mediabox
    x0 = max(rect.x0, mb.x0)
    y0 = max(rect.y0, mb.y0)
    x1 = min(rect.x1, mb.x1)
    y1 = min(rect.y1, mb.y1)
    if x0 < x1 and y0 < y1:
        return fitz.Rect(x0, y0, x1, y1)
    return fitz.Rect(mb.x0, mb.y0, mb.x1, mb.y1)


def crop_shipping_labels(input_file_path: str, output_file_path: str) -> None:
    """Label-printer output: apply fixed crop box to every page."""
    with fitz.open(input_file_path) as doc:
        for page in doc:
            page.set_cropbox(_clamp_rect_to_page(page, FLIPKART_LABEL_RECT))
        doc.save(output_file_path)


def _find_flipkart_anchor_point(page: fitz.Page) -> tuple[float, float]:
    """Pick a safe inside-crop annotation location for a Flipkart label.

    Placement priority:
      1. Just above the top edge of the cropbox, below any barcode, using the
         "Shipping/Customer address" or "QTY" anchors when present.
      2. Fall back to the bottom-left corner of the fixed crop rectangle so
         the stamp is always visible after Flipkart's fixed-rect crop.
    """
    crop_rect = _clamp_rect_to_page(page, FLIPKART_LABEL_RECT)
    for needle in ("Shipping/Customer address", "Shipping / Customer address"):
        hits = page.search_for(needle)
        if hits:
            hit = hits[0]
            x = max(crop_rect.x0 + 3.0, hit.x0)
            y = hit.y0 - 2.0
            if y <= crop_rect.y0 + 6.0:
                y = hit.y1 + 9.0
            if crop_rect.y0 + 6.0 <= y <= crop_rect.y1 - 4.0:
                return float(x), float(y)
    hits = page.search_for("QTY")
    for hit in hits:
        if crop_rect.x0 - 2 <= hit.x0 <= crop_rect.x1 and crop_rect.y0 <= hit.y0 <= crop_rect.y1:
            return float(max(crop_rect.x0 + 3.0, hit.x0)), float(max(crop_rect.y0 + 10.0, hit.y0 - 2.0))
    return float(crop_rect.x0 + 4.0), float(crop_rect.y1 - 14.0)


def annotate_flipkart_labels(
    input_file_path: str,
    output_file_path: str,
    *,
    print_datetime: bool = False,
    custom_message: str = "",
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """Stamp timestamp / custom message onto each Flipkart label page.

    Text is placed inside the Flipkart fixed crop rectangle so it survives
    the downstream fixed-rect crop. No-op when both features are disabled:
    the input PDF is copied bytes-for-bytes into the output path.
    """
    clean_message = (custom_message or "").strip()
    if not print_datetime and not clean_message:
        with fitz.open(input_file_path) as src:
            src.save(output_file_path)
        return

    timestamp_text = ""
    if print_datetime:
        current_time = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        timestamp_text = f"Printed: {current_time}"
    msg_text = f"Msg: {clean_message[:80]}" if clean_message else ""

    with fitz.open(input_file_path) as doc:
        total_pages = len(doc)
        for page in doc:
            try:
                base_x, base_y = _find_flipkart_anchor_point(page)
            except Exception:
                crop_rect = _clamp_rect_to_page(page, FLIPKART_LABEL_RECT)
                base_x = float(crop_rect.x0 + 4.0)
                base_y = float(crop_rect.y1 - 14.0)

            line_index = 0
            if timestamp_text:
                try:
                    page.insert_text(
                        fitz.Point(base_x, base_y + (line_index * 9)),
                        timestamp_text,
                        fontsize=7.0,
                        fontname="helv",
                        color=(0.0, 0.0, 0.0),
                    )
                    line_index += 1
                except Exception:
                    pass
            if msg_text:
                try:
                    page.insert_text(
                        fitz.Point(base_x, base_y + (line_index * 9)),
                        msg_text,
                        fontsize=6.8,
                        fontname="helv",
                        color=(0.0, 0.0, 0.0),
                    )
                except Exception:
                    pass

            _emit_page_progress(
                progress_callback,
                page_index=page.number,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Annotating Flipkart labels",
            )
        doc.save(output_file_path)


def extract_sku(text: str) -> str:
    """
    Extract SKU from Flipkart invoice text.
    Primary pattern uses the QTY row; fallback handles shifted table layout.
    When both regex paths miss, fall back to the OCR parser which tolerates
    wrapped SKUs and noisier layouts before declaring the SKU unknown.
    """
    text = text or ""
    match = re.search(r"QTY\s*\n\d+\s+([A-Za-z0-9\-_]+)\s*\|", text)
    if match:
        return match.group(1).strip()

    fallback = re.search(
        r"SKU ID\s*\|\s*Description\s*\n.*?\n(?:QTY\n)?(\d+\s+)?([A-Za-z0-9\-_]+)\s*\|",
        text,
        re.DOTALL,
    )
    if fallback:
        return fallback.group(2).strip()

    # Last-resort: reuse the structured Flipkart parser. Imported lazily to
    # keep this module import-cheap and avoid any circular-import risk.
    try:
        from label_ocr_service import parse_required_fields

        parsed = parse_required_fields(text) or {}
        ocr_sku = (parsed.get("Sku") or "").strip()
        if ocr_sku:
            return ocr_sku
    except Exception:
        pass

    return "Unknown_SKU"


def extract_total_qty(text: str) -> int:
    """
    Extract total invoice quantity from `TOTAL QTY: X`.
    Defaults to 1 when quantity cannot be confidently parsed.
    """
    text = text or ""
    match = re.search(r"TOTAL\s+QTY:\s*(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 1


def sort_by_sku_and_crop(
    input_file_path: str,
    output_file_path: str,
    *,
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """
    Apply Flipkart crop to each page, then reorder all pages by SKU (A-Z).
    """
    sku_pages: dict[str, list[int]] = defaultdict(list)

    with fitz.open(input_file_path) as doc:
        total_pages = len(doc)
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            sku = extract_sku(text)
            page.set_cropbox(_clamp_rect_to_page(page, FLIPKART_LABEL_RECT))
            sku_pages[sku].append(page_num)
            _emit_page_progress(
                progress_callback,
                page_index=page_num,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Sorting pages by SKU",
            )

        final_page_sequence: list[int] = []
        for sku in sorted(sku_pages.keys()):
            final_page_sequence.extend(sku_pages[sku])

        if final_page_sequence and final_page_sequence != list(range(len(doc))):
            doc.select(final_page_sequence)
        doc.save(output_file_path)


def sort_flipkart_by_sku_and_qty(
    input_file_path: str,
    output_file_path: str,
    *,
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """
    Flipkart combo mode:
    - Crop all pages with Flipkart fixed rectangle
    - Sort by SKU
    - Keep single-qty pages first, multi-qty pages at bottom
    """
    single_qty_pages: dict[str, list[int]] = defaultdict(list)
    multi_qty_pages: dict[str, list[int]] = defaultdict(list)

    with fitz.open(input_file_path) as doc:
        total_pages = len(doc)
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            sku = extract_sku(text)
            qty = extract_total_qty(text)
            page.set_cropbox(_clamp_rect_to_page(page, FLIPKART_LABEL_RECT))

            if qty > 1:
                multi_qty_pages[sku].append(page_num)
            else:
                single_qty_pages[sku].append(page_num)
            _emit_page_progress(
                progress_callback,
                page_index=page_num,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Grouping single and multi-quantity labels",
            )

        final_page_sequence: list[int] = []
        for sku in sorted(single_qty_pages.keys()):
            final_page_sequence.extend(single_qty_pages[sku])
        for sku in sorted(multi_qty_pages.keys()):
            final_page_sequence.extend(multi_qty_pages[sku])

        if final_page_sequence and final_page_sequence != list(range(len(doc))):
            doc.select(final_page_sequence)
        doc.save(output_file_path)


def sort_full_invoice_by_sku(
    input_file_path: str,
    output_file_path: str,
    *,
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """Keep full invoice pages and reorder only by SKU."""
    sku_pages: dict[str, list[int]] = defaultdict(list)
    with fitz.open(input_file_path) as doc:
        total_pages = len(doc)
        for page_num in range(total_pages):
            text = doc[page_num].get_text("text")
            sku_pages[extract_sku(text)].append(page_num)
            _emit_page_progress(
                progress_callback,
                page_index=page_num,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Sorting full invoice pages by SKU",
            )
        final_page_sequence: list[int] = []
        for sku in sorted(sku_pages.keys()):
            final_page_sequence.extend(sku_pages[sku])
        if final_page_sequence and final_page_sequence != list(range(total_pages)):
            doc.select(final_page_sequence)
        doc.save(output_file_path)


def sort_full_invoice_by_sku_and_qty(
    input_file_path: str,
    output_file_path: str,
    *,
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """Keep full invoices and sort by SKU with single-qty first."""
    single_qty_pages: dict[str, list[int]] = defaultdict(list)
    multi_qty_pages: dict[str, list[int]] = defaultdict(list)
    with fitz.open(input_file_path) as doc:
        total_pages = len(doc)
        for page_num in range(total_pages):
            text = doc[page_num].get_text("text")
            sku = extract_sku(text)
            qty = extract_total_qty(text)
            if qty > 1:
                multi_qty_pages[sku].append(page_num)
            else:
                single_qty_pages[sku].append(page_num)
            _emit_page_progress(
                progress_callback,
                page_index=page_num,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Grouping full invoices by quantity",
            )
        final_page_sequence: list[int] = []
        for sku in sorted(single_qty_pages.keys()):
            final_page_sequence.extend(single_qty_pages[sku])
        for sku in sorted(multi_qty_pages.keys()):
            final_page_sequence.extend(multi_qty_pages[sku])
        if final_page_sequence and final_page_sequence != list(range(total_pages)):
            doc.select(final_page_sequence)
        doc.save(output_file_path)


def crop_shipping_labels_to_a4(
    input_file_path: str,
    output_file_path: str,
    *,
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """
    A4 output: place cropped labels 4 per page (2x2 grid), keeping source order.
    """
    with fitz.open(input_file_path) as src_doc:
        rotate_degrees = _normalize_quadrant_rotation(FLIPKART_A4_ROTATE_DEGREES)
        total_pages = len(src_doc)
        with fitz.open() as out_doc:
            a4_width = 595.0
            a4_height = 842.0
            w2 = a4_width / 2.0
            h2 = a4_height / 2.0
            quadrants = [
                fitz.Rect(0, 0, w2, h2),
                fitz.Rect(w2, 0, a4_width, h2),
                fitz.Rect(0, h2, w2, a4_height),
                fitz.Rect(w2, h2, a4_width, a4_height),
            ]

            out_page = None
            for i, page in enumerate(src_doc):
                quad_index = i % 4
                if quad_index == 0:
                    out_page = out_doc.new_page(width=a4_width, height=a4_height)
                out_page.show_pdf_page(
                    rect=quadrants[quad_index],
                    docsrc=src_doc,
                    pno=page.number,
                    clip=_clamp_rect_to_page(page, FLIPKART_LABEL_RECT),
                    rotate=rotate_degrees,
                )
                _emit_page_progress(
                    progress_callback,
                    page_index=i,
                    total_pages=total_pages,
                    start_pct=start_pct,
                    end_pct=end_pct,
                    message="Compiling A4 output",
                )

            out_doc.save(output_file_path)


def _normalize_quadrant_rotation(degrees: int) -> int:
    normalized = int(degrees) % 360
    if normalized not in (0, 90, 180, 270):
        raise ValueError(f"Unsupported A4 rotate degrees: {degrees}")
    return normalized


def process_uploaded_paths(
    input_paths: list[str],
    output_pdf: str,
    *,
    layout: str,
    sort_by: str = "sku",
    multi_order_bottom: bool = False,
    print_datetime: bool = False,
    custom_message: str = "",
    progress_callback=None,
) -> None:
    """
    Flipkart processing entrypoint.
    - Sort by SKU
    - Fixed crop rectangle
    - Optional annotation (print_datetime + custom_message) applied before crop
    """
    if not input_paths:
        raise ValueError("No input PDFs")

    clean_message = (custom_message or "").strip()
    annotation_requested = bool(print_datetime or clean_message)

    chain_tmps: list[str] = []
    merged_input = fitz.open()
    try:
        _emit_progress(progress_callback, 1, "Merging uploaded PDFs")
        for p in input_paths:
            with fitz.open(p) as d:
                merged_input.insert_pdf(d)
        # Save merged source to a temp path for pipeline functions.
        merged_tmp = fitz.open()
        try:
            merged_tmp.insert_pdf(merged_input)
            fh = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            fh.close()
            merged_tmp.save(fh.name)
            chain_tmps.append(fh.name)
            work_path = fh.name

            if annotation_requested:
                _emit_progress(progress_callback, 4, "Applying Flipkart label annotations")
                annotated = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                annotated.close()
                chain_tmps.append(annotated.name)
                try:
                    annotate_flipkart_labels(
                        work_path,
                        annotated.name,
                        print_datetime=bool(print_datetime),
                        custom_message=clean_message,
                        progress_callback=progress_callback,
                        start_pct=4,
                        end_pct=8,
                    )
                    work_path = annotated.name
                except Exception:
                    # Defensive: never fail the whole crop because annotation
                    # placement raised. Fall through with the un-annotated PDF.
                    pass

            sorted_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            sorted_tmp.close()
            try:
                clean_sort = (sort_by or "sku").strip().lower()
                # UI label "Sold by" maps to order_id sort token. Flipkart
                # labels do not expose reliable seller-group sorting yet, so
                # keep behavior deterministic by aliasing to the stable SKU sort.
                if clean_sort == "order_id":
                    clean_sort = "sku"
                if clean_sort != "sku":
                    raise ValueError(f"Unsupported Flipkart sort_by: {sort_by}")
                if (layout or "label_printer").strip() == "keep_invoice":
                    if multi_order_bottom:
                        sort_full_invoice_by_sku_and_qty(
                            work_path,
                            output_pdf,
                            progress_callback=progress_callback,
                            start_pct=8,
                            end_pct=99,
                        )
                    else:
                        sort_full_invoice_by_sku(
                            work_path,
                            output_pdf,
                            progress_callback=progress_callback,
                            start_pct=8,
                            end_pct=99,
                        )
                else:
                    if multi_order_bottom:
                        sort_flipkart_by_sku_and_qty(
                            work_path,
                            sorted_tmp.name,
                            progress_callback=progress_callback,
                            start_pct=8,
                            end_pct=82,
                        )
                    else:
                        sort_by_sku_and_crop(
                            work_path,
                            sorted_tmp.name,
                            progress_callback=progress_callback,
                            start_pct=8,
                            end_pct=82,
                        )
                    _emit_progress(progress_callback, 95, "Finalizing output PDF")
                    os.replace(sorted_tmp.name, output_pdf)
            finally:
                try:
                    os.unlink(sorted_tmp.name)
                except OSError:
                    pass
        finally:
            merged_tmp.close()
    finally:
        merged_input.close()
        for p in chain_tmps:
            try:
                os.unlink(p)
            except OSError:
                pass

