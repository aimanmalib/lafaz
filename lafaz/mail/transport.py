"""SMTP and IMAP for the test inbox. Credentials are read from the environment at call time and never logged.

`send` returns nothing on success and raises on failure. `arrived` answers whether a message with this Message-ID is
in the inbox now. Both take a connection factory so tests run without a network.
"""

from __future__ import annotations

import imaplib
import os
import re
import smtplib
import ssl
from email.message import EmailMessage

from .. import config


def _cfg() -> dict:
    return config.mail()


def credentials() -> tuple[str, str] | None:
    env = _cfg()["env"]
    user, password = os.environ.get(env["user"], ""), os.environ.get(env["password"], "")
    return (user, password) if user and password else None


def configured() -> bool:
    return credentials() is not None


def smtp_connect() -> smtplib.SMTP:
    cfg = _cfg()
    return smtplib.SMTP_SSL(cfg["smtp"]["host"], cfg["smtp"]["port"], timeout=cfg["timeout_s"],
                            context=ssl.create_default_context())


def imap_connect() -> imaplib.IMAP4:
    cfg = _cfg()
    return imaplib.IMAP4_SSL(cfg["imap"]["host"], cfg["imap"]["port"], timeout=cfg["timeout_s"],
                             ssl_context=ssl.create_default_context())


def send(message: EmailMessage, connect=smtp_connect) -> None:
    user, password = credentials() or ("", "")
    with connect() as smtp:
        smtp.login(user, password)
        smtp.send_message(message)


_ID = re.compile(r"^<[A-Za-z0-9.@_+=-]+>$")


def arrived(message_id: str, connect=imap_connect) -> bool:
    if not _ID.match(message_id):  # the id is placed in an IMAP search; only the shape make_msgid produces passes
        raise ValueError("unexpected Message-ID shape")
    user, password = credentials() or ("", "")
    imap = connect()
    try:
        imap.login(user, password)
        imap.select(_cfg()["imap"]["folder"], readonly=True)
        status, data = imap.search(None, "HEADER", "Message-ID", f'"{message_id}"')
        return status == "OK" and bool(data and data[0].split())
    finally:
        try:
            imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
