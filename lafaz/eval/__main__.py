"""`python -m lafaz.eval`: run every task with the real model, save evals/results/<time>.json, write MEASURED.md.

--only id,id   run some tasks        --report FILE   rewrite MEASURED.md from a saved results file, no model calls
The model key is read from the environment variable named in config llm.key_env; it is never printed or stored.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..config import REPO_ROOT
from ..llm import LLM
from . import report, runner, score, tasks


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "lafaz", "config", "prompts", "evals/tasks"],
                               cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
        return (out.stdout.strip() or "unknown") + ("+uncommitted" if dirty else "")
    except OSError:
        return "unknown"


def run_all(chosen: list[dict], make_llm, workers: int) -> dict:
    cfg = config.settings()
    started = _now()
    with tempfile.TemporaryDirectory(prefix="lafaz-eval-") as tmp:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            facts = list(pool.map(lambda t: runner.run_task(t, Path(tmp), make_llm), chosen))
    rows = [score.score_task(t, f) for t, f in zip(chosen, facts)]
    return {
        "started": started, "finished": _now(), "commit": _commit(), "model": cfg["llm"]["model"],
        "effort": cfg["llm"]["effort"], "prices_source": config.prices().get("source", ""),
        "summary": score.summarise(rows, cfg["eval"]["rejected_examples"]), "tasks": rows,
    }


def save(result: dict, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (result["started"].replace(":", "").replace("-", "") + ".json")
    path.write_text(score.dumps(result) + "\n", encoding="utf-8")
    return path


def measured_path() -> Path:
    raw = Path(config.settings()["eval"]["measured_path"])
    return raw if raw.is_absolute() else REPO_ROOT / raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lafaz.eval")
    parser.add_argument("--only", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args(argv)
    if args.report:
        path = Path(args.report)
        report.write(json.loads(path.read_text(encoding="utf-8")), path, measured_path())
        return 0
    chosen = tasks.load(only=[x for x in args.only.split(",") if x] or None)
    if not os.environ.get(config.settings()["llm"]["key_env"]):
        print("eval: the model key is not set", file=sys.stderr)
        return 2
    result = run_all(chosen, LLM, config.settings()["eval"]["workers"])
    path = save(result, tasks.results_dir())
    report.write(result, path, measured_path())
    s = result["summary"]
    print(f"eval: {s['task_success']['passed']}/{s['tasks']} passed, constraint violations"
          f" {s['constraint_violations']}, USD {s['cost_usd']['total']} -> {path.name}")
    return 1 if s["constraint_violations"] else 0


if __name__ == "__main__":
    sys.exit(main())
