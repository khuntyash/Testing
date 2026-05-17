from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def _pg_type(sqlite_type: str) -> str:
    t = (sqlite_type or "").strip().upper()
    if "INT" in t:
        return "BIGINT"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "DOUBLE PRECISION"
    if "BLOB" in t:
        return "BYTEA"
    return "TEXT"


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def main() -> int:
    sqlite_path = Path(os.getenv("SQLITE_PATH", "./backend/labelhub.db")).resolve()
    pg_dsn = os.getenv("DATABASE_URL", "").strip()
    if not sqlite_path.exists():
        raise RuntimeError(f"SQLite file not found: {sqlite_path}")
    if not pg_dsn:
        raise RuntimeError("DATABASE_URL is required")

    import psycopg  # type: ignore

    sq = sqlite3.connect(str(sqlite_path))
    sq.row_factory = sqlite3.Row
    try:
        table_rows = sq.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        tables = [str(r["name"]) for r in table_rows]

        with psycopg.connect(pg_dsn) as pg:  # type: ignore[attr-defined]
            with pg.cursor() as cur:
                for table in tables:
                    cols = sq.execute(f"PRAGMA table_info({_quote_ident(table)})").fetchall()
                    if not cols:
                        continue

                    col_defs = []
                    col_names: list[str] = []
                    for c in cols:
                        name = str(c["name"])
                        col_names.append(name)
                        col_type = _pg_type(str(c["type"] or "TEXT"))
                        nullable = "" if int(c["notnull"] or 0) else " NULL"
                        col_defs.append(f"{_quote_ident(name)} {col_type}{nullable}")

                    create_sql = f"CREATE TABLE IF NOT EXISTS {_quote_ident(table)} ({', '.join(col_defs)})"
                    cur.execute(create_sql)

                    rows = sq.execute(f"SELECT * FROM {_quote_ident(table)}").fetchall()
                    if not rows:
                        continue

                    placeholders = ", ".join(["%s"] * len(col_names))
                    insert_sql = (
                        f"INSERT INTO {_quote_ident(table)} ({', '.join(_quote_ident(c) for c in col_names)}) "
                        f"VALUES ({placeholders})"
                    )
                    batch = [tuple(row[c] for c in col_names) for row in rows]
                    cur.executemany(insert_sql, batch)
                    print(f"Migrated {len(batch)} rows into {table}")
            pg.commit()
    finally:
        sq.close()

    print("Migration completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
