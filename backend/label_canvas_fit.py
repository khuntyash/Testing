from __future__ import annotations

import fitz
import os

STICKER_3X5_WIDTH_MM = 75.0
STICKER_3X5_HEIGHT_MM = 125.0
MM_TO_PT = 72.0 / 25.4
STICKER_3X5_WIDTH_PT = STICKER_3X5_WIDTH_MM * MM_TO_PT
STICKER_3X5_HEIGHT_PT = STICKER_3X5_HEIGHT_MM * MM_TO_PT
DEFAULT_CANVAS_PADDING_PT = 8.0
CONTENT_BOUNDS_SAFETY_PT = 3.0
MIN_RECT_SIDE_PT = 1.0
CANVAS_FIT_PROGRESS_EVERY_PAGES = max(1, int(os.getenv("CANVAS_FIT_PROGRESS_EVERY_PAGES", "10")))
DEFAULT_RASTER_WHITE_THRESHOLD = 245
DEFAULT_RASTER_DETECT_ZOOM = 0.8
NEAR_CLIP_EPSILON_PT = 1.0


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
    if page_index + 1 < total and ((page_index + 1) % CANVAS_FIT_PROGRESS_EVERY_PAGES) != 0:
        return
    span = max(0, int(end_pct) - int(start_pct))
    pct = int(start_pct) + int(((page_index + 1) / total) * span)
    progress_callback(max(0, min(100, pct)), (message or "").strip())


def _rect_intersection(a: fitz.Rect, b: fitz.Rect) -> fitz.Rect:
    x0 = max(float(a.x0), float(b.x0))
    y0 = max(float(a.y0), float(b.y0))
    x1 = min(float(a.x1), float(b.x1))
    y1 = min(float(a.y1), float(b.y1))
    if x1 - x0 >= MIN_RECT_SIDE_PT and y1 - y0 >= MIN_RECT_SIDE_PT:
        return fitz.Rect(x0, y0, x1, y1)
    return fitz.Rect(b.x0, b.y0, b.x1, b.y1)


def _union_rect(base: fitz.Rect | None, rect: fitz.Rect | None) -> fitz.Rect | None:
    if rect is None:
        return base
    if base is None:
        return fitz.Rect(rect)
    return fitz.Rect(
        min(float(base.x0), float(rect.x0)),
        min(float(base.y0), float(rect.y0)),
        max(float(base.x1), float(rect.x1)),
        max(float(base.y1), float(rect.y1)),
    )


def _safe_source_clip(page: fitz.Page) -> fitz.Rect:
    return _rect_intersection(page.cropbox, page.mediabox)


def _extract_text_bounds(page: fitz.Page, clip: fitz.Rect) -> fitz.Rect | None:
    bounds = None
    for block in page.get_text("blocks", clip=clip) or []:
        if len(block) < 5:
            continue
        text = (block[4] or "").strip()
        if not text:
            continue
        rect = fitz.Rect(float(block[0]), float(block[1]), float(block[2]), float(block[3]))
        bounds = _union_rect(bounds, _rect_intersection(rect, clip))
    return bounds


def _extract_image_bounds(page: fitz.Page, clip: fitz.Rect) -> fitz.Rect | None:
    bounds = None
    for img in page.get_images(full=True) or []:
        xref = int(img[0])
        for rect in page.get_image_rects(xref) or []:
            bounds = _union_rect(bounds, _rect_intersection(rect, clip))
    return bounds


def _extract_drawing_bounds(page: fitz.Page, clip: fitz.Rect) -> fitz.Rect | None:
    bounds = None
    for drawing in page.get_drawings() or []:
        rect = drawing.get("rect")
        if rect is None:
            continue
        bounds = _union_rect(bounds, _rect_intersection(rect, clip))
    return bounds


def _inflate_and_clamp(rect: fitz.Rect, clip: fitz.Rect, pad_pt: float) -> fitz.Rect:
    padded = fitz.Rect(
        float(rect.x0) - pad_pt,
        float(rect.y0) - pad_pt,
        float(rect.x1) + pad_pt,
        float(rect.y1) + pad_pt,
    )
    return _rect_intersection(padded, clip)


