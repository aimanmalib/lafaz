"""Configuration loading. Values that may change live in config/*.json; code only reads them."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    return Path(os.environ.get("LAFAZ_CONFIG_DIR", REPO_ROOT / "config"))


def _read(name: str) -> dict:
    with open(config_dir() / name, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=None)
def settings() -> dict:
    return _read("lafaz.json")


@lru_cache(maxsize=None)
def tools() -> list[dict]:
    return _read("tools.json")["tools"]


@lru_cache(maxsize=None)
def samples() -> list[dict]:
    return _read("samples.json")["samples"]


@lru_cache(maxsize=None)
def listen() -> dict:
    return _read("listen.json")


@lru_cache(maxsize=None)
def memory() -> dict:
    return _read("memory.json")


@lru_cache(maxsize=None)
def prices() -> dict:
    return _read("prices.json")


@lru_cache(maxsize=None)
def mail() -> dict:
    return _read("mail.json")


@lru_cache(maxsize=None)
def board() -> dict:
    return _read("board.json")


@lru_cache(maxsize=None)
def voice() -> dict:
    return _read("voice.json")


def tool(name: str) -> dict:
    for entry in tools():
        if entry["name"] == name:
            return entry
    raise KeyError(name)


@lru_cache(maxsize=None)
def prompt(name: str) -> str:
    return (REPO_ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def messages(lang: str) -> dict[str, str]:
    return _read(f"i18n/{lang}.json")


def db_path() -> Path:
    raw = os.environ.get("LAFAZ_DB") or settings()["app"]["db_path_default"]
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def clear_cache() -> None:
    for fn in (settings, tools, samples, messages, listen, memory, prices, mail, board, voice, prompt):
        fn.cache_clear()
