"""The board page, its exports and the calendar feed. Every route answers for the visitor's own space only."""

from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException

from . import config, db, owner
from .board import ics, summary, tasks
from .memory import scheduler
from .web import context, render

router = APIRouter()


@router.get("/board", response_class=HTMLResponse)
def page(request: Request) -> HTMLResponse:
    space = owner.space(request)
    conn = db.connect()
    try:
        ctx = context(request, space=space, columns=tasks.grouped(conn, space), waiting=tasks.waiting(conn, space),
                      people=summary.weekly(conn, space, scheduler.today()), ics_token=ics.token_for(space),
                      window_days=config.board()["summary"]["window_days"])
    finally:
        conn.close()
    return render("board.html", ctx)


@router.post("/board/task/{task_id}/{status}")
def move(request: Request, task_id: int, status: str) -> Response:
    conn = db.connect()
    try:
        moved = tasks.move(conn, owner.space(request), task_id, status)
    finally:
        conn.close()
    if not moved:
        raise HTTPException(404)
    return RedirectResponse(f"/board#task-{task_id}", status_code=303)


def _rows(request: Request) -> list[dict]:
    conn = db.connect()
    try:
        return tasks.export_rows(conn, owner.space(request))
    finally:
        conn.close()


def _download(body: str, media: str, ext: str) -> Response:
    name = config.board()["export"]["filename"]
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{ext}"'})


@router.get("/board.csv")
def export_csv(request: Request) -> Response:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=config.board()["export"]["fields"])
    writer.writeheader()
    writer.writerows(_rows(request))
    return _download(out.getvalue(), "text/csv; charset=utf-8", "csv")


@router.get("/board.json")
def export_json(request: Request) -> Response:
    return _download(json.dumps({"tasks": _rows(request)}, ensure_ascii=False, indent=2),
                     "application/json", "json")


@router.get("/ics/{token}.ics")
def calendar(token: str) -> Response:
    space = ics.space_for(token)
    if space is None:
        raise HTTPException(404)
    conn = db.connect()
    try:
        body = ics.feed(conn, space)
    finally:
        conn.close()
    return Response(body, media_type="text/calendar; charset=utf-8")
