"""Weekly summary per person, built by code from the database (PRD 4.6).

This is the preview: reading it changes nothing. Sending a summary is the irreversible `send_summary` tool, which
only runs after a person approves its card on a run page; nothing on the board sends email. The preview sits on the
board, so it lists published tasks only, like the board itself.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from .. import config


def weekly(conn: sqlite3.Connection, space: str, today: date) -> list[dict]:
    cfg = config.board()["summary"]
    since = (today - timedelta(days=cfg["window_days"])).isoformat()
    rows = conn.execute(
        "SELECT t.id, t.title, t.owner, t.due_date, t.status, t.published FROM tasks t JOIN runs r ON r.id = t.run_id "
        "JOIN meetings m ON m.id = r.meeting_id WHERE COALESCE(r.space, 'public') = ? AND t.owner IS NOT NULL "
        "AND t.published = 1 AND t.status != 'undone' AND m.meeting_date >= ? "
        "ORDER BY t.owner, t.due_date IS NULL, t.due_date, t.id",
        (space, since),
    ).fetchall()
    people: dict[str, dict] = {}
    for row in rows:
        person = people.setdefault(row["owner"], {"person": row["owner"], "open": [], "done": [], "overdue": 0})
        (person["done"] if row["status"] == "done" else person["open"]).append(dict(row))
        if row["status"] != "done" and row["due_date"] and row["due_date"] < today.isoformat():
            person["overdue"] += 1
    return list(people.values())[: cfg["max_people"]]
