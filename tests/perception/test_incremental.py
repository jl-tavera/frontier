from app.perception import ocr as perception
from tests.perception.test_ocr import near, norm

overlaps = perception._overlaps

# Hand-read from facturas.png: the ink of "Ferreteria Ruiz", second grid row, Cliente column.
REGION = (168, 234, 299, 250)


def shape(els):
    """Elements without ids: ids follow reading order, so they shift when a region gains or loses one."""
    return [(e.text, e.bbox, e.kind, e.conf) for e in els]


def repainted(fb):
    x0, y0, x1, y1 = REGION
    out = fb.copy()
    out[y0 : y1 + 1, x0 : x1 + 1] = fb[240, 400]  # the cell's own background, right of the text
    return out


def test_only_the_changed_region_is_re_perceived(facturas_fb, monkeypatch):
    before = perception.elements(facturas_fb)
    after = perception.elements(repainted(facturas_fb), prev=before, changed_bbox=REGION)
    assert [e for e in shape(before) if not overlaps(e[1], REGION)] == [
        e for e in shape(after) if not overlaps(e[1], REGION)
    ]
    assert [norm(e.text) for e in before if overlaps(e.bbox, REGION)] == ["ferreteria ruiz"]
    assert [e.text for e in after if overlaps(e.bbox, REGION)] == []

    # Painting the text back with an empty line cache recognises no more than the region's lines.
    monkeypatch.setattr(perception, "_line_cache", {})
    back = perception.elements(facturas_fb, prev=after, changed_bbox=REGION)
    assert perception.rec_calls == 1  # "Ferreteria Ruiz" is the region's one line
    assert [(e.text, e.kind) for e in back] == [(e.text, e.kind) for e in before]
    # Detection on a crop can move a box a pixel or two against the full pass.
    assert all(near(a.bbox, b.bbox, 2) for a, b in zip(back, before))


def test_a_known_unchanged_screen_comes_from_the_screen_cache(facturas_fb, monkeypatch):
    before = perception.elements(facturas_fb)

    def no_build(*_):
        raise AssertionError("rebuilt a known screen")

    monkeypatch.setattr(perception, "build", no_build)
    monkeypatch.setattr(perception, "_line_cache", {})
    assert perception.elements(facturas_fb, prev=before, changed_bbox=REGION) == before
    assert perception.rec_calls == 0
    assert perception.elements(facturas_fb, prev=before) == before
