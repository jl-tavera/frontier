import json

from app.log import Log
from app.sync.cache import Cache
from app.sync.clipboard import acquire_by_clipboard

TSV = "Código\tCliente\tFecha\tValor\r\nF-0001\tCliente 1\t05/10/2026\t1.810.000\r\nF-0002\tCliente 2\t06/10/2026\t250.500,75\r\n"


class Grid:
    """A grid on screen: select-all + copy puts `text` on the clipboard; paging is the fallback rung."""

    def __init__(self, text):
        self.text, self.copies, self.pages = text, 0, 0

    def select_all_copy(self):
        self.copies += 1

    def wait_clipboard(self, timeout):
        return self.text

    def paging(self):
        self.pages += 1
        return "complete"


def acquire(cache, grid):
    return acquire_by_clipboard("facturas", grid.select_all_copy, grid.wait_clipboard, cache, grid.paging)


def cache_for(tmp_db, count=2):
    return Cache("sigecom", lambda entity: (count, "p1"), path=tmp_db, log=Log(tmp_db.parent / "t.jsonl"))


def events(cache):
    return [json.loads(line) for line in cache.log.path.read_text(encoding="utf-8").splitlines()]


def test_tsv_gives_typed_rows_keyed_by_the_header_line(tmp_db):
    cache, grid = cache_for(tmp_db), Grid("Facturas de venta\n" + TSV)  # a caption above the grid is not the header
    assert acquire(cache, grid) == "complete"
    rows = {r["Código"]: r for r in cache.need("facturas").rows}
    assert rows["F-0001"] == {"Código": "F-0001", "Cliente": "Cliente 1", "Fecha": "2026-10-05", "Valor": 1810000,
                              "_unparsed": []}
    assert rows["F-0002"]["Valor"] == 250500.75
    assert grid.pages == 0
    assert cache.query("SELECT source FROM rows LIMIT 1") == [("clipboard",)]


def test_empty_clipboard_falls_back_to_paging_and_is_remembered_for_the_grid(tmp_db):
    cache, grid = cache_for(tmp_db), Grid(None)
    assert acquire(cache, grid) == "complete"
    assert (grid.copies, grid.pages) == (1, 1)
    assert cache.unusable("facturas", "clipboard")
    assert not cache.unusable("clientes", "clipboard")
    fallback = [e for e in events(cache) if e["event"] == "sync.fallback"]
    assert [(e["method"], e["reason"], e["to"]) for e in fallback] == [("clipboard", "empty", "ocr")]

    grid.text = TSV  # even if it would copy now, a grid marked unusable goes straight to paging
    acquire(cache_for(tmp_db), grid)
    assert (grid.copies, grid.pages) == (1, 2)


def test_text_without_tabs_also_falls_back(tmp_db):
    cache, grid = cache_for(tmp_db), Grid("Facturas\nNo hay registros\n")
    assert acquire(cache, grid) == "complete"
    assert grid.pages == 1
    assert cache.unusable("facturas", "clipboard")
    assert [e["reason"] for e in events(cache) if e["event"] == "sync.fallback"] == ["unstructured"]


def test_a_copy_short_of_the_probe_count_falls_back_to_paging(tmp_db):
    cache, grid = cache_for(tmp_db, count=40), Grid(TSV)  # only the visible rows were copied
    assert acquire(cache, grid) == "complete"
    assert grid.pages == 1
    assert cache.unusable("facturas", "clipboard")
    assert [e["reason"] for e in events(cache) if e["event"] == "sync.fallback"] == ["partial"]
