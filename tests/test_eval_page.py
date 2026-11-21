"""The /eval page reads a saved results file and shows every word in the chosen language: task labels, stop reasons,
tool categories and step statuses, plus a path ratio rounded for reading."""

import json

import pytest

from lafaz import config, routes_eval
from lafaz.eval import tasks
from lafaz.i18n import Translator


def _row(tid, label, reason="missing_facts"):
    return {"id": tid, "category": "extraction", "source": "synthetic", "label": label, "success": True,
            "checks": {"items": True}, "reason": reason, "error": None, "items": [], "steps_used": 3,
            "min_steps": 2, "path_ratio": 1.5, "ms": 10, "cost_usd": 0.01,
            "trace": [{"seq": 1, "tool": "model", "category": "model", "status": "tool_use", "ms": 5},
                      {"seq": 2, "tool": "read_memory", "category": "read", "status": "executed", "ms": 1},
                      {"seq": 3, "tool": "send_summary", "category": "irreversible", "status": "pending_approval",
                       "ms": 2}]}


SUMMARY = {"tasks": 2, "task_success": {"passed": 2}, "path_quality": {"mean_ratio": 2.041666, "repeated_calls": 0},
           "constraint_violations": 0, "approvals_pending": 2, "give_up_quality": {"tasks": 0, "mean": None},
           "quotes_rejected": {"count": 0}, "corrections": {"resolved": 0, "expected": 0},
           "latency_ms": {"p50": 1, "p95": 2}, "cost_usd": {"mean": 0.01, "total": 0.02}}


@pytest.fixture()
def results(tmp_path, monkeypatch):
    first = tasks.load()[0]
    data = {"started": "2026-11-21T00:00:00Z", "model": "m", "commit": "abc", "summary": SUMMARY,
            "tasks": [_row("t99-new", {"en": "English label here", "ms": "Label Melayu di sini"}),
                      _row(first["id"], first["label"]["en"], reason="finished")]}
    (tmp_path / "20990101T000000Z.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(tasks, "results_dir", lambda: tmp_path)
    return first


def test_malay_page_has_no_english_task_label_or_raw_codes(client, results):
    html = client.get("/eval?lang=ms").text
    assert "Label Melayu di sini" in html and "English label here" not in html
    assert results["label"]["ms"] in html and results["label"]["en"] not in html
    for raw in (">pending_approval<", ">irreversible<", ">tool_use<", ">executed<", "missing_facts", ": finished"):
        assert raw not in html
    ms = Translator("ms")
    for key in ("eval.status.pending_approval", "eval.tool_cat.irreversible", "eval.reason.missing_facts"):
        assert ms(key) in html


def test_english_page_uses_english_labels(client, results):
    html = client.get("/eval?lang=en").text
    assert "English label here" in html and results["label"]["en"] in html
    assert "Label Melayu di sini" not in html


def test_path_ratio_is_shown_with_two_decimals(client, results):
    html = client.get("/eval?lang=en").text
    assert "2.04x" in html and "2.0416" not in html


def test_every_code_in_the_saved_run_has_text_in_every_language():
    result, _ = routes_eval.latest()
    if result is None:
        pytest.skip("no saved eval run")
    codes = {("eval.reason.", r["reason"].split(":")[0]) for r in result["tasks"]}
    for r in result["tasks"]:
        codes |= {("eval.tool_cat.", s["category"]) for s in r["trace"]}
        codes |= {("eval.status.", s["status"]) for s in r["trace"]}
    for lang in config.settings()["app"]["languages"]:
        t = Translator(lang)
        missing = sorted(p + c for p, c in codes if p + c not in config.messages(lang))
        assert not missing, (lang, missing)
        assert t.term("eval.status.", "no_such_code") == "no_such_code"


@pytest.mark.parametrize("label", ["Only English", {"en": "Only English"}, {"en": "x", "ms": " "}])
def test_task_label_must_exist_in_every_language(label):
    task = json.loads(json.dumps(tasks.load()[0]))
    task["label"] = label
    with pytest.raises(tasks.TaskError, match="label"):
        tasks.validate(task)
