"""UI tree from OCR lines + OpenCV boxes, by heuristics with no training (Appendix H §4.1)."""
from typing import TYPE_CHECKING

import cv2
import numpy as np
from numpy import ndarray

from app.contracts import BBox, Element, Kind

if TYPE_CHECKING:
    from app.perception.ocr import Line


def _inside(a: BBox, b: BBox, pad: int = 0) -> bool:
    return a[0] >= b[0] - pad and a[1] >= b[1] - pad and a[2] <= b[2] + pad and a[3] <= b[3] + pad


def _cy(b: BBox) -> float:
    return (b[1] + b[3]) / 2


def _centre_in(a: BBox, b: BBox) -> bool:
    return b[0] <= (a[0] + a[2]) / 2 <= b[2] and b[1] <= _cy(a) <= b[3]


def _height(b: BBox) -> int:
    return b[3] - b[1]


def boxes(fb: ndarray) -> tuple[list[BBox], list[BBox]]:
    """Bordered rectangles split by containment into (widgets, grid cells); containers and grid rows are dropped."""
    edges = cv2.Canny(cv2.cvtColor(fb[:, :, :3], cv2.COLOR_BGR2GRAY), 20, 60)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    rects = set()
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= 20 and h >= 12 and cv2.contourArea(c) > 0.8 * w * h:  # closed, axis-aligned
            rects.add((x, y, x + w - 1, y + h - 1))
    # A box hugging a slightly larger one is the same widget's inner border.
    rects = [r for r in rects if not any(o != r and _inside(r, o) and _inside(o, r, 2) for o in rects)]
    cells, parents = set(), set()
    for r in rects:
        for o in rects:
            if o != r and _inside(r, o):
                parents.add(o)
                if abs(_height(o) - _height(r)) <= 2:  # same-height parent: r is a grid cell, o its row
                    cells.add(r)
    return [r for r in rects if r not in cells | parents], sorted(cells, key=lambda r: (r[1], r[0]))


def _widget_kind(fb: ndarray, box: BBox, lines: list["Line"]) -> Kind | None:
    # lazy: white inputs and a dark ▾ as on SIGECOM; read the theme from a known field when a second app shows up
    x0, y0, x1, y1 = box
    bg = np.median(fb[y0 + 3 : y1 - 2, x0 + 3 : x1 - 2, :3].reshape(-1, 3), axis=0)
    arrow = fb[y0 + 3 : y1 - 2, x1 - 20 : x1 - 2, :3]
    if not any(ln.bbox[2] > x1 - 20 for ln in lines) and (np.abs(arrow.astype(int) - bg).sum(axis=2) > 200).any():
        return "select"  # ink in the right end that no text explains: the ▾
    if (bg >= 250).all():
        return "field"
    return "button" if lines else None  # lazy: an icon-only box is left to Spec F (raw x,y)


def _bands(fb: ndarray) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """(title bar, menu bar) as row spans: the first runs of rows with one background colour."""
    # lazy: assumes a title bar at the very top and a menu bar ≤ 40 px under it, as on SIGECOM, so an app without
    # them gets its first content band as "menu"; check the band's text is a row of short words when that happens
    med = np.median(fb[:160, :, :3], axis=1).astype(int)
    runs, start = [], 0
    for y in range(1, len(med) + 1):
        if y == len(med) or (np.abs(med[y] - med[start]) > 8).any():
            runs.append((start, y - 1))
            start = y
    runs = [r for r in runs if r[1] - r[0] >= 10]  # drop separator lines
    if not runs or runs[0][0] > 3:
        return None, None
    title, menu = runs[0], runs[1] if len(runs) > 1 else None
    if menu and (menu[0] - title[1] > 4 or menu[1] - menu[0] > 40):
        menu = None
    return title, menu


def _merge(lines: list["Line"]) -> list[tuple[str, BBox, float]]:
    """Gestalt: lines on the same row with a gap under half a line height are one text."""
    out: list[tuple[str, BBox, float]] = []
    for ln in sorted(lines, key=lambda ln: ln.bbox[0]):
        b = ln.bbox
        for i, (t2, b2, c2) in enumerate(out):
            overlap = min(b[3], b2[3]) - max(b[1], b2[1])
            if overlap > 0.5 * min(_height(b), _height(b2)) and 0 <= b[0] - b2[2] <= 0.5 * _height(b):
                out[i] = (f"{t2} {ln.text}", (b2[0], min(b[1], b2[1]), b[2], max(b[3], b2[3])), min(ln.conf, c2))
                break
        else:
            out.append((ln.text, b, ln.conf))
    return out


