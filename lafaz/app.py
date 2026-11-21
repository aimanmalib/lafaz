"""FastAPI application: pages, health check, language switch."""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, db, i18n
from .assets import STATIC_DIR, asset_url
from .config import REPO_ROOT
from .memory import scheduler

templates = Jinja2Templates(directory=str(REPO_ROOT / "templates"))
templates.env.globals["asset"] = asset_url


def _today() -> str:
    return scheduler.today().isoformat()


def _context(request: Request, **extra: object) -> dict:
    app_cfg = config.settings()["app"]
    lang = i18n.pick(request.query_params.get("lang"), request.cookies.get(app_cfg["lang_cookie"]))
    rung = config.settings()["rung"]
    ctx = {
        "request": request,
        "lang": lang,
        "languages": i18n.languages(),
        "t": i18n.Translator(lang),
        "rung_key": rung["levels"][str(rung["current"])],
        "max_chars": config.settings()["input"]["max_chars"],
    }
    ctx.update(extra)
    return ctx


def _render(name: str, ctx: dict, status_code: int = 200) -> HTMLResponse:
    response = templates.TemplateResponse(ctx["request"], name, ctx, status_code=status_code)
    requested = ctx["request"].query_params.get("lang")
    if requested in ctx["languages"]:
        app_cfg = config.settings()["app"]
        response.set_cookie(
            app_cfg["lang_cookie"], requested, max_age=app_cfg["lang_cookie_days"] * 86400, samesite="lax"
        )
    return response


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(scheduler.loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    app = FastAPI(title="Lafaz", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    db.init()

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        if config.settings()["app"]["noindex"]:
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache, no-transform"
        return response

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        ok = db.healthy()
        return JSONResponse({"ok": ok, "db": "wal" if ok else "error"}, status_code=200 if ok else 503)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        return _render("index.html", _context(request, text="", meeting_date=_today(), sample=None))

    @app.get("/sample", response_class=HTMLResponse)
    def sample(request: Request, n: int = 0) -> HTMLResponse:
        items = config.samples()
        chosen = items[n % len(items)]
        ctx = _context(request, text=chosen["text"], meeting_date=chosen["meeting_date"], sample=chosen)
        return _render("partials/sheet.html", ctx)

    @app.post("/run", response_class=HTMLResponse)
    def run(request: Request, text: str = Form(""), meeting_date: str = Form("")) -> HTMLResponse:
        ctx = _context(request)
        limit = ctx["max_chars"]
        if not text.strip():
            notice, status = ctx["t"]("run.empty"), 422
        elif len(text) > limit:
            notice, status = ctx["t"]("run.too_long", max=limit), 422
        else:
            notice, status = ctx["t"]("run.not_ready"), 503
        ctx.update(text=text, meeting_date=meeting_date or _today(), sample=None, notice=notice)
        return _render("index.html", ctx, status_code=status)

    @app.exception_handler(StarletteHTTPException)
    async def not_found(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404 and not request.url.path.startswith("/static/"):
            return _render("404.html", _context(request), status_code=404)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app


app = create_app()
