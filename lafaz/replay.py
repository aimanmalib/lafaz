"""Replay mode (PRD 4.10): a stored model run played back through the same code.

A cassette holds the model's responses for one sample, recorded once with a real key. Replaying it hands those
responses to the real loop: the quote checker, date resolver, permission gate, approvals and actions all run as
they do live. Only the model's turns come from the recording, and the run is labelled 'replay'.

A cassette plays only for the exact text and meeting date it was recorded for. Edited text cannot be replayed,
because the model never saw it.

Record:  python -m lafaz.replay record <sample-id>   (needs the model key; writes the file named in the sample)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from . import config
from .config import REPO_ROOT
from .llm import LLM, LLMError

KEPT_BLOCKS = ("text", "tool_use", "thinking")


def normalise(text: str) -> str:
    """Browsers submit textarea line breaks as CRLF; the recording and the check use LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def fingerprint(text: str, meeting_date: str) -> str:
    return hashlib.sha256(f"{meeting_date}\n{normalise(text)}".encode("utf-8")).hexdigest()


def _block(b) -> dict | None:
    kind = getattr(b, "type", None)
    if kind == "text":
        return {"type": "text", "text": b.text}
    if kind == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    if kind == "thinking":  # thinking text is not kept; the block only keeps the turn's shape
        return {"type": "thinking", "thinking": "", "signature": ""}
    return None


def _tools(body: dict) -> list[str]:
    return sorted(t["name"] for t in body.get("tools", []))


def _results(body: dict) -> dict:
    """Tool results the request carries back to the model, by tool_use id."""
    last = (body.get("messages") or [{}])[-1]
    content = last.get("content") if last.get("role") == "user" else None
    out = {}
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            try:
                out[block["tool_use_id"]] = json.loads(block.get("content") or "{}")
            except ValueError:
                continue
    return out


def _ids(data: dict):
    """(namespace, value) pairs for every *_id / *_ids field: task_id and task_ids share the 'task' namespace."""
    for key, value in data.items():
        if key.endswith("_id") and isinstance(value, int):
            yield key[:-3], [value]
        elif key.endswith("_ids") and isinstance(value, list):
            yield key[:-4], [v for v in value if isinstance(v, int)]


def _learn(mapping: dict, recorded: dict, actual: dict) -> None:
    for use_id, was in recorded.items():
        now = dict(_ids(actual.get(use_id) or {}))
        for space, values in _ids(was):
            for old, new in zip(values, now.get(space, [])):
                mapping[(space, old)] = new


def _remap(mapping: dict, data: dict) -> dict:
    out = dict(data)
    for key, value in data.items():
        if key.endswith("_id") and isinstance(value, int):
            out[key] = mapping.get((key[:-3], value), value)
        elif key.endswith("_ids") and isinstance(value, list):
            out[key] = [mapping.get((key[:-4], v), v) for v in value]
    return out


class RecordingClient:
    """Wraps a real client and keeps every response in call order."""

    def __init__(self, inner):
        self.inner = inner
        self.turns: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **body):
        response = self.inner.beta.messages.create(**body)
        self.turns.append({
            "tools": _tools(body),
            "results": _results(body),
            "stop_reason": response.stop_reason,
            "model": getattr(response, "model", None) or body.get("model"),
            "content": [blk for blk in map(_block, response.content) if blk],
        })
        return response


class ReplayClient:
    """Answers each request with the next recorded response for the same tool set.

    Rows created during the replay get new ids (task 1 in the recording may be task 57 here). The ids the model saw
    in recorded tool results are matched with the ids this run's results carry, and the model's later tool inputs
    are rewritten to match, so a recorded answer never points at another run's rows.

    A request the recording has no answer for (a conflict found against memory the recording did not have) fails
    with a stable code, which the loop stores like any other model error.
    """

    def __init__(self, turns: list[dict]):
        self.turns = [dict(t) for t in turns]
        self.mapping: dict = {}
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _block(self, blk: dict) -> SimpleNamespace:
        if blk["type"] == "tool_use":
            return SimpleNamespace(**{**blk, "input": _remap(self.mapping, blk["input"])})
        return SimpleNamespace(**blk)

    def _create(self, **body):
        wanted = _tools(body)
        for i, turn in enumerate(self.turns):
            if turn["tools"] == wanted:
                self.turns.pop(i)
                _learn(self.mapping, turn.get("results") or {}, _results(body))
                return SimpleNamespace(
                    content=[self._block(blk) for blk in turn["content"]],
                    stop_reason=turn["stop_reason"], model=turn.get("model") or body.get("model"),
                    usage=SimpleNamespace(input_tokens=0, output_tokens=0), stop_details=None,
                )
        raise LLMError("replay_unrecorded", ",".join(wanted))


def _path(sample: dict) -> Path | None:
    raw = sample.get("replay")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def load(sample: dict) -> dict | None:
    path = _path(sample)
    if path is None or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def find(text: str, meeting_date: date) -> dict | None:
    """The cassette recorded for exactly this text and date, if there is one."""
    want = fingerprint(text, meeting_date.isoformat())
    for sample in config.samples():
        cassette = load(sample)
        if cassette and cassette.get("fingerprint") == want:
            return cassette
    return None


def llm_for(cassette: dict) -> LLM:
    return LLM(client=ReplayClient(cassette["turns"]))


def _commit() -> str:
    out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True)
    return out.stdout.strip() or "unknown"


def record(sample: dict, workdir: Path) -> dict:
    """Run the sample once with the real model on an empty database and return the cassette."""
    os.environ["LAFAZ_DB"] = str(workdir / "record.db")
    from . import db
    from .agent import loop

    db.init()
    llm = LLM()
    recorder = RecordingClient(llm.client)
    llm._client = recorder
    conn = db.connect()
    try:
        day = date.fromisoformat(sample["meeting_date"])
        text = normalise(sample["text"])
        run_id = loop.start_run(conn, text, day, "sample", "en")
        outcome = loop.run(conn, run_id, text, day, llm=llm)
    finally:
        conn.close()
    return {
        "sample": sample["id"],
        "recorded": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _commit(),
        "meeting_date": sample["meeting_date"],
        "fingerprint": fingerprint(sample["text"], sample["meeting_date"]),
        "outcome": {"status": outcome["status"], "reason": outcome.get("reason")},
        "turns": recorder.turns,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "record":
        print("usage: python -m lafaz.replay record <sample-id>", file=sys.stderr)
        return 2
    sample = next((s for s in config.samples() if s["id"] == args[1]), None)
    if sample is None or _path(sample) is None:
        print(f"replay: no sample {args[1]!r} with a replay path in config/samples.json", file=sys.stderr)
        return 2
    if not os.environ.get(config.settings()["llm"]["key_env"]):
        print("replay: the model key is not set", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="lafaz-record-") as tmp:
        cassette = record(sample, Path(tmp))
    path = _path(sample)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cassette, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"replay: {len(cassette['turns'])} turns, outcome {cassette['outcome']} -> {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
