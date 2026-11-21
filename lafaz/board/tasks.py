"""Board queries. A space ('public' or 'owner') only ever sees tasks from runs started in that space.

The board shows published tasks: publishing is irreversible because it is the moment a task is seen by the team, so
it only happens after a person approves `publish_to_board`. Moving a card between columns is a person's own click on
the board and can be moved back, so it needs no approval.
"""

from __future__ import annotations

import sqlite3

from .. import config

_SPACE = "COALESCE(r.space, 'public') = ?"


def columns() -> list[str]:
    return list(config.board()["columns"])


def published(conn: sqlite3.Connection, space: str) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT t.* FROM tasks t JOIN runs r ON r.id = t.run_id WHERE {_SPACE} AND t.published = 1 "
        "AND t.status != 'undone' ORDER BY t.due_date IS NULL, t.due_date, t.id",
        (space,),
    ).fetchall()


def grouped(conn: sqlite3.Connection, space: str) -> dict[str, list[sqlite3.Row]]:
    found = {name: [] for name in columns()}
    for row in published(conn, space):
        found.setdefault(row["status"], []).append(row)
    return found


def waiting(conn: sqlite3.Connection, space: str) -> int:
    """Tasks created in this space that nobody has approved for the board yet."""
    return conn.execute(
        f"SELECT COUNT(*) FROM tasks t JOIN runs r ON r.id = t.run_id WHERE {_SPACE} AND t.published = 0 "
        "AND t.status != 'undone'",
        (space,),
    ).fetchone()[0]


def dated(conn: sqlite3.Connection, space: str) -> list[sqlite3.Row]:
    """Open tasks with a due date, for the calendar feed, with their active reminder policies."""
    statuses = ["todo", "doing"] + (["done"] if config.board()["ics"]["include_done"] else [])
    marks = ",".join("?" * len(statuses))
    return conn.execute(
        f"SELECT t.* FROM tasks t JOIN runs r ON r.id = t.run_id WHERE {_SPACE} AND t.due_date IS NOT NULL "
        f"AND t.status IN ({marks}) ORDER BY t.due_date, t.id",
        (space, *statuses),
    ).fetchall()


def policies(conn: sqlite3.Connection, task_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM reminder_policies WHERE task_id=? AND status='active' ORDER BY id", (task_id,)
    ).fetchall()


def move(conn: sqlite3.Connection, space: str, task_id: int, status: str) -> bool:
    """Move a published task in this space to another column. False when there is no such card."""
    if status not in columns():
        return False
    cur = conn.execute(
        "UPDATE tasks SET status=? WHERE id=? AND published=1 AND status != 'undone' AND run_id IN "
        f"(SELECT r.id FROM runs r WHERE {_SPACE})",
        (status, task_id, space),
    )
    conn.commit()
    return cur.rowcount == 1


def export_rows(conn: sqlite3.Connection, space: str) -> list[dict]:
    fields = config.board()["export"]["fields"]
    return [{f: row[f] for f in fields} for row in published(conn, space)]
