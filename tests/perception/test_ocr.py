import unicodedata

from app.perception import ocr as perception

# Hand-read from tests/fixtures/screens/facturas.png: x0, y0, x1, y1 of each word's ink.
FACTURAS_LABELS = {
    "Buscar": (360, 124, 405, 137),
    "Limpiar": (442, 124, 491, 137),
    "Exportar": (27, 160, 83, 173),
    "Código": (21, 189, 66, 201),
    "Cliente": (171, 189, 216, 201),
    "Fecha": (604, 189, 642, 201),
    "Vence": (780, 189, 820, 201),
    "Valor": (956, 189, 989, 201),
    "Estado": (1115, 189, 1159, 201),
    "Siguiente": (177, 678, 239, 691),
}


def norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower().strip()


def near(a, b, tol=10) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def test_ocr_finds_facturas_labels_where_they_are(facturas_fb):
    lines = perception.ocr(facturas_fb)
    for label, rect in FACTURAS_LABELS.items():
        hits = [ln.bbox for ln in lines if norm(ln.text) == norm(label)]
        assert any(near(b, rect) for b in hits), f"{label}: {hits} not within 10 px of {rect}"


def test_second_read_of_a_screen_recognises_nothing(facturas_fb, monkeypatch):
    monkeypatch.setattr(perception, "_line_cache", {})
    first = perception.ocr(facturas_fb)
    assert perception.rec_calls > 100  # cold: ~146 lines on Facturas, minus repeated crops
    again = perception.ocr(facturas_fb)
    assert perception.rec_calls == 0
    assert again == first


def test_low_confidence_lines_are_flagged(facturas_fb):
    lines = perception.ocr(facturas_fb)
    # The mouse pointer over "Facturas" reads as a stray glyph at (205, 76).
    pointer = next(ln for ln in lines if near(ln.bbox, (205, 76, 221, 95)))
    buscar = next(ln for ln in lines if ln.text == "Buscar")
    assert pointer.conf < 0.8 and pointer.low_conf
    assert not buscar.low_conf

