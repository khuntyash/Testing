"""Local smoke test: run Meesho + Flipkart pipelines on a PDF (same file for engineering checks)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import fitz  # noqa: E402


def page_count(path: Path) -> int:
    with fitz.open(path) as doc:
        return len(doc)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python verify_pdf_platforms.py <path-to.pdf>")
        sys.exit(1)
    inp = Path(sys.argv[1]).resolve()
    if not inp.is_file():
        print(f"Not found: {inp}")
        sys.exit(1)

    out_dir = inp.parent
    print(f"Input: {inp}")
    print(f"Pages: {page_count(inp)}")
    print(f"Size bytes: {inp.stat().st_size}")
    print()

    from meesho_service import process_uploaded_paths as meesho_process  # noqa: E402

    out_meesho = out_dir / "verify-output-meesho.pdf"
    t0 = time.perf_counter()
    meesho_process(
        [str(inp)],
        str(out_meesho),
        sort_by="order_id",
        layout="label_printer",
        print_datetime=False,
        multi_order_bottom=False,
        custom_message="",
    )
    dt = time.perf_counter() - t0
    print(f"[Meesho] OK in {dt:.2f}s")
    print(f"  Output: {out_meesho}")
    print(f"  Pages: {page_count(out_meesho)}  Size: {out_meesho.stat().st_size} bytes")
    print()

    from flipkart_service import process_uploaded_paths as flipkart_process  # noqa: E402

    out_fk = out_dir / "verify-output-flipkart.pdf"
    t0 = time.perf_counter()
    flipkart_process(
        [str(inp)],
        str(out_fk),
        layout="label_printer",
        sort_by="sku",
        multi_order_bottom=False,
        print_datetime=False,
        custom_message="",
    )
    dt = time.perf_counter() - t0
    print(f"[Flipkart] OK in {dt:.2f}s")
    print(f"  Output: {out_fk}")
    print(f"  Pages: {page_count(out_fk)}  Size: {out_fk.stat().st_size} bytes")
    print()
    print(
        "Note: If the PDF is Meesho-only, Flipkart output may be visually wrong; "
        "this run still verifies the Flipkart code path executes without crashing.",
    )


if __name__ == "__main__":
    main()
