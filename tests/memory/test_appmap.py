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
