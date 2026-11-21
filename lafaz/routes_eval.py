"""Pages that only read committed files: /eval, /voice and /about.

/eval shows the latest saved eval run (evals/results/*.json), four measures first, then every task and its trace. It
never starts a run; a new run is `python -m lafaz.eval`, committed with its results. /voice lists the notes dictated
to the builder (config/voice.json). /about explains the problem, the layers and who may do what (config/tools.json).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from . import config, i18n
from .config import REPO_ROOT
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


def voice_notes() -> list[dict]:
    """Dictated notes, oldest first, with the arrival time shown in the app's time zone."""
    cfg = config.voice()
    zone = ZoneInfo(config.settings()["app"]["timezone"])
    rows = []
    for note in sorted(cfg["notes"], key=lambda n: n["at"]):
        at = datetime.fromisoformat(note["at"].replace("Z", "+00:00")).astimezone(zone)
        rows.append({"title": f"{cfg['title_prefix']} {note['keyword']}", "at": at.strftime("%Y-%m-%d %H:%M"),
                     "words": int(note["words"])})
    return rows


@router.get("/voice", response_class=HTMLResponse)
def voice_page(request: Request) -> HTMLResponse:
    notes = voice_notes()
    return render("voice.html", context(request, notes=notes, total_words=sum(n["words"] for n in notes)))


def tools_by_category() -> dict[str, list[str]]:
    """Enabled tools grouped by permission category, in the order config/tools.json lists them."""
    groups: dict[str, list[str]] = {"read": [], "reversible": [], "irreversible": []}
    for tool in config.tools():
        if tool.get("enabled", True):
            groups.setdefault(tool["kategori"], []).append(tool["name"])
    return groups


@router.get("/about", response_class=HTMLResponse)
def about_page(request: Request) -> HTMLResponse:
    return render("about.html", context(request, categories=tools_by_category()))


@router.get("/about/architecture.svg")
def architecture_svg() -> FileResponse:
    return FileResponse(REPO_ROOT / "docs" / "architecture.svg", media_type="image/svg+xml")
