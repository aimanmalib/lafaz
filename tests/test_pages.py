"""Memory, voice and about pages (PRD 4.8, 5.1): each answers in both languages, /memory shows only the visitor's own
space with replaced decisions and judged pairs, /voice shows note titles, times and word counts but never a body, and
/about lists every enabled tool under the category config/tools.json gives it."""

import re
from datetime import date

import pytest

from lafaz import config, db, routes_eval
from lafaz.i18n import Translator
from lafaz.memory import decisions, people
from memory_helpers import decision, meeting

TOKEN_ENV = config.mail()["env"]["owner_token"]
COOKIE = config.mail()["owner_cookie"]
OLD_TEXT = "Hana: The open day is on the 3rd of March at the hall.\nIrfan: Fine."
NEW_TEXT = "Hana: Change that, the open day is on the 10th of March at the hall.\nIrfan: Noted."
OLD = decision("Open day on 3 March", "The open day is on the 3rd of March")
NEW = decision("Open day on 10 March", "the open day is on the 10th of March")


@pytest.fixture()
def owner_token(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "owner-token-for-page-tests")
    return "owner-token-for-page-tests"


def _remembered(space):
    """Two meetings in `space`: the later decision replaced the earlier one after a judged clash."""
    conn = db.connect()
    try:
        runs = []
        for text, day, item in ((OLD_TEXT, date(2026, 11, 14), OLD), (NEW_TEXT, date(2026, 11, 21), NEW)):
            run_id = meeting(conn, text, day, [{**item, "owner": "Hana"}])
            conn.execute("UPDATE runs SET space=? WHERE id=?", (space, run_id))
            decisions.save_run(conn, run_id)
            people.remember_run(conn, run_id)
            runs.append(run_id)
        old_id, new_id = (conn.execute("SELECT id FROM decisions WHERE run_id=?", (r,)).fetchone()[0] for r in runs)
        conn.execute("UPDATE decisions SET status='superseded', superseded_by=? WHERE id=?", (new_id, old_id))
        conn.execute(
            "INSERT INTO conflicts (run_id, new_decision_id, old_decision_id, shared_terms, verdict, old_quote,"
            " new_quote, status) VALUES (?,?,?,?,?,?,?,?)",
            (runs[1], new_id, old_id, "open day", "conflict", OLD["quotes"][0], NEW["quotes"][0], "replaced"),
        )
        conn.execute("UPDATE people SET email='hana@example.test' WHERE name='Hana'")
        conn.commit()
    finally:
        conn.close()
    return runs


@pytest.mark.parametrize("path", ["/memory", "/voice", "/about"])
@pytest.mark.parametrize("lang", ["en", "ms"])
def test_pages_answer_in_both_languages_without_raw_keys(client, path, lang):
    res = client.get(f"{path}?lang={lang}")
    assert res.status_code == 200
    assert f'<html lang="{lang}">' in res.text
    t = Translator(lang)
    assert t(path.strip("/") + ".heading") in res.text
    assert not re.search(r">\s*(memory|voice|about|footer)\.[a-z_.]+\s*<", res.text)


def test_footer_links_every_page(client):
    html = client.get("/about").text
    for page in ("board", "memory", "eval", "voice", "about"):
        assert f'href="/{page}"' in html


def test_memory_shows_replaced_decision_and_judged_pair_with_quotes(client):
    _remembered("public")
    html = client.get("/memory?lang=en").text
    t = Translator("en")
    assert t("memory.replaced_by", statement=NEW["text"]) in html
    assert t("memory.status.superseded") in html and t("memory.verdict.conflict") in html
    assert OLD["quotes"][0] in html and NEW["quotes"][0] in html
    assert "Hana" in html and "hana@example.test" not in html
    assert "{n}" not in html and t("memory.space_public") in html


def test_memory_keeps_spaces_apart_and_shows_addresses_only_to_the_owner(client, owner_token):
    _remembered("owner")
    public = client.get("/memory").text
    assert "hana@example.test" not in public
    client.cookies.set(COOKIE, owner_token)
    mine = client.get("/memory").text
    assert "hana@example.test" in mine
    owner_ids = set(re.findall(r'id="decision-(\d+)"', mine))
    client.cookies.clear()
    assert owner_ids.isdisjoint(re.findall(r'id="decision-(\d+)"', client.get("/memory").text))


def test_voice_lists_title_time_and_words_never_the_body(client, monkeypatch):
    cfg = {"title_prefix": "nextgen", "notes": [
        {"keyword": "baiki", "at": "2026-11-21T16:05:00Z", "words": 42, "body": "secret words here"},
        {"keyword": "suara", "at": "2026-11-21T08:30:00Z", "words": 120},
    ]}
    monkeypatch.setattr(config, "voice", lambda: cfg)
    html = client.get("/voice?lang=en").text
    assert "secret words here" not in html
    first, second = html.index("nextgen suara"), html.index("nextgen baiki")
    assert first < second
    assert "2026-11-22 00:05" in html
    assert Translator("en")("voice.totals", n=2, words=162) in html


def test_voice_without_notes_says_so(client, monkeypatch):
    monkeypatch.setattr(config, "voice", lambda: {"title_prefix": "nextgen", "notes": []})
    assert Translator("ms")("voice.empty") in client.get("/voice?lang=ms").text


def test_about_lists_each_enabled_tool_under_its_config_category(client):
    groups = routes_eval.tools_by_category()
    enabled = [t for t in config.tools() if t.get("enabled", True)]
    assert sum(len(v) for v in groups.values()) == len(enabled)
    for tool in enabled:
        assert tool["name"] in groups[tool["kategori"]]
    html = client.get("/about?lang=ms").text
    t = Translator("ms")
    for tool in enabled:
        assert t.has("tool." + tool["name"])
        assert t("tool." + tool["name"]) in html


def test_architecture_diagram_is_served_as_svg(client):
    res = client.get("/about/architecture.svg")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/svg+xml")
    assert "<title" in res.text
