"""OCR lines: detect once per screen, recognise each line crop once (Appendix H §4, §6)."""
import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from numpy import ndarray

from app.contracts import BBox, Element
from app.perception.tree import build

LATIN_REC = Path(__file__).parent / "models" / "latin_rec.onnx"
LOW_CONF = 0.8

# Frames are lossless and fonts fixed, so a line's pixels decide its text.
# lazy: in-memory, no eviction; a 5-minute task sees a few hundred lines.
_line_cache: dict[bytes, tuple[str, float]] = {}
rec_calls = 0  # line crops recognised by the last ocr() call


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

    # Classifier off: it flipped "Todos" → "sopol" (Appendix H §6).
    kw = {"rec_model_path": str(LATIN_REC)} if LATIN_REC.exists() else {}
    return RapidOCR(use_cls=False, **kw)


def ocr(fb: ndarray) -> list[Line]:
    engine = _engine()
    img = fb[:, :, :3].copy()  # BGRX → BGR, contiguous
    boxes, _ = engine.text_det(img)
    if boxes is None or len(boxes) == 0:
        return []
    boxes = engine.sorted_boxes(boxes)
    crops = engine.get_crop_img_list(img, boxes)
    keys = [hashlib.blake2b(c.tobytes() + str(c.shape).encode(), digest_size=16).digest() for c in crops]
    missing = {k: c for k, c in zip(keys, crops) if k not in _line_cache}
    global rec_calls
    rec_calls = len(missing)
    if missing:
        texts, _ = engine.text_rec(list(missing.values()))
        _line_cache.update((k, (text, float(conf))) for k, (text, conf) in zip(missing, texts))
    return [Line(text, _bbox(q), conf) for q, (text, conf) in zip(boxes, map(_line_cache.get, keys))]


def _bbox(quad: ndarray) -> BBox:
    """Axis-aligned, inclusive box around a detection quad."""
    (x0, y0), (x1, y1) = quad.min(axis=0).astype(int), quad.max(axis=0).astype(int)
    return int(x0), int(y0), int(x1), int(y1)


def elements(fb: ndarray) -> list[Element]:
    return build(fb, ocr(fb))
