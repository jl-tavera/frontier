import json
from collections import namedtuple

from app.log import Log
from app.sync.cache import Cache
from app.sync.paging import acquire_by_paging

Grid = namedtuple("Grid", "columns rows")  # C3's read_grid shape: rows keyed by header text
COLUMNS = ["Código", "Cliente", "Fecha", "Vence", "Valor", "Estado"]


def row(n, valor="1.810.000", fecha="05/10/2026"):
    return dict(zip(COLUMNS, (f"F-{n:04}", f"Cliente {n}", fecha, "04/11/2026", valor, "Pagada")))


# page 3 opens with page 2's last row: the grid shifted under us
PAGES = [
    Grid(COLUMNS, [row(1), row(2), row(3)]),
    Grid(COLUMNS, [row(4), row(5, valor="250.500,75"), row(6)]),
    Grid(COLUMNS, [row(6), row(7), row(8, valor="1.8l0.000")]),
]


class Pager:
    """A grid on screen: Siguiente moves one page and has no effect on the last."""

    def __init__(self, pages):
        self.pages, self.at, self.clicks = pages, 0, 0

    def read_grid(self):
        return self.pages[self.at]

    def click_next(self):
        self.clicks += 1
        if self.at == len(self.pages) - 1:
            return False
        self.at += 1
        return True


def acquire(tmp_db, pager=None, count=8, **kw):
    pager = pager or Pager(PAGES)
    log = Log(tmp_db.parent / "t.jsonl")
    cache = Cache("sigecom", lambda entity: (count, "p1"), path=tmp_db, log=log)
    status = acquire_by_paging("facturas", pager.read_grid, pager.click_next, cache, **kw)
    rows = cache.need("facturas").rows
    assert len(rows) == len({r["Código"] for r in rows})  # every row exactly once
    rows = {r["Código"]: r for r in rows}
    events = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
    return status, rows, events, pager


def test_three_pages_give_every_row_once_and_stop_on_the_last(tmp_db):
    status, rows, _, pager = acquire(tmp_db)
    assert status == "complete"
    assert sorted(rows) == [f"F-{n:04}" for n in range(1, 9)]
    assert pager.clicks == 3  # the third click had no effect, so the loop ended


def test_values_are_typed_colombian_money_and_iso_dates(tmp_db):
    _, rows, _, _ = acquire(tmp_db)
    assert rows["F-0001"]["Valor"] == 1810000
    assert rows["F-0005"]["Valor"] == 250500.75
    assert rows["F-0001"]["Fecha"] == "2026-10-05"
    assert rows["F-0001"]["Cliente"] == "Cliente 1"
    assert rows["F-0001"]["_unparsed"] == []


def test_unparseable_cell_is_null_with_a_flag(tmp_db):
    _, rows, _, _ = acquire(tmp_db)
    assert rows["F-0008"]["Valor"] is None
    assert rows["F-0008"]["_unparsed"] == ["Valor"]


def test_reprobe_before_the_swap_is_logged(tmp_db):
    _, _, events, _ = acquire(tmp_db)
    assert [(e["event"], e.get("scope"), e["outcome"]) for e in events[:2]] == [
        ("sync.probe", "entity", "hit"), ("sync.acquire", None, "complete")]


def test_out_of_budget_stops_and_keeps_the_short_read_out(tmp_db):
    status, rows, events, _ = acquire(tmp_db, budget_s=0)
    assert status == "partial" and rows == {}
    assert ("sync.fallback", "budget") in [(e["event"], e.get("reason")) for e in events]


def test_text_column_keeps_its_strings(tmp_db):
    pages = [Grid(COLUMNS, [{**row(n), "Cliente": c} for n, c in ((1, "Ana"), (2, "0042"), (3, "1000"))])]
    _, rows, _, _ = acquire(tmp_db, Pager(pages), count=3)
    assert [rows[f"F-000{n}"]["Cliente"] for n in (1, 2, 3)] == ["Ana", "0042", "1000"]
