"""Every step of a run goes to the `steps` table: tool, category, arguments (secrets hidden), result, time, tokens, cost."""

from __future__ import annotations

import json
import sqlite3

from .. import config

HIDDEN = "[hidden]"


def redact(value):
    keys = [k.casefold() for k in config.settings()["agent"]["redact_keys"]]
    if isinstance(value, dict):
        return {
            k: HIDDEN if any(word in k.casefold() for word in keys) else redact(v) for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _clip(value) -> str:
    text = json.dumps(value, ensure_ascii=False)
    limit = config.settings()["agent"]["result_max_chars"]
    return text if len(text) <= limit else text[: limit - 1] + "…"


def next_seq(conn: sqlite3.Connection, run_id: int) -> int:
    return conn.execute("SELECT COALESCE(MAX(seq), -1) + 1 FROM steps WHERE run_id=?", (run_id,)).fetchone()[0]


def record(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    tool: str,
    category: str,
    arguments: dict,
    status: str,
    result=None,
    ms: int = 0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    approval_id: int | None = None,
    undo: dict | None = None,
) -> int:
    seq = next_seq(conn, run_id)
    conn.execute(
        "INSERT INTO steps (run_id, seq, tool, category, arguments_json, result_summary, ms, tokens_in, tokens_out,"
        " cost_usd, status, approval_id, undo_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            run_id, seq, tool, category, json.dumps(redact(arguments), ensure_ascii=False),
            None if result is None else _clip(redact(result)), ms, tokens_in, tokens_out, cost_usd, status,
            approval_id, None if undo is None else json.dumps(undo),
        ),
    )
    return seq


def steps(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM steps WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
    return [dict(r) for r in rows]
