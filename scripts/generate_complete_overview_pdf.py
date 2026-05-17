"""Generate the complete technical PDF (all product + stack + API + env + layout details)."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF


class DocPDF(FPDF):
    def __init__(self) -> None:
        super().__init__()
        self.set_auto_page_break(auto=True, margin=14)

    def header(self) -> None:
        self.set_font("Helvetica", "B", 12)
        self.cell(
            0,
            9,
            "Zero Label Cropper - Complete Technical Overview",
            new_x="LMARGIN",
            new_y="NEXT",
            align="C",
        )
        self.set_font("Helvetica", size=7)
        self.set_text_color(90, 90, 90)
        self.cell(0, 4, "Cropper Hub | Full documentation export", align="C")
        self.ln(6)
        self.set_text_color(0, 0, 0)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(140, 140, 140)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")

    def h1(self, t: str) -> None:
        self.set_font("Helvetica", "B", 10.5)
        self.cell(0, 6, t, new_x="LMARGIN", new_y="NEXT")
        self.ln(0.5)

    def h2(self, t: str) -> None:
        self.set_font("Helvetica", "B", 9.5)
        self.cell(0, 5.5, t, new_x="LMARGIN", new_y="NEXT")
        self.ln(0.5)

    def p(self, text: str, size: int = 8) -> None:
        self.set_font("Helvetica", size=size)
        self.multi_cell(0, 4.3, text)
        self.ln(1.5)


def main() -> None:
    pdf = DocPDF()
    pdf.add_page()

    pdf.h1("Contents (sections in this document)")
    pdf.p(
        "1. Product overview\n"
        "2. Frontend stack (frameworks, libraries, tooling)\n"
        "3. Backend stack (Python, packages, Docker OS deps)\n"
        "4. Data stores, queues, and object storage\n"
        "5. Production deployment topology\n"
        "6. Key environment variables (reference)\n"
        "7. REST API surface (summary)\n"
        "8. Async task and download flow\n"
        "9. Repository layout (high level)\n"
        "10. Development and regeneration"
    )

    pdf.h1("1. Product overview")
    pdf.p(
        "Zero Label Cropper (internally: Cropper Hub) is a SaaS-style web application for Indian "
        "e-commerce sellers who process Meesho and Flipkart shipping-label PDFs. Core capabilities: "
        "upload multi-page PDFs; sort and crop labels by delivery partner or SKU; optional premium "
        "features (suspicious-buyer marking, pincode-based splits, multi-order handling, loyalty markers, "
        "custom print text); OCR pipelines producing CSV/Excel; return-analysis jobs; per-user wallet "
        "with coin billing; dashboards and persistent crop history; admin operations for users and credits; "
        "secure downloads of cropped PDFs or ZIP bundles via presigned object-storage URLs."
    )

    pdf.h1("2. Frontend stack")
    pdf.h2("Frameworks and runtime")
    pdf.p(
        "- React 18.3.x (react, react-dom) with JSX.\n"
        "- Vite 5.4.x as bundler and dev server (@vitejs/plugin-react).\n"
        "- react-router-dom 7.x: BrowserRouter, Routes, lazy(() => import(...)) code splitting.\n"
        "- ES modules (package.json type: module); Node/npm for build.\n"
        "- pdf-lib 1.17.x for optional client-side PDF helpers.\n"
        "- firebase 12.x SDK listed as dependency (integrations as wired in app).\n"
        "- Native fetch() for HTTP (no axios dependency).\n"
        "- Prettier 3.x for formatting."
    )
    pdf.h2("Application patterns")
    pdf.p(
        "- AuthProvider + WalletProvider wrapping the router tree.\n"
        "- Session: JSON in localStorage (cropperhub_session) with bearer token for API.\n"
        "- import.meta.env.VITE_API_URL: production API origin.\n"
        "- vite.config.js: dev proxy /api -> http://127.0.0.1:8000 (override VITE_DEV_API_PROXY).\n"
        "- Optional VITE_ARTIFACT_DOWNLOAD_TIMEOUT_MS for large downloads.\n"
        "- ProtectedRoute wraps authenticated shell; AdminRoute gates /admin.\n"
        "- AppLayout: Header + Outlet; theme from theme/brandTheme.js.\n"
        "- Large UI: WorkspaceView (crop/OCR flows, polling), MeeshoNeonView, MyDashboardPage, AdminPage.\n"
        "- src/api/taskApi.js: fetchWithRetry, fetchTaskStatus, downloadTaskArtifact (?as_json=1 for R2)."
    )
    pdf.h2("Frontend hosting")
    pdf.p(
        "- Static build: npm run build -> dist/.\n"
        "- vercel.json rewrites for SPA (client-side routes).\n"
        "- Typical host: Vercel with custom domain and HTTPS."
    )

    pdf.add_page()
    pdf.h1("3. Backend stack")
    pdf.h2("Runtime and framework")
    pdf.p(
        "- Python 3.11 (Dockerfile: python:3.11-slim).\n"
        "- FastAPI 0.115+ with Uvicorn 0.32+ (ASGI).\n"
        "- Pydantic models for request/response bodies.\n"
        "- python-multipart for file uploads.\n"
        "- Starlette CORSMiddleware (allow_origins from env; expose_headers Location, Content-Disposition)."
    )
    pdf.h2("Python packages (requirements.txt)")
    pdf.p(
        "fastapi, uvicorn[standard], python-multipart, pymupdf (fitz), pdfplumber, pytesseract, "
        "openpyxl, Pillow, redis>=4.6,<5, psycopg[binary], boto3."
    )
    pdf.h2("Docker system packages")
    pdf.p(
        "tesseract-ocr, tesseract-ocr-eng, libgl1, libglib2.0-0 (OCR and imaging native deps).\n"
        "WORKDIR /app/backend; LABELHUB_DB_PATH=/app/data/labelhub.db default; CMD start.sh runs uvicorn "
        "binding PORT."
    )
    pdf.h2("Notable backend modules")
    pdf.p(
        "server.py (routes), auth_store.py, history_store.py, task_queue.py, worker.py, "
        "meesho_service.py, flipkart_service.py, partner_crop.py, pdf_sort_delivery.py, pdf_sort_sku.py, "
        "label_ocr_service.py, return_analysis_service.py, hybrid/storage.py, hybrid/queue.py."
    )

    pdf.h1("4. Data stores, queues, and object storage")
    pdf.p(
        "- SQLite: primary app DB path via LABELHUB_DB_PATH (persistent volume on Railway recommended): "
        "users, sessions, wallet, crop_jobs, crop_job_metrics, processing_tasks (including shadow rows when "
        "QUEUE_BACKEND=redis).\n"
        "- PostgreSQL: optional auth path via DB_BACKEND=postgres and DATABASE_URL.\n"
        "- Redis: QUEUE_BACKEND=redis; REDIS_URL; REDIS_QUEUE_NAME; task JSON keyed per task_id; LIST for queue.\n"
        "- Cloudflare R2: STORAGE_BACKEND=s3; S3_BUCKET, S3_ENDPOINT_URL, S3_REGION, S3_ACCESS_KEY_ID, "
        "S3_SECRET_ACCESS_KEY; optional S3_PREFIX; boto3 presigned URLs for GET.\n"
        "- Files: temp dirs on API/worker for processing; outputs uploaded to R2 in hybrid mode."
    )

    pdf.add_page()
    pdf.h1("5. Production deployment topology (hybrid)")
    pdf.p(
        "- Vercel: hosts the Vite SPA (users hit HTTPS domain).\n"
        "- Railway (or similar): Docker container runs FastAPI only; connects to Redis + SQLite volume + "
        "optional Neon Postgres; reads/writes R2 for artifacts.\n"
        "- Managed Redis: Railway Redis plugin (REDIS_URL shared with workers).\n"
        "- VPS (e.g. Hetzner): Docker Compose runs N worker containers (deploy/hybrid/docker-compose.worker.yml), "
        "QUEUE_BACKEND=redis, STORAGE_BACKEND=s3, DISABLE_EMBEDDED_WORKER=1; pulls jobs and writes to R2.\n"
        "- DNS: apex/www to Vercel; API URL configured in VITE_API_URL.\n"
        "- R2 bucket CORS: allow web origins for GET/HEAD on presigned downloads."
    )

    pdf.h1("6. Key environment variables (reference)")
    pdf.p(
        "Frontend: VITE_API_URL, optional VITE_ARTIFACT_DOWNLOAD_TIMEOUT_MS, VITE_DEV_API_PROXY (dev only).\n\n"
        "API (Railway): PORT, CORS_ORIGINS, LABELHUB_DB_PATH, QUEUE_BACKEND, STORAGE_BACKEND, REDIS_URL, "
        "REDIS_QUEUE_NAME, S3_* bucket credentials, optional DATABASE_URL and DB_BACKEND, "
        "ADMIN_EMAILS, API_PLATFORM, task/worker tuning (DISABLE_EMBEDDED_WORKER, EMBEDDED_WORKER_CONCURRENCY, "
        "MEESHO_CLASSIFY_WORKERS, etc.).\n\n"
        "Worker (VPS): same Redis/S3/queue vars as API where applicable; WORKER_* idle/backoff if set."
    )

    pdf.h1("7. REST API surface (summary)")
    pdf.p(
        "Health: GET /api/health, GET /api/ready.\n"
        "Auth: POST /api/auth/signup, /login, GET /api/auth/me, POST /api/auth/logout.\n"
        "Wallet: GET /api/wallet, POST /api/wallet/spend.\n"
        "Crop (async): POST /api/crop/meesho/start, POST /api/crop/flipkart/start (multipart); "
        "legacy sync-style POST /api/crop/meesho, /api/crop/flipkart may exist for compatibility.\n"
        "Tasks: GET /api/tasks/{task_id}, GET /api/tasks/{task_id}/download (?as_json=1 returns JSON with "
        "presigned URL).\n"
        "OCR: POST /api/ocr/labels/excel/start, GET /api/ocr/labels/tasks/{task_id}, download route; "
        "POST /api/ocr/labels/excel.\n"
        "Returns: POST /api/returns/analysis/start.\n"
        "History: GET /api/history/jobs, GET /api/history/jobs/{job_id}, GET /api/history/customer.\n"
        "Dashboard: GET /api/me/dashboard.\n"
        "Admin (restricted): metrics, jobs, users, wallet credit, audits, OCR/returns admin routes, "
        "risk/OCR downloads per user (see server.py for full list)."
    )

    pdf.add_page()
    pdf.h1("8. Async task and download flow")
    pdf.p(
        "1) User submits crop -> API creates crop_job, uploads inputs to R2 if hybrid, enqueues Redis task, "
        "inserts local SQLite shadow row.\n"
        "2) Worker dequeues, hydrates inputs from R2, processes with PyMuPDF/Tesseract pipeline, uploads "
        "output PDF/ZIP to R2, sets Redis task success with s3:// result_path.\n"
        "3) Browser polls GET /api/tasks/{id}; API syncs Redis state into SQLite for history UI.\n"
        "4) Download: GET .../download?as_json=1 returns { download_url }; browser fetches presigned URL "
        "(no Bearer on R2); large files use extended client timeout on blob fetch only."
    )

    pdf.h1("9. Repository layout (high level)")
    pdf.p(
        "src/ : React app (pages, components, api, auth, wallet, theme, hooks).\n"
        "backend/ : Python FastAPI app, requirements.txt, worker.py, services, Dockerfile context.\n"
        "deploy/hybrid/ : docker-compose.worker.yml, related deploy docs/examples.\n"
        "scripts/ : ops and PDF generators.\n"
        "Root: Dockerfile (API image), railway.toml, vercel.json, vite.config.js, package.json."
    )

    pdf.h1("10. Development and regeneration of this PDF")
    pdf.p(
        "Local FE: npm run dev (Vite). Local BE: uvicorn server:app --reload --port 8000 from backend/.\n"
        "This file is produced by: python scripts/generate_complete_overview_pdf.py\n"
        "Output filename: Zero_Label_Cropper_Complete_Overview.pdf (project root).\n"
        "Dependency: pip install fpdf2"
    )

    out = Path(__file__).resolve().parent.parent / "Zero_Label_Cropper_Complete_Overview.pdf"
    pdf.output(str(out))
    print(out)


if __name__ == "__main__":
    main()
