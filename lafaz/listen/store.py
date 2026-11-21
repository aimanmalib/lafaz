"""Save a listen result for one run: accepted items, rejected items with their reason, and open questions."""

from __future__ import annotations

import json
import sqlite3

from .extract import ListenResult


def _dump(value) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def save(conn: sqlite3.Connection, run_id: int, result: ListenResult) -> None:
    rows = [("accepted", None, item) for item in result.items]
    rows += [("rejected", r["reason"], r.get("item") or {}) for r in result.rejected if "item" in r]
    for seq, (status, reason, item) in enumerate(rows):
        conn.execute(
            "INSERT INTO items (run_id, seq, status, reason, kind, text, owner, speaker, due_phrase, due_date,"
            " confidence, quotes_json, corrects_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, seq, status, reason, item.get("kind"), item.get("text"), item.get("owner"),
                item.get("speaker"), item.get("due_phrase"), item.get("due_date"), item.get("confidence"),
                _dump(item.get("quotes") or []) or "[]", _dump(item.get("corrects")),
            ),
        )
    for seq, q in enumerate(result.questions):
        conn.execute(
            "INSERT INTO questions (run_id, seq, origin, code, params_json, text, item_seq, quote)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (run_id, seq, q["origin"], q.get("code"), _dump(q.get("params")), q.get("text"), q.get("item_index"), q.get("quote")),
        )
    conn.commit()


def counts(conn: sqlite3.Connection, run_id: int) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) FROM items WHERE run_id=? GROUP BY status", (run_id,)).fetchall()
    return {status: n for status, n in rows}
