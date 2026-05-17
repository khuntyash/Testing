"""Generate a PDF summary of the Cropper Hub / Zero Label Cropper architecture and tech stack."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF


class OverviewPDF(FPDF):
    def __init__(self) -> None:
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)

    def header(self) -> None:
        self.set_font("Helvetica", "B", 13)
        self.cell(
            0,
            10,
            "Zero Label Cropper (Cropper Hub) - Website & Technology Overview",
            new_x="LMARGIN",
            new_y="NEXT",
            align="C",
        )
        self.ln(3)
        self.set_font("Helvetica", size=8)
        self.set_text_color(80, 80, 80)
        self.cell(0, 5, "Architecture, frameworks, libraries, and deployment stack", align="C")
        self.ln(7)
        self.set_text_color(0, 0, 0)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    def section(self, title: str) -> None:
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def subsection(self, title: str) -> None:
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(0.5)

    def body(self, text: str, size: int = 9) -> None:
        self.set_font("Helvetica", size=size)
        self.multi_cell(0, 4.8, text)
        self.ln(2)


def main() -> None:
    pdf = OverviewPDF()
    pdf.add_page()

    pdf.section("1. Product summary")
    pdf.body(
        "Zero Label Cropper (Cropper Hub) is a web application for e-commerce sellers working with "
        "Meesho and Flipkart shipping-label PDFs. It provides automated cropping and sorting, optional OCR "
        "exports (CSV/Excel), premium labeling features (suspicious-buyer detection, pincode splits, loyalty markers, "
        "custom print fields), coin-based billing via an in-app wallet, user dashboards, admin tools, and secure "
        "download of processed PDFs or ZIP archives."
    )

    pdf.section("2. Frontend technologies")
    pdf.subsection("Core framework and tooling")
    pdf.body(
        "- JavaScript runtime: ES modules (type: module in package.json).\n"
        "- UI library: React 18.3.x (react, react-dom).\n"
        "- Build tool and dev server: Vite 5.4.x with @vitejs/plugin-react (Fast Refresh, optimized bundles).\n"
        "- Routing: react-router-dom 7.x (BrowserRouter, lazy-loaded route components, nested layouts).\n"
        "- Client-side PDF utilities: pdf-lib 1.17.x (when PDF manipulation is needed in the browser).\n"
        "- Firebase SDK: firebase 12.x (included in dependencies for optional integrations).\n"
        "- Code style: Prettier 3.x for formatting src/**/*.{js,jsx}.\n"
        "- HTTP: native fetch API for REST calls to the backend (no axios in package.json)."
    )
    pdf.subsection("Application structure")
    pdf.body(
        "- State: React Context for authentication (AuthContext) and wallet (WalletProvider).\n"
        "- Session: Bearer token stored in localStorage (cropperhub_session); sent as Authorization header.\n"
        "- Config: import.meta.env.VITE_API_URL for production API base URL; Vite dev proxy forwards /api to "
        "localhost FastAPI (VITE_DEV_API_PROXY override).\n"
        "- Optional env: VITE_ARTIFACT_DOWNLOAD_TIMEOUT_MS for large artifact downloads.\n"
        "- Major views: lazy-loaded pages (HomePage, WorkspacePage, LoginPage, SignupPage, MyDashboardPage, "
        "WalletPage, AdminPage, HistoryPage, etc.).\n"
        "- Large feature components: WorkspaceView (upload + async tasks), MeeshoNeonView (Meesho workspace UI), "
        "Header, ProtectedRoute, AdminRoute, AppErrorBoundary.\n"
        "- API module: src/api/taskApi.js (fetchWithRetry, fetchTaskStatus, downloadTaskArtifact with as_json=1 "
        "for presigned R2 URLs)."
    )
    pdf.subsection("Hosting (frontend)")
    pdf.body(
        "- Static SPA built with npm run build (vite build); deployed to Vercel.\n"
        "- vercel.json: SPA fallback rewrites so client-side routes (e.g. /login, /meesho) resolve correctly."
    )

    pdf.section("3. Backend technologies")
    pdf.subsection("Web framework and server")
    pdf.body(
        "- Language: Python 3.11 (Dockerfile base image python:3.11-slim).\n"
        "- ASGI framework: FastAPI 0.115+ with Pydantic models for request/response validation.\n"
        "- HTTP server: Uvicorn 0.32+ with standard extras (WebSockets support where applicable).\n"
        "- Multipart uploads: python-multipart for file upload endpoints.\n"
        "- CORS: Starlette CORSMiddleware with configurable allow_origins (environment-driven)."
    )
    pdf.subsection("Python dependencies (requirements.txt)")
    pdf.body(
        "- fastapi: REST API, dependency injection, OpenAPI docs.\n"
        "- uvicorn[standard]: production ASGI server.\n"
        "- python-multipart: multipart form parsing for PDF uploads.\n"
        "- pymupdf (PyMuPDF): PDF open, render, crop, merge, page extraction (fitz).\n"
        "- pdfplumber: supplementary PDF text/layout parsing where needed.\n"
        "- pytesseract: OCR bridge to Tesseract engine.\n"
        "- Pillow (PIL): image handling for stamps/markers and OCR prep.\n"
        "- openpyxl: Excel workbook generation for OCR/exports.\n"
        "- redis (pinned <5): Redis queue client (RESP2 compatibility with some hosted proxies).\n"
        "- psycopg[binary]: PostgreSQL driver when DB_BACKEND=postgres / Neon etc.\n"
        "- boto3: AWS SDK-compatible client for S3 API (Cloudflare R2, presigned URLs)."
    )
    pdf.subsection("System dependencies (Docker image)")
    pdf.body(
        "- tesseract-ocr, tesseract-ocr-eng: OCR engine for label OCR pipelines.\n"
        "- libgl1, libglib2.0-0: native libs commonly required by Pillow/OpenCV-style stacks.\n"
        "- Container exposes port 8000; Railway uses PORT env with start.sh for uvicorn bind."
    )
    pdf.subsection("Backend modules (conceptual)")
    pdf.body(
        "- server.py: FastAPI app, routes, middleware, startup hooks.\n"
        "- auth_store.py: users, sessions, wallet; SQLite or optional Postgres.\n"
        "- history_store.py: crop_jobs, metrics, history APIs.\n"
        "- task_queue.py: enqueue, worker logic, Redis/SQLite backends, S3 result upload.\n"
        "- worker.py: standalone consumer for VPS Docker Compose.\n"
        "- hybrid/storage.py, hybrid/queue.py: auxiliary abstractions for object storage and Redis.\n"
        "- Domain logic: meesho_service.py, flipkart_service.py, partner_crop.py, pdf_sort_delivery.py, "
        "pdf_sort_sku.py, label_ocr_service.py, return_analysis_service.py."
    )

    pdf.add_page()
    pdf.section("4. Data stores and protocols")
    pdf.body(
        "- SQLite: default embedded DB file (LABELHUB_DB_PATH; e.g. /app/data/labelhub.db on Railway with volume). "
        "Stores users, sessions, wallet ledger, crop_jobs, processing_tasks shadow rows.\n"
        "- PostgreSQL: optional via DATABASE_URL and DB_BACKEND=postgres for auth (Neon, RDS-style).\n"
        "- Redis: LIST/STRING/ZSET patterns for queue and task metadata when QUEUE_BACKEND=redis; "
        "Railway internal or public URL.\n"
        "- Cloudflare R2: S3-compatible object storage (STORAGE_BACKEND=s3, boto3, S3_* env vars); "
        "presigned GET for downloads; bucket CORS for browser origins.\n"
        "- HTTP APIs: REST + JSON; Bearer token authentication; optional Idempotency-Key headers on some endpoints.\n"
        "- File formats: PDF (primary), ZIP (multi-file outputs), CSV/XLSX for OCR exports."
    )

    pdf.section("5. Deployment and infrastructure")
    pdf.body(
        "- Frontend: Vercel (global CDN, HTTPS, automatic builds from Git).\n"
        "- API: Railway (Docker deploy from repo Dockerfile; internal networking; public HTTPS URL).\n"
        "- Redis: Railway Redis plugin or equivalent managed Redis.\n"
        "- Workers: Linux VPS (e.g. Hetzner) running Docker Compose "
        "(deploy/hybrid/docker-compose.worker.yml): multiple worker replicas, optional custom DNS resolvers.\n"
        "- Domain/DNS: user domain on Vercel; API subdomain or Railway-provided hostname.\n"
        "- Secrets: environment variables only (never committed); rotation recommended for Redis and R2 keys.\n"
        "- Observability: /api/health and application logging; optional ops scripts under scripts/ops/."
    )

    pdf.section("6. End-to-end processing flow")
    pdf.body(
        "1. Browser uploads PDFs to FastAPI (multipart).\n"
        "2. API authenticates session, creates crop_job row, may upload inputs to R2, enqueues Redis task, "
        "writes shadow SQLite row for UI joins.\n"
        "3. VPS worker pulls task, downloads inputs from R2 if needed, runs PyMuPDF/Tesseract pipelines, "
        "uploads output to R2, updates Redis task to success.\n"
        "4. Browser polls GET /api/tasks/{id}; API merges Redis state into SQLite for history.\n"
        "5. GET /api/tasks/{id}/download?as_json=1 returns JSON with presigned URL; browser fetch() downloads "
        "from R2 without embedding secrets."
    )

    pdf.section("7. Development workflow")
    pdf.body(
        "- Frontend: npm run dev (Vite) with proxy /api -> local uvicorn.\n"
        "- Backend: cd backend && python -m uvicorn server:app --reload --port 8000 (per server.py docstring).\n"
        "- Production parity: Docker build matches Railway; worker compose file for hybrid queue testing.\n"
        "- Formatting: npm run format (Prettier)."
    )

    pdf.section("8. Document revision")
    pdf.body(
        "This PDF is generated from scripts/generate_website_overview_pdf.py using the fpdf2 library. "
        "Regenerate after dependency or architecture changes: python scripts/generate_website_overview_pdf.py"
    )

    out = Path(__file__).resolve().parent.parent / "Zero_Label_Cropper_Website_Overview.pdf"
    pdf.output(str(out))
    print(out)


if __name__ == "__main__":
    main()
