"""Conflicts: code picks candidates, the model judges, code checks both quotes, a person decides the card."""

import json

import pytest

from fakes import FakeClient, response, tool_use
from lafaz import config
from lafaz.agent import gate
from lafaz.agent.context import ActionError
from lafaz.llm import LLM
from lafaz.memory import conflicts, decisions
from memory_helpers import D1, D2, NEW, NEW_TEXT, OLD, OLD_TEXT, decision, meeting, open_db

VALID = {"conflict": True, "old_quote": "beta launch is on the 5th of December",
         "new_quote": "beta launch is on the 12th of December", "reason": "Two dates for one launch."}


def judge(payload=VALID):
    return response([tool_use("judge_conflict", payload)])


@pytest.fixture()
def conn(tmp_path):
    c = open_db(tmp_path)
    meeting(c, OLD_TEXT, D1, [OLD])
    conflicts.detect(c, 1, LLM(FakeClient()))  # first meeting: nothing earlier, so no model call
    yield c
    c.close()


def second(conn, *replies, items=(NEW,)):
    run_id = meeting(conn, NEW_TEXT, D2, list(items))
    fake = FakeClient(*replies)
    counts = conflicts.detect(conn, run_id, LLM(fake))
    return run_id, counts, fake


def card(conn):
    return conn.execute("SELECT * FROM conflicts ORDER BY id DESC").fetchone()


def test_candidates_are_chosen_by_shared_terms():
    assert {"beta", "launch", "december"} <= decisions.terms(OLD["text"] + " " + OLD["quotes"][0])
    assert "the" not in decisions.terms("the beta") and "dan" not in decisions.terms("beta dan launch")


def test_unrelated_decision_never_reaches_the_model(conn):
    other = decision("Hall booking moves to Room 4", "Mei: Noted.")
    run_id, counts, fake = second(conn, items=[other])
    assert counts == {} and fake.requests == []


def test_conflict_with_both_quotes_checked_opens_a_card(conn):
    run_id, counts, fake = second(conn, judge())
    assert counts == {"conflict": 1}
    row = card(conn)
    assert row["status"] == "open" and "beta" in row["shared_terms"].split()
    assert row["old_quote"].casefold() in OLD_TEXT.casefold() and row["new_quote"].casefold() in NEW_TEXT.casefold()
    sent = fake.requests[0]["messages"][0]["content"]
    assert OLD_TEXT in sent and NEW_TEXT in sent
    step = conn.execute("SELECT category FROM steps WHERE run_id=? AND tool='judge_conflict'", (run_id,)).fetchone()
    assert step["category"] == config.tool("judge_conflict")["kategori"]


@pytest.mark.parametrize("payload, reason", [
    (dict(VALID, old_quote=VALID["new_quote"]), "old_quote_not_found"),
    (dict(VALID, new_quote=VALID["old_quote"]), "new_quote_not_found"),
    (dict(VALID, new_quote="12th December"), "new_quote_too_short"),
])
def test_a_quote_from_the_wrong_meeting_is_rejected(conn, payload, reason):
    _, counts, _ = second(conn, judge(payload))
    row = card(conn)
    assert counts == {"rejected": 1} and row["reject_reason"] == reason and row["status"] == "closed"
    assert conflicts.open_cards(conn, row["run_id"]) == []


def test_no_conflict_is_closed(conn):
    _, counts, _ = second(conn, judge(dict(VALID, conflict=False)))
    assert counts == {"no_conflict": 1} and card(conn)["status"] == "closed"


def test_model_failure_and_budget_are_recorded_not_dropped(conn):
    class Spent:
        steps = 0
        def exceeded(self):
            return "limit_steps"
    run_id = meeting(conn, NEW_TEXT, D2, [NEW])
    assert conflicts.detect(conn, run_id, LLM(FakeClient()), Spent()) == {"not_judged": 1}
    assert card(conn)["reject_reason"] == "limit_steps"


def test_replace_supersedes_and_undo_restores(conn):
    run_id, _, _ = second(conn, judge())
    out = conflicts.resolve(conn, card(conn)["id"], "replace")
    assert out.status == "executed" and out.category == "reversible"
    old = conn.execute("SELECT status, superseded_by FROM decisions WHERE id=1").fetchone()
    assert tuple(old) == ("superseded", 2)
    third = meeting(conn, NEW_TEXT + "\nAina: Thanks, all.", D2, [NEW])
    assert [d["id"] for d, _ in decisions.candidates(conn, decisions.save_run(conn, third)[0])] == [2]
    gate.undo(conn, run_id, out.seq)
    assert conn.execute("SELECT status FROM decisions WHERE id=1").fetchone()[0] == "active"
    assert card(conn)["status"] == "open"


def test_keep_both_closes_the_card(conn):
    second(conn, judge())
    out = conflicts.resolve(conn, card(conn)["id"], "keep")
    assert out.status == "executed" and card(conn)["status"] == "kept"
    assert conn.execute("SELECT COUNT(*) FROM decisions WHERE status='active'").fetchone()[0] == 2
    with pytest.raises(ActionError, match="already_decided"):
        conflicts.resolve(conn, card(conn)["id"], "replace")


def test_ask_the_team_waits_for_a_person(conn):
    second(conn, judge())
    out = conflicts.resolve(conn, card(conn)["id"], "ask")
    assert out.status == "pending_approval" and card(conn)["status"] == "asked"
    assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    diff = json.loads(conn.execute("SELECT diff_json FROM approvals WHERE id=?", (out.approval_id,)).fetchone()[0])
    body = next(c["after"] for c in diff["changes"] if c["field"] == "body")
    assert "2026-11-14" in body and VALID["old_quote"] in body and VALID["new_quote"] in body
    gate.approve(conn, out.approval_id)
    assert conn.execute("SELECT recipient FROM outbox").fetchone()[0] == "team"


def test_card_category_comes_from_config(conn, monkeypatch):
    second(conn, judge())
    flipped = [dict(t, kategori="irreversible") if t["name"] == "replace_decision" else t for t in config.tools()]
    monkeypatch.setattr(config, "tools", lambda: flipped)
    out = conflicts.resolve(conn, card(conn)["id"], "replace")
    assert out.status == "pending_approval"
    assert conn.execute("SELECT status FROM decisions WHERE id=1").fetchone()[0] == "active"


def test_card_tools_are_not_offered_to_the_loop():
    names = {t["name"] for t in gate.plan_tools()}
    assert not names & {"replace_decision", "keep_both_decisions", "judge_conflict"}


def test_unknown_choice_is_refused(conn):
    second(conn, judge())
    with pytest.raises(ActionError, match="unknown_choice"):
        conflicts.resolve(conn, card(conn)["id"], "delete")


def test_the_same_meeting_text_again_is_not_a_conflict(conn):
    """A sample tried twice restates its decisions; judging them against each other only adds noise."""
    first = decisions.save_run(conn, meeting(conn, NEW_TEXT, D2, [NEW]))[0]
    again = meeting(conn, NEW_TEXT, D2, [NEW])
    found = [d["id"] for d, _ in decisions.candidates(conn, decisions.save_run(conn, again)[0])]
    assert first not in found and found  # the older, different meeting is still a candidate
