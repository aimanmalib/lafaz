"""/run/<id>: the marked transcript, items, approval cards, undo, conflict cards, the handoff banner and the trace."""

import re
from datetime import date

import pytest

from fakes import FakeClient, response, text, tool_use
from lafaz import config, db, runner
from lafaz.agent.loop import start_run
from lafaz.llm import LLM
from lafaz.memory import conflicts
from memory_helpers import D1, D2, NEW, NEW_TEXT, OLD, OLD_TEXT, meeting

KEY_ENV = config.settings()["llm"]["key_env"]
TEXT = (
    "Aina: The beta goes out on the 28th, actually no, let’s move the beta to the 5th of December.\n"
    "Faris: Fine. I'll fix the payment page by Wednesday.\n"
    "Mei: Do we still want the Friday demo with the ministry?"
)
LISTENED = {
    "items": [
        {"kind": "decision", "text": "Beta moves to 5 December", "owner": None, "due_phrase": None,
         "quotes": ["let's move the beta to the 5th of December"], "confidence": "high",
         "corrects": {"old_quote": "The beta goes out on the 28th", "new_quote": "let's move the beta to the 5th of December"}},
        {"kind": "action", "text": "Fix the payment page", "owner": "Faris", "due_phrase": "by Wednesday",
         "quotes": ["I'll fix the payment page by Wednesday"], "corrects": None, "confidence": "high"},
        {"kind": "fact", "text": "Invented", "owner": None, "due_phrase": None,
         "quotes": ["this sentence was never said"], "corrects": None, "confidence": "low"},
    ],
    "questions": [{"item_index": None, "question": "Is the Friday demo still on?",
                   "quote": "the Friday demo with the ministry"}],
}


def replies():
    return FakeClient(
        response([tool_use("record_items", LISTENED)]),
        response([tool_use("create_task", {"item_index": 1, "title": "Fix payment page"}, id="a")]),
        response([tool_use("send_summary", {"person": "Faris", "subject": "Payment page", "body": "Due Wednesday."},
                           id="b")]),
        response([text("One task, one email waiting.")], stop_reason="end_turn"),
    )


@pytest.fixture(autouse=True)
def own_db(tmp_path, monkeypatch):
    """Each test gets a fresh database: earlier decisions would otherwise open conflict checks in later runs."""
    monkeypatch.setenv("LAFAZ_DB", str(tmp_path / "run-page.db"))
    db.init()


@pytest.fixture()
def live(monkeypatch):
    """Live mode with a scripted model; the worker thread runs inline so the test sees the finished run."""
    monkeypatch.setenv(KEY_ENV, "test-only")
    fake = replies()
    monkeypatch.setattr(runner, "make_llm", lambda: LLM(fake))
    monkeypatch.setattr(runner, "spawn", lambda work: work())
    return fake


