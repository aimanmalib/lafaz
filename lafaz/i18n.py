"""Interface text lookup. All copy lives in config/i18n/<lang>.json with identical keys."""

from __future__ import annotations

from . import config


def languages() -> list[str]:
    return list(config.settings()["app"]["languages"])


def default_lang() -> str:
    return config.settings()["app"]["default_lang"]


def pick(requested: str | None, cookie: str | None) -> str:
    """Query parameter wins, then the cookie, then the configured default."""
    for candidate in (requested, cookie):
        if candidate in languages():
            return candidate
    return default_lang()


class Translator:
    def __init__(self, lang: str):
        self.lang = lang
        self._messages = config.messages(lang)
        self._fallback = config.messages(default_lang())

    def has(self, key: str) -> bool:
        return key in self._messages or key in self._fallback

    def term(self, prefix: str, code: object) -> str:
        """Text for a stored code such as a trace status; an unknown code is shown as it was stored."""
        code = str(code)
        key = prefix + code.split(":", 1)[0]
        return self(key) if self.has(key) else code

    def __call__(self, key: str, **params: object) -> str:
        text = self._messages.get(key) or self._fallback.get(key) or key
        for name, value in params.items():
            text = text.replace("{" + name + "}", str(value))
        return text
