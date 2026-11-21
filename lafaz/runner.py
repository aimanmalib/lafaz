"""Start a run in a worker thread so the page can show progress instead of holding a request open for a minute.

Live runs need the model key in the environment (name in config llm.key_env). Without it, or once the public budget
is spent, only a recorded sample can run, as a replay (PRD 4.10, lafaz.replay). A run left 'started' by a restart is closed as 'interrupted' at start-up.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date

from . import config, db
from .agent import loop
from .llm import LLM

log = logging.getLogger("lafaz.runner")


def live_available() -> bool:
    return bool(os.environ.get(config.settings()["llm"]["key_env"]))


def make_llm() -> LLM:
    return LLM()


def spawn(work) -> None:
    threading.Thread(target=work, name="lafaz-run", daemon=True).start()


def _stop(conn, run_id: int, reason: str) -> None:
    handoff = {"reason": reason, "done": [], "not_done": [], "questions": [], "quotes": [], "conflicts": []}
    conn.execute("UPDATE runs SET status='stopped', handoff_json=?, finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
                 " WHERE id=? AND status='started'", (json.dumps(handoff), run_id))
    conn.commit()


def launch(run_id: int, text: str, meeting_date: date, llm: LLM | None = None) -> None:
    def work() -> None:
        conn = db.connect()
        try:
            loop.run(conn, run_id, text, meeting_date, llm=llm or make_llm())
        except Exception:  # noqa: BLE001 - a bug must end the run visibly, not leave it spinning
            log.exception("run %s failed", run_id)
            _stop(conn, run_id, "internal_error")
        finally:
            conn.close()

    spawn(work)


def recover() -> int:
    conn = db.connect()
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM runs WHERE status='started'")]
        for run_id in ids:
            _stop(conn, run_id, "interrupted")
        return len(ids)
    finally:
        conn.close()
