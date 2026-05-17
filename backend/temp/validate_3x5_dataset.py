from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import fitz

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from flipkart_service import process_uploaded_paths as process_flipkart_uploaded_paths
from label_canvas_fit import STICKER_3X5_HEIGHT_PT, STICKER_3X5_WIDTH_PT
from meesho_service import process_uploaded_paths as process_meesho_uploaded_paths

DATASET_DIR = Path(r"C:\Users\HP\Downloads\New folder (7)")
OUTPUT_DIR = Path(__file__).resolve().parent / "label_3x5_validation" / "new_folder_7_run"
SIZE_TOLERANCE_PT = 0.8


def _detect_platform(pdf_path: Path) -> str:
    with fitz.open(str(pdf_path)) as doc:
        if not doc:
            return "unknown"
        page = doc[0]
        text = (page.get_text("text") or "").lower()
        rect = page.rect

    flipkart_hints = ("flipkart", "e-kart", "ekart", "sku id", "total qty", "shipping/customer")
    meesho_hints = ("meesho", "valmo", "shadowfax", "delhivery", "sub order", "bill to / ship to")
    if any(token in text for token in flipkart_hints):
        return "flipkart"
    if any(token in text for token in meesho_hints):
        return "meesho"

    # Geometric fallback for already-cropped labels.
    if rect.width <= 280 and rect.height <= 420:
        return "flipkart"
    if rect.width >= 500 and rect.height <= 420:
        return "meesho"
    return "unknown"


def _page_margin_check(doc: fitz.Document, page_indexes: list[int]) -> dict:
    checks = []
    for idx in page_indexes:
        page = doc[idx]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        width = pix.width
        height = pix.height
        data = pix.samples
        n = pix.n
        min_x = width
        min_y = height
        max_x = -1
        max_y = -1
        threshold = 245
        for y in range(height):
            row = y * width * n
            for x in range(width):
                i = row + (x * n)
                if data[i] < threshold or data[i + 1] < threshold or data[i + 2] < threshold:
                    if x < min_x:
                        min_x = x
                    if y < min_y:
                        min_y = y
                    if x > max_x:
                        max_x = x
                    if y > max_y:
                        max_y = y
        if max_x < 0 or max_y < 0:
            checks.append({"page": idx + 1, "blank_or_light": True})
            continue
        checks.append(
            {
                "page": idx + 1,
                "left_margin_px": int(min_x),
                "top_margin_px": int(min_y),
                "right_margin_px": int(width - 1 - max_x),
                "bottom_margin_px": int(height - 1 - max_y),
                "touches_edge": bool(min_x <= 0 or min_y <= 0 or max_x >= width - 1 or max_y >= height - 1),
            }
        )
    return {"checks": checks, "edge_touch_pages": [c["page"] for c in checks if c.get("touches_edge")]}


def _pick_sample_pages(page_count: int) -> list[int]:
    if page_count <= 0:
        return []
    candidates = {
        0,
        max(0, page_count // 4),
        max(0, page_count // 2),
        max(0, (3 * page_count) // 4),
        page_count - 1,
    }
    return sorted(candidates)


def _read_pdf_size_stats(pdf_path: Path) -> dict:
    with fitz.open(str(pdf_path)) as doc:
        page_count = len(doc)
        unique_sizes = sorted({(round(p.rect.width, 2), round(p.rect.height, 2)) for p in doc})
        sample_pages = _pick_sample_pages(page_count)
        margin_check = _page_margin_check(doc, sample_pages)
    return {"page_count": page_count, "unique_sizes_pt": unique_sizes, "margin_check": margin_check}


def _assert_is_3x5_portrait(size_stats: dict) -> None:
    expected_w = STICKER_3X5_WIDTH_PT
    expected_h = STICKER_3X5_HEIGHT_PT
    for width_pt, height_pt in size_stats["unique_sizes_pt"]:
        if abs(width_pt - expected_w) > SIZE_TOLERANCE_PT or abs(height_pt - expected_h) > SIZE_TOLERANCE_PT:
            raise AssertionError(
                f"Unexpected page size {width_pt}x{height_pt}pt, expected {round(expected_w,2)}x{round(expected_h,2)}pt"
            )


def _save_preview(pdf_path: Path, png_path: Path) -> None:
    with fitz.open(str(pdf_path)) as doc:
        if not doc:
            return
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False)
        pix.save(str(png_path))


def _run_for_platform(platform: str, input_paths: list[Path], output_pdf: Path) -> dict:
    if platform == "meesho":
        process_meesho_uploaded_paths(
            [str(p) for p in input_paths],
            str(output_pdf),
            sort_by="order_id",
            layout="label_printer",
        )
    elif platform == "flipkart":
        process_flipkart_uploaded_paths(
            [str(p) for p in input_paths],
            str(output_pdf),
            layout="label_printer",
            sort_by="sku",
            multi_order_bottom=False,
        )
    else:
        raise ValueError(f"Unsupported platform: {platform}")

    input_pages = 0
    for p in input_paths:
        with fitz.open(str(p)) as doc:
            input_pages += len(doc)

    size_stats = _read_pdf_size_stats(output_pdf)
    _assert_is_3x5_portrait(size_stats)
    if input_pages != size_stats["page_count"]:
        raise AssertionError(f"{platform}: input pages ({input_pages}) != output pages ({size_stats['page_count']})")

    if size_stats["margin_check"]["edge_touch_pages"]:
        raise AssertionError(f"{platform}: sampled pages touching canvas edge {size_stats['margin_check']['edge_touch_pages']}")

    return {"input_pages": input_pages, "output_pages": size_stats["page_count"], **size_stats}


def main() -> None:
    if not DATASET_DIR.exists():
        raise FileNotFoundError(f"Dataset path does not exist: {DATASET_DIR}")

    pdf_paths = sorted(DATASET_DIR.glob("*.pdf"))
    if not pdf_paths:
        raise FileNotFoundError(f"No PDF files found in dataset: {DATASET_DIR}")

    shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    buckets: dict[str, list[Path]] = {"meesho": [], "flipkart": [], "unknown": []}
    for p in pdf_paths:
        buckets[_detect_platform(p)].append(p)

    run_summary: dict[str, dict] = {
        "dataset_dir": str(DATASET_DIR),
        "output_dir": str(OUTPUT_DIR),
        "classified_inputs": {k: [str(x) for x in v] for k, v in buckets.items()},
    }

    if not buckets["meesho"] or not buckets["flipkart"]:
        raise RuntimeError(
            "Dataset classification did not produce both platforms. "
            f"meesho={len(buckets['meesho'])}, flipkart={len(buckets['flipkart'])}, unknown={len(buckets['unknown'])}"
        )

    for platform in ("meesho", "flipkart"):
        inputs = buckets[platform]
        output_pdf = OUTPUT_DIR / f"{platform}_3x5_output.pdf"
        preview_in = OUTPUT_DIR / f"{platform}_input_preview_page1.png"
        preview_out = OUTPUT_DIR / f"{platform}_3x5_preview_page1.png"

        _save_preview(inputs[0], preview_in)
        stats = _run_for_platform(platform, inputs, output_pdf)
        _save_preview(output_pdf, preview_out)

        run_summary[platform] = {
            "output_pdf": str(output_pdf),
            "input_preview": str(preview_in),
            "output_preview": str(preview_out),
            "stats": stats,
        }

    report_path = OUTPUT_DIR / "validation_report.json"
    report_path.write_text(json.dumps(run_summary, indent=2), encoding="utf-8")
    print(json.dumps(run_summary, indent=2))
    print(f"\nValidation report: {report_path}")


if __name__ == "__main__":
    main()