def _extract_raster_nonwhite_bounds(
    page: fitz.Page,
    clip: fitz.Rect,
    *,
    white_threshold: int = DEFAULT_RASTER_WHITE_THRESHOLD,
    zoom: float = DEFAULT_RASTER_DETECT_ZOOM,
) -> fitz.Rect | None:
    """
    Detect visible (non-white) content bounds by raster scan.

    Useful when the page is a full-bleed image object whose geometric rect equals
    the full page but still contains visible white border in pixels.
    """
    pix = page.get_pixmap(matrix=fitz.Matrix(float(zoom), float(zoom)), clip=clip, alpha=False)
    width = int(pix.width)
    height = int(pix.height)
    channels = int(pix.n)
    if width <= 0 or height <= 0 or channels < 3:
        return None

    threshold = max(0, min(255, int(white_threshold)))
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

    scale_x = float(clip.width) / float(width)
    scale_y = float(clip.height) / float(height)
    rect = fitz.Rect(
        float(clip.x0) + (float(min_x) * scale_x),
        float(clip.y0) + (float(min_y) * scale_y),
        float(clip.x0) + (float(max_x + 1) * scale_x),
        float(clip.y0) + (float(max_y + 1) * scale_y),
    )
    return _rect_intersection(rect, clip)


def _detect_content_clip(
    page: fitz.Page,
    *,
    content_safety_pt: float = CONTENT_BOUNDS_SAFETY_PT,
    trim_visible_whitespace: bool = False,
    raster_white_threshold: int = DEFAULT_RASTER_WHITE_THRESHOLD,
) -> fitz.Rect:
    clip = _safe_source_clip(page)
    content_bounds = None
    content_bounds = _union_rect(content_bounds, _extract_text_bounds(page, clip))
    content_bounds = _union_rect(content_bounds, _extract_image_bounds(page, clip))
    content_bounds = _union_rect(content_bounds, _extract_drawing_bounds(page, clip))
    if bool(trim_visible_whitespace):
        raster_bounds = _extract_raster_nonwhite_bounds(
            page,
            clip,
            white_threshold=raster_white_threshold,
        )
        if raster_bounds is not None:
            if content_bounds is None:
                content_bounds = raster_bounds
            else:
                near_full_clip = (
                    abs(float(content_bounds.x0) - float(clip.x0)) <= NEAR_CLIP_EPSILON_PT
                    and abs(float(content_bounds.y0) - float(clip.y0)) <= NEAR_CLIP_EPSILON_PT
                    and abs(float(content_bounds.x1) - float(clip.x1)) <= NEAR_CLIP_EPSILON_PT
                    and abs(float(content_bounds.y1) - float(clip.y1)) <= NEAR_CLIP_EPSILON_PT
                )
                if near_full_clip:
                    content_bounds = raster_bounds
    if content_bounds is None:
        return clip
    return _inflate_and_clamp(content_bounds, clip, max(0.0, float(content_safety_pt)))


