"""Resolve spoken deadlines ("by Wednesday", "lusa", "the 5th of December") into dates, by code.

The meeting date is the anchor. Words come from config/listen.json. A phrase that matches no rule returns None and
the caller turns it into a question; nothing is guessed.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .. import config

_ORDINAL = r"(\d{1,2})(?:st|nd|rd|th)?"


def _words() -> dict:
    return config.listen()


def _tokens(phrase: str) -> list[str]:
    cleaned = re.sub(r"[^\w\s'-]", " ", phrase.casefold())
    return cleaned.split()


def _strip_fillers(tokens: list[str], fillers: set[str]) -> list[str]:
    return [t for t in tokens if t not in fillers]


def _next_weekday(anchor: date, weekday: int) -> date:
    """The first given weekday strictly after the anchor."""
    ahead = (weekday - anchor.weekday() - 1) % 7 + 1
    return anchor + timedelta(days=ahead)


def _weekday_next_week(anchor: date, weekday: int) -> date:
    """The given weekday in the calendar week (Monday to Sunday) after the anchor's week."""
    monday_next = anchor - timedelta(days=anchor.weekday()) + timedelta(days=7)
    return monday_next + timedelta(days=weekday)


def _number(token: str, words: dict) -> int | None:
    if token.isdigit():
        return int(token)
    return words["number_words"].get(token)


def _calendar(anchor: date, day: int, month: int, year: int | None) -> date | None:
    try:
        found = date(year or anchor.year, month, day)
    except ValueError:
        return None
    if year is None and found < anchor:
        try:
            found = date(anchor.year + 1, month, day)
        except ValueError:
            return None
    return found


def _day_of_month(anchor: date, day: int) -> date | None:
    year, month = anchor.year, anchor.month
    if day < anchor.day:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _weekday_rule(core: str, anchor: date, words: dict) -> date | None:
    days = words["weekdays"]
    prefixes = "|".join(map(re.escape, words["next_week_prefixes"]))
    suffixes = "|".join(map(re.escape, sorted(words["next_week_suffixes"], key=len, reverse=True)))
    lead = "|".join(map(re.escape, words["weekday_prefixes"]))
    names = "|".join(map(re.escape, sorted(days, key=len, reverse=True)))
    m = re.fullmatch(rf"(?:(?P<pre>{prefixes}) )?(?:(?:{lead}) )?(?P<wd>{names})(?: (?P<suf>{suffixes}))?", core)
    if not m:
        return None
    weekday = days[m.group("wd")]
    if m.group("pre") or m.group("suf"):
        return _weekday_next_week(anchor, weekday)
    return _next_weekday(anchor, weekday)


def _calendar_rule(core: str, anchor: date, words: dict) -> date | None:
    months = words["months"]
    names = "|".join(map(re.escape, sorted(months, key=len, reverse=True)))
    m = re.fullmatch(rf"{_ORDINAL} (?P<mon>{names})(?: (?P<y>\d{{4}}))?", core) or re.fullmatch(
        rf"(?P<mon>{names}) {_ORDINAL}(?: (?P<y>\d{{4}}))?", core
    )
    if m:
        year = int(m.group("y")) if m.group("y") else None
        return _calendar(anchor, int(m.group(1) if m.group(1).isdigit() else m.group(2)), months[m.group("mon")], year)
    m = re.fullmatch(r"(\d{1,2})(st|nd|rd|th)", core)
    if m:
        return _day_of_month(anchor, int(m.group(1)))
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", core)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _weekday_and_date_rule(core: str, anchor: date, words: dict) -> date | None:
    """'Friday the 27th', 'Jumaat 27 November': the date decides, the weekday must agree or nothing is returned."""
    first, _, rest = core.partition(" ")
    weekday = words["weekdays"].get(first)
    if weekday is None or not rest:
        return None
    found = _day_of_month(anchor, int(rest)) if re.fullmatch(r"\d{1,2}", rest) else _calendar_rule(rest, anchor, words)
    return found if found and found.weekday() == weekday else None


def _span_rule(tokens: list[str], anchor: date, words: dict) -> date | None:
    text = " ".join(tokens)
    prefixes = "|".join(map(re.escape, sorted(words["in_prefixes"], key=len, reverse=True)))
    units = "|".join(map(re.escape, sorted(words["unit_days"], key=len, reverse=True)))
    m = re.fullmatch(rf"(?:{prefixes}) (?P<n>\S+) (?P<u>{units})", text)
    if not m:
        return None
    n = _number(m.group("n"), words)
    if n is None:
        return None
    return anchor + timedelta(days=n * words["unit_days"][m.group("u")])


def resolve(phrase: str | None, meeting_date: date) -> date | None:
    """Return the date a spoken deadline means, or None when the words do not fix one date."""
    if not phrase or not phrase.strip():
        return None
    words = _words()
    tokens = _tokens(phrase)
    span = _span_rule(tokens, meeting_date, words)
    if span:
        return span
    core = " ".join(_strip_fillers(tokens, set(words["filler_words"])))
    if core in words["relative_days"]:
        return meeting_date + timedelta(days=words["relative_days"][core])
    return (_weekday_rule(core, meeting_date, words) or _calendar_rule(core, meeting_date, words)
            or _weekday_and_date_rule(core, meeting_date, words))
