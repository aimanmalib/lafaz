"""Decisions across meetings, and which earlier decisions are worth asking the model about.

Candidates are chosen by code: terms shared between two decisions after normalising, dropping stopwords and short
words (config/memory.json). Only active decisions from other runs qualify. The model never picks candidates.
"""

from __future__ import annotations

import json
import re
import sqlite3

from .. import config
from ..listen.quotes import normalise


def _cfg() -> dict:
    return config.memory()["conflict"]


def terms(text: str) -> set[str]:
    cfg = _cfg()
    stop = {normalise(w) for w in cfg["stopwords"]}
    words = re.findall(r"\w+(?:'\w+)?", normalise(text))
    return {w for w in words if len(w) >= cfg["min_term_chars"] and w not in stop}


def decision_terms(statement: str, quote: str) -> set[str]:
    return terms(f"{statement} {quote}")


def save_run(conn: sqlite3.Connection, run_id: int) -> list[int]:
    """Store each accepted decision item of the run as an active decision. Returns the new decision ids."""
    meeting_id = conn.execute("SELECT meeting_id FROM runs WHERE id=?", (run_id,)).fetchone()[0]
    ids = []
    rows = conn.execute(
        "SELECT seq, text, quotes_json FROM items WHERE run_id=? AND status='accepted' AND kind='decision' ORDER BY seq",
        (run_id,),
    ).fetchall()
    for row in rows:
        quote = json.loads(row["quotes_json"])[0]
        topic = " ".join(sorted(decision_terms(row["text"], quote)))
        cur = conn.execute(
            "INSERT OR IGNORE INTO decisions (run_id, meeting_id, item_seq, topic, statement, quote) VALUES (?,?,?,?,?,?)",
            (run_id, meeting_id, row["seq"], topic, row["text"], quote),
        )
        if cur.rowcount:
            ids.append(cur.lastrowid)
    return ids


def get(conn: sqlite3.Connection, decision_id: int) -> sqlite3.Row:
    return conn.execute(
        "SELECT d.*, m.text AS meeting_text, m.meeting_date FROM decisions d JOIN meetings m ON m.id = d.meeting_id"
        " WHERE d.id=?", (decision_id,),
    ).fetchone()


def candidates(conn: sqlite3.Connection, decision_id: int) -> list[tuple[sqlite3.Row, list[str]]]:
    """Active decisions from other runs sharing at least `min_shared_terms` terms, most shared first.

    A run of the very same meeting text (a sample tried twice) restates its decisions; it never contradicts them.
    """
    cfg = _cfg()
    new = get(conn, decision_id)
    mine = set(new["topic"].split())
    scored = []
    for old in conn.execute(
        "SELECT d.*, m.text AS meeting_text, m.meeting_date FROM decisions d JOIN meetings m ON m.id = d.meeting_id"
        " WHERE d.status='active' AND d.run_id != ? AND d.id < ? AND m.text != ?",
        (new["run_id"], decision_id, new["meeting_text"]),
    ):
        shared = sorted(mine & set(old["topic"].split()))
        if len(shared) >= cfg["min_shared_terms"]:
            scored.append((old, shared))
    scored.sort(key=lambda pair: (-len(pair[1]), -pair[0]["id"]))
    return scored[: cfg["max_candidates"]]


def timeline(conn: sqlite3.Connection, space: str, limit: int) -> list[dict]:
    """Decisions from runs started in `space`, newest meeting first, each with the statement that replaced it."""
    rows = conn.execute(
        "SELECT d.id, d.run_id, d.statement, d.quote, d.status, m.meeting_date, s.statement AS replaced_by"
        " FROM decisions d JOIN runs r ON r.id = d.run_id JOIN meetings m ON m.id = d.meeting_id"
        " LEFT JOIN decisions s ON s.id = d.superseded_by"
        " WHERE COALESCE(r.space, 'public') = ? ORDER BY m.meeting_date DESC, d.id DESC LIMIT ?",
        (space, limit),
    )
    return [dict(r) for r in rows]
