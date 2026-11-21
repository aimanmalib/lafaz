"""Conflicts between a new decision and earlier active ones (PRD 4.6).

Code picks the candidates (lafaz.memory.decisions), the model judges each pair with `judge_conflict`, and code checks
that the old quote is in the old meeting and the new quote is in the new meeting. A rejected judgement is kept with
its reason and never shown as a conflict. A reported conflict becomes an open card: Replace, Keep both, or Ask the
team. Which of those runs straight away and which waits for a person comes from `kategori` in config/tools.json.
"""

from __future__ import annotations

import sqlite3

from .. import config, i18n
from ..agent import gate, trace
from ..agent.context import ActionError, load
from ..listen.quotes import QuoteChecker
from . import decisions

TOOL = "judge_conflict"
PROMPT = "conflict"


def judge_message(old: sqlite3.Row, new: sqlite3.Row) -> str:
    return (
        f"<earlier_decision date=\"{old['meeting_date']}\">\n{old['statement']}\n</earlier_decision>\n"
        f"<earlier_meeting>\n{old['meeting_text']}\n</earlier_meeting>\n\n"
        f"<new_decision date=\"{new['meeting_date']}\">\n{new['statement']}\n</new_decision>\n"
        f"<new_meeting>\n{new['meeting_text']}\n</new_meeting>"
    )


def check_judgement(raw: dict, old: sqlite3.Row, new: sqlite3.Row) -> str | None:
    """Return a reject reason, or None when both quotes are where they must be."""
    min_words = config.listen()["min_quote_words"]
    for quote, text, prefix in ((raw.get("old_quote"), old["meeting_text"], "old_"),
                                (raw.get("new_quote"), new["meeting_text"], "new_")):
        verdict = QuoteChecker(text, min_words).check_quote(quote or "")
        if not verdict.ok:
            return prefix + verdict.reason
    return None


def _insert(conn, run_id, new_id, old_id, shared, verdict, raw=None, reject=None) -> int:
    raw = raw or {}
    cur = conn.execute(
        "INSERT OR IGNORE INTO conflicts (run_id, new_decision_id, old_decision_id, shared_terms, verdict, reason,"
        " reject_reason, old_quote, new_quote, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (run_id, new_id, old_id, " ".join(shared), verdict, raw.get("reason"), reject, raw.get("old_quote"),
         raw.get("new_quote"), "open" if verdict == "conflict" else "closed"),
    )
    return cur.lastrowid


def _judge_one(conn, llm, run_id, new, old, shared, budget) -> str:
    try:
        call = llm.call_tool(config.prompt(PROMPT), judge_message(old, new), TOOL)
    except Exception as exc:  # noqa: BLE001 - a failed judgement is recorded, never a crash
        code = getattr(exc, "code", type(exc).__name__)
        _insert(conn, run_id, new["id"], old["id"], shared, "not_judged", reject=f"model_error:{code}")
        trace.record(conn, run_id, tool=TOOL, category=gate.category_of(TOOL) or "read",
                     arguments={"new": new["id"], "old": old["id"]}, status="refused", result={"error": code})
        return "not_judged"
    if budget is not None:
        budget.spend(call.cost_usd)
    reject = check_judgement(call.input, old, new)
    verdict = "rejected" if reject else ("conflict" if call.input.get("conflict") is True else "no_conflict")
    conflict_id = _insert(conn, run_id, new["id"], old["id"], shared, verdict, call.input, reject)
    trace.record(conn, run_id, tool=TOOL, category=gate.category_of(TOOL) or "read",
                 arguments={"new": new["id"], "old": old["id"], "shared": shared}, status="executed",
                 result={"verdict": verdict, "conflict_id": conflict_id, "reject": reject},
                 ms=call.ms, tokens_in=call.tokens_in, tokens_out=call.tokens_out, cost_usd=call.cost_usd)
    return verdict


def detect(conn: sqlite3.Connection, run_id: int, llm, budget=None) -> dict[str, int]:
    """Save the run's decisions and judge each code-picked candidate pair. Returns counts by verdict.

    `budget` (the loop's Budget) is optional: each judgement is one step; once a limit is reached the remaining
    pairs are stored as 'not_judged' so nothing is silently dropped.
    """
    counts: dict[str, int] = {}
    for new_id in decisions.save_run(conn, run_id):
        new = decisions.get(conn, new_id)
        for old, shared in decisions.candidates(conn, new_id):
            if budget is not None and budget.exceeded():
                _insert(conn, run_id, new_id, old["id"], shared, "not_judged", reject=budget.exceeded())
                verdict = "not_judged"
            else:
                if budget is not None:
                    budget.steps += 1
                verdict = _judge_one(conn, llm, run_id, new, old, shared, budget)
            counts[verdict] = counts.get(verdict, 0) + 1
    conn.commit()
    return counts


def open_cards(conn: sqlite3.Connection, run_id: int | None = None) -> list[dict]:
    sql = (
        "SELECT c.*, o.statement AS old_statement, om.meeting_date AS old_date, n.statement AS new_statement,"
        " nm.meeting_date AS new_date FROM conflicts c"
        " JOIN decisions o ON o.id = c.old_decision_id JOIN meetings om ON om.id = o.meeting_id"
        " JOIN decisions n ON n.id = c.new_decision_id JOIN meetings nm ON nm.id = n.meeting_id"
        " WHERE c.verdict='conflict'"
    )
    params: tuple = ()
    if run_id is not None:
        sql += " AND c.run_id=?"
        params = (run_id,)
    return [dict(r) for r in conn.execute(sql + " ORDER BY c.id", params)]


def _card(conn, conflict_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM conflicts WHERE id=?", (conflict_id,)).fetchone()
    if row is None or row["verdict"] != "conflict":
        raise ActionError("unknown_conflict", str(conflict_id))
    if row["status"] != "open":
        raise ActionError("already_decided", row["status"])
    return row


def ask_arguments(conn: sqlite3.Connection, card: sqlite3.Row) -> dict:
    """The team email for 'Ask the team', written by code from the two quotes in the run's language."""
    full = next(c for c in open_cards(conn) if c["id"] == card["id"])
    lang = conn.execute("SELECT lang FROM runs WHERE id=?", (card["run_id"],)).fetchone()[0]
    t = i18n.Translator(lang)
    params = {"old_date": full["old_date"], "old_quote": card["old_quote"], "new_date": full["new_date"],
              "new_quote": card["new_quote"]}
    return {"subject": t("conflict.ask_subject", **params), "body": t("conflict.ask_body", **params),
            "quote": card["new_quote"]}


def resolve(conn: sqlite3.Connection, conflict_id: int, choice: str) -> gate.Outcome:
    """A person pressed a button on a conflict card."""
    card = _card(conn, conflict_id)
    tool = config.memory()["conflict"]["choices"].get(choice)
    if tool is None:
        raise ActionError("unknown_choice", choice)
    args = ask_arguments(conn, card) if tool == "ask_team" else {"conflict_id": conflict_id}
    outcome = gate.dispatch(load(conn, card["run_id"]), tool, args, stage=config.tool(tool).get("stage"))
    if tool == "ask_team" and outcome.status in ("pending_approval", "executed"):
        conn.execute("UPDATE conflicts SET status='asked', approval_id=?, decided_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
                     " WHERE id=?", (outcome.approval_id, conflict_id))
        conn.commit()
    return outcome


def summary(conn: sqlite3.Connection, run_id: int) -> dict[str, int]:
    rows = conn.execute("SELECT verdict, COUNT(*) FROM conflicts WHERE run_id=? GROUP BY verdict", (run_id,))
    return {verdict: n for verdict, n in rows}
