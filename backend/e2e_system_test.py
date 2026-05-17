from __future__ import annotations

import argparse
import json
import os
import random
import string
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from openpyxl import Workbook

from label_ocr_service import extract_records_from_pdfs


def _request(
    method: str,
    url: str,
    *,
    token: str = "",
    payload: dict | None = None,
    body: bytes | None = None,
    content_type: str = "",
    timeout: float = 30.0,
) -> tuple[int, dict | str]:
    data = body
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url=url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw
            return int(res.status), parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw
        return int(exc.code), parsed
    except Exception as exc:
        return 599, str(exc)


def _build_multipart(fields: dict[str, str], files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----CropperHubBoundary" + "".join(random.choices(string.ascii_letters + string.digits, k=18))
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append((value or "").encode("utf-8"))
        chunks.append(b"\r\n")
    for field_name, filename, data, mime in files:
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _pick_pdfs(pdf_dir: str, count: int) -> list[Path]:
    root = Path(pdf_dir).resolve()
    if not root.exists():
        raise RuntimeError(f"PDF directory not found: {root}")
    files = sorted(p for p in root.glob("*.pdf") if p.is_file())
    if not files:
        raise RuntimeError(f"No PDFs found in: {root}")
    return files[: max(1, min(len(files), count))]


def _auth(base_url: str) -> tuple[str, str]:
    suffix = f"{int(time.time())}{random.randint(1000,9999)}"
    email = f"e2e_{suffix}@example.com"
    password = "E2eCheck@123"
    name = "E2E Runner"
    signup = f"{base_url.rstrip('/')}/api/auth/signup"
    login = f"{base_url.rstrip('/')}/api/auth/login"
    status, data = _request("POST", signup, payload={"email": email, "password": password, "name": name})
    if status == 200 and isinstance(data, dict) and isinstance(data.get("token"), str):
        return data["token"], email
    status, data = _request("POST", login, payload={"email": email, "password": password})
    if status == 200 and isinstance(data, dict) and isinstance(data.get("token"), str):
        return data["token"], email
    raise RuntimeError(f"Auth failed: {status} {data}")


def _poll_task(base_url: str, token: str, task_id: str, *, timeout_sec: int = 240, endpoint: str = "tasks") -> dict:
    deadline = time.time() + timeout_sec
    last = {}
    while time.time() < deadline:
        if endpoint == "ocr":
            url = f"{base_url.rstrip('/')}/api/ocr/labels/tasks/{urllib.parse.quote(task_id)}"
        else:
            url = f"{base_url.rstrip('/')}/api/tasks/{urllib.parse.quote(task_id)}"
        status, data = _request("GET", url, token=token)
        if status != 200 or not isinstance(data, dict):
            time.sleep(1.0)
            continue
        task = data.get("task") if isinstance(data.get("task"), dict) else {}
        last = task
        state = str(task.get("status") or "")
        if state in {"success", "failed", "cancelled", "expired"}:
            return task
        time.sleep(1.5)
    raise TimeoutError(f"Task timeout for {task_id}; last={last}")


def _create_returns_excel(path: Path, suborder_for_match: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Returns"
    headers = [
        "Suborder Number",
        "AWB Number",
        "Type of Return",
        "Sub Type",
        "Status",
        "Return Reason",
        "Detailed Return Reason",
    ]
    ws.append(headers)
    ws.append(
        [
            suborder_for_match,
            "AWB-10001",
            "RTO",
            "Customer Return",
            "Completed",
            "Quality issue",
            "Damaged packaging",
        ]
    )
    ws.append(
        [
            f"unknown-{int(time.time())}",
            "AWB-10002",
            "RTO",
            "Customer Return",
            "Completed",
            "Wrong item",
            "Wrong size",
        ]
    )
    wb.save(path)


def _submit_ocr(base_url: str, token: str, pdfs: list[Path]) -> str:
    endpoint = f"{base_url.rstrip('/')}/api/ocr/labels/excel/start?column_preset=standard_v1"
    files: list[tuple[str, str, bytes, str]] = []
    for p in pdfs:
        files.append(("files", p.name, p.read_bytes(), "application/pdf"))
    body, ctype = _build_multipart({}, files)
    status, data = _request("POST", endpoint, token=token, body=body, content_type=ctype, timeout=120.0)
    if status != 200 or not isinstance(data, dict) or not data.get("task_id"):
        raise RuntimeError(f"OCR submit failed: {status} {data}")
    return str(data["task_id"])


def _submit_return_analysis(base_url: str, token: str, excel_path: Path) -> str:
    endpoint = f"{base_url.rstrip('/')}/api/returns/analysis/start"
    body, ctype = _build_multipart(
        {},
        [("file", excel_path.name, excel_path.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")],
    )
    status, data = _request("POST", endpoint, token=token, body=body, content_type=ctype, timeout=120.0)
    if status != 200 or not isinstance(data, dict) or not data.get("task_id"):
        raise RuntimeError(f"Return analysis submit failed: {status} {data}")
    return str(data["task_id"])


def _submit_crop_meesho(
    base_url: str,
    token: str,
    pdfs: list[Path],
    pincode: str,
    *,
    detect_suspicious: bool,
) -> str:
    endpoint = f"{base_url.rstrip('/')}/api/crop/meesho/start"
    fields = {
        "sort_by": "order_id",
        "layout": "label_printer",
        "print_datetime": "0",
        "multi_order_bottom": "0",
        "custom_message": "",
        "separate_pincodes": pincode.strip(),
        "detect_suspicious": "1" if detect_suspicious else "0",
    }
    files: list[tuple[str, str, bytes, str]] = []
    for p in pdfs:
        files.append(("files", p.name, p.read_bytes(), "application/pdf"))
    body, ctype = _build_multipart(fields, files)
    status, data = _request("POST", endpoint, token=token, body=body, content_type=ctype, timeout=180.0)
    if status != 200 or not isinstance(data, dict) or not data.get("task_id"):
        raise RuntimeError(f"Meesho crop submit failed: {status} {data}")
    return str(data["task_id"])


def _download_result(base_url: str, token: str, task_id: str) -> tuple[int, str, int]:
    url = f"{base_url.rstrip('/')}/api/tasks/{urllib.parse.quote(task_id)}/download"
    headers = {"Authorization": f"Bearer {token}"}
    req = urllib.request.Request(url=url, method="GET", headers=headers)
    with urllib.request.urlopen(req, timeout=60.0) as res:
        content_type = res.headers.get("content-type", "")
        payload = res.read()
        return int(res.status), content_type, len(payload)


def _extract_suborder_and_pincode(pdfs: list[Path]) -> tuple[str, str]:
    records, _, _ = extract_records_from_pdfs([str(p) for p in pdfs], max_workers=2)
    for rec in records:
        sub = str(rec.get("Order_id", "")).strip()
        pin = str(rec.get("Pincode", "")).strip()
        if sub:
            return sub, pin
    raise RuntimeError("Could not extract any suborder from provided PDFs.")


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end functional system test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--ocr-pdfs", type=int, default=8)
    parser.add_argument("--crop-pdfs", type=int, default=12)
    parser.add_argument("--use-pincode", action="store_true", default=False)
    parser.add_argument("--forced-pincode", default="")
    parser.add_argument("--detect-suspicious", action="store_true", default=False)
    args = parser.parse_args()

    report: dict = {"base_url": args.base_url, "pdf_dir": str(Path(args.pdf_dir).resolve()), "checks": []}
    t0 = time.perf_counter()

    def record(name: str, ok: bool, detail: str = "", extra: dict | None = None) -> None:
        row = {"name": name, "ok": bool(ok), "detail": detail}
        if extra:
            row["extra"] = extra
        report["checks"].append(row)

    status, data = _request("GET", f"{args.base_url.rstrip('/')}/api/health", timeout=10.0)
    record("health", status == 200, f"status={status}", {"response": data if isinstance(data, dict) else str(data)})
    if status != 200:
        report["ok"] = False
        report["elapsed_sec"] = round(time.perf_counter() - t0, 2)
        print(json.dumps(report, indent=2))
        raise SystemExit(2)

    token, email = _auth(args.base_url)
    record("auth_signup_login", True, f"user={email}")

    ocr_pdfs = _pick_pdfs(args.pdf_dir, args.ocr_pdfs)
    crop_pdfs = _pick_pdfs(args.pdf_dir, args.crop_pdfs)
    record("pdf_dataset_loaded", True, f"ocr={len(ocr_pdfs)}, crop={len(crop_pdfs)}")

    ocr_task = _submit_ocr(args.base_url, token, ocr_pdfs)
    ocr_task_state = _poll_task(args.base_url, token, ocr_task, timeout_sec=360, endpoint="ocr")
    ocr_ok = str(ocr_task_state.get("status", "")) == "success"
    record("ocr_background_task", ocr_ok, f"task={ocr_task}", {"status": ocr_task_state})

    suborder = ""
    pincode = ""
    try:
        suborder, pincode = _extract_suborder_and_pincode(ocr_pdfs)
        record("extract_suborder_from_pdfs", True, f"suborder={suborder}, pincode={pincode or '-'}")
    except Exception as exc:
        record("extract_suborder_from_pdfs", False, str(exc))

    if ocr_ok:
        with tempfile.TemporaryDirectory(prefix="cropperhub_e2e_") as td:
            returns_file = Path(td) / "returns_test.xlsx"
            _create_returns_excel(returns_file, suborder)
            try:
                returns_task = _submit_return_analysis(args.base_url, token, returns_file)
                returns_state = _poll_task(args.base_url, token, returns_task, timeout_sec=240)
                ret_ok = str(returns_state.get("status", "")) == "success"
                record("returns_analysis_background_task", ret_ok, f"task={returns_task}", {"status": returns_state})
            except Exception as exc:
                record("returns_analysis_background_task", False, f"submit/poll exception: {exc}")
    else:
        record("returns_analysis_background_task", False, "Skipped because OCR task did not succeed")

    try:
        selected_pincode = ""
        if args.use_pincode:
            selected_pincode = (args.forced_pincode or "").strip() or (pincode if pincode else "560001")
        crop_task = _submit_crop_meesho(
            args.base_url,
            token,
            crop_pdfs,
            selected_pincode,
            detect_suspicious=bool(args.detect_suspicious),
        )
        crop_state = _poll_task(args.base_url, token, crop_task, timeout_sec=360)
        crop_ok = str(crop_state.get("status", "")) == "success"
        record("crop_meesho_background_task", crop_ok, f"task={crop_task}", {"status": crop_state})
        if crop_ok:
            summary = crop_state.get("summary") if isinstance(crop_state, dict) else {}
            if not isinstance(summary, dict):
                summary = {}
            record(
                "crop_split_summary_fields",
                True,
                "captured",
                {
                    "risk_split_enabled": bool(summary.get("risk_split_enabled")),
                    "risky_orders_matched": int(summary.get("risky_orders_matched") or 0),
                    "risky_pages": int(summary.get("risky_pages") or 0),
                    "pincode_split_enabled": bool(summary.get("pincode_split_enabled")),
                    "selected_pincode_pages": int(summary.get("selected_pincode_pages") or 0),
                    "normal_pages": int(summary.get("normal_pages") or 0),
                },
            )
    except Exception as exc:
        crop_task = ""
        crop_ok = False
        record("crop_meesho_background_task", False, f"submit/poll exception: {exc}")

    if crop_ok:
        try:
            d_status, d_type, d_size = _download_result(args.base_url, token, crop_task)
            record("crop_download_artifact", d_status == 200 and d_size > 0, f"status={d_status}", {"content_type": d_type, "bytes": d_size})
        except Exception as exc:
            record("crop_download_artifact", False, f"exception={exc}")
    else:
        record("crop_download_artifact", False, "Skipped (crop task failed)")

    h_status, h_data = _request("GET", f"{args.base_url.rstrip('/')}/api/history/jobs?limit=20&offset=0&sort=newest", token=token, timeout=20.0)
    history_ok = h_status == 200 and isinstance(h_data, dict) and isinstance(h_data.get("jobs"), list)
    record("history_jobs_list", history_ok, f"status={h_status}", {"jobs_count": len(h_data.get("jobs", [])) if isinstance(h_data, dict) else 0})
    if history_ok and h_data["jobs"]:
        first_id = h_data["jobs"][0].get("id")
        d_status, d_data = _request("GET", f"{args.base_url.rstrip('/')}/api/history/jobs/{first_id}", token=token, timeout=20.0)
        record("history_job_detail", d_status == 200 and isinstance(d_data, dict), f"status={d_status}", {"job_id": first_id})
    else:
        record("history_job_detail", False, "No history job found")

    ok_count = sum(1 for c in report["checks"] if c["ok"])
    fail_count = len(report["checks"]) - ok_count
    report["summary"] = {"passed": ok_count, "failed": fail_count, "total": len(report["checks"])}
    report["ok"] = fail_count == 0
    report["elapsed_sec"] = round(time.perf_counter() - t0, 2)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
