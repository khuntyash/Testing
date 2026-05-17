from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz


def _first_y(page: fitz.Page, token: str) -> float | None:
    hits = page.search_for(token)
    if not hits:
        return None
    return min(float(r.y0) for r in hits)


def _visible_bounds(page: fitz.Page, *, threshold: int = 245, zoom: float = 0.6) -> tuple[float, float, float, float] | None:
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    width = int(pix.width)
    height = int(pix.height)
    channels = int(pix.n)
    if width <= 0 or height <= 0 or channels < 3:
        return None
    data = pix.samples
    min_x = width
    min_y = height
    max_x = -1
    max_y = -1
    for y in range(height):
        row = y * width * channels
        for x in range(width):
            i = row + (x * channels)
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
        return None
    rect = page.rect
    scale_x = float(rect.width) / float(width)
    scale_y = float(rect.height) / float(height)
    return (
        float(rect.x0) + (float(min_x) * scale_x),
        float(rect.y0) + (float(min_y) * scale_y),
        float(rect.x0) + (float(max_x + 1) * scale_x),
        float(rect.y0) + (float(max_y + 1) * scale_y),
    )


def _safe_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]


def compare(expected_path: Path, actual_path: Path) -> dict:
    anchor_tokens = ["Customer Address", "Product Details", "Order No.", "BILL TO / SHIP TO", "TAX INVOICE"]
    with fitz.open(str(expected_path)) as expected_doc, fitz.open(str(actual_path)) as actual_doc:
        page_count_expected = len(expected_doc)
        page_count_actual = len(actual_doc)
        compare_pages = min(page_count_expected, page_count_actual)

        page_rows: list[dict] = []
        height_abs_errors: list[float] = []
        visible_edge_abs_errors: list[float] = []
        anchor_abs_errors: list[float] = []

        for i in range(compare_pages):
            ep = expected_doc[i]
            ap = actual_doc[i]
            e_bounds = _visible_bounds(ep)
            a_bounds = _visible_bounds(ap)

            anchor_deltas: dict[str, float | None] = {}
            for token in anchor_tokens:
                anchor_deltas[token] = _safe_diff(_first_y(ap, token), _first_y(ep, token))

            row = {
                "page": i + 1,
                "expected_size": [round(float(ep.rect.width), 2), round(float(ep.rect.height), 2)],
                "actual_size": [round(float(ap.rect.width), 2), round(float(ap.rect.height), 2)],
                "height_delta": round(float(ap.rect.height - ep.rect.height), 2),
                "visible_bounds_delta": None,
                "anchor_y_delta": {k: (None if v is None else round(v, 2)) for k, v in anchor_deltas.items()},
            }
            height_abs_errors.append(abs(float(ap.rect.height - ep.rect.height)))

            if e_bounds is not None and a_bounds is not None:
                bounds_delta = {
                    "left": round(a_bounds[0] - e_bounds[0], 2),
                    "top": round(a_bounds[1] - e_bounds[1], 2),
                    "right": round(a_bounds[2] - e_bounds[2], 2),
                    "bottom": round(a_bounds[3] - e_bounds[3], 2),
                }
                row["visible_bounds_delta"] = bounds_delta
                visible_edge_abs_errors.extend(abs(v) for v in bounds_delta.values())

            for delta in anchor_deltas.values():
                if delta is not None:
                    anchor_abs_errors.append(abs(delta))
            page_rows.append(row)

        worst_height_pages = sorted(page_rows, key=lambda r: abs(float(r["height_delta"])), reverse=True)[:20]
        return {
            "expected_pdf": str(expected_path),
            "actual_pdf": str(actual_path),
            "expected_page_count": page_count_expected,
            "actual_page_count": page_count_actual,
            "compared_pages": compare_pages,
            "summary": {
                "height_abs_mae": _mean(height_abs_errors),
                "height_abs_p90": _p90(height_abs_errors),
                "visible_edge_abs_mae": _mean(visible_edge_abs_errors),
                "visible_edge_abs_p90": _p90(visible_edge_abs_errors),
                "anchor_abs_mae": _mean(anchor_abs_errors),
                "anchor_abs_p90": _p90(anchor_abs_errors),
            },
            "worst_height_pages": worst_height_pages,
            "per_page": page_rows,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare produced Meesho output against expected PDF.")
    parser.add_argument("--expected", required=True, help="Expected/reference PDF path")
    parser.add_argument("--actual", required=True, help="Produced output PDF path")
    parser.add_argument("--out", required=True, help="Output JSON report path")
    args = parser.parse_args()

    report = compare(Path(args.expected), Path(args.actual))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report written: {out_path}")


if __name__ == "__main__":
    main()
