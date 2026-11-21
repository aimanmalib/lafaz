from lafaz.listen.quotes import QuoteChecker, normalise

TEXT = "Aina: We agreed the beta goes out on the 28th, but actually, no, let's move the beta to the 5th of December."


def checker(min_words=3):
    return QuoteChecker(TEXT, min_words)


def test_normalise_spaces_case_and_marks():
    assert normalise("  Let’s   MOVE\nthe ") == "let's move the"


def test_exact_quote_is_accepted():
    assert checker().check_quote("let's move the beta to the 5th of December").ok


def test_quote_matches_despite_case_spacing_and_edge_punctuation():
    assert checker().check_quote('"LET’S  move the beta."').ok


def test_quote_not_in_input_is_rejected():
    verdict = checker().check_quote("move the launch to January")
    assert (verdict.ok, verdict.reason) == (False, "quote_not_found")


def test_paraphrase_is_rejected():
    assert checker().check_quote("the beta moves to December 5").reason == "quote_not_found"


def test_short_quote_is_rejected_even_if_present():
    assert checker().check_quote("the beta").reason == "quote_too_short"


def test_minimum_words_comes_from_the_caller():
    assert checker(min_words=2).check_quote("the beta").ok


def test_item_without_quotes_is_rejected():
    assert checker().check_item({"quotes": []}).reason == "no_quotes"


def test_item_with_one_bad_quote_is_rejected():
    item = {"quotes": ["let's move the beta", "and the gamma goes out"]}
    assert checker().check_item(item).reason == "quote_not_found"


def test_correction_old_then_new_is_accepted():
    item = {
        "quotes": ["move the beta to the 5th of December"],
        "corrects": {"old_quote": "goes out on the 28th", "new_quote": "move the beta to the 5th"},
    }
    assert checker().check_item(item).ok


def test_correction_in_wrong_order_is_rejected():
    item = {
        "quotes": ["move the beta to the 5th of December"],
        "corrects": {"old_quote": "move the beta to the 5th", "new_quote": "goes out on the 28th"},
    }
    assert checker().check_item(item).reason == "correction_order"


def test_correction_with_invented_old_words_is_rejected():
    item = {
        "quotes": ["move the beta to the 5th of December"],
        "corrects": {"old_quote": "beta goes out in January", "new_quote": "move the beta to the 5th"},
    }
    assert checker().check_item(item).reason == "correction_quote_not_found"
