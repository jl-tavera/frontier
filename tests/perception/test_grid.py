import json

from app.perception.grid import read_grid
from tests.perception.test_ocr import norm

COLUMNS = ["Código", "Cliente", "Fecha", "Vence", "Valor", "Estado"]


def test_facturas_grid_reads_as_rows_keyed_by_header(facturas_fb, fixtures_dir):
    # Golden rows are hand-written from facturas.png, in column order.
    golden = json.loads((fixtures_dir / "expected" / "facturas_page1.json").read_text(encoding="utf-8"))
    grid = read_grid(facturas_fb)
    assert [norm(c) for c in grid.columns] == [norm(c) for c in COLUMNS]
    assert [[norm(r[c]) for c in grid.columns] for r in grid.rows] == [[norm(v) for v in row] for row in golden]
