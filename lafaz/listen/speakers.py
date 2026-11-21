"""Speaker attribution and owner matching, by code.

A transcript line `Name: text` starts a turn for that speaker. Text without labels is one turn with no speaker
(a single person dictating). Owners named by the model are matched against known people; no match or more than
one match means a question, not a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .quotes import normalise

_LABEL = re.compile(r"^\s*([A-Z][\w'.-]*(?: [A-Z][\w'.-]*){0,2})\s*:\s*(.*)$")


@dataclass(frozen=True)
class Turn:
    speaker: str | None
    text: str


def parse_turns(text: str) -> list[Turn]:
    turns: list[Turn] = []
    for line in text.splitlines():
        m = _LABEL.match(line)
        if m and len(m.group(1)) <= 40:
            turns.append(Turn(m.group(1), m.group(2)))
        elif turns:
            turns[-1] = Turn(turns[-1].speaker, f"{turns[-1].text}\n{line}")
        elif line.strip():
            turns.append(Turn(None, line))
    return turns


def speakers(turns: list[Turn]) -> list[str]:
    seen: list[str] = []
    for turn in turns:
        if turn.speaker and turn.speaker not in seen:
            seen.append(turn.speaker)
    return seen


def speaker_of(quote: str, turns: list[Turn]) -> str | None:
    """The speaker of the first turn that contains the whole quote."""
    needle = normalise(quote).strip(" .,;:!?\"'")
    for turn in turns:
        if needle and needle in normalise(turn.text):
            return turn.speaker
    return None


def is_first_person(quote: str, markers: list[str]) -> bool:
    words = set(re.findall(r"\w+(?:'\w+)?", normalise(quote)))
    return any(m in words for m in markers if " " not in m)


def match_person(name: str | None, people: list[dict]) -> str | None:
    """Return the canonical name of the one person whose name, first name or alias equals `name`."""
    if not name:
        return None
    wanted = normalise(name)
    hits = []
    for person in people:
        keys = {normalise(person["name"]), normalise(person["name"]).split(" ")[0]}
        keys.update(normalise(a) for a in person.get("aliases", []))
        if wanted in keys:
            hits.append(person["name"])
    return hits[0] if len(set(hits)) == 1 else None
