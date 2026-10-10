import asyncio
import json
import logging

import pytest

from app.agent.tools import Tools
from app.contracts import Target
from app.memory.appmap import AppMap
from app.memory.fingerprint import fingerprint
from tests.fakes.fake_app import FakeSession

V39 = "SIGECOM · Distribuidora Andina   v3.9"
NAV = {("inicio", "Cartera"): "menu-cartera", ("menu-cartera", "Facturas"): "facturas"}
# The dropdown item, clear of the Inicio title and taller than any other box, so its crop shows only where it is
# (FakeSession paints flat boxes: a box of equal height would match too).
FACTURAS_ITEM = [180, 82, 380, 121]


class Counter:
    """A perceive that counts its calls (the rec_calls of these tests) and answers with the session's elements."""

    def __init__(self, session):
        self.session, self.calls = session, 0

    def __call__(self, fb):
        self.calls += 1
        return self.session.elements


def screens(fixtures_dir, tmp_path, shift=0):
    d = tmp_path / f"screens-{shift}"
    d.mkdir()
    for f in (fixtures_dir / "elements").glob("*.json"):
        els = json.loads(f.read_text("utf-8"))
        if f.stem == "menu-cartera":
            item = next(e for e in els if e["text"] == "Facturas")
            item["bbox"] = [FACTURAS_ITEM[0] + shift, FACTURAS_ITEM[1], FACTURAS_ITEM[2] + shift, FACTURAS_ITEM[3]]
        (d / f.name).write_text(json.dumps(els, ensure_ascii=False), "utf-8")
    return d


@pytest.fixture
def three_nodes(fixtures_dir, tmp_path):
    """inicio --Cartera--> menu-cartera --Facturas--> facturas, with snapshots, crops and edge xy."""
    d = screens(fixtures_dir, tmp_path)
    m = AppMap.load(tmp_path / "memory", V39)
    for name in ("inicio", "menu-cartera", "facturas"):
        s = FakeSession(name, {}, d)
        m.upsert_node(fingerprint(s.elements, s.w, s.h), s.elements, s.fb, name)
    m.upsert_edge("inicio", "click", Target("Cartera", "menu", (2, 0)), (215, 35), "menu-cartera")
    m.upsert_edge("menu-cartera", "click", Target("Facturas", "menu", (2, 1)), (280, 101), "facturas")
    m.save()
    return m, d


def tools(m, d, start, task=""):
    session = FakeSession(start, NAV, d)
    perceive = Counter(session)
    return Tools(session, m, task, perceive=perceive), session, perceive


def run(coro):
    return asyncio.run(coro)


def inside(xy, b):
    return b[0] <= xy[0] <= b[2] and b[1] <= xy[1] <= b[3]


def test_click_text_on_a_matching_snapshot_clicks_the_stored_bbox_without_perceiving(three_nodes):
    t, session, perceive = tools(*three_nodes, "menu-cartera")
    effect = run(t.click_text("Facturas"))
    assert (effect.ok, effect.screen_id, perceive.calls) == (True, "facturas", 0)
    assert len(session.clicks) == 1 and inside(session.clicks[0], FACTURAS_ITEM)


def test_click_text_on_a_button_shifted_30px_clicks_the_moved_bbox_without_perceiving(three_nodes, fixtures_dir, tmp_path, caplog):
    m, _ = three_nodes
    t, session, perceive = tools(m, screens(fixtures_dir, tmp_path, shift=30), "menu-cartera")
    with caplog.at_level(logging.INFO, "app.warm"):
        effect = run(t.click_text("Facturas"))
    assert (effect.ok, effect.screen_id, perceive.calls) == (True, "facturas", 0)
    assert session.clicks == [(280 + 30, 101)]  # the moved item's centre, not the stored one
    assert "fastpath: moved" in caplog.text


def test_click_text_on_an_unknown_label_is_an_s1_effect_after_perceiving(three_nodes):
    t, session, perceive = tools(*three_nodes, "menu-cartera")
    effect = run(t.click_text("Zzzz"))
    assert (effect.ok, effect.signal, perceive.calls, session.clicks) == (False, "S1", 1, [])


def test_fill_field_clicks_the_paired_input_then_types(three_nodes):
    t, session, _ = tools(*three_nodes, "facturas")
    effect = run(t.fill_field("Cliente", "Ruiz"))
    assert effect.ok and inside(session.clicks[0], (98, 90, 288, 108))  # the box, not the "Cliente" label
    assert session.keys == ["tab"] and session.typed == ["Ruiz"]  # no caret showed on the fake, so Tab first


def test_go_to_replays_the_stored_edges_at_their_xy(three_nodes):
    t, session, perceive = tools(*three_nodes, "inicio")
    effect = run(t.go_to("Facturas"))
    assert (effect.ok, effect.screen_id, session.screen, perceive.calls) == (True, "facturas", "facturas", 0)
    assert session.clicks == [(215, 35), (280, 101)]


def test_a_denylisted_label_is_refused_unless_the_task_names_it(three_nodes):
    m, d = three_nodes
    m.denylist.append("Facturas")
    t, session, _ = tools(m, d, "menu-cartera")
    effect = run(t.click_text("Facturas"))
    assert (effect.ok, session.clicks) == (False, []) and "denied" in effect.detail
    assert not run(t.click_text("Factura")).ok and session.clicks == []  # fuzzy-grounded onto the denied label

    t, session, _ = tools(m, d, "menu-cartera", task="Abre las facturas vencidas")
    assert run(t.click_text("Facturas")).ok and session.screen == "facturas"


def test_read_region_and_wait_for_read_the_perceived_screen(three_nodes):
    t, _, perceive = tools(*three_nodes, "facturas")
    assert run(t.read_region((160, 155, 960, 180))).detail == "Comercial Ruiz\n14/10/2026\n$ 1.250.000\nVencida"
    assert run(t.wait_for("Vencida", timeout=0)).ok
    assert not run(t.wait_for("Guardado", timeout=0)).ok
