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
def messages(lang: str) -> dict[str, str]:
    return _read(f"i18n/{lang}.json")


def db_path() -> Path:
    raw = os.environ.get("LAFAZ_DB") or settings()["app"]["db_path_default"]
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def clear_cache() -> None:
    for fn in (settings, tools, samples, messages):
        fn.cache_clear()
