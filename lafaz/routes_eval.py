"""The /eval page: the latest saved eval run (evals/results/*.json), four measures first, then every task and its trace.

The page only reads files; it never starts a run. A new run is `python -m lafaz.eval`, committed with its results.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from . import i18n
from .eval import tasks
from .web import context, render

router = APIRouter()


def latest(folder: Path | None = None) -> tuple[dict | None, str | None]:
    """The newest results file by name (names are UTC timestamps), or (None, None)."""
    folder = folder or tasks.results_dir()
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    for path in reversed(files):
        try:
            return json.loads(path.read_text(encoding="utf-8")), path.name
        except (OSError, ValueError):
            continue
    return None, None


def labels(result: dict | None, lang: str) -> dict[str, str]:
    """Task id -> label in `lang`. Rows saved before labels were bilingual hold one string; for those the label
    comes from the task file with the same id, and the stored string is the last resort."""
    rows = (result or {}).get("tasks", [])
    files = {}
    if any(not isinstance(r.get("label"), dict) for r in rows):
        try:
            files = {t["id"]: t["label"] for t in tasks.load()}
        except (OSError, ValueError):
            files = {}
    found = {}
    for r in rows:
        label = r.get("label") if isinstance(r.get("label"), dict) else files.get(r["id"], r.get("label"))
        if isinstance(label, dict):
            label = label.get(lang) or label.get(i18n.default_lang()) or r["id"]
        found[r["id"]] = label or r["id"]
    return found


@router.get("/eval", response_class=HTMLResponse)
def eval_page(request: Request) -> HTMLResponse:
    result, name = latest()
    ctx = context(request, result=result, results_name=name)
    ctx["labels"] = labels(result, ctx["lang"])
    return render("eval.html", ctx)
