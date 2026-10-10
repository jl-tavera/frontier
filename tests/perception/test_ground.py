import json
from pathlib import Path

import cv2
import numpy as np

from app.contracts import Element, Target
from app.perception.ground import MARK, elements_text, ground, som_image

ELEMENTS = Path(__file__).parent.parent / "fixtures" / "elements"


def screen(name: str) -> list[Element]:
    return [Element(**{**e, "bbox": tuple(e["bbox"])}) for e in json.loads((ELEMENTS / f"{name}.json").read_text("utf-8"))]


def test_exact_label_resolves_to_its_button():
    els = screen("facturas")
    hit = ground(Target("buscar", "button", (0, 0)), els)
    assert (hit.id, hit.kind) == (12, "button")


def test_same_label_twice_resolves_to_the_target_role():
    els = screen("facturas")  # "Cliente" is both the filter label and a column header
    assert ground(Target("Cliente", "header", (0, 0)), els).id == 16
    assert ground(Target("Cliente", "text", (0, 0)), els).id == 8


def test_near_label_resolves_by_fuzzy_match():
    els = screen("menu-cartera")
    hit = ground(Target("Facturación", "menu", (0, 0)), els)
    assert hit.text == "Facturas"


def test_renamed_label_falls_back_to_the_one_same_role_element_in_its_cell():
    els = screen("facturas")
    # Buscar's centre (840, 99) on 1280×800 sits in cell (7, 0); Limpiar's (930, 99) in (8, 0).
    assert ground(Target("Consultar", "button", (7, 0)), els).text == "Buscar"
    assert ground(Target("Consultar", "field", (7, 0)), els) is None


def test_unknown_label_resolves_to_nothing():
    assert ground(Target("Proveedores", "button", (3, 6)), screen("facturas")) is None
    assert ground(Target("", "field", (3, 6)), screen("facturas")) is None  # not the first empty field
    # A word inside a long sentence is not a near label: "Sistema de gestión comercial: use el menú…"
    assert ground(Target("Gestion", "menu", (6, 6)), screen("menu-cartera")) is None


def test_elements_text_lists_every_element_by_id_kind_and_text():
    els = screen("facturas")
    lines = elements_text(els).splitlines()
    assert len(lines) == len(els)
    assert lines[8] == '8 text "Cliente" -> 9'
    assert lines[9] == '9 field ""'
    assert lines[12] == '12 button "Buscar"'


def test_som_image_draws_one_mark_per_element():
    fb = np.full((800, 1280, 4), 255, np.uint8)
    els = [Element(i, t, b, "button") for i, (t, b) in enumerate(
        [("Buscar", (800, 88, 880, 110)), ("", (98, 90, 288, 108)), ("Ayuda", (380, 300, 430, 318)), ("x", (1200, 700, 1270, 790))]
    )]
    png = som_image(fb, els)
    assert png.startswith(bytes.fromhex("89504e470d0a1a0a"))  # PNG signature
    rgb = cv2.cvtColor(cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    ink = (np.abs(rgb.astype(int) - MARK).sum(axis=2) < 30).astype(np.uint8)
    marks, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)  # outer only: a "0" hole isn't a mark
    assert len(marks) == len(els)
    for e in els:  # each mark outlines its element
        x0, y0, x1, y1 = e.bbox
        assert ink[y0:y1 + 1, x1].all() and ink[y1, x0:x1 + 1].all()
