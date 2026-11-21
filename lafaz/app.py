"""FastAPI application: dictation page, health check, language switch. Run pages live in lafaz.routes_run."""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, db, owner, runner
from .assets import STATIC_DIR
from .mail import delivery
from .memory import scheduler
from .routes_board import router as board_router
from .routes_eval import router as eval_router
from .routes_run import router as run_router
from .web import context, render, today



@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    runner.recover()
    conn = db.connect()
    try:
        delivery.recover(conn)
    finally:
        conn.close()
    runner.spawn(delivery.dispatch)
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

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        from fastapi.responses import FileResponse
        return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon")

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        ok = db.healthy()
        return JSONResponse({"ok": ok, "db": "wal" if ok else "error"}, status_code=200 if ok else 503)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        return render("index.html", context(request, text="", meeting_date=today(), sample=None))

    @app.get("/sample", response_class=HTMLResponse)
    def sample(request: Request, n: int = 0) -> HTMLResponse:
        items = config.samples()
        chosen = items[n % len(items)]
        ctx = context(request, text=chosen["text"], meeting_date=chosen["meeting_date"], sample=chosen)
        return render("partials/sheet.html", ctx)

    app.include_router(run_router)
    app.include_router(eval_router)
    app.include_router(board_router)
    app.include_router(owner.router)

    @app.exception_handler(StarletteHTTPException)
    async def not_found(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404 and not request.url.path.startswith("/static/"):
            return render("404.html", context(request), status_code=404)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app


app = create_app()
