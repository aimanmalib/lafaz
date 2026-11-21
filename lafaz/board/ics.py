"""The calendar feed `/ics/<token>.ics` (RFC 5545), one per space.

Each open task with a due date is an all-day event on its due date. Each active reminder policy on that task becomes
an alarm the same number of days before, so the calendar shows what a person already approved. The public space has
a fixed, non-secret token from config. The owner space token is derived from the owner secret, so knowing the public
token says nothing about the owner one, and the owner feed disappears when the owner secret is unset.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from datetime import date, timedelta

from .. import config, owner
from . import tasks

_LINE_OCTETS = 75


def owner_token() -> str | None:
    secret = owner.secret()
    if not secret:
        return None
    cfg = config.board()["ics"]
    digest = hmac.new(secret.encode("utf-8"), cfg["owner_token_label"].encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[: cfg["owner_token_chars"]]


def token_for(space: str) -> str | None:
    return owner_token() if space == "owner" else config.board()["ics"]["public_token"]


def space_for(token: str) -> str | None:
    if token == config.board()["ics"]["public_token"]:
        return "public"
    expected = owner_token()
    if expected and hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        return "owner"
    return None


def escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def fold(line: str) -> str:
    """Split a content line into 75-octet pieces without cutting a UTF-8 character."""
    out, current, size = [], "", 0
    for ch in line:
        width = len(ch.encode("utf-8"))
        limit = _LINE_OCTETS if not out else _LINE_OCTETS - 1
        if size + width > limit:
            out.append(current)
            current, size = "", 0
        current += ch
        size += width
    out.append(current)
    return "\r\n ".join(out)


def _stamp(created_at: str) -> str:
    return created_at.replace("-", "").replace(":", "")


def _event(task: sqlite3.Row, alarms: list[sqlite3.Row], uid_domain: str) -> list[str]:
    due = date.fromisoformat(task["due_date"])
    summary = f"{task['title']} ({task['owner']})" if task["owner"] else task["title"]
    lines = [
        "BEGIN:VEVENT",
        f"UID:task-{task['id']}@{uid_domain}",
        f"DTSTAMP:{_stamp(task['created_at'])}",
        f"DTSTART;VALUE=DATE:{due.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(due + timedelta(days=1)).strftime('%Y%m%d')}",
        f"SUMMARY:{escape(summary)}",
        "TRANSP:TRANSPARENT",
    ]
    if task["quote"]:
        lines.append(f"DESCRIPTION:{escape(task['quote'])}")
    for policy in alarms:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-P{int(policy['days_before'])}D",
                  f"DESCRIPTION:{escape(policy['message'])}", "END:VALARM"]
    lines.append("END:VEVENT")
    return lines


def feed(conn: sqlite3.Connection, space: str) -> str:
    cfg = config.board()["ics"]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{cfg['prodid']}", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{escape(cfg['calendar_name'])}"]
    for task in tasks.dated(conn, space):
        lines += _event(task, tasks.policies(conn, task["id"]), cfg["uid_domain"])
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
