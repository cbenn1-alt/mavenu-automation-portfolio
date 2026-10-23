"""SQLite connection factory and version-controlled migration runner."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with sane defaults for this project."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def applied_migrations(conn: sqlite3.Connection) -> set[str]:
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT name FROM schema_migrations").fetchall()
    return {r["name"] for r in rows}


def run_migrations(conn: sqlite3.Connection, migrations_dir: str = MIGRATIONS_DIR) -> list[str]:
    """Apply pending *.sql migrations in filename order. Returns names applied."""
    _ensure_migrations_table(conn)
    done = applied_migrations(conn)
    files = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
    applied: list[str] = []
    for fname in files:
        if fname in done:
            continue
        with open(os.path.join(migrations_dir, fname), encoding="utf-8") as fh:
            sql = fh.read()
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
            (fname, utcnow_iso()),
        )
        conn.commit()
        applied.append(fname)
    return applied
