"""Public spending limits (PRD 4.10): a daily dollar budget for live runs and a daily run count per visitor.

The visitor's address is taken from the Cloudflare header only when the hop that reached the host proxy is a
Cloudflare address; anyone else could write that header. Addresses are stored as a salted day hash, never raw.
Days are UTC days. A run still in progress counts at the per-run cost cap until it finishes.
"""

from __future__ import annotations

import hashlib
import ipaddress
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import Request

from . import config


def _cfg() -> dict:
    return config.settings()["public_budget"]


@lru_cache(maxsize=None)
def _ranges() -> tuple:
    return tuple(ipaddress.ip_network(r) for r in _cfg()["cloudflare_ranges"])


def _addr(value: str):
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    hop = _addr(peer)
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and hop is not None and (hop.is_private or hop.is_loopback):
        peer = forwarded.split(",")[-1].strip()  # the address the host proxy itself saw
        hop = _addr(peer)
    edge = request.headers.get(_cfg()["trusted_proxy_header"], "")
    if edge and hop is not None and any(hop in net for net in _ranges()) and _addr(edge) is not None:
        return edge.strip()
    return peer


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def client_key(request: Request) -> str:
    return hashlib.sha256(f"{today()}|{client_ip(request)}".encode("utf-8")).hexdigest()[:16]


def spent_today(conn: sqlite3.Connection) -> float:
    reserve = config.settings()["run_limits"]["max_cost_usd"]
    row = conn.execute(
        "SELECT COALESCE(SUM(COALESCE(cost_usd, CASE WHEN status='started' THEN ? ELSE 0 END)), 0) FROM runs"
        " WHERE mode='live' AND substr(created_at, 1, 10)=?", (reserve, today())).fetchone()
    return float(row[0])


def refusal(conn: sqlite3.Connection, key: str) -> str | None:
    """None when a live run may start; otherwise the i18n key that explains why not."""
    cfg = _cfg()
    if spent_today(conn) + config.settings()["run_limits"]["max_cost_usd"] > cfg["usd_per_day"]:
        return "run.budget_spent"
    runs = conn.execute("SELECT COUNT(*) FROM runs WHERE mode='live' AND client_key=? AND substr(created_at, 1, 10)=?",
                        (key, today())).fetchone()[0]
    if runs >= cfg["runs_per_ip_per_day"]:
        return "run.ip_limit"
    return None
