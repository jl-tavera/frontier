import asyncio
import json
import logging

import pytest

from app.contracts import Target
from app.memory.appmap import AppMap
from app.memory.fingerprint import fingerprint
from app.perception.ocr import elements
from app.warm.replay import observe, replay_edge
from tests.fakes.fake_app import FakeSession

V39 = "SIGECOM · Distribuidora Andina   v3.9"


_snapshot = {}  # lazy: hand-rolled module cache, as facturas_fb is function-scoped; a module fixture if conftest gets one


@pytest.fixture
def snapshot(facturas_fb):
    """facturas.png's elements, perceived once for the module."""
    if "els" not in _snapshot:
        _snapshot["els"] = elements(facturas_fb)
    return _snapshot["els"]


@pytest.fixture
def facturas_map(facturas_fb, snapshot, tmp_path):
    m = AppMap.load(tmp_path, V39)
    h, w = facturas_fb.shape[:2]
    m.upsert_node(fingerprint(snapshot, w, h), snapshot, facturas_fb)
    m.save()
    return m


class Counter:
    """A perceive that counts its calls and answers with fixed elements."""

    def __init__(self, els):
        self.els, self.calls = els, 0

    def __call__(self, fb):
        self.calls += 1
        return self.els


def one(els, text, kind):
    hits = [e for e in els if e.text == text and e.kind == kind]
    assert len(hits) == 1, hits
    return hits[0]


def test_same_frame_replays_the_snapshot_without_perceiving(facturas_fb, facturas_map, snapshot):
    perceive = Counter(snapshot)
    obs = observe(facturas_fb, facturas_map, perceive=perceive)
    assert (obs.source, obs.node, perceive.calls) == ("snapshot", "facturas", 0)
    assert one(obs.elements, "Buscar", "button").bbox == one(snapshot, "Buscar", "button").bbox


