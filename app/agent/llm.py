"""Model clients. Every LLM call goes through OpenRouter with the `openai` SDK, never the Anthropic SDK.

Three tiers read from env: MODEL_FAST, MODEL_VLM, MODEL_PLANNER. Pass `llm=` (any AsyncOpenAI-like object) to
swap the client; tests pass `tests.fakes.llm.FakeLLM`."""
import json
import os
from contextlib import nullcontext
from functools import cache
from typing import Any, Literal

from openai import AsyncOpenAI
from typesafe_sdk import AsyncTypeSafeClient

OPENROUTER_URL = "https://openrouter.ai/api/v1"
JEV_MODEL = "jev-latest"
Tier = Literal["fast", "vlm", "planner"]


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set; add it to .env (see .env.example)")
    return value


def model(tier: Tier) -> str:
    return env(f"MODEL_{tier.upper()}")


@cache
def openrouter() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=OPENROUTER_URL, api_key=env("OPENROUTER_API_KEY"))


async def chat_json(tier: Tier, messages: list[dict], llm=None) -> Any:
    """One JSON-mode call on `tier`; returns the parsed content. Raises ValueError when it isn't JSON."""
    resp = await (llm or openrouter()).chat.completions.create(
        model=model(tier), messages=messages, response_format={"type": "json_object"})
    return json.loads(resp.choices[0].message.content or "")


async def decide(state: Any, questions: dict, *, llm=None, jev=None) -> dict[str, tuple[Any, float]]:
    """Jev (System 1) answers typed questions: every Choice / Noul / Score in one `system_one` call.
    Returns {name: (answer, confidence)}: choice → label, noul → bool, score → expected score.
    Without TYPESAFE_API_KEY the same questions go to MODEL_FAST in JSON mode; a name it leaves out or garbles
    comes back as (None, 0.0), below any confidence gate."""
    if os.environ.get("TYPESAFE_API_KEY", "").strip():
        async with nullcontext(jev) if jev else AsyncTypeSafeClient(model=JEV_MODEL) as client:
            return _jev_answers(await client.system_one(state, questions, model=JEV_MODEL))
    return await _decide_fast(state, questions, llm)


def _jev_answers(resp) -> dict[str, tuple[Any, float]]:
    out = {}
    for name, answer in resp.answers.items():
        if answer.type == "noul":
            out[name] = (answer.noul >= 0.5, max(answer.noul, 1 - answer.noul))
        else:
            out[name] = (answer.choice if answer.type == "choice" else answer.score, answer.confidence)
    return out


DECIDE_SYSTEM = """Answer each typed question about the state. Reply with JSON only:
{"<name>": {"answer": <answer>, "confidence": <0..1>}} for every question name.
choice: answer is one of the criteria keys. noul: answer is true or false. score: answer is the criteria index (0-based)."""


async def _decide_fast(state: Any, questions: dict, llm) -> dict[str, tuple[Any, float]]:
    qs = {n: q if isinstance(q, dict) else q.model_dump() for n, q in questions.items()}
    user = json.dumps({"state": state, "questions": qs}, ensure_ascii=False, default=str)
    out = await chat_json("fast", [{"role": "system", "content": DECIDE_SYSTEM}, {"role": "user", "content": user}], llm)
    answers = {}
    for n in questions:
        try:
            answers[n] = (out[n]["answer"], float(out[n]["confidence"]))
        except (KeyError, TypeError, ValueError):
            answers[n] = (None, 0.0)
    return answers
