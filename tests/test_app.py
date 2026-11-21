from lafaz import config, db


def test_healthz_reports_wal(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "db": "wal"}


def test_healthz_fails_when_db_unusable(tmp_path):
    bad = tmp_path / "not-a-db.db"
    bad.write_bytes(b"this is not sqlite" * 10)
    assert db.healthy(bad) is False


def test_home_english_by_default(client):
    r = client.get("/")
    assert r.status_code == 200
    assert '<html lang="en">' in r.text
    assert config.messages("en")["dictate.submit"] in r.text
    assert r.headers["cache-control"] == "no-cache, no-transform"
    assert r.headers["x-robots-tag"].startswith("noindex")


def test_home_malay_and_cookie_sticks(client):
    r = client.get("/?lang=ms")
    assert '<html lang="ms">' in r.text
    assert config.messages("ms")["dictate.submit"] in r.text
    assert r.cookies.get(config.settings()["app"]["lang_cookie"]) == "ms"
    again = client.get("/")
    assert '<html lang="ms">' in again.text


def test_unknown_language_falls_back(client):
    r = client.get("/?lang=xx")
    assert '<html lang="en">' in r.text


def test_rung_badge_comes_from_config(client):
    rung = config.settings()["rung"]
    key = rung["levels"][str(rung["current"])]
    assert config.messages("en")[key] in client.get("/").text


def test_assets_are_versioned_by_content(client):
    html = client.get("/").text
    assert "/static/css/lafaz.css?v=" in html
    assert client.get("/static/css/lafaz.css").status_code == 200
    assert "cdn" not in html.lower()


def test_sample_is_labelled(client):
    r = client.get("/sample")
    assert r.status_code == 200
    assert config.messages("en")["sample.label"] in r.text
    assert 'id="sheet"' in r.text


def test_run_rejects_empty_and_long_text(client):
    assert client.post("/run", data={"text": "  "}).status_code == 422
    limit = config.settings()["input"]["max_chars"]
    assert client.post("/run", data={"text": "a" * (limit + 1)}).status_code == 422


def test_unknown_page_is_translated_404(client):
    r = client.get("/nope?lang=ms")
    assert r.status_code == 404
    assert config.messages("ms")["error.not_found"] in r.text


def test_tool_categories_are_known():
    allowed = {"read", "reversible", "irreversible"}
    names = [t["name"] for t in config.tools()]
    assert len(names) == len(set(names))
    assert all(t["category"] in allowed for t in config.tools())
