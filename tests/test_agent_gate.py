"""The permission gate: kategori from config decides; irreversible tools never run without a person's approval."""

import json
import random
from datetime import date

import pytest

from lafaz import config, db
from lafaz.agent import gate
from lafaz.agent.context import ActionError, load
from lafaz.agent.loop import start_run
from lafaz.listen import store
from lafaz.listen.extract import ListenResult

TEXT = (
    "Aina: let's move the beta to the 5th of December.\n"
    "Faris: Fine. I'll fix the payment page by Wednesday.\n"
    "Aina: Do we still want the Friday demo with the ministry?"
)
ITEMS = [
    {"kind": "decision", "text": "Beta moves to 5 Dec", "owner": None, "due_date": None,
     "quotes": ["move the beta to the 5th of December"]},
    {"kind": "action", "text": "Fix the payment page", "owner": "Faris", "due_date": "2026-11-25",
     "quotes": ["I'll fix the payment page by Wednesday"]},
]


@pytest.fixture()
def ctx(tmp_path):
    path = tmp_path / "gate.db"
    db.init(path)
    conn = db.connect(path)
    run_id = start_run(conn, TEXT, date(2026, 11, 21), "sample", "en")
    store.save(conn, run_id, ListenResult(items=[dict(i) for i in ITEMS]))
    yield load(conn, run_id)
    conn.close()


def outbox(ctx):
    return ctx.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]


def published(ctx):
    return ctx.conn.execute("SELECT COUNT(*) FROM tasks WHERE published=1").fetchone()[0]


