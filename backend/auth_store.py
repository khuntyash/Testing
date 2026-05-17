from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DB_PATH = Path(__file__).resolve().parent / "labelhub.db"
DB_PATH = Path(os.getenv("LABELHUB_DB_PATH", str(_DEFAULT_DB_PATH))).expanduser().resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
SESSION_TTL_DAYS = 30
PBKDF2_ITERATIONS = 200_000
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_postgres_backend() -> bool:
    return (os.getenv("DB_BACKEND", "sqlite") or "sqlite").strip().lower() in {"postgres", "postgresql"}


def _normalize_sql_for_backend(sql: str, *, postgres: bool) -> str:
    text = str(sql or "")
    if not postgres:
        return text
    stripped = text.strip().upper()
    if stripped == "BEGIN IMMEDIATE":
        return "BEGIN"
    # psycopg treats literal percent signs in SQL as placeholder markers, so
    # escape them before converting sqlite-style "?" placeholders.
    return text.replace("%", "%%").replace("?", "%s")


class _DBConn:
    def __init__(self, raw_conn: Any, *, postgres: bool) -> None:
        self._raw_conn = raw_conn
        self._postgres = bool(postgres)

    def __enter__(self):
        self._raw_conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._raw_conn.__exit__(exc_type, exc, tb)

    def execute(self, sql: str, params: tuple | list | None = None):
        safe_params = tuple(params or ())
        return self._raw_conn.execute(
            _normalize_sql_for_backend(sql, postgres=self._postgres),
            safe_params,
        )

    def __getattr__(self, name: str):
        return getattr(self._raw_conn, name)


def _db_connect() -> _DBConn:
    if _is_postgres_backend():
        try:
            import psycopg  # type: ignore
            from psycopg.rows import dict_row  # type: ignore
        except Exception as exc:
            raise RuntimeError("DB_BACKEND=postgres requires psycopg installed") from exc
        dsn = (os.getenv("DATABASE_URL", "") or "").strip()
        if not dsn:
            raise RuntimeError("DB_BACKEND=postgres requires DATABASE_URL")
        raw_conn = psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10)  # type: ignore[attr-defined]
        return _DBConn(raw_conn, postgres=True)
    raw_conn = sqlite3.connect(DB_PATH, timeout=30)
    raw_conn.row_factory = sqlite3.Row
    raw_conn.execute("PRAGMA journal_mode=WAL")
    raw_conn.execute("PRAGMA busy_timeout=5000")
    raw_conn.execute("PRAGMA foreign_keys=ON")
    return _DBConn(raw_conn, postgres=False)


