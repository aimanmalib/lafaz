"""What each tool does. Code here never decides whether it may run; lafaz.agent.gate does that from `kategori`.

Every action has `prepare` (check the arguments against the run, return a readable diff) and `execute` (do it).
Reversible actions return an undo record. Irreversible actions only ever execute from gate.approve.
Email actions put a message in the outbox; delivery is a later layer.
"""

from __future__ import annotations

from datetime import date, timedelta

from .. import config
from .context import ActionError, RunContext


def _diff(summary: str, *changes: tuple[str, object, object]) -> dict:
    return {"summary": summary, "changes": [{"field": f, "before": b, "after": a} for f, b, a in changes]}


# --- create_task (reversible) ---

def prepare_create_task(ctx: RunContext, args: dict) -> dict:
    item = ctx.item(args["item_index"])
    if item["kind"] != "action":
        raise ActionError("not_an_action", str(args["item_index"]))
    if not args["title"].strip():
        raise ActionError("empty_title")
    return _diff(
        "task",
        ("title", None, args["title"].strip()),
        ("owner", None, item["owner"]),
        ("due_date", None, item["due_date"]),
    )


def execute_create_task(ctx: RunContext, args: dict, approval_id: int | None = None) -> tuple[dict, dict]:
    prepare_create_task(ctx, args)
    item = ctx.item(args["item_index"])
    cur = ctx.conn.execute(
        "INSERT INTO tasks (run_id, item_seq, title, owner, due_date, quote) VALUES (?,?,?,?,?,?)",
        (ctx.run_id, item["seq"], args["title"].strip(), item["owner"], item["due_date"], item["quotes"][0]),
    )
    task_id = cur.lastrowid
    return (
        {"task_id": task_id, "owner": item["owner"], "due_date": item["due_date"]},
        {"table": "tasks", "id": task_id},
    )


# --- preview_summary (reversible) ---

def prepare_preview_summary(ctx: RunContext, args: dict) -> dict:
    person = ctx.require_owner(args["person"])
    if not args["body"].strip():
        raise ActionError("empty_body")
    return _diff("draft", ("person", None, person), ("body", None, args["body"].strip()))


def execute_preview_summary(ctx: RunContext, args: dict, approval_id: int | None = None) -> tuple[dict, dict]:
    prepare_preview_summary(ctx, args)
    person = ctx.require_owner(args["person"])
    cur = ctx.conn.execute(
        "INSERT INTO drafts (run_id, person, body) VALUES (?,?,?)", (ctx.run_id, person, args["body"].strip())
    )
    return {"draft_id": cur.lastrowid, "person": person}, {"table": "drafts", "id": cur.lastrowid}


# --- publish_to_board (irreversible) ---

def prepare_publish_to_board(ctx: RunContext, args: dict) -> dict:
    ids = list(dict.fromkeys(args["task_ids"]))
    if not ids:
        raise ActionError("no_tasks")
    rows = [ctx.task(task_id) for task_id in ids]
    changes = [(f"task {r['id']}: {r['title']}", "private", "shared board") for r in rows if not r["published"]]
    if not changes:
        raise ActionError("already_published")
    return _diff("publish", *changes)


def execute_publish_to_board(ctx: RunContext, args: dict, approval_id: int | None = None) -> tuple[dict, None]:
    prepare_publish_to_board(ctx, args)
    ids = list(dict.fromkeys(args["task_ids"]))
    ctx.conn.executemany("UPDATE tasks SET published=1 WHERE id=? AND run_id=?", [(i, ctx.run_id) for i in ids])
    return {"published": ids}, None


# --- email actions (irreversible): reminder, summary, ask the team ---

def _reminder(ctx: RunContext, args: dict) -> dict:
    task = ctx.task(args["task_id"])
    if not task["owner"]:
        raise ActionError("task_has_no_owner", str(task["id"]))
    if not task["due_date"]:
        raise ActionError("task_has_no_due_date", str(task["id"]))
    limit = config.settings()["agent"]["reminder_max_days_before"]
    if not 0 <= args["days_before"] <= limit:
        raise ActionError("days_before_out_of_range", str(args["days_before"]))
    send_on = date.fromisoformat(task["due_date"]) - timedelta(days=args["days_before"])
    return {"recipient": task["owner"], "subject": task["title"], "body": args["message"].strip(),
            "send_on": send_on.isoformat()}


def _summary(ctx: RunContext, args: dict) -> dict:
    return {"recipient": ctx.require_owner(args["person"]), "subject": args["subject"].strip(),
            "body": args["body"].strip()}


def _ask_team(ctx: RunContext, args: dict) -> dict:
    quote = ctx.require_quote(args["quote"])
    return {"recipient": "team", "subject": args["subject"].strip(), "body": args["body"].strip(), "quote": quote}


_EMAILS = {"send_reminder": _reminder, "send_summary": _summary, "ask_team": _ask_team}


def _email_diff(message: dict) -> dict:
    if not message["body"]:
        raise ActionError("empty_body")
    changes = [("to", None, message["recipient"]), ("subject", None, message["subject"]), ("body", None, message["body"])]
    if message.get("send_on"):
        changes.append(("send_on", None, message["send_on"]))
    if message.get("quote"):
        changes.append(("quote", None, message["quote"]))
    return _diff("email", *changes)


def _email_prepare(name: str):
    return lambda ctx, args: _email_diff(_EMAILS[name](ctx, args))


def _email_execute(name: str):
    def execute(ctx: RunContext, args: dict, approval_id: int | None = None) -> tuple[dict, None]:
        message = _EMAILS[name](ctx, args)
        _email_diff(message)
        cur = ctx.conn.execute(
            "INSERT INTO outbox (run_id, approval_id, tool, recipient, subject, body) VALUES (?,?,?,?,?,?)",
            (ctx.run_id, approval_id, name, message["recipient"], message["subject"], message["body"]),
        )
        return {"outbox_id": cur.lastrowid, "recipient": message["recipient"]}, None

    return execute


PREPARE = {
    "create_task": prepare_create_task,
    "preview_summary": prepare_preview_summary,
    "publish_to_board": prepare_publish_to_board,
    **{name: _email_prepare(name) for name in _EMAILS},
}

EXECUTE = {
    "create_task": execute_create_task,
    "preview_summary": execute_preview_summary,
    "publish_to_board": execute_publish_to_board,
    **{name: _email_execute(name) for name in _EMAILS},
}

UNDO_STATUS = {"tasks": "undone", "drafts": "discarded"}


def undo(ctx: RunContext, record: dict) -> None:
    table = record["table"]
    if table not in UNDO_STATUS:
        raise ActionError("cannot_undo", table)
    if table == "tasks" and ctx.conn.execute("SELECT published FROM tasks WHERE id=?", (record["id"],)).fetchone()[0]:
        raise ActionError("already_published", str(record["id"]))
    ctx.conn.execute(f"UPDATE {table} SET status=? WHERE id=? AND run_id=?", (UNDO_STATUS[table], record["id"], ctx.run_id))
