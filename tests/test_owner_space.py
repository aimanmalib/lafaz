"""The owner space: a secret link sets a cookie, runs started with it are owner runs, and the run page shows the
outbox with each email's delivery state (PRD 4.7)."""

import pytest

from lafaz import config, db, runner
from lafaz.mail import delivery
from test_run_page import _approval_url, live, start  # noqa: F401 - `live` is a fixture

TOKEN_ENV = config.mail()["env"]["owner_token"]
COOKIE = config.mail()["owner_cookie"]
EN = config.messages("en")
MS = config.messages("ms")


@pytest.fixture()
def token(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "owner-token-for-tests")
    return "owner-token-for-tests"


def test_no_token_configured_means_no_owner_space(client, monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    assert client.get("/owner/anything", follow_redirects=False).status_code == 404
    client.cookies.set(COOKIE, "")
    assert EN["space.owner_note"] not in client.get("/").text


def test_wrong_token_is_not_found(client, token):
    r = client.get("/owner/not-the-token", follow_redirects=False)
    assert r.status_code == 404 and COOKIE not in r.headers.get("set-cookie", "")


def test_link_sets_an_httponly_cookie_and_runs_start_in_the_owner_space(client, token, live):
    r = client.get(f"/owner/{token}", follow_redirects=False)
    assert r.status_code == 303
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert EN["space.owner_note"] in client.get("/").text
    url = start(client)
    run_id = int(url.rsplit("/", 1)[1])
    assert db.connect().execute("SELECT space FROM runs WHERE id=?", (run_id,)).fetchone()[0] == "owner"
    assert EN["space.owner"] in client.get(url).text


def test_without_the_cookie_runs_are_public(client, token, live):
    client.cookies.clear()
    url = start(client)
    run_id = int(url.rsplit("/", 1)[1])
    assert db.connect().execute("SELECT space FROM runs WHERE id=?", (run_id,)).fetchone()[0] == "public"


def test_approving_an_email_hands_it_to_delivery_and_the_page_shows_the_outbox(client, live, monkeypatch):
    client.cookies.clear()
    url = start(client)
    run_id, aid, a_url = _approval_url(url)
    handed = []
    monkeypatch.setattr(runner, "spawn", handed.append)
    r = client.post(a_url + "/approve", headers={"HX-Request": "true"})
    assert handed == [delivery.dispatch]
    assert EN["outbox.heading"] in r.text and EN["outbox.status.queued"] in r.text
    assert 'hx-trigger="every' in r.text  # still waiting: the page keeps polling
    handed[0]()
    page = client.get(url + "?lang=ms").text
    assert MS["outbox.status.sandbox"] in page and MS["outbox.note_public"] in page
    assert 'hx-trigger="every' not in page


def _owner_run(client, token):
    client.get(f"/owner/{token}", follow_redirects=False)
    url = start(client)
    run_id, aid, a_url = _approval_url(url)
    return url, run_id, aid, a_url


def test_a_visitor_without_the_cookie_cannot_see_or_approve_an_owner_run(client, token, live, monkeypatch):
    url, run_id, aid, a_url = _owner_run(client, token)
    client.cookies.clear()
    handed, sent = [], []
    monkeypatch.setattr(runner, "spawn", handed.append)
    monkeypatch.setattr("lafaz.mail.transport.send", lambda *a, **k: sent.append(a))
    assert client.get(url).status_code == 404
    assert client.get(url + "/body").status_code == 404
    for path in ("/approve", "/edit", "/skip"):
        assert client.post(a_url + path, headers={"HX-Request": "true"}).status_code == 404
    assert client.post(f"{url}/steps/1/undo").status_code == 404
    assert client.post(f"{url}/conflicts/1/replace").status_code == 404
    c = db.connect()
    assert c.execute("SELECT COUNT(*) FROM outbox WHERE run_id=?", (run_id,)).fetchone()[0] == 0
    assert c.execute("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0] == "pending"
    assert handed == [] and sent == []
    client.get(f"/owner/{token}", follow_redirects=False)  # the owner still can
    assert client.get(url).status_code == 200


def test_public_run_pages_never_show_an_address(client, live):
    client.cookies.clear()
    url = start(client)
    run_id, aid, a_url = _approval_url(url)
    client.post(a_url + "/approve")
    conn = db.connect()
    conn.execute("UPDATE outbox SET address='inbox+faris@example.test' WHERE run_id=?", (run_id,))
    conn.commit()
    assert "inbox+faris@example.test" not in client.get(url).text


def test_delivered_badge_and_address_on_the_run_page(client, token, live):
    url, run_id, aid, a_url = _owner_run(client, token)
    client.post(a_url + "/approve")
    conn = db.connect()
    conn.execute("UPDATE outbox SET status='delivered', address='inbox+faris@example.test' WHERE run_id=?", (run_id,))
    conn.commit()
    page = client.get(url).text
    assert EN["outbox.status.delivered"] in page and "inbox+faris@example.test" in page
    assert "mail-delivered" in page
