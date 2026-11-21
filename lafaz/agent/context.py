"""What an action may rely on: the run, its meeting text, and the items the listen layer accepted.

Built from the database, so an approval clicked an hour after the run sees exactly what the loop saw.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .. import config
from ..listen.quotes import QuoteChecker


class ActionError(Exception):
    """An action refused its arguments. `code` is stable and goes back to the model and into the trace."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass
class RunContext:
    conn: sqlite3.Connection
    run_id: int
    text: str
    items: list[dict]

    @property
    def checker(self) -> QuoteChecker:
        return QuoteChecker(self.text, config.listen()["min_quote_words"])

    def item(self, index) -> dict:
        if not isinstance(index, int) or not 0 <= index < len(self.items):
            raise ActionError("unknown_item", str(index))
        return self.items[index]

    def owners(self) -> list[str]:
        return sorted({i["owner"] for i in self.items if i.get("owner")})

    def require_owner(self, person: str) -> str:
        for owner in self.owners():
            if owner.casefold() == (person or "").strip().casefold():
                return owner
        raise ActionError("unknown_person", person or "")

    def require_quote(self, quote: str) -> str:
        verdict = self.checker.check_quote(quote or "")
        if not verdict.ok:
            raise ActionError(verdict.reason, quote or "")
        return quote

    def task(self, task_id) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id=? AND run_id=? AND status != 'undone'", (task_id, self.run_id)
        ).fetchone()
        if row is None:
            raise ActionError("unknown_task", str(task_id))
        return row


def load(conn: sqlite3.Connection, run_id: int) -> RunContext:
    row = conn.execute(
        "SELECT m.text FROM runs r JOIN meetings m ON m.id = r.meeting_id WHERE r.id=?", (run_id,)
    ).fetchone()
    if row is None:
        raise ActionError("unknown_run", str(run_id))
    items = []
    for item in conn.execute(
        "SELECT seq, kind, text, owner, due_date, quotes_json FROM items WHERE run_id=? AND status='accepted' ORDER BY seq",
        (run_id,),
    ):
        items.append(
            {"seq": item["seq"], "kind": item["kind"], "text": item["text"], "owner": item["owner"],
             "due_date": item["due_date"], "quotes": json.loads(item["quotes_json"])}
        )
    return RunContext(conn=conn, run_id=run_id, text=row["text"], items=items)