def compose_pdf_to_3x5_canvas(
    input_file_path: str,
    output_file_path: str,
    *,
    padding_pt: float = DEFAULT_CANVAS_PADDING_PT,
    horizontal_offset_pt: float = 0.0,
    vertical_offset_pt: float = 0.0,
    clip_to_content: bool = True,
    content_safety_pt: float = CONTENT_BOUNDS_SAFETY_PT,
    trim_visible_whitespace: bool = False,
    whitespace_threshold: int = DEFAULT_RASTER_WHITE_THRESHOLD,
    content_anchor_x: str = "center",
    content_anchor_y: str = "center",
    progress_callback=None,
    start_pct: int = 0,
    end_pct: int = 100,
    orientation: str = "portrait",
) -> None:
    """
    Render each source page into a fixed 3x5in canvas page.

    Source content is clipped to detected bounds and scaled with a contain-fit
    strategy into an inner frame with padding, so no critical content is cut.

    orientation:
      - "portrait"  -> 75mm x 125mm (default; existing Flipkart behavior)
      - "landscape" -> 125mm x 75mm (Meesho horizontal sticker)

    clip_to_content:
      - True  -> trim to detected content bounds before fitting.
      - False -> fit the full source cropbox/mediabox region. This is safer
                 for preserving every printable element (barcode quiet zones,
                 edge lines, etc.) when strict no-clipping is required.

    horizontal_offset_pt / vertical_offset_pt:
      - Optional nudge applied after contain-fit positioning.
      - Value is clamped so content remains inside the padded inner frame.

    content_anchor_x / content_anchor_y:
      - Optional alignment in the leftover frame space after contain-fit.
      - x: "left" | "center" | "right" (default center)
      - y: "top" | "center" | "bottom" (default center)

    trim_visible_whitespace:
      - When True, enables pixel-based non-white bound detection to trim
        visible blank borders for full-bleed scans that geometric bounds
        cannot tighten.
    """
    if str(orientation).strip().lower() == "landscape":
        # Swap width/height to produce a 5x3in landscape canvas (125mm x 75mm).
        canvas_w = STICKER_3X5_HEIGHT_PT
        canvas_h = STICKER_3X5_WIDTH_PT
    else:
        canvas_w = STICKER_3X5_WIDTH_PT
        canvas_h = STICKER_3X5_HEIGHT_PT
    inner = fitz.Rect(
        float(padding_pt),
        float(padding_pt),
        float(canvas_w - padding_pt),
        float(canvas_h - padding_pt),
    )

    with fitz.open(input_file_path) as src_doc:
        total_pages = len(src_doc)
        with fitz.open() as out_doc:
            for i, src_page in enumerate(src_doc):
                source_clip = (
                    _detect_content_clip(
                        src_page,
                        content_safety_pt=content_safety_pt,
                        trim_visible_whitespace=trim_visible_whitespace,
                        raster_white_threshold=whitespace_threshold,
                    )
                    if bool(clip_to_content)
                    else _safe_source_clip(src_page)
                )
                src_w = max(MIN_RECT_SIDE_PT, float(source_clip.width))
                src_h = max(MIN_RECT_SIDE_PT, float(source_clip.height))
                # Use contain-fit to keep whole label visible while preserving aspect ratio.
                scale = min(float(inner.width) / src_w, float(inner.height) / src_h)
                dest_w = src_w * scale
                dest_h = src_h * scale
                anchor_x = (content_anchor_x or "center").strip().lower()
                anchor_y = (content_anchor_y or "center").strip().lower()
                if anchor_x == "left":
                    dest_x0 = float(inner.x0)
                elif anchor_x == "right":
                    dest_x0 = float(inner.x1) - dest_w
                else:
                    dest_x0 = float(inner.x0) + (float(inner.width) - dest_w) / 2.0
                if anchor_y == "top":
                    dest_y0 = float(inner.y0)
                elif anchor_y == "bottom":
                    dest_y0 = float(inner.y1) - dest_h
                else:
                    dest_y0 = float(inner.y0) + (float(inner.height) - dest_h) / 2.0
                dest_x0 += float(horizontal_offset_pt)
                dest_y0 += float(vertical_offset_pt)
                min_x0 = float(inner.x0)
                max_x0 = float(inner.x1) - dest_w
                min_y0 = float(inner.y0)
                max_y0 = float(inner.y1) - dest_h
                dest_x0 = min(max(dest_x0, min_x0), max_x0)
                dest_y0 = min(max(dest_y0, min_y0), max_y0)
                dest_rect = fitz.Rect(dest_x0, dest_y0, dest_x0 + dest_w, dest_y0 + dest_h)

                out_page = out_doc.new_page(width=canvas_w, height=canvas_h)
                try:
                    out_page.show_pdf_page(
                        rect=dest_rect,
                        docsrc=src_doc,
                        pno=src_page.number,
                        clip=source_clip,
                        keep_proportion=True,
                    )
                except ValueError as exc:
                    # Some scanned pages carry rotated geometry where a computed
                    # clip is rejected by PyMuPDF; fallback to safe/full page to
                    # keep output generation robust.
                    if "clip must be finite and not empty" not in str(exc):
                        raise
                    try:
                        out_page.show_pdf_page(
                            rect=dest_rect,
                            docsrc=src_doc,
                            pno=src_page.number,
                            clip=_safe_source_clip(src_page),
                            keep_proportion=True,
                        )
                    except ValueError:
                        out_page.show_pdf_page(
                            rect=dest_rect,
                            docsrc=src_doc,
                            pno=src_page.number,
                            keep_proportion=True,
                        )
                _emit_page_progress(
                    progress_callback,
                    page_index=i,
                    total_pages=total_pages,
                    start_pct=start_pct,
                    end_pct=end_pct,
                    message="Fitting labels into 3x5 canvas",
                )
            out_doc.save(output_file_path)
