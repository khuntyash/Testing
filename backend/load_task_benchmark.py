from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import string
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz


def _json_request(
    method: str,
    url: str,
    *,
    token: str = "",
    payload: dict | None = None,
    body: bytes | None = None,
    content_type: str = "",
    timeout: float = 20.0,
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
    boundary = "----LabelHubBoundary" + "".join(random.choices(string.ascii_letters + string.digits, k=16))
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
    body = b"".join(chunks)
    return body, f"multipart/form-data; boundary={boundary}"


def _make_test_pdf(kind: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if kind == "crop":
        text = (
            "INVOICE\n"
            "SKU ID | Description\n"
            "QTY\n1 SKU12345 |\n"
            "TOTAL QTY: 1\n"
            "Product Details"
        )
    else:
        text = (
            "Order ID: ORD-12345\n"
            "Name: Test User\n"
            "Address: Demo Street 12\n"
            "City: Bengaluru\n"
            "State: Karnataka\n"
            "Pincode: 560001\n"
            "Mobile: 9999999999\n"
            "Courier: Delhivery\n"
            "Product Details"
        )
    page.insert_text((40, 80), text, fontsize=12)
    pdf = doc.tobytes()
    doc.close()
    return pdf


def _collect_pdf_paths(pdf_dir: str) -> list[str]:
    root = os.path.abspath(pdf_dir)
    if not os.path.isdir(root):
        raise RuntimeError(f"PDF directory not found: {pdf_dir}")
    out: list[str] = []
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if os.path.isfile(p) and name.lower().endswith(".pdf"):
            out.append(p)
    if not out:
        raise RuntimeError(f"No PDF files found in: {pdf_dir}")
    return sorted(out)


def _create_or_login_user(base_url: str, email: str, password: str, name: str) -> str:
    signup_url = f"{base_url.rstrip('/')}/api/auth/signup"
    login_url = f"{base_url.rstrip('/')}/api/auth/login"
    last_detail: str = "unknown"
    for attempt in range(6):
        status, data = _json_request(
            "POST",
            signup_url,
            payload={"email": email, "password": password, "name": name},
            timeout=25.0,
        )
        if status == 200 and isinstance(data, dict) and isinstance(data.get("token"), str):
            return data["token"]
        status, data = _json_request(
            "POST",
            login_url,
            payload={"email": email, "password": password},
            timeout=25.0,
        )
        if status == 200 and isinstance(data, dict) and isinstance(data.get("token"), str):
            return data["token"]
        last_detail = str(data.get("detail") if isinstance(data, dict) else data)
        time.sleep(min(2.5, 0.4 * (attempt + 1)))
    raise RuntimeError(f"Auth failed for {email}: {last_detail}")


def _submit_crop_task(base_url: str, token: str, pdf_bytes: bytes) -> tuple[float, int, dict | str]:
    url = f"{base_url.rstrip('/')}/api/crop/flipkart/start"
    fields = {"sort_by": "sku", "layout": "label_printer", "multi_order_bottom": "0"}
    files = [("files", "bench-crop.pdf", pdf_bytes, "application/pdf")]
    body, ctype = _build_multipart(fields, files)
    t0 = time.perf_counter()
    status, data = _json_request("POST", url, token=token, body=body, content_type=ctype, timeout=90.0)
    return (time.perf_counter() - t0) * 1000, status, data


def _submit_ocr_task(base_url: str, token: str, pdf_bytes: bytes) -> tuple[float, int, dict | str]:
    qs = urllib.parse.urlencode({"column_preset": "standard_v1"})
    url = f"{base_url.rstrip('/')}/api/ocr/labels/excel/start?{qs}"
    body, ctype = _build_multipart({}, [("files", "bench-ocr.pdf", pdf_bytes, "application/pdf")])
    t0 = time.perf_counter()
    status, data = _json_request("POST", url, token=token, body=body, content_type=ctype, timeout=90.0)
    return (time.perf_counter() - t0) * 1000, status, data


def _get_task_status(base_url: str, token: str, task_id: str) -> tuple[int, dict | str]:
    url = f"{base_url.rstrip('/')}/api/tasks/{urllib.parse.quote(task_id)}"
    return _json_request("GET", url, token=token, timeout=12.0)


def run_benchmark(
    *,
    base_url: str,
    clients: int,
    total_tasks: int,
    submit_concurrency: int,
    ocr_ratio: float,
    max_wait_sec: int,
    pdf_paths: list[str] | None = None,
) -> dict:
    password = "LoadTest@1234"
    run_id = int(time.time())
    tokens: list[str] = []
    for i in range(max(1, clients)):
        email = f"load_user_{run_id}_{i}@example.com"
        token = _create_or_login_user(base_url, email, password, f"Load User {i}")
        tokens.append(token)

    use_real_pdfs = bool(pdf_paths)
    crop_pdf = _make_test_pdf("crop")
    ocr_pdf = _make_test_pdf("ocr")

    submit_latencies: list[float] = []
    submit_failures = 0
    submit_429 = 0
    submit_error_codes: dict[str, int] = {}
    submit_error_samples: list[str] = []
    submitted: list[dict] = []
    lock = threading.Lock()

    def _submit_one(i: int) -> None:
        nonlocal submit_failures, submit_429
        kind = "ocr" if random.random() < ocr_ratio else "crop"
        token = tokens[i % len(tokens)]
        selected_pdf_name = ""
        if use_real_pdfs:
            selected_path = random.choice(pdf_paths or [])
            selected_pdf_name = os.path.basename(selected_path)
            with open(selected_path, "rb") as f:
                selected_bytes = f.read()
        else:
            selected_bytes = ocr_pdf if kind == "ocr" else crop_pdf
        if kind == "ocr":
            latency_ms, status, data = _submit_ocr_task(base_url, token, selected_bytes)
        else:
            latency_ms, status, data = _submit_crop_task(base_url, token, selected_bytes)
        with lock:
            submit_latencies.append(latency_ms)
            if status >= 400:
                submit_failures += 1
                if status == 429:
                    submit_429 += 1
                k = str(status)
                submit_error_codes[k] = submit_error_codes.get(k, 0) + 1
                if len(submit_error_samples) < 10:
                    detail = data.get("detail") if isinstance(data, dict) else str(data)
                    submit_error_samples.append(f"{status}: {detail}")
                return
            task_id = (data or {}).get("task_id") if isinstance(data, dict) else ""
            if not task_id:
                submit_failures += 1
                submit_error_codes["missing_task_id"] = submit_error_codes.get("missing_task_id", 0) + 1
                if len(submit_error_samples) < 10:
                    submit_error_samples.append(f"missing_task_id: {data}")
                return
            submitted.append(
                {
                    "task_id": task_id,
                    "token": token,
                    "kind": kind,
                    "submitted_at": time.time(),
                    "status": "queued",
                    "running_at": None,
                    "finished_at": None,
                    "error": "",
                    "source_pdf": selected_pdf_name,
                }
            )

    wall_start = time.time()
    with ThreadPoolExecutor(max_workers=max(1, submit_concurrency)) as ex:
        futs = [ex.submit(_submit_one, i) for i in range(max(1, total_tasks))]
        for _ in as_completed(futs):
            pass
    submit_done_at = time.time()

    pending = {item["task_id"]: item for item in submitted}
    terminal = {"success", "failed", "cancelled", "expired"}
    deadline = time.time() + max(30, int(max_wait_sec))
    while pending and time.time() < deadline:
        ids = list(pending.keys())
        for task_id in ids:
            item = pending.get(task_id)
            if not item:
                continue
            status_code, data = _get_task_status(base_url, item["token"], task_id)
            if status_code >= 400:
                continue
            task = data.get("task") if isinstance(data, dict) else {}
            s = (task.get("status") or "").strip()
            if not s:
                continue
            item["status"] = s
            if s == "running" and item["running_at"] is None:
                item["running_at"] = time.time()
            if s in terminal:
                item["finished_at"] = time.time()
                item["error"] = (task.get("error") or "") if isinstance(task, dict) else ""
                pending.pop(task_id, None)
        if pending:
            time.sleep(0.6)

    timed_out = len(pending)
    if timed_out:
        for task_id, item in pending.items():
            item["status"] = "timed_out"
            item["finished_at"] = time.time()

    all_items = submitted
    by_kind = {"crop": [], "ocr": []}
    for item in all_items:
        by_kind[item["kind"]].append(item)

    success_count = sum(1 for x in all_items if x["status"] == "success")
    failed_count = sum(1 for x in all_items if x["status"] in {"failed", "cancelled", "expired", "timed_out"})

    queue_waits = [
        (x["running_at"] - x["submitted_at"])
        for x in all_items
        if x["running_at"] is not None and x["submitted_at"] is not None
    ]
    end_to_end = [
        (x["finished_at"] - x["submitted_at"])
        for x in all_items
        if x["finished_at"] is not None and x["submitted_at"] is not None
    ]
    wall_elapsed = max(0.001, time.time() - wall_start)
    throughput = success_count / wall_elapsed

    p95_submit = statistics.quantiles(submit_latencies, n=100)[94] if len(submit_latencies) >= 20 else (
        max(submit_latencies) if submit_latencies else 0.0
    )
    p95_queue_wait = statistics.quantiles(queue_waits, n=100)[94] if len(queue_waits) >= 20 else (
        max(queue_waits) if queue_waits else 0.0
    )
    p95_e2e = statistics.quantiles(end_to_end, n=100)[94] if len(end_to_end) >= 20 else (
        max(end_to_end) if end_to_end else 0.0
    )

    def _kind_summary(kind: str) -> dict:
        arr = by_kind[kind]
        succ = sum(1 for x in arr if x["status"] == "success")
        fail = sum(1 for x in arr if x["status"] in {"failed", "cancelled", "expired", "timed_out"})
        return {"submitted": len(arr), "success": succ, "failed_or_timeout": fail}

    return {
        "clients": clients,
        "total_tasks_requested": total_tasks,
        "submit_concurrency": submit_concurrency,
        "ocr_ratio": ocr_ratio,
        "submitted_ok": len(submitted),
        "submit_failures": submit_failures,
        "submit_429": submit_429,
        "submit_error_codes": submit_error_codes,
        "submit_error_samples": submit_error_samples,
        "submit_p95_ms": round(p95_submit, 2),
        "queue_wait_p95_sec": round(p95_queue_wait, 2),
        "end_to_end_p95_sec": round(p95_e2e, 2),
        "success_count": success_count,
        "failed_or_timeout_count": failed_count,
        "timed_out_count": timed_out,
        "success_rate_pct": round((success_count / len(submitted) * 100.0) if submitted else 0.0, 2),
        "throughput_success_tasks_per_sec": round(throughput, 3),
        "wall_elapsed_sec": round(wall_elapsed, 2),
        "submit_stage_elapsed_sec": round(submit_done_at - wall_start, 2),
        "using_real_pdfs": bool(use_real_pdfs),
        "real_pdf_count": len(pdf_paths or []),
        "by_kind": {"crop": _kind_summary("crop"), "ocr": _kind_summary("ocr")},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live multi-client task queue benchmark")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--clients", type=int, default=40)
    parser.add_argument("--tasks", type=int, default=200)
    parser.add_argument("--submit-concurrency", type=int, default=60)
    parser.add_argument("--ocr-ratio", type=float, default=0.3)
    parser.add_argument("--max-wait-sec", type=int, default=300)
    parser.add_argument("--pdf-dir", default="", help="Optional directory of real PDFs to use")
    args = parser.parse_args()
    pdf_paths = _collect_pdf_paths(args.pdf_dir) if (args.pdf_dir or "").strip() else None

    result = run_benchmark(
        base_url=args.base_url,
        clients=max(1, int(args.clients)),
        total_tasks=max(1, int(args.tasks)),
        submit_concurrency=max(1, int(args.submit_concurrency)),
        ocr_ratio=max(0.0, min(1.0, float(args.ocr_ratio))),
        max_wait_sec=max(60, int(args.max_wait_sec)),
        pdf_paths=pdf_paths,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

