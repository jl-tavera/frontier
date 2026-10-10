from dataclasses import replace

import pytest

from app.memory.appmap import AppMap
from app.memory.fingerprint import fingerprint, split_title

W, H = 1258, 566
SCREENS = ["inicio", "facturas", "clientes", "pedidos", "bitacora", "reportes", "integraciones",
           "factura-detalle", "cliente-nuevo", "pedido-detalle"]
TITLE = "SIGECOM · Distribuidora Andina   v3.9"


@pytest.fixture
def screen(fake_app):
    return lambda name: fake_app(name, {}).elements


def scaled(elements, w, h):
    sx, sy = w / W, h / H
    return [replace(e, bbox=(round(e.bbox[0] * sx), round(e.bbox[1] * sy), round(e.bbox[2] * sx), round(e.bbox[3] * sy)))
            for e in elements]


def test_title_splits_into_app_and_version():
    assert split_title(TITLE) == ("SIGECOM · Distribuidora Andina", "v3.9")
    assert split_title("ACME ERP") == ("ACME ERP", None)


def test_fingerprint_keeps_static_labels_and_drops_data(screen):
    fp = fingerprint(screen("facturas"), W, H)
    texts = {a.split("|", 1)[1] for a in fp.atoms}
    assert (fp.app_id, fp.version, fp.band) == ("SIGECOM · Distribuidora Andina", "v3.9", ("Facturas",))
    assert {"Cartera", "Cliente", "Buscar", "Exportar", "Código", "Anterior"} <= texts
    assert not texts & {"FV-10159", "Comercial Ruiz", "Todos", "Página 1", TITLE}


def test_same_screen_rescaled_is_one_node_and_ten_screens_are_ten(screen, tmp_path):
    m = AppMap.load(tmp_path, TITLE)
    ids = []
    for name in SCREENS:
        fp = fingerprint(screen(name), W, H)
        assert m.identify(fp).kind == "new"
        ids.append(m.upsert_node(fp, screen(name)))
    assert len(set(ids)) == 10

    for name, nid in zip(SCREENS, ids):
        match = m.identify(fingerprint(scaled(screen(name), 1024, 640), 1024, 640))
        assert (match.kind, match.node_id, match.sim) == ("same", nid, 1.0)


def test_dropdown_open_is_an_overlay_of_its_node(screen, tmp_path):
    m = AppMap.load(tmp_path, TITLE)
    nid = m.upsert_node(fingerprint(screen("facturas"), W, H), screen("facturas"))
    match = m.identify(fingerprint(screen("facturas-estado-open"), W, H))
    assert (match.kind, match.node_id) == ("overlay", nid)
    assert match.labels == ["Todos", "Vencida", "Pendiente", "Pagada", "Anulada"]


@pytest.mark.parametrize("name, buttons", [("facturas-dialog", ["Aceptar", "Cancelar"]), ("acerca-de", ["Aceptar"])])
def test_centred_dialog_is_a_blocker_not_a_node(screen, tmp_path, name, buttons):
    m = AppMap.load(tmp_path, TITLE)
    m.upsert_node(fingerprint(screen("facturas"), W, H), screen("facturas"))
    match = m.identify(fingerprint(screen(name), W, H))
    assert (match.kind, match.node_id, match.labels) == ("blocker", None, buttons)


def test_centred_form_buttons_are_not_a_blocker(screen):
    assert fingerprint(screen("cliente-nuevo"), W, H).blocker is None


def test_partial_change_is_ambiguous_and_other_title_is_new(screen, tmp_path):
    m = AppMap.load(tmp_path, TITLE)
    nid = m.upsert_node(fingerprint(screen("facturas"), W, H), screen("facturas"))
    els = screen("facturas")
    renamed3 = {"Código", "Fecha", "Vence"}
    moved = [replace(e, text=e.text.upper()) if e.kind == "header" and e.text in renamed3 else e for e in els]  # 16/22
    match = m.identify(fingerprint(moved, W, H))
    assert match.kind == "ambiguous" and match.node_id == nid and 0.6 <= match.sim < 0.9

    renamed = [replace(e, text="Proveedores") if e.text == "Facturas" else e for e in els]  # same toolbar, other title
    assert m.identify(fingerprint(renamed, W, H)).kind == "new"
