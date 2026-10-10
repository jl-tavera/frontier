import asyncio
import json
import shutil

from app.log import Log
from app.memory.appmap import AppMap
from app.memory.drift import FACTURAS, Drift, mutate

V39 = "SIGECOM · Distribuidora Andina   v3.9"
TREE = {("inicio", "Cartera"): "menu-cartera", ("menu-cartera", "Facturas"): "facturas",
        ("menu-cartera", "esc"): "inicio", ("facturas", "FV-10159"): "factura-detalle"}


def golden(fixtures_dir, tmp_path) -> AppMap:
    d = tmp_path / "memory" / "SIGECOM · Distribuidora Andina" / "v3.9"
    d.mkdir(parents=True)
    shutil.copy(fixtures_dir / "maps" / "golden_map.json", d / "map.json")
    return AppMap.load(tmp_path / "memory", V39)


def drift_lines(log: Log) -> list[dict]:
    lines = [json.loads(x) for x in log.path.read_text("utf-8").splitlines()] if log.path.exists() else []
    return [x for x in lines if x["event"] == "drift"]


def task(m, session, edge, tmp_path, *, decide=lambda els, old: (None, 0.0), vlm=lambda fb, els, old: (None, 0.0),
         live=lambda els: els):
    """One task: the start checks, then the step; returns the effect and every drift line logged so far."""
    log = Log(tmp_path / "drift.jsonl")
    drift = Drift(m, log, lambda fb: live(session.elements), decide=decide, vlm=vlm)
    drift.start(live(session.elements), session.w, session.h)
    effect = asyncio.run(drift.step(session, m.edges[edge]))
    return effect, drift_lines(log)


def test_rename_is_repaired_in_place_by_a_fuzzy_match(fixtures_dir, fake_app, tmp_path):
    m = golden(fixtures_dir, tmp_path)
    mutate(m, "rename")
    effect, lines = task(m, fake_app("inicio", TREE), FACTURAS, tmp_path)

    assert (effect.ok, effect.screen_id) == (True, "facturas")
    assert [(x["signal"], x["rung"], x["via"], x["before"], x["after"]) for x in lines] == [
        ("S1", 1, "fuzzy", "Facturación", "Facturas")]
    looks = m.edges[FACTURAS]["action"]["target"]["appearances"]
    assert [a["label"] for a in looks] == ["Facturas", "Facturación"]


def test_an_unrelated_rename_resolves_through_decide_when_it_is_sure_else_the_vlm(fixtures_dir, fake_app, tmp_path):
    asked = []
    vlm = lambda fb, els, old: asked.append(old["target"]["appearances"][0]["label"]) or (11, 0.7)  # Facturas
    for answer, via in [((11, 0.9), "decide"), ((11, 0.5), "vlm")]:
        m = golden(fixtures_dir, tmp_path / via)
        mutate(m, "removed")
        effect, lines = task(m, fake_app("inicio", TREE), FACTURAS, tmp_path / via, decide=lambda els, old: answer,
                             vlm=vlm)

        assert (effect.ok, effect.screen_id) == (True, "facturas")
        assert [(x["signal"], x["rung"], x["via"], x["confidence"], x["after"]) for x in lines] == [
            ("S1", 1, via, answer[1] if via == "decide" else 0.7, "Facturas")]
    assert asked == ["Zzzz"]  # the VLM only when decide was unsure, with the old action as the example


def test_a_landing_mismatch_retargets_the_edge(fixtures_dir, fake_app, tmp_path):
    m = golden(fixtures_dir, tmp_path)
    mutate(m, "landing_mismatch")
    effect, lines = task(m, fake_app("inicio", TREE), FACTURAS, tmp_path)

    assert (effect.signal, effect.screen_id) == ("S3", "facturas")
    assert [(x["signal"], x["rung"], x["before"], x["after"]) for x in lines] == [("S3", 1, "clientes", "facturas")]
    assert m.edges[FACTURAS]["to"] == "facturas" and m.edges[FACTURAS]["fail"] == 0


