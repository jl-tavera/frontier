"""OCR lines: detect once per screen, recognise each line crop once (Appendix H §4, §6)."""
import hashlib
import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from numpy import ndarray

from app.contracts import BBox, Element
from app.perception.tree import build

LATIN_REC = Path(__file__).parent / "models" / "latin_rec.onnx"
LOW_CONF = 0.8
PAD = 64  # px of context around a changed region
JITTER = 2  # px a line's box moves when detected in a crop rather than the full frame
STABLE = {"title", "menu", "button", "link", "header"}  # as app/memory/fingerprint.py STATIC

# Frames are lossless and fonts fixed, so a line's pixels decide its text.
# lazy: in-memory, no eviction; a 5-minute task sees a few hundred lines.
_line_cache: dict[bytes, tuple[str, float]] = {}
rec_calls = 0  # line crops recognised by the last ocr() or elements() call
# Screen key -> (frame, lines, tree) of the last tree built for that screen.
# lazy: in-memory, no eviction, one tree per key; Spec W persists snapshots
_screens: dict[tuple[str, ...], tuple[ndarray, list["Line"], list[Element]]] = {}


@dataclass
class Line:
    text: str
    bbox: BBox
    conf: float

    @property
    def low_conf(self) -> bool:
        return self.conf < LOW_CONF


@cache
def _engine():
    from rapidocr_onnxruntime import RapidOCR

    # Classifier off: it flipped "Todos" → "sopol" (Appendix H §6). Limit "max" keeps a frame or region under
    # 1500 px at native scale; "min" upscales a small region to 736 px, ~2.5 s for one line (H §6).
    kw = {"rec_model_path": str(LATIN_REC)} if LATIN_REC.exists() else {}
    # The Dockerfile's OMP_NUM_THREADS caps onnxruntime too, which ignores it otherwise and sizes its pool to every
    # host CPU; on Railway's 48-CPU host a step ran ~10x slower than on a laptop (#88). Unset (a laptop) keeps the default.
    threads = int(os.environ.get("OMP_NUM_THREADS", -1))
    return RapidOCR(use_cls=False, det_limit_type="max", intra_op_num_threads=threads, **kw)


def ocr(fb: ndarray, region: BBox | None = None) -> list[Line]:
    """Every line on the frame; with a region, only the lines touching it, detected in a padded crop around it."""
    engine = _engine()
    img = fb[:, :, :3].copy()  # BGRX → BGR, contiguous
    x0 = y0 = 0
    x1 = y1 = None
    if region:  # padded for context, on the 32 px grid the detector strides on
        x0, y0 = (max(v - PAD, 0) // 32 * 32 for v in region[:2])
        x1, y1 = (-(-(v + PAD + 1) // 32) * 32 for v in region[2:])
    boxes, _ = engine.text_det(img[y0:y1, x0:x1].copy())
    if boxes is None or len(boxes) == 0:
        return []
    boxes = engine.sorted_boxes(boxes + np.array([x0, y0], boxes.dtype))
    if region:
        boxes = [q for q in boxes if _overlaps(_bbox(q), region)]
    crops = engine.get_crop_img_list(img, boxes)
    keys = [hashlib.blake2b(c.tobytes() + str(c.shape).encode(), digest_size=16).digest() for c in crops]
    missing = {k: c for k, c in zip(keys, crops) if k not in _line_cache}
    global rec_calls
    rec_calls = len(missing)
    if missing:
        texts, _ = engine.text_rec(list(missing.values()))
        _line_cache.update((k, (text, float(conf))) for k, (text, conf) in zip(missing, texts))
    return [Line(text, _bbox(q), conf) for q, (text, conf) in zip(boxes, map(_line_cache.get, keys))]


def _overlaps(a: BBox, b: BBox) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _bbox(quad: ndarray) -> BBox:
    """Axis-aligned, inclusive box around a detection quad."""
    (x0, y0), (x1, y1) = quad.min(axis=0).astype(int), quad.max(axis=0).astype(int)
    return int(x0), int(y0), int(x1), int(y1)


def screen_key(els: list[Element]) -> tuple[str, ...]:
    """The screen's stable texts: titles, menus, buttons, links, headers and field labels, never values (H §4.2)."""
    return tuple(sorted(e.text for e in els if e.kind in STABLE or e.paired_input is not None))


def elements(fb: ndarray, *, prev: list[Element] | None = None, changed_bbox: BBox | None = None) -> list[Element]:
    """The UI tree; given the previous tree and the changed region, only that region is detected and recognised."""
    global rec_calls
    known = prev is not None and _screens.get(screen_key(prev))
    if not known or known[2] != prev:  # a tree we did not build, or one since replaced under its key
        lines = ocr(fb)
    else:
        old_fb, old_lines, tree = known
        x0, y0, x1, y1 = changed_bbox or (0, 0, fb.shape[1] - 1, fb.shape[0] - 1)  # no region: any of it
        if np.array_equal(fb[y0 : y1 + 1, x0 : x1 + 1], old_fb[y0 : y1 + 1, x0 : x1 + 1]):
            rec_calls = 0
            return tree  # nothing changed where it was said to: the known screen, as built
        # Detection jitters a pixel or two with its crop, so the region grows by that much, then to whole old lines
        # touching it (a wide line cut at the crop edge would read short), and an old line touching a new one goes.
        # lazy: a line whose edge sits within the jitter of the region can still be dropped; widen JITTER if seen
        region = (x0 - JITTER, y0 - JITTER, x1 + JITTER, y1 + JITTER)
        for ln in old_lines:
            if _overlaps(ln.bbox, region):
                region = tuple(f(a, b) for f, a, b in zip((min, min, max, max), region, ln.bbox))
        new = ocr(fb, region)
        lines = [
            ln
            for ln in old_lines
            if not _overlaps(ln.bbox, region) and not any(_overlaps(ln.bbox, n.bbox) for n in new)
        ] + new
    els = build(fb, lines)
    # lazy: keeps a frame copy per screen (4 MB at 1280×800); store the line boxes' pixels if memory bites
    _screens[screen_key(els)] = (fb.copy(), lines, els)
    return els
