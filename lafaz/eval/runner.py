"""Run one eval task through the real agent loop in its own SQLite file, then read back what the run left.

Nothing is approved during an eval: no person is present, so every irreversible call must stay pending. The facts
returned here are plain data; lafaz.eval.score turns them into numbers.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import date
from pathlib import Path

from .. import db
from ..agent import loop
from ..listen import store
from ..listen.extract import ListenResult
from ..memory import decisions, people as memory_people

MEETING_SOURCE = {"synthetic": "transcript", "wispr-sebenar": "wispr"}


def seed(conn: sqlite3.Connection, memory: dict) -> None:
    """People and earlier meetings with their decisions, stored the way a real earlier run would have stored them."""
    for person in memory.get("people", []):
        memory_people.upsert(conn, person["name"], person.get("aliases"), person.get("email"))
    for meeting in memory.get("meetings", []):
        run_id = loop.start_run(conn, meeting["text"], date.fromisoformat(meeting["meeting_date"]), "transcript", "en")
        items = [{"kind": "decision", "text": d["text"], "owner": None, "due_date": None, "quotes": [d["quote"]]}
                 for d in meeting.get("decisions", [])]
        store.save(conn, run_id, ListenResult(items=items))
        decisions.save_run(conn, run_id)
        conn.execute("UPDATE runs SET status='done' WHERE id=?", (run_id,))
    conn.commit()


def _rows(conn, sql: str, run_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, (run_id,))]


def collect(conn: sqlite3.Connection, run_id: int) -> dict:
    run = dict(conn.execute("SELECT status, handoff_json, cost_usd FROM runs WHERE id=?", (run_id,)).fetchone())
    items = _rows(conn, "SELECT status, reason, kind, text, owner, due_date, quotes_json, corrects_json FROM items"
                        " WHERE run_id=? ORDER BY seq", run_id)
    for item in items:
        item["quotes"] = json.loads(item.pop("quotes_json") or "[]")
        item["corrects"] = json.loads(item.pop("corrects_json") or "null")
    steps = _rows(conn, "SELECT seq, tool, category, status, arguments_json, ms, cost_usd, approval_id FROM steps"
                        " WHERE run_id=? ORDER BY seq", run_id)
    return {
        "status": run["status"],
        "handoff": json.loads(run["handoff_json"] or "{}"),
        "cost_usd": run["cost_usd"] or 0.0,
        "items": items,
        "questions": _rows(conn, "SELECT origin, code, text, quote FROM questions WHERE run_id=? ORDER BY seq", run_id),
        "steps": steps,
        "approvals": _rows(conn, "SELECT id, tool, status FROM approvals WHERE run_id=? ORDER BY id", run_id),
        "conflicts": _rows(conn, "SELECT verdict, reject_reason FROM conflicts WHERE run_id=? ORDER BY id", run_id),
    }


def run_task(task: dict, workdir: Path, make_llm) -> dict:
    """Run one task; any crash is recorded as the task's outcome so one bad task never stops the others."""
    path = workdir / f"{task['id']}.db"
    db.init(path)
    conn = db.connect(path)
    started = time.monotonic()
    try:
        seed(conn, task["memory"])
        day = date.fromisoformat(task["meeting_date"])
        run_id = loop.start_run(conn, task["text"], day, MEETING_SOURCE[task["source"]], "en", title=task["id"])
        loop.run(conn, run_id, task["text"], day, llm=make_llm(), limits=task.get("limits"))
        facts = collect(conn, run_id)
        facts["error"] = None
    except Exception as exc:  # noqa: BLE001 - the eval reports crashes, it does not hide them
        facts = {"status": "crashed", "handoff": {}, "cost_usd": 0.0, "items": [], "questions": [], "steps": [],
                 "approvals": [], "conflicts": [], "error": f"{type(exc).__name__}: {exc}"}
    finally:
        conn.close()
    facts["ms"] = int((time.monotonic() - started) * 1000)
    return facts
