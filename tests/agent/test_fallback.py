import json
import os
from functools import partial
from pathlib import Path

from fastapi.testclient import TestClient

from app import runner
from app.agent import loop
from app.main import app
from tests.agent.test_loop import Counter, parse, read_grid
from tests.fakes.fake_app import FakeSession
from tests.fakes.llm import FakeLLM
from tests.test_main import AUTH, _wait

NAV = {("inicio", "Cartera"): "menu-cartera", ("menu-cartera", "Facturas"): "facturas"}
TASK = "¿Cuántas facturas vencidas hay?"
READ = parse({"op": "read", "entity": "facturas", "where": {"Estado": "Vencida"}, "aggregate": "count"})
LEARN = [("click_text", {"label": "Cartera"}), ("click_text", {"label": "Facturas"})]


def run(monkeypatch, fixtures_dir, memory, *replies):
    """POST the task to the entrypoint on a FakeSession at Inicio; returns (status, events, session, llm)."""
    session = FakeSession("inicio", NAV, fixtures_dir / "elements")
    llm = FakeLLM(*replies)

    async def fake_open(url, password):
        return session

    monkeypatch.setattr(runner, "open_session", fake_open)
    monkeypatch.setattr(runner, "run_task", partial(loop.run_task, llm=llm, memory=memory, perceive=Counter(session),
                                                    read_grid=read_grid(session)))
    with TestClient(app) as c:
        body = {"task": TASK, "desktop": {"url": "wss://desktop.example/ws", "password": "x"}}
        task_id = c.post("/tasks", json=body, headers=AUTH).json()["task_id"]
        status = _wait(c, task_id)
    lines = (Path(os.environ["LOG_DIR"]) / f"{task_id}.jsonl").read_text("utf-8").splitlines()
    return status, [json.loads(x) for x in lines], session, llm


def stored(memory: Path) -> dict:
    return json.loads(next(memory.glob("*/*/map.json")).read_text("utf-8"))


def test_an_unseen_app_is_learned_by_the_agent_loop_and_the_procedure_stored(monkeypatch, fixtures_dir, tmp_path):
    memory = tmp_path / "memory"
    status, events, session, _ = run(monkeypatch, fixtures_dir, memory, READ, LEARN,
                                       [("done", {"answer": "1"})], {"text": "respuesta: 1", "data": {"respuesta": 1}})

    assert (status["status"], status["summary"]) == ("terminada", "respuesta: 1")
    assert session.screen == "facturas"
    assert [(s["tool"], s["args"]) for s in events if s["event"] == "step"] == [
        ("click_text", ["Cartera"]), ("click_text", ["Facturas"])]
    procs = [p for p in stored(memory)["procedures"] if (p["op"], p["entity"]) == ("read", "facturas")]
    assert [(s["tool"], s["args"]) for s in procs[0]["steps"]] == [("click_text", ["Cartera"]), ("click_text", ["Facturas"])]


def test_the_second_run_of_the_learned_task_goes_through_the_executor(monkeypatch, fixtures_dir, tmp_path):
    memory = tmp_path / "memory"
    run(monkeypatch, fixtures_dir, memory, READ, LEARN, [("done", {"answer": "1"})], {"text": "respuesta: 1"})

    status, events, _, llm = run(monkeypatch, fixtures_dir, memory, READ, {"text": "respuesta: 1"})
    assert status["status"] == "terminada" and len(llm.calls) == 2  # parse and summary, no planner turn
    assert not any(e["event"] == "handoff" for e in events)
    assert '"answer": 1' in llm.calls[1]["messages"][-1]["content"]  # counted by SQL over the page it navigated to


def test_a_batch_stops_at_its_first_failed_effect(monkeypatch, fixtures_dir, tmp_path):
    status, events, session, llm = run(monkeypatch, fixtures_dir, tmp_path / "memory", READ,
                                       [("click_text", {"label": "Zzzz"}), *LEARN], [("done", {"answer": "?"})],
                                       {"text": "No se encontró Zzzz"})

    assert [(s["tool"], s["args"], s["outcome"]) for s in events if s["event"] == "step"] == [
        ("click_text", ["Zzzz"], "fail")]
    assert session.clicks == [] and session.screen == "inicio"
    results = [m["content"] for m in llm.calls[2]["messages"] if m["role"] == "tool"]
    assert results[0].startswith("failed") and all(r.startswith("not run") for r in results[1:]) and len(results) == 3
