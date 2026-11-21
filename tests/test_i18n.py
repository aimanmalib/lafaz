import json
import re

from lafaz import config

I18N = config.config_dir() / "i18n"


def _load(lang):
    return json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))


def test_every_language_has_the_same_keys():
    langs = config.settings()["app"]["languages"]
    keys = {lang: set(_load(lang)) for lang in langs}
    base = keys[langs[0]]
    for lang, ks in keys.items():
        assert ks == base, f"{lang}: missing {base - ks}, extra {ks - base}"


def test_placeholders_match_across_languages():
    langs = config.settings()["app"]["languages"]
    base = _load(langs[0])
    for lang in langs[1:]:
        other = _load(lang)
        for key, text in base.items():
            assert set(re.findall(r"\{\w+\}", text)) == set(re.findall(r"\{\w+\}", other[key])), key


def test_no_empty_strings():
    for lang in config.settings()["app"]["languages"]:
        assert all(v.strip() for v in _load(lang).values()), lang


def test_templates_only_use_known_keys():
    keys = set(_load("en"))
    used = set()
    for tpl in (config.REPO_ROOT / "templates").rglob("*.html"):
        used |= set(re.findall(r"t\('([a-z0-9_.]*[a-z0-9_])'\s*[,)]", tpl.read_text(encoding="utf-8")))
    rung_keys = set(config.settings()["rung"]["levels"].values())
    assert used, "no translated strings found in templates"
    assert (used | rung_keys) - keys == set()
