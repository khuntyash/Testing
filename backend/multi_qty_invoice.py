"""
Detect invoice pages where line-item quantity sums to > 1 (bottom region scan).
Used to move those pages to the end of the PDF before cropping.
"""
from __future__ import annotations

import pdfplumber


def get_multi_qty_pages(input_file_path: str) -> set[int]:
    """
    Pass 1: pdfplumber scans the bottom ~60% of each page (below 40% from top).
    Returns 0-based page indices where a table Qty/Quantity column sums to > 1.
    """
    multi_qty_pages: set[int] = set()

    try:
        with pdfplumber.open(input_file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                bounding_box = (0, page.height * 0.4, page.width, page.height)
                bottom_half = page.crop(bounding_box)

                tables = bottom_half.extract_tables()
                if not tables:
                    continue

                is_multi = False
                for table in tables:
                    if not table or len(table) < 2:
                        continue

                    header = [str(cell).strip().lower() if cell else "" for cell in table[0]]

                    qty_index = -1
                    for j, col in enumerate(header):
                        if "qty" in col or "quantity" in col:
                            qty_index = j
                            break

                    if qty_index != -1:
                        total_qty = 0
                        for row in table[1:]:
                            try:
                                val = str(row[qty_index]).strip()
                                if val.isdigit():
                                    total_qty += int(val)
                            except (IndexError, ValueError, TypeError):
                                continue

                        if total_qty > 1:
                            is_multi = True
                            break

                if is_multi:
                    multi_qty_pages.add(i)
    except Exception:
        return set()

    return multi_qty_pages
