"""Thin adapter over the Anthropic Messages API for single tool calls.

Choices recorded in docs/DECISIONS.md (D3, D7): the model, effort, token cap and timeout come from config/lafaz.json;
forced tool_choice is rejected by the configured model, so the request uses tool_choice auto, a strict schema and a
prompt that names the tool. stop_reason is checked before any content is read. Tests pass a fake client.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import config

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """The model did not return a usable tool call. `code` is stable and shown in the trace."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass
class ToolCall:
    name: str
    input: dict
    model: str
    ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


def api_tool(name: str) -> dict:
    """The tool definition sent to the API, built from config/tools.json."""
    entry = config.tool(name)
    return {
        "name": entry["name"],
        "description": entry["description"],
        "input_schema": entry["input_schema"],
        "strict": True,
    }


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price = config.prices()["models"].get(model)
    if not price:
        return 0.0
    return round((tokens_in * price["input"] + tokens_out * price["output"]) / 1_000_000, 6)


def default_client():
    import anthropic  # imported here so tests and pages never need a key

    return anthropic.Anthropic(timeout=config.settings()["llm"]["timeout_s"])


@dataclass
class Turn:
    """One model turn inside the agent loop. `content` goes back into the conversation unchanged."""

    content: list
    tool_uses: list
    stop_reason: str
    model: str
    ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


def _usage(response, model: str) -> tuple[int, int, float]:
    usage = getattr(response, "usage", None)
    tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
    tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
    return tokens_in, tokens_out, estimate_cost(model, tokens_in, tokens_out)


class LLM:
    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = default_client()
        return self._client

    def request(self, system: str, user_text: str, tool_name: str) -> dict:
        return self.request_messages(system, [{"role": "user", "content": user_text}], [tool_name])

    def request_messages(self, system: str, messages: list, tool_names: list[str]) -> dict:
        cfg = config.settings()["llm"]
        body = {
            "model": cfg["model"],
            "max_tokens": cfg["max_tokens"],
            "system": system,
            "messages": messages,
            "tools": [api_tool(name) for name in tool_names],
            "tool_choice": {"type": "auto"},
            "output_config": {"effort": cfg["effort"]},
        }
        if cfg.get("fallbacks"):
            body["betas"] = [FALLBACK_BETA]
            body["fallbacks"] = cfg["fallbacks"]
        return body

    def _send(self, body: dict):
        """Send one request; stop_reason is checked before any content is read."""
        started = time.monotonic()
        response = self.client.beta.messages.create(**body)
        ms = int((time.monotonic() - started) * 1000)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMError("refusal", getattr(details, "category", None) or "")
        if response.stop_reason == "max_tokens":
            raise LLMError("max_tokens")
        model = getattr(response, "model", None) or body["model"]
        return response, model, ms, _usage(response, model)

    def call_tool(self, system: str, user_text: str, tool_name: str) -> ToolCall:
        response, model, ms, (tokens_in, tokens_out, cost) = self._send(self.request(system, user_text, tool_name))
        block = next(
            (b for b in response.content if getattr(b, "type", None) == "tool_use" and b.name == tool_name),
            None,
        )
        if block is None:
            raise LLMError("no_tool_call", response.stop_reason or "")
        if not isinstance(block.input, dict):
            raise LLMError("bad_tool_input", type(block.input).__name__)
        return ToolCall(name=tool_name, input=block.input, model=model, ms=ms, tokens_in=tokens_in,
                        tokens_out=tokens_out, cost_usd=cost)

    def converse(self, system: str, messages: list, tool_names: list[str]) -> Turn:
        """One turn of a manual tool loop. The caller appends `content` unchanged (thinking blocks included)."""
        body = self.request_messages(system, messages, tool_names)
        response, model, ms, (tokens_in, tokens_out, cost) = self._send(body)
        uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        return Turn(content=list(response.content), tool_uses=uses, stop_reason=response.stop_reason or "",
                    model=model, ms=ms, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost)
