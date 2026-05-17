# Today Updates - 2026-05-02

This file is a handover note so work can continue quickly tomorrow.

## 1) Meesho crop accuracy improvements

- Updated `backend/partner_crop.py` to improve real-world label detection across mixed templates.
- Implemented dynamic bottom-edge detection using semantic anchors:
  - Primary anchors: `BILL TO / SHIP TO`, `BILL TO`, `SHIP TO`
  - Secondary fallback anchors: `Order No.`, `Product Details`, `SKU`
- Crop behavior now matches sample/reference style better:
  - top fixed to page start
  - bottom detected per page type
  - full-width crop used for reference-like output
- Added environment-tunable parameters:
  - `MEESHO_BOTTOM_ANCHOR_GAP` (default `23`)
  - `MEESHO_MIN_LABEL_HEIGHT` (default `320`)
  - `MEESHO_ORDER_NO_BOTTOM_OFFSET` (default `46.5`)
  - `MEESHO_PRODUCT_DETAILS_BOTTOM_OFFSET` (default `64.9`)
  - `MEESHO_SKU_BOTTOM_OFFSET` (default `46.5`)

## 2) Label orientation fix (no forced sideways)

- Updated `backend/meesho_service.py`:
  - Removed forced 90-degree rotation from label-printer outputs by default.
  - Added config option `MEESHO_LABEL_ROTATE_DEGREES` with default `0`.
- Updated `backend/flipkart_service.py`:
  - Added `FLIPKART_A4_ROTATE_DEGREES` with default `0` for A4 composition.
  - A4 page embedding rotation is now configurable (0/90/180/270).

Result: label output is now normal readable orientation (like user-approved screenshot), not sideways.

## 3) Timestamp placement update

- Updated `backend/meesho_service.py` date-time behavior:
  - `Printed: ...` is now placed just after `Product Details`.
  - If `Product Details` is missing, fallback is bottom-left.
  - When both timestamp + custom message are enabled, lines are stacked safely.
- Increased timestamp text size slightly:
  - `Printed:` font size updated to `9.0`.

## 4) Daily history auto-clear + storage cleanup

- Updated `backend/history_store.py` with strict daily cleanup.
- At first access on a new local day:
  - Deletes previous-day `crop_jobs` entries (including old pending/processing).
  - Deletes old `processing_tasks` rows for crop tasks:
    - `crop_meesho`, `crop_flipkart`
  - Deletes linked backend output paths (`result_path`) to reduce storage:
    - file -> delete
    - folder -> delete recursively
- This makes Recent Jobs start empty each new day and clears old crop storage.

## 5) Accuracy validation artifacts generated

### Folder 7
- Generated output:
  - `C:\Users\HP\Downloads\New folder (7)\generated_pipeline_label_printer_v2.pdf`
- Report:
  - `C:\Users\HP\Downloads\New folder (7)\accuracy_report_gurukrupa231_best_aligned.json`

### Folder 8
- Generated output:
  - `C:\Users\HP\Downloads\New folder (8)\generated_pipeline_label_printer_v2.pdf`
- Report:
  - `C:\Users\HP\Downloads\New folder (8)\accuracy_report_nakalank476_best_aligned.json`

### Combined summary
- `C:\Users\HP\Downloads\label_cropper_accuracy_latest.json`
- `C:\Users\HP\Downloads\best_crop_accuracy_summary.json`

## 6) Key backend files changed today

- `backend/partner_crop.py`
- `backend/meesho_service.py`
- `backend/flipkart_service.py`
- `backend/history_store.py`

## 7) Tomorrow quick restart checklist

1. Start backend and frontend.
2. Run one Meesho crop with `label_printer` layout to confirm:
   - orientation is normal (not rotated)
   - timestamp appears after `Product Details`.
3. Check Recent Jobs behavior and daily cleanup trigger.
4. If needed, tune crop anchors using the env vars listed above.

