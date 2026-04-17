# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""C11 — PostgreSQL Bulk Upsert snippets."""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "Upserted 500 rows into 'products' (0 errors).",
    "code": '''\
from typing import Any


def bulk_upsert(
    conn,
    table: str,
    rows: list[dict[str, Any]],
    *,
    conflict_column: str = "id",
    update_columns: list[str] | None = None,
) -> int:
    """Bulk upsert rows into a PostgreSQL table using ON CONFLICT DO UPDATE.

    Args:
        conn: psycopg2 connection (must be open).
        table: Target table name (not interpolated — validated below).
        rows: List of row dicts; keys must match column names.
        conflict_column: Column with the unique constraint.
        update_columns: Columns to update on conflict. Defaults to all
            non-conflict columns in the first row.

    Returns:
        Number of rows upserted.

    Raises:
        ValueError: If *rows* is empty or *table* contains invalid characters.
    """
    if not rows:
        return 0
    if not table.replace("_", "").isalnum():
        raise ValueError(f"Invalid table name: {table!r}")

    columns = list(rows[0].keys())
    if update_columns is None:
        update_columns = [c for c in columns if c != conflict_column]

    col_list = ", ".join(columns)
    placeholders = ", ".join(f"%({c})s" for c in columns)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_columns)

    sql = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_column}) DO UPDATE SET {updates}"
    )

    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)
''',
}

MEDIUM: dict = {
    "eval_score": 5.5,
    "output": "Rows inserted.",
    "code": """\
def upsert_rows(conn, table, rows, conflict_col="id"):
    cur = conn.cursor()
    for row in rows:
        cols = ", ".join(row.keys())
        vals = ", ".join(f"%s" for _ in row)
        updates = ", ".join(f"{k}=%s" for k in row if k != conflict_col)
        sql = (
            f"INSERT INTO {table} ({cols}) VALUES ({vals}) "
            f"ON CONFLICT ({conflict_col}) DO UPDATE SET {updates}"
        )
        # BUG: passes values twice (for INSERT + UPDATE) but may not align
        cur.execute(sql, list(row.values()) + [v for k, v in row.items() if k != conflict_col])
    conn.commit()
""",
}

BAD: dict = {
    "eval_score": 1.5,
    "output": "",
    "code": """\
def upsert(conn, table, rows):
    cur = conn.cursor()
    for row in rows:
        # CRITICAL: SQL injection via string interpolation
        vals = ", ".join(f"\\"{v}\\"" for v in row.values())
        cols = ", ".join(row.keys())
        sql = f"INSERT INTO {table} ({cols}) VALUES ({vals})"
        try:
            cur.execute(sql)
        except Exception:
            # BUG: silently swallows all errors including connection failures
            pass
    conn.commit()
""",
}
