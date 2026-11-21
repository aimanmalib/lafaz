"""Static asset URLs with a content hash, so Cloudflare's 4 hour cache of .css/.js never serves a stale file."""

from __future__ import annotations

import hashlib
from functools import lru_cache

from .config import REPO_ROOT

STATIC_DIR = REPO_ROOT / "static"


@lru_cache(maxsize=None)
def _digest(relpath: str) -> str:
    data = (STATIC_DIR / relpath).read_bytes()
    return hashlib.sha256(data).hexdigest()[:10]


def asset_url(relpath: str) -> str:
    return f"/static/{relpath}?v={_digest(relpath)}"
