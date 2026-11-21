"""People memory: owners and speakers are remembered, and the next run's listen call knows them."""

from datetime import date

from fakes import FakeClient, response, text, tool_use
from lafaz.agent.loop import run, start_run
from lafaz.llm import LLM
from lafaz.memory import people
from memory_helpers import D2, NEW, NEW_TEXT, OLD, OLD_TEXT, meeting, open_db


def test_upsert_merges_aliases_and_keeps_email(tmp_path):
    conn = open_db(tmp_path)
    people.upsert(conn, "Faris", ["Fariz"], "faris@example.test")
    people.upsert(conn, "Faris", ["Ris"], None)
    assert people.all_people(conn) == [{"name": "Faris", "aliases": ["Fariz", "Ris"], "email": "faris@example.test"}]


def test_owners_and_speakers_are_remembered(tmp_path):
    conn = open_db(tmp_path)
    item = {"kind": "action", "text": "Book the hall", "owner": "Faris", "speaker": "Aina", "due_date": None,
            "quotes": ["I'll book the hall"]}
    run_id = meeting(conn, OLD_TEXT, D2, [item])
    assert people.remember_run(conn, run_id) == 2
    assert people.remember_run(conn, run_id) == 0


def test_loop_passes_known_people_and_judges_conflicts(tmp_path):
    conn = open_db(tmp_path)
    people.upsert(conn, "Faris")
    first = meeting(conn, OLD_TEXT, date(2026, 11, 14), [OLD])
    from lafaz.memory import decisions
    decisions.save_run(conn, first)
    listened = {"items": [dict(NEW, owner=None, due_phrase=None, corrects=None, confidence="high")],
                "questions": []}
    verdict = {"conflict": True, "old_quote": "beta launch is on the 5th of December",
               "new_quote": "beta launch is on the 12th of December", "reason": "Two dates."}
    fake = FakeClient(response([tool_use("record_items", listened)]), response([tool_use("judge_conflict", verdict)]),
                      response([text("Nothing to do.")], stop_reason="end_turn"))
    run_id = start_run(conn, NEW_TEXT, D2, "sample", "en")
    out = run(conn, run_id, NEW_TEXT, D2, llm=LLM(fake))
    assert "Known people: Faris" in fake.requests[0]["messages"][0]["content"]
    assert fake.requests[1]["tools"][0]["name"] == "judge_conflict"
    assert len(out["conflicts"]) == 1
