"""Grid: the header row names the columns, each repeated row below becomes a dict keyed by header text."""
from typing import NamedTuple

from numpy import ndarray

from app.perception.ocr import elements
from app.perception.tree import _cy


class Grid(NamedTuple):
    columns: list[str]
    rows: list[dict[str, str]]


def read_grid(fb: ndarray) -> Grid:
    els = elements(fb)
    headers = sorted((e for e in els if e.kind == "header"), key=lambda e: e.bbox[0])
    if not headers:
        return Grid([], [])
    columns = [h.text for h in headers]
    header_bottom = max(h.bbox[3] for h in headers)
    rows: list[dict[str, str]] = []
    row_y = None
    # elements() is in reading order: a row left to right, then the next row.
    # lazy: one line per cell; group by tree.boxes()' cell rectangles when a grid wraps text onto two lines
    for e in els:
        if e.kind not in ("cell", "link") or _cy(e.bbox) <= header_bottom:
            continue
        if row_y is None or _cy(e.bbox) > row_y:  # past the current row's band: a new row
            rows.append(dict.fromkeys(columns, ""))
            row_y = e.bbox[3]
        # Cells are left-aligned under their header: the last header starting left of the cell's centre.
        # lazy: a right-aligned column whose values overhang its header lands one column right; use cell boxes then
        cx = (e.bbox[0] + e.bbox[2]) / 2
        rows[-1][next((h.text for h in reversed(headers) if h.bbox[0] <= cx), columns[0])] = e.text
    return Grid(columns, rows)
