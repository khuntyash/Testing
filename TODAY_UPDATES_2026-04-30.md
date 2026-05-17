# Cropper Hub - Daily Update (2026-04-30)

This file is a full handoff note for today's work so it can be reloaded tomorrow.

## Scope Completed Today

1. Admin user list now shows per-user:
   - Total labels processed
   - Risky count
2. Admin table alignment was fixed (header/body column sync).
3. OCR workflow changed to backend-automatic when user crops labels.
4. Manual OCR action controls were removed from user-facing workspace UI.
5. Added Admin user sorting option:
   - Email highest to lowest
   - Email lowest to highest
6. Services were restarted and verified healthy.
7. Real jobs were executed for live validation of admin totals.

---

## Backend Changes

## 1) Admin per-user aggregate metrics

### Final metric definition (as requested)
- `total_labels_processed`:
  - Sum of processed labels across all successful crop jobs
  - Platforms included: `meesho`, `flipkart`
  - Formula uses `crop_job_metrics.total_output_labels` (fallback logic present where needed)
- `risky_customer_count` (display label in UI is "Risky"):
  - Sum of risky processed quantity across successful crop jobs
  - Derived from per-job `options_json` risk split summary (`risky_pages` / risk fields)
  - This is aggregated by job quantities, not profile/customer master count

### Files
- `backend/history_store.py`
  - Added aggregate helper for per-user crop totals (`labels` + `risky`).
- `backend/server.py`
  - Admin user endpoints enrich each user row with:
    - `total_labels_processed`
    - `risky_customer_count`
  - Applied to both:
    - `GET /api/admin/users`
    - `GET /api/admin/users/cursor`

---

## 2) OCR now auto-runs in backend when crop starts

### Requirement implemented
Users come for cropping only. OCR should still happen in background for data collection.

### Implementation
- Added helper in `backend/server.py`:
  - `_enqueue_auto_ocr_from_crop(...)`
- Hooked into crop flows:
  - `POST /api/crop/meesho/start`
  - `POST /api/crop/flipkart/start`
  - `POST /api/crop/meesho` (sync path)
  - `POST /api/crop/flipkart` (sync path)

### Behavior
- Crop continues as primary user flow.
- OCR is enqueued in background with copied input payload.
- OCR enqueue failure does not break crop output.
- Failure path marks OCR job failed cleanly if enqueue partially created job.

---

## Frontend Changes

## 3) Admin user table alignment fixes

### Problem addressed
Columns appeared misaligned/colliding between header and rows.

### Fixes applied in `src/pages/AdminPage.jsx`
- Shared column grid constants for header and rows (single source of truth).
- Header and rows kept in same scroll/layout context.
- Role column stabilized with fixed sizing.
- Added min-width strategy + controlled horizontal overflow.
- Preserved virtualization and all row actions/checkbox behavior.

---

## 4) Removed manual OCR controls from workspace UI

### Requirement
Manual OCR trigger UI not useful because OCR is backend-automatic.

### Changes
- `src/components/MeeshoNeonView.jsx`
  - Removed manual OCR control block:
    - Preset selector
    - Worker input
    - Custom columns input
    - "Run OCR CSV" button
  - Replaced with informational text:
    - OCR runs automatically in backend during crop flow.
- `src/components/WorkspaceView.jsx`
  - Removed parallel manual OCR control section from fallback UI.

---

## 5) Admin user sort option added

### File
- `src/pages/AdminPage.jsx`

### Feature
- New sort dropdown in User management section:
  - `Sort: Default`
  - `Sort: Email highest to lowest`
  - `Sort: Email lowest to highest`
- Sorting is applied on displayed list by email.
- Preference is persisted in admin UI prefs (local storage payload).

---

## Service/Runtime Actions Done

- Backend restarted on `127.0.0.1:8001`.
- Frontend restarted on `127.0.0.1:5173`.
- Health verified:
  - `/api/health` => 200 with `{ "ok": true }`
  - frontend root => 200
- Old task failure notifications observed later were from prior sessions; current services remained healthy.

---

## Validation Runs Performed

## A) Crop benchmark run (for admin totals testing)
- Script: `backend/load_task_benchmark.py`
- Mode: crop-only (`ocr_ratio=0`)
- Result: successful submissions/executions, generated fresh load users and crop totals.

## B) End-to-end run with suspicious detection enabled
- Script: `backend/e2e_system_test.py`
- Run completed with all checks passing.
- Produced clear risk split summary and download artifact.

### Verification user created for high-value admin check
- Email: `e2e_17775584316830@example.com`
- Expected admin totals:
  - `Labels` = `1427`
  - `Risky` = `2`

Additional verification users from load benchmark:
- `load_user_1777558272_0@example.com` => Labels 4, Risky 0
- `load_user_1777558272_1@example.com` => Labels 4, Risky 0
- `load_user_1777558272_2@example.com` => Labels 4, Risky 0
- `load_user_1777558272_3@example.com` => Labels 4, Risky 0

---

## Notes for Tomorrow

1. If admin values look stale, refresh admin page and use user-table refresh.
2. For deterministic verification, use exact emails listed above.
3. Current design intent is:
   - Crop flow is user-facing.
   - OCR is backend-automatic and server-stored.
4. Admin "Risky" column currently represents aggregated risky processed quantity from crop job summaries.

