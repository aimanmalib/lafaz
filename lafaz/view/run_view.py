"""Everything /run/<id> shows, read from the database in one place.

Columns: Heard (marked transcript), Understood (accepted items and open questions), Plan (approval cards, done
steps with Undo, conflict cards). Below them, the trace drawer. A stopped run carries its handoff object.
"""

from __future__ import annotations

import json
import sqlite3

from .. import config
from ..memory import conflicts
from . import marks

ACTIVE = "started"


def _loads(value, default):
    return json.loads(value) if value else default


def editable_fields(tool: str) -> list[dict]:
    """Fields a person may edit on an approval card: top-level strings and integers of the tool's schema."""
    props = config.tool(tool).get("input_schema", {}).get("properties", {})
    return [{"name": k, "type": v.get("type")} for k, v in props.items() if v.get("type") in ("string", "integer")]


def _items(conn, run_id: int) -> tuple[list[dict], list[dict]]:
    accepted, rejected = [], []
    for row in conn.execute("SELECT * FROM items WHERE run_id=? ORDER BY seq", (run_id,)):
        item = dict(row)
        item["quotes"] = _loads(row["quotes_json"], [])
        item["corrects"] = _loads(row["corrects_json"], None)
        (accepted if row["status"] == "accepted" else rejected).append(item)
    return accepted, rejected


def _questions(conn, run_id: int) -> list[dict]:
    out = []
    for row in conn.execute("SELECT * FROM questions WHERE run_id=? ORDER BY seq", (run_id,)):
        q = dict(row)
        q["params"] = _loads(row["params_json"], {})
        q["item_number"] = None if row["item_seq"] is None else row["item_seq"] + 1
        out.append(q)
    return out


def _approvals(conn, run_id: int) -> list[dict]:
    out = []
    for row in conn.execute("SELECT * FROM approvals WHERE run_id=? ORDER BY id", (run_id,)):
        a = dict(row)
        a["arguments"] = _loads(row["arguments_json"], {})
        a["diff"] = _loads(row["diff_json"], {"changes": []})
        a["result"] = _loads(row["result_json"], {})
        a["fields"] = editable_fields(row["tool"]) if row["status"] == "pending" else []
        out.append(a)
    return out


def _done_steps(steps: list[dict]) -> list[dict]:
    """Reversible steps that ran, newest state first: executed ones can be undone, undone ones say so."""
    out = []
    for step in steps:
        if step["category"] == "reversible" and step["status"] in ("executed", "undone") and step["tool"] in (
            t["name"] for t in config.tools() if t.get("stage") == "plan"
        ):
            step = dict(step)
            step["arguments"] = _loads(step["arguments_json"], {})
            step["result"] = _loads(step["result_summary"], {})
            step["can_undo"] = step["status"] == "executed" and bool(step["undo_json"])
            out.append(step)
    return out


def load(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute(
        "SELECT r.*, m.text, m.meeting_date, m.source, m.title FROM runs r JOIN meetings m ON m.id = r.meeting_id"
        " WHERE r.id=?", (run_id,)).fetchone()
    if row is None:
        return None
    run = dict(row)
    run["handoff"] = _loads(row["handoff_json"], None)
    run["active"] = row["status"] == ACTIVE
    items, rejected = _items(conn, run_id)
    questions = _questions(conn, run_id)
    steps = [dict(s) for s in conn.execute("SELECT * FROM steps WHERE run_id=? ORDER BY seq", (run_id,))]
    totals = {
        "ms": sum(s["ms"] or 0 for s in steps),
        "tokens_in": sum(s["tokens_in"] or 0 for s in steps),
        "tokens_out": sum(s["tokens_out"] or 0 for s in steps),
        "cost_usd": round(sum(s["cost_usd"] or 0 for s in steps), 4),
    }
    return {
        "run": run,
        "segments": marks.paint(run["text"], items, questions),
        "items": items,
        "rejected": rejected,
        "questions": questions,
        "approvals": _approvals(conn, run_id),
        "done_steps": _done_steps(steps),
        "cards": conflicts.open_cards(conn, run_id),
        "steps": steps,
        "totals": totals,
    }
