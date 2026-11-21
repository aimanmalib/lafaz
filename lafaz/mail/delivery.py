"""Deliver approved emails from the outbox (PRD 4.7).

The outbox row is written when a person approves (or when an approved reminder policy fires). This module decides
what happens to it next, from the space the run was started in:

  public space   -> 'sandbox'    shown in the in-app outbox, never sent
  owner space    -> 'sending' -> 'sent' -> 'delivered' once IMAP finds the Message-ID in the test inbox
                    'unverified' if it was accepted by SMTP but not found in time, 'failed' if SMTP refused it
  owner space without SMTP credentials -> 'held'

Every person maps to a plus alias of the one test inbox, so a real person is never emailed. Each outcome is a trace
step whose status starts with 'mail_', so it never counts as an action that ran.
"""

from __future__ import annotations

import imaplib
import logging
import re
import smtplib
import sqlite3
import threading
import time
import unicodedata
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from .. import config, db, i18n
from ..agent import trace
from . import transport

log = logging.getLogger("lafaz.mail")
_LOCK = threading.Lock()
WAITING = ("queued", "sending", "sent")


def _alias(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[: config.mail()["alias_max_chars"]].strip("-")


def address_for(recipient: str, inbox: str) -> str:
    """The test inbox, with the person's name as a plus alias when config allows it."""
    cfg = config.mail()
    slug = _alias(cfg["team_alias"] if recipient == "team" else recipient)
    if not cfg["plus_alias"] or not slug:
        return inbox
    local, _, domain = inbox.partition("@")
    return f"{local}+{slug}@{domain}"


def build(row: sqlite3.Row, inbox: str) -> EmailMessage:
    cfg = config.mail()
    t = i18n.Translator(row["lang"])
    to = address_for(row["recipient"], inbox)
    subject = f"{cfg['subject_prefix']} {row['subject']}"
    if to == inbox:  # no alias: the name goes in the subject so each person's mail can still be told apart
        subject += f" ({row['recipient']})"
    msg = EmailMessage()
    msg["From"] = formataddr((cfg["from_name"], inbox))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=inbox.partition("@")[2] or None)
    footer = t("mail.footer_policy" if row["label"] else "mail.footer", date=row["meeting_date"])
    msg.set_content(f"{row['body']}\n\n-- \n{footer}\n")
    return msg


def _set(conn: sqlite3.Connection, row: sqlite3.Row, status: str, **cols) -> str:
    sets = ", ".join(f"{k}=?" for k in ("status", *cols))
    conn.execute(f"UPDATE outbox SET {sets} WHERE id=?", (status, *cols.values(), row["id"]))  # keys are constants
    trace.record(conn, row["run_id"], tool=row["tool"], category="irreversible",
                 arguments={"outbox_id": row["id"]}, status=f"mail_{status}",
                 result={k: v for k, v in cols.items() if k in ("address", "message_id", "error")} or None,
                 approval_id=row["approval_id"])
    conn.commit()
    return status


def _row(conn: sqlite3.Connection, outbox_id: int) -> sqlite3.Row:
    return conn.execute(
        "SELECT o.*, r.space, r.lang, m.meeting_date FROM outbox o JOIN runs r ON r.id = o.run_id"
        " JOIN meetings m ON m.id = r.meeting_id WHERE o.id=?", (outbox_id,)).fetchone()


def deliver(conn: sqlite3.Connection, outbox_id: int, *, smtp_connect=None, imap_connect=None,
            sleep=time.sleep) -> str:
    row = _row(conn, outbox_id)
    if row is None or row["status"] != "queued":
        return row["status"] if row else "missing"
    if row["space"] != "owner":
        return _set(conn, row, "sandbox")
    creds = transport.credentials()
    if creds is None:
        return _set(conn, row, "held")
    if conn.execute("UPDATE outbox SET status='sending' WHERE id=? AND status='queued'", (outbox_id,)).rowcount != 1:
        conn.commit()
        return "sending"
    conn.commit()
    msg = build(row, creds[0])
    try:
        transport.send(msg, smtp_connect or transport.smtp_connect)
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("outbox %s: SMTP refused (%s)", outbox_id, type(exc).__name__)
        return _set(conn, row, "failed", error=type(exc).__name__)
    mid = msg["Message-ID"]
    _set(conn, row, "sent", address=msg["To"], message_id=mid,
         sent_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    verify = config.mail()["verify"]
    for _ in range(verify["attempts"]):
        sleep(verify["wait_seconds"])
        try:
            if transport.arrived(mid, imap_connect or transport.imap_connect):
                return _set(conn, row, "delivered", delivered_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        except (imaplib.IMAP4.error, OSError) as exc:
            log.warning("outbox %s: IMAP check failed (%s)", outbox_id, type(exc).__name__)
    return _set(conn, row, "unverified")


def dispatch(**kwargs) -> dict[int, str]:
    """Deliver every queued row, one dispatcher at a time. Safe to call from any thread: a second caller waits and
    then finds only what arrived meanwhile."""
    with _LOCK:
        conn = db.connect()
        try:
            ids = [r[0] for r in conn.execute("SELECT id FROM outbox WHERE status='queued' ORDER BY id")]
            return {i: deliver(conn, i, **kwargs) for i in ids}
        finally:
            conn.close()


def recover(conn: sqlite3.Connection) -> int:
    """A restart during SMTP leaves 'sending' rows: whether the mail left is unknown, so they are marked, not resent."""
    rows = conn.execute("SELECT o.*, r.space FROM outbox o JOIN runs r ON r.id = o.run_id WHERE o.status='sending'")
    rows = rows.fetchall()
    for row in rows:
        _set(conn, row, "unverified", error="interrupted")
    return len(rows)