def init_db() -> None:
    with _db_connect() as conn:
        if _is_postgres_backend():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    wallet_balance INTEGER NOT NULL DEFAULT 0,
                    is_premium INTEGER NOT NULL DEFAULT 0,
                    premium_since TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_balance INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_since TEXT NOT NULL DEFAULT ''")
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    wallet_balance INTEGER NOT NULL DEFAULT 0,
                    is_premium INTEGER NOT NULL DEFAULT 0,
                    premium_since TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
            if "is_admin" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            if "wallet_balance" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN wallet_balance INTEGER NOT NULL DEFAULT 0")
            if "is_premium" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER NOT NULL DEFAULT 0")
            if "premium_since" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN premium_since TEXT NOT NULL DEFAULT ''")
        admin_count = int(conn.execute("SELECT COUNT(1) AS cnt FROM users WHERE is_admin = 1").fetchone()["cnt"])
        if admin_count == 0:
            first_user = conn.execute("SELECT id, email FROM users ORDER BY id ASC LIMIT 1").fetchone()
            if first_user:
                conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (first_user["id"],))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
        if _is_postgres_backend():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_role_audit (
                    id BIGSERIAL PRIMARY KEY,
                    actor_user_id BIGINT,
                    target_user_id BIGINT NOT NULL,
                    prev_is_admin INTEGER NOT NULL,
                    next_is_admin INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_role_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_user_id INTEGER,
                    target_user_id INTEGER NOT NULL,
                    prev_is_admin INTEGER NOT NULL,
                    next_is_admin INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_role_audit_created ON admin_role_audit(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_role_audit_target ON admin_role_audit(target_user_id)")
        if _is_postgres_backend():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wallet_transactions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    actor_user_id BIGINT,
                    tx_type TEXT NOT NULL,
                    delta INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL
                )
                """
            )
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wallet_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    actor_user_id INTEGER,
                    tx_type TEXT NOT NULL,
                    delta INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL
                )
                """
            )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wallet_tx_user_id ON wallet_transactions(user_id, id DESC)")
        if _is_postgres_backend():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS premium_members (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL UNIQUE,
                    email TEXT NOT NULL,
                    first_credit_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS premium_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL UNIQUE,
                    email TEXT NOT NULL,
                    first_credit_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_premium_members_email ON premium_members(email)")
        # Backfill premium flags from historical positive credits/wallet balances.
        now_iso = _utc_now().isoformat()
        conn.execute(
            """
            UPDATE users
            SET is_premium = 1,
                premium_since = CASE
                    WHEN COALESCE(NULLIF(premium_since, ''), '') <> '' THEN premium_since
                    ELSE COALESCE(created_at, ?)
                END
            WHERE COALESCE(wallet_balance, 0) > 0
            """,
            (now_iso,),
        )
        credit_rows = conn.execute(
            """
            SELECT user_id, MIN(created_at) AS first_credit_at
            FROM wallet_transactions
            WHERE delta > 0
            GROUP BY user_id
            """
        ).fetchall()
        for row in credit_rows:
            uid = int(row["user_id"] or 0)
            if uid <= 0:
                continue
            first_credit_at = str(row["first_credit_at"] or "").strip() or now_iso
            user_row = conn.execute(
                "SELECT email, premium_since FROM users WHERE id = ?",
                (uid,),
            ).fetchone()
            if not user_row:
                continue
            conn.execute(
                """
                UPDATE users
                SET is_premium = 1,
                    premium_since = CASE
                        WHEN COALESCE(NULLIF(premium_since, ''), '') <> '' THEN premium_since
                        ELSE ?
                    END
                WHERE id = ?
                """,
                (first_credit_at, uid),
            )
            email = str(user_row["email"] or "").strip().lower()
            if not email:
                continue
            if _is_postgres_backend():
                conn.execute(
                    """
                    INSERT INTO premium_members (user_id, email, first_credit_at, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (uid, email, first_credit_at, now_iso),
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO premium_members (user_id, email, first_credit_at, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (uid, email, first_credit_at, now_iso),
                )


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex()


def _create_password_record(password: str) -> tuple[str, str]:
    salt_hex = secrets.token_hex(16)
    password_hash = _hash_password(password, salt_hex)
    return salt_hex, password_hash


def create_user(name: str, email: str, password: str) -> dict:
    clean_email = email.strip().lower()
    clean_name = (name or "").strip() or clean_email.split("@")[0] or "User"
    clean_password = password or ""
    if "@" not in clean_email:
        raise ValueError("Please enter a valid email address.")
    if len(clean_password) < 8:
        raise ValueError("Password must be at least 8 characters.")

    salt_hex, password_hash = _create_password_record(clean_password)
    created_at = _utc_now().isoformat()
    is_admin = 1 if clean_email in ADMIN_EMAILS else 0
    with _db_connect() as conn:
        if not is_admin:
            existing_users = int(conn.execute("SELECT COUNT(1) AS cnt FROM users").fetchone()["cnt"])
            if existing_users == 0:
                is_admin = 1
        try:
            if _is_postgres_backend():
                cur = conn.execute(
                    """
                    INSERT INTO users (email, name, is_admin, password_salt, password_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (clean_email, clean_name, is_admin, salt_hex, password_hash, created_at),
                )
                row = cur.fetchone()
                user_id = int(row["id"]) if row else 0
            else:
                cur = conn.execute(
                    """
                    INSERT INTO users (email, name, is_admin, password_salt, password_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (clean_email, clean_name, is_admin, salt_hex, password_hash, created_at),
                )
                user_id = int(cur.lastrowid)
        except Exception as exc:
            raise ValueError("That email is already registered.") from exc
    return {
        "id": user_id,
        "email": clean_email,
        "name": clean_name,
        "is_admin": bool(is_admin),
        "is_premium": False,
    }


def authenticate_user(email: str, password: str) -> dict | None:
    clean_email = email.strip().lower()
    with _db_connect() as conn:
        row = conn.execute(
            "SELECT id, email, name, is_admin, is_premium, password_salt, password_hash FROM users WHERE email = ?",
            (clean_email,),
        ).fetchone()
    if not row:
        return None

    incoming_hash = _hash_password(password or "", row["password_salt"])
    if incoming_hash != row["password_hash"]:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "is_admin": bool(row["is_admin"]),
        "is_premium": bool(row["is_premium"]),
    }


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    now = _utc_now()
    expires = now + timedelta(days=SESSION_TTL_DAYS)
    with _db_connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, now.isoformat(), expires.isoformat()),
        )
    return token


def get_session_user(token: str) -> dict | None:
    if not token:
        return None
    now_iso = _utc_now().isoformat()
    with _db_connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, u.name, u.is_admin, u.is_premium, s.expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] <= now_iso:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "is_admin": bool(row["is_admin"]),
        "is_premium": bool(row["is_premium"]),
    }


def delete_session(token: str) -> None:
    if not token:
        return
    with _db_connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def update_user_name(user_id: int, name: str) -> dict:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Name cannot be empty.")
    with _db_connect() as conn:
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (clean_name, user_id))
        row = conn.execute("SELECT id, email, name, is_admin, is_premium FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise ValueError("User not found.")
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "is_admin": bool(row["is_admin"]),
        "is_premium": bool(row["is_premium"]),
    }


def _normalize_search_query(query: str | None) -> str:
    return (query or "").strip()


def _user_search_filter(query: str) -> tuple[str, list[object]]:
    """Builds a `WHERE` fragment + params that match name/email substrings."""
    if not query:
        return "", []
    pattern = f"%{query.lower()}%"
    return " AND (LOWER(name) LIKE ? OR LOWER(email) LIKE ?)", [pattern, pattern]


def list_users(*, query: str | None = None, limit: int = 20, offset: int = 0) -> list[dict]:
    """Lists users with optional name/email substring search and pagination.

    Results are ordered by id ascending so admins see the original join order;
    pagination is clamped to safe bounds.
    """
    safe_limit = min(max(int(limit), 1), 100)
    safe_offset = max(int(offset), 0)
    clean_query = _normalize_search_query(query)
    where_sql, params = _user_search_filter(clean_query)
    sql = (
        "SELECT id, email, name, is_admin, is_premium, wallet_balance, created_at "
        "FROM users WHERE 1=1" + where_sql + " ORDER BY id ASC LIMIT ? OFFSET ?"
    )
    params = [*params, safe_limit, safe_offset]
    with _db_connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "id": int(row["id"]),
            "email": row["email"],
            "name": row["name"],
            "is_admin": bool(row["is_admin"]),
            "is_premium": bool(row["is_premium"]),
            "wallet_balance": int(row["wallet_balance"] or 0),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def list_users_cursor(*, query: str | None = None, limit: int = 20, cursor: int | None = None) -> tuple[list[dict], int | None]:
    """Cursor-based user listing for large datasets.

    Returns rows ordered by id ASC, starting strictly after `cursor` when provided.
    """
    safe_limit = min(max(int(limit), 1), 100)
    clean_query = _normalize_search_query(query)
    where_sql, params = _user_search_filter(clean_query)
    cursor_sql = ""
    cursor_params: list[object] = []
    if cursor is not None:
        cursor_sql = " AND id > ?"
        cursor_params = [int(cursor)]
    sql = (
        "SELECT id, email, name, is_admin, is_premium, wallet_balance, created_at "
        "FROM users WHERE 1=1"
        + where_sql
        + cursor_sql
        + " ORDER BY id ASC LIMIT ?"
    )
    all_params = [*params, *cursor_params, safe_limit + 1]
    with _db_connect() as conn:
        rows = conn.execute(sql, tuple(all_params)).fetchall()
    has_more = len(rows) > safe_limit
    page_rows = rows[:safe_limit]
    items = [
        {
            "id": int(row["id"]),
            "email": row["email"],
            "name": row["name"],
            "is_admin": bool(row["is_admin"]),
            "is_premium": bool(row["is_premium"]),
            "wallet_balance": int(row["wallet_balance"] or 0),
            "created_at": row["created_at"],
        }
        for row in page_rows
    ]
    next_cursor = items[-1]["id"] if has_more and items else None
    return items, next_cursor


def count_users(*, query: str | None = None) -> int:
    """Counts users matching the same filter rules as `list_users`."""
    clean_query = _normalize_search_query(query)
    where_sql, params = _user_search_filter(clean_query)
    sql = "SELECT COUNT(1) AS cnt FROM users WHERE 1=1" + where_sql
    with _db_connect() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
    return int(row["cnt"] if row else 0)


def _insert_admin_role_audit(
    conn: sqlite3.Connection,
    *,
    actor_user_id: int | None,
    target_user_id: int,
    prev_is_admin: int,
    next_is_admin: int,
) -> None:
    conn.execute(
        """
        INSERT INTO admin_role_audit (actor_user_id, target_user_id, prev_is_admin, next_is_admin, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            actor_user_id if actor_user_id is not None else None,
            int(target_user_id),
            int(prev_is_admin),
            int(next_is_admin),
            _utc_now().isoformat(),
        ),
    )


def set_user_admin_role(user_id: int, *, is_admin: bool, actor_user_id: int | None = None) -> dict:
    """Toggles a user's admin flag. Refuses to demote the only remaining admin."""
    target_id = int(user_id)
    next_flag = 1 if is_admin else 0
    with _db_connect() as conn:
        row = conn.execute(
            "SELECT id, email, name, is_admin, is_premium, created_at FROM users WHERE id = ?",
            (target_id,),
        ).fetchone()
        if not row:
            raise ValueError("User not found.")
        current_flag = 1 if bool(row["is_admin"]) else 0
        if current_flag == next_flag:
            return {
                "id": int(row["id"]),
                "email": row["email"],
                "name": row["name"],
                "is_admin": bool(row["is_admin"]),
                "is_premium": bool(row["is_premium"]),
                "created_at": row["created_at"],
            }
        if current_flag == 1 and next_flag == 0:
            admin_count = int(
                conn.execute("SELECT COUNT(1) AS cnt FROM users WHERE is_admin = 1").fetchone()["cnt"]
            )
            if admin_count <= 1:
                raise ValueError("Cannot remove the last remaining admin.")
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (next_flag, target_id))
        _insert_admin_role_audit(
            conn,
            actor_user_id=actor_user_id,
            target_user_id=target_id,
            prev_is_admin=current_flag,
            next_is_admin=next_flag,
        )
        updated = conn.execute(
            "SELECT id, email, name, is_admin, is_premium, created_at FROM users WHERE id = ?",
            (target_id,),
        ).fetchone()
    return {
        "id": int(updated["id"]),
        "email": updated["email"],
        "name": updated["name"],
        "is_admin": bool(updated["is_admin"]),
        "is_premium": bool(updated["is_premium"]),
        "created_at": updated["created_at"],
    }


def set_users_admin_role_bulk(
    *,
    user_ids: list[int],
    is_admin: bool,
    actor_user_id: int | None = None,
) -> list[dict]:
    clean_ids = []
    seen = set()
    for raw in user_ids or []:
        try:
            uid = int(raw)
        except Exception:
            continue
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        clean_ids.append(uid)
    if not clean_ids:
        raise ValueError("No valid users selected.")

    next_flag = 1 if is_admin else 0
    placeholders = ",".join("?" for _ in clean_ids)
    with _db_connect() as conn:
        rows = conn.execute(
            f"SELECT id, email, name, is_admin, is_premium, created_at FROM users WHERE id IN ({placeholders})",
            tuple(clean_ids),
        ).fetchall()
        found_ids = {int(r["id"]) for r in rows}
        if len(found_ids) != len(clean_ids):
            raise ValueError("One or more users were not found.")

        if next_flag == 0:
            currently_admin_targets = [r for r in rows if bool(r["is_admin"])]
            if currently_admin_targets:
                admin_count = int(
                    conn.execute("SELECT COUNT(1) AS cnt FROM users WHERE is_admin = 1").fetchone()["cnt"]
                )
                if admin_count - len(currently_admin_targets) < 1:
                    raise ValueError("Cannot remove the last remaining admin.")

        # Keep update order deterministic for UI responses.
        row_map = {int(r["id"]): r for r in rows}
        ordered_rows = [row_map[uid] for uid in clean_ids]

        updated_items: list[dict] = []
        for row in ordered_rows:
            prev_flag = 1 if bool(row["is_admin"]) else 0
            if prev_flag != next_flag:
                conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (next_flag, int(row["id"])))
                _insert_admin_role_audit(
                    conn,
                    actor_user_id=actor_user_id,
                    target_user_id=int(row["id"]),
                    prev_is_admin=prev_flag,
                    next_is_admin=next_flag,
                )
            updated_items.append(
                {
                    "id": int(row["id"]),
                    "email": row["email"],
                    "name": row["name"],
                    "is_admin": bool(next_flag),
                    "is_premium": bool(row["is_premium"]),
                    "created_at": row["created_at"],
                }
            )
    return updated_items


