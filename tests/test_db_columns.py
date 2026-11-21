"""A database created before the agent layer gains the new columns without losing rows."""

import sqlite3

from lafaz import db


def test_existing_tables_gain_columns_and_keep_rows(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE meetings (id INTEGER PRIMARY KEY, meeting_date TEXT NOT NULL, title TEXT, source TEXT NOT NULL,"
        " text TEXT NOT NULL, created_at TEXT);"
        "CREATE TABLE runs (id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'started',"
        " mode TEXT NOT NULL DEFAULT 'live', lang TEXT NOT NULL, created_at TEXT);"
        "CREATE TABLE steps (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, seq INTEGER NOT NULL, tool TEXT NOT NULL,"
        " category TEXT NOT NULL, arguments_json TEXT NOT NULL, result_summary TEXT, ms INTEGER, tokens_in INTEGER,"
        " tokens_out INTEGER, cost_usd REAL, UNIQUE (run_id, seq));"
        "INSERT INTO meetings (meeting_date, source, text) VALUES ('2026-11-21', 'sample', 't');"
        "INSERT INTO runs (meeting_id, lang) VALUES (1, 'en');"
    )
    old.commit()
    old.close()
    db.init(path)
    db.init(path)  # idempotent
    conn = db.connect(path)
    for table, columns in db.ADDED_COLUMNS.items():
        have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert set(columns) <= have
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    conn.close()