def start(client, **form):
    data = {"text": TEXT, "meeting_date": "2026-11-21", **form}
    r = client.post("/run", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text[:300]
    return r.headers["location"]


def conn():
    return db.connect()


def test_without_a_key_nothing_runs_or_is_stored(client, monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    before = conn().execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    r = client.post("/run", data={"text": TEXT, "meeting_date": "2026-11-21"})
    assert r.status_code == 503
    assert config.messages("en")["run.not_live"] in r.text
    assert conn().execute("SELECT COUNT(*) FROM runs").fetchone()[0] == before


def test_bad_date_is_refused(client, live):
    r = client.post("/run", data={"text": TEXT, "meeting_date": "21/11/2026"})
    assert r.status_code == 422 and config.messages("en")["run.bad_date"] in r.text


def test_run_page_marks_quotes_items_and_cards(client, live):
    url = start(client, source="sample")
    page = client.get(url).text
    en = config.messages("en")
    # Heard: the decision mark covers the words as said (curly apostrophe kept), the correction is struck through
    assert '<mark class="mk mk-decision" style="--i: 0">let’s move the beta to the 5th of December</mark>' in page
    assert '<s class="corrected">The beta goes out on the 28th</s>' in page and en["run.corrected"] in page
    assert "mk mk-question" in page  # the model's question is painted too
    assert "this sentence was never said" not in page.split('id="heard-h"')[1].split("</section>")[0]
    # Understood: owner and resolved date as chips, the set-aside item counted
    assert en["item.owner"].replace("{name}", "Faris") in page
    assert en["item.due"].replace("{date}", "2026-11-25") in page
    assert en["run.set_aside"].replace("{n}", "1") in page
    # Plan: the irreversible email waits on a sealed card; the reversible task can be undone
    assert "card card-seal" in page and en["plan.approve"] in page
    assert en["plan.undo"] in page
    # The run asked a question, so it stopped on purpose and says why
    assert en["handoff.heading"] in page and en["handoff.reason.missing_facts"] in page
    assert "hx-trigger" not in page
    assert conn().execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0


def test_malay_run_page(client, live):
    url = start(client)
    page = client.get(url + "?lang=ms").text
    assert '<html lang="ms">' in page and config.messages("ms")["run.heard"] in page


def _approval_url(url):
    c = conn()
    run_id = int(url.rsplit("/", 1)[1])
    aid = c.execute("SELECT id FROM approvals WHERE run_id=? AND status='pending'", (run_id,)).fetchone()[0]
    return run_id, aid, f"{url}/approvals/{aid}"


def test_approve_runs_the_action_once(client, live):
    url = start(client)
    run_id, aid, a_url = _approval_url(url)
    r = client.post(a_url + "/approve", headers={"HX-Request": "true"})
    assert r.status_code == 200 and 'id="run"' in r.text and "<html" not in r.text
    assert config.messages("en")["approval.approved"] in r.text
    assert conn().execute("SELECT COUNT(*) FROM outbox WHERE approval_id=?", (aid,)).fetchone()[0] == 1
    again = client.post(a_url + "/approve", headers={"HX-Request": "true"})
    assert again.status_code == 409 and config.messages("en")["action_error.already_decided"] in again.text
    assert conn().execute("SELECT COUNT(*) FROM outbox WHERE approval_id=?", (aid,)).fetchone()[0] == 1


def test_edit_then_approve_sends_the_edited_text(client, live):
    url = start(client)
    _, aid, a_url = _approval_url(url)
    r = client.post(a_url + "/edit", data={"subject": "Payment page, new subject", "body": "Due Wed.",
                                           "person": "Faris"}, follow_redirects=False)
    assert r.status_code == 303
    row = conn().execute("SELECT subject, body FROM outbox WHERE approval_id=?", (aid,)).fetchone()
    assert tuple(row) == ("Payment page, new subject", "Due Wed.")
    assert conn().execute("SELECT edited FROM approvals WHERE id=?", (aid,)).fetchone()[0] == 1


def test_bad_edit_keeps_the_card_pending(client, live):
    url = start(client)
    _, aid, a_url = _approval_url(url)
    r = client.post(a_url + "/edit", data={"person": "Nobody", "subject": "x", "body": "y"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 409
    assert conn().execute("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0] == "failed"
    assert conn().execute("SELECT COUNT(*) FROM outbox WHERE approval_id=?", (aid,)).fetchone()[0] == 0


def test_skip_sends_nothing(client, live):
    url = start(client)
    _, aid, a_url = _approval_url(url)
    client.post(a_url + "/skip")
    assert conn().execute("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0] == "skipped"
    assert conn().execute("SELECT COUNT(*) FROM outbox WHERE approval_id=?", (aid,)).fetchone()[0] == 0


def test_approval_from_another_run_is_not_found(client, live):
    url = start(client)
    _, aid, _ = _approval_url(url)
    other = start_run(conn(), "Aina: something else entirely here.", date(2026, 11, 21), "wispr", "en")
    assert client.post(f"/run/{other}/approvals/{aid}/approve").status_code == 404
    assert client.post(f"{url}/approvals/{aid}/delete").status_code == 404


def test_undo_a_created_task(client, live):
    url = start(client)
    run_id = int(url.rsplit("/", 1)[1])
    seq = conn().execute("SELECT seq FROM steps WHERE run_id=? AND tool='create_task'", (run_id,)).fetchone()[0]
    r = client.post(f"{url}/steps/{seq}/undo", headers={"HX-Request": "true"})
    assert r.status_code == 200 and config.messages("en")["plan.undone"] in r.text
    assert conn().execute("SELECT status FROM tasks WHERE run_id=?", (run_id,)).fetchone()[0] == "undone"
    assert client.post(f"{url}/steps/{seq}/undo", headers={"HX-Request": "true"}).status_code == 409


def test_conflict_card_buttons(client):
    c = conn()
    meeting(c, OLD_TEXT, D1, [OLD])
    conflicts.detect(c, c.execute("SELECT MAX(id) FROM runs").fetchone()[0], LLM(FakeClient()))
    run_id = meeting(c, NEW_TEXT, D2, [NEW])
    judged = {"conflict": True, "old_quote": "beta launch is on the 5th of December",
              "new_quote": "beta launch is on the 12th of December", "reason": "Two dates for one launch."}
    conflicts.detect(c, run_id, LLM(FakeClient(response([tool_use("judge_conflict", judged)]))))
    c.execute("UPDATE runs SET status='done' WHERE id=?", (run_id,))
    c.commit()
    cid = c.execute("SELECT id FROM conflicts WHERE run_id=? AND verdict='conflict'", (run_id,)).fetchone()[0]
    page = client.get(f"/run/{run_id}").text
    en = config.messages("en")
    assert en["conflict.heading"] in page and en["conflict.choice.replace"] in page
    r = client.post(f"/run/{run_id}/conflicts/{cid}/replace", headers={"HX-Request": "true"})
    assert r.status_code == 200 and en["conflict.status.replaced"] in r.text
    assert client.post(f"/run/{run_id}/conflicts/{cid}/keep", headers={"HX-Request": "true"}).status_code == 409


def test_unfinished_run_polls_and_restart_closes_it(client):
    run_id = start_run(conn(), "Aina: we ship the beta on Friday.", date(2026, 11, 21), "wispr", "en")
    page = client.get(f"/run/{run_id}").text
    assert re.search(r'hx-get="/run/%d/body\?lang=en" hx-trigger="every \d+s"' % run_id, page)
    assert config.messages("en")["run.working"] in page
    assert runner.recover() >= 1
    page = client.get(f"/run/{run_id}/body").text
    assert "hx-trigger" not in page and config.messages("en")["handoff.reason.interrupted"] in page


def test_unknown_run_is_404(client):
    assert client.get("/run/999999").status_code == 404


def test_every_dynamic_key_has_text():
    en = config.messages("en")
    from lafaz.listen.quotes import REASONS

    needed = [f"tool.{t['name']}" for t in config.tools() if t.get("stage") in ("plan", "card")]
    needed += [f"kind.{k}" for k in ("decision", "action", "question", "fact")]
    needed += [f"source.{s}" for s in ("wispr", "transcript", "sample")] + ["mode.live", "mode.replay"]
    needed += [f"handoff.reason.{r}" for r in ("finished", "missing_facts", "nothing_heard", "limit_steps",
                                               "limit_seconds", "limit_cost", "model_error", "internal_error",
                                               "interrupted")]
    needed += [f"reject.{r}" for r in REASONS]
    needed += [f"approval.{s}" for s in ("pending", "approved", "skipped", "failed")]
    needed += [f"conflict.status.{s}" for s in ("open", "replaced", "kept", "asked", "closed")]
    needed += [f"conflict.choice.{c}" for c in config.memory()["conflict"]["choices"]]
    assert [k for k in needed if k not in en] == []
