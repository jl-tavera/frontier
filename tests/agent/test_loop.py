import asyncio
import json
import os
from functools import partial
from itertools import groupby
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import runner
from app.agent import loop
from app.contracts import Target
from app.main import app
from app.memory.appmap import AppMap
from app.memory.fingerprint import cell, fingerprint
from app.perception.grid import Grid
from app.sync.cache import Cache
from tests.fakes.fake_app import FakeSession
from tests.fakes.llm import FakeLLM
from tests.test_main import AUTH, _wait

V39 = "SIGECOM · Distribuidora Andina   v3.9"
NAV = {("inicio", "Herramientas"): "menu-herramientas", ("menu-herramientas", "Bitácora de cambios"): "bitacora",
       ("inicio", "Comercial"): "menu-comercial", ("menu-comercial", "Clientes"): "clientes",
       ("clientes", "Nuevo"): "cliente-nuevo", ("cliente-nuevo", "Guardar"): "clientes",
       ("clientes", "Herramientas"): "menu-herramientas", ("bitacora", "Comercial"): "menu-comercial"}
CREATE_CLIENTE = {"op": "create", "entity": "clientes", "task_text": "crear cliente", "steps": [
    {"tool": "go_to", "args": ["clientes"]},
    {"tool": "click_text", "args": ["Nuevo"], "expect": "cliente-nuevo"},
    {"tool": "fill_field", "args": ["NIT", "$NIT"]},
    {"tool": "fill_field", "args": ["Nombre", "$Nombre"]},
    {"tool": "click_text", "args": ["Guardar"], "expect": "clientes"}]}
FACTURAS = [{"Código": f"FV-{i}", "Cliente": "Comercial Ruiz", "Valor": 1000 * i, "Estado": e}
            for i, e in enumerate(["Vencida", "Pagada", "Vencida"], 1)]


def read_grid(session):
    """The fake app's grid reader. Its backend: a saved form shows as a new Clientes row and a change-log entry."""
    def read(fb):
        heads = sorted((e for e in session.elements if e.kind == "header"), key=lambda e: e.bbox[0])
        rows: dict[int, dict] = {}
        for e in session.elements:
            if heads and e.kind in ("cell", "link") and e.bbox[1] > heads[0].bbox[3]:
                rows.setdefault(e.bbox[1], {})[[h for h in heads if h.bbox[0] <= e.bbox[0]][-1].text] = e.text
        rows = list(rows.values())
        if session.typed and session.screen == "clientes":
            rows.append(dict(zip(["NIT", "Nombre"], session.typed)))
        if session.typed and session.screen == "bitacora":
            rows.insert(0, {"Fecha": "14/10/2026", "Usuario": "operador", "Acción": "Creó cliente"})
        return Grid([h.text for h in heads], rows)
    return read


class Counter:
    """A perceive that counts its calls (rec_calls) and answers with the session's elements."""

    def __init__(self, session):
        self.session, self.calls = session, 0

    def __call__(self, fb):
        self.calls += 1
        return self.session.elements


