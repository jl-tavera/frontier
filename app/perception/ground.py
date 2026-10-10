"""Grounding: a planner's Target to one Element by name, never by coordinates (Appendix H §4.3)."""
import io
import json
import unicodedata
from difflib import SequenceMatcher

from numpy import ndarray
from PIL import Image, ImageDraw, ImageFont

from app.contracts import Element, Target
from app.memory.fingerprint import cell

FUZZY = 0.8
MARK = (255, 0, 255)  # magenta: rare in business UIs, so marks stand apart from the screen


def _fold(s: str) -> str:
    """Case, accents and runs of whitespace don't count."""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _similar(a: str, b: str) -> float:
    """difflib ratio, or the best ratio of the shorter string against same-length windows of the longer one,
    so a stem matches its inflection: "facturas" ~ "facturac(ion)" scores 0.875 where the plain ratio is 0.74."""
    best = SequenceMatcher(None, a, b).ratio()
    short, long_ = sorted((a, b), key=len)
    # A window over a much longer text would find a 4-letter word inside any sentence; stems stay within ~30 %.
    if len(short) >= 4 and len(short) >= 0.7 * len(long_):
        best = max(best, *(SequenceMatcher(None, short, long_[i : i + len(short)]).ratio() for i in range(len(long_) - len(short) + 1)))
    return best


def ground(target: Target, elements: list[Element], w: int = 1280, h: int = 800) -> Element | None:
    """Exact label, then fuzzy label, then the only element of the target's role in its 12×8 cell."""
    # lazy: w, h default to the 1280×800 framebuffer; callers pass fb.shape once a second screen size shows up
    label = _fold(target.label)
    if label and (hits := [e for e in elements if _fold(e.text) == label]):
        return min(hits, key=lambda e: e.kind != target.role)
    scored = [(s, e) for e in elements if label and e.text and (s := _similar(label, _fold(e.text))) >= FUZZY]
    if scored:
        return min(scored, key=lambda se: (se[1].kind != target.role, -se[0]))[1]
    near = [e for e in elements if e.kind == target.role and cell(e.bbox, w, h) == tuple(target.cell)]
    # lazy: two candidates is a guess, so none wins; rank by distance to the label's last bbox if the planner keeps one
    return near[0] if len(near) == 1 else None


def elements_text(elements: list[Element]) -> str:
    """The default prompt view: `id kind "text"` per line, `-> id` on a label that names an input; no coordinates."""
    return "\n".join(
        f"{e.id} {e.kind} {json.dumps(e.text, ensure_ascii=False)}"
        + (f" -> {e.paired_input}" if e.paired_input is not None else "")
        for e in elements
    )


def som_image(fb: ndarray, elements: list[Element]) -> bytes:
    """Set-of-Mark PNG for new or unexpected screens: each element outlined, its id on a tag over its top-left."""
    img = Image.fromarray(fb[:, :, 2::-1])  # BGRX -> RGB
    draw, font = ImageDraw.Draw(img), ImageFont.load_default()
    for e in elements:
        x0, y0 = e.bbox[:2]
        draw.rectangle(e.bbox, outline=MARK, width=2)
        l, t, r, b = draw.textbbox((0, 0), str(e.id), font=font)
        tw, th = r - l + 4, b - t + 4
        ty = y0 - th if y0 >= th else y0  # above the box, or inside it at the top edge
        draw.rectangle((x0, ty, x0 + tw, ty + th), fill=MARK)
        draw.text((x0 + 2 - l, ty + 2 - t), str(e.id), fill="white", font=font)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
