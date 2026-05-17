from __future__ import annotations

import os
import time
from pathlib import Path

import requests


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> int:
    base_url = os.getenv("OPS_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    email = _require("SYNTHETIC_USER_EMAIL")
    password = _require("SYNTHETIC_USER_PASSWORD")
    pdf_path = Path(_require("SYNTHETIC_INPUT_PDF"))
    timeout_sec = max(30, int(os.getenv("SYNTHETIC_TIMEOUT_SEC", "600")))
    poll_sec = max(2, int(os.getenv("SYNTHETIC_POLL_SEC", "5")))

    if not pdf_path.exists():
        raise RuntimeError(f"SYNTHETIC_INPUT_PDF not found: {pdf_path}")

    session = requests.Session()

    # 1) Auth
    auth = session.post(
        f"{base_url}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    auth.raise_for_status()
    token = auth.json().get("token") or ""
    if not token:
        raise RuntimeError("login response missing token")
    headers = {"Authorization": f"Bearer {token}"}

    # 2) Crop start
    with pdf_path.open("rb") as fp:
        files = {"files": (pdf_path.name, fp, "application/pdf")}
        data = {"platform": "meesho", "layout": "label_printer"}
        start = session.post(f"{base_url}/api/crop", headers=headers, data=data, files=files, timeout=60)
    start.raise_for_status()
    task_id = (start.json() or {}).get("task_id") or ""
    if not task_id:
        raise RuntimeError("crop start response missing task_id")

    # 3) Poll
    deadline = time.time() + timeout_sec
    final_payload: dict | None = None
    while time.time() < deadline:
        status_res = session.get(f"{base_url}/api/tasks/{task_id}", headers=headers, timeout=20)
        status_res.raise_for_status()
        payload = status_res.json() or {}
        status = (payload.get("status") or "").strip().lower()
        if status in {"success", "failed", "cancelled", "expired"}:
            final_payload = payload
            break
        time.sleep(poll_sec)
    if not final_payload:
        raise RuntimeError(f"task {task_id} did not finish within timeout")
    if (final_payload.get("status") or "").strip().lower() != "success":
        raise RuntimeError(f"task {task_id} finished with status={final_payload.get('status')}")

    # 4) Download metadata + proxy download
    meta = session.get(
        f"{base_url}/api/tasks/{task_id}/download?as_json=1",
        headers=headers,
        timeout=20,
    )
    meta.raise_for_status()
    meta_payload = meta.json() or {}
    auth_url = (meta_payload.get("authenticated_download_url") or "").strip()
    if not auth_url:
        raise RuntimeError("download metadata missing authenticated_download_url")
    if auth_url.startswith("/"):
        auth_url = f"{base_url}{auth_url}"
    download = session.get(auth_url, headers=headers, timeout=60)
    download.raise_for_status()
    if len(download.content) < 1024:
        raise RuntimeError(f"download payload too small ({len(download.content)} bytes)")

    print(
        f"[OK] synthetic flow passed task_id={task_id} "
        f"status={final_payload.get('status')} bytes={len(download.content)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
