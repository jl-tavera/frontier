import json

import pytest

from app.perception.grid import read_grid
from tests.perception.test_ocr import norm

COLUMNS = ["Código", "Cliente", "Fecha", "Vence", "Valor", "Estado"]


# The live frame draws the header row as bordered boxes; it shows the same page 1, so the same golden.
@pytest.mark.parametrize("fb", ["facturas_fb", "facturas_live_fb"])
def test_facturas_grid_reads_as_rows_keyed_by_header(fb, fixtures_dir, request):
    # Golden rows are hand-written from facturas.png, in column order.
    golden = json.loads((fixtures_dir / "expected" / "facturas_page1.json").read_text(encoding="utf-8"))
    grid = read_grid(request.getfixturevalue(fb))
    assert [norm(c) for c in grid.columns] == [norm(c) for c in COLUMNS]
    assert [[norm(r[c]) for c in grid.columns] for r in grid.rows] == [[norm(v) for v in row] for row in golden]
