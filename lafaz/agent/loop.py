"""The agent loop (W2): listen, then a manual tool loop over the plan tools, inside hard limits.

The model proposes tool calls; lafaz.agent.gate decides what happens to each one from its `kategori`. When a limit is
reached, the model fails, or facts needed to act are missing, the run stops on purpose and stores a handoff object
{reason, done, not_done, questions, quotes} that the interface shows as "Lafaz stopped here, and why".
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from .. import config
from ..listen import store
from ..listen.extract import ListenResult, listen
from ..llm import LLM, LLMError
from . import gate, trace
from .context import load

PROMPT = "plan"


@dataclass
class Budget:
    clock: Callable[[], float] = time.monotonic
    steps: int = 0
    cost_usd: float = 0.0
    started: float = field(default=0.0)

    def __post_init__(self):
        self.limits = config.settings()["run_limits"]
        self.started = self.clock()

    def spend(self, cost: float) -> None:
        self.cost_usd = round(self.cost_usd + cost, 6)

    def exceeded(self) -> str | None:
        if self.steps >= self.limits["max_steps"]:
            return "limit_steps"
        if self.clock() - self.started >= self.limits["max_seconds"]:
            return "limit_seconds"
        if self.cost_usd >= self.limits["max_cost_usd"]:
            return "limit_cost"
        return None


def start_run(conn: sqlite3.Connection, text: str, meeting_date: date, source: str, lang: str,
              title: str | None = None, mode: str = "live") -> int:
    cur = conn.execute("INSERT INTO meetings (meeting_date, title, source, text) VALUES (?,?,?,?)",
                       (meeting_date.isoformat(), title, source, text))
    run = conn.execute("INSERT INTO runs (meeting_id, mode, lang) VALUES (?,?,?)", (cur.lastrowid, mode, lang))
    conn.commit()
    return run.lastrowid


def plan_message(result: ListenResult, meeting_date: date) -> str:
    items = [
        {"index": i, "kind": it["kind"], "text": it["text"], "owner": it.get("owner"),
         "due_date": it.get("due_date"), "quotes": it["quotes"]}
        for i, it in enumerate(result.items)
    ]
    questions = [{"item_index": q.get("item_index"), "quote": q.get("quote"),
                  "question": q.get("text") or q.get("code")} for q in result.questions]
    return (
        f"Meeting date: {meeting_date.isoformat()}\n\n"
        f"<understood>\n{json.dumps(items, ensure_ascii=False, indent=1)}\n</understood>\n\n"
        f"<open_questions>\n{json.dumps(questions, ensure_ascii=False, indent=1)}\n</open_questions>"
    )


def _tool_result(use, outcome: gate.Outcome) -> dict:
    block = {"type": "tool_result", "tool_use_id": use.id,
             "content": json.dumps(outcome.for_model(), ensure_ascii=False)}
    if outcome.status == "refused":
        block["is_error"] = True
    return block


def handoff(conn: sqlite3.Connection, run_id: int, reason: str, skipped: list[dict] | None = None) -> dict:
    done, not_done = [], list(skipped or [])
    for step in trace.steps(conn, run_id):
        if step["category"] not in gate.CATEGORIES or step["tool"] == "record_items":
            continue
        entry = {"seq": step["seq"], "tool": step["tool"], "approval_id": step["approval_id"]}
        if step["status"] == "executed":
            done.append(entry)
        elif step["status"] in ("pending_approval", "refused"):
            not_done.append({**entry, "status": step["status"], "result": json.loads(step["result_summary"] or "{}")})
    questions = [dict(q) for q in conn.execute(
        "SELECT origin, code, params_json, text, item_seq, quote FROM questions WHERE run_id=? ORDER BY seq", (run_id,))]
    return {"reason": reason, "done": done, "not_done": not_done, "questions": questions,
            "quotes": [q["quote"] for q in questions if q["quote"]]}


def _finish(conn, run_id: int, budget: Budget, reason: str | None, skipped=None) -> dict:
    status = "done" if reason is None else "stopped"
    data = handoff(conn, run_id, reason or "finished", skipped)
    conn.execute(
        "UPDATE runs SET status=?, handoff_json=?, cost_usd=?, finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
        " WHERE id=?", (status, json.dumps(data, ensure_ascii=False), budget.cost_usd, run_id))
    conn.commit()
    return {"run_id": run_id, "status": status, **data}


def _model_error(exc: Exception) -> str:
    return f"model_error:{exc.code}" if isinstance(exc, LLMError) else f"model_error:{type(exc).__name__}"


def _listen(conn, run_id, text, meeting_date, people, llm, budget) -> ListenResult:
    result = listen(text, meeting_date, people, llm)
    store.save(conn, run_id, result)
    call = result.call
    budget.spend(call.cost_usd)
    budget.steps += 1
    trace.record(conn, run_id, tool="record_items", category=gate.category_of("record_items") or "read",
                 arguments={"chars": len(text)}, status="executed",
                 result={"accepted": len(result.items), "rejected": len(result.rejected),
                         "questions": len(result.questions)},
                 ms=call.ms, tokens_in=call.tokens_in, tokens_out=call.tokens_out, cost_usd=call.cost_usd)
    conn.commit()
    return result


def run(conn: sqlite3.Connection, run_id: int, text: str, meeting_date: date, people: list[dict] | None = None,
        llm: LLM | None = None, clock=time.monotonic) -> dict:
    llm = llm or LLM()
    budget = Budget(clock=clock)
    try:
        result = _listen(conn, run_id, text, meeting_date, people or [], llm, budget)
    except Exception as exc:  # noqa: BLE001 - any model failure is a designed stop, never a crash page
        return _finish(conn, run_id, budget, _model_error(exc))
    if not result.items:
        return _finish(conn, run_id, budget, "nothing_heard")
    ctx = load(conn, run_id)
    tools = [t["name"] for t in gate.plan_tools()]
    messages = [{"role": "user", "content": plan_message(result, meeting_date)}]
    while True:
        reason = budget.exceeded()
        if reason:
            return _finish(conn, run_id, budget, reason)
        try:
            turn = llm.converse(config.prompt(PROMPT), messages, tools)
        except Exception as exc:  # noqa: BLE001
            return _finish(conn, run_id, budget, _model_error(exc))
        budget.spend(turn.cost_usd)
        text_out = " ".join(getattr(b, "text", "") for b in turn.content if getattr(b, "type", None) == "text")
        trace.record(conn, run_id, tool="model", category="model", arguments={"turn": len(messages) // 2},
                     status=turn.stop_reason, result={"text": text_out.strip()} if text_out.strip() else None,
                     ms=turn.ms, tokens_in=turn.tokens_in, tokens_out=turn.tokens_out, cost_usd=turn.cost_usd)
        conn.commit()
        if not turn.tool_uses:
            return _finish(conn, run_id, budget, "missing_facts" if result.questions else None)
        messages.append({"role": "assistant", "content": turn.content})
        results, skipped = [], []
        for use in turn.tool_uses:
            reason = budget.exceeded()
            if reason:
                skipped.append({"tool": use.name, "status": "not_run", "result": {"error": reason}})
                continue
            budget.steps += 1
            results.append(_tool_result(use, gate.dispatch(ctx, use.name, use.input)))
        if skipped:
            return _finish(conn, run_id, budget, budget.exceeded(), skipped)
        messages.append({"role": "user", "content": results})
