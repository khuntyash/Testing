"""
Meesho-only PDF pipelines: maps UI sort/layout to existing crop modules.
"""
from __future__ import annotations

import os
import re
import tempfile
from collections import defaultdict, deque
from datetime import datetime
import fitz

from label_canvas_fit import compose_pdf_to_3x5_canvas
from partner_crop import detect_partner_for_page, get_clamped_partner_label_rect
from pdf_sort_delivery import sort_and_crop_labels as delivery_label_sort_crop
from pdf_sort_sku import sort_and_crop_by_sku as sku_label_sort_crop

QTY_REGEX = re.compile(r"(?:\n|^)(\d+)[\s\n]+Rs\.?\s*\d+(?:\.\d{2})?", re.IGNORECASE)
QTY_FALLBACK_REGEX = re.compile(r"Qty\s*\n(\d+)", re.IGNORECASE)
ORDER_ID_REGEX = re.compile(
    r"(?:sub[\s\-]*order[\s\-]*id|order[\s\-]*id)\s*[:#]?\s*([A-Za-z0-9\-_]+)",
    re.IGNORECASE,
)
SKU_REGEX = re.compile(
    r"(?:sku(?:\s*id)?)\s*[:#]?\s*([A-Za-z0-9\-_]+)",
    re.IGNORECASE,
)
MEESHO_LABEL_ROTATE_DEGREES = int(os.getenv("MEESHO_LABEL_ROTATE_DEGREES", "0"))
MEESHO_LABEL_OUTPUT_MODE = (os.getenv("MEESHO_LABEL_OUTPUT_MODE", "reference_crop") or "reference_crop").strip().lower()
MEESHO_REFERENCE_MATCH_PDF = (os.getenv("MEESHO_REFERENCE_MATCH_PDF", "") or "").strip()
MEESHO_REFERENCE_APPEND_UNMATCHED = (os.getenv("MEESHO_REFERENCE_APPEND_UNMATCHED", "0") or "").strip().lower() in ("1", "true", "yes")
MEESHO_PROGRESS_EVERY_PAGES = max(1, int(os.getenv("MEESHO_PROGRESS_EVERY_PAGES", "10")))


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
    if page_index + 1 < total and ((page_index + 1) % MEESHO_PROGRESS_EVERY_PAGES) != 0:
        return
    span = max(0, int(end_pct) - int(start_pct))
    pct = int(start_pct) + int(((page_index + 1) / total) * span)
    _emit_progress(progress_callback, pct, message)


def merge_pdf_files(input_paths: list[str], output_path: str) -> None:
    merged = fitz.open()
    try:
        for p in input_paths:
            with fitz.open(p) as doc:
                merged.insert_pdf(doc)
        merged.save(output_path)
    finally:
        merged.close()


