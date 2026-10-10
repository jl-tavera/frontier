"""Fake model clients for every F ticket. Offline: no network, no model ids read.

`FakeLLM(*replies)` stands in for `openai.AsyncOpenAI` pointed at OpenRouter: each `chat.completions.create` call
pops the next reply and returns a real OpenAI-style `ChatCompletion`. A reply is a str (the `content`), a dict
(JSON-encoded `content`) or a list of `(name, args)` pairs (`tool_calls`). Every call's kwargs land in `.calls`.

`FakeDecide(*answers)` stands in for `app.agent.llm.decide`: each call pops the next `{name: (answer, confidence)}`."""
import json
from types import SimpleNamespace
from typing import Any

from openai.types.chat import ChatCompletion


class FakeLLM:
    def __init__(self, *replies: str | dict | list[tuple[str, dict]]):
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw) -> ChatCompletion:
        self.calls.append(kw)
        assert self.replies, f"FakeLLM ran out of scripted replies at call {len(self.calls)}"
        reply = self.replies.pop(0)
        message: dict[str, Any] = {"role": "assistant", "content": None}
        if isinstance(reply, list):
            message["tool_calls"] = [
                {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
                for i, (name, args) in enumerate(reply)
            ]
        else:
            message["content"] = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return ChatCompletion.model_validate({
            "id": f"fake-{len(self.calls)}", "object": "chat.completion", "created": 0, "model": kw.get("model", ""),
            "choices": [{"index": 0, "finish_reason": "tool_calls" if isinstance(reply, list) else "stop", "message": message}],
        })


class FakeDecide:
    def __init__(self, *answers: dict[str, tuple[Any, float]]):
        self.answers = list(answers)
        self.calls: list[tuple[Any, dict]] = []

    async def __call__(self, state, questions, **_) -> dict[str, tuple[Any, float]]:
        self.calls.append((state, questions))
        assert self.answers, f"FakeDecide ran out of scripted answers at call {len(self.calls)}"
        return self.answers.pop(0)
