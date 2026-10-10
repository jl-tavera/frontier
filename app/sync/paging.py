"""OCR paging acquirer (Appendix G §4.1 step 3, §4.4): read a page, press Siguiente, repeat.

`read_grid() -> Grid(columns, rows)` and `click_next() -> bool` (False when the click had no effect) are injected,
so nothing here imports perception or the agent. The cache's own probe is the re-probe before the swap.
"""
import re
import time
from collections import Counter
from datetime import datetime
from typing import Any, Callable

from app.sync.cache import Cache, Rows, _norm, _sha

ID_HEADERS = {"id", "codigo", "numero", "nro", "no"}
# Colombian format: dot thousands, comma decimals. No leading zeros, so a code like 0042 stays text.
NUMBER = re.compile(r"-?\$?\s*(\d{1,3}(?:\.\d{3})+|0|[1-9]\d*)(?:,(\d+))?")


def _parse(cell: str) -> tuple[str, Any]:
    """(kind, value) with kind date | number | text."""
    try:
        return "date", datetime.strptime(cell, "%d/%m/%Y").date().isoformat()
    except ValueError:
        pass
    if m := NUMBER.fullmatch(cell):
        n = (float if m[2] else int)(m[1].replace(".", "") + (f".{m[2]}" if m[2] else ""))
        return "number", -n if cell.startswith("-") else n
    return "text", cell


def _typed_rows(columns: list[str], rows: Rows) -> Rows:
    """Each column takes the kind most of its cells parse as; a cell that doesn't fit is null + flagged, never guessed."""
    cells = [{h: _parse(str(r[h]).strip()) for h in columns if r.get(h) not in (None, "")} for r in rows]
    kinds = {h: Counter(c[h][0] for c in cells if h in c).most_common(1)[0][0] for h in columns if any(h in c for c in cells)}
    out = []
    for r, c in zip(rows, cells):
        bad = [h for h in c if kinds[h] != "text" and c[h][0] != kinds[h]]
        typed = {h: None for h in columns}
        for h, (_, value) in c.items():
            typed[h] = str(r[h]).strip() if kinds[h] == "text" else None if h in bad else value
        out.append({**typed, "_unparsed": bad})  # on every row, so the header hash doesn't move with the flags
    return out


def acquire_by_paging(entity: str, read_grid: Callable[[], Any], click_next: Callable[[], bool], cache: Cache,
                      budget_s: float = 60) -> str:
    """Page through the grid on screen into the cache. Returns the cache's status (`complete` / `partial`).

    Past `budget_s` it stops paging; a short read is never swapped and the task takes the targeted path (G §4.4).
    """
    deadline = time.monotonic() + budget_s
    columns, rows, seen = [], [], set()
    grid = read_grid()
    while (fp := _sha(grid.rows)) not in seen:  # a repeated page means Siguiente went nowhere new
        seen.add(fp)
        headers = {h: h.strip() for h in grid.columns}
        columns = columns or list(headers.values())
        rows += [{s: r.get(h) for h, s in headers.items()} for r in grid.rows]
        if time.monotonic() >= deadline:
            cache._event("sync.fallback", entity=entity, method="ocr", reason="budget", rows=len(rows), to="targeted")
            break  # what we have goes to the cache, which swaps it only if it matches the probe count
        if not click_next():
            break
        grid = read_grid()
    key = next((h for h in columns if _norm(h) in ID_HEADERS), None)
    return cache.acquire(entity, lambda: _typed_rows(columns, rows), key=key)
