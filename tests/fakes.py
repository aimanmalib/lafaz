"""A stand-in for the Anthropic client. It records each request and returns a scripted response."""

from types import SimpleNamespace


def tool_use(name, payload):
    return SimpleNamespace(type="tool_use", id="toolu_fake", name=name, input=payload)


def response(content, stop_reason="tool_use", model="claude-sonnet-5-5", tokens=(1000, 200), stop_details=None):
    usage = SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1])
    return SimpleNamespace(content=content, stop_reason=stop_reason, model=model, usage=usage, stop_details=stop_details)


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **body):
        self.requests.append(body)
        return self.responses.pop(0)
