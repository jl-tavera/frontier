"""Screen fingerprint (Appendix E §4.1): the title band as a hard key plus static label atoms on a 12×8 grid."""
import re
from dataclasses import dataclass

from app.contracts import BBox, Element

COLS, ROWS = 12, 8
STATIC = {"title", "menu", "button", "link", "header"}
_VERSION = re.compile(r"^(.*?)\s+(v\d+(?:\.\d+)*)$", re.I)


@dataclass(frozen=True)
class Fingerprint:
    app_id: str
    version: str | None
    band: tuple[str, ...]  # screen titles in the top 15 %, the hard key
    atoms: dict[str, tuple[float, float, float, float]]  # "col,row|text" -> normalised bbox
    menu: frozenset[str]  # the menu atoms, for adopting a rebranded app
    blocker: list[str] | None  # the dialog's buttons when a small centred dialog is up


def split_title(text: str) -> tuple[str, str | None]:
    """'SIGECOM · Distribuidora Andina   v3.9' -> ('SIGECOM · Distribuidora Andina', 'v3.9')."""
    text = " ".join(text.split())
    m = _VERSION.match(text)
    return (m[1], m[2]) if m else (text, None)


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 1.0


def _centre(b: BBox, w: int, h: int) -> tuple[float, float]:
    return (b[0] + b[2]) / 2 / w, (b[1] + b[3]) / 2 / h


def _blocker(elements: list[Element], w: int, h: int) -> list[str] | None:
    # lazy: "dialog" = 1–3 buttons in the middle box with no input there, so a screen whose only buttons sit
    # centred (an empty state) reads as a blocker; use a dialog box from C when it exists
    mid = [e for e in elements if all(0.25 <= c <= 0.75 for c in _centre(e.bbox, w, h))]
    buttons = [e.text for e in mid if e.kind == "button"]
    return buttons if 1 <= len(buttons) <= 3 and not any(e.kind in ("field", "select") for e in mid) else None


def fingerprint(elements: list[Element], w: int, h: int) -> Fingerprint:
    titles = sorted((e for e in elements if e.kind == "title"), key=lambda e: e.bbox[1])
    app_id, version = split_title(titles[0].text) if titles else ("", None)
    atoms, menu, band = {}, set(), []
    for e in elements:
        text = " ".join(e.text.split())
        static = e.kind in STATIC or (e.kind == "text" and e.paired_input is not None)  # field labels
        if not static or not text or any(c.isdigit() for c in text) or (titles and e is titles[0]):
            continue  # numbers, dates, codes, currency and the app title (it carries the version)
        cx, cy = _centre(e.bbox, w, h)
        atom = f"{min(int(cx * COLS), COLS - 1)},{min(int(cy * ROWS), ROWS - 1)}|{text}"
        atoms[atom] = (e.bbox[0] / w, e.bbox[1] / h, e.bbox[2] / w, e.bbox[3] / h)
        if e.kind == "menu":
            menu.add(atom)
        if e.kind == "title" and cy < 0.15:
            band.append(text)
    return Fingerprint(app_id, version, tuple(sorted(band)), atoms, frozenset(menu), _blocker(elements, w, h))