def _link(fb: ndarray, b: BBox) -> bool:
    """Blue ink with an underline: a row in the lower half that is mostly blue."""
    # lazy: "blue" is SIGECOM's default link colour; compare to the screen's other text colours if a theme differs
    crop = fb[b[1] : b[3] + 1, b[0] : b[2] + 1, :3].astype(int)
    blue = (crop[:, :, 0] > crop[:, :, 1] + 100) & (crop[:, :, 0] > crop[:, :, 2] + 100)
    return bool(blue[blue.shape[0] // 2 :].mean(axis=1).max(initial=0) > 0.6)


def _header(b: BBox, cells: list[BBox]) -> bool:
    """Text right above the top grid row, inside the grid's x span, is a column header."""
    x0, y0 = min(c[0] for c in cells), min(c[1] for c in cells)
    x1, rh = max(c[2] for c in cells), _height(cells[0])
    return x0 <= b[0] and b[2] <= x1 + 10 and y0 - 1.5 * rh <= _cy(b) < y0


def _reading_order(items: list[tuple[str, BBox, Kind, float]]) -> list[tuple[str, BBox, Kind, float]]:
    """Rows top to bottom, each left to right; a row is everything overlapping its first item's centre line."""
    rest, out = sorted(items, key=lambda t: _cy(t[1])), []
    while rest:
        cy = _cy(rest[0][1])
        row = [t for t in rest if t[1][1] <= cy <= t[1][3]]
        out += sorted(row, key=lambda t: t[1][0])
        rest = [t for t in rest if t not in row]
    return out


def _pair(els: list[Element]) -> None:
    """Each input takes the nearest free text above it or to its left as its label."""
    # lazy: greedy in reading order, so an earlier input can take a label a later one sits closer to;
    # assign by global nearest pairs when a dense form shows it
    labels = [e for e in els if e.kind == "text"]
    for box in (e for e in els if e.kind in ("field", "select")):
        bx0, by0, bx1, by1 = box.bbox
        best, gap = None, None
        for lab in labels:
            lx0, ly0, lx1, ly1 = lab.bbox
            if _cy(lab.bbox) < by0 and lx1 > bx0 and lx0 < bx1:  # above, overlapping in x
                d, limit = by0 - ly1, by1 - by0
            elif (lx0 + lx1) / 2 < bx0 and ly1 > by0 and ly0 < by1:  # left, overlapping in y
                d, limit = bx0 - lx1, 2 * (by1 - by0)
            else:
                continue
            if d <= limit and lab.paired_input is None and (gap is None or d < gap):
                best, gap = lab, d
        if best:
            best.paired_input = box.id


def build(fb: ndarray, lines: list["Line"]) -> list[Element]:
    widgets, cells = boxes(fb)
    title_band, menu_band = _bands(fb)
    items: list[tuple[str, BBox, Kind, float]] = []
    free = list(lines)
    for w in widgets:
        inner = [ln for ln in lines if _centre_in(ln.bbox, w)]
        if kind := _widget_kind(fb, w, inner):
            free = [ln for ln in free if ln not in inner]
            items.append((" ".join(ln.text for ln in inner), w, kind, min((ln.conf for ln in inner), default=1.0)))
    texts = _merge(free)

    def in_band(band):
        return [t for t in texts if band and band[0] <= _cy(t[1]) <= band[1]]

    menus = in_band(menu_band)
    # Titles: the title bar's leftmost text, and the page heading, the leftmost text of the first row under the bars.
    # lazy: a form with no heading gets its first label as title; check for bold ink when that bites
    below = [t for t in texts if _cy(t[1]) > (menu_band or title_band or (0, 0))[1]]
    first = min(below, key=lambda t: t[1][1], default=None)
    heading = first and min((t for t in below if t[1][1] <= _cy(first[1])), key=lambda t: t[1][0])
    titles = [min(in_band(title_band), key=lambda t: t[1][0], default=None), heading]
    for t in texts:
        text, b, conf = t
        kind: Kind = "text"
        if any(t is x for x in titles):
            kind = "title"
        elif t in menus:
            kind = "menu"
        elif _link(fb, b):
            kind = "link"
        elif any(_centre_in(b, c) for c in cells):
            kind = "cell"
        elif cells and _header(b, cells):
            kind = "header"
        items.append((text, b, kind, conf))
    els = [Element(i, text, bbox, kind, conf) for i, (text, bbox, kind, conf) in enumerate(_reading_order(items))]
    _pair(els)
    return els
