"""SQLite access. WAL mode, one connection per request, schema applied idempotently at start-up."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

SCHEMA = Path(__file__).with_name("schema.sql")


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
