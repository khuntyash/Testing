"""End-to-end verification for per-platform master OCR storage + downloads.

Spins up the FastAPI app against an isolated temp DB, signs up an admin user,
seeds two platform-specific master CSVs (Meesho + Flipkart) plus a legacy
union CSV, and exercises every download endpoint to confirm:

  * /api/admin/users/{id}/ocr/master/download still serves the legacy union.
  * /api/admin/users/{id}/ocr/master/meesho/download serves only Meesho rows.
  * /api/admin/users/{id}/ocr/master/flipkart/download serves only Flipkart.
  * Admin user enrichment surfaces per-platform availability flags.
  * Unknown platform values are rejected with a 400.

The script writes nothing outside its temp directory.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _bootstrap_paths() -> tuple[Path, Path]:
    workspace = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(workspace))
    tmp_root = Path(tempfile.mkdtemp(prefix="master_per_platform_"))
    db_path = tmp_root / "labelhub.db"
    os.environ["DISABLE_EMBEDDED_WORKER"] = "1"
    return workspace, db_path


def _seed_master_files(user_id: int) -> dict[str, Path]:
    import task_queue

    paths = {
        "meesho": task_queue._user_ocr_master_csv_path(user_id, "meesho"),
        "flipkart": task_queue._user_ocr_master_csv_path(user_id, "flipkart"),
        "legacy": task_queue._user_ocr_master_csv_path(user_id, None),
    }
    header = (
        "Order_id,Name,Address_1,Address_2,Address_3,District,State,Pincode,"
        "Sku,Size,Quantity,Payment_Mode,Courier_Partner,Courier_trans_id\n"
    )
    paths["meesho"].parent.mkdir(parents=True, exist_ok=True)
    paths["meesho"].write_text(
        header
        + "MS_ORDER_001,Asha M,Flat 1,,,Pune,Maharashtra,411001,SKU_M1,M,1,Prepaid,Shadowfax,SF111\n",
        encoding="utf-8",
    )
    paths["flipkart"].write_text(
        header
        + "OD123456789012345678,Bala F,Flat 2,,,Bengaluru,Karnataka,560001,SKU_F1,L,1,Prepaid,E-Kart Logistics,FMP111\n",
        encoding="utf-8",
    )
    paths["legacy"].write_text(
        header
        + "MS_ORDER_001,Asha M,Flat 1,,,Pune,Maharashtra,411001,SKU_M1,M,1,Prepaid,Shadowfax,SF111\n"
        + "OD123456789012345678,Bala F,Flat 2,,,Bengaluru,Karnataka,560001,SKU_F1,L,1,Prepaid,E-Kart Logistics,FMP111\n",
        encoding="utf-8",
    )
    return paths


def _signup_admin(client) -> str:
    res = client.post(
        "/api/auth/signup",
        json={"email": "verify-admin@example.com", "name": "Admin", "password": "Verify-Admin-123!"},
    )
    assert res.status_code == 200, f"signup failed: {res.status_code} {res.text}"
    body = res.json()
    return body["token"]


def main() -> int:
    workspace, db_path = _bootstrap_paths()
    os.environ["LABELHUB_DB_PATH"] = str(db_path)

    # auth_store reads DB_PATH at import time, so monkey-patch it before importing
    # any module that captures DB_PATH.
    import auth_store

    auth_store.DB_PATH = db_path

    import importlib

    # task_queue captures DB_PATH and OCR_MASTER_DIR at import time, so reload
    # against the temp DB.
    if "task_queue" in sys.modules:
        importlib.reload(sys.modules["task_queue"])
    import task_queue

    task_queue.DB_PATH = db_path
    task_queue.OCR_MASTER_DIR = (db_path.parent / "ocr_store").resolve()
    task_queue.RISK_STORE_DIR = (db_path.parent / "risk_store").resolve()

    if "server" in sys.modules:
        importlib.reload(sys.modules["server"])
    import server

    server.DB_PATH = db_path

    from fastapi.testclient import TestClient

    client = TestClient(server.app)

    # Force schema init against temp DB.
    import history_store

    auth_store.init_db()
    history_store.init_history_db()
    task_queue.init_task_queue_db()

    token = _signup_admin(client)

    # First user is auto-promoted to admin by auth_store.init_db()/create_user
    # logic. Confirm that's the case.
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["user"]["is_admin"] is True, "first user should be admin"

    # Find this user's id via the admin users listing.
    listing = client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing.status_code == 200, listing.text
    users = listing.json()["users"]
    assert users, "no users returned"
    user_id = int(users[0]["id"])

    # Seed two distinct master CSVs and a legacy union.
    seeded = _seed_master_files(user_id)
    print(f"seeded user {user_id}:")
    for k, p in seeded.items():
        print(f"  {k}: {p} ({p.stat().st_size} bytes)")

    # Re-run admin enrichment now that files exist.
    listing2 = client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing2.status_code == 200, listing2.text
    me_row = listing2.json()["users"][0]
    print(
        "enriched flags:",
        {k: me_row.get(k) for k in (
            "has_master_ocr_data",
            "has_meesho_master_ocr_data",
            "has_flipkart_master_ocr_data",
            "meesho_master_records",
            "flipkart_master_records",
        )},
    )
    assert me_row["has_master_ocr_data"] is True
    assert me_row["has_meesho_master_ocr_data"] is True
    assert me_row["has_flipkart_master_ocr_data"] is True
    assert me_row["meesho_master_records"] == 1
    assert me_row["flipkart_master_records"] == 1

    auth_h = {"Authorization": f"Bearer {token}"}

    # Legacy union download — backward-compat path.
    legacy_dl = client.get(
        f"/api/admin/users/{user_id}/ocr/master/download", headers=auth_h
    )
    assert legacy_dl.status_code == 200, legacy_dl.text
    legacy_text = legacy_dl.text
    assert "MS_ORDER_001" in legacy_text and "OD123456789012345678" in legacy_text, (
        "legacy CSV should contain both platform suborder ids"
    )

    # Meesho download.
    meesho_dl = client.get(
        f"/api/admin/users/{user_id}/ocr/master/meesho/download", headers=auth_h
    )
    assert meesho_dl.status_code == 200, meesho_dl.text
    meesho_text = meesho_dl.text
    assert "MS_ORDER_001" in meesho_text
    assert "OD123456789012345678" not in meesho_text, "Meesho CSV must not include Flipkart rows"
    cd = meesho_dl.headers.get("content-disposition", "")
    assert "meesho-master-orders" in cd, f"unexpected filename header: {cd}"

    # Flipkart download.
    flipkart_dl = client.get(
        f"/api/admin/users/{user_id}/ocr/master/flipkart/download", headers=auth_h
    )
    assert flipkart_dl.status_code == 200, flipkart_dl.text
    flipkart_text = flipkart_dl.text
    assert "OD123456789012345678" in flipkart_text
    assert "MS_ORDER_001" not in flipkart_text, "Flipkart CSV must not include Meesho rows"

    # Unknown platform should 400.
    bad = client.get(
        f"/api/admin/users/{user_id}/ocr/master/amazon/download", headers=auth_h
    )
    assert bad.status_code == 400, f"expected 400, got {bad.status_code}: {bad.text}"

    # Delete the Meesho file -> per-platform endpoint should 404 even though
    # legacy still works (proves the platform endpoint scopes correctly).
    seeded["meesho"].unlink()
    missing_meesho = client.get(
        f"/api/admin/users/{user_id}/ocr/master/meesho/download", headers=auth_h
    )
    assert missing_meesho.status_code == 404, missing_meesho.text
    legacy_after = client.get(
        f"/api/admin/users/{user_id}/ocr/master/download", headers=auth_h
    )
    assert legacy_after.status_code == 200, legacy_after.text

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
