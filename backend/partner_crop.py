"""
Shared Meesho label crop.

Current policy: use one universal crop size for all carriers, aligned to
ValmoPlus label dimensions, so every output label has the same size.
"""
from __future__ import annotations

import os
import fitz

# Read carrier names from the largest label header area (covers all partner templates).
MAX_PROBE_RECT = fitz.Rect(0, 0, 597, 390)

# Reference-style Meesho crop:
# - keep full width from x0=0 (matches provided output PDFs)
# - top aligned to page start
# - dynamic bottom edge detected from BILL TO/SHIP TO block (handles big FAST labels too)
BOTTOM_ANCHOR_TOKENS = (
    "BILL TO / SHIP TO",
    "Bill To / Ship To",
    "BILL TO",
    "Bill To",
    "SHIP TO",
    "Ship To",
)
BOTTOM_ANCHOR_GAP = float(os.getenv("MEESHO_BOTTOM_ANCHOR_GAP", "23"))
MIN_LABEL_HEIGHT = float(os.getenv("MEESHO_MIN_LABEL_HEIGHT", "320"))
FOOTER_TRIM_GAP = float(os.getenv("MEESHO_FOOTER_TRIM_GAP", "2"))
FOOTER_TRIM_TOKENS = (
    "TAX INVOICE",
    "Tax Invoice",
    "Original For Recipient",
)
TOP_ANCHOR_TOKENS = (
    "Customer Address",
    "COD:",
    "Prepaid:",
)
TOP_ANCHOR_PAD = float(os.getenv("MEESHO_TOP_ANCHOR_PAD", "6"))
TOP_ANCHOR_MIN_SHIFT = float(os.getenv("MEESHO_TOP_ANCHOR_MIN_SHIFT", "18"))
STACKED_TOP_HINT_TOKENS = (
    "Product Details",
    "SKU",
    "Order No.",
    "TAX INVOICE",
    "Original For Recipient",
    "BILL TO / SHIP TO",
    "Sold by",
)
BOTTOM_EXTRA_PAD = float(os.getenv("MEESHO_BOTTOM_EXTRA_PAD", "4"))
BOTTOM_VISUAL_TRIM = max(0.0, float(os.getenv("MEESHO_BOTTOM_VISUAL_TRIM", "0") or 0))
COMPACT_LAYOUT_ORDER_Y_THRESHOLD = float(os.getenv("MEESHO_COMPACT_LAYOUT_ORDER_Y_THRESHOLD", "340"))
COMPACT_LAYOUT_ORDER_BOTTOM_OFFSET = float(os.getenv("MEESHO_COMPACT_LAYOUT_ORDER_BOTTOM_OFFSET", "-3"))
COMPACT_LAYOUT_MAX_FOOTER_LINE_Y = float(os.getenv("MEESHO_COMPACT_LAYOUT_MAX_FOOTER_LINE_Y", "585"))
COMPACT_LAYOUT_ORDER_LINE_PROXIMITY_MAX_GAP = float(
    os.getenv("MEESHO_COMPACT_LAYOUT_ORDER_LINE_PROXIMITY_MAX_GAP", "22")
)
SECONDARY_BOTTOM_OFFSETS = (
    ("Order No.", float(os.getenv("MEESHO_ORDER_NO_BOTTOM_OFFSET", "46.5"))),
    ("Product Details", float(os.getenv("MEESHO_PRODUCT_DETAILS_BOTTOM_OFFSET", "64.9"))),
    ("SKU", float(os.getenv("MEESHO_SKU_BOTTOM_OFFSET", "46.5"))),
)

# Keep legacy per-partner presets for reference/debug, but runtime crop uses
# the universal ValmoPlus-sized rectangle above.
PARTNER_LABEL_RECTS: dict[str, fitz.Rect] = {
    "Shadowfax": fitz.Rect(0, 0, 597, 339),
    "ValmoPlus": fitz.Rect(0, 0, 597, 390),
    "Valmo": fitz.Rect(0, 0, 597, 349),
    "Delhivery": fitz.Rect(0, 0, 595, 352),
    "Unknown": fitz.Rect(0, 0, 594, 355),
}

