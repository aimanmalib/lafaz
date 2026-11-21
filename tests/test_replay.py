"""Replay mode and the public limits (PRD 4.10): a recorded sample plays through the real checks, nothing else runs
without a key or budget, and the visitor address is trusted only from Cloudflare."""

import html

from markupsafe import escape
import json
from types import SimpleNamespace

import pytest

from fakes import FakeClient, response, tool_use
from lafaz import budget, config, db, replay, runner
from lafaz.agent.loop import start_run
from lafaz.llm import LLM

KEY_ENV = config.settings()["llm"]["key_env"]
SAMPLE = next(s for s in config.samples() if s.get("replay"))
CASSETTE = replay.load(SAMPLE)


@pytest.fixture(autouse=True)
def own_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFAZ_DB", str(tmp_path / "replay.db"))
    db.init()
    monkeypatch.setattr(runner, "spawn", lambda work: work())


def conn():
    return db.connect()


def post(client, text, day=None, **headers):
    return client.post("/run", data={"text": text, "meeting_date": day or SAMPLE["meeting_date"]},
                       headers=headers, follow_redirects=False)


def notice(key):
    return str(escape(config.messages("en")[key]))


def test_cassette_matches_its_sample():
    assert CASSETTE is not None, "record it: python -m lafaz.replay record " + SAMPLE["id"]
    assert CASSETTE["fingerprint"] == replay.fingerprint(SAMPLE["text"], SAMPLE["meeting_date"])
    assert CASSETTE["turns"] and all(t["tools"] for t in CASSETTE["turns"])


def test_sample_replays_without_a_key_even_with_browser_line_breaks(client, monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    # rows from an earlier run shift every id, so recorded ids must be rewritten to this run's rows
    c = conn()
    earlier = start_run(c, "Earlier: nothing here.", replay.date.fromisoformat("2026-11-01"), "wispr", "en")
    for n in range(5):
        c.execute("INSERT INTO tasks (run_id, title) VALUES (?, ?)", (earlier, f"old {n}"))
    c.commit()
    r = post(client, SAMPLE["text"].replace("\n", "\r\n"))
    assert r.status_code == 303, r.text[:300]
    run_id = int(r.headers["location"].rsplit("/", 1)[1])
    row = c.execute("SELECT mode, status, handoff_json FROM runs WHERE id=?", (run_id,)).fetchone()
    assert row["mode"] == "replay"
    assert json.loads(row["handoff_json"])["reason"] == CASSETTE["outcome"]["reason"]
    refused = c.execute("SELECT tool, result_summary FROM steps WHERE run_id=? AND status='refused'", (run_id,)).fetchall()
    assert [tuple(x) for x in refused] == []
    for (args,) in c.execute("SELECT arguments_json FROM approvals WHERE run_id=?", (run_id,)):
        data = json.loads(args)
        for task_id in data.get("task_ids", []) + ([data["task_id"]] if "task_id" in data else []):
            owner = c.execute("SELECT run_id FROM tasks WHERE id=?", (task_id,)).fetchone()
            assert owner is not None and owner[0] == run_id
    assert c.execute("SELECT COUNT(*) FROM outbox WHERE run_id=?", (run_id,)).fetchone()[0] == 0
    page = client.get(f"/run/{run_id}")
    assert html.escape(config.messages("en")["mode.replay"], quote=True) in page.text


def test_edited_text_is_not_replayed_or_stored(client, monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    r = post(client, SAMPLE["text"] + " One more line.")
    assert r.status_code == 503
    assert notice("run.not_live") in r.text
    assert conn().execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_other_meeting_date_is_not_replayed(client, monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    assert post(client, SAMPLE["text"], day="2026-12-01").status_code == 503


def test_unrecorded_request_is_a_model_error_not_a_crash():
    llm = LLM(replay.ReplayClient([]))
    with pytest.raises(Exception) as caught:
        llm.call_tool("system", "text", "record_items")
    assert getattr(caught.value, "code", "") == "replay_unrecorded"


def test_recorded_ids_follow_this_runs_rows():
    turns = [
        {"tools": ["create_task"], "results": {}, "stop_reason": "tool_use", "content": [
            {"type": "tool_use", "id": "u1", "name": "create_task", "input": {"item_index": 0, "title": "x"}}]},
        {"tools": ["create_task"], "results": {"u1": {"status": "done", "task_id": 1}}, "stop_reason": "tool_use",
         "content": [{"type": "tool_use", "id": "u2", "name": "publish_to_board", "input": {"task_ids": [1, 9]}}]},
    ]
    client = replay.ReplayClient(turns)
    client.beta.messages.create(tools=[{"name": "create_task"}], messages=[{"role": "user", "content": "go"}])
    second = client.beta.messages.create(tools=[{"name": "create_task"}], messages=[{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "u1", "content": json.dumps({"status": "done", "task_id": 57})}]}])
    assert second.content[0].input == {"task_ids": [57, 9]}
    assert second.usage.input_tokens == 0


def live_fake(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "test-only")
    fake = FakeClient(response([tool_use("record_items", {"items": [], "questions": []})]))
    monkeypatch.setattr(runner, "make_llm", lambda: LLM(fake))
    return fake


def spend(c, usd):
    run_id = start_run(c, "Spent.", replay.date.fromisoformat("2026-11-21"), "wispr", "en")
    c.execute("UPDATE runs SET cost_usd=?, status='done' WHERE id=?", (usd, run_id))
    c.commit()


def test_spent_budget_falls_back_to_replay_for_the_sample_only(client, monkeypatch):
    fake = live_fake(monkeypatch)
    spend(conn(), config.settings()["public_budget"]["usd_per_day"])
    r = post(client, "Aina: a new meeting nobody recorded.")
    assert r.status_code == 503 and notice("run.budget_spent") in r.text
    r = post(client, SAMPLE["text"])
    assert r.status_code == 303
    assert conn().execute("SELECT mode FROM runs ORDER BY id DESC").fetchone()[0] == "replay"
    assert fake.requests == []


def test_runs_per_address_are_limited(client, monkeypatch):
    live_fake(monkeypatch)
    monkeypatch.setitem(config.settings()["public_budget"], "runs_per_ip_per_day", 2)
    for _ in range(2):
        assert post(client, "Aina: we agreed to paint the hall blue.").status_code == 303
    r = post(client, "Aina: we agreed to paint the hall blue.")
    assert r.status_code == 503 and notice("run.ip_limit") in r.text
    # another address still gets its runs
    monkeypatch.setattr(budget, "client_ip", lambda request: "198.51.100.7")
    assert post(client, "Aina: we agreed to paint the hall blue.").status_code == 303


def request(peer, headers):
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers={k.lower(): v for k, v in headers.items()})


def test_cloudflare_header_trusted_only_from_cloudflare():
    cf = {"cf-connecting-ip": "203.0.113.9"}
    # direct to the host proxy from a non-Cloudflare address: the header is ignored
    assert budget.client_ip(request("172.18.0.5", {**cf, "x-forwarded-for": "198.51.100.1"})) == "198.51.100.1"
    # via Cloudflare: the proxy saw a Cloudflare edge address
    assert budget.client_ip(request("172.18.0.5", {**cf, "x-forwarded-for": "1.2.3.4, 162.158.1.1"})) == "203.0.113.9"
    # a public peer cannot claim a forwarded address
    assert budget.client_ip(request("8.8.4.4", {**cf, "x-forwarded-for": "162.158.1.1"})) == "8.8.4.4"
    # a malformed header is not used
    assert budget.client_ip(request("162.158.1.1", {"cf-connecting-ip": "not-an-ip"})) == "162.158.1.1"
