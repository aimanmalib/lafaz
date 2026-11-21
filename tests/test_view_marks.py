"""Marks land on the words as they were said, even when the quote was normalised to find them."""

from lafaz.view.marks import SourceMap, paint


def test_span_maps_back_through_typography_case_and_spaces():
    source = "Aina:  We’ll   SHIP it on Friday, okay?"
    start, end = SourceMap(source).span("we'll ship it on friday")
    assert source[start:end] == "We’ll   SHIP it on Friday"


def test_missing_quote_has_no_span():
    assert SourceMap("Aina: we ship on Friday.").span("we ship on Monday") is None


def test_overlap_keeps_first_item_colour_and_both_numbers():
    source = "Faris will fix the payment page by Wednesday."
    items = [{"kind": "action", "quotes": ["fix the payment page by Wednesday"]},
             {"kind": "fact", "quotes": ["the payment page"]}]
    segs = paint(source, items, [])
    inner = next(s for s in segs if s.text == "the payment page")
    assert inner.kind == "action" and inner.refs == [1, 2] and inner.ends == [2]
    assert "".join(s.text for s in segs) == source


def test_correction_is_struck_and_labelled_once():
    source = "The beta is on the 28th, no, the beta is on the 5th."
    items = [{"kind": "decision", "quotes": ["the beta is on the 5th"],
              "corrects": {"old_quote": "The beta is on the 28th", "new_quote": "the beta is on the 5th"}}]
    segs = paint(source, items, [])
    struck = [s for s in segs if s.corrected]
    assert [s.text for s in struck] == ["The beta is on the 28th"] and struck[0].correction_ends
    assert [s.kind for s in segs if s.kind] == ["decision"]


def test_only_model_questions_are_painted():
    source = "Mei: Do we still want the Friday demo with the ministry?"
    segs = paint(source, [], [{"origin": "model", "quote": "the Friday demo with the ministry"},
                              {"origin": "code", "quote": "Do we still want"}])
    assert [(s.text, s.kind) for s in segs if s.kind] == [("the Friday demo with the ministry", "question")]


def test_mark_element_drops_the_browser_yellow():
    """Regression: the default <mark> background showed through the translucent dark-mode marks."""
    from lafaz.config import REPO_ROOT

    css = (REPO_ROOT / "static/css/run.css").read_text(encoding="utf-8")
    rule = css.split(".mk {", 1)[1].split("}", 1)[0]
    assert "background-color: transparent" in rule
