import asyncio
import json
import shutil

from app.contracts import Effect
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
    return [x for x in lines if x["event"] in ("drift", "rejoin")]


async def no_plan(m, edge, here):
    return None


def make(m, session, tmp_path, *, decide=lambda els, old: (None, 0.0), vlm=lambda fb, els, old: (None, 0.0),
         which_node=lambda fb, candidates: None, replan=no_plan, live=lambda els: els) -> Drift:
    return Drift(m, Log(tmp_path / "drift.jsonl"), lambda fb: live(session.elements), decide=decide, vlm=vlm,
                 which_node=which_node, replan=replan)


def run(drift, session, edge) -> Effect:
    """One task: the start checks (rung 0 may swap the map for a new epoch's), then the step on that map's edge."""
    async def go():
        await drift.start(session)
        return await drift.step(session, drift.m.edges[edge])
    return asyncio.run(go())


def task(m, session, edge, tmp_path, **kw):
    """`run`, returning the effect and every drift and rejoin line logged so far."""
    drift = make(m, session, tmp_path, **kw)
    return run(drift, session, edge), drift_lines(drift.log)


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
    for _ in range(3):
        effect, lines = task(m, fake_app("inicio", TREE), FACTURAS, tmp_path, live=mutate(m, "persistent"))

    assert effect.signal == "S1" and not effect.ok
    assert [(x["signal"], x["rung"], x["via"], x["after"]) for x in lines] == [
        ("S1", rung, via, after) for n in (1, 2, 3)
        for rung, via, after in [(1, None, None), (2, "reexplore", None), (3, "replan", None), (4, "rank_down", n)]]
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
    at = {}  # each step starts back on Inicio
    drift = Drift(m, Log(tmp_path / "drift.jsonl"), lambda fb: at["session"].elements, decide=None, vlm=None,
                  which_node=lambda fb, candidates: None, replan=no_plan)
    for _ in range(3):
        at["session"] = fake_app("inicio", TREE)
        assert asyncio.run(drift.step(at["session"], m.edges[FACTURAS])).signal == "S4"
    assert [(x["signal"], x["rung"]) for x in drift_lines(drift.log)] == [
        ("S4", 3), ("S4", 4), ("S4", 3), ("S4", 4), ("S7", 0), ("S4", 4)]
    assert drift.m.version == "epoch-1" and drift.m.nodes["inicio"]["stale"]
    assert (m.edges[FACTURAS]["fail"], drift.m.edges[FACTURAS]["fail"]) == (2, 3)  # the third on the new epoch's copy


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


def test_a_version_bump_opens_a_new_epoch_beside_the_old_one_with_no_edge_failures(fixtures_dir, fake_app, tmp_path):
    m = golden(fixtures_dir, tmp_path)
    old = (m.dir / "map.json").read_bytes()
    live = mutate(m, "version_bump")
    session = fake_app("inicio", TREE)
    effect = run(drift := make(m, session, tmp_path, live=live), session, FACTURAS)

    first = drift_lines(drift.log)[0]
    assert (first["signal"], first["rung"], first["before"], first["after"]) == ("S5", 0, "v3.9", "v4.0")
    assert drift.m.version == "v4.0" and (m.dir.parent / "v4.0" / "map.json").is_file()
    assert (m.dir / "map.json").read_bytes() == old
    assert (effect.ok, effect.screen_id) == (True, "facturas")
    assert all(e["fail"] == 0 for e in drift.m.edges.values())
    assert drift.m.edges[FACTURAS]["inherited"] is False  # the first confirmed landing verifies it


def test_a_redesign_is_rung_0_then_the_old_facturas_node_re_identified_then_rejoin(fixtures_dir, fake_app, tmp_path):
    for kind, signal, epoch in [("redesign", "S5", "v4.0"), ("redesign_silent", "S7", "epoch-1")]:
        m = golden(fixtures_dir, tmp_path / kind)
        live = mutate(m, kind)
        asked = []
        pick = lambda fb, candidates: asked.append([c["id"] for c in candidates]) or "facturas"
        session = fake_app("inicio", TREE)
        effect = run(drift := make(m, session, tmp_path / kind, live=live, which_node=pick), session, FACTURAS)
        lines = drift_lines(drift.log)

        assert [(x["event"], x["signal"], x.get("rung"), x.get("via"), x.get("after", x.get("node"))) for x in lines] == [
            ("drift", signal, 0, "inherit", epoch), ("drift", signal, 0, "reidentify", "facturas"),
            ("rejoin", signal, None, None, "facturas")], kind
        assert asked == [["facturas"]]  # the redesigned Inicio is too far from every stale node to ask about
        assert (effect.ok, effect.screen_id) == (True, "facturas")
        assert drift.m.version == epoch
        assert [a["version"] for a in drift.m.nodes["facturas"]["appearances"]] == [epoch, "v3.9"]
        session = fake_app("inicio", TREE)
        assert asyncio.run(make(drift.m, session, tmp_path / kind, live=live).start(session)) is None, kind  # once


def test_an_unknown_screen_is_s4_then_one_replan_then_rejoin_on_the_screen_esc_goes_back_to(fixtures_dir, fake_app, tmp_path):
    m = golden(fixtures_dir, tmp_path)
    mutate(m, "unknown_screen")
    asked = []

    async def replan(m, edge, here):
        asked.append((edge["broken"], here))
        return ["inicio|click|Comercial › Clientes"]
    session = fake_app("inicio", TREE | {("facturas", "esc"): "inicio"})
    effect, lines = task(m, session, FACTURAS, tmp_path, replan=replan)

    assert (effect.ok, effect.signal) == (False, "S4")
    assert [(x["event"], x["signal"], x.get("rung"), x.get("node")) for x in lines] == [
        ("drift", "S4", 3, None), ("drift", "S4", 4, None), ("rejoin", "S4", None, "inicio")]
    assert lines[0]["after"] == ["inicio|click|Comercial › Clientes"] and asked == [(True, "inicio")]
    assert session.keys == ["esc"]  # back off the unknown screen


def test_a_removed_target_is_found_again_by_rung_2(fixtures_dir, fake_app, tmp_path):
    m = golden(fixtures_dir, tmp_path)
    mutate(m, "removed")
    effect, lines = task(m, fake_app("inicio", TREE), FACTURAS, tmp_path)

    assert (effect.ok, effect.screen_id, effect.signal, effect.detail) == (True, "facturas", "S1", "rung 2 via reexplore")
    assert [(x["signal"], x["rung"], x["via"], x["before"], x["after"]) for x in lines] == [
        ("S1", 1, None, "Zzzz", None), ("S1", 2, "reexplore", "Zzzz", "Facturas")]
    assert m.edges[FACTURAS]["action"]["target"]["appearances"][0]["label"] == "Facturas"
    assert m.nodes["inicio"]["stale"] and m.edges[FACTURAS]["fail"] == 0


def test_a_menu_item_with_no_edge_left_is_re_added_by_rung_2(fixtures_dir, fake_app, tmp_path):
    m = golden(fixtures_dir, tmp_path)
    mutate(m, "menu_moved")
    assert FACTURAS not in m.edges
    session = fake_app("inicio", TREE)
    drift = make(m, session, tmp_path)
    found = asyncio.run(drift.rung2(session, "S1", "Facturas"))

    assert found is m.edges[FACTURAS] and found["to"] is None  # seen in its menu, its landing learned on first use
    assert [(x["rung"], x["via"], x["after"]) for x in drift_lines(drift.log)] == [(2, "reexplore", "Facturas")]
    assert asyncio.run(drift.step(session, found)).screen_id == "facturas" and found["to"] == "facturas"
