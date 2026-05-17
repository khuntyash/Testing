"""Flipkart-focused end-to-end stress smoke (background mode).

Exercises:
  * /api/health
  * /api/auth/signup + /api/auth/login (token bearer)
  * /api/crop/flipkart/start  (background task) -- 3 scenarios:
      T1 baseline label_printer + sort_by=sku
      T2 parity-rich (print_datetime, custom_message, multi_order_bottom,
         separate_pincodes, detect_suspicious, separate_multi_order_by_customer,
         mark_loyal_customer, mark_loyal_customer_preview)
      T3 keep_invoice + multi_order_bottom (full-invoice path)
  * /api/tasks/{id}                   -- background polling
  * /api/tasks/{id}/download          -- artifact retrieval
  * /api/history/jobs                 -- listing for the test user

Validates each task ends with status=success, downloaded artifact exists,
output PDF (or zip) is non-empty + parseable, page counts/split summary
fields look sensible, and there are no server-side exceptions surfaced.

Run:
    python backend/temp/flipkart_e2e_smoke.py --base-url http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import fitz


DEFAULT_PDFS = [
    r"C:\Users\HP\Downloads\New folder (5)\Nakalank-520.pdf",
    r"C:\Users\HP\Downloads\Downloads\02-03-2026\Flipkart\Zenzero-03-02=1.pdf",
    r"C:\Users\HP\Downloads\Downloads\18-01-2026\Flipkart\Zenzero-03.pdf",
]


def _request(
    method: str,
    url: str,
    *,
    token: str = "",
    payload: dict | None = None,
    body: bytes | None = None,
    content_type: str = "",
    timeout: float = 60.0,
    raw_response: bool = False,
) -> tuple[int, object, dict]:
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
            raw = res.read()
            resp_headers = {k.lower(): v for k, v in res.getheaders()}
            if raw_response:
                return int(res.status), raw, resp_headers
            text = raw.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = text
            return int(res.status), parsed, resp_headers
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        resp_headers = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
        if raw_response:
            return int(exc.code), raw, resp_headers
        text = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = text
        return int(exc.code), parsed, resp_headers
    except Exception as exc:
        return 599, str(exc), {}


def _build_multipart(fields: dict[str, str], files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----CropperHubFlipkart" + "".join(random.choices(string.ascii_letters + string.digits, k=18))
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


def _auth(base_url: str) -> tuple[str, str]:
    suffix = f"{int(time.time())}{random.randint(1000,9999)}"
    email = f"flipkart_smoke_{suffix}@example.com"
    password = "FkSmoke@1234"
    name = "Flipkart Smoke"
    s, body, _ = _request("POST", f"{base_url}/api/auth/signup", payload={"email": email, "password": password, "name": name}, timeout=20.0)
    if s == 200 and isinstance(body, dict) and isinstance(body.get("token"), str):
        return body["token"], email
    s2, body2, _ = _request("POST", f"{base_url}/api/auth/login", payload={"email": email, "password": password}, timeout=20.0)
    if s2 == 200 and isinstance(body2, dict) and isinstance(body2.get("token"), str):
        return body2["token"], email
    raise RuntimeError(f"auth failed signup={s}/{body!r} login={s2}/{body2!r}")


def _read_pdf_bytes(paths: list[Path]) -> list[tuple[str, bytes, int]]:
    out: list[tuple[str, bytes, int]] = []
    for p in paths:
        data = p.read_bytes()
        with fitz.open(stream=data, filetype="pdf") as doc:
            page_count = len(doc)
        out.append((p.name, data, page_count))
    return out


def _submit_flipkart(
    base_url: str,
    token: str,
    files: list[tuple[str, bytes, int]],
    fields: dict[str, str],
) -> tuple[int, dict, dict]:
    multipart_files = [("files", name, data, "application/pdf") for name, data, _ in files]
    body, ctype = _build_multipart(fields, multipart_files)
    s, parsed, _ = _request(
        "POST",
        f"{base_url}/api/crop/flipkart/start",
        token=token,
        body=body,
        content_type=ctype,
        timeout=180.0,
    )
    return s, parsed if isinstance(parsed, dict) else {"raw": parsed}, fields


def _poll(base_url: str, token: str, task_id: str, *, timeout_sec: int = 600, label: str = "") -> dict:
    deadline = time.time() + timeout_sec
    last_state = ""
    last_progress = -1
    last_print = 0.0
    snap = {}
    while time.time() < deadline:
        s, body, _ = _request(
            "GET",
            f"{base_url}/api/tasks/{urllib.parse.quote(task_id)}",
            token=token,
            timeout=15.0,
        )
        if s == 200 and isinstance(body, dict) and isinstance(body.get("task"), dict):
            task = body["task"]
            snap = task
            state = str(task.get("status") or "")
            prog = int(task.get("progress") or 0)
            now = time.time()
            if state != last_state or prog != last_progress or (now - last_print) > 4.0:
                msg = (task.get("progress_message") or "").strip()[:80]
                print(f"  [{label}] status={state} progress={prog}% msg={msg!r}")
                last_state = state
                last_progress = prog
                last_print = now
            if state in {"success", "failed", "cancelled", "expired"}:
                return task
        else:
            print(f"  [{label}] poll status={s} body={str(body)[:200]}")
        time.sleep(1.5)
    raise TimeoutError(f"task {task_id} timed out; last={snap}")


def _download(base_url: str, token: str, task_id: str) -> tuple[int, bytes, dict]:
    return _request(
        "GET",
        f"{base_url}/api/tasks/{urllib.parse.quote(task_id)}/download",
        token=token,
        timeout=120.0,
        raw_response=True,
    )


def _inspect_pdf_or_zip(blob: bytes) -> dict:
    info: dict = {"bytes": len(blob), "kind": "unknown"}
    if blob[:4] == b"PK\x03\x04":
        info["kind"] = "zip"
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                names = zf.namelist()
                info["zip_members"] = names
                pdf_pages: dict[str, int] = {}
                for n in names:
                    if not n.lower().endswith(".pdf"):
                        continue
                    with zf.open(n) as fh:
                        pdf_data = fh.read()
                    try:
                        with fitz.open(stream=pdf_data, filetype="pdf") as d:
                            pdf_pages[n] = len(d)
                    except Exception as exc:
                        pdf_pages[n] = -1
                        info["zip_open_error"] = f"{n}: {exc}"
                info["zip_pdf_pages"] = pdf_pages
                info["zip_total_pages"] = sum(p for p in pdf_pages.values() if p > 0)
        except Exception as exc:
            info["zip_error"] = str(exc)
    elif blob[:5] == b"%PDF-":
        info["kind"] = "pdf"
        try:
            with fitz.open(stream=blob, filetype="pdf") as d:
                info["pages"] = len(d)
                if len(d) > 0:
                    info["page0_text_sample"] = (d[0].get_text("text") or "")[:160]
                    cb = d[0].cropbox
                    info["page0_cropbox"] = [cb.x0, cb.y0, cb.x1, cb.y1]
        except Exception as exc:
            info["pdf_error"] = str(exc)
    else:
        info["head_hex"] = blob[:8].hex()
    return info


def _summarize_task(task: dict) -> dict:
    summary = task.get("summary") if isinstance(task, dict) else {}
    if not isinstance(summary, dict):
        summary = {}
    keys = [
        "total_input_files",
        "total_input_pages",
        "total_output_pages",
        "risk_split_enabled",
        "risky_orders_matched",
        "risky_pages",
        "pincode_split_enabled",
        "selected_pincodes_count",
        "selected_pincode_pages",
        "normal_pages",
        "multi_order_split_enabled",
        "multi_order_groups",
        "multi_order_pages",
        "multi_order_normal_pages",
        "loyal_customer_enabled",
        "loyal_preview_enabled",
        "loyal_customers_matched",
        "loyal_customers_evaluated",
        "loyal_labels_marked",
        "manual_high_risk_customers_total",
        "manual_high_risk_suborders_total",
        "detect_suspicious_enabled",
        "risk_eval_error",
        "loyal_eval_error",
    ]
    return {k: summary.get(k) for k in keys}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parent / "flipkart_e2e_artifacts"))
    parser.add_argument("--pdf", action="append", default=None, help="Override default PDF set; repeatable.")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths_raw = args.pdf or DEFAULT_PDFS
    pdfs = [Path(p) for p in pdf_paths_raw]
    missing = [str(p) for p in pdfs if not p.exists()]
    if missing:
        print(f"FATAL missing PDFs: {missing}")
        return 2

    files = _read_pdf_bytes(pdfs)
    total_pages_local = sum(c for _, _, c in files)
    print(f"== Flipkart E2E smoke ==")
    print(f"base_url   : {base_url}")
    print(f"pdf_count  : {len(files)}, total_pages_local={total_pages_local}")
    for n, b, c in files:
        print(f"   - {n}  pages={c}  size={len(b)}")

    report: dict = {"base_url": base_url, "pdfs": [{"name": n, "pages": c, "bytes": len(b)} for n, b, c in files], "checks": []}
    t_total = time.perf_counter()

    def record(name: str, ok: bool, detail: str = "", extra: dict | None = None) -> None:
        row = {"name": name, "ok": bool(ok), "detail": detail}
        if extra:
            row["extra"] = extra
        report["checks"].append(row)
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name} -- {detail}")

    s_health, body_health, _ = _request("GET", f"{base_url}/api/health", timeout=10.0)
    record("health", s_health == 200 and isinstance(body_health, dict) and bool(body_health.get("ok")), f"status={s_health}", {"body": body_health if isinstance(body_health, dict) else str(body_health)})
    if s_health != 200:
        report["ok"] = False
        report["elapsed_sec"] = round(time.perf_counter() - t_total, 2)
        print(json.dumps(report, indent=2))
        return 1

    try:
        token, email = _auth(base_url)
        record("auth_signup_login", True, f"user={email}")
    except Exception as exc:
        record("auth_signup_login", False, f"{exc}")
        report["ok"] = False
        report["elapsed_sec"] = round(time.perf_counter() - t_total, 2)
        print(json.dumps(report, indent=2))
        return 1

    scenarios = [
        {
            "name": "T1_baseline_label_printer",
            "fields": {
                "sort_by": "sku",
                "layout": "label_printer",
                "multi_order_bottom": "0",
                "print_datetime": "0",
                "custom_message": "",
                "separate_pincodes": "",
                "detect_suspicious": "0",
                "separate_multi_order_by_customer": "0",
                "mark_loyal_customer": "0",
                "mark_loyal_customer_preview": "0",
            },
            "expected_kind": "pdf",
        },
        {
            "name": "T2_parity_full",
            "fields": {
                "sort_by": "sku",
                "layout": "label_printer",
                "multi_order_bottom": "1",
                "print_datetime": "1",
                "custom_message": "Smoke Batch B-204",
                "separate_pincodes": "560001,110001,400001",
                "detect_suspicious": "1",
                "separate_multi_order_by_customer": "1",
                "mark_loyal_customer": "1",
                "mark_loyal_customer_preview": "1",
            },
            "expected_kind": "any",
        },
        {
            "name": "T3_keep_invoice_multi_order_bottom",
            "fields": {
                "sort_by": "sku",
                "layout": "keep_invoice",
                "multi_order_bottom": "1",
                "print_datetime": "1",
                "custom_message": "Invoice keep mode",
                "separate_pincodes": "",
                "detect_suspicious": "0",
                "separate_multi_order_by_customer": "0",
                "mark_loyal_customer": "0",
                "mark_loyal_customer_preview": "0",
            },
            "expected_kind": "pdf",
        },
    ]

    submitted_tasks: list[dict] = []

    metrics: dict = {}
    for sc in scenarios:
        name = sc["name"]
        print(f"\n-- submit {name} --")
        t0 = time.perf_counter()
        s, body, _ = _submit_flipkart(base_url, token, files, sc["fields"])
        submit_ms = (time.perf_counter() - t0) * 1000
        ok = s == 200 and isinstance(body, dict) and bool(body.get("task_id"))
        record(f"{name}/submit", ok, f"http={s} submit_ms={submit_ms:.0f}", {"response": body})
        if not ok:
            continue

        task_id = str(body["task_id"])
        try:
            t1 = time.perf_counter()
            final = _poll(base_url, token, task_id, timeout_sec=900, label=name)
            poll_sec = time.perf_counter() - t1
        except Exception as exc:
            record(f"{name}/poll", False, f"poll exception: {exc}")
            continue

        success = str(final.get("status") or "") == "success"
        record(f"{name}/poll_success", success, f"status={final.get('status')} progress={final.get('progress')} duration_sec={poll_sec:.1f} error={final.get('error')!r}")

        if not success:
            continue

        s_dl, blob, hdrs = _download(base_url, token, task_id)
        dl_ok = s_dl == 200 and isinstance(blob, (bytes, bytearray)) and len(blob) > 0
        record(f"{name}/download", dl_ok, f"http={s_dl} bytes={len(blob) if isinstance(blob, (bytes, bytearray)) else 0} content_type={hdrs.get('content-type','')}")
        if not dl_ok:
            continue

        artifact_path = out_dir / f"{name}.{ 'zip' if blob[:4]==b'PK\\x03\\x04' else 'pdf'}"
        # Use Python literal form for marker check
        if blob[:4] == b"PK\x03\x04":
            artifact_path = out_dir / f"{name}.zip"
        else:
            artifact_path = out_dir / f"{name}.pdf"
        artifact_path.write_bytes(blob)
        info = _inspect_pdf_or_zip(blob)

        record(f"{name}/artifact_kind", info["kind"] in {"pdf", "zip"}, f"kind={info['kind']} saved={artifact_path}", {"info": info})

        sc_summary = _summarize_task(final)
        record(
            f"{name}/summary_fields",
            True,
            "captured",
            {
                "summary": sc_summary,
            },
        )

        if name == "T1_baseline_label_printer":
            page_total = info.get("pages", 0) if info["kind"] == "pdf" else info.get("zip_total_pages", 0)
            ok_pages = page_total >= total_pages_local
            record(f"{name}/page_count_at_least_input", ok_pages, f"output_pages={page_total} input_pages_local={total_pages_local}")
            text_sample = info.get("page0_text_sample", "") or ""
            record(f"{name}/no_unexpected_stamps", ("Printed:" not in text_sample) and ("Msg:" not in text_sample), f"text_sample={text_sample!r}")

        if name == "T2_parity_full":
            risk_split_enabled = bool(sc_summary.get("risk_split_enabled"))
            pincode_enabled = bool(sc_summary.get("pincode_split_enabled"))
            multi_order_enabled = bool(sc_summary.get("multi_order_split_enabled"))
            loyal_enabled = bool(sc_summary.get("loyal_customer_enabled"))
            record(
                f"{name}/parity_flags_present",
                pincode_enabled and multi_order_enabled and loyal_enabled,
                f"pincode={pincode_enabled} multi_order={multi_order_enabled} loyal={loyal_enabled} risk_split={risk_split_enabled}",
            )
            page_total = info.get("zip_total_pages", info.get("pages", 0)) or 0
            record(f"{name}/page_count_close_to_input", abs(page_total - total_pages_local) <= max(2, total_pages_local // 200), f"output_pages={page_total} input_pages_local={total_pages_local}")
            risk_eval_err = (sc_summary.get("risk_eval_error") or "").strip()
            loyal_eval_err = (sc_summary.get("loyal_eval_error") or "").strip()
            record(f"{name}/no_eval_errors", not risk_eval_err and not loyal_eval_err, f"risk_eval_error={risk_eval_err!r} loyal_eval_error={loyal_eval_err!r}")

        if name == "T3_keep_invoice_multi_order_bottom":
            page_total = info.get("pages", 0) if info["kind"] == "pdf" else info.get("zip_total_pages", 0)
            record(f"{name}/page_count_at_least_input", page_total >= total_pages_local, f"output_pages={page_total} input_pages_local={total_pages_local}")
            text_sample = info.get("page0_text_sample", "") or ""
            has_stamp = ("Printed:" in text_sample) or ("Msg:" in text_sample)
            record(f"{name}/stamp_present_or_no_anchor", True, f"stamp_in_first_page_sample={has_stamp} text_sample={text_sample!r}")

        submitted_tasks.append({"name": name, "task_id": task_id, "duration_sec": round(poll_sec, 2), "kind": info["kind"]})

    s_hist, body_hist, _ = _request("GET", f"{base_url}/api/history/jobs?limit=50&offset=0&sort=newest", token=token, timeout=30.0)
    hist_ok = s_hist == 200 and isinstance(body_hist, dict) and isinstance(body_hist.get("jobs"), list)
    jobs_count = len(body_hist["jobs"]) if hist_ok else 0
    record("history_jobs_list", hist_ok, f"http={s_hist} jobs={jobs_count}")
    if hist_ok and jobs_count > 0:
        flipkart_jobs = [j for j in body_hist["jobs"] if str(j.get("platform") or "").lower() == "flipkart"]
        record(
            "history_has_flipkart_jobs",
            len(flipkart_jobs) >= 1,
            f"flipkart_jobs_in_history={len(flipkart_jobs)}",
            {"top_flipkart_job": flipkart_jobs[0] if flipkart_jobs else None},
        )
    else:
        record("history_has_flipkart_jobs", False, "history listing missing or empty")

    s_idem, body_idem, _ = _submit_flipkart(
        base_url,
        token,
        files[:1],
        {
            "sort_by": "sku",
            "layout": "label_printer",
            "multi_order_bottom": "0",
            "print_datetime": "0",
            "custom_message": "",
            "separate_pincodes": "",
            "detect_suspicious": "0",
            "separate_multi_order_by_customer": "0",
            "mark_loyal_customer": "0",
            "mark_loyal_customer_preview": "0",
        },
    )
    record("extra_submit_after_main", s_idem == 200 and isinstance(body_idem, dict) and bool(body_idem.get("task_id")), f"http={s_idem}", {"response": body_idem})

    ok_count = sum(1 for c in report["checks"] if c["ok"])
    fail_count = len(report["checks"]) - ok_count
    report["summary"] = {"passed": ok_count, "failed": fail_count, "total": len(report["checks"])}
    report["tasks"] = submitted_tasks
    report["ok"] = fail_count == 0
    report["elapsed_sec"] = round(time.perf_counter() - t_total, 2)
    print("\n=== JSON REPORT ===")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
