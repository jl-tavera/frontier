import json
from dataclasses import replace

import pytest

from app.contracts import Element
from app.memory.appmap import AppMap
from app.memory.fingerprint import fingerprint

W, H = 1258, 566
V39 = "SIGECOM · Distribuidora Andina   v3.9"
V40 = "SIGECOM · Distribuidora Andina   v4.0"


@pytest.fixture
def screen(fake_app):
    def load(name, title=None):
        return [replace(e, text=title) if title and e.id == 0 else e for e in fake_app(name, {}).elements]
    return load


def see(m, els, fb=None, node_id=None):
    return m.upsert_node(fingerprint(els, W, H), els, fb, node_id)


@pytest.fixture
def v39(screen, fake_app, tmp_path):
    """A saved v3.9 map: Inicio (root) and Facturas with ref PNGs and crops, one edge with its last-good xy."""
    m = AppMap.load(tmp_path, V39)
    inicio = see(m, screen("inicio"), fake_app("inicio", {}).fb)
    facturas = see(m, screen("facturas"), fake_app("facturas", {}).fb)
    m.edges["e1"] = {"from": inicio, "to": facturas, "effect": None, "ok": 3, "fail": 0, "last_ok": 1.0,
                     "outcomes": {facturas: 3},
                     "action": {"kind": "click", "params": {}, "target": {"appearances": [
                         {"version": "v3.9", "label": "Facturas", "role": "menu", "cell": [2, 0], "xy": [215, 35]}]}}}
    m.save()
    return m


def test_map_round_trips_with_edge_xy_and_appearance_version(v39, tmp_path):
    back = AppMap.load(tmp_path, V39)
    assert back.data() == json.loads(json.dumps(v39.data()))
    assert back.edges["e1"]["action"]["target"]["appearances"][0]["xy"] == [215, 35]
    assert back.nodes["facturas"]["appearances"][0]["version"] == "v3.9"
    assert back.root == "inicio" and "Integraciones" in back.denylist


def test_appearance_writes_ref_png_and_padded_static_crops(v39):
    a = v39.nodes["facturas"]["appearances"][0]
    assert v39.file(a, a["ref_png"]).is_file()
    crops = {c["file"]: c["bbox"] for c in a["crops"]}
    assert crops["facturas/12.png"] == [798, 86, 882, 112]  # Buscar [800, 88, 880, 110] padded 2 px
    assert "facturas/21.png" not in crops  # FV-10159 is data, not static
    assert all(v39.file(a, f).is_file() for f in crops)


def test_inherit_leaves_the_old_epoch_untouched(v39, tmp_path):
    before = (v39.dir / "map.json").read_bytes()
    new = v39.inherit(V40)

    assert new.dir == tmp_path / "SIGECOM · Distribuidora Andina" / "v4.0" and (new.dir / "map.json").is_file()
    assert all(n["stale"] for n in new.nodes.values()) and new.edges["e1"]["inherited"]
    assert new.edges["e1"]["action"]["target"]["appearances"][0]["xy"] == [215, 35]
    a = new.nodes["facturas"]["appearances"][0]
    assert a["version"] == "v3.9" and new.file(a, a["ref_png"]).is_file()  # still resolves into v3.9/

    assert (v39.dir / "map.json").read_bytes() == before
    old = AppMap.load(tmp_path, V39)
    assert old.version == "v3.9" and old.data() == json.loads(before)
    assert AppMap.load(tmp_path, V40).version == "v4.0"


def test_node_with_two_appearances_matches_either(v39, screen):
    new = v39.inherit(V40)
    redesigned = [replace(e, bbox=(e.bbox[0] + 600, *e.bbox[1:]) if e.kind in ("button", "header") else e.bbox)
                  for e in screen("facturas", V40)]
    assert new.identify(fingerprint(redesigned, W, H)).kind == "new"

    assert see(new, redesigned, node_id="facturas") == "facturas"
    assert [a["version"] for a in new.nodes["facturas"]["appearances"]] == ["v4.0", "v3.9"]
    for els in (redesigned, screen("facturas", V40)):
        match = new.identify(fingerprint(els, W, H))
        assert (match.kind, match.node_id) == ("same", "facturas")


def test_rebranded_title_with_same_menus_adopts_the_old_app(v39, screen, tmp_path):
    first = screen("inicio", "ANDINA ERP   v1.0")
    m = AppMap.load(tmp_path, "ANDINA ERP   v1.0", first, W, H)
    assert (m.app_id, m.version) == ("SIGECOM · Distribuidora Andina", "v1.0")
    assert m.edges["e1"]["inherited"] and m.nodes["facturas"]["stale"]
    assert AppMap.load(tmp_path, "ANDINA ERP   v1.0", first, W, H).dir == m.dir  # reloads, no second epoch

    other = [e for e in first if e.kind != "menu"] + [Element(99, "Ventas", (8, 26, 70, 44), "menu")]
    cold = AppMap.load(tmp_path, "OTRA APP v2", other, W, H)
    assert (cold.app_id, cold.nodes) == ("OTRA APP", {})


def test_load_opens_a_version_directory_saved_without_this_title(v39, tmp_path):
    v39.titles = []  # a committed map, say
    v39.save()
    assert AppMap.load(tmp_path, V39).dir == v39.dir


def test_both_ocr_readings_of_the_real_title_load_the_same_map(tmp_path):
    """Locally the title read with a spaced version, on Railway with it glued on; OCR also misreads a letter."""
    local = AppMap(tmp_path, "SIGEcoM·Distribuidora Andina", "V4.2")  # as the first local run saved it
    local.titles = ["SIGEcoM·Distribuidora Andina V4.2"]
    local.save()
    for reading in ("SIGEcoM·Distribuidora Andinav4.2", "SIGECOM · Distribuidora Andlna v4.2"):
        m = AppMap.load(tmp_path, reading)
        assert (m.dir, m.app_id, m.version) == (local.dir, local.app_id, local.version)
    assert AppMap.load(tmp_path, "CONTABILIDAD · Distribuidora Andina v4.2").dir != local.dir


def retitle(els, old, new):
    return [replace(e, text=new) if e.text == old and e.kind == "title" else e for e in els]


def test_a_title_band_misread_lands_on_the_stored_node(screen, tmp_path):
    m = AppMap.load(tmp_path, V39)
    inicio = m.locate(screen("inicio"), W, H)
    welcome = retitle(screen("inicio"), "Inicio", "Bienvenido a SIGECOM")
    home = m.locate(welcome, W, H)

    assert m.locate(retitle(screen("inicio"), "Inicio", "lnicio"), W, H) == inicio
    assert m.locate(retitle(welcome, "Bienvenido a SIGECOM", "BienvenidckaSIGECOM"), W, H) == home
    assert m.locate(screen("facturas"), W, H) == "facturas"
    assert m.locate(screen("pedidos"), W, H) == "pedidos" and len(m.nodes) == 4
    # a title a letter off over only part of a stored screen's atoms (here no grid) is another screen, not "ambiguous"
    other = [e for e in retitle(screen("pedidos"), "Pedidos", "Pedido") if e.kind != "header"]
    assert m.locate(other, W, H) == "pedido"


def test_a_misread_frame_never_overwrites_the_clean_snapshot(screen, tmp_path):
    m = AppMap.load(tmp_path, V39)
    m.locate(screen("inicio"), W, H)
    m.locate(retitle(screen("inicio"), "Inicio", "lnicio"), W, H)
    m.write_back()

    assert m.nodes["inicio"]["appearances"][0]["band"] == ["Inicio"]
