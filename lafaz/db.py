"""SQLite access. WAL mode, one connection per request, schema applied idempotently at start-up."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

SCHEMA = Path(__file__).with_name("schema.sql")

# Columns added after a table first shipped. ADD COLUMN never rebuilds a table, so existing rows stay as they are.
ADDED_COLUMNS = {
    "runs": {"handoff_json": "TEXT", "cost_usd": "REAL", "finished_at": "TEXT", "client_key": "TEXT", "space": "TEXT"},
    "steps": {"status": "TEXT", "approval_id": "INTEGER", "undo_json": "TEXT"},
    "outbox": {"policy_id": "INTEGER", "label": "TEXT", "address": "TEXT", "message_id": "TEXT", "sent_at": "TEXT",
               "delivered_at": "TEXT", "error": "TEXT"},
}


def _add_columns(conn: sqlite3.Connection) -> None:
    for table, columns in ADDED_COLUMNS.items():
        have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init(path: Path | None = None) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        _add_columns(conn)
        conn.commit()
    finally:
        conn.close()


def healthy(path: Path | None = None) -> bool:
    try:
        conn = connect(path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            conn.execute("SELECT 1 FROM runs LIMIT 1")
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return mode == "wal"
