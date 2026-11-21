"""The /eval page: the latest saved eval run (evals/results/*.json), four measures first, then every task and its trace.

The page only reads files; it never starts a run. A new run is `python -m lafaz.eval`, committed with its results.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

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


@router.get("/eval", response_class=HTMLResponse)
def eval_page(request: Request) -> HTMLResponse:
    result, name = latest()
    return render("eval.html", context(request, result=result, results_name=name))