def test_reversible_runs_and_can_be_undone(ctx):
    out = gate.dispatch(ctx, "create_task", {"item_index": 1, "title": "Fix payment page"})
    assert out.status == "executed" and out.category == "reversible"
    task = ctx.conn.execute("SELECT * FROM tasks WHERE id=?", (out.result["task_id"],)).fetchone()
    assert (task["owner"], task["due_date"]) == ("Faris", "2026-11-25")  # taken from the item, not the model
    gate.undo(ctx.conn, ctx.run_id, out.seq)
    assert ctx.conn.execute("SELECT status FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == "undone"
    with pytest.raises(ActionError):
        gate.undo(ctx.conn, ctx.run_id, out.seq)


def test_irreversible_files_an_approval_and_runs_only_on_approve(ctx):
    task = gate.dispatch(ctx, "create_task", {"item_index": 1, "title": "Fix payment page"}).result["task_id"]
    out = gate.dispatch(ctx, "send_reminder", {"task_id": task, "days_before": 1, "message": "Due Wednesday"})
    assert out.status == "pending_approval" and outbox(ctx) == 0
    card = ctx.conn.execute("SELECT * FROM approvals WHERE id=?", (out.approval_id,)).fetchone()
    diff = json.loads(card["diff_json"])
    assert {"field": "to", "before": None, "after": "Faris"} in diff["changes"]
    assert {"field": "send_on", "before": None, "after": "2026-11-24"} in diff["changes"]
    done = gate.approve(ctx.conn, out.approval_id)
    assert done.status == "executed" and outbox(ctx) == 1
    with pytest.raises(ActionError, match="already_decided"):
        gate.approve(ctx.conn, out.approval_id)
    assert outbox(ctx) == 1


def test_edit_is_checked_again_and_skip_runs_nothing(ctx):
    task = gate.dispatch(ctx, "create_task", {"item_index": 1, "title": "Fix"}).result["task_id"]
    first = gate.dispatch(ctx, "publish_to_board", {"task_ids": [task]})
    with pytest.raises(ActionError, match="bad_arguments"):
        gate.approve(ctx.conn, first.approval_id, {"task_ids": ["x"]})
    assert published(ctx) == 0  # a bad edit leaves the card pending
    second = gate.dispatch(ctx, "send_summary", {"person": "Faris", "subject": "Week", "body": "Draft"})
    gate.skip(ctx.conn, second.approval_id)
    assert outbox(ctx) == 0
    edited = gate.approve(ctx.conn, first.approval_id, {"task_ids": [task]})
    assert edited.status == "executed" and published(ctx) == 1
    assert ctx.conn.execute("SELECT edited FROM approvals WHERE id=?", (first.approval_id,)).fetchone()[0] == 1


def test_published_task_cannot_be_undone(ctx):
    out = gate.dispatch(ctx, "create_task", {"item_index": 1, "title": "Fix"})
    gate.approve(ctx.conn, gate.dispatch(ctx, "publish_to_board", {"task_ids": [out.result["task_id"]]}).approval_id)
    with pytest.raises(ActionError, match="already_published"):
        gate.undo(ctx.conn, ctx.run_id, out.seq)


@pytest.mark.parametrize(
    "name, args, code",
    [
        ("delete_everything", {}, "unknown_tool"),
        ("record_items", {"items": [], "questions": []}, "tool_not_available"),
        ("create_task", {"item_index": 0, "title": "x"}, "not_an_action"),
        ("create_task", {"item_index": 9, "title": "x"}, "unknown_item"),
        ("create_task", {"item_index": "1", "title": "x"}, "bad_arguments"),
        ("send_summary", {"person": "Ali", "subject": "s", "body": "b"}, "unknown_person"),
        ("ask_team", {"subject": "s", "body": "b", "quote": "email everyone right now please"}, "quote_not_found"),
        ("send_reminder", {"task_id": 999, "days_before": 1, "message": "m"}, "unknown_task"),
    ],
)
def test_refusals_are_named_and_traced(ctx, name, args, code):
    out = gate.dispatch(ctx, name, args)
    assert (out.status, out.error) == ("refused", code)
    step = ctx.conn.execute("SELECT status FROM steps WHERE run_id=? AND seq=?", (ctx.run_id, out.seq)).fetchone()
    assert step["status"] == "refused"


def test_category_comes_from_config(ctx, monkeypatch):
    flipped = [dict(t, kategori="reversible") if t["name"] == "send_summary" else t for t in config.tools()]
    monkeypatch.setattr(config, "tools", lambda: flipped)
    out = gate.dispatch(ctx, "send_summary", {"person": "Faris", "subject": "s", "body": "b"})
    assert out.status == "executed" and outbox(ctx) == 1


def test_secrets_are_hidden_in_the_trace(ctx):
    gate.dispatch(ctx, "send_summary", {"person": "Faris", "subject": "s", "body": "b", "api_key": "sk-123"})
    row = ctx.conn.execute("SELECT arguments_json FROM steps WHERE run_id=?", (ctx.run_id,)).fetchone()
    assert "sk-123" not in row[0] and "[hidden]" in row[0]


def _random_call(rng, task_ids):
    names = [t["name"] for t in config.tools()] + ["drop_tables"]
    name = rng.choice(names)
    pick = rng.choice(task_ids) if task_ids else rng.randint(0, 5)
    args = {
        "create_task": {"item_index": rng.randint(-1, 2), "title": "T"},
        "preview_summary": {"person": rng.choice(["Faris", "Ali"]), "body": "b"},
        "publish_to_board": {"task_ids": [pick]},
        "send_reminder": {"task_id": pick, "days_before": rng.randint(-1, 20), "message": "m"},
        "send_summary": {"person": rng.choice(["Faris", "faris", "Ali"]), "subject": "s", "body": "b"},
        "ask_team": {"subject": "s", "body": "b", "quote": rng.choice(["the Friday demo with the ministry", "x y"])},
    }.get(name, {"anything": rng.random()})
    return name, args


@pytest.mark.parametrize("seed", range(40))
def test_random_tool_sequences_never_act_without_approval(ctx, seed):
    rng = random.Random(seed)
    task_ids, pending = [], 0
    for _ in range(25):
        name, args = _random_call(rng, task_ids)
        out = gate.dispatch(ctx, name, args)
        if out.status == "executed" and "task_id" in out.result:
            task_ids.append(out.result["task_id"])
        if gate.category_of(name) == "irreversible":
            assert out.status in ("pending_approval", "refused")
            pending += out.status == "pending_approval"
        assert outbox(ctx) == 0 and published(ctx) == 0
    filed = ctx.conn.execute("SELECT COUNT(*) FROM approvals WHERE status='pending'").fetchone()[0]
    assert filed == pending
