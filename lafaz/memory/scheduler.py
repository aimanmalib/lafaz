"""The in-process scheduler (PRD 4.6): no daemon outside the app. Every `scheduler.reminder_check_seconds` it runs
one reminder pass in a worker thread. A failed pass is logged and the loop carries on."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import config, db
from . import reminders

log = logging.getLogger("lafaz.scheduler")


def today():
    return datetime.now(ZoneInfo(config.settings()["app"]["timezone"])).date()


def run_once() -> list[int]:
    conn = db.connect()
    try:
        return reminders.tick(conn, today())
    finally:
        conn.close()


async def loop(interval: float | None = None) -> None:
    interval = interval or config.settings()["scheduler"]["reminder_check_seconds"]
    while True:
        await asyncio.sleep(interval)
        try:
            queued = await asyncio.to_thread(run_once)
            if queued:
                log.info("reminders queued: %d", len(queued))
        except Exception:  # noqa: BLE001 - the scheduler must outlive one bad pass
            log.exception("reminder pass failed")
