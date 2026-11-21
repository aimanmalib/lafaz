"""Paint quotes onto the transcript.

The quote checker compares normalised text (lafaz.listen.quotes.normalise). To show a mark on the words the person
actually said, the normalised text is rebuilt here one source character at a time, keeping a map from each
normalised character back to its source index. A quote found in the normalised text then maps to a span of the
original text, so the page never shows words that differ from what was said.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from ..listen.quotes import _EDGE, _MARKS, normalise


def _fold(char: str) -> str:
    return unicodedata.normalize("NFKC", char).translate(_MARKS).casefold()


class SourceMap:
    def __init__(self, source: str):
        self.source = source
        chars: list[str] = []
        index: list[int] = []
        for i, char in enumerate(source):
            if char.isspace():
                if chars and chars[-1] != " ":
                    chars.append(" ")
                    index.append(i)
                continue
            for folded in _fold(char):
                chars.append(folded)
                index.append(i)
        self.text = "".join(chars)
        self.index = index

    def span(self, quote: str, start: int = 0) -> tuple[int, int] | None:
        """(start, end) in the source for the first match of `quote` at or after normalised position `start`."""
        cleaned = normalise(quote).strip(_EDGE)
        if not cleaned:
            return None
        at = self.text.find(cleaned, start)
        if at < 0:
            return None
        return self.index[at], self.index[at + len(cleaned) - 1] + 1


@dataclass
class Mark:
    start: int
    end: int
    kind: str  # decision | action | question | fact | corrected
    ref: int | None = None  # item number shown to the reader (1-based); None for a standalone question


@dataclass
class Segment:
    text: str
    kind: str | None = None
    refs: list[int] = field(default_factory=list)
    corrected: bool = False
    ends: list[int] = field(default_factory=list)  # item numbers whose quote ends at this segment
    correction_ends: bool = False  # the "you corrected this" label goes after this segment
    order: int = 0  # position of the mark among all marks, for the staggered sweep


def find_marks(source: str, items: list[dict], questions: list[dict]) -> list[Mark]:
    smap = SourceMap(source)
    marks: list[Mark] = []
    for number, item in enumerate(items, start=1):
        for quote in item.get("quotes") or []:
            span = smap.span(quote)
            if span:
                marks.append(Mark(*span, kind=item.get("kind") or "fact", ref=number))
        corrects = item.get("corrects") or {}
        span = smap.span(corrects.get("old_quote") or "") if corrects else None
        if span:
            marks.append(Mark(*span, kind="corrected", ref=number))
    for question in questions:
        if question.get("origin") == "model" and question.get("quote"):
            span = smap.span(question["quote"])
            if span:
                marks.append(Mark(*span, kind="question"))
    return marks


def segments(source: str, marks: list[Mark]) -> list[Segment]:
    """Split the source where the set of marks changes. The first mark (item order) gives the colour."""
    cuts = sorted({0, len(source), *(m.start for m in marks), *(m.end for m in marks)})
    out: list[Segment] = []
    order = 0
    for a, b in zip(cuts, cuts[1:]):
        covering = [m for m in marks if m.start <= a and b <= m.end]
        coloured = [m for m in covering if m.kind != "corrected"]
        seg = Segment(text=source[a:b])
        if coloured:
            seg.kind = coloured[0].kind
            seg.refs = sorted({m.ref for m in coloured if m.ref})
            seg.order = order
            order += 1
        seg.corrected = any(m.kind == "corrected" for m in covering)
        seg.ends = sorted({m.ref for m in covering if m.end == b and m.ref and m.kind != "corrected"})
        seg.correction_ends = any(m.kind == "corrected" and m.end == b for m in covering)
        out.append(seg)
    return out


def paint(source: str, items: list[dict], questions: list[dict]) -> list[Segment]:
    return segments(source, find_marks(source, items, questions))
