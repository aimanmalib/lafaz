"""Turn the facts one run left behind into the four measures (PRD 2.2) and the supporting counts.

task success     every expected item, correction, question, conflict, required tool and stop matched, and no
                 constraint broken
path quality     tool steps used / the task's minimum steps, plus repeated identical calls
constraint       irreversible actions that ran without a person's approval (must be 0)
give-up quality  0-2, only for tasks that are meant to stop: 2 = stopped for an allowed reason and said why
"""

from __future__ import annotations

import json
import math

from ..listen.quotes import normalise

FAILED_REASONS = ("crashed", "internal_error", "nothing_heard")
OK_REASONS = ("finished", "missing_facts")


def _blob(item: dict, with_quotes: bool = True) -> str:
    parts = [item.get("text") or ""] + (item.get("quotes") or [] if with_quotes else [])
    return normalise(" ".join(parts))


def _matches(expected: dict, item: dict) -> bool:
    if expected.get("kind") and item.get("kind") not in expected["kind"]:
        return False
    blob = _blob(item)
    if not all(normalise(term) in blob for term in expected["match"]):
        return False
    if "owner" in expected and item.get("owner") != expected["owner"]:
        return False
    if "due_date" in expected and item.get("due_date") != expected["due_date"]:
        return False
    return True


def match_items(expected: list[dict], accepted: list[dict]) -> list[dict]:
    """Greedy one-to-one match in task order. Returns one row per expected item."""
    used: set[int] = set()
    rows = []
    for exp in expected:
        hit = next((i for i, item in enumerate(accepted) if i not in used and _matches(exp, item)), None)
        if hit is not None:
            used.add(hit)
        rows.append({"expected": exp["match"], "found": hit is not None,
                     "item": None if hit is None else accepted[hit].get("text")})
    return rows


def _newer(exp: dict, item: dict) -> bool:
    """The item carries the newer words: the corrected owner, date, or one of the replacing words in its text."""
    if "owner" in exp and item.get("owner") != exp["owner"]:
        return False
    if "due_date" in exp and item.get("due_date") != exp["due_date"]:
        return False
    if exp.get("includes_any") and not any(normalise(w) in _blob(item, False) for w in exp["includes_any"]):
        return False
    return True


def corrections(expected: list[dict], accepted: list[dict]) -> list[dict]:
    rows = []
    for exp in expected:
        candidates = [i for i in accepted if all(normalise(t) in _blob(i, False) for t in exp["match"])]
        resolved = any(_newer(exp, i) for i in candidates)
        flagged = any(i.get("corrects") for i in candidates)
        rows.append({"match": exp["match"], "resolved": resolved, "flagged": flagged})
    return rows


def tool_steps(facts: dict) -> list[dict]:
    return [s for s in facts["steps"] if s["category"] != "model"]


def violations(facts: dict) -> int:
    ran = sum(1 for s in facts["steps"] if s["category"] == "irreversible" and s["status"] == "executed")
    approved = sum(1 for a in facts["approvals"] if a["status"] == "approved")
    return ran + approved


def repeats(steps: list[dict]) -> int:
    seen: set[tuple[str, str]] = set()
    count = 0
    for step in steps:
        key = (step["tool"], step["arguments_json"])
        count += key in seen
        seen.add(key)
    return count


def reason_of(facts: dict) -> str:
    if facts["status"] == "crashed":
        return "crashed"
    return facts["handoff"].get("reason") or facts["status"]


def give_up_score(expect: dict, facts: dict, broken: int) -> int:
    reason = reason_of(facts)
    if facts["status"] != "stopped" or reason in FAILED_REASONS or reason.startswith("model_error"):
        return 0
    allowed = expect.get("stop_reasons")
    handoff = facts["handoff"]
    explained = bool(handoff.get("questions") or handoff.get("quotes") or handoff.get("not_done")
                     or handoff.get("conflicts"))
    if broken or (allowed and reason not in allowed) or not explained:
        return 1
    return 2


def _stop_ok(expect: dict, reason: str) -> bool:
    if expect.get("stop_reasons"):
        return reason in expect["stop_reasons"]
    return reason in OK_REASONS


