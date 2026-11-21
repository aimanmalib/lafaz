"""Reminder policies: approved once, then the scheduler sends only inside the policy."""

import asyncio
import json
from datetime import date

import pytest

from lafaz import config
from lafaz.agent import gate
from lafaz.agent.context import load
from lafaz.memory import reminders, scheduler
from memory_helpers import D2, meeting, open_db

TEXT = "Faris: I'll fix the payment page by Wednesday."
ACTION = {"kind": "action", "text": "Fix the payment page", "owner": "Faris", "due_date": "2026-11-25",
          "quotes": ["I'll fix the payment page by Wednesday"]}


@pytest.fixture()
def setup(tmp_path):
    conn = open_db(tmp_path)
    ctx = load(conn, meeting(conn, TEXT, D2, [ACTION]))
    task = gate.dispatch(ctx, "create_task", {"item_index": 0, "title": "Fix payment page"})
    yield conn, ctx, task


def approve_policy(ctx, task, days_before=1):
    card = gate.dispatch(ctx, "send_reminder", {"task_id": task.result["task_id"], "days_before": days_before,
                                                "message": "Due Wednesday"})
    gate.approve(ctx.conn, card.approval_id)
    return card.approval_id


def sent(conn):
    return [dict(r) for r in conn.execute("SELECT recipient, label, policy_id, approval_id FROM outbox")]


def test_policy_sends_once_on_its_day_and_never_after(setup):
    conn, ctx, task = setup
    approval = approve_policy(ctx, task)
    assert reminders.tick(conn, date(2026, 11, 23)) == [] and sent(conn) == []
    assert len(reminders.tick(conn, date(2026, 11, 24))) == 1
    assert sent(conn) == [{"recipient": "Faris", "label": "approved_once", "policy_id": 1, "approval_id": approval}]
    for day in (24, 25, 26):
        reminders.tick(conn, date(2026, 11, day))
    assert len(sent(conn)) == 1
    step = conn.execute("SELECT category, status FROM steps WHERE tool='send_reminder' ORDER BY seq DESC").fetchone()
    assert tuple(step) == ("irreversible", "policy_send")


def test_more_sends_stay_inside_the_window(setup, monkeypatch):
    conn, ctx, task = setup
    mem = json.loads(json.dumps(config.memory()))
    mem["reminders"]["max_sends_per_policy"] = 5
    monkeypatch.setattr(config, "memory", lambda: mem)
    approve_policy(ctx, task, days_before=1)
    for day in (22, 23, 24, 24, 25, 26, 27):
        reminders.tick(conn, date(2026, 11, day))
    assert len(sent(conn)) == 2  # the 24th once, the 25th (due day); nothing before or after
    assert conn.execute("SELECT status FROM reminder_policies").fetchone()[0] == "finished"


def test_undone_task_stops_the_policy(setup):
    conn, ctx, task = setup
    approve_policy(ctx, task)
    gate.undo(conn, ctx.run_id, task.seq)
    assert reminders.tick(conn, date(2026, 11, 24)) == []
    assert conn.execute("SELECT status FROM reminder_policies").fetchone()[0] == "stopped"


def test_skipped_policy_never_sends(setup):
    conn, ctx, task = setup
    card = gate.dispatch(ctx, "send_reminder", {"task_id": task.result["task_id"], "days_before": 1, "message": "m"})
    gate.skip(conn, card.approval_id)
    assert reminders.tick(conn, date(2026, 11, 24)) == [] and sent(conn) == []


def test_scheduler_loop_runs_passes_and_survives_a_failure(monkeypatch):
    calls = []

    def fake_pass():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("one bad pass")
        return []

    monkeypatch.setattr(scheduler, "run_once", fake_pass)

    async def drive():
        task = asyncio.create_task(scheduler.loop(interval=0.01))
        for _ in range(500):  # up to 5 s on a slow runner
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(drive())
    assert len(calls) >= 2


def test_scheduler_interval_comes_from_config():
    assert config.settings()["scheduler"]["reminder_check_seconds"] > 0