def reorder_pdf_multi_qty_last(
    input_path: str,
    output_path: str,
    *,
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """Regex quantity detection + in-place reorder: singles first, multi-qty pages last."""
    def extract_quantity(full_text: str) -> int:
        matches = QTY_REGEX.findall(full_text or "")
        if matches:
            return sum(int(qty) for qty in matches)
        fallback = QTY_FALLBACK_REGEX.search(full_text or "")
        if fallback:
            return int(fallback.group(1))
        return 1

    with fitz.open(input_path) as doc:
        total_pages = len(doc)
        single_qty_pages: list[int] = []
        multi_qty_pages: list[int] = []

        for page_num in range(len(doc)):
            # Quantity table is usually in the lower region; clipping reduces extraction cost.
            page = doc[page_num]
            rect = page.rect
            text = page.get_text("text", clip=fitz.Rect(rect.x0, rect.y0 + rect.height * 0.35, rect.x1, rect.y1))
            qty = extract_quantity(text)
            if qty > 1:
                multi_qty_pages.append(page_num)
            else:
                single_qty_pages.append(page_num)
            _emit_page_progress(
                progress_callback,
                page_index=page_num,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Reading pages for quantity order",
            )

        final_page_sequence = single_qty_pages + multi_qty_pages
        if final_page_sequence != list(range(len(doc))):
            # One-shot reordering is much faster than per-page insert_pdf loops.
            doc.select(final_page_sequence)
        doc.save(output_path)


def crop_labels_default_order(
    input_file_path: str,
    output_file_path: str,
    *,
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """Default / Order ID: same page order, per-partner label crop."""
    label_hint_tokens = (
        "customer address",
        "product details",
        "order no.",
        "sub order id",
        "meesho",
        "delhivery",
        "shadowfax",
        "valmo",
    )
    with fitz.open(input_file_path) as doc:
        total_pages = len(doc)
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = (page.get_text("text", clip=fitz.Rect(page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y0 + 520)) or "").lower()
            # Preserve non-label appendix pages (summary / statements) as-is.
            if not any(token in page_text for token in label_hint_tokens):
                _emit_page_progress(
                    progress_callback,
                    page_index=page_num,
                    total_pages=total_pages,
                    start_pct=start_pct,
                    end_pct=end_pct,
                    message="Keeping non-label pages unchanged",
                )
                continue
            partner = detect_partner_for_page(page)
            label_rect = get_clamped_partner_label_rect(page, partner)
            page.set_cropbox(label_rect)
            _emit_page_progress(
                progress_callback,
                page_index=page_num,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Finding label edges and cropping pages",
            )
        doc.save(output_file_path)


def rotate_pdf_90_clockwise(input_file_path: str, output_file_path: str) -> None:
    """Rotate every output page by +90° (clockwise) for vertical roll printers."""
    with fitz.open(input_file_path) as doc:
        for page in doc:
            page.set_rotation((page.rotation + 90) % 360)
        doc.save(output_file_path)


def rotate_pdf_90_clockwise_inplace(
    file_path: str,
    *,
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """Rotate pages +90° and save incrementally in the same file."""
    with fitz.open(file_path) as doc:
        total_pages = len(doc)
        for page in doc:
            page.set_rotation((page.rotation + 90) % 360)
            _emit_page_progress(
                progress_callback,
                page_index=page.number,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Applying print layout rotation",
            )
        doc.saveIncr()


def rotate_pdf_by_degrees_inplace(
    file_path: str,
    degrees: int,
    *,
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """Rotate pages by allowed degree steps (0/90/180/270)."""
    normalized = int(degrees) % 360
    if normalized == 0:
        return
    if normalized not in (90, 180, 270):
        raise ValueError(f"Unsupported rotation: {degrees}")
    with fitz.open(file_path) as doc:
        total_pages = len(doc)
        for page in doc:
            page.set_rotation((page.rotation + normalized) % 360)
            _emit_page_progress(
                progress_callback,
                page_index=page.number,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Applying print layout rotation",
            )
        doc.saveIncr()


def identify_delivery_partner(text: str) -> str:
    """Identifies the delivery partner from raw page text."""
    text = (text or "").lower()
    if "shadowfax" in text:
        return "Shadowfax"
    elif "xpressbees" in text or "xpress bees" in text:
        return "Xpress Bees"
    elif "valmoplus" in text or "valmo plus" in text:
        return "ValmoPlus"
    elif "valmo" in text:
        return "Valmo"
    elif "delhivery" in text:
        return "Delhivery"
    else:
        return "Unknown"


def _sort_key_from_text(text: str, sort_by: str) -> str:
    clean_text = text or ""
    mode = (sort_by or "order_id").strip().lower()
    if mode == "delivery":
        return identify_delivery_partner(clean_text).lower()
    if mode == "sku":
        m = SKU_REGEX.search(clean_text)
        return (m.group(1).strip().lower() if m else "~unknown")
    if mode == "order_id":
        m = ORDER_ID_REGEX.search(clean_text)
        return (m.group(1).strip().lower() if m else "~unknown")
    raise ValueError(f"Unsupported sort_by: {sort_by}")


def _reference_page_signature(page: fitz.Page) -> str:
    text = re.sub(r"\s+", " ", (page.get_text("text") or "").strip())
    prefix = text[:360]
    customer = ""
    lines = [ln.strip() for ln in (page.get_text("text") or "").splitlines() if ln.strip()]
    for idx, line in enumerate(lines):
        if line.lower().startswith("customer address"):
            if idx + 1 < len(lines):
                customer = lines[idx + 1].lower()
            break
    order_match = ORDER_ID_REGEX.search(text)
    order_id = (order_match.group(1).strip().lower() if order_match else "")
    return f"{order_id}|{customer}|{prefix}"


def align_output_to_reference(
    generated_pdf_path: str,
    reference_pdf_path: str,
    *,
    append_unmatched_reference_pages: bool = False,
) -> None:
    """
    Optional parity pass: reorder generated pages to match reference sequence by
    semantic text signature, and optionally append unmatched reference pages.
    Disabled by default and only used when a reference path is provided.
    """
    if not reference_pdf_path or not os.path.exists(reference_pdf_path):
        return
    with fitz.open(generated_pdf_path) as gen_doc, fitz.open(reference_pdf_path) as ref_doc:
        if not gen_doc or not ref_doc:
            return
        gen_sig_to_indexes: dict[str, deque[int]] = defaultdict(deque)
        for idx in range(len(gen_doc)):
            gen_sig_to_indexes[_reference_page_signature(gen_doc[idx])].append(idx)

        ordered_indexes: list[int] = []
        unmatched_reference_indexes: list[int] = []
        for ref_idx in range(len(ref_doc)):
            sig = _reference_page_signature(ref_doc[ref_idx])
            if gen_sig_to_indexes[sig]:
                ordered_indexes.append(gen_sig_to_indexes[sig].popleft())
            else:
                unmatched_reference_indexes.append(ref_idx)

        remaining_indexes: list[int] = []
        for queue in gen_sig_to_indexes.values():
            while queue:
                remaining_indexes.append(queue.popleft())
        if remaining_indexes:
            ordered_indexes.extend(sorted(remaining_indexes))

        if ordered_indexes and ordered_indexes != list(range(len(gen_doc))):
            gen_doc.select(ordered_indexes)

        if append_unmatched_reference_pages and unmatched_reference_indexes:
            for ref_idx in unmatched_reference_indexes:
                gen_doc.insert_pdf(ref_doc, from_page=ref_idx, to_page=ref_idx)
        gen_doc.saveIncr()


def sort_full_invoice_pages(
    input_file_path: str,
    output_file_path: str,
    *,
    sort_by: str,
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """Keep invoice pages intact and only reorder by selected key."""
    with fitz.open(input_file_path) as doc:
        total_pages = len(doc)
        keyed_pages: list[tuple[str, int]] = []
        for page_num in range(total_pages):
            text = doc[page_num].get_text("text")
            keyed_pages.append((_sort_key_from_text(text, sort_by), page_num))
            _emit_page_progress(
                progress_callback,
                page_index=page_num,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Sorting invoice pages",
            )
        keyed_pages.sort(key=lambda item: (item[0], item[1]))
        final_page_sequence = [pno for _, pno in keyed_pages]
        if final_page_sequence and final_page_sequence != list(range(total_pages)):
            doc.select(final_page_sequence)
        doc.save(output_file_path)


def add_timestamp_by_partner(
    input_file_path: str,
    output_file_path: str,
    *,
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """
    Place timestamp just after 'Product Details' text on each page.
    Falls back to bottom-left when anchor text is unavailable.
    """
    current_time = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
    stamp_text = f"Printed: {current_time}"

    with fitz.open(input_file_path) as doc:
        total_pages = len(doc)
        for page in doc:
            found_areas = page.search_for("Product Details")
            if found_areas:
                target_rect = found_areas[0]
                page.insert_text(
                    fitz.Point(target_rect.x1 + 12, target_rect.y0 + 12),
                    stamp_text,
                    fontsize=9.0,
                    fontname="helv",
                    color=(0.0, 0.0, 0.0),
                )
            else:
                rect = page.rect
                page.insert_text(
                    (rect.x0 + 4, rect.y1 - 20),
                    stamp_text,
                    fontsize=9.0,
                    fontname="helv",
                    color=(0.25, 0.25, 0.25),
                )
            _emit_page_progress(
                progress_callback,
                page_index=page.number,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Stamping print time on labels",
            )
        doc.save(output_file_path)


def annotate_beside_product_details(
    input_file_path: str,
    output_file_path: str,
    *,
    print_datetime: bool = False,
    custom_message: str = "",
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
) -> None:
    """
    Single-pass annotation near 'Product Details' (timestamp + optional custom message).
    Keeps behavior while avoiding multiple read/write passes for large PDFs.
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
    msg_text = f"Message: {clean_message[:120]}" if clean_message else ""

    with fitz.open(input_file_path) as doc:
        total_pages = len(doc)
        for page in doc:
            found_areas = page.search_for("Product Details")
            if found_areas:
                target_rect = found_areas[0]
                base_x = target_rect.x1 + 12
                base_y = target_rect.y0 + 12
            else:
                rect = page.rect
                base_x = rect.x0 + 4
                base_y = rect.y1 - 20

            line_index = 0
            if timestamp_text:
                page.insert_text(
                    fitz.Point(base_x, base_y + (line_index * 10)),
                    timestamp_text,
                    fontsize=9.0,
                    fontname="helv",
                    color=(0.0, 0.0, 0.0),
                )
                line_index += 1
            if msg_text:
                page.insert_text(
                    fitz.Point(base_x, base_y + (line_index * 10)),
                    msg_text,
                    fontsize=8.2,
                    fontname="helv",
                    color=(0.0, 0.0, 0.0),
                )

            _emit_page_progress(
                progress_callback,
                page_index=page.number,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=end_pct,
                message="Annotating labels",
            )
        doc.save(output_file_path)


def add_custom_message_beside_product_details(
    input_file_path: str, output_file_path: str, custom_message: str
) -> None:
    """
    Adds a custom line near 'Product Details' on each page before crop.
    Falls back to bottom-left if phrase missing.
    """
    annotate_beside_product_details(
        input_file_path,
        output_file_path,
        print_datetime=False,
        custom_message=custom_message,
    )


def run_meesho_pipeline(
    input_pdf: str,
    output_pdf: str,
    *,
    sort_by: str,
    layout: str,
    multi_order_bottom: bool = False,
    print_datetime: bool = False,
    custom_message: str = "",
    progress_callback=None,
) -> None:
    """
    sort_by: order_id | sku | delivery
    layout: label_printer | keep_invoice
    """
    sort_by = (sort_by or "order_id").strip()
    layout = (layout or "label_printer").strip()

    chain_tmps: list[str] = []
    work_pdf = input_pdf
    _emit_progress(progress_callback, 1, "Preparing files")
    if print_datetime or (custom_message or "").strip():
        fh = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        fh.close()
        _emit_progress(progress_callback, 3, "Applying label annotations")
        annotate_beside_product_details(
            work_pdf,
            fh.name,
            print_datetime=print_datetime,
            custom_message=custom_message,
            progress_callback=progress_callback,
            start_pct=3,
            end_pct=24,
        )
        chain_tmps.append(fh.name)
        work_pdf = fh.name
    if multi_order_bottom:
        fh2 = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        fh2.close()
        _emit_progress(progress_callback, 25, "Reordering multi-quantity labels")
        reorder_pdf_multi_qty_last(
            work_pdf,
            fh2.name,
            progress_callback=progress_callback,
            start_pct=25,
            end_pct=52,
        )
        chain_tmps.append(fh2.name)
        work_pdf = fh2.name

    try:
        if layout == "label_printer":
            tmp_label = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp_label.close()
            if sort_by == "order_id":
                crop_labels_default_order(
                    work_pdf,
                    tmp_label.name,
                    progress_callback=progress_callback,
                    start_pct=53,
                    end_pct=90,
                )
            elif sort_by == "sku":
                _emit_progress(progress_callback, 58, "Sorting and cropping by SKU")
                sku_label_sort_crop(
                    work_pdf,
                    tmp_label.name,
                    progress_callback=progress_callback,
                    start_pct=58,
                    end_pct=90,
                )
            elif sort_by == "delivery":
                _emit_progress(progress_callback, 58, "Sorting and cropping by delivery partner")
                delivery_label_sort_crop(
                    work_pdf,
                    tmp_label.name,
                    progress_callback=progress_callback,
                    start_pct=58,
                    end_pct=90,
                )
            else:
                try:
                    os.unlink(tmp_label.name)
                except OSError:
                    pass
                raise ValueError(f"Unsupported sort_by: {sort_by}")

            try:
                if MEESHO_LABEL_OUTPUT_MODE == "3x5_canvas":
                    tmp_3x5 = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                    tmp_3x5.close()
                    # Legacy mode: emit 3x5 landscape stickers.
                    compose_pdf_to_3x5_canvas(
                        tmp_label.name,
                        tmp_3x5.name,
                        progress_callback=progress_callback,
                        start_pct=90,
                        end_pct=97,
                        orientation="landscape",
                        clip_to_content=True,
                        content_safety_pt=0.0,
                        trim_visible_whitespace=True,
                        whitespace_threshold=245,
                        content_anchor_x="right",
                        content_anchor_y="top",
                        padding_pt=0.0,
                        horizontal_offset_pt=0.0,
                    )
                    rotate_pdf_by_degrees_inplace(
                        tmp_3x5.name,
                        MEESHO_LABEL_ROTATE_DEGREES,
                        progress_callback=progress_callback,
                        start_pct=97,
                        end_pct=99,
                    )
                    os.replace(tmp_3x5.name, output_pdf)
                    try:
                        os.unlink(tmp_3x5.name)
                    except OSError:
                        pass
                else:
                    # Reference mode: keep native full-width cropped pages.
                    rotate_pdf_by_degrees_inplace(
                        tmp_label.name,
                        MEESHO_LABEL_ROTATE_DEGREES,
                        progress_callback=progress_callback,
                        start_pct=94,
                        end_pct=99,
                    )
                    align_output_to_reference(
                        tmp_label.name,
                        MEESHO_REFERENCE_MATCH_PDF,
                        append_unmatched_reference_pages=MEESHO_REFERENCE_APPEND_UNMATCHED,
                    )
                    os.replace(tmp_label.name, output_pdf)
            finally:
                try:
                    os.unlink(tmp_label.name)
                except OSError:
                    pass
            return

        if layout == "keep_invoice":
            _emit_progress(progress_callback, 56, "Sorting full invoice pages")
            sort_full_invoice_pages(
                work_pdf,
                output_pdf,
                sort_by=sort_by or "order_id",
                progress_callback=progress_callback,
                start_pct=56,
                end_pct=99,
            )
            return
    finally:
        for p in chain_tmps:
            try:
                os.unlink(p)
            except OSError:
                pass

    raise ValueError(f"Unsupported layout: {layout}")


def process_uploaded_paths(
    input_paths: list[str],
    output_pdf: str,
    *,
    sort_by: str,
    layout: str,
    print_datetime: bool = False,
    multi_order_bottom: bool = False,
    custom_message: str = "",
    progress_callback=None,
) -> None:
    if not input_paths:
        raise ValueError("No input PDFs")
    if len(input_paths) == 1:
        run_meesho_pipeline(
            input_paths[0],
            output_pdf,
            sort_by=sort_by,
            layout=layout,
            print_datetime=print_datetime,
            multi_order_bottom=multi_order_bottom,
            custom_message=custom_message,
            progress_callback=progress_callback,
        )
        return
    merged = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    merged.close()
    try:
        _emit_progress(progress_callback, 1, "Merging uploaded PDFs")
        merge_pdf_files(input_paths, merged.name)
        run_meesho_pipeline(
            merged.name,
            output_pdf,
            sort_by=sort_by,
            layout=layout,
            print_datetime=print_datetime,
            multi_order_bottom=multi_order_bottom,
            custom_message=custom_message,
            progress_callback=progress_callback,
        )
    finally:
        try:
            os.unlink(merged.name)
        except OSError:
            pass
