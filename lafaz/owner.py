"""The owner space (PRD 4.7): runs started here really send approved emails to the test inbox.

The way in is a secret link `/owner/<token>`; the token lives only in the environment (name in config/mail.json).
Opening the link sets an HttpOnly cookie holding the token. Without the token set, there is no owner space at all.
"""

from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException

from . import config

router = APIRouter()


def secret() -> str:
    return os.environ.get(config.mail()["env"]["owner_token"], "")


def _matches(value: str | None) -> bool:
    token = secret()
    return bool(token and value) and hmac.compare_digest(value.encode("utf-8"), token.encode("utf-8"))


def is_owner(request: Request) -> bool:
    return _matches(request.cookies.get(config.mail()["owner_cookie"]))


def space(request: Request) -> str:
    return "owner" if is_owner(request) else "public"


@router.get("/owner/{token}")
def enter(request: Request, token: str) -> RedirectResponse:
    if not _matches(token):
        raise HTTPException(404)
    cfg = config.mail()
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(cfg["owner_cookie"], token, max_age=cfg["owner_cookie_days"] * 86400, httponly=True,
                        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https", samesite="lax")
    return response


@router.post("/owner/leave")
def leave() -> RedirectResponse:
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(config.mail()["owner_cookie"])
    return response
