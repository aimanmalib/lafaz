"""Actions behind the conflict card buttons. Both change Lafaz's own memory only and can be undone.

Whether they run straight away or wait for a person is still decided by lafaz.agent.gate from `kategori`.
"""

from __future__ import annotations

from .context import ActionError, RunContext


def _diff(summary: str, *changes: tuple[str, object, object]) -> dict:
    return {"summary": summary, "changes": [{"field": f, "before": b, "after": a} for f, b, a in changes]}


def _open_card(ctx: RunContext, conflict_id) -> dict:
    row = ctx.conn.execute(
        "SELECT c.*, o.statement AS old_statement, n.statement AS new_statement FROM conflicts c"
        " JOIN decisions o ON o.id = c.old_decision_id JOIN decisions n ON n.id = c.new_decision_id"
        " WHERE c.id=? AND c.run_id=? AND c.verdict='conflict'", (conflict_id, ctx.run_id),
    ).fetchone()
    if row is None:
        raise ActionError("unknown_conflict", str(conflict_id))
    if row["status"] != "open":
        raise ActionError("already_decided", row["status"])
    return dict(row)


def _close(ctx: RunContext, conflict_id: int, status: str) -> None:
    ctx.conn.execute("UPDATE conflicts SET status=?, decided_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                     (status, conflict_id))


def prepare_replace(ctx: RunContext, args: dict) -> dict:
    card = _open_card(ctx, args["conflict_id"])
    return _diff("decision", (card["old_statement"], "active", "superseded"), (card["new_statement"], None, "active"))


def execute_replace(ctx: RunContext, args: dict, approval_id: int | None = None) -> tuple[dict, dict]:
    card = _open_card(ctx, args["conflict_id"])
    ctx.conn.execute("UPDATE decisions SET status='superseded', superseded_by=? WHERE id=?",
                     (card["new_decision_id"], card["old_decision_id"]))
    _close(ctx, card["id"], "replaced")
    return ({"conflict_id": card["id"], "superseded": card["old_decision_id"]},
            {"table": "conflicts", "id": card["id"]})


def prepare_keep(ctx: RunContext, args: dict) -> dict:
    card = _open_card(ctx, args["conflict_id"])
    return _diff("decision", (card["old_statement"], "active", "active"), (card["new_statement"], None, "active"))


def execute_keep(ctx: RunContext, args: dict, approval_id: int | None = None) -> tuple[dict, dict]:
    card = _open_card(ctx, args["conflict_id"])
    _close(ctx, card["id"], "kept")
    return {"conflict_id": card["id"], "kept": True}, {"table": "conflicts", "id": card["id"]}


def undo_card(ctx: RunContext, record: dict) -> None:
    """Reopen the card; a replaced decision becomes active again."""
    row = ctx.conn.execute("SELECT * FROM conflicts WHERE id=? AND run_id=?", (record["id"], ctx.run_id)).fetchone()
    if row is None or row["status"] not in ("replaced", "kept"):
        raise ActionError("cannot_undo", "conflicts")
    if row["status"] == "replaced":
        ctx.conn.execute("UPDATE decisions SET status='active', superseded_by=NULL WHERE id=?", (row["old_decision_id"],))
    ctx.conn.execute("UPDATE conflicts SET status='open', decided_at=NULL WHERE id=?", (row["id"],))


PREPARE = {"replace_decision": prepare_replace, "keep_both_decisions": prepare_keep}
EXECUTE = {"replace_decision": execute_replace, "keep_both_decisions": execute_keep}
UNDO = {"conflicts": undo_card}
