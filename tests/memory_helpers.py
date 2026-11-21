"""Shared set-up for memory tests: store a meeting whose listen result is already known."""

from datetime import date

from lafaz import db
from lafaz.agent.loop import start_run
from lafaz.listen import store
from lafaz.listen.extract import ListenResult


def open_db(tmp_path, name="memory.db"):
    path = tmp_path / name
    db.init(path)
    return db.connect(path)


def meeting(conn, text, day, items, lang="en"):
    run_id = start_run(conn, text, day, "sample", lang)
    store.save(conn, run_id, ListenResult(items=[dict(i) for i in items]))
    return run_id


def decision(text, quote):
    return {"kind": "decision", "text": text, "owner": None, "due_date": None, "quotes": [quote]}


D1 = date(2026, 11, 14)
D2 = date(2026, 11, 21)
OLD_TEXT = "Aina: Okay, the beta launch is on the 5th of December.\nFaris: I'll book the hall."
NEW_TEXT = "Aina: Change of plan, the beta launch is on the 12th of December.\nMei: Noted."
OLD = decision("Beta launch on 5 December", "the beta launch is on the 5th of December")
NEW = decision("Beta launch on 12 December", "the beta launch is on the 12th of December")