def _audit_filter_sql(
    actor_query: str | None = None,
    target_query: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    clean_actor = (actor_query or "").strip().lower()
    clean_target = (target_query or "").strip().lower()
    clean_from = (from_date or "").strip()
    clean_to = (to_date or "").strip()
    if clean_actor:
        clauses.append("(LOWER(actor.email) LIKE ? OR LOWER(actor.name) LIKE ?)")
        actor_pattern = f"%{clean_actor}%"
        params.extend([actor_pattern, actor_pattern])
    if clean_target:
        clauses.append("(LOWER(target.email) LIKE ? OR LOWER(target.name) LIKE ?)")
        target_pattern = f"%{clean_target}%"
        params.extend([target_pattern, target_pattern])
    if clean_from:
        clauses.append("a.created_at >= ?")
        params.append(clean_from)
    if clean_to:
        clauses.append("a.created_at <= ?")
        params.append(clean_to)
    if not clauses:
        return "", []
    return " WHERE " + " AND ".join(clauses), params


def list_admin_role_audit(
    *,
    limit: int = 20,
    offset: int = 0,
    actor_query: str | None = None,
    target_query: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict]:
    safe_limit = min(max(int(limit), 1), 100)
    safe_offset = max(int(offset), 0)
    where_sql, params = _audit_filter_sql(
        actor_query=actor_query,
        target_query=target_query,
        from_date=from_date,
        to_date=to_date,
    )
    with _db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT a.id, a.actor_user_id, a.target_user_id, a.prev_is_admin, a.next_is_admin, a.created_at,
                   actor.email AS actor_email, actor.name AS actor_name,
                   target.email AS target_email, target.name AS target_name
            FROM admin_role_audit a
            LEFT JOIN users actor ON actor.id = a.actor_user_id
            LEFT JOIN users target ON target.id = a.target_user_id
            {where_sql}
            ORDER BY a.id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, safe_limit, safe_offset),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "actor_user_id": row["actor_user_id"],
            "actor_email": row["actor_email"] or "",
            "actor_name": row["actor_name"] or "",
            "target_user_id": row["target_user_id"],
            "target_email": row["target_email"] or "",
            "target_name": row["target_name"] or "",
            "prev_is_admin": bool(row["prev_is_admin"]),
            "next_is_admin": bool(row["next_is_admin"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def list_admin_role_audit_cursor(
    *,
    limit: int = 20,
    cursor: int | None = None,
    actor_query: str | None = None,
    target_query: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> tuple[list[dict], int | None]:
    safe_limit = min(max(int(limit), 1), 100)
    where_sql, params = _audit_filter_sql(
        actor_query=actor_query,
        target_query=target_query,
        from_date=from_date,
        to_date=to_date,
    )
    cursor_clause = " AND a.id < ?" if where_sql else " WHERE a.id < ?"
    cursor_params: list[object] = []
    if cursor is not None:
        cursor_params = [int(cursor)]
    with _db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT a.id, a.actor_user_id, a.target_user_id, a.prev_is_admin, a.next_is_admin, a.created_at,
                   actor.email AS actor_email, actor.name AS actor_name,
                   target.email AS target_email, target.name AS target_name
            FROM admin_role_audit a
            LEFT JOIN users actor ON actor.id = a.actor_user_id
            LEFT JOIN users target ON target.id = a.target_user_id
            {where_sql}
            {" " + cursor_clause if cursor is not None else ""}
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (*params, *cursor_params, safe_limit + 1),
        ).fetchall()
    has_more = len(rows) > safe_limit
    page_rows = rows[:safe_limit]
    items = [
        {
            "id": int(row["id"]),
            "actor_user_id": row["actor_user_id"],
            "actor_email": row["actor_email"] or "",
            "actor_name": row["actor_name"] or "",
            "target_user_id": row["target_user_id"],
            "target_email": row["target_email"] or "",
            "target_name": row["target_name"] or "",
            "prev_is_admin": bool(row["prev_is_admin"]),
            "next_is_admin": bool(row["next_is_admin"]),
            "created_at": row["created_at"],
        }
        for row in page_rows
    ]
    next_cursor = items[-1]["id"] if has_more and items else None
    return items, next_cursor


def count_admin_role_audit(
    *,
    actor_query: str | None = None,
    target_query: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> int:
    where_sql, params = _audit_filter_sql(
        actor_query=actor_query,
        target_query=target_query,
        from_date=from_date,
        to_date=to_date,
    )
    with _db_connect() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(1) AS cnt
            FROM admin_role_audit a
            LEFT JOIN users actor ON actor.id = a.actor_user_id
            LEFT JOIN users target ON target.id = a.target_user_id
            {where_sql}
            """,
            tuple(params),
        ).fetchone()
    return int(row["cnt"] if row else 0)


def list_admin_wallet_credit_audit(
    *,
    limit: int = 20,
    offset: int = 0,
    query: str | None = None,
) -> list[dict]:
    safe_limit = min(max(int(limit), 1), 200)
    safe_offset = max(int(offset), 0)
    params: list[object] = []
    where_sql = "WHERE tx.tx_type = 'admin_credit'"
    clean_query = (query or "").strip().lower()
    if clean_query:
        pattern = f"%{clean_query}%"
        where_sql += (
            " AND ("
            "LOWER(COALESCE(actor.email, '')) LIKE ? OR "
            "LOWER(COALESCE(actor.name, '')) LIKE ? OR "
            "LOWER(COALESCE(target.email, '')) LIKE ? OR "
            "LOWER(COALESCE(target.name, '')) LIKE ? OR "
            "LOWER(COALESCE(tx.note, '')) LIKE ?"
            ")"
        )
        params.extend([pattern, pattern, pattern, pattern, pattern])
    with _db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT tx.id, tx.user_id, tx.actor_user_id, tx.tx_type, tx.delta, tx.balance_after, tx.note, tx.created_at,
                   actor.email AS actor_email, actor.name AS actor_name,
                   target.email AS target_email, target.name AS target_name
            FROM wallet_transactions tx
            LEFT JOIN users actor ON actor.id = tx.actor_user_id
            LEFT JOIN users target ON target.id = tx.user_id
            {where_sql}
            ORDER BY tx.id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, safe_limit, safe_offset),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "target_user_id": int(row["user_id"] or 0),
            "target_email": row["target_email"] or "",
            "target_name": row["target_name"] or "",
            "actor_user_id": int(row["actor_user_id"] or 0),
            "actor_email": row["actor_email"] or "",
            "actor_name": row["actor_name"] or "",
            "tx_type": row["tx_type"] or "",
            "delta": int(row["delta"] or 0),
            "balance_after": int(row["balance_after"] or 0),
            "note": row["note"] or "",
            "created_at": row["created_at"] or "",
        }
        for row in rows
    ]


def count_admin_wallet_credit_audit(*, query: str | None = None) -> int:
    params: list[object] = []
    where_sql = "WHERE tx.tx_type = 'admin_credit'"
    clean_query = (query or "").strip().lower()
    if clean_query:
        pattern = f"%{clean_query}%"
        where_sql += (
            " AND ("
            "LOWER(COALESCE(actor.email, '')) LIKE ? OR "
            "LOWER(COALESCE(actor.name, '')) LIKE ? OR "
            "LOWER(COALESCE(target.email, '')) LIKE ? OR "
            "LOWER(COALESCE(target.name, '')) LIKE ? OR "
            "LOWER(COALESCE(tx.note, '')) LIKE ?"
            ")"
        )
        params.extend([pattern, pattern, pattern, pattern, pattern])
    with _db_connect() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(1) AS cnt
            FROM wallet_transactions tx
            LEFT JOIN users actor ON actor.id = tx.actor_user_id
            LEFT JOIN users target ON target.id = tx.user_id
            {where_sql}
            """,
            tuple(params),
        ).fetchone()
    return int(row["cnt"] if row else 0)


def get_user_id_by_email(email: str) -> int | None:
    clean_email = (email or "").strip().lower()
    if not clean_email:
        return None
    with _db_connect() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (clean_email,)).fetchone()
    return int(row["id"]) if row else None


def _list_wallet_transactions(conn: sqlite3.Connection, user_id: int, *, limit: int = 200) -> list[dict]:
    safe_limit = min(max(int(limit), 1), 500)
    rows = conn.execute(
        """
        SELECT id, tx_type, delta, balance_after, note, created_at
        FROM wallet_transactions
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(user_id), safe_limit),
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "ts": row["created_at"],
            "type": row["tx_type"],
            "delta": int(row["delta"]),
            "balanceAfter": int(row["balance_after"]),
            "label": row["note"] or "",
        }
        for row in rows
    ]


def get_wallet(user_id: int) -> dict:
    target_id = int(user_id)
    with _db_connect() as conn:
        row = conn.execute("SELECT wallet_balance FROM users WHERE id = ?", (target_id,)).fetchone()
        if not row:
            raise ValueError("User not found.")
        return {
            "balance": int(row["wallet_balance"] or 0),
            "transactions": _list_wallet_transactions(conn, target_id),
        }


def add_wallet_credit(
    *,
    user_id: int,
    amount: int,
    note: str | None = None,
    actor_user_id: int | None = None,
) -> dict:
    target_id = int(user_id)
    delta = int(amount)
    if delta <= 0:
        raise ValueError("Amount must be greater than zero.")
    clean_note = (note or "").strip() or "Admin coin credit"
    now = _utc_now().isoformat()
    with _db_connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT wallet_balance FROM users WHERE id = ?", (target_id,)).fetchone()
        if not row:
            raise ValueError("User not found.")
        next_balance = int(row["wallet_balance"] or 0) + delta
        conn.execute("UPDATE users SET wallet_balance = ? WHERE id = ?", (next_balance, target_id))
        conn.execute(
            """
            INSERT INTO wallet_transactions (user_id, actor_user_id, tx_type, delta, balance_after, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_id,
                int(actor_user_id) if actor_user_id is not None else None,
                "admin_credit",
                delta,
                next_balance,
                clean_note,
                now,
            ),
        )
        user_row = conn.execute("SELECT email FROM users WHERE id = ?", (target_id,)).fetchone()
        user_email = str(user_row["email"] or "").strip().lower() if user_row else ""
        conn.execute(
            """
            UPDATE users
            SET is_premium = 1,
                premium_since = CASE
                    WHEN COALESCE(NULLIF(premium_since, ''), '') <> '' THEN premium_since
                    ELSE ?
                END
            WHERE id = ?
            """,
            (now, target_id),
        )
        if user_email:
            if _is_postgres_backend():
                conn.execute(
                    """
                    INSERT INTO premium_members (user_id, email, first_credit_at, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (target_id, user_email, now, now),
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO premium_members (user_id, email, first_credit_at, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (target_id, user_email, now, now),
                )
        transactions = _list_wallet_transactions(conn, target_id)
    return {"balance": next_balance, "transactions": transactions}


def spend_wallet_coins(*, user_id: int, amount: int, note: str | None = None) -> dict:
    target_id = int(user_id)
    delta = int(amount)
    if delta <= 0:
        raise ValueError("Amount must be greater than zero.")
    clean_note = (note or "").strip() or "Premium crop usage"
    now = _utc_now().isoformat()
    with _db_connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT wallet_balance FROM users WHERE id = ?", (target_id,)).fetchone()
        if not row:
            raise ValueError("User not found.")
        current_balance = int(row["wallet_balance"] or 0)
        if current_balance < delta:
            return {
                "ok": False,
                "wallet": {"balance": current_balance, "transactions": _list_wallet_transactions(conn, target_id)},
            }
        next_balance = current_balance - delta
        conn.execute("UPDATE users SET wallet_balance = ? WHERE id = ?", (next_balance, target_id))
        conn.execute(
            """
            INSERT INTO wallet_transactions (user_id, actor_user_id, tx_type, delta, balance_after, note, created_at)
            VALUES (?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                target_id,
                "spend",
                -delta,
                next_balance,
                clean_note,
                now,
            ),
        )
        return {
            "ok": True,
            "wallet": {"balance": next_balance, "transactions": _list_wallet_transactions(conn, target_id)},
        }
