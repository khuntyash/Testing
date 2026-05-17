import fitz  # PyMuPDF
import os
from concurrent.futures import ProcessPoolExecutor

from partner_crop import detect_partner_for_page, get_clamped_partner_label_rect


MEESHO_CLASSIFY_WORKERS = max(1, int(os.getenv("MEESHO_CLASSIFY_WORKERS", "4") or 4))
MEESHO_CLASSIFY_MIN_PAGES = max(1, int(os.getenv("MEESHO_CLASSIFY_MIN_PAGES", "120") or 120))


def _classify_partner_range(input_file_path: str, start: int, end: int) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    with fitz.open(input_file_path) as doc:
        upper = min(int(end), len(doc))
        for page_num in range(max(0, int(start)), upper):
            page = doc[page_num]
            out.append((page_num, detect_partner_for_page(page)))
    return out


def _emit_progress(progress_callback, pct: int, message: str) -> None:
    if callable(progress_callback):
        progress_callback(max(0, min(99, int(pct))), (message or "").strip())


def _emit_page_progress(
    progress_callback,
    *,
    page_index: int,
    total_pages: int,
    start_pct: int,
    end_pct: int,
    message: str,
    every_pages: int = 10,
) -> None:
    if not callable(progress_callback):
        return
    total = max(1, int(total_pages))
    every = max(1, int(every_pages))
    if page_index + 1 < total and ((page_index + 1) % every) != 0:
        return
    span = max(0, int(end_pct) - int(start_pct))
    pct = int(start_pct) + int(((page_index + 1) / total) * span)
    _emit_progress(progress_callback, pct, message)


def sort_and_crop_labels(
    input_file_path,
    output_file_path,
    *,
    progress_callback=None,
    start_pct: int = 58,
    end_pct: int = 90,
):
    sorted_pages = {
        "Shadowfax": [],
        "ValmoPlus": [],
        "Valmo": [],
        "Delhivery": [],
        "Xpress Bees": [],
        "Unknown": [],
    }

    print("[meesho] Analyzing and cropping pages...")
    with fitz.open(input_file_path) as original_doc:
        total_pages = len(original_doc)
        analyze_end = int(start_pct) + int(max(1, int(end_pct) - int(start_pct)) * 0.7)
        partner_by_page: dict[int, str] = {}
        if total_pages >= MEESHO_CLASSIFY_MIN_PAGES and MEESHO_CLASSIFY_WORKERS > 1:
            chunk_size = max(24, (total_pages + (MEESHO_CLASSIFY_WORKERS * 2) - 1) // (MEESHO_CLASSIFY_WORKERS * 2))
            ranges = [(start, min(total_pages, start + chunk_size)) for start in range(0, total_pages, chunk_size)]
            with ProcessPoolExecutor(max_workers=MEESHO_CLASSIFY_WORKERS) as pool:
                in_paths = [input_file_path] * len(ranges)
                starts = [r[0] for r in ranges]
                ends = [r[1] for r in ranges]
                for classified in pool.map(_classify_partner_range, in_paths, starts, ends):
                    for idx, partner in classified:
                        partner_by_page[int(idx)] = str(partner or "Unknown")
        for page_num in range(total_pages):
            page = original_doc[page_num]
            partner = partner_by_page.get(page_num) or detect_partner_for_page(page)
            label_rect = get_clamped_partner_label_rect(page, partner)
            page.set_cropbox(label_rect)
            sorted_pages.setdefault(partner, []).append(page_num)
            _emit_page_progress(
                progress_callback,
                page_index=page_num,
                total_pages=total_pages,
                start_pct=start_pct,
                end_pct=analyze_end,
                message="Sorting and cropping by delivery partner",
            )

        print("[meesho] Sorting document...")
        final_page_sequence: list[int] = []
        counted = 0
        for partner, page_numbers in sorted_pages.items():
            if len(page_numbers) > 0:
                print(f"   -> Found {len(page_numbers)} labels for {partner}")
                final_page_sequence.extend(page_numbers)
                counted += len(page_numbers)
                _emit_page_progress(
                    progress_callback,
                    page_index=min(total_pages - 1, counted - 1),
                    total_pages=total_pages,
                    start_pct=analyze_end,
                    end_pct=end_pct,
                    message="Sorting and cropping by delivery partner",
                )

        if final_page_sequence and final_page_sequence != list(range(total_pages)):
            # One-shot page reordering is far faster than per-page insert_pdf loops.
            original_doc.select(final_page_sequence)
        original_doc.save(output_file_path)
        print(f"[meesho] Success: sorted and cropped {len(original_doc)} pages.")
        print(f"[meesho] Saved to: {output_file_path}")


if __name__ == "__main__":
    my_input_pdf = r"D:\Gate\Sub_Order_Labels_87fb0f8e-81e2-4ea3-9b75-ab84c1451c88.pdf"
    my_output_pdf = r"D:\Gate\11sorted_and_cropped_labels.pdf"

    try:
        sort_and_crop_labels(my_input_pdf, my_output_pdf)
    except FileNotFoundError:
        print(f"[meesho] Error: could not find the file '{my_input_pdf}'.")
    except Exception as e:
        print(f"[meesho] Unexpected error: {e}")
