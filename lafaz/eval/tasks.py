"""Eval task files (evals/tasks/*.json). Each file is checked before any model call so a typo never costs money."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .. import config, i18n
from ..config import REPO_ROOT
from ..agent import gate

CATEGORIES = ("extraction", "conflict", "give_up", "adversarial")
SOURCES = ("synthetic", "wispr-sebenar")
ITEM_KINDS = ("decision", "action", "question", "fact")
EXPECT_KEYS = {"items", "corrections", "conflicts", "questions_min", "tools_required", "give_up", "stop_reasons",
               "min_steps"}


class TaskError(ValueError):
    pass


def _path(key: str) -> Path:
    raw = Path(config.settings()["eval"][key])
    return raw if raw.is_absolute() else REPO_ROOT / raw


def tasks_dir() -> Path:
    return _path("tasks_dir")


def results_dir() -> Path:
    return _path("results_dir")


def _check_item(where: str, item: dict) -> None:
    if not isinstance(item.get("match"), list) or not item["match"]:
        raise TaskError(f"{where}: 'match' must be a non-empty list")
    for kind in item.get("kind", []):
        if kind not in ITEM_KINDS:
            raise TaskError(f"{where}: unknown kind {kind!r}")
    if item.get("due_date"):
        date.fromisoformat(item["due_date"])


def validate(task: dict) -> dict:
    tid = task.get("id") or "?"
    for key in ("id", "category", "source", "label", "meeting_date", "text", "memory", "expect"):
        if key not in task:
            raise TaskError(f"{tid}: missing {key!r}")
    label = task["label"]
    if not isinstance(label, dict) or set(label) != set(i18n.languages()) or not all(
            isinstance(v, str) and v.strip() for v in label.values()):
        raise TaskError(f"{tid}: 'label' needs non-empty text for each of {sorted(i18n.languages())}")
    if task["category"] not in CATEGORIES:
        raise TaskError(f"{tid}: unknown category {task['category']!r}")
    if task["source"] not in SOURCES:
        raise TaskError(f"{tid}: unknown source {task['source']!r}")
    date.fromisoformat(task["meeting_date"])
    expect = task["expect"]
    extra = set(expect) - EXPECT_KEYS
    if extra:
        raise TaskError(f"{tid}: unknown expect keys {sorted(extra)}")
    if not isinstance(expect.get("min_steps"), int) or expect["min_steps"] < 1:
        raise TaskError(f"{tid}: 'min_steps' must be a positive integer")
    for n, item in enumerate(expect.get("items", [])):
        _check_item(f"{tid} item {n}", item)
    for n, corr in enumerate(expect.get("corrections", [])):
        if not corr.get("match") or not ({"owner", "due_date", "includes_any"} & set(corr)):
            raise TaskError(f"{tid} correction {n}: needs 'match' and one of owner, due_date, includes_any")
    plan = {t["name"] for t in gate.plan_tools()}
    for name in expect.get("tools_required", []):
        if name not in plan:
            raise TaskError(f"{tid}: {name!r} is not a plan tool")
    for meeting in task["memory"].get("meetings", []):
        date.fromisoformat(meeting["meeting_date"])
        for d in meeting.get("decisions", []):
            if d["quote"] not in meeting["text"]:
                raise TaskError(f"{tid}: memory quote not in its meeting text: {d['quote']!r}")
    return task


def load(folder: Path | None = None, only: list[str] | None = None) -> list[dict]:
    folder = folder or tasks_dir()
    found = []
    seen = set()
    for path in sorted(folder.glob("*.json")):
        task = validate(json.loads(path.read_text(encoding="utf-8")))
        if task["id"] in seen:
            raise TaskError(f"duplicate task id {task['id']!r}")
        if task["id"] != path.stem:
            raise TaskError(f"{path.name}: file name must equal id {task['id']!r}")
        seen.add(task["id"])
        if not only or task["id"] in only:
            found.append(task)
    return found
