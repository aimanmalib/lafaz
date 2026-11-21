"""Run pages and the buttons a person presses on them.

Every button posts a form. With HTMX the run body is swapped in place; without JavaScript the browser is sent
back to /run/<id> (303). Nothing here decides whether an action may run: lafaz.agent.gate does.
"""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException

from . import config, db, runner
from .agent import gate, loop
from .agent.context import ActionError
from .memory import conflicts
from .view import run_view
from .web import context, render, today

router = APIRouter()
SOURCES = ("wispr", "transcript", "sample")


def _home_error(request: Request, text: str, meeting_date: str, key: str, status: int, **params) -> HTMLResponse:
    ctx = context(request)
    ctx.update(text=text, meeting_date=meeting_date or today(), sample=None, notice=ctx["t"](key, **params))
    return render("index.html", ctx, status_code=status)


@router.post("/run", response_class=HTMLResponse)
def start(request: Request, text: str = Form(""), meeting_date: str = Form(""), source: str = Form("wispr")):
    limit = config.settings()["input"]["max_chars"]
    if not text.strip():
        return _home_error(request, text, meeting_date, "run.empty", 422)
    if len(text) > limit:
        return _home_error(request, text, meeting_date, "run.too_long", 422, max=limit)
    try:
        day = date.fromisoformat(meeting_date) if meeting_date else date.fromisoformat(today())
    except ValueError:
        return _home_error(request, text, meeting_date, "run.bad_date", 422)
    if not runner.live_available():
        return _home_error(request, text, meeting_date, "run.not_live", 503)
    lang = context(request)["lang"]
    conn = db.connect()
    try:
        run_id = loop.start_run(conn, text, day, source if source in SOURCES else "wispr", lang)
    finally:
        conn.close()
    runner.launch(run_id, text, day)
    return RedirectResponse(f"/run/{run_id}", status_code=303)


def _view(request: Request, run_id: int, notice: str | None = None, partial: bool = False,
          status_code: int = 200) -> HTMLResponse:
    conn = db.connect()
    try:
        data = run_view.load(conn, run_id)
    finally:
        conn.close()
    if data is None:
        raise HTTPException(404)
    ctx = context(request, notice=notice, poll=config.settings()["run_page"]["poll_seconds"], **data)
    return render("partials/run_body.html" if partial else "run.html", ctx, status_code=status_code)


@router.get("/run/{run_id}", response_class=HTMLResponse)
def page(request: Request, run_id: int) -> HTMLResponse:
    return _view(request, run_id)


@router.get("/run/{run_id}/body", response_class=HTMLResponse)
def body(request: Request, run_id: int) -> HTMLResponse:
    return _view(request, run_id, partial=True)


def _after(request: Request, run_id: int, error: ActionError | None) -> Response:
    """Answer a button press: the swapped body for HTMX, a redirect otherwise."""
    if request.headers.get("hx-request") != "true":
        return RedirectResponse(f"/run/{run_id}", status_code=303)
    notice = None
    if error is not None:
        t = context(request)["t"]
        key = f"action_error.{error.code}"
        notice = t(key) if t.has(key) else t("action_error.other", code=error.code)
    return _view(request, run_id, notice=notice, partial=True, status_code=200 if error is None else 409)


def _owned(conn, table: str, row_id: int, run_id: int) -> None:
    row = conn.execute(f"SELECT run_id FROM {table} WHERE id=?", (row_id,)).fetchone()  # table is a constant
    if row is None or row[0] != run_id:
        raise HTTPException(404)


def _edited(conn, approval_id: int, form) -> dict:
    row = conn.execute("SELECT tool, arguments_json FROM approvals WHERE id=?", (approval_id,)).fetchone()
    args = json.loads(row["arguments_json"])
    for field in run_view.editable_fields(row["tool"]):
        name = field["name"]
        if name not in form:
            continue
        value = str(form[name]).strip()
        if field["type"] == "integer":
            try:
                args[name] = int(value)
            except ValueError as exc:
                raise ActionError("bad_arguments", name) from exc
        else:
            args[name] = value
    return args


@router.post("/run/{run_id}/approvals/{approval_id}/{decision}")
async def decide(request: Request, run_id: int, approval_id: int, decision: str) -> Response:
    if decision not in ("approve", "edit", "skip"):
        raise HTTPException(404)
    form = await request.form()
    conn = db.connect()
    error = None
    try:
        _owned(conn, "approvals", approval_id, run_id)
        if decision == "skip":
            gate.skip(conn, approval_id)
        else:
            edited = _edited(conn, approval_id, form) if decision == "edit" else None
            outcome = gate.approve(conn, approval_id, edited)
            if outcome.status == "failed":
                error = ActionError(outcome.error or "failed")
    except ActionError as exc:
        error = exc
    finally:
        conn.close()
    return _after(request, run_id, error)


@router.post("/run/{run_id}/steps/{seq}/undo")
def undo(request: Request, run_id: int, seq: int) -> Response:
    conn = db.connect()
    error = None
    try:
        gate.undo(conn, run_id, seq)
    except ActionError as exc:
        error = exc
    finally:
        conn.close()
    return _after(request, run_id, error)


@router.post("/run/{run_id}/conflicts/{conflict_id}/{choice}")
def resolve(request: Request, run_id: int, conflict_id: int, choice: str) -> Response:
    conn = db.connect()
    error = None
    try:
        _owned(conn, "conflicts", conflict_id, run_id)
        outcome = conflicts.resolve(conn, conflict_id, choice)
        if outcome.status == "refused":
            error = ActionError(outcome.error or "refused")
    except ActionError as exc:
        error = exc
    finally:
        conn.close()
    return _after(request, run_id, error)
