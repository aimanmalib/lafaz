import pytest

from fakes import FakeClient, response, tool_use
from lafaz import config
from lafaz.llm import LLM, LLMError, api_tool, estimate_cost


def test_request_follows_config_and_api_rules():
    body = LLM(FakeClient()).request("sys", "hello", "record_items")
    cfg = config.settings()["llm"]
    assert body["model"] == cfg["model"]
    assert body["max_tokens"] == cfg["max_tokens"]
    assert body["output_config"] == {"effort": cfg["effort"]}
    assert body["tool_choice"] == {"type": "auto"}  # forced tool_choice is rejected by the model
    assert "thinking" not in body and "temperature" not in body
    assert body["tools"][0]["strict"] is True


def test_strict_schema_closes_every_object():
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(api_tool("record_items")["input_schema"])


def test_tool_input_comes_back_as_a_dict_with_usage_and_cost():
    fake = FakeClient(response([tool_use("record_items", {"items": [], "questions": []})], tokens=(1000, 100)))
    call = LLM(fake).call_tool("sys", "hi", "record_items")
    assert call.input == {"items": [], "questions": []}
    assert (call.tokens_in, call.tokens_out) == (1000, 100)
    assert call.cost_usd == estimate_cost(call.model, 1000, 100)


@pytest.mark.parametrize(
    "resp, code",
    [
        (response([], stop_reason="max_tokens"), "max_tokens"),
        (response([], stop_reason="end_turn"), "no_tool_call"),
        (response([tool_use("other_tool", {})]), "no_tool_call"),
    ],
)
def test_unusable_responses_raise_named_errors(resp, code):
    with pytest.raises(LLMError) as err:
        LLM(FakeClient(resp)).call_tool("sys", "hi", "record_items")
    assert err.value.code == code


def test_unknown_model_costs_nothing_rather_than_a_made_up_number():
    assert estimate_cost("no-such-model", 1000, 1000) == 0.0