def erase(fb, b, pad=3):
    """Paint a bbox over with the colour just left of it."""
    x0, y0, x1, y1 = b
    fb[y0 - pad:y1 + pad + 1, x0 - pad:x1 + pad + 1] = fb[(y0 + y1) // 2, x0 - pad - 1]


def test_new_date_and_user_label_still_replay(facturas_fb, facturas_map, snapshot):
    user = next(e for e in snapshot if e.text.startswith("Hoy"))
    fb = facturas_fb.copy()
    erase(fb, user.bbox)
    perceive = Counter(snapshot)
    assert observe(fb, facturas_map, perceive=perceive).source == "snapshot" and perceive.calls == 0


def test_repainted_static_label_perceives(facturas_fb, facturas_map, snapshot, caplog):
    label = next(e for e in snapshot if e.text == "Cliente" and e.paired_input is not None)
    fb = facturas_fb.copy()
    erase(fb, label.bbox, pad=1)
    perceive = Counter(snapshot)
    with caplog.at_level(logging.INFO, "app.warm"):
        obs = observe(fb, facturas_map, perceive=perceive)
    assert (obs.source, obs.node, perceive.calls) == ("perception", "facturas", 1)
    assert "fastpath: miss:static_mismatch" in caplog.text


def test_button_shifted_30px_replays_the_moved_bbox(facturas_fb, facturas_map, snapshot, caplog):
    x0, y0, x1, y1 = one(snapshot, "Exportar", "button").bbox
    fb = facturas_fb.copy()
    button = fb[y0 - 4:y1 + 5, x0 - 4:x1 + 5].copy()
    erase(fb, (x0, y0, x1, y1), pad=4)
    fb[y0 - 4:y1 + 5, x0 + 26:x1 + 35] = button
    eid = facturas_map.upsert_edge("facturas", "click", Target("Exportar", "button", (0, 1)),
                                   ((x0 + x1) // 2, (y0 + y1) // 2), None)
    perceive = Counter(snapshot)
    with caplog.at_level(logging.INFO, "app.warm"):
        obs = observe(fb, facturas_map, perceive=perceive)
    assert (obs.source, perceive.calls) == ("snapshot", 0)
    assert facturas_map.edges[eid]["action"]["target"]["appearances"][0]["xy"] == [(x0 + x1) // 2 + 30, (y0 + y1) // 2]
    assert one(obs.elements, "Exportar", "button").bbox == (x0 + 30, y0, x1 + 30, y1)
    assert one(obs.elements, "Buscar", "button").bbox == one(snapshot, "Buscar", "button").bbox
    assert "fastpath: moved" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.INFO, "app.warm"):
        assert observe(fb, facturas_map, perceive=perceive).source == "snapshot"
    assert "fastpath: hit" in caplog.text and perceive.calls == 0  # the moved layout is now the stored one


def test_dropdown_open_is_a_miss_that_d1_calls_an_overlay(fake_app, tmp_path):
    m, base = AppMap.load(tmp_path, V39), fake_app("facturas", {})
    m.upsert_node(fingerprint(base.elements, base.w, base.h), base.elements, base.fb)
    open_ = fake_app("facturas-estado-open", {})
    obs = observe(open_.fb, m, perceive=Counter(open_.elements))
    assert (obs.source, obs.node, obs.match.kind, obs.match.node_id) == ("perception", None, "overlay", "facturas")


# replay_edge: Facturas --FV-10159--> Detalle de factura on FakeSession screens
STALE = 30  # px the link moves down in the "after" app


@pytest.fixture
def two_nodes(fake_app, tmp_path):
    """A saved 2-node map with the edge's last-good xy at the link's centre."""
    m = AppMap.load(tmp_path / "memory", V39)
    for name in ("facturas", "factura-detalle"):
        s = fake_app(name, {})
        m.upsert_node(fingerprint(s.elements, s.w, s.h), s.elements, s.fb)
    eid = m.upsert_edge("facturas", "click", Target("FV-10159", "link", (0, 2)), (83, 169), "detalle-de-factura")
    m.save()
    return m, eid


def moved_app(fixtures_dir, tmp_path):
    """Facturas with FV-10159 30 px lower and repainted, so its stored crop shows nowhere."""
    d = tmp_path / "moved"
    d.mkdir(exist_ok=True)
    for f in (fixtures_dir / "elements").glob("*.json"):
        els = json.loads(f.read_text("utf-8"))
        if f.stem == "facturas":
            link = next(e for e in els if e["text"] == "FV-10159")
            link["bbox"] = [link["bbox"][0], link["bbox"][1] + STALE, link["bbox"][2], link["bbox"][3] + STALE]
        (d / f.name).write_text(json.dumps(els, ensure_ascii=False), "utf-8")

    def start():
        s = FakeSession("facturas", {("facturas", "FV-10159"): "factura-detalle"}, d)
        x0, y0, x1, y1 = link["bbox"]
        s.fb[y0:y1 + 1, x0:x1 + 1, :3] = 7
        return s
    return start


def replay(m, eid, session, perceive):
    return asyncio.run(replay_edge(m.edges[eid], session.fb, session, m, perceive=perceive))


def test_replay_edge_with_a_good_xy_reaches_the_node_without_perceiving(two_nodes, fake_app, caplog):
    m, eid = two_nodes
    session = fake_app("facturas", {("facturas", "FV-10159"): "factura-detalle"})
    perceive = Counter([])
    with caplog.at_level(logging.INFO, "app.warm"):
        effect = replay(m, eid, session, perceive)
    assert (effect.ok, effect.screen_id, perceive.calls) == (True, "detalle-de-factura", 0)
    assert session.screen == "factura-detalle" and session.clicks == [(83, 169)]
    assert "fastpath: hit" in caplog.text


def test_stale_xy_perceives_once_repairs_and_then_replays(two_nodes, fixtures_dir, tmp_path, caplog):
    m, eid = two_nodes
    start = moved_app(fixtures_dir, tmp_path)
    session = start()
    perceive = Counter(session.elements)
    with caplog.at_level(logging.INFO, "app.warm"):
        effect = replay(m, eid, session, perceive)
    assert (effect.ok, effect.screen_id, session.screen, perceive.calls) == (True, "detalle-de-factura", "factura-detalle", 1)
    assert "fastpath: miss:target_missing" in caplog.text and "fastpath: repaired" in caplog.text
    saved = json.loads((m.dir / "map.json").read_text("utf-8"))
    assert saved["edges"][eid]["action"]["target"]["appearances"][0]["xy"] == [83, 169 + STALE]

    again = start()
    perceive = Counter([])
    caplog.clear()
    with caplog.at_level(logging.INFO, "app.warm"):
        effect = replay(m, eid, again, perceive)
    assert "fastpath: hit edge=FV-10159" in caplog.text
    assert (effect.ok, again.screen, perceive.calls) == (True, "factura-detalle", 0)
    assert again.clicks == [(83, 169 + STALE)]