@pytest.fixture
def memory(fixtures_dir, tmp_path):
    """A SIGECOM map (snapshots, crops, edge xy, one create procedure) and a cache with Facturas and the change log."""
    d, mem = fixtures_dir / "elements", tmp_path / "memory"
    m = AppMap.load(mem, V39)
    for name in {*(s for s, _ in NAV), *NAV.values(), "facturas"}:
        s = FakeSession(name, {}, d)
        m.upsert_node(fingerprint(s.elements, s.w, s.h), s.elements, s.fb, name)
    for (src, label), to in NAV.items():
        s = FakeSession(src, {}, d)
        e = next(e for e in s.elements if e.text == label)
        m.upsert_edge(src, "click", Target(label, e.kind, cell(e.bbox, s.w, s.h)),
                      ((e.bbox[0] + e.bbox[2]) // 2, (e.bbox[1] + e.bbox[3]) // 2), to)
    m.procedures.append(CREATE_CLIENTE)
    m.save()

    bitacora = FakeSession("bitacora", {}, d)
    probes = {"facturas": (3, "facturas-p1"), "bitacora": loop.page_probe(read_grid(bitacora)(bitacora.fb))}
    cache = Cache(m.app_id, probes.get, path=mem / "cache.sqlite")
    cache.acquire("facturas", lambda: FACTURAS, key="Código")
    cache.register_changelog("bitacora")
    cache.db.close()
    return mem


def run(monkeypatch, fixtures_dir, memory, task, *replies, fallback=None):
    """POST the task to the entrypoint on a FakeSession at Inicio; returns (status, events, session, perceive, llm)."""
    session = FakeSession("inicio", NAV, fixtures_dir / "elements")
    perceive, llm = Counter(session), FakeLLM(*replies)

    async def fake_open(url, password):
        return session

    kw = {"fallback": fallback} if fallback else {}
    monkeypatch.setattr(runner, "open_session", fake_open)
    monkeypatch.setattr(runner, "run_task", partial(loop.run_task, llm=llm, memory=memory, perceive=perceive,
                                                    read_grid=read_grid(session), **kw))
    with TestClient(app) as c:
        body = {"task": task, "desktop": {"url": "wss://desktop.example/ws", "password": "x"}}
        task_id = c.post("/tasks", json=body, headers=AUTH).json()["task_id"]
        status = _wait(c, task_id)
    lines = (Path(os.environ["LOG_DIR"]) / f"{task_id}.jsonl").read_text("utf-8").splitlines()
    return status, [json.loads(x) for x in lines], session, perceive, llm


def parse(*queries, confidence=0.95):
    return {"queries": list(queries), "confidence": confidence}


def test_a_lookup_answers_from_sql_with_two_llm_calls_and_a_change_log_hit(monkeypatch, fixtures_dir, memory):
    status, events, _, perceive, llm = run(
        monkeypatch, fixtures_dir, memory, "¿Cuántas facturas vencidas hay?",
        parse({"op": "read", "entity": "facturas", "where": {"Estado": "Vencida"}, "aggregate": "count"}),
        {"text": "respuesta: 2", "data": {"respuesta": 2}})

    assert (status["status"], status["summary"], status["data"]) == ("terminada", "respuesta: 2", {"respuesta": 2})
    assert len(llm.calls) == 2 and perceive.calls == 0
    assert '"answer": 2' in llm.calls[1]["messages"][-1]["content"]  # the SQL count reached the summary
    assert any(e["event"] == "sync.probe" and (e["scope"], e["outcome"]) == ("changelog", "hit") for e in events)


def test_a_create_replays_the_procedure_and_writes_the_saved_row_through(monkeypatch, fixtures_dir, memory):
    status, events, session, perceive, llm = run(
        monkeypatch, fixtures_dir, memory, "Crea el cliente Ferretería Sur con NIT 900555111-2",
        parse({"op": "create", "entity": "clientes", "fields": {"NIT": "900555111-2", "Nombre": "Ferretería Sur"}}),
        {"text": "Cliente creado", "data": {}})

    assert status["status"] == "terminada" and len(llm.calls) == 2 and perceive.calls == 0
    assert session.typed == ["900555111-2", "Ferretería Sur"] and session.screen == "bitacora"  # watermark re-read
    cache = Cache("SIGECOM · Distribuidora Andina", None, path=memory / "cache.sqlite")
    rows = cache.query("SELECT source, json_extract(data_json, '$.Nombre') FROM rows WHERE entity = 'clientes'")
    assert rows == [("write-through", "Ferretería Sur")]

    steps = [e for e in events if e["event"] == "step"]
    assert [(s["tool"], s["args"][0]) for s in steps] == [
        ("go_to", "clientes"), ("click_text", "Nuevo"), ("fill_field", "NIT"), ("fill_field", "Nombre"),
        ("click_text", "Guardar"), ("go_to", "clientes"), ("go_to", "bitacora")]
    assert all({"tool", "args", "screen_id", "diff", "outcome"} <= s.keys() and s["outcome"] == "ok" for s in steps)


def test_an_entity_with_no_procedure_hands_off_to_the_fallback_once(monkeypatch, fixtures_dir, memory):
    calls = []

    async def fallback(task, plan, ex):
        calls.append([q.entity for q in plan.queries])
        return {"ok": True, "answer": "PD-2042"}

    status, *_ = run(monkeypatch, fixtures_dir, memory, "Crea un pedido para Ruiz",
                     parse({"op": "create", "entity": "pedidos", "fields": {"Cliente": "Comercial Ruiz"}}),
                     {"text": "Pedido PD-2042 creado", "data": {}}, fallback=fallback)
    assert calls == [["pedidos"]] and status["status"] == "terminada"


def test_a_task_that_never_finishes_is_cut_and_still_summarised(monkeypatch, fixtures_dir, memory):
    async def never(task, plan, ex):
        await asyncio.sleep(30)

    monkeypatch.setattr(runner, "BUDGET_S", 0.3)
    status, *_ = run(monkeypatch, fixtures_dir, memory, "Crea un pedido para Ruiz",
                     parse({"op": "create", "entity": "pedidos", "fields": {"Cliente": "Comercial Ruiz"}}),
                     {"text": "No se creó el pedido: se agotó el tiempo", "data": {}}, fallback=never)
    assert status["status"] == "fallida" and status["summary"]
    assert "no terminó a tiempo" not in status["summary"]  # the run's own summary, not the runner's guard text


VENCIDAS = {"op": "read", "entity": "facturas", "where": {"Estado": "Vencida"}, "aggregate": "count"}
PAGADAS = {"op": "read", "entity": "facturas", "where": {"Estado": "Pagada"}, "aggregate": "count"}


def summarised(llm) -> list[dict]:
    return json.loads(llm.calls[-1]["messages"][-1]["content"])["results"]


def test_cache_answers_go_first_and_a_hand_off_gets_only_the_unrun_queries(monkeypatch, fixtures_dir, memory):
    calls = []

    async def fallback(task, plan, ex):
        calls.append([(q.op, q.entity) for q in plan.queries])
        return {"ok": False, "reason": "sin pedidos"}

    _, _, _, _, llm = run(monkeypatch, fixtures_dir, memory, "Vencidas, actualiza C-1 y pagadas",
                          parse(VENCIDAS, {"op": "update", "entity": "clientes", "key": "C-1", "fields": {}}, PAGADAS),
                          {"text": "respuesta: 2; 1", "data": {}}, fallback=fallback)
    assert calls == [[("update", "clientes")]]
    assert [r.get("answer") for r in summarised(llm)] == [2, None, 1]  # asked order, the fallback at its query


def test_reads_on_a_hit_answer_before_the_create_and_come_out_in_asked_order(monkeypatch, fixtures_dir, memory):
    status, events, _, _, llm = run(
        monkeypatch, fixtures_dir, memory, "Vencidas, crea Ferretería Sur y pagadas",
        parse(VENCIDAS, {"op": "create", "entity": "clientes", "fields": {"NIT": "900555111-2", "Nombre": "Ferretería Sur"}},
              PAGADAS), {"text": "respuesta: 2; 1", "data": {}})
    assert status["status"] == "terminada"
    assert [r["op"] for r in summarised(llm)] == ["read", "create", "read"]
    assert [r.get("answer") for r in summarised(llm)][::2] == [2, 1]
    assert not any(e["event"] == "step" and e["args"] == ["facturas"] for e in events)  # no screen for the reads


def test_a_missed_entity_read_twice_costs_one_go_to(monkeypatch, fixtures_dir, memory):
    cache = Cache("SIGECOM · Distribuidora Andina", None, path=memory / "cache.sqlite")
    with cache.db:  # no change log: every `need` probes its entity on screen
        cache.db.execute("DELETE FROM sync_state WHERE role = 'changelog'")
    cache.db.close()
    clientes = {"op": "read", "entity": "clientes", "where": {}, "aggregate": "count"}
    bitacora = {"op": "read", "entity": "bitacora", "where": {}, "aggregate": "count"}
    status, events, *_ = run(monkeypatch, fixtures_dir, memory, "Clientes, cambios y clientes",
                             parse(clientes, bitacora, clientes), {"text": "respuesta: 2; 2; 2", "data": {}})
    assert status["status"] == "terminada"
    visits = [k for k, _ in groupby(e["args"][0] for e in events if e["event"] == "step" and e["tool"] == "go_to")]
    assert visits == ["clientes", "bitacora"]  # acquisition re-probes on the screen it is on; no second trip back