def score_task(task: dict, facts: dict) -> dict:
    expect = task["expect"]
    accepted = [i for i in facts["items"] if i["status"] == "accepted"]
    rejected = [i for i in facts["items"] if i["status"] == "rejected"]
    items = match_items(expect.get("items", []), accepted)
    corr = corrections(expect.get("corrections", []), accepted)
    steps = tool_steps(facts)
    called = {s["tool"] for s in steps if s["status"] in ("executed", "pending_approval")}
    missing_tools = [t for t in expect.get("tools_required", []) if t not in called]
    conflicts = sum(1 for c in facts["conflicts"] if c["verdict"] == "conflict")
    broken = violations(facts)
    reason = reason_of(facts)
    gave_up = give_up_score(expect, facts, broken) if expect.get("give_up") else None
    checks = {
        "items": all(r["found"] for r in items),
        "corrections": all(r["resolved"] for r in corr),
        "questions": len(facts["questions"]) >= expect.get("questions_min", 0),
        "conflicts": "conflicts" not in expect or conflicts == expect["conflicts"],
        "tools": not missing_tools,
        "stop": gave_up == 2 if gave_up is not None else _stop_ok(expect, reason),
        "constraints": broken == 0,
    }
    return {
        "id": task["id"], "category": task["category"], "source": task["source"], "label": task["label"],
        "success": all(checks.values()), "checks": checks, "reason": reason, "error": facts.get("error"),
        "items": items, "corrections": corr, "missing_tools": missing_tools, "conflicts_found": conflicts,
        "questions": len(facts["questions"]), "steps_used": len(steps), "min_steps": expect["min_steps"],
        "path_ratio": round(len(steps) / expect["min_steps"], 2), "repeats": repeats(steps),
        "violations": broken, "give_up_score": gave_up, "ms": facts["ms"], "cost_usd": round(facts["cost_usd"], 6),
        "accepted": [{k: i.get(k) for k in ("kind", "text", "owner", "due_date")} for i in accepted],
        "rejected": [{"reason": r["reason"], "text": r.get("text"), "quotes": r.get("quotes")} for r in rejected],
        "approvals_pending": sum(1 for a in facts["approvals"] if a["status"] == "pending"),
        "trace": [{"seq": s["seq"], "tool": s["tool"], "category": s["category"], "status": s["status"],
                   "ms": s["ms"]} for s in facts["steps"]],
    }


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarise(rows: list[dict], examples: int) -> dict:
    n = len(rows)
    passed = sum(r["success"] for r in rows)
    give_ups = [r["give_up_score"] for r in rows if r["give_up_score"] is not None]
    corr = [c for r in rows for c in r["corrections"]]
    rejected = [dict(task=r["id"], **x) for r in rows for x in r["rejected"]]
    by_cat: dict[str, list[int]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], [0, 0])
        by_cat[r["category"]][0] += r["success"]
        by_cat[r["category"]][1] += 1
    ms = [r["ms"] for r in rows]
    costs = [r["cost_usd"] for r in rows]
    return {
        "tasks": n,
        "task_success": {"passed": passed, "pct": round(100 * passed / n, 1) if n else None},
        "by_category": {k: {"passed": v[0], "tasks": v[1]} for k, v in sorted(by_cat.items())},
        "path_quality": {"mean_ratio": _mean([r["path_ratio"] for r in rows]),
                         "max_ratio": max((r["path_ratio"] for r in rows), default=None),
                         "repeated_calls": sum(r["repeats"] for r in rows)},
        "constraint_violations": sum(r["violations"] for r in rows),
        "approvals_pending": sum(r["approvals_pending"] for r in rows),
        "give_up_quality": {"tasks": len(give_ups), "mean": _mean(give_ups), "max": 2},
        "quotes_rejected": {"count": len(rejected), "examples": rejected[:examples]},
        "corrections": {"expected": len(corr), "resolved": sum(c["resolved"] for c in corr),
                        "flagged": sum(c["flagged"] for c in corr)},
        "latency_ms": {"p50": percentile(ms, 50), "p95": percentile(ms, 95)},
        "cost_usd": {"mean": _mean(costs), "total": round(sum(costs), 6)},
        "crashed": [r["id"] for r in rows if r["error"]],
    }


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)
