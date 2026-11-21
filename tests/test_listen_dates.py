from datetime import date

import pytest

from lafaz.listen.dates import resolve

SATURDAY = date(2026, 11, 21)
MONDAY = date(2026, 11, 23)


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("tomorrow", date(2026, 11, 22)),
        ("esok", date(2026, 11, 22)),
        ("lusa", date(2026, 11, 23)),
        ("day after tomorrow", date(2026, 11, 23)),
        ("by Wednesday", date(2026, 11, 25)),
        ("hari Rabu", date(2026, 11, 25)),
        ("the 5th of December", date(2026, 12, 5)),
        ("5 Disember", date(2026, 12, 5)),
        ("Dec 5th", date(2026, 12, 5)),
        ("on the 28th", date(2026, 11, 28)),
        ("in two weeks", date(2026, 12, 5)),
        ("dalam 3 hari", date(2026, 11, 24)),
        ("2026-12-01", date(2026, 12, 1)),
    ],
)
def test_phrases_resolve_from_the_meeting_date(phrase, expected):
    assert resolve(phrase, SATURDAY) == expected


def test_plain_weekday_is_the_next_one_after_the_meeting():
    assert resolve("Friday", MONDAY) == date(2026, 11, 27)
    assert resolve("Monday", MONDAY) == date(2026, 11, 30)


def test_next_weekday_means_the_following_calendar_week():
    assert resolve("next Friday", MONDAY) == date(2026, 12, 4)
    assert resolve("Jumaat depan", MONDAY) == date(2026, 12, 4)


def test_date_already_past_this_year_rolls_to_next_year():
    assert resolve("3 January", SATURDAY) == date(2027, 1, 3)


def test_day_number_already_past_this_month_means_next_month():
    assert resolve("the 2nd", SATURDAY) == date(2026, 12, 2)


@pytest.mark.parametrize("phrase", ["soon", "next week", "minggu depan", "ASAP", "31st", "", None, "end of the quarter"])
def test_vague_or_impossible_phrases_are_not_guessed(phrase):
    assert resolve(phrase, SATURDAY) is None
