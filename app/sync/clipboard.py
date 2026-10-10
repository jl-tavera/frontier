"""Clipboard acquirer (Appendix G §4.1 step 2, §4.4): select-all + copy, parse the tab-separated text.

`select_all_copy()`, `wait_clipboard(timeout) -> str | None` and the `paging()` fallback are injected,
so nothing here touches RFB or the agent. The wrapper F injects must arm RFB's `wait_clipboard` before
the copy keys go out: text that lands before the wait starts is ignored and would read as empty.
"""
from typing import Callable

from app.sync.cache import Cache, _norm
from app.sync.paging import ID_HEADERS, _typed_rows


def acquire_by_clipboard(entity: str, select_all_copy: Callable[[], None], wait_clipboard: Callable[[float], str | None],
                         cache: Cache, paging: Callable[[], str]) -> str:
    """Read the grid in one copy. Returns the cache's status, or the paging fallback's.

    Empty, unstructured or short text marks `clipboard=unusable` for this grid, so later reads go straight to paging.
    """
    if cache.unusable(entity, "clipboard"):
        return paging()
    select_all_copy()
    lines = [line for line in (wait_clipboard(3.0) or "").splitlines() if line.strip()]
    header = next((i for i, line in enumerate(lines) if "\t" in line), None)  # a caption may sit above the grid
    if header is None:
        reason = "unstructured" if lines else "empty"
    else:
        columns = [h.strip() for h in lines[header].split("\t")]
        rows = [dict(zip(columns, line.split("\t"))) for line in lines[header + 1:]]
        key = next((h for h in columns if _norm(h) in ID_HEADERS), None)
        if cache.acquire(entity, lambda: _typed_rows(columns, rows), key=key, source="clipboard") == "complete":
            return "complete"
        reason = "partial"  # e.g. only the visible rows were copied
    cache.mark_unusable(entity, "clipboard")
    cache._event("sync.fallback", entity=entity, method="clipboard", reason=reason, to="ocr")
    return paging()
