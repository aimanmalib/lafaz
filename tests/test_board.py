"""Board, exports, calendar feed and weekly summary (PRD 4.6, 4.7): each space sees only its own tasks, the feed is
valid iCalendar read back by a real parser, and publishing and sending stay irreversible in config."""

import csv
import io
import json
from datetime import date

import icalendar
import pytest

from lafaz import config, db
from lafaz.agent import gate
from lafaz.agent.context import load
from lafaz.board import ics, summary, tasks
from memory_helpers import meeting

TOKEN_ENV = config.mail()["env"]["owner_token"]
COOKIE = config.mail()["owner_cookie"]
DAY = date(2026, 11, 21)
TEXT = "Faris: I'll fix the payment page by Wednesday, with care; and a comma.\nAina: I'll write the launch note."
ITEMS = [
    {"kind": "action", "text": "Fix the payment page", "owner": "Faris", "due_date": "2026-11-25",
     "quotes": ["I'll fix the payment page by Wednesday, with care; and a comma."]},
    {"kind": "action", "text": "Write the launch note", "owner": "Aina", "due_date": None,
     "quotes": ["I'll write the launch note"]},
]


def _plan(conn, space, publish=True, reminder=False):
    run_id = meeting(conn, TEXT, DAY, ITEMS)
    conn.execute("UPDATE runs SET space=? WHERE id=?", (space, run_id))
    ctx = load(conn, run_id)
    ids = [gate.dispatch(ctx, "create_task", {"item_index": i, "title": item["text"]}).result["task_id"]
           for i, item in enumerate(ITEMS)]
    if publish:
        gate.approve(conn, gate.dispatch(ctx, "publish_to_board", {"task_ids": ids}).approval_id)
    if reminder:
        card = gate.dispatch(ctx, "send_reminder", {"task_id": ids[0], "days_before": 2, "message": "Due soon"})
        gate.approve(conn, card.approval_id)
    conn.commit()
    return run_id, ids


@pytest.fixture()
def conn():
    c = db.connect()
    c.execute("DELETE FROM reminder_policies")
    c.execute("UPDATE tasks SET status='undone'")
    c.commit()
    yield c
    c.close()


@pytest.fixture()
def owner_token(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "owner-token-for-board-tests")
    return "owner-token-for-board-tests"


def test_categories_come_from_config():
    assert gate.category_of("publish_to_board") == "irreversible"
    assert gate.category_of("send_summary") == "irreversible"
    assert gate.category_of("preview_summary") == "reversible"
    assert gate.category_of("create_task") == "reversible"


def test_unpublished_tasks_wait_off_the_board(conn):
    _plan(conn, "public", publish=False)
    assert tasks.published(conn, "public") == []
    assert tasks.waiting(conn, "public") == 2


def test_unpublished_tasks_stay_out_of_the_feed_and_weekly_summary(client, conn):
    _plan(conn, "public", publish=False)
    assert "BEGIN:VEVENT" not in ics.feed(conn, "public")
    assert summary.weekly(conn, "public", DAY) == []
    page = client.get("/board").text
    assert ITEMS[0]["text"] not in page and ITEMS[1]["text"] not in page


def test_board_page_shows_published_cards_with_quotes(client, conn):
    _, ids = _plan(conn, "public")
    page = client.get("/board").text
    assert f'id="task-{ids[0]}"' in page and "Fix the payment page" in page
    assert config.messages("en")["board.col.todo"] in page
    ms = client.get("/board?lang=ms").text
    assert config.messages("ms")["board.col.doing"] in ms


def test_moving_a_card_changes_its_column_and_bad_moves_are_404(client, conn):
    _, ids = _plan(conn, "public")
    assert client.post(f"/board/task/{ids[0]}/doing", follow_redirects=False).status_code == 303
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (ids[0],)).fetchone()[0] == "doing"
    assert client.post(f"/board/task/{ids[0]}/undone").status_code == 404
    assert client.post("/board/task/999999/done").status_code == 404


def test_owner_tasks_never_reach_the_public_board_exports_or_feed(client, conn, owner_token):
    _, owner_ids = _plan(conn, "owner")
    assert client.post(f"/board/task/{owner_ids[0]}/done").status_code == 404
    rows = json.loads(client.get("/board.json").text)["tasks"]
    assert all(r["id"] not in owner_ids for r in rows)
    csv_ids = {row["id"] for row in csv.DictReader(io.StringIO(client.get("/board.csv").text))}
    assert not csv_ids & {str(i) for i in owner_ids}
    assert f"task-{owner_ids[0]}@" not in client.get("/ics/public.ics").text
    client.cookies.set(COOKIE, owner_token)
    rows = json.loads(client.get("/board.json").text)["tasks"]
    assert {r["id"] for r in rows} == set(owner_ids)


def test_exports_have_the_configured_fields(client, conn):
    _, ids = _plan(conn, "public")
    fields = config.board()["export"]["fields"]
    r = client.get("/board.csv")
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert list(rows[0].keys()) == fields
    assert {int(row["id"]) for row in rows} == set(ids)
    data = client.get("/board.json").json()["tasks"]
    assert all(list(row.keys()) == fields for row in data)


def test_feed_parses_with_alarms_and_escaped_text(client, conn):
    _, ids = _plan(conn, "public", reminder=True)
    r = client.get(f"/ics/{config.board()['ics']['public_token']}.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    cal = icalendar.Calendar.from_ical(r.content)
    events = [e for e in cal.walk("VEVENT")]
    assert len(events) == 1  # the second task has no due date
    event = events[0]
    assert str(event["UID"]).startswith(f"task-{ids[0]}@")
    assert event.decoded("DTSTART") == date(2026, 11, 25)
    assert event.decoded("DTEND") == date(2026, 11, 26)
    assert str(event["DESCRIPTION"]) == ITEMS[0]["quotes"][0]
    alarms = event.walk("VALARM")
    assert len(alarms) == 1 and str(alarms[0]["TRIGGER"].to_ical(), "ascii") == "-P2D"


def test_done_and_undone_tasks_leave_the_feed(conn):
    _, ids = _plan(conn, "public")
    tasks.move(conn, "public", ids[0], "done")
    assert "BEGIN:VEVENT" not in ics.feed(conn, "public")


def test_long_lines_fold_inside_75_octets_without_breaking_characters():
    line = "SUMMARY:" + "Mesyuarat pelancaran beta é " * 10
    folded = ics.fold(line)
    assert all(len(part.encode("utf-8")) <= 75 for part in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == line


def test_owner_feed_token_is_derived_and_unknown_tokens_are_404(client, conn, monkeypatch, owner_token):
    token = ics.owner_token()
    assert token and owner_token not in token and len(token) == config.board()["ics"]["owner_token_chars"]
    assert client.get(f"/ics/{token}.ics").status_code == 200
    assert client.get("/ics/not-a-token.ics").status_code == 404
    monkeypatch.delenv(TOKEN_ENV)
    assert ics.owner_token() is None
    assert client.get(f"/ics/{token}.ics").status_code == 404


def test_weekly_summary_groups_by_person_and_counts_overdue(conn):
    _, ids = _plan(conn, "public")
    tasks.move(conn, "public", ids[1], "done")
    people = {p["person"]: p for p in summary.weekly(conn, "public", date(2026, 11, 27))}
    assert people["Faris"]["overdue"] == 1 and len(people["Faris"]["open"]) == 1
    assert len(people["Aina"]["done"]) == 1 and people["Aina"]["overdue"] == 0
    assert summary.weekly(conn, "public", date(2026, 12, 30)) == []
