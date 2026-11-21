"""Shared page helpers: templates, the per-request context (language, rung) and rendering with the language cookie."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import config, i18n
from .assets import asset_url
from .config import REPO_ROOT
from .memory import scheduler

templates = Jinja2Templates(directory=str(REPO_ROOT / "templates"))
templates.env.globals["asset"] = asset_url


def today() -> str:
    return scheduler.today().isoformat()


def context(request: Request, **extra: object) -> dict:
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


def render(name: str, ctx: dict, status_code: int = 200) -> HTMLResponse:
    response = templates.TemplateResponse(ctx["request"], name, ctx, status_code=status_code)
    requested = ctx["request"].query_params.get("lang")
    if requested in ctx["languages"]:
        app_cfg = config.settings()["app"]
        response.set_cookie(
            app_cfg["lang_cookie"], requested, max_age=app_cfg["lang_cookie_days"] * 86400, samesite="lax"
        )
    return response
