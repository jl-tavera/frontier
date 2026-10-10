from app.perception import ocr as perception
from tests.perception.test_ocr import near, norm


def one(els, text, kind=None):
    hits = [e for e in els if norm(e.text) == norm(text) and kind in (None, e.kind)]
    assert len(hits) == 1, f"{text!r} ({kind}): {[(e.text, e.kind, e.bbox) for e in hits]}"
    return hits[0]


def test_filter_row_labels_pair_with_their_inputs(facturas_fb):
    els = perception.elements(facturas_fb)
    by_id = {e.id: e for e in els}
    # Hand-read from facturas.png: the filter row's two inputs, outer border inclusive.
    cliente = by_id[one(els, "Cliente", "text").paired_input]
    estado = by_id[one(els, "Estado", "text").paired_input]
    assert cliente.kind == "field" and cliente.text == "" and near(cliente.bbox, (22, 120, 173, 142), 3)
    assert estado.kind == "select" and norm(estado.text) == "todos" and near(estado.bbox, (184, 120, 335, 142), 3)
    assert one(els, "Buscar").kind == "button"
    assert one(els, "Limpiar").kind == "button"
    assert one(els, "Exportar").kind == "button"


def test_kinds_from_bands_and_grid(facturas_fb):
    els = perception.elements(facturas_fb)
    app, page = [e for e in els if e.kind == "title"]
    # The title bar's text and its version read as one title; the date/user line on its right does not.
    assert norm(app.text).startswith("sigecom") and norm(app.text).endswith("3.9")
    assert page.text == "Facturas" and near(page.bbox, (14, 76, 91, 90))  # the page heading, as the fingerprint wants
    # Ids run in reading order: a row left to right, then the next row.
    assert [e.text for e in els if e.kind == "menu"] == ["Archivo", "Comercial", "Cartera", "Herramientas", "Ayuda"]
    assert [norm(e.text) for e in els if e.kind == "header"] == ["codigo", "cliente", "fecha", "vence", "valor", "estado"]
    assert one(els, "FV-10159").kind == "link"
    assert one(els, "01/03/2026", "cell")
    assert one(els, "Pagina 1").kind == "text"
