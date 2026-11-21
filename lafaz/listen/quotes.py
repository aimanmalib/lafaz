"""Quote checker. Code, not the model, decides whether an item is backed by what was actually said.

Rules (PRD 4.4): after normalising spaces, case and typographic marks, every quote must be a substring of the input
and at least `min_quote_words` words long. A correction is valid only when both its quotes are in the input and the
old one comes first. An item that fails any rule is rejected with a reason code.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_MARKS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
_EDGE = " \t\n.,;:!?\"'()[]"

REASONS = (
    "no_quotes",
    "quote_too_short",
    "quote_not_found",
    "correction_quote_not_found",
    "correction_order",
)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_MARKS).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _clean_quote(quote: str) -> str:
    return normalise(quote).strip(_EDGE)


def word_count(text: str) -> int:
    return len(re.findall(r"\w+(?:'\w+)?", text))


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str | None = None
    detail: str | None = None


class QuoteChecker:
    """Holds the normalised input once so many items can be checked against it."""

    def __init__(self, source: str, min_words: int):
        self.source = normalise(source)
        self.min_words = min_words

    def find(self, quote: str, start: int = 0) -> int:
        cleaned = _clean_quote(quote)
        if not cleaned:
            return -1
        return self.source.find(cleaned, start)

    def check_quote(self, quote: str) -> Verdict:
        cleaned = _clean_quote(quote)
        if word_count(cleaned) < self.min_words:
            return Verdict(False, "quote_too_short", quote)
        if self.find(quote) < 0:
            return Verdict(False, "quote_not_found", quote)
        return Verdict(True)

    def check_correction(self, old_quote: str, new_quote: str) -> Verdict:
        old_at = self.find(old_quote)
        if old_at < 0 or self.find(new_quote) < 0:
            missing = old_quote if old_at < 0 else new_quote
            return Verdict(False, "correction_quote_not_found", missing)
        if self.find(new_quote, old_at + 1) < 0:
            return Verdict(False, "correction_order", new_quote)
        return Verdict(True)

    def check_item(self, item: dict) -> Verdict:
        quotes = [q for q in item.get("quotes") or [] if isinstance(q, str)]
        if not quotes:
            return Verdict(False, "no_quotes")
        for quote in quotes:
            verdict = self.check_quote(quote)
            if not verdict.ok:
                return verdict
        corrects = item.get("corrects")
        if corrects:
            return self.check_correction(corrects.get("old_quote", ""), corrects.get("new_quote", ""))
        return Verdict(True)
