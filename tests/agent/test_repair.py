import asyncio
import json
import shutil

import pytest

from app.agent import loop
from app.log import Log
from app.sync.cache import Cache
from tests.agent.test_loop import FACTURAS, Counter, parse, read_grid
from tests.fakes.fake_app import FakeSession
from tests.fakes.llm import FakeDecide, FakeLLM

APP = "SIGECOM · Distribuidora Andina"
TREE = {("inicio", "Cartera"): "menu-cartera", ("menu-cartera", "Facturas"): "facturas",
        ("menu-cartera", "esc"): "inicio", ("facturas", "esc"): "inicio"}
COUNT = parse({"op": "read", "entity": "facturas", "where": {"Estado": "Vencida"}, "aggregate": "count"})
SUMMARY = {"text": "respuesta: 2", "data": {"respuesta": 2}}


def memory(fixtures_dir, tmp_path):
    """The golden SIGECOM map, and a cache that already holds Facturas as the fake app shows it."""
    mem = tmp_path / "memory"
    (mem / APP / "v3.9").mkdir(parents=True)
    shutil.copy(fixtures_dir / "maps" / "golden_map.json", mem / APP / "v3.9" / "map.json")
    facturas = FakeSession("facturas", {}, fixtures_dir / "elements")
    cache = Cache(APP, {"facturas": loop.page_probe(read_grid(facturas)(facturas.fb))}.get, path=mem / "cache.sqlite")
    cache.acquire("facturas", lambda: FACTURAS, key="Código")
    cache.db.close()
    return mem


async def no_fallback(task, plan, ex):
    return {"ok": False, "detail": "F4"}


def run(fixtures_dir, tmp_path, kind, *replies, decide=None, tree=TREE, fallback=no_fallback):
    """`run_task` on the golden map with the E §6.1 mutation `kind`; returns (summary, drift/rejoin lines, llm)."""
    session = FakeSession("inicio", tree, fixtures_dir / "elements")
    llm, log = FakeLLM(*replies), Log(tmp_path / "task.jsonl")
    summary = asyncio.run(loop.run_task(
        "¿Cuántas facturas vencidas hay?", session, log, 60, llm=llm, memory=memory(fixtures_dir, tmp_path),
        perceive=Counter(session), read_grid=read_grid(session), fallback=fallback, mutate=kind,
        decide=decide or FakeDecide()))
    lines = [json.loads(x) for x in log.path.read_text("utf-8").splitlines()]
    return summary, [x for x in lines if x["event"] in ("drift", "rejoin")], llm


def jev(target, confidence):
    return {"target": (target, confidence), "effect_ok": (True, confidence), "drift": (1, confidence)}


def test_a_removed_item_is_found_by_jev_when_it_is_sure_and_the_vlm_is_never_asked(fixtures_dir, tmp_path):
    decide = FakeDecide(jev("11", 0.9))  # 11: Facturas in the open Cartera menu
    summary, lines, llm = run(fixtures_dir, tmp_path, "removed", COUNT, SUMMARY, decide=decide)

    assert (summary.status, summary.text) == ("terminada", "respuesta: 2")
    assert [(x["signal"], x["rung"], x["via"], x["confidence"]) for x in lines] == [("S1", 1, "decide", 0.9)]
    assert len(llm.calls) == 2  # parse and summary: no VLM
    state, questions = decide.calls[0]
    assert set(questions) == {"target", "effect_ok", "drift"} and "11" in questions["target"].criteria
    assert "Zzzz" in json.dumps(state, ensure_ascii=False)  # the old action is the few-shot


def test_the_same_item_reaches_the_vlm_over_the_som_image_when_jev_is_unsure(fixtures_dir, tmp_path):
    summary, lines, llm = run(fixtures_dir, tmp_path, "removed", COUNT, {"id": 11, "confidence": 0.7}, SUMMARY,
                              decide=FakeDecide(jev("11", 0.5)))

    assert summary.status == "terminada"
    assert [(x["signal"], x["rung"], x["via"], x["confidence"]) for x in lines] == [("S1", 1, "vlm", 0.7)]
    vlm = llm.calls[1]
    assert vlm["model"] == "test/vlm"
    assert vlm["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_an_unknown_screen_is_replanned_then_rejoins_and_f4_is_the_last_rung(fixtures_dir, tmp_path):
    handed = []

    async def fallback(task, plan, ex):
        handed.append([q.entity for q in plan.queries])
        return {"ok": False, "detail": "F4"}

    summary, lines, llm = run(fixtures_dir, tmp_path, "unknown_screen", COUNT, {"edges": None},
                              {"text": "no se pudo", "data": {}}, fallback=fallback)

    assert [(x["event"], x["signal"], x.get("rung"), x.get("node")) for x in lines] == [
        ("drift", "S4", 3, None), ("drift", "S4", 4, None), ("rejoin", "S4", None, "inicio")]
    assert llm.calls[1]["model"] == "test/planner"
    assert handed == [["facturas"]] and summary.status == "fallida"


def test_a_version_bump_opens_a_new_epoch_at_task_start_and_the_task_still_finishes(fixtures_dir, tmp_path):
    summary, lines, _ = run(fixtures_dir, tmp_path, "version_bump", COUNT, SUMMARY)

    assert (summary.status, summary.text) == ("terminada", "respuesta: 2")
    assert (lines[0]["signal"], lines[0]["rung"], lines[0]["before"], lines[0]["after"]) == ("S5", 0, "v3.9", "v4.0")
    assert (tmp_path / "memory" / APP / "v4.0" / "map.json").is_file()  # the new epoch is written back


def test_a_rename_is_repaired_in_place_before_any_model_is_asked(fixtures_dir, tmp_path):
    summary, lines, llm = run(fixtures_dir, tmp_path, "rename", COUNT, SUMMARY)

    assert summary.status == "terminada" and len(llm.calls) == 2
    assert [(x["signal"], x["rung"], x["via"]) for x in lines] == [("S1", 1, "fuzzy")]


@pytest.mark.parametrize("kind", ["rename", "removed", "persistent", "landing_mismatch", "menu_moved", "unknown_screen",
                                  "shifted_cell", "data_state", "version_bump", "redesign", "redesign_silent"])
def test_every_mutation_in_the_table_runs_through_the_executor_to_a_summary(fixtures_dir, tmp_path, kind):
    summary, *_ = run(fixtures_dir, tmp_path, kind, COUNT, *[{}] * 8)  # models that answer nothing useful
    assert "error:" not in summary.text, summary.text
