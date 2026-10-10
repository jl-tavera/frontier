import pytest
from typesafe_sdk import Choice, ChoiceAnswer, Noul, NoulAnswer

from app.agent.llm import decide, model
from tests.fakes.llm import FakeLLM

QUESTIONS = {
    "target": Choice(instructions="Which element is the old 'Facturas' button?", criteria={"7": "Facturación", "9": "Cartera"}),
    "effect_ok": Noul(instructions="Did the click open the invoices list?"),
}


async def test_decide_without_a_jev_key_asks_the_fast_model_and_returns_its_confidence(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    llm = FakeLLM({"target": {"answer": "7", "confidence": 0.86}, "effect_ok": {"answer": True, "confidence": 0.9}})

    answers = await decide({"screen": "facturas"}, QUESTIONS, llm=llm)

    assert answers == {"target": ("7", 0.86), "effect_ok": (True, 0.9)}
    [call] = llm.calls
    assert call["model"] == "test/fast"
    assert call["response_format"] == {"type": "json_object"}


class FakeJev:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def system_one(self, state, questions, **kw):
        self.calls.append((state, questions, kw))
        return type("R", (), {"answers": self.answers})()


async def test_decide_with_a_jev_key_asks_every_question_in_one_jev_call(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-jev")
    jev = FakeJev({"target": ChoiceAnswer(choice="7", confidence=0.9, probabilities={"7": 0.9, "9": 0.1}),
                   "effect_ok": NoulAnswer(noul=0.2)})

    answers = await decide({"screen": "facturas"}, QUESTIONS, jev=jev, llm=FakeLLM())

    assert answers == {"target": ("7", 0.9), "effect_ok": (False, 0.8)}
    [(_, questions, kw)] = jev.calls
    assert set(questions) == {"target", "effect_ok"} and kw["model"] == "jev-latest"


@pytest.mark.parametrize("var", ["MODEL_FAST", "MODEL_VLM", "MODEL_PLANNER"])
def test_a_missing_model_variable_raises_naming_it(monkeypatch, var):
    monkeypatch.delenv(var)

    with pytest.raises(RuntimeError, match=var):
        model(var.removeprefix("MODEL_").lower())


async def test_a_question_the_fast_model_leaves_out_comes_back_unsure(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    llm = FakeLLM({"target": {"answer": "7", "confidence": 0.86}, "effect_ok": "sí"})

    answers = await decide({"screen": "facturas"}, QUESTIONS, llm=llm)

    assert answers == {"target": ("7", 0.86), "effect_ok": (None, 0.0)}
