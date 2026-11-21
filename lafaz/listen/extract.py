"""Listen: one model call with `record_items`, then code checks quotes, corrections, owners and dates.

The model proposes; code decides. Items whose quotes are not in the input are rejected with a reason and kept for
the trace and the measured counts. Owners and dates the code cannot pin down become questions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .. import config
from ..llm import LLM, ToolCall
from . import dates, speakers
from .quotes import QuoteChecker

TOOL = "record_items"


@dataclass
class ListenResult:
    items: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)
    call: ToolCall | None = None


def user_message(text: str, meeting_date: date, people: list[dict]) -> str:
    names = ", ".join(p["name"] for p in people) or "none known"
    return (
        f"Meeting date: {meeting_date.isoformat()}\n"
        f"Known people: {names}\n\n"
        f"<input>\n{text}\n</input>"
    )


def _people_with_speakers(people: list[dict], turns: list[speakers.Turn]) -> list[dict]:
    known = {p["name"] for p in people}
    return list(people) + [{"name": s} for s in speakers.speakers(turns) if s not in known]


def _code_question(code: str, item_index: int, quote: str, **params: str) -> dict:
    return {"origin": "code", "code": code, "params": params, "item_index": item_index, "quote": quote}


def _settle_owner(item: dict, index: int, turns, people, words) -> dict | None:
    """Fill item['owner'] with a canonical name; return a question when that is not possible."""
    raw = item.get("owner")
    first = item["quotes"][0]
    item["speaker"] = speakers.speaker_of(first, turns)
    if raw:
        item["owner"] = speakers.match_person(raw, people)
        if item["owner"] is None and item["kind"] == "action":
            return _code_question("owner_unmatched", index, first, name=raw)
        return None
    if item["kind"] != "action":
        return None
    if item["speaker"] and speakers.is_first_person(first, words["first_person"]):
        item["owner"] = item["speaker"]
        return None
    return _code_question("owner_missing", index, first, item=item["text"])


def _settle_due(item: dict, index: int, meeting_date: date) -> dict | None:
    phrase = item.get("due_phrase")
    resolved = dates.resolve(phrase, meeting_date) if phrase else None
    item["due_date"] = resolved.isoformat() if resolved else None
    if phrase and resolved is None:
        return _code_question("due_unclear", index, item["quotes"][0], phrase=phrase)
    return None


def check(raw: dict, text: str, meeting_date: date, people: list[dict]) -> ListenResult:
    """Apply every code check to the model's `record_items` input."""
    words = config.listen()
    checker = QuoteChecker(text, words["min_quote_words"])
    turns = speakers.parse_turns(text)
    people = _people_with_speakers(people, turns)
    result = ListenResult()
    kept: dict[int, int] = {}
    for source_index, proposed in enumerate(raw.get("items") or []):
        proposed = checker.drop_short(proposed)
        verdict = checker.check_item(proposed)
        if not verdict.ok:
            result.rejected.append({"item": proposed, "reason": verdict.reason, "detail": verdict.detail})
            continue
        item = dict(proposed)
        index = len(result.items)
        kept[source_index] = index
        result.items.append(item)
        for question in (_settle_owner(item, index, turns, people, words), _settle_due(item, index, meeting_date)):
            if question:
                result.questions.append(question)
    for proposed in raw.get("questions") or []:
        verdict = checker.check_quote(proposed.get("quote") or "")
        if not verdict.ok:
            result.rejected.append({"question": proposed, "reason": verdict.reason, "detail": verdict.detail})
            continue
        result.questions.append(
            {
                "origin": "model",
                "text": proposed["question"],
                "item_index": kept.get(proposed.get("item_index")),
                "quote": proposed["quote"],
            }
        )
    return result


def listen(text: str, meeting_date: date, people: list[dict] | None = None, llm: LLM | None = None) -> ListenResult:
    llm = llm or LLM()
    people = people or []
    turns = speakers.parse_turns(text)
    message = user_message(text, meeting_date, _people_with_speakers(people, turns))
    call = llm.call_tool(config.prompt("listen"), message, TOOL)
    result = check(call.input, text, meeting_date, people)
    result.call = call
    return result