def identify_delivery_partner(text: str) -> str:
    text = text.lower()
    if "shadowfax" in text:
        return "Shadowfax"
    if "xpressbees" in text or "xpress bees" in text:
        return "Xpress Bees"
    if "valmoplus" in text or "valmo plus" in text:
        return "ValmoPlus"
    if "valmo" in text:
        return "Valmo"
    if "delhivery" in text:
        return "Delhivery"
    return "Unknown"


def get_partner_label_rect(partner: str) -> fitz.Rect:
    """Return legacy partner crop (defensive copy) as fallback."""
    r = PARTNER_LABEL_RECTS.get(partner, PARTNER_LABEL_RECTS["Unknown"])
    return fitz.Rect(r.x0, r.y0, r.x1, r.y1)


def _search_hits(
    page: fitz.Page,
    token: str,
    clip: fitz.Rect,
    cache: dict[tuple[str, float, float, float, float], list[fitz.Rect]] | None = None,
) -> list[fitz.Rect]:
    key = (token, float(clip.x0), float(clip.y0), float(clip.x1), float(clip.y1))
    if cache is not None and key in cache:
        return cache[key]
    hits = page.search_for(token, clip=clip)
    if cache is not None:
        cache[key] = hits
    return hits


def _first_token_y(
    page: fitz.Page,
    token: str,
    clip: fitz.Rect,
    *,
    search_cache: dict[tuple[str, float, float, float, float], list[fitz.Rect]] | None = None,
) -> float | None:
    hits = _search_hits(page, token, clip, cache=search_cache)
    if not hits:
        return None
    return min(float(r.y0) for r in hits)


def _wide_horizontal_line_ys(page: fitz.Page) -> list[float]:
    ys: list[float] = []
    for drawing in page.get_drawings() or []:
        rect = drawing.get("rect")
        if rect is None:
            continue
        if float(rect.width) > 500.0 and float(rect.height) <= 1.5:
            ys.append(float(rect.y0))
    ys.sort()
    return ys


def _detect_label_bottom_y(page: fitz.Page, *, fallback_y1: float) -> float:
    """
    Detect label bottom Y from semantic anchor.
    This reproduces reference cropped output where top is fixed and height varies.
    """
    mb = page.mediabox
    full_probe = fitz.Rect(mb.x0, mb.y0, mb.x1, mb.y1)
    search_cache: dict[tuple[str, float, float, float, float], list[fitz.Rect]] = {}

    def _clamp_bottom(y: float) -> float:
        return max(mb.y0 + MIN_LABEL_HEIGHT, min(float(y), mb.y1))

    # Compact label templates place the visible cut line very close to the
    # first "Order No." row; using this early avoids retaining extra footer
    # rows in those pages.
    first_order_y = _first_token_y(page, "Order No.", full_probe, search_cache=search_cache)
    line_ys = _wide_horizontal_line_ys(page)
    lower_footer_line_y = line_ys[3] if len(line_ys) >= 4 else None
    next_line_below_order_y = None
    if first_order_y is not None:
        for y in line_ys:
            if y > (first_order_y + 1.0):
                next_line_below_order_y = y
                break
    compact_footer = (
        lower_footer_line_y is None
        or lower_footer_line_y <= COMPACT_LAYOUT_MAX_FOOTER_LINE_Y
    )
    # Use the compact shortcut only when the first horizontal separator below
    # "Order No." is genuinely close to that row; otherwise we end up cutting
    # through the product details section on larger templates.
    order_row_near_cutline = (
        first_order_y is not None
        and next_line_below_order_y is not None
        and (next_line_below_order_y - first_order_y) <= COMPACT_LAYOUT_ORDER_LINE_PROXIMITY_MAX_GAP
    )
    sparse_line_layout = next_line_below_order_y is None and len(line_ys) <= 2
    if (
        first_order_y is not None
        and first_order_y >= COMPACT_LAYOUT_ORDER_Y_THRESHOLD
        and compact_footer
        and (order_row_near_cutline or sparse_line_layout)
    ):
        return _clamp_bottom(first_order_y + COMPACT_LAYOUT_ORDER_BOTTOM_OFFSET)

    # Trim decorative/legal footer strip when present, so output ends at
    # the actual label table and avoids extra blank/footer band in stickers.
    footer_candidates: list[float] = []
    for token in FOOTER_TRIM_TOKENS:
        hits = _search_hits(page, token, full_probe, cache=search_cache)
        if not hits:
            continue
        footer_y = min(float(r.y0) for r in hits)
        footer_candidates.append(footer_y - FOOTER_TRIM_GAP)
    if footer_candidates:
        return _clamp_bottom(min(footer_candidates))

    for token in BOTTOM_ANCHOR_TOKENS:
        anchor_y = _first_token_y(page, token, full_probe, search_cache=search_cache)
        if anchor_y is None:
            continue
        bottom = anchor_y - BOTTOM_ANCHOR_GAP
        return _clamp_bottom(bottom)

    # Fallback for pages where BILL/SHIP anchor text is not rendered.
    secondary_candidates: list[float] = []
    for token, offset in SECONDARY_BOTTOM_OFFSETS:
        anchor_y = _first_token_y(page, token, full_probe, search_cache=search_cache)
        if anchor_y is None:
            continue
        secondary_candidates.append(anchor_y + offset)
    if secondary_candidates:
        return _clamp_bottom(min(secondary_candidates))

    return _clamp_bottom(fallback_y1)