def test_a_persistent_break_is_ranked_down_every_task_never_deleted(fixtures_dir, fake_app, tmp_path):
    m = golden(fixtures_dir, tmp_path)
    mutate(m, "persistent")
    for _ in range(3):
        effect, lines = task(m, fake_app("inicio", TREE), FACTURAS, tmp_path)

    assert effect.signal == "S1" and not effect.ok
    assert [(x["signal"], x["rung"], x["via"], x["after"]) for x in lines] == [
        ("S1", rung, via, after) for n in (1, 2, 3) for rung, via, after in [(1, None, None), (4, "rank_down", n)]]
    assert m.edges[FACTURAS]["fail"] == 3 and m.edges[FACTURAS]["ok"] == 1


def test_a_shifted_cell_and_a_data_state_are_not_drift(fixtures_dir, fake_app, tmp_path):
    m = golden(fixtures_dir, tmp_path)
    mutate(m, "shifted_cell")
    effect, lines = task(m, fake_app("inicio", TREE), FACTURAS, tmp_path)
    assert (effect.ok, lines) == (True, [])

    live = mutate(m := golden(fixtures_dir, tmp_path / "data"), "data_state")
    effect, lines = task(m, fake_app("facturas", TREE), "facturas|click|FV-10159", tmp_path / "data", live=live)
    assert (effect.detail, lines) == ("find", [])  # page 2: the row is found by the find procedure, not repaired
    effect, lines = task(m, fake_app("inicio", TREE), FACTURAS, tmp_path / "data", live=live)
    assert (effect.ok, lines) == (True, [])


def test_task_start_flags_a_version_bump_and_a_silent_redesign(fixtures_dir, fake_app, tmp_path):
    for kind, signal in [("version_bump", "S5"), ("redesign", "S5"), ("redesign_silent", "S7")]:
        m = golden(fixtures_dir, tmp_path / kind)
        live = mutate(m, kind)
        _, lines = task(m, fake_app("inicio", TREE), FACTURAS, tmp_path / kind, live=live)
        assert lines[0]["signal"] == signal, kind


def test_three_unmatched_landings_in_one_task_are_mass_drift(fixtures_dir, fake_app, tmp_path):
    m = golden(fixtures_dir, tmp_path)
    mutate(m, "unknown_screen")
    log = Log(tmp_path / "drift.jsonl")
    at = {}  # each step starts back on Inicio
    drift = Drift(m, log, lambda fb: at["session"].elements, decide=None, vlm=None)
    for _ in range(3):
        at["session"] = fake_app("inicio", TREE)
        assert asyncio.run(drift.step(at["session"], m.edges[FACTURAS])).signal == "S4"
    assert [x["signal"] for x in drift_lines(log)] == ["S4", "S4", "S7", "S4"]


def test_a_click_that_changes_nothing_is_s2_not_a_retarget(fixtures_dir, fake_app, tmp_path):
    m = golden(fixtures_dir, tmp_path)
    dead = {k: v for k, v in TREE.items() if k != ("menu-cartera", "Facturas")} | {("menu-cartera", "Facturas"): "inicio"}
    effect, lines = task(m, fake_app("inicio", dead), FACTURAS, tmp_path)

    assert effect.signal == "S2"
    assert [(x["signal"], x["rung"]) for x in lines] == [("S2", 4)]
    assert (m.edges[FACTURAS]["to"], m.edges[FACTURAS]["fail"]) == ("facturas", 1)


def test_an_edge_that_leads_to_two_places_is_s6(fixtures_dir, fake_app, tmp_path):
    m = golden(fixtures_dir, tmp_path)
    m.edges[FACTURAS]["outcomes"]["clientes"] = 1
    effect, lines = task(m, fake_app("inicio", TREE), FACTURAS, tmp_path)

    assert effect.ok and [(x["signal"], x["after"]) for x in lines] == [("S6", ["facturas", "clientes"])]
