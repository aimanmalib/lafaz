"""The permission gate. The category of a tool comes only from `kategori` in config/tools.json.

read         runs.
reversible   runs, is logged with an undo record.
irreversible never runs from the loop. It becomes a pending approval with a readable diff. Only `approve`, called
             for a person's click, runs it, and then code runs it, not the model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .. import config
from . import actions, trace
from .context import ActionError, RunContext, load
from .schemacheck import errors as schema_errors

CATEGORIES = ("read", "reversible", "irreversible")


@dataclass
class Outcome:
    tool: str
    category: str
    status: str  # executed | pending_approval | refused
    result: dict = field(default_factory=dict)
    error: str | None = None
    approval_id: int | None = None
    undo: dict | None = None
    seq: int | None = None

    def for_model(self) -> dict:
        """What goes back to the model as the tool result."""
        if self.status == "pending_approval":
            return {"status": "waiting_for_human_approval", "approval_id": self.approval_id,
                    "note": "Not done. A person must approve it in Lafaz."}
        if self.status == "refused":
            return {"status": "refused", "error": self.error}
        return {"status": "done", **self.result}


def plan_tools() -> list[dict]:
    return [t for t in config.tools() if t.get("stage") == "plan" and t.get("enabled") and "input_schema" in t]


def category_of(name: str) -> str | None:
    try:
        kategori = config.tool(name).get("kategori")
    except KeyError:
        return None
    return kategori if kategori in CATEGORIES else None


def _check(name: str, args, stage: str | None = "plan") -> tuple[str, dict]:
    """Return (category, entry) or raise ActionError. Unknown, disabled or malformed calls never reach an action.

    The loop only reaches `plan` tools. Conflict-card tools have stage `card` and are dispatched for a person's click.
    """
    category = category_of(name)
    if category is None:
        raise ActionError("unknown_tool", name)
    entry = config.tool(name)
    if not entry.get("enabled") or not entry.get("stage") or entry.get("stage") != stage or name not in actions.EXECUTE:
        raise ActionError("tool_not_available", name)
    if not isinstance(args, dict):
        raise ActionError("bad_arguments", type(args).__name__)
    problems = schema_errors(args, entry["input_schema"])
    if problems:
        raise ActionError("bad_arguments", "; ".join(problems[:3]))
    return category, entry


def dispatch(ctx: RunContext, name: str, args, cost: dict | None = None, stage: str = "plan") -> Outcome:
    """Handle one tool call (from the loop, or from a card button with its own stage) and record it as a step."""
    cost = cost or {}
    try:
        category, _ = _check(name, args, stage)
        diff = actions.PREPARE[name](ctx, args)
    except ActionError as exc:
        outcome = Outcome(name, category_of(name) or "unknown", "refused", error=exc.code)
    else:
        if category == "irreversible":
            outcome = _file_approval(ctx, name, args, diff)
        else:
            try:
                result, undo = actions.EXECUTE[name](ctx, args)
            except ActionError as exc:
                outcome = Outcome(name, category, "refused", error=exc.code)
            else:
                outcome = Outcome(name, category, "executed", result=result,
                                  undo=undo if category == "reversible" else None)
    outcome.seq = trace.record(
        ctx.conn, ctx.run_id, tool=name, category=outcome.category, arguments=args if isinstance(args, dict) else {},
        status=outcome.status, result=outcome.for_model(), approval_id=outcome.approval_id, undo=outcome.undo, **cost,
    )
    if outcome.approval_id:
        ctx.conn.execute("UPDATE approvals SET step_seq=? WHERE id=?", (outcome.seq, outcome.approval_id))
    ctx.conn.commit()
    return outcome


def _stage_of(name: str) -> str | None:
    try:
        return config.tool(name).get("stage")
    except KeyError:
        return None


def _file_approval(ctx: RunContext, name: str, args: dict, diff: dict) -> Outcome:
    cur = ctx.conn.execute(
        "INSERT INTO approvals (run_id, step_seq, tool, arguments_json, diff_json) VALUES (?,?,?,?,?)",
        (ctx.run_id, -1, name, json.dumps(args, ensure_ascii=False), json.dumps(diff, ensure_ascii=False)),
    )
    return Outcome(name, "irreversible", "pending_approval", approval_id=cur.lastrowid)


# --- human decisions -------------------------------------------------------------------------------------------

def _pending(conn, approval_id: int):
    row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    if row is None:
        raise ActionError("unknown_approval", str(approval_id))
    if row["status"] != "pending":
        raise ActionError("already_decided", row["status"])
    return row


def approve(conn, approval_id: int, edited_args: dict | None = None) -> Outcome:
    """A person approved (optionally after editing). Code checks the arguments again, then runs the action."""
    row = _pending(conn, approval_id)
    ctx = load(conn, row["run_id"])
    name = row["tool"]
    args = json.loads(row["arguments_json"]) if edited_args is None else edited_args
    try:
        category, _ = _check(name, args, _stage_of(name))
        if category != "irreversible":
            raise ActionError("not_irreversible", category)
        diff = actions.PREPARE[name](ctx, args)
        result, _ = actions.EXECUTE[name](ctx, args, approval_id)
    except ActionError as exc:
        if edited_args is not None and exc.code == "bad_arguments":
            raise  # a bad edit leaves the card pending so the person can fix it
        conn.execute(
            "UPDATE approvals SET status='failed', result_json=?, decided_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
            " WHERE id=?", (json.dumps({"error": exc.code}), approval_id),
        )
        outcome = Outcome(name, "irreversible", "failed", error=exc.code, approval_id=approval_id)
    else:
        conn.execute(
            "UPDATE approvals SET status='approved', edited=?, arguments_json=?, diff_json=?, result_json=?,"
            " decided_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
            (int(edited_args is not None), json.dumps(args, ensure_ascii=False), json.dumps(diff, ensure_ascii=False),
             json.dumps(result, ensure_ascii=False), approval_id),
        )
        outcome = Outcome(name, "irreversible", "executed", result=result, approval_id=approval_id)
    outcome.seq = trace.record(conn, row["run_id"], tool=name, category="irreversible", arguments=args,
                               status=f"approval_{outcome.status}", result=outcome.result or {"error": outcome.error},
                               approval_id=approval_id)
    conn.commit()
    return outcome


def skip(conn, approval_id: int) -> None:
    row = _pending(conn, approval_id)
    conn.execute(
        "UPDATE approvals SET status='skipped', decided_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
        (approval_id,),
    )
    trace.record(conn, row["run_id"], tool=row["tool"], category="irreversible", arguments={},
                 status="approval_skipped", approval_id=approval_id)
    conn.commit()


def undo(conn, run_id: int, seq: int) -> None:
    """Undo one executed reversible step."""
    row = conn.execute("SELECT * FROM steps WHERE run_id=? AND seq=?", (run_id, seq)).fetchone()
    if row is None:
        raise ActionError("unknown_step", str(seq))
    if row["category"] != "reversible" or row["status"] != "executed" or not row["undo_json"]:
        raise ActionError("cannot_undo", row["status"] or "")
    actions.undo(load(conn, run_id), json.loads(row["undo_json"]))
    conn.execute("UPDATE steps SET status='undone' WHERE id=?", (row["id"],))
    trace.record(conn, run_id, tool=row["tool"], category="reversible", arguments={"undo_of": seq}, status="undo")
    conn.commit()