def _detect_label_top_y(page: fitz.Page) -> float:
    """
    Detect label top for large continuous/stacked pages where y=0 may start in
    the previous label tail. For normal pages, this remains near mediabox top.
    """
    mb = page.mediabox
    full_probe = fitz.Rect(mb.x0, mb.y0, mb.x1, mb.y1)
    search_cache: dict[tuple[str, float, float, float, float], list[fitz.Rect]] = {}
    candidate_top: float | None = None
    for token in TOP_ANCHOR_TOKENS:
        hits = _search_hits(page, token, full_probe, cache=search_cache)
        if not hits:
            continue
        y = min(float(r.y0) for r in hits) - TOP_ANCHOR_PAD
        if candidate_top is None or y < candidate_top:
            candidate_top = y
    if candidate_top is None:
        return float(mb.y0)
    shift = candidate_top - float(mb.y0)
    # Shift top only when clearly inside page *and* we detect stacked-label
    # leftovers above the anchor. This avoids cutting valid top banner/header
    # rows on normal labels.
    if shift >= TOP_ANCHOR_MIN_SHIFT:
        top_band = fitz.Rect(mb.x0, mb.y0, mb.x1, min(float(mb.y1), candidate_top + 2.0))
        top_text = (page.get_text("text", clip=top_band) or "").lower()
        has_stacked_hint = any(token.lower() in top_text for token in STACKED_TOP_HINT_TOKENS)
        if has_stacked_hint:
            return max(float(mb.y0), candidate_top)
    return float(mb.y0)


def clamp_rect_to_mediabox(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    """
    PDF requires CropBox (and clip rects used like crops) to lie inside MediaBox.
    Partner templates can be wider/taller than some invoice pages — intersect with MediaBox.
    """
    mb = page.mediabox
    x0 = max(rect.x0, mb.x0)
    y0 = max(rect.y0, mb.y0)
    x1 = min(rect.x1, mb.x1)
    y1 = min(rect.y1, mb.y1)
    if x0 < x1 and y0 < y1:
        return fitz.Rect(x0, y0, x1, y1)
    # Degenerate intersection: use top band of the page
    h = min(355.0, mb.height)
    return fitz.Rect(mb.x0, mb.y0, mb.x1, mb.y0 + h)


def get_clamped_partner_label_rect(page: fitz.Page, partner: str) -> fitz.Rect:
    """
    Reference-style crop:
    top + full width fixed, bottom detected per page for accurate height.
    """
    mb = page.mediabox
    base = clamp_rect_to_mediabox(page, get_partner_label_rect(partner))
    y0 = _detect_label_top_y(page)
    y1 = min(float(mb.y1), _detect_label_bottom_y(page, fallback_y1=base.y1) + BOTTOM_EXTRA_PAD - BOTTOM_VISUAL_TRIM)
    dynamic_rect = fitz.Rect(mb.x0, y0, mb.x1, y1)
    return clamp_rect_to_mediabox(page, dynamic_rect)


def detect_partner_for_page(page: fitz.Page) -> str:
    """Identify carrier using text inside the probe region (clamped to MediaBox)."""
    probe = clamp_rect_to_mediabox(page, MAX_PROBE_RECT)
    text = page.get_text("text", clip=probe)
    return identify_delivery_partner(text)
