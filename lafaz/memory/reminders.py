"""Reminder policies: a person approves "email the owner N days before" once per task (PRD 4.6).

After that the scheduler sends inside the policy and nowhere else: only to the task's owner, never before the send
day, never after the due date, at most `max_sends` times, and never for a task that is done or undone. Each send is
labelled `approved_once` so the interface can say "approved once, runs within limits".
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from .. import config
from ..agent import trace

LABEL = "approved_once"


def create_policy(conn: sqlite3.Connection, task: sqlite3.Row, approval_id: int | None, days_before: int,
                  message: str) -> int:
    cur = conn.execute(
        "INSERT INTO reminder_policies (task_id, approval_id, days_before, message, max_sends) VALUES (?,?,?,?,?)",
        (task["id"], approval_id, days_before, message, config.memory()["reminders"]["max_sends_per_policy"]),
    )
    return cur.lastrowid


def send_on(due_date: str, days_before: int) -> date:
    return date.fromisoformat(due_date) - timedelta(days=days_before)


def _set_status(conn, policy_id: int, status: str) -> None:
    conn.execute("UPDATE reminder_policies SET status=? WHERE id=?", (status, policy_id))


def tick(conn: sqlite3.Connection, today: date) -> list[int]:
    """One scheduler pass. Returns the outbox ids queued in this pass."""
    queued = []
    rows = conn.execute(
        "SELECT p.*, t.run_id, t.title, t.owner, t.due_date, t.status AS task_status FROM reminder_policies p"
        " JOIN tasks t ON t.id = p.task_id WHERE p.status='active' ORDER BY p.id"
    ).fetchall()
    for p in rows:
        if p["task_status"] in ("done", "undone") or not p["owner"] or not p["due_date"]:
            _set_status(conn, p["id"], "stopped")
            continue
        if today > date.fromisoformat(p["due_date"]):
            _set_status(conn, p["id"], "finished")
            continue
        if today < send_on(p["due_date"], p["days_before"]) or p["last_sent_on"] == today.isoformat():
            continue
        cur = conn.execute(
            "INSERT INTO outbox (run_id, approval_id, tool, recipient, subject, body, policy_id, label)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (p["run_id"], p["approval_id"], "send_reminder", p["owner"], p["title"], p["message"], p["id"], LABEL),
        )
        queued.append(cur.lastrowid)
        sends = p["sends"] + 1
        conn.execute("UPDATE reminder_policies SET sends=?, last_sent_on=?, status=? WHERE id=?",
                     (sends, today.isoformat(), "finished" if sends >= p["max_sends"] else "active", p["id"]))
        trace.record(conn, p["run_id"], tool="send_reminder", category="irreversible",
                     arguments={"policy_id": p["id"], "task_id": p["task_id"]}, status="policy_send",
                     result={"outbox_id": cur.lastrowid, "label": LABEL}, approval_id=p["approval_id"])
    conn.commit()
    return queued
